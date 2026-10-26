"""Interfaz Streamlit del laboratorio FIR."""

from __future__ import annotations

from io import BytesIO
import zipfile

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from firlab.export_arduino import build_arduino_export, build_arduino_serial_export
from firlab.export_micropython import (
    build_micropython_impulse_export,
    build_micropython_serial_export,
)
from firlab.fir import (
    FIRConfiguration,
    accumulator_bound_bits,
    analyze_internal_precision,
    design_highpass,
    design_lowpass,
    frequency_response,
    recommend_output_format,
    simulate_fir,
    test_signal,
    trace_fir_sample,
)
from firlab.fixed_point import FixedFormat, OverflowMode, RoundingMode
from firlab.serial_protocol import SerialProtocolError, process_samples_sequentially


def _two_notations(format_: FixedFormat) -> str:
    """Muestra la notación Q explícita junto con la sintaxis de MATLAB."""
    return f"`{format_.q_notation}` (QI.QF) · `{format_.matlab_notation}`"


_PRODUCT_PRECISION_HELP = """
**¿Qué se calcula?** Se buscan los valores mínimo y máximo del producto exacto `p[k] = x[n-k]·h[k]`. Su escala natural siempre es `F_x + F_h`; por ello sus extremos, los valores raw y el `W mínimo` dependen solamente de los formatos de **Entrada** y **Coeficientes**, nunca del registro Producto que se elija después.

**Teórico:** se prueban las cuatro combinaciones de extremos permitidas por los formatos de entrada y coeficiente: `(x_min,h_min)`, `(x_min,h_max)`, `(x_max,h_min)` y `(x_max,h_max)`. Es seguro, pero puede ser muy pesimista: supone que cualquier coeficiente podría ocupar todo el rango de su formato.

**Con este FIR:** se cuantizan primero los coeficientes diseñados. Después, para cada tap, se multiplica ese `h[k] raw` por `x_min raw` y por `x_max raw`. El intervalo resultante es el máximo realista para **este filtro**, si cada muestra de entrada puede recorrer todo el rango del formato.

Abajo se comprueba por separado si el registro Producto elegido puede almacenar esa cota al recuantizarla a su F/QF. Ahí sí influyen sus W y F. Los números de la cota se muestran **antes** de saturar o hacer wrap.
"""


_ACCUMULATOR_PRECISION_HELP = """
**¿Qué se calcula?** Se acota la suma exacta `a = Σ[k=0…N−1] p[k]` en su escala natural `F_x + F_h`. No se está mirando una señal de prueba concreta: se está diseñando el ancho del registro para cualquier secuencia que quepa en el formato de entrada.

**Teórico:** se asume que los `N` productos pueden ser simultáneamente el mínimo, o simultáneamente el máximo, permitido por los formatos de entrada y coeficiente. Es la cota más conservadora; equivale a calcular `N·p_min` y `N·p_max` después de alinear el producto.

**Con este FIR:** para cada `h[k]` cuantizado se calcula su contribución mínima y máxima usando `x_min raw` o `x_max raw`. Luego se suman todos los mínimos y por separado todos los máximos. Esto conserva el peor caso de una FIR: cada retardo `x[n-k]` puede tomar independientemente un extremo distinto.

Abajo se comprueba por separado si el acumulador elegido puede almacenar esa suma al recuantizarla a su F/QF. Al igual que en Producto, las cotas aparecen **antes** de saturar o hacer wrap. Si la fila dice que no cabe, la política de overflow seleccionada cambiaría el resultado cuando ocurra ese caso límite.
"""


def _precision_summary_rows(theoretical, actual, theoretical_in_register, actual_in_register) -> pd.DataFrame:
    """Convierte dos cotas raw a una tabla legible y homogénea."""
    return pd.DataFrame(
        [
            {
                "caso": "Teórico (formatos)",
                "mínimo raw": theoretical.raw_min,
                "mínimo real": theoretical.minimum,
                "máximo raw": theoretical.raw_max,
                "máximo real": theoretical.maximum,
                "W mínimo": theoretical.required_word_length,
                "¿cabe en registro elegido?": "Sí" if theoretical_in_register.fits_destination else "No",
            },
            {
                "caso": "Este FIR (h[k] cuantizado)",
                "mínimo raw": actual.raw_min,
                "mínimo real": actual.minimum,
                "máximo raw": actual.raw_max,
                "máximo real": actual.maximum,
                "W mínimo": actual.required_word_length,
                "¿cabe en registro elegido?": "Sí" if actual_in_register.fits_destination else "No",
            },
        ]
    )


def _product_witness_caption(label: str, range_) -> str:
    """Explica las dos combinaciones que alcanzan los extremos de Producto."""
    minimum = range_.min_witness
    maximum = range_.max_witness
    return (
        f"{label}: mínimo con x raw = {minimum.input_raw}, h raw = {minimum.coefficient_raw} "
        f"→ {minimum.raw}; máximo con x raw = {maximum.input_raw}, h raw = {maximum.coefficient_raw} "
        f"→ {maximum.raw}."
    )


def _two_series_chart(
    data: pd.DataFrame,
    x_field: str,
    x_title: str,
    ideal_field: str,
    ideal_title: str,
    quantized_field: str,
    quantized_title: str,
    y_title: str,
) -> alt.Chart:
    """Dos curvas con un tooltip que muestra los dos valores en la misma x."""
    tooltip = [
        alt.Tooltip(f"{x_field}:Q", title=x_title, format=".3f"),
        alt.Tooltip(f"{ideal_field}:Q", title=ideal_title, format=".4f"),
        alt.Tooltip(f"{quantized_field}:Q", title=quantized_title, format=".4f"),
    ]
    base = alt.Chart(data).transform_fold(
        [ideal_field, quantized_field], as_=["serie", "valor"]
    ).encode(
        x=alt.X(f"{x_field}:Q", title=x_title),
        y=alt.Y("valor:Q", title=y_title),
        color=alt.Color(
            "serie:N",
            title="Curva",
            scale=alt.Scale(
                domain=[ideal_field, quantized_field],
                range=["#5DADE2", "#F5B041"],
            ),
            legend=alt.Legend(
                labelExpr=f"datum.label === '{ideal_field}' ? '{ideal_title}' : '{quantized_title}'"
            ),
        ),
        tooltip=tooltip,
    )
    return base.mark_line(strokeWidth=2).properties(height=300).configure_view(strokeWidth=0)


