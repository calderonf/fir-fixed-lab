"""Diseño y simulación bit-exacta de FIR de forma directa."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

import numpy as np

from .fixed_point import FixedFormat, OverflowMode, RoundingMode

WindowName = Literal["rectangular", "hann", "hamming", "blackman", "kaiser"]


def _window(name: WindowName, taps: int, beta: float = 8.6) -> np.ndarray:
    index = np.arange(taps)
    if name == "rectangular":
        return np.ones(taps)
    if name == "hann":
        return np.hanning(taps)
    if name == "hamming":
        return np.hamming(taps)
    if name == "blackman":
        return np.blackman(taps)
    if name == "kaiser":
        return np.kaiser(taps, beta)
    raise ValueError(f"Ventana no soportada: {name}")


def design_lowpass(
    sample_rate: float,
    cutoff_hz: float,
    taps: int,
    window: WindowName = "hamming",
    beta: float = 8.6,
) -> np.ndarray:
    """Diseña un FIR pasobajo de fase lineal con el método de ventanas.

    La frecuencia de corte es la del sinc ideal; la ventana introduce la
    transición real. Para un número par de taps se usa fase lineal tipo II.
    """
    if sample_rate <= 0:
        raise ValueError("La frecuencia de muestreo debe ser positiva.")
    if not 0 < cutoff_hz < sample_rate / 2:
        raise ValueError("El corte debe estar entre 0 y Nyquist.")
    if taps < 2:
        raise ValueError("El filtro necesita al menos dos taps.")
    normalized_cutoff = 2 * cutoff_hz / sample_rate
    n = np.arange(taps) - (taps - 1) / 2
    ideal = normalized_cutoff * np.sinc(normalized_cutoff * n)
    coefficients = ideal * _window(window, taps, beta)
    return coefficients / np.sum(coefficients)  # Ganancia DC unitaria.


def design_highpass(
    sample_rate: float,
    cutoff_hz: float,
    taps: int,
    window: WindowName = "hamming",
    beta: float = 8.6,
) -> np.ndarray:
    """Diseña un FIR paso alto por modulación espectral de un pasobajo.

    Se traslada un pasobajo con corte ``Fs/2 - Fc`` hasta Nyquist mediante
    ``(-1)^n``. Esta construcción conserva ganancia unitaria en Nyquist y
    admite tanto un número par como impar de taps.
    """
    if not 0 < cutoff_hz < sample_rate / 2:
        raise ValueError("El corte debe estar entre 0 y Nyquist.")
    complementary_lowpass = design_lowpass(
        sample_rate,
        sample_rate / 2 - cutoff_hz,
        taps,
        window,
        beta,
    )
    return complementary_lowpass * np.where(np.arange(taps) % 2, -1.0, 1.0)


def frequency_response(coefficients: np.ndarray, points: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    response = np.fft.rfft(coefficients, n=2 * (points - 1))
    return np.linspace(0.0, 1.0, points), response


@dataclass(frozen=True)
class FIRConfiguration:
    input_format: FixedFormat
    coefficient_format: FixedFormat
    output_format: FixedFormat
    rounding: RoundingMode = RoundingMode.NEAREST
    overflow: OverflowMode = OverflowMode.SATURATE
    product_format: FixedFormat | None = None
    accumulator_format: FixedFormat | None = None

    def resolved_product_format(self) -> FixedFormat:
        if self.product_format is not None:
            return self.product_format
        return FixedFormat(
            signed=self.input_format.signed or self.coefficient_format.signed,
            word_length=self.input_format.word_length + self.coefficient_format.word_length,
            fraction_length=self.input_format.fraction_length + self.coefficient_format.fraction_length,
        )

    def resolved_accumulator_format(self, taps: int) -> FixedFormat:
        if self.accumulator_format is not None:
            return self.accumulator_format
        product = self.resolved_product_format()
        guard_bits = math.ceil(math.log2(taps)) if taps > 1 else 0
        return FixedFormat(product.signed, product.word_length + guard_bits, product.fraction_length)


@dataclass
class SimulationResult:
    input_raw: np.ndarray
    output_raw: np.ndarray
    output: np.ndarray
    coefficient_raw: np.ndarray
    coefficient_values: np.ndarray
    input_overflows: int
    product_overflows: int
    accumulator_overflows: int
    output_overflows: int
    coefficient_overflows: int
    overflow_events: tuple["OverflowEvent", ...]


@dataclass(frozen=True)
class OverflowEvent:
    """Un valor que no cupo en alguno de los registros del camino de datos."""

    sample_index: int
    stage: str
    tap_index: int | None
    raw_before: int
    raw_after: int


@dataclass(frozen=True)
class TapTrace:
    """Una fila del cálculo MAC para una muestra concreta."""

    tap_index: int
    input_raw: int
    coefficient_raw: int
    product_exact_raw: int
    product_raw: int
    aligned_product_raw: int
    accumulator_before_raw: int
    accumulator_raw: int
    product_overflow: bool
    alignment_overflow: bool
    accumulator_overflow: bool


@dataclass(frozen=True)
class SampleTrace:
    """Traza reproducible de la evaluación de ``y[n]``."""

    sample_index: int
    input_raw: int
    input_value: float
    rows: tuple[TapTrace, ...]
    accumulator_raw: int
    output_raw: int
    output_value: float
    output_overflow: bool


@dataclass(frozen=True)
class RangeWitness:
    """Un caso que alcanza uno de los extremos de un análisis de rango.

    Los enteros de entrada y coeficiente se conservan para que el resultado no
    sea una cifra misteriosa: la interfaz puede mostrar exactamente qué pareja
    ``x·h`` produjo el límite.
    """

    raw: int
    input_raw: int | None = None
    coefficient_raw: int | None = None
    tap_index: int | None = None


@dataclass(frozen=True)
class RawRange:
    """Intervalo matemático en una escala binaria concreta, antes de overflow."""

    raw_min: int
    raw_max: int
    fraction_length: int
    required_word_length: int
    fits_destination: bool
    min_witness: RangeWitness
    max_witness: RangeWitness

    @property
    def minimum(self) -> float:
        return self.raw_min / (1 << self.fraction_length)

    @property
    def maximum(self) -> float:
        return self.raw_max / (1 << self.fraction_length)


@dataclass(frozen=True)
class AccumulatorContribution:
    """Rango de uno de los productos ya expresado en la escala del acumulador."""

    tap_index: int
    coefficient_raw: int
    raw_min: int
    raw_max: int
    input_for_min_raw: int
    input_for_max_raw: int


@dataclass(frozen=True)
class InternalPrecisionAnalysis:
    """Cotas para escoger los registros producto y acumulador de un FIR.

    Todas las cotas se toman *antes* de saturar o envolver. De este modo se
    puede contestar la pregunta de diseño importante: ¿cuántos bits hacen falta
    para que esa política de overflow nunca llegue a activarse bajo el supuesto
    indicado?
    """

    product_format: FixedFormat
    accumulator_format: FixedFormat
    full_precision_product_format: FixedFormat
    product_theoretical: RawRange
    product_actual: RawRange
    accumulator_theoretical: RawRange
    accumulator_actual: RawRange
    product_theoretical_in_register: RawRange
    product_actual_in_register: RawRange
    accumulator_theoretical_in_register: RawRange
    accumulator_actual_in_register: RawRange
    actual_contributions: tuple[AccumulatorContribution, ...]


def _quantize_value(
    value: float,
    format_: FixedFormat,
    rounding: RoundingMode,
    overflow: OverflowMode,
) -> tuple[int, int, bool]:
    """Devuelve el raw matemático, el almacenado y si hubo overflow."""
    raw_before = format_._round_float(value * format_.scale, rounding)
    raw_after, overflowed = format_.apply_overflow(raw_before, overflow)
    return raw_before, raw_after, overflowed


def _rescale_raw_with_before(
    raw: int,
    source_fraction_length: int,
    destination: FixedFormat,
    rounding: RoundingMode,
    overflow: OverflowMode,
) -> tuple[int, int, bool]:
    """Como ``rescale_raw``, pero conserva el entero antes de limitarlo."""
    shift = source_fraction_length - destination.fraction_length
    if shift <= 0:
        raw_before = raw << (-shift)
    else:
        divisor = 1 << shift
        if rounding is RoundingMode.FLOOR:
            raw_before = raw // divisor
        elif rounding is RoundingMode.CEIL:
            raw_before = -((-raw) // divisor)
        elif rounding is RoundingMode.TOWARD_ZERO:
            raw_before = (abs(raw) // divisor) * (1 if raw >= 0 else -1)
        else:
            magnitude, remainder = divmod(abs(raw), divisor)
            twice_remainder = 2 * remainder
            increment = twice_remainder > divisor
            if twice_remainder == divisor:
                increment = rounding is RoundingMode.NEAREST or magnitude % 2 == 1
            raw_before = (magnitude + int(increment)) * (1 if raw >= 0 else -1)
    raw_after, overflowed = destination.apply_overflow(raw_before, overflow)
    return raw_before, raw_after, overflowed


def _rescale_raw_before_overflow(
    raw: int,
    source_fraction_length: int,
    destination: FixedFormat,
    rounding: RoundingMode,
) -> int:
    """Reescala un entero, pero no le aplica ni saturación ni ``wrap``.

    La parte común con el simulador se conserva en
    :func:`_rescale_raw_with_before`. El valor devuelto es exactamente el
    candidato que ese simulador compararía contra el rango del registro.
    """
    raw_before, _, _ = _rescale_raw_with_before(
        raw,
        source_fraction_length,
        destination,
        rounding,
        OverflowMode.SATURATE,
    )
    return raw_before


def _required_word_length(raw_min: int, raw_max: int, signed: bool) -> int:
    """Longitud mínima de palabra que puede almacenar un intervalo raw."""
    if raw_min > raw_max:
        raise ValueError("El límite inferior no puede superar al límite superior.")
    if not signed and raw_min < 0:
        raise ValueError("Un formato sin signo no puede representar un límite negativo.")
    word_length = 1
    while raw_min < (-(1 << (word_length - 1)) if signed else 0) or raw_max > (
        (1 << (word_length - 1)) - 1 if signed else (1 << word_length) - 1
    ):
        word_length += 1
    return word_length


def _range_from_witnesses(
    witnesses: list[RangeWitness],
    destination: FixedFormat,
) -> RawRange:
    """Resume candidatos ya expresados en la escala de ``destination``."""
    if not witnesses:
        raise ValueError("El análisis necesita al menos un candidato.")
    min_witness = min(witnesses, key=lambda witness: witness.raw)
    max_witness = max(witnesses, key=lambda witness: witness.raw)
    return RawRange(
        raw_min=min_witness.raw,
        raw_max=max_witness.raw,
        fraction_length=destination.fraction_length,
        required_word_length=_required_word_length(
            min_witness.raw, max_witness.raw, destination.signed
        ),
        fits_destination=(
            destination.raw_min <= min_witness.raw <= destination.raw_max
            and destination.raw_min <= max_witness.raw <= destination.raw_max
        ),
        min_witness=min_witness,
        max_witness=max_witness,
    )


def _rescale_range_before_overflow(
    range_: RawRange,
    destination: FixedFormat,
    rounding: RoundingMode,
) -> RawRange:
    """Lleva los extremos de una cota a otro F sin aplicar overflow.

    El redondeo usado por el laboratorio es monótono; por ello basta convertir
    los dos extremos para conocer el intervalo en el nuevo registro. Esta
    función sólo se usa para comprobar el registro escogido: no cambia la cota
    matemática original.
    """
    def convert(witness: RangeWitness) -> RangeWitness:
        return RangeWitness(
            _rescale_raw_before_overflow(
                witness.raw,
                range_.fraction_length,
                destination,
                rounding,
            ),
            witness.input_raw,
            witness.coefficient_raw,
            witness.tap_index,
        )

    return _range_from_witnesses(
        [convert(range_.min_witness), convert(range_.max_witness)], destination
    )


def _quantized_coefficients_with_events(
    coefficients: np.ndarray,
    configuration: FIRConfiguration,
) -> tuple[np.ndarray, np.ndarray, tuple[OverflowEvent, ...]]:
    raw_values: list[int] = []
    events: list[OverflowEvent] = []
    for tap_index, coefficient in enumerate(coefficients):
        raw_before, raw_after, overflowed = _quantize_value(
            float(coefficient),
            configuration.coefficient_format,
            configuration.rounding,
            configuration.overflow,
        )
        raw_values.append(raw_after)
        if overflowed:
            events.append(
                OverflowEvent(-1, "Coeficiente", tap_index, raw_before, raw_after)
            )
    raw = np.asarray(raw_values, dtype=np.int64)
    return raw, raw / configuration.coefficient_format.scale, tuple(events)


def quantize_coefficients(
    coefficients: np.ndarray,
    configuration: FIRConfiguration,
) -> tuple[np.ndarray, np.ndarray, int]:
    raw, values, events = _quantized_coefficients_with_events(coefficients, configuration)
    return raw, values, len(events)


def analyze_internal_precision(
    coefficients: np.ndarray,
    configuration: FIRConfiguration,
) -> InternalPrecisionAnalysis:
    """Calcula cotas teóricas y específicas del FIR para la precisión interna.

    **Teórico** deja que cada producto use cualquiera de los extremos que
    permiten *los formatos* de entrada y coeficiente. Para el acumulador, los
    ``N`` productos pueden tomar simultáneamente ese extremo: es una cota segura
    pero deliberadamente conservadora.

    **Real** usa los coeficientes ya cuantizados del filtro diseñado. Cada
    retardo ``x[n-k]`` todavía puede tomar de forma independiente el mínimo o
    máximo del formato de entrada; por eso suma los mínimos (o los máximos) de
    todos los taps. Las cuatro cotas se expresan antes de saturación o wrap.
    """
    coefficients = np.asarray(coefficients, dtype=float)
    if coefficients.ndim != 1 or len(coefficients) == 0:
        raise ValueError("El análisis necesita al menos un coeficiente unidimensional.")

    input_format = configuration.input_format
    coefficient_format = configuration.coefficient_format
    product_format = configuration.resolved_product_format()
    accumulator_format = configuration.resolved_accumulator_format(len(coefficients))
    source_fraction_length = (
        input_format.fraction_length + coefficient_format.fraction_length
    )
    full_precision_product_format = FixedFormat(
        signed=input_format.signed or coefficient_format.signed,
        word_length=input_format.word_length + coefficient_format.word_length,
        fraction_length=source_fraction_length,
    )

    # El caso teórico usa las cuatro esquinas del rectángulo x×h. Estos son
    # productos exactos: su escala F_x + F_h y sus extremos no dependen del
    # formato elegido después para guardar el producto.
    theoretical_product_witnesses: list[RangeWitness] = []
    for x_raw in (input_format.raw_min, input_format.raw_max):
        for h_raw in (coefficient_format.raw_min, coefficient_format.raw_max):
            theoretical_product_witnesses.append(RangeWitness(x_raw * h_raw, x_raw, h_raw))
    product_theoretical = _range_from_witnesses(
        theoretical_product_witnesses, full_precision_product_format
    )

    coefficient_raw, _, _ = _quantized_coefficients_with_events(
        coefficients, configuration
    )
    actual_product_witnesses: list[RangeWitness] = []
    contributions: list[AccumulatorContribution] = []
    accumulator_actual_min = 0
    accumulator_actual_max = 0
    for tap_index, h_raw_value in enumerate(coefficient_raw):
        h_raw = int(h_raw_value)
        tap_product_witnesses: list[RangeWitness] = []
        for x_raw in (input_format.raw_min, input_format.raw_max):
            witness = RangeWitness(x_raw * h_raw, x_raw, h_raw, tap_index)
            actual_product_witnesses.append(witness)
            tap_product_witnesses.append(witness)

        minimum = min(tap_product_witnesses, key=lambda witness: witness.raw)
        maximum = max(tap_product_witnesses, key=lambda witness: witness.raw)
        accumulator_actual_min += minimum.raw
        accumulator_actual_max += maximum.raw
        contributions.append(
            AccumulatorContribution(
                tap_index=tap_index,
                coefficient_raw=h_raw,
                raw_min=minimum.raw,
                raw_max=maximum.raw,
                input_for_min_raw=int(minimum.input_raw),
                input_for_max_raw=int(maximum.input_raw),
            )
        )

    product_actual = _range_from_witnesses(
        actual_product_witnesses, full_precision_product_format
    )

    # Para el acumulador teórico se usa un producto máximo/mínimo permitido por
    # los formatos, repetido N veces, tal como se hace al presupuestar guard bits.
    theoretical_accumulator_witnesses = [
        RangeWitness(len(coefficients) * product_theoretical.raw_min),
        RangeWitness(len(coefficients) * product_theoretical.raw_max),
    ]
    accumulator_theoretical = _range_from_witnesses(
        theoretical_accumulator_witnesses, full_precision_product_format
    )
    accumulator_actual = _range_from_witnesses(
        [
            RangeWitness(accumulator_actual_min),
            RangeWitness(accumulator_actual_max),
        ],
        full_precision_product_format,
    )
    product_theoretical_in_register = _rescale_range_before_overflow(
        product_theoretical, product_format, configuration.rounding
    )
    product_actual_in_register = _rescale_range_before_overflow(
        product_actual, product_format, configuration.rounding
    )
    accumulator_theoretical_in_register = _rescale_range_before_overflow(
        accumulator_theoretical, accumulator_format, configuration.rounding
    )
    accumulator_actual_in_register = _rescale_range_before_overflow(
        accumulator_actual, accumulator_format, configuration.rounding
    )

    return InternalPrecisionAnalysis(
        product_format=product_format,
        accumulator_format=accumulator_format,
        full_precision_product_format=full_precision_product_format,
        product_theoretical=product_theoretical,
        product_actual=product_actual,
        accumulator_theoretical=accumulator_theoretical,
        accumulator_actual=accumulator_actual,
        product_theoretical_in_register=product_theoretical_in_register,
        product_actual_in_register=product_actual_in_register,
        accumulator_theoretical_in_register=accumulator_theoretical_in_register,
        accumulator_actual_in_register=accumulator_actual_in_register,
        actual_contributions=tuple(contributions),
    )


def accumulator_bound_bits(coefficient_raw: np.ndarray, configuration: FIRConfiguration) -> int:
    """Bits para la cota ``sum(abs(h))*abs(x)`` en la escala del producto."""
    maximum_input = max(abs(configuration.input_format.raw_min), abs(configuration.input_format.raw_max))
    bound = maximum_input * int(np.abs(coefficient_raw).sum())
    product = configuration.resolved_product_format()
    # En un formato con signo, W-1 bits deben poder almacenar la magnitud.
    # En uno sin signo no existe ese bit adicional de signo.
    return max(1, bound.bit_length() + int(product.signed))


def recommend_output_format(coefficient_raw: np.ndarray, configuration: FIRConfiguration) -> FixedFormat:
    """Formato de salida seguro que conserva toda la precisión del producto.

    La cota usa el peor caso ``|x| sum(|h|)``. Mantener los F bits del producto
    evita una segunda cuantización de la salida. Es una recomendación didáctica
    conservadora; un formato de salida más corto sigue siendo válido si se acepta
    la recuantización y se verifica que no haya overflow.
    """
    product = configuration.resolved_product_format()
    return FixedFormat(
        signed=product.signed,
        # Además de cubrir la amplitud, W debe dejar espacio estructural para
        # todos los F bits fraccionarios y, si aplica, el bit de signo. Esto
        # importa, por ejemplo, cuando todos los coeficientes se cuantizan a 0.
        word_length=max(
            accumulator_bound_bits(coefficient_raw, configuration),
            product.fraction_length + int(product.signed),
        ),
        fraction_length=product.fraction_length,
    )


def simulate_fir(
    coefficients: np.ndarray,
    signal: np.ndarray,
    configuration: FIRConfiguration,
) -> SimulationResult:
    """Simula un FIR directo cuantizando en cada punto físico relevante."""
    coefficients = np.asarray(coefficients, dtype=float)
    signal = np.asarray(signal, dtype=float)
    if coefficients.ndim != 1 or signal.ndim != 1:
        raise ValueError("Coeficientes y señal deben ser vectores unidimensionales.")
    if len(coefficients) == 0:
        raise ValueError("El FIR necesita al menos un coeficiente.")

    coefficient_raw, coefficient_values, coefficient_events = _quantized_coefficients_with_events(
        coefficients, configuration
    )
    product_format = configuration.resolved_product_format()
    accumulator_format = configuration.resolved_accumulator_format(len(coefficients))
    states = [0] * len(coefficients)
    input_raw: list[int] = []
    output_raw: list[int] = []
    events = list(coefficient_events)
    input_overflows = product_overflows = accumulator_overflows = output_overflows = 0

    for sample_index, sample in enumerate(signal):
        x_before, x_raw, overflowed = _quantize_value(
            float(sample), configuration.input_format, configuration.rounding, configuration.overflow
        )
        input_overflows += int(overflowed)
        if overflowed:
            events.append(OverflowEvent(sample_index, "Entrada", None, x_before, x_raw))
        states.insert(0, x_raw)
        states.pop()
        accumulator = 0
        for tap_index, (x_delayed, coefficient) in enumerate(zip(states, coefficient_raw, strict=True)):
            product_exact = int(x_delayed) * int(coefficient)
            product_before, product_raw, overflowed = _rescale_raw_with_before(
                product_exact,
                configuration.input_format.fraction_length + configuration.coefficient_format.fraction_length,
                product_format,
                configuration.rounding,
                configuration.overflow,
            )
            product_overflows += int(overflowed)
            if overflowed:
                events.append(OverflowEvent(sample_index, "Producto", tap_index, product_before, product_raw))
            aligned_before, aligned_product, overflowed = _rescale_raw_with_before(
                product_raw,
                product_format.fraction_length,
                accumulator_format,
                configuration.rounding,
                configuration.overflow,
            )
            product_overflows += int(overflowed)
            if overflowed:
                events.append(
                    OverflowEvent(sample_index, "Alineación al acumulador", tap_index, aligned_before, aligned_product)
                )
            accumulator_before = accumulator
            accumulator, overflowed = accumulator_format.apply_overflow(
                accumulator_before + aligned_product, configuration.overflow
            )
            accumulator_overflows += int(overflowed)
            if overflowed:
                events.append(
                    OverflowEvent(
                        sample_index,
                        "Acumulador",
                        tap_index,
                        accumulator_before + aligned_product,
                        accumulator,
                    )
                )
        y_before, y_raw, overflowed = _rescale_raw_with_before(
            accumulator,
            accumulator_format.fraction_length,
            configuration.output_format,
            configuration.rounding,
            configuration.overflow,
        )
        output_overflows += int(overflowed)
        if overflowed:
            events.append(OverflowEvent(sample_index, "Salida", None, y_before, y_raw))
        input_raw.append(x_raw)
        output_raw.append(y_raw)

    output_raw_array = np.asarray(output_raw, dtype=np.int64)
    return SimulationResult(
        input_raw=np.asarray(input_raw, dtype=np.int64),
        output_raw=output_raw_array,
        output=output_raw_array / configuration.output_format.scale,
        coefficient_raw=coefficient_raw,
        coefficient_values=coefficient_values,
        input_overflows=input_overflows,
        product_overflows=product_overflows,
        accumulator_overflows=accumulator_overflows,
        output_overflows=output_overflows,
        coefficient_overflows=len(coefficient_events),
        overflow_events=tuple(events),
    )


def trace_fir_sample(
    coefficients: np.ndarray,
    signal: np.ndarray,
    configuration: FIRConfiguration,
    sample_index: int,
) -> SampleTrace:
    """Explica el cálculo de una muestra sin ocultar los valores ``raw``.

    Ejecuta exactamente el mismo camino de datos que :func:`simulate_fir`,
    incluyendo los retardos iniciales nulos y las políticas de overflow.
    """
    coefficients = np.asarray(coefficients, dtype=float)
    signal = np.asarray(signal, dtype=float)
    if not 0 <= sample_index < len(signal):
        raise ValueError("El índice de muestra debe pertenecer a la señal.")
    if len(coefficients) == 0:
        raise ValueError("El FIR necesita al menos un coeficiente.")

    coefficient_raw, _, _ = _quantized_coefficients_with_events(coefficients, configuration)
    product_format = configuration.resolved_product_format()
    accumulator_format = configuration.resolved_accumulator_format(len(coefficients))
    states = [0] * len(coefficients)

    for current_index, sample in enumerate(signal[: sample_index + 1]):
        _, x_raw, _ = _quantize_value(
            float(sample), configuration.input_format, configuration.rounding, configuration.overflow
        )
        states.insert(0, x_raw)
        states.pop()
        accumulator = 0
        rows: list[TapTrace] = []
        for tap_index, (x_delayed, coefficient) in enumerate(zip(states, coefficient_raw, strict=True)):
            product_exact = int(x_delayed) * int(coefficient)
            _, product_raw, product_overflow = _rescale_raw_with_before(
                product_exact,
                configuration.input_format.fraction_length + configuration.coefficient_format.fraction_length,
                product_format,
                configuration.rounding,
                configuration.overflow,
            )
            _, aligned_product, alignment_overflow = _rescale_raw_with_before(
                product_raw,
                product_format.fraction_length,
                accumulator_format,
                configuration.rounding,
                configuration.overflow,
            )
            accumulator_before = accumulator
            accumulator, accumulator_overflow = accumulator_format.apply_overflow(
                accumulator_before + aligned_product, configuration.overflow
            )
            if current_index == sample_index:
                rows.append(
                    TapTrace(
                        tap_index,
                        int(x_delayed),
                        int(coefficient),
                        product_exact,
                        product_raw,
                        aligned_product,
                        accumulator_before,
                        accumulator,
                        product_overflow,
                        alignment_overflow,
                        accumulator_overflow,
                    )
                )
        _, y_raw, output_overflow = _rescale_raw_with_before(
            accumulator,
            accumulator_format.fraction_length,
            configuration.output_format,
            configuration.rounding,
            configuration.overflow,
        )

    return SampleTrace(
        sample_index=sample_index,
        input_raw=x_raw,
        input_value=configuration.input_format.from_raw(x_raw),
        rows=tuple(rows),
        accumulator_raw=accumulator,
        output_raw=y_raw,
        output_value=configuration.output_format.from_raw(y_raw),
        output_overflow=output_overflow,
    )


def test_signal(
    kind: str,
    samples: int,
    sample_rate: float,
    amplitude: float = 0.8,
    frequency_hz: float = 10.0,
    seed: int = 1,
    unipolar: bool = False,
) -> np.ndarray:
    """Crea señales didácticas centradas o compatibles con una entrada sin signo.

    Con ``unipolar=True``, el coseno se desplaza a ``A(1 + cos(...))`` y
    ocupa [0, 2A]. El ruido se genera uniforme en [0, A]. Así no aparecen
    muestras negativas que un registro sin signo tendría que saturar o envolver.
    """
    n = np.arange(samples)
    if kind == "Impulso":
        result = np.zeros(samples)
        result[0] = amplitude
        return result
    if kind == "Paso":
        return np.full(samples, amplitude)
    if kind == "Coseno":
        cosine = amplitude * np.cos(2 * np.pi * frequency_hz * n / sample_rate)
        return amplitude + cosine if unipolar else cosine
    if kind == "Ruido":
        generator = np.random.default_rng(seed)
        return generator.uniform(0.0, amplitude, samples) if unipolar else generator.normal(0.0, amplitude / 3, samples)
    raise ValueError(f"Señal no soportada: {kind}")
