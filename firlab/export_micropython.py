"""Exportación bit-exacta de FIR para tarjetas compatibles con MicroPython."""

from __future__ import annotations

from dataclasses import dataclass
import textwrap

import numpy as np

from .fir import FIRConfiguration, quantize_coefficients
from .fixed_point import FixedFormat


@dataclass(frozen=True)
class MicroPythonExport:
    """Los tres archivos que se copian juntos al sistema de archivos de la tarjeta."""

    config: str
    runtime: str
    main: str


def _format_tuple(format_: FixedFormat) -> str:
    return f"({format_.word_length}, {format_.fraction_length}, {format_.signed!r})"


def micropython_config(coefficients: np.ndarray, configuration: FIRConfiguration) -> str:
    """Configuración simple, compatible con el runtime de MicroPython."""
    coefficients = np.asarray(coefficients, dtype=float)
    coefficient_raw, _, _ = quantize_coefficients(coefficients, configuration)
    product = configuration.resolved_product_format()
    accumulator = configuration.resolved_accumulator_format(len(coefficients))
    raw_text = ", ".join(str(int(value)) for value in coefficient_raw)
    if len(coefficient_raw) == 1:
        raw_text += ","
    return f'''# Generado por FIR Fixed Lab para una tarjeta compatible con MicroPython.
# MicroPython objetivo: v1.29.0 o posterior.
# Regla: valor_real = raw / 2**F.

TAPS = {len(coefficients)}
COEFFICIENTS_RAW = ({raw_text})

# Cada formato es (W, F, signed): W incluye el signo cuando signed=True.
INPUT_FORMAT = {_format_tuple(configuration.input_format)}       # {configuration.input_format.q_notation}; {configuration.input_format.matlab_notation}
COEFFICIENT_FORMAT = {_format_tuple(configuration.coefficient_format)}  # {configuration.coefficient_format.q_notation}; {configuration.coefficient_format.matlab_notation}
PRODUCT_FORMAT = {_format_tuple(product)}
ACCUMULATOR_FORMAT = {_format_tuple(accumulator)}
OUTPUT_FORMAT = {_format_tuple(configuration.output_format)}

ROUNDING = {configuration.rounding.value!r}
OVERFLOW = {configuration.overflow.value!r}

CONFIG = {{
    "taps": TAPS,
    "input": INPUT_FORMAT,
    "coefficient": COEFFICIENT_FORMAT,
    "product": PRODUCT_FORMAT,
    "accumulator": ACCUMULATOR_FORMAT,
    "output": OUTPUT_FORMAT,
    "rounding": ROUNDING,
    "overflow": OVERFLOW,
}}
'''


def micropython_runtime() -> str:
    """Runtime pequeño que reproduce el camino de datos del simulador Python."""
    return '''# Runtime generado para una tarjeta compatible con MicroPython.
# No usa flotantes: todas las entradas, estados y salidas son enteros raw.

def _minimum(format_):
    word_length, _fraction_length, signed = format_
    return -(1 << (word_length - 1)) if signed else 0


def _maximum(format_):
    word_length, _fraction_length, signed = format_
    return (1 << (word_length - 1)) - 1 if signed else (1 << word_length) - 1


def apply_overflow(raw, format_, overflow):
    """Aplica saturación o wrap exactamente en el registro indicado."""
    minimum = _minimum(format_)
    maximum = _maximum(format_)
    if minimum <= raw <= maximum:
        return raw
    if overflow == "saturate":
        return minimum if raw < minimum else maximum
    word_length = format_[0]
    wrapped = raw & ((1 << word_length) - 1)
    if format_[2] and wrapped >= (1 << (word_length - 1)):
        wrapped -= 1 << word_length
    return wrapped


def _round_right(raw, shift, rounding):
    if shift == 0:
        return raw
    divisor = 1 << shift
    if rounding == "floor":
        return raw // divisor
    if rounding == "ceil":
        return -((-raw) // divisor)
    magnitude = -raw if raw < 0 else raw
    quotient, remainder = divmod(magnitude, divisor)
    if rounding == "toward_zero":
        rounded = quotient
    else:
        twice_remainder = 2 * remainder
        increment = twice_remainder > divisor
        if twice_remainder == divisor:
            increment = rounding == "nearest" or (quotient & 1) == 1
        rounded = quotient + int(increment)
    return -rounded if raw < 0 else rounded


def rescale(raw, source_fraction_length, destination, rounding, overflow):
    destination_fraction_length = destination[1]
    if source_fraction_length < destination_fraction_length:
        raw = raw << (destination_fraction_length - source_fraction_length)
    else:
        raw = _round_right(raw, source_fraction_length - destination_fraction_length, rounding)
    return apply_overflow(raw, destination, overflow)


class FirFixed:
    def __init__(self, coefficients_raw, config):
        self.coefficients_raw = coefficients_raw
        self.config = config
        self.delay_line = [0] * config["taps"]
        self.write_index = 0

    def reset(self):
        for index in range(self.config["taps"]):
            self.delay_line[index] = 0
        self.write_index = 0

    def process(self, input_raw):
        config = self.config
        input_format = config["input"]
        coefficient_format = config["coefficient"]
        product_format = config["product"]
        accumulator_format = config["accumulator"]
        output_format = config["output"]
        rounding = config["rounding"]
        overflow = config["overflow"]

        x_raw = apply_overflow(input_raw, input_format, overflow)
        self.delay_line[self.write_index] = x_raw
        accumulator = 0
        state_index = self.write_index
        source_fraction_length = input_format[1] + coefficient_format[1]
        for tap_index in range(config["taps"]):
            product = self.delay_line[state_index] * self.coefficients_raw[tap_index]
            product = rescale(product, source_fraction_length, product_format, rounding, overflow)
            aligned_product = rescale(product, product_format[1], accumulator_format, rounding, overflow)
            accumulator = apply_overflow(accumulator + aligned_product, accumulator_format, overflow)
            state_index = config["taps"] - 1 if state_index == 0 else state_index - 1

        self.write_index = (self.write_index + 1) % config["taps"]
        return rescale(accumulator, accumulator_format[1], output_format, rounding, overflow)
'''


