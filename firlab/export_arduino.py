"""Exportación de un filtro y su contrato numérico a Arduino Uno."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import textwrap

import numpy as np

from .fir import FIRConfiguration, quantize_coefficients
from .fixed_point import FixedFormat, OverflowMode, RoundingMode


def _cpp_format(name: str, value: FixedFormat) -> str:
    return (
        f"const FirFormat {name} = "
        f"{{{value.word_length}, {value.fraction_length}, {'true' if value.signed else 'false'}}};"
    )


def _rounding_name(rounding: RoundingMode) -> str:
    return f"FIR_ROUND_{rounding.value.upper()}"


def _overflow_name(overflow: OverflowMode) -> str:
    return f"FIR_OVERFLOW_{overflow.value.upper()}"


def arduino_header(coefficients: np.ndarray, configuration: FIRConfiguration) -> str:
    """Devuelve un ``fir_config.h`` que consume la librería FIRFixed.h.

    El destino almacena los valores raw como int32_t. En Arduino Uno el
    simulador avisa al usuario si el formato elegido no cabe en esa palabra.
    """
    coefficients = np.asarray(coefficients, dtype=float)
    coefficient_raw, _, _ = quantize_coefficients(coefficients, configuration)
    product = configuration.resolved_product_format()
    accumulator = configuration.resolved_accumulator_format(len(coefficients))
    external_formats = [configuration.input_format, configuration.coefficient_format, configuration.output_format]
    def fits_int32(format_: FixedFormat) -> bool:
        # int32_t incluye el bit de signo. Un formato con signo W=32 cabe;
        # uno sin signo necesita W<=31 porque el runtime usa int32_t.
        return format_.word_length <= (32 if format_.signed else 31)

    if not all(fits_int32(format_) for format_ in external_formats):
        raise ValueError(
            "En Arduino Uno, entrada, coeficientes y salida deben usar W <= 32 con signo "
            "o W <= 31 sin signo."
        )
    if product.word_length > 60 or accumulator.word_length > 60:
        raise ValueError("Producto y acumulador deben usar W <= 60 bits para la simulación segura.")
    unity_raw, _ = configuration.input_format.quantize(1.0, configuration.rounding, configuration.overflow)
    ideal_dc_gain = float(coefficients.sum())
    quantized_dc_gain = float(coefficient_raw.sum() / configuration.coefficient_format.scale)
    accumulator_to_output_shift = accumulator.fraction_length - configuration.output_format.fraction_length
    shift_text = (
        f"corrimiento a la derecha de {accumulator_to_output_shift} bits"
        if accumulator_to_output_shift >= 0
        else f"corrimiento a la izquierda de {-accumulator_to_output_shift} bits"
    )
    coefficient_lines = ",\n    ".join(str(int(value)) for value in coefficient_raw)
    return f"""// Archivo generado por FIR Fixed Lab. No editar a mano.
//
// Escalas: valor_real = valor_raw / 2^F.
// h[k] se guarda con F_h={configuration.coefficient_format.fraction_length}; por tanto,
// y_acumulado_raw = suma(x_raw * h_raw) representa y con F_acc={accumulator.fraction_length}.
// Para guardar la salida con F_y={configuration.output_format.fraction_length}, la librería hace
// un {shift_text}, aplicando además el redondeo y overflow configurados.
// Ganancia DC: ideal={ideal_dc_gain:.12g}; cuantizada={quantized_dc_gain:.12g}.
#pragma once
#include <Arduino.h>
#include \"FIRFixed.h\"

constexpr uint16_t FIR_TAPS = {len(coefficients)};
constexpr int8_t FIR_ACCUMULATOR_TO_OUTPUT_SHIFT = {accumulator_to_output_shift};
constexpr int32_t FIR_COEFFICIENT_RAW_SUM = {int(coefficient_raw.sum())};
const int32_t FIR_COEFFICIENTS[FIR_TAPS] PROGMEM = {{
    {coefficient_lines}
}};

{_cpp_format('FIR_INPUT_FORMAT', configuration.input_format)}
{_cpp_format('FIR_COEFFICIENT_FORMAT', configuration.coefficient_format)}
{_cpp_format('FIR_PRODUCT_FORMAT', product)}
{_cpp_format('FIR_ACCUMULATOR_FORMAT', accumulator)}
{_cpp_format('FIR_OUTPUT_FORMAT', configuration.output_format)}