def _signal_chart(data: pd.DataFrame) -> alt.Chart:
    """Entrada, respuesta ideal y respuesta de punto fijo en una sola lectura."""
    labels = {
        "entrada": "Entrada",
        "salida_ideal": "Salida ideal",
        "salida_cuantizada": "Salida cuantizada",
    }
    tooltip = [
        alt.Tooltip("n:Q", title="Muestra n", format=".0f"),
        alt.Tooltip("entrada:Q", title="Entrada", format=".6g"),
        alt.Tooltip("salida_ideal:Q", title="Salida ideal", format=".6g"),
        alt.Tooltip("salida_cuantizada:Q", title="Salida cuantizada", format=".6g"),
        alt.Tooltip("error:Q", title="Error (cuantizada − ideal)", format=".3g"),
    ]
    return (
        alt.Chart(data)
        .transform_fold(list(labels), as_=["serie", "valor"])
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("n:Q", title="Muestra n"),
            y=alt.Y("valor:Q", title="Amplitud"),
            color=alt.Color(
                "serie:N",
                title="Curva",
                scale=alt.Scale(
                    domain=list(labels), range=["#AAB7B8", "#5DADE2", "#F5B041"]
                ),
                legend=alt.Legend(
                    labelExpr=(
                        "datum.label === 'entrada' ? 'Entrada' : "
                        "datum.label === 'salida_ideal' ? 'Salida ideal' : 'Salida cuantizada'"
                    )
                ),
            ),
            tooltip=tooltip,
        )
        .properties(height=300)
        .configure_view(strokeWidth=0)
    )


_EXAMPLES: dict[str, dict[str, object]] = {
    "Q1.15": {
        "Entrada x[n]-signed": True,
        "Entrada x[n]-w": 16,
        "Entrada x[n]-f": 15,
        "Coeficientes h[k]-signed": True,
        "Coeficientes h[k]-w": 16,
        "Coeficientes h[k]-f": 15,
        "Salida y[n]-signed": True,
        "Salida y[n]-w": 16,
        "Salida y[n]-f": 15,
        "customize-internal": False,
        "rounding-mode": RoundingMode.NEAREST.value,
        "overflow-mode": OverflowMode.SATURATE.value,
        "signal-kind": "Coseno",
        "signal-amplitude": 0.8,
    },
    "Pocos bits": {
        "Entrada x[n]-signed": True,
        "Entrada x[n]-w": 8,
        "Entrada x[n]-f": 5,
        "Coeficientes h[k]-signed": True,
        "Coeficientes h[k]-w": 8,
        "Coeficientes h[k]-f": 5,
        "Salida y[n]-signed": True,
        "Salida y[n]-w": 8,
        "Salida y[n]-f": 5,
        "customize-internal": False,
        "rounding-mode": RoundingMode.NEAREST.value,
        "overflow-mode": OverflowMode.SATURATE.value,
        "signal-kind": "Coseno",
        "signal-amplitude": 0.8,
    },
    "Saturación": {
        "Entrada x[n]-signed": True,
        "Entrada x[n]-w": 4,
        "Entrada x[n]-f": 0,
        "Coeficientes h[k]-signed": True,
        "Coeficientes h[k]-w": 8,
        "Coeficientes h[k]-f": 7,
        "Salida y[n]-signed": True,
        "Salida y[n]-w": 4,
        "Salida y[n]-f": 3,
        "customize-internal": False,
        "rounding-mode": RoundingMode.NEAREST.value,
        "overflow-mode": OverflowMode.SATURATE.value,
        "signal-kind": "Paso",
        "signal-amplitude": 7.0,
    },
    "Wrap": {
        "Entrada x[n]-signed": True,
        "Entrada x[n]-w": 4,
        "Entrada x[n]-f": 0,
        "Coeficientes h[k]-signed": True,
        "Coeficientes h[k]-w": 8,
        "Coeficientes h[k]-f": 7,
        "Salida y[n]-signed": True,
        "Salida y[n]-w": 4,
        "Salida y[n]-f": 3,
        "customize-internal": False,
        "rounding-mode": RoundingMode.NEAREST.value,
        "overflow-mode": OverflowMode.WRAP.value,
        "signal-kind": "Paso",
        "signal-amplitude": 7.0,
    },
    "Todo sin signo": {
        "design-mode": "Media móvil",
        "Entrada x[n]-signed": False,
        "Entrada x[n]-w": 16,
        "Entrada x[n]-f": 16,
        "Coeficientes h[k]-signed": False,
        "Coeficientes h[k]-w": 16,
        "Coeficientes h[k]-f": 16,
        "Salida y[n]-signed": False,
        "Salida y[n]-w": 16,
        "Salida y[n]-f": 16,
        "customize-internal": False,
        "rounding-mode": RoundingMode.NEAREST.value,
        "overflow-mode": OverflowMode.SATURATE.value,
        "signal-kind": "Coseno",
        "signal-amplitude": 0.4,
    },
}


def _load_example(name: str) -> None:
    """Carga un caso corto antes de que Streamlit vuelva a crear los widgets."""
    st.session_state.update(_EXAMPLES[name])


def _clamp_format_fraction(title: str, max_word_length: int) -> None:
    """Mantiene F válido antes del siguiente render de los widgets asociados.

    Los callbacks se ejecutan antes del rerun de Streamlit. Esto evita que un
    ``number_input`` de F conserve visualmente un valor que ya no cabe después
    de reducir W o de activar el bit de signo.
    """
    signed_key = f"{title}-signed"
    word_key = f"{title}-w"
    fraction_key = f"{title}-f"
    if word_key not in st.session_state or fraction_key not in st.session_state:
        return
    word = min(int(st.session_state[word_key]), max_word_length)
    maximum_fraction = word - int(bool(st.session_state.get(signed_key, True)))
    st.session_state[fraction_key] = min(int(st.session_state[fraction_key]), maximum_fraction)