def _equation_lines(coefficient_raw: np.ndarray, fraction_length: int) -> str:
    terms = []
    for index, raw in enumerate(coefficient_raw):
        delayed_input = "x[n]" if index == 0 else f"x[n-{index}]"
        terms.append(f"({int(raw)}/2^{fraction_length})·{delayed_input}")
    if len(terms) > 24:
        terms = terms[:10] + ["…"] + terms[-1:]
    return "\n".join("#   " + line for line in textwrap.wrap(" + ".join(terms), width=78))


def micropython_impulse_main(coefficients: np.ndarray, configuration: FIRConfiguration) -> str:
    """``main.py`` que imprime la respuesta al impulso en enteros raw."""
    coefficients = np.asarray(coefficients, dtype=float)
    coefficient_raw, _, _ = quantize_coefficients(coefficients, configuration)
    unity_raw, _ = configuration.input_format.quantize(
        1.0, configuration.rounding, configuration.overflow
    )
    equation = _equation_lines(coefficient_raw, configuration.coefficient_format.fraction_length)
    return f'''# FIR Fixed Lab — respuesta impulso para una tarjeta MicroPython.
# ECUACIÓN CUANTIZADA ({len(coefficients)} taps)
{equation}
# Cada línea impresa es: x_raw,y_raw.
# x_real = x_raw / 2^{configuration.input_format.fraction_length}; y_real = y_raw / 2^{configuration.output_format.fraction_length}.

from fir_config import COEFFICIENTS_RAW, CONFIG, TAPS
from fir_fixed import FirFixed

filter = FirFixed(COEFFICIENTS_RAW, CONFIG)
for n in range(TAPS + 20):
    x_raw = {unity_raw} if n == 0 else 0
    y_raw = filter.process(x_raw)
    print("%d,%d" % (x_raw, y_raw))
'''


def micropython_serial_main(coefficients: np.ndarray, configuration: FIRConfiguration) -> str:
    """``main.py`` por USB serial, compatible con el cliente actual de la app."""
    coefficients = np.asarray(coefficients, dtype=float)
    coefficient_raw, _, _ = quantize_coefficients(coefficients, configuration)
    equation = _equation_lines(coefficient_raw, configuration.coefficient_format.fraction_length)
    return f'''# FIR Fixed Lab — prueba interactiva por USB serial para una tarjeta MicroPython.
# Objetivo: MicroPython v1.29.0 o posterior.
#
# Protocolo ASCII, una petición por línea:
#   PC -> Pico: x_raw\\n
#   Pico -> PC: x_raw,y_raw\\n
# El host espera cada respuesta antes de enviar la muestra siguiente.
# Comandos: PING -> ^..^ ; RESET -> OK ; INFO -> formatos y taps.
#
# ECUACIÓN CUANTIZADA ({len(coefficients)} taps)
{equation}
# x_real = x_raw / 2^{configuration.input_format.fraction_length}; y_real = y_raw / 2^{configuration.output_format.fraction_length}.

import sys
from fir_config import COEFFICIENTS_RAW, CONFIG, TAPS
from fir_fixed import FirFixed

filter = FirFixed(COEFFICIENTS_RAW, CONFIG)

def reply(text):
    print(text)
    try:
        sys.stdout.flush()
    except AttributeError:
        pass


def print_info():
    reply("INFO,taps=%d,input_F=%d,output_F=%d" % (TAPS, CONFIG["input"][1], CONFIG["output"][1]))


reply("FIR_SERIAL_READY")
while True:
    line = sys.stdin.readline()
    if not line:
        continue
    command = line.strip()
    if command == "PING":
        reply("^..^")
    elif command == "RESET":
        filter.reset()
        reply("OK")
    elif command == "INFO":
        print_info()
    else:
        try:
            x_raw = int(command)
        except ValueError:
            reply("ERR,expected-int-or-command")
            continue
        y_raw = filter.process(x_raw)
        reply("%d,%d" % (x_raw, y_raw))
'''


def build_micropython_impulse_export(
    coefficients: np.ndarray, configuration: FIRConfiguration
) -> MicroPythonExport:
    """Archivos para cargar en una Pico como ``main.py`` y módulos auxiliares."""
    return MicroPythonExport(
        config=micropython_config(coefficients, configuration),
        runtime=micropython_runtime(),
        main=micropython_impulse_main(coefficients, configuration),
    )


def build_micropython_serial_export(
    coefficients: np.ndarray, configuration: FIRConfiguration
) -> MicroPythonExport:
    """Archivos para la prueba serial bit-exacta en una Pico."""
    return MicroPythonExport(
        config=micropython_config(coefficients, configuration),
        runtime=micropython_runtime(),
        main=micropython_serial_main(coefficients, configuration),
    )