const FirConfig FIR_CONFIG = {{
    FIR_COEFFICIENTS,
    FIR_TAPS,
    FIR_INPUT_FORMAT,
    FIR_COEFFICIENT_FORMAT,
    FIR_PRODUCT_FORMAT,
    FIR_ACCUMULATOR_FORMAT,
    FIR_OUTPUT_FORMAT,
    {_rounding_name(configuration.rounding)},
    {_overflow_name(configuration.overflow)}
}};

// Muestra raw que representa un impulso de amplitud 1 (puede saturar según Q).
constexpr int32_t FIR_UNITY_INPUT_RAW = {unity_raw};
"""


def _format_description(name: str, format_: FixedFormat, storage: str) -> str:
    sign = "con signo" if format_.signed else "sin signo"
    return (
        f"//   {name}: {storage}; {format_.q_notation} = {format_.matlab_notation}; "
        f"W={format_.word_length}, F={format_.fraction_length}, {sign}."
    )


def _expanded_fir_equation(coefficient_raw: np.ndarray, fraction_length: int) -> list[str]:
    """Expone la ecuación cuantizada sin crear comentarios gigantes."""
    terms = []
    for index, raw in enumerate(coefficient_raw):
        delayed_input = "x[n]" if index == 0 else f"x[n-{index}]"
        terms.append(f"({int(raw)}/2^{fraction_length})·{delayed_input}")
    if len(terms) > 32:
        terms = terms[:12] + ["…"] + terms[-1:]
    equation = " + ".join(terms)
    lines = textwrap.wrap(equation, width=88, break_long_words=False, break_on_hyphens=False)
    return [f"//   y[n] = {line}" if index == 0 else f"//          {line}" for index, line in enumerate(lines)]


def arduino_sketch(coefficients: np.ndarray, configuration: FIRConfiguration) -> str:
    """Ejemplo de impulso con una explicación concreta del filtro exportado."""
    coefficients = np.asarray(coefficients, dtype=float)
    coefficient_raw, coefficient_values, _ = quantize_coefficients(coefficients, configuration)
    product = configuration.resolved_product_format()
    accumulator = configuration.resolved_accumulator_format(len(coefficients))
    output = configuration.output_format
    input_ = configuration.input_format
    coefficient = configuration.coefficient_format
    unity_raw, _ = input_.quantize(1.0, configuration.rounding, configuration.overflow)
    nonzero_index = next((index for index, raw in enumerate(coefficient_raw) if raw != 0), 0)
    example_coefficient_raw = int(coefficient_raw[nonzero_index])
    example_coefficient_value = float(coefficient_values[nonzero_index])
    shift = accumulator.fraction_length - output.fraction_length
    if shift > 0:
        shift_explanation = (
            f"yRaw = redondear(accRaw / 2^{shift}); es un corrimiento a la derecha de {shift} bits."
        )
    elif shift < 0:
        shift_explanation = (
            f"yRaw = accRaw · 2^{-shift}; es un corrimiento a la izquierda de {-shift} bits."
        )
    else:
        shift_explanation = "yRaw = accRaw; no hay corrimiento de escala."
    equation_lines = "\n".join(_expanded_fir_equation(coefficient_raw, coefficient.fraction_length))
    return f"""/*
  FIR Fixed Lab — guía del filtro exportado

  ECUACIÓN DE ESTE FIR ({len(coefficients)} taps)
{equation_lines}
  Cada fracción h[k] es el coeficiente CUANTIZADO almacenado en fir_config.h.
  De forma compacta: y[n] = suma(k=0..{len(coefficients) - 1}) h[k]·x[n-k].

  FORMATOS DE LOS REGISTROS RAW
{_format_description('xRaw y delayLine[k]', input_, 'int32_t')}
{_format_description('hRaw[k] (PROGMEM)', coefficient, 'int32_t')}
{_format_description('productRaw', product, 'int64_t')}
{_format_description('accRaw', accumulator, 'int64_t')}
{_format_description('yRaw', output, 'int32_t')}

  ESCALAMIENTO Y CORRIMIENTO DE SALIDA
  accRaw representa un valor real dividido por 2^{accumulator.fraction_length};
  yRaw debe quedar dividido por 2^{output.fraction_length}.
  {shift_explanation}
  La operación aplica el redondeo y la política de overflow definidos en fir_config.h.

  EJEMPLOS RAW -> REAL
  xRaw = {unity_raw} representa x = {unity_raw} / 2^{input_.fraction_length} = {unity_raw / input_.scale:.12g}.
  hRaw[{nonzero_index}] = {example_coefficient_raw} representa h[{nonzero_index}] = {example_coefficient_raw} / 2^{coefficient.fraction_length} = {example_coefficient_value:.12g}.
  Para cualquier dato recibido por Serial: y_real = yRaw / 2^{output.fraction_length}.
*/