def _clamp_frequencies_for_sample_rate() -> None:
    """Mantiene Fc y la frecuencia del coseno dentro del nuevo Nyquist."""
    sample_rate = float(st.session_state.get("sample-rate", 1_000.0))
    cutoff_key = "cutoff-hz"
    maximum_cutoff = sample_rate / 2 - 0.001
    if cutoff_key in st.session_state and not 0.01 <= float(st.session_state[cutoff_key]) <= maximum_cutoff:
        # Fs/4 deja margen a ambos lados y es una referencia didáctica simple.
        st.session_state[cutoff_key] = sample_rate / 4
    signal_frequency_key = "signal-frequency"
    if signal_frequency_key in st.session_state and not 0.0 <= float(st.session_state[signal_frequency_key]) <= sample_rate / 2:
        st.session_state[signal_frequency_key] = sample_rate / 4


def _format_editor(
    title: str,
    defaults: tuple[bool, int, int],
    *,
    max_word_length: int = 32,
) -> FixedFormat:
    st.subheader(title)
    signed_key = f"{title}-signed"
    signed_options = {} if signed_key in st.session_state else {"value": defaults[0]}
    signed = st.checkbox(
        "Con signo",
        key=signed_key,
        on_change=_clamp_format_fraction,
        args=(title, max_word_length),
        **signed_options,
    )
    left, right = st.columns(2)
    word_key = f"{title}-w"
    # Los formatos externos se limitan a 32 bits para Arduino; los internos
    # pueden requerir más (por ejemplo, W=38 en el acumulador por defecto).
    if word_key in st.session_state and int(st.session_state[word_key]) > max_word_length:
        st.session_state[word_key] = max_word_length
    word_options = {} if word_key in st.session_state else {"value": min(defaults[1], max_word_length)}
    word = left.number_input(
        "W — bits totales",
        min_value=1,
        max_value=max_word_length,
        key=word_key,
        on_change=_clamp_format_fraction,
        args=(title, max_word_length),
        **word_options,
    )
    maximum_fraction = int(word) - int(signed)
    fraction_key = f"{title}-f"
    # Protección para valores cargados por un preset o una sesión anterior.
    # Durante una interacción normal el callback de W o de signo ya hizo este
    # ajuste antes de que se renderice F.
    _clamp_format_fraction(title, max_word_length)
    fraction_options = {} if fraction_key in st.session_state else {"value": min(defaults[2], maximum_fraction)}
    fraction = right.number_input(
        "F / QF — bits fraccionarios",
        min_value=0,
        max_value=maximum_fraction,
        key=fraction_key,
        **fraction_options,
    )
    try:
        result = FixedFormat(signed, int(word), int(fraction))
        st.caption(f"Notaciones: {_two_notations(result)}")
        st.caption(f"Rango: [{result.minimum:g}, {result.maximum:g}] · LSB: {result.lsb:g}")
        return result
    except ValueError as error:
        st.error(str(error))
        return FixedFormat(True, 16, 15)


def _zip_export(header: str, sketch: str, runtime: str, sketch_name: str) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("fir_config.h", header)
        archive.writestr(sketch_name, sketch)
        archive.writestr("FIRFixed.h", runtime)
    return output.getvalue()


def _zip_micropython_export(export) -> bytes:
    """Empaqueta los tres archivos que deben copiarse juntos en la Pico."""
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("main.py", export.main)
        archive.writestr("fir_config.py", export.config)
        archive.writestr("fir_fixed.py", export.runtime)
    return output.getvalue()


def _serial_ports() -> list[tuple[str, str]]:
    """Devuelve puertos seriales sin impedir usar el laboratorio sin pyserial."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [(port.device, port.description or port.device) for port in list_ports.comports()]


def _render_serial_hardware_test(
    input_raw: np.ndarray,
    python_output_raw: np.ndarray,
    input_format: FixedFormat,
    output_format: FixedFormat,
) -> None:
    """Ofrece una validación uno-a-uno contra el programa serial exportado."""
    st.header("Prueba en hardware por puerto serial")
    st.warning(
        "Cierra Arduino IDE, Serial Monitor, Serial Plotter, Thonny u otro terminal antes de usar este puerto. "
        "Sólo una aplicación puede abrirlo a la vez.",
        title="Libera el puerto serial",
    )
    st.caption(
        "Carga primero `FIRFixedSerial.ino` en Arduino o los archivos de `FIRPicoSerial.zip` "
        "en una tarjeta MicroPython. La aplicación envía un `x_raw`, espera su respuesta "
        "`x_raw,y_raw` y sólo entonces envía la siguiente muestra. También envía `RESET`, "
        "por lo que el hardware y la simulación parten con retardos en cero."
    )
    ports = _serial_ports()
    if not ports:
        st.info(
            "No se detectó un puerto serial. Conecta la tarjeta por USB y vuelve a cargar la página. "
            "Si el módulo falta, instala las dependencias del proyecto para incluir pyserial."
        )
        return

    port_names = [name for name, _ in ports]
    descriptions = {name: description for name, description in ports}
    selected_port = st.selectbox(
        "Puerto de la tarjeta",
        port_names,
        format_func=lambda name: f"{name} — {descriptions[name]}",
        key="arduino-serial-port",
    )
    if not st.button(
        f"Enviar {len(input_raw)} muestras y comparar",
        key="send-to-arduino",
        width="stretch",
    ):
        return

    progress = st.progress(0, text="Abriendo el puerto y esperando el reinicio de la tarjeta…")

    def update_progress(completed: int, total: int) -> None:
        progress.progress(
            completed / total,
            text=f"El hardware procesó {completed} de {total} muestras (una petición, una respuesta).",
        )

    try:
        hardware_output_raw = process_samples_sequentially(
            selected_port,
            input_raw,
            on_sample=update_progress,
        )
    except (OSError, RuntimeError, SerialProtocolError) as error:
        progress.empty()
        st.error(str(error), title="No se pudo completar la prueba serial")
        return

    progress.empty()
    differences = hardware_output_raw - python_output_raw
    mismatch_count = int(np.count_nonzero(differences))
    result_cards = st.columns(3)
    result_cards[0].metric("Muestras comparadas", len(input_raw))
    result_cards[1].metric("Muestras distintas", mismatch_count)
    result_cards[2].metric("Máximo |Δ raw|", int(np.max(np.abs(differences))))
    if mismatch_count:
        st.error(
            "La aritmética del hardware no coincidió muestra a muestra. Revisa que el programa "
            "cargado provenga de esta misma configuración FIR y que se haya usado RESET."
        )
    else:
        st.success("El hardware y la simulación Python coinciden exactamente, muestra por muestra.")

    serial_data = pd.DataFrame(
        {
            "n": np.arange(len(input_raw)),
            "x_raw": input_raw,
            "y_python_raw": python_output_raw,
            "y_hardware_raw": hardware_output_raw,
            "diferencia_raw": differences,
        }
    )
    st.caption(
        f"Entrada: x = x_raw / 2^{input_format.fraction_length}. "
        f"Salida: y = y_raw / 2^{output_format.fraction_length}."
    )
    st.altair_chart(
        _two_series_chart(
            serial_data,
            "n",
            "Muestra n",
            "y_python_raw",
            "Python y_raw",
            "y_hardware_raw",
            "Hardware y_raw",
            "Salida raw",
        ),
        width="stretch",
        alt="Comparación muestra a muestra de la salida raw del simulador Python y del hardware.",
    )
    st.dataframe(
        serial_data,
        column_config={
            "n": st.column_config.NumberColumn(format="%d"),
            "x_raw": st.column_config.NumberColumn(format="%d"),
            "y_python_raw": st.column_config.NumberColumn(format="%d"),
            "y_hardware_raw": st.column_config.NumberColumn(format="%d"),
            "diferencia_raw": st.column_config.NumberColumn(format="%d"),
        },
        hide_index=True,
        width="stretch",
        height=280,
        alt="Entrada y salidas raw de Python y del hardware para cada muestra enviada por serial.",
    )


def main() -> None:
    st.set_page_config(page_title="FIR Fixed Lab", layout="wide")
    st.title("Laboratorio FIR de punto fijo")
    st.write("Diseña, cuantiza y observa cada formato numérico antes de exportar a hardware.")
    st.subheader("Ejemplos para explorar")
    st.caption("Cargan formatos y señal de prueba; después puedes modificar cualquier control.")
    st.caption(
        "El ejemplo clásico llamado `Q1.15` en muchos textos aparece aquí como `Q0.15`: "
        "en este laboratorio QI no cuenta el bit de signo y siempre se muestra también `numerictype(1, W, F)`. "
        "El ejemplo Todo sin signo usa 16 bits `Q0.16` (`numerictype(0, 16, 16)`)."
    )
    example_columns = st.columns(5)
    for column, (name, help_text) in zip(
        example_columns,
        [
            ("Q1.15", "Caso habitual de 16 bits fraccionarios."),
            ("Pocos bits", "Hace visible el error de cuantización."),
            ("Saturación", "Fuerza una salida fuera de rango y la limita."),
            ("Wrap", "Fuerza el mismo caso, conservando sólo los bits bajos."),
            (
                "Todo sin signo",
                "Media móvil con entrada, coeficientes y salida sin signo de 16 bits.",
            ),
        ],
        strict=True,
    ):
        column.button(name, help=help_text, on_click=_load_example, args=(name,), width="stretch")

    with st.sidebar:
        st.header("Diseño FIR")
        with st.expander("Acerca de y licencia GPLv3"):
            st.markdown(
                "Copyright © 2026 Francisco Carlos Calderón. Este programa es software libre: "
                "puede redistribuirse y modificarse bajo la **GNU GPL versión 3**. Se ofrece "
                "sin garantía. Consulta el texto completo de la "
                "[licencia GPLv3](https://github.com/calderonf/fir-fixed-lab/blob/main/LICENSE)."
            )
        design_options = {} if "design-mode" in st.session_state else {"default": "Pasobajo por ventana"}
        design_mode = st.segmented_control(
            "Estructura del FIR",
            ["Pasobajo por ventana", "Paso alto por ventana", "Media móvil"],
            required=True,
            key="design-mode",
            width="stretch",
            **design_options,
        )
        sample_rate_options = {} if "sample-rate" in st.session_state else {"value": 1000.0}
        sample_rate = st.number_input(
            "Frecuencia de muestreo [Hz]",
            min_value=1.0,
            key="sample-rate",
            on_change=_clamp_frequencies_for_sample_rate,
            **sample_rate_options,
        )
        _clamp_frequencies_for_sample_rate()
        if design_mode == "Media móvil":
            moving_taps_options = {} if "moving-average-taps" in st.session_state else {"value": 31}
            taps = int(
                st.number_input(
                    "Número de taps (coeficientes)",
                    min_value=1,
                    max_value=4096,
                    step=1,
                    key="moving-average-taps",
                    help="Escribe el número de taps o usa los controles − y +. Se admiten hasta 4096 taps.",
                    **moving_taps_options,
                )
            )
        else:
            taps = st.slider(
                "Número de taps (coeficientes)",
                min_value=2,
                max_value=256,
                value=31,
                step=1,
                key="windowed-taps",
            )
        st.caption(
            f"Orden del FIR: {taps - 1}. Hay {taps} coeficientes y {taps - 1} retardos. "
            + ("Taps impares: FIR simétrico de tipo I." if taps % 2 else "Taps pares: FIR simétrico de tipo II.")
        )
        if design_mode in ("Pasobajo por ventana", "Paso alto por ventana"):
            # También cubre valores restaurados desde una sesión anterior.
            cutoff_options = {} if "cutoff-hz" in st.session_state else {"value": min(100.0, sample_rate / 4)}
            cutoff = st.number_input(
                "Frecuencia de corte [Hz]",
                min_value=0.01,
                key="cutoff-hz",
                help="Debe ser menor que Fs/2. Si reduces Fs y Fc deja de ser válida, se ajusta automáticamente a Fs/4.",
                max_value=float(sample_rate / 2 - 0.001),
                **cutoff_options,
            )
            window = st.selectbox("Ventana", ["rectangular", "hann", "hamming", "blackman", "kaiser"], index=2)
            beta = st.slider("β de Kaiser", 0.0, 14.0, 8.6) if window == "kaiser" else 8.6
            if design_mode == "Paso alto por ventana":
                st.caption("Deja pasar las frecuencias por encima del corte y atenúa las cercanas a DC.")
        else:
            st.caption(
                "Media móvil: h[k] = 1/N para todo k. Su respuesta impulsional tiene forma de ventana rectangular "
                "y todos los taps son no negativos."
            )

    if design_mode == "Media móvil":
        coefficients = np.full(taps, 1.0 / taps)
    else:
        try:
            designer = design_lowpass if design_mode == "Pasobajo por ventana" else design_highpass
            coefficients = designer(sample_rate, cutoff, taps, window, beta)
        except ValueError as error:
            st.error(str(error))
            st.stop()

    one, two, three = st.columns(3)
    with one:
        input_format = _format_editor("Entrada x[n]", (True, 16, 15))
    with two:
        coefficient_format = _format_editor("Coeficientes h[k]", (True, 16, 15))
    with three:
        output_format = _format_editor("Salida y[n]", (True, 16, 15))

    st.header("Precisión interna")
    customize_options = {} if "customize-internal" in st.session_state else {"value": False}
    customize_internal = st.checkbox("Personalizar producto y acumulador", key="customize-internal", **customize_options)
    if customize_internal:
        st.caption("Los formatos internos admiten hasta 63 bits; los de entrada, coeficientes y salida permanecen limitados a 32 bits para Arduino.")
        internal_one, internal_two = st.columns(2)
        with internal_one:
            product_format = _format_editor("Producto x·h", (True, 32, 30), max_word_length=63)
        with internal_two:
            accumulator_format = _format_editor("Acumulador", (True, 38, 30), max_word_length=63)
    else:
        product_format = None
        accumulator_format = None
        st.caption("Modo full precision: producto y acumulador se calculan automáticamente.")

    policy, signal_options = st.columns(2)
    with policy:
        rounding_options = {} if "rounding-mode" in st.session_state else {"index": 3}
        rounding = RoundingMode(
            st.selectbox("Redondeo", [mode.value for mode in RoundingMode], key="rounding-mode", **rounding_options)
        )
        overflow_options = {} if "overflow-mode" in st.session_state else {"index": 0}
        overflow = OverflowMode(
            st.selectbox("Overflow", [mode.value for mode in OverflowMode], key="overflow-mode", **overflow_options)
        )
    with signal_options:
        signal_kind_options = {} if "signal-kind" in st.session_state else {"index": 0}
        signal_kind = st.selectbox(
            "Señal de prueba", ["Impulso", "Paso", "Coseno", "Ruido"], key="signal-kind", **signal_kind_options
        )
        amplitude_options = {} if "signal-amplitude" in st.session_state else {"value": 0.8}
        signal_amplitude = st.number_input(
            "Amplitud de paso, coseno y ruido",
            min_value=0.0,
            step=0.1,
            key="signal-amplitude",
            help="El valor inicial 0.8 deja margen antes de saturar un formato con rango cercano a [-1, 1).",
            **amplitude_options,
        )
        signal_frequency_options = {} if "signal-frequency" in st.session_state else {"value": min(50.0, sample_rate / 4)}
        signal_frequency = st.number_input(
            "Frecuencia del coseno [Hz]",
            min_value=0.0,
            max_value=float(sample_rate / 2),
            key="signal-frequency",
            help="Debe estar entre 0 y Fs/2. Si reduces Fs y deja de ser válida, se ajusta a Fs/4.",
            **signal_frequency_options,
        )

    configuration = FIRConfiguration(
        input_format,
        coefficient_format,
        output_format,
        rounding,
        overflow,
        product_format,
        accumulator_format,
    )
    internal_analysis = analyze_internal_precision(coefficients, configuration) if customize_internal else None
    if internal_analysis is not None:
        st.header("Ayuda para elegir la precisión interna")
        st.caption(
            "Las cotas no dependen de la señal de prueba: usan el rango completo de x[n]. "
            "Así sirven para escoger registros antes de implementar el filtro."
        )

        with st.container(border=True):
            st.subheader("Producto x·h: cota teórica y cota de este FIR", help=_PRODUCT_PRECISION_HELP)
            st.caption(
                "La tabla es el producto exacto en "
                f"{_two_notations(internal_analysis.full_precision_product_format)}. "
                "El registro que estás comprobando después es "
                f"{_two_notations(internal_analysis.product_format)}."
            )
            product_cards = st.columns(3)
            product_cards[0].metric("W elegido", internal_analysis.product_format.word_length)
            product_cards[1].metric("W mínimo teórico", internal_analysis.product_theoretical.required_word_length)
            product_cards[2].metric("W mínimo con este FIR", internal_analysis.product_actual.required_word_length)
            st.dataframe(
                _precision_summary_rows(
                    internal_analysis.product_theoretical,
                    internal_analysis.product_actual,
                    internal_analysis.product_theoretical_in_register,
                    internal_analysis.product_actual_in_register,
                ),
                column_config={
                    "mínimo raw": st.column_config.NumberColumn(format="%d"),
                    "mínimo real": st.column_config.NumberColumn(format="%.8g"),
                    "máximo raw": st.column_config.NumberColumn(format="%d"),
                    "máximo real": st.column_config.NumberColumn(format="%.8g"),
                    "W mínimo": st.column_config.NumberColumn(format="%d"),
                },
                hide_index=True,
                width="stretch",
                alt="Cotas mínima y máxima del producto FIR antes de saturación o wrap, para formatos teóricos y coeficientes cuantizados.",
            )
            st.caption(
                _product_witness_caption("Teórico", internal_analysis.product_theoretical)
                + " "
                + _product_witness_caption("Este FIR", internal_analysis.product_actual)
            )

        with st.container(border=True):
            st.subheader(
                "Acumulador: peor caso teórico y peor caso de este FIR",
                help=_ACCUMULATOR_PRECISION_HELP,
            )
            st.caption(
                "La tabla suma los productos exactos en "
                f"F = {internal_analysis.full_precision_product_format.fraction_length}; "
                "el acumulador que estás comprobando después es "
                f"{_two_notations(internal_analysis.accumulator_format)}."
            )
            accumulator_cards = st.columns(3)
            accumulator_cards[0].metric("W elegido", internal_analysis.accumulator_format.word_length)
            accumulator_cards[1].metric(
                "W mínimo teórico", internal_analysis.accumulator_theoretical.required_word_length
            )
            accumulator_cards[2].metric(
                "W mínimo con este FIR", internal_analysis.accumulator_actual.required_word_length
            )
            st.dataframe(
                _precision_summary_rows(
                    internal_analysis.accumulator_theoretical,
                    internal_analysis.accumulator_actual,
                    internal_analysis.accumulator_theoretical_in_register,
                    internal_analysis.accumulator_actual_in_register,
                ),
                column_config={
                    "mínimo raw": st.column_config.NumberColumn(format="%d"),
                    "mínimo real": st.column_config.NumberColumn(format="%.8g"),
                    "máximo raw": st.column_config.NumberColumn(format="%d"),
                    "máximo real": st.column_config.NumberColumn(format="%.8g"),
                    "W mínimo": st.column_config.NumberColumn(format="%d"),
                },
                hide_index=True,
                width="stretch",
                alt="Cotas mínima y máxima del acumulador FIR antes de saturación o wrap, para formatos teóricos y coeficientes cuantizados.",
            )
            with st.expander("Ver las contribuciones de los coeficientes cuantizados"):
                contribution_rows = [
                    {
                        "k": contribution.tap_index,
                        "h[k] raw": contribution.coefficient_raw,
                        "x para mínimo raw": contribution.input_for_min_raw,
                        "contribución mínima exacta raw": contribution.raw_min,
                        "x para máximo raw": contribution.input_for_max_raw,
                        "contribución máxima exacta raw": contribution.raw_max,
                    }
                    for contribution in internal_analysis.actual_contributions
                ]
                st.dataframe(
                    pd.DataFrame(contribution_rows),
                    column_config={
                        "k": st.column_config.NumberColumn(format="%d"),
                        "h[k] raw": st.column_config.NumberColumn(format="%d"),
                        "x para mínimo raw": st.column_config.NumberColumn(format="%d"),
                        "contribución mínima exacta raw": st.column_config.NumberColumn(format="%d"),
                        "x para máximo raw": st.column_config.NumberColumn(format="%d"),
                        "contribución máxima exacta raw": st.column_config.NumberColumn(format="%d"),
                    },
                    hide_index=True,
                    width="stretch",
                    height=280,
                    alt="Contribuciones mínima y máxima al acumulador para cada coeficiente cuantizado.",
                )
                st.caption(
                    "La cota real inferior suma la columna de contribución mínima; "
                    "la superior suma la columna de contribución máxima. Ambas usan F_x+F_h."
                )
    # Para observar h[k] directamente, la entrada impulso debe valer uno. Cuando
    # el formato no puede representar +1, se usa su máximo sin provocar overflow.
    impulse_amplitude = min(1.0, input_format.maximum)
    signal = test_signal(
        signal_kind,
        256,
        sample_rate,
        amplitude=impulse_amplitude if signal_kind == "Impulso" else signal_amplitude,
        frequency_hz=signal_frequency,
        unipolar=not input_format.signed,
    )
    result = simulate_fir(coefficients, signal, configuration)
    product = configuration.resolved_product_format()
    accumulator = configuration.resolved_accumulator_format(taps)
    recommended_output = recommend_output_format(result.coefficient_raw, configuration)
    # Referencia en coma flotante: usa la misma señal aplicada al simulador, sin
    # cuantizar ni limitar registros. Así el error mostrado es fácil de atribuir.
    ideal_output = np.convolve(signal, coefficients)[: len(signal)]
    output_error = result.output - ideal_output

    st.header("Camino de datos: una muestra")
    if not input_format.signed:
        if signal_kind == "Coseno":
            st.info(
                f"El coseno se desplaza a A·(1 + cos(…)), por lo que ocupa "
                f"[0, {2 * signal_amplitude:g}]. Así no hay muestras negativas.",
                title="Entrada sin signo",
            )
        elif signal_kind == "Ruido":
            st.info(
                f"El ruido de prueba es uniforme en [0, {signal_amplitude:g}], no ruido centrado en cero.",
                title="Entrada sin signo",
            )
        else:
            st.info(
                "La señal de prueba se genera únicamente con valores mayores o iguales que cero.",
                title="Entrada sin signo",
            )
    st.markdown(
        f"""1. **Entrada:** se cuantiza $x[n]$ como {_two_notations(input_format)}.