#include \"FIRFixed.h\"
#include \"fir_config.h\"

int32_t delayLine[FIR_TAPS] = {{0}};
FirFixed filter(FIR_CONFIG, delayLine);

void setup() {{
  Serial.begin(115200);
  for (uint16_t n = 0; n < FIR_TAPS + 20; ++n) {{
    const int32_t x = n == 0 ? FIR_UNITY_INPUT_RAW : 0;
    const int32_t y = filter.process(x);
    Serial.print(x);       // entrada raw: x_real = x / 2^F_x
    Serial.print(',');
    Serial.println(y);     // salida raw: y_real = y / 2^F_y
  }}
}}

void loop() {{}}
"""


def arduino_serial_sketch(coefficients: np.ndarray, configuration: FIRConfiguration) -> str:
    """Sketch FIR interactivo: una línea raw recibida produce una línea raw.

    El parser no usa ``String`` para no fragmentar la RAM pequeña del Uno. Cada
    petición se responde antes de que el host envíe la siguiente, de modo que la
    práctica no depende de llenar el buffer serial del microcontrolador.
    """
    coefficients = np.asarray(coefficients, dtype=float)
    coefficient_raw, coefficient_values, _ = quantize_coefficients(coefficients, configuration)
    product = configuration.resolved_product_format()
    accumulator = configuration.resolved_accumulator_format(len(coefficients))
    input_ = configuration.input_format
    coefficient = configuration.coefficient_format
    output = configuration.output_format
    nonzero_index = next((index for index, raw in enumerate(coefficient_raw) if raw != 0), 0)
    example_coefficient_raw = int(coefficient_raw[nonzero_index])
    example_coefficient_value = float(coefficient_values[nonzero_index])
    equation_lines = "\n".join(_expanded_fir_equation(coefficient_raw, coefficient.fraction_length))
    return f'''/*
  FIR Fixed Lab — prueba interactiva por Serial

  PROTOCOLO (ASCII, una petición por línea)
    PC -> Arduino:  x_raw\\n
    Arduino -> PC:  x_raw,y_raw\\n
  El PC debe esperar la respuesta antes de enviar la siguiente muestra. Así el
  Uno procesa una secuencia con estados FIR correctos sin llenar su buffer.

  COMANDOS
    PING   -> ^..^
    RESET  -> OK                  (borra todos los retardos)
    INFO   -> formatos y número de taps

  ECUACIÓN DE ESTE FIR ({len(coefficients)} taps)
{equation_lines}
  De forma compacta: y[n] = suma(k=0..{len(coefficients) - 1}) h[k]·x[n-k].

  FORMATOS DE LOS REGISTROS RAW
{_format_description('xRaw y delayLine[k]', input_, 'int32_t')}
{_format_description('hRaw[k] (PROGMEM)', coefficient, 'int32_t')}
{_format_description('productRaw', product, 'int64_t')}
{_format_description('accRaw', accumulator, 'int64_t')}
{_format_description('yRaw', output, 'int32_t')}

  CONVERSIÓN RAW -> REAL
  x_real = x_raw / 2^{input_.fraction_length}
  y_real = y_raw / 2^{output.fraction_length}
  Ejemplo: hRaw[{nonzero_index}] = {example_coefficient_raw} representa
            h[{nonzero_index}] = {example_coefficient_raw} / 2^{coefficient.fraction_length} = {example_coefficient_value:.12g}.
*/

#include <Arduino.h>
#include <errno.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include "FIRFixed.h"
#include "fir_config.h"

constexpr unsigned long SERIAL_BAUD = 115200;
constexpr uint8_t SERIAL_LINE_CAPACITY = 24;  // int32_t, signo y terminador.
char serialLine[SERIAL_LINE_CAPACITY];
uint8_t serialLineLength = 0;
bool discardingLongLine = false;

int32_t delayLine[FIR_TAPS] = {{0}};
FirFixed filter(FIR_CONFIG, delayLine);

void printInfo() {{
  Serial.print(F("INFO,taps="));
  Serial.print(FIR_TAPS);
  Serial.print(F(",input_F="));
  Serial.print(FIR_INPUT_FORMAT.fractionLength);
  Serial.print(F(",output_F="));
  Serial.println(FIR_OUTPUT_FORMAT.fractionLength);
}}

bool parseRawInt32(const char *text, int32_t *value) {{
  char *end = nullptr;
  errno = 0;
  const long parsed = strtol(text, &end, 10);
  if (text == end || errno == ERANGE) return false;
  while (*end == ' ' || *end == '\\t') ++end;
  if (*end != '\\0' || parsed < INT32_MIN || parsed > INT32_MAX) return false;
  *value = static_cast<int32_t>(parsed);
  return true;
}}

void processSerialLine(char *line) {{
  if (strcmp(line, "PING") == 0) {{
    Serial.println(F("^..^"));
    return;
  }}
  if (strcmp(line, "RESET") == 0) {{
    filter.reset();
    Serial.println(F("OK"));
    return;
  }}
  if (strcmp(line, "INFO") == 0) {{
    printInfo();
    return;
  }}

  int32_t xRaw = 0;
  if (!parseRawInt32(line, &xRaw)) {{
    Serial.println(F("ERR,expected-int32-or-command"));
    return;
  }}
  const int32_t yRaw = filter.process(xRaw);
  Serial.print(xRaw);  // x_real = xRaw / 2^F_x
  Serial.print(',');
  Serial.println(yRaw);  // y_real = yRaw / 2^F_y
}}

void setup() {{
  Serial.begin(SERIAL_BAUD);
  filter.reset();
  Serial.println(F("FIR_SERIAL_READY"));
}}

void loop() {{
  while (Serial.available() > 0) {{
    const char received = static_cast<char>(Serial.read());
    if (received == '\\r') continue;
    if (received == '\\n') {{
      if (discardingLongLine) {{
        Serial.println(F("ERR,line-too-long"));
      }} else {{
        serialLine[serialLineLength] = '\\0';
        processSerialLine(serialLine);
      }}
      serialLineLength = 0;
      discardingLongLine = false;
    }} else if (!discardingLongLine) {{
      if (serialLineLength + 1 < SERIAL_LINE_CAPACITY) {{
        serialLine[serialLineLength++] = received;
      }} else {{
        discardingLongLine = true;
      }}
    }}
  }}
}}
'''


@dataclass(frozen=True)
class ArduinoExport:
    header: str
    sketch: str
    runtime: str


def build_arduino_export(coefficients: np.ndarray, configuration: FIRConfiguration) -> ArduinoExport:
    runtime = Path(__file__).with_name("FIRFixed.h").read_text(encoding="utf-8")
    return ArduinoExport(
        arduino_header(coefficients, configuration),
        arduino_sketch(coefficients, configuration),
        runtime,
    )


def build_arduino_serial_export(coefficients: np.ndarray, configuration: FIRConfiguration) -> ArduinoExport:
    """Genera el mismo FIR, pero con un sketch que lo alimenta por Serial."""
    runtime = Path(__file__).with_name("FIRFixed.h").read_text(encoding="utf-8")
    return ArduinoExport(
        arduino_header(coefficients, configuration),
        arduino_serial_sketch(coefficients, configuration),
        runtime,
    )


def write_arduino_export(directory: str | Path, coefficients: np.ndarray, configuration: FIRConfiguration) -> ArduinoExport:
    """Escribe configuración y sketch; la librería FIRFixed debe estar instalada."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    export = build_arduino_export(coefficients, configuration)
    (target / "fir_config.h").write_text(export.header, encoding="utf-8")
    (target / "FIRFixedImpulse.ino").write_text(export.sketch, encoding="utf-8")
    (target / "FIRFixed.h").write_text(export.runtime, encoding="utf-8")
    return export