2. **Retardos:** se guardan $x[n-1]$ hasta $x[n-{taps - 1}]$ en el mismo formato. Al iniciar, todos valen cero.
3. **Productos:** cada pareja $x[n-k]h[k]$ usa {_two_notations(product)}.
4. **Suma:** se acumulan los {taps} productos en {_two_notations(accumulator)}.
5. **Salida:** el acumulador se recuantiza a {_two_notations(output_format)} para obtener $y[n]$."""
    )
    if signal_kind == "Impulso":
        st.caption(
            "El impulso usa x[0] = "
            f"{impulse_amplitude:g} y x[n>0] = 0. Por eso la salida muestra "
            f"{impulse_amplitude:g}·h[k], con los retardos iniciales en cero."
        )
    required_bits = accumulator_bound_bits(result.coefficient_raw, configuration)
    cards = st.columns(4)
    cards[0].metric("W acumulador usado", accumulator.word_length)
    cards[1].metric("W por cota de coeficientes", required_bits)
    cards[2].metric("Overflows de acumulador", result.accumulator_overflows)
    cards[3].metric("Overflows de salida", result.output_overflows)

    st.subheader("Inspector: calcula una muestra paso a paso")
    trace_index = st.slider(
        "Muestra n que desea inspeccionar", min_value=0, max_value=len(signal) - 1, value=0, key="trace-sample"
    )
    trace = trace_fir_sample(coefficients, signal, configuration, trace_index)
    trace_cards = st.columns(3)
    trace_cards[0].metric("x[n] almacenada", f"{trace.input_value:.8g}", f"raw {trace.input_raw}")
    trace_cards[1].metric(
        "Suma final del acumulador",
        f"{accumulator.from_raw(trace.accumulator_raw):.8g}",
        f"raw {trace.accumulator_raw}",
    )
    trace_cards[2].metric("y[n] almacenada", f"{trace.output_value:.8g}", f"raw {trace.output_raw}")
    trace_rows = []
    for row in trace.rows:
        flags = []
        if row.product_overflow:
            flags.append("producto")
        if row.alignment_overflow:
            flags.append("alineación")
        if row.accumulator_overflow:
            flags.append("acumulador")
        trace_rows.append(
            {
                "k": row.tap_index,
                "x[n-k] raw": row.input_raw,
                "h[k] raw": row.coefficient_raw,
                "producto exacto raw": row.product_exact_raw,
                "producto raw": row.product_raw,
                "producto alineado raw": row.aligned_product_raw,
                "suma parcial raw": row.accumulator_raw,
                "evento": ", ".join(flags) or "—",
            }
        )
    st.caption(
        "Cada fila implementa `suma parcial ← suma parcial + x[n-k]·h[k]`. "
        "`producto exacto raw` usa F_x+F_h; `producto raw` usa F del producto; las dos últimas columnas usan F del acumulador."
    )
    st.dataframe(
        pd.DataFrame(trace_rows),
        column_config={
            "k": st.column_config.NumberColumn("k", format="%d"),
            "x[n-k] raw": st.column_config.NumberColumn(format="%d"),
            "h[k] raw": st.column_config.NumberColumn(format="%d"),
            "producto exacto raw": st.column_config.NumberColumn(format="%d"),
            "producto raw": st.column_config.NumberColumn(format="%d"),
            "producto alineado raw": st.column_config.NumberColumn(format="%d"),
            "suma parcial raw": st.column_config.NumberColumn(format="%d"),
        },
        width="stretch",
        hide_index=True,
        height=280,
        alt="Tabla paso a paso de los productos y sumas que calculan la muestra FIR seleccionada.",
    )

    st.subheader("¿Hubo desbordamientos?")
    if result.overflow_events:
        st.error(
            f"Se detectaron {len(result.overflow_events)} evento(s). "
            "`raw antes` no cupo en ese registro; `raw almacenado` es el resultado de la política elegida."
        )
        overflow_rows = [
            {
                "muestra": "h[k]" if event.sample_index < 0 else event.sample_index,
                "etapa": event.stage,
                "k": "—" if event.tap_index is None else event.tap_index,
                "raw antes": event.raw_before,
                "raw almacenado": event.raw_after,
            }
            for event in result.overflow_events
        ]
        st.dataframe(
            pd.DataFrame(overflow_rows),
            width="stretch",
            hide_index=True,
            height=260,
            alt="Eventos de overflow por muestra, etapa, tap y enteros raw antes y después de la política aplicada.",
        )
    else:
        st.success("No hubo desbordamientos en los coeficientes, la señal ni los registros internos.")

    ideal_dc_gain = float(coefficients.sum())
    quantized_dc_gain = float(result.coefficient_values.sum())
    shift = accumulator.fraction_length - output_format.fraction_length
    st.info(
        "**Por qué se escala la salida:** el acumulador está en escala "
        f"2^(-{accumulator.fraction_length}) y la salida en 2^(-{output_format.fraction_length}). "
        + (f"Por eso se descartan {shift} bits fraccionarios (con {rounding.value})." if shift >= 0
           else f"Por eso se añaden {-shift} bits fraccionarios.")
    )
    gain_cards = st.columns(2)
    gain_cards[0].metric("Ganancia DC ideal", f"{ideal_dc_gain:.8g}")
    gain_cards[1].metric("Ganancia DC cuantizada", f"{quantized_dc_gain:.8g}", f"error {quantized_dc_gain - ideal_dc_gain:+.3g}")

    st.subheader("Comparación con el FIR ideal")
    maximum_error = float(np.max(np.abs(output_error)))
    rms_error = float(np.sqrt(np.mean(output_error**2)))
    ideal_rms = float(np.sqrt(np.mean(ideal_output**2)))
    snr_db = np.inf if rms_error == 0 else 20 * np.log10(ideal_rms / rms_error) if ideal_rms else -np.inf
    comparison_cards = st.columns(3)
    comparison_cards[0].metric("Error máximo |y_fija − y_ideal|", f"{maximum_error:.4g}")
    comparison_cards[1].metric("Error RMS", f"{rms_error:.4g}")
    comparison_cards[2].metric("SNR de salida", "∞ dB" if np.isinf(snr_db) and snr_db > 0 else f"{snr_db:.3g} dB")

    st.subheader("Formato recomendado para y[n]")
    st.code(f"{recommended_output.q_notation} (QI.QF)  ·  {recommended_output.matlab_notation}")
    st.caption(
        "Recomendación conservadora: conserva todos los bits fraccionarios del producto "
        f"(F = {product.fraction_length}) y cubre la cota |x|·Σ|h|. "
        "Puede elegirse una salida más corta si se acepta recuantizar y se revisan los overflows."
    )

    frequency, ideal_response = frequency_response(coefficients)
    _, quantized_response = frequency_response(result.coefficient_values)
    frequency_hz = frequency * sample_rate / 2
    response_data = pd.DataFrame(
        {
            "frecuencia_hz": frequency_hz,
            "magnitud_ideal_db": 20 * np.log10(np.maximum(np.abs(ideal_response), 1e-12)),
            "magnitud_cuantizada_db": 20 * np.log10(np.maximum(np.abs(quantized_response), 1e-12)),
            "fase_ideal_grados": np.rad2deg(np.unwrap(np.angle(ideal_response))),
            "fase_cuantizada_grados": np.rad2deg(np.unwrap(np.angle(quantized_response))),
        }
    )

    st.header("Respuesta y señal")
    st.subheader("Magnitud")
    st.caption("Azul: ideal. Naranja: cuantizado. El tooltip muestra ambos valores para la misma frecuencia.")
    st.altair_chart(
        _two_series_chart(
            response_data,
            "frecuencia_hz",
            "Frecuencia [Hz]",
            "magnitud_ideal_db",
            "Magnitud ideal [dB]",
            "magnitud_cuantizada_db",
            "Magnitud cuantizada [dB]",
            "Magnitud [dB]",
        ),
        width="stretch",
        alt="Magnitud en dB del FIR ideal y del FIR con coeficientes cuantizados según la frecuencia.",
    )

    st.subheader("Fase")
    st.caption("Fase desenvolvida. En la banda de rechazo, donde la magnitud es muy pequeña, la fase pierde importancia física.")
    st.altair_chart(
        _two_series_chart(
            response_data,
            "frecuencia_hz",
            "Frecuencia [Hz]",
            "fase_ideal_grados",
            "Fase ideal [°]",
            "fase_cuantizada_grados",
            "Fase cuantizada [°]",
            "Fase [°]",
        ),
        width="stretch",
        alt="Fase desenvolvida del FIR ideal y del FIR con coeficientes cuantizados según la frecuencia.",
    )

    signal_data = pd.DataFrame(
        {
            "n": np.arange(len(signal)),
            "entrada": signal,
            "salida_ideal": ideal_output,
            "salida_cuantizada": result.output,
            "error": output_error,
        }
    )
    st.subheader(f"Señal de prueba: {signal_kind}")
    st.caption("Gris: entrada. Azul: FIR ideal. Naranja: simulación de punto fijo. El tooltip muestra las cuatro cantidades.")
    st.altair_chart(
        _signal_chart(signal_data),
        width="stretch",
        alt="Entrada, salida ideal y salida cuantizada del filtro FIR a lo largo de las muestras.",
    )
    error_chart = (
        alt.Chart(signal_data)
        .mark_line(color="#D35400", strokeWidth=2)
        .encode(
            x=alt.X("n:Q", title="Muestra n"),
            y=alt.Y("error:Q", title="Error: cuantizada − ideal"),
            tooltip=[
                alt.Tooltip("n:Q", title="Muestra n", format=".0f"),
                alt.Tooltip("error:Q", title="Error", format=".8g"),
            ],
        )
        .properties(height=180)
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(
        error_chart,
        width="stretch",
        alt="Error entre la salida cuantizada y la salida ideal para cada muestra.",
    )
    if signal_kind == "Paso":
        st.caption(
            f"Para un paso A = {signal_amplitude:g}, el valor estacionario esperado es A·Σh: "
            f"ideal ≈ {signal_amplitude * ideal_dc_gain:.6g}; con coeficientes cuantizados ≈ "
            f"{signal_amplitude * quantized_dc_gain:.6g}. La última salida simulada es {result.output[-1]:.6g}."
        )

    st.header("Coeficientes cuantizados")
    coefficient_denominator = coefficient_format.scale
    st.caption(
        "Conversión de cada coeficiente: `cuantizado = raw / 2^F`. "
        f"Aquí F = {coefficient_format.fraction_length}, por lo tanto 2^F = {coefficient_denominator}."
    )
    st.dataframe(
        {
            "k": np.arange(taps),
            "ideal": coefficients,
            "raw": result.coefficient_raw,
            "denominador 2^F": np.full(taps, coefficient_denominator),
            "cuantizado": result.coefficient_values,
            "error": result.coefficient_values - coefficients,
        },
        width="stretch",
        hide_index=True,
        alt="Tabla de coeficientes FIR ideales, enteros raw, denominador, cuantizados y su error.",
    )

    try:
        impulse_export = build_arduino_export(coefficients, configuration)
        serial_export = build_arduino_serial_export(coefficients, configuration)
        st.caption("Arduino Uno / Mega 2560")
        impulse_column, serial_column = st.columns(2)
        impulse_column.download_button(
            "Descargar demostración de impulso",
            _zip_export(
                impulse_export.header,
                impulse_export.sketch,
                impulse_export.runtime,
                "FIRFixedImpulse.ino",
            ),
            file_name="FIRFixedImpulse.zip",
            mime="application/zip",
            help="Genera un impulso y envía por Serial pares entrada_raw,salida_raw.",
            width="stretch",
        )
        serial_column.download_button(
            "Descargar FIR interactivo por Serial",
            _zip_export(
                serial_export.header,
                serial_export.sketch,
                serial_export.runtime,
                "FIRFixedSerial.ino",
            ),
            file_name="FIRFixedSerial.zip",
            mime="application/zip",
            help="Recibe x_raw por líneas y responde x_raw,y_raw; incluye PING, RESET e INFO.",
            width="stretch",
        )
    except ValueError as error:
        st.warning(f"No se puede exportar a Arduino Uno: {error}")

    pico_impulse_export = build_micropython_impulse_export(coefficients, configuration)
    pico_serial_export = build_micropython_serial_export(coefficients, configuration)
    st.caption(
        "Hardware MicroPython probado: Raspberry Pi Pico, Pico H, Pico 2 y ESP32-S "
        "(incluida ESP32-CAM), con MicroPython v1.29.0 o posterior."
    )
    pico_impulse_column, pico_serial_column = st.columns(2)
    pico_impulse_column.download_button(
        "Descargar Pico: demostración de impulso",
        _zip_micropython_export(pico_impulse_export),
        file_name="FIRPicoImpulse.zip",
        mime="application/zip",
        help="Incluye main.py, fir_config.py y fir_fixed.py para MicroPython.",
        width="stretch",
    )
    pico_serial_column.download_button(
        "Descargar Pico: FIR interactivo por Serial",
        _zip_micropython_export(pico_serial_export),
        file_name="FIRPicoSerial.zip",
        mime="application/zip",
        help="Usa el mismo protocolo serial que Arduino: PING, RESET, INFO y x_raw,y_raw.",
        width="stretch",
    )

    _render_serial_hardware_test(
        result.input_raw,
        result.output_raw,
        input_format,
        output_format,
    )


if __name__ == "__main__":
    main()
