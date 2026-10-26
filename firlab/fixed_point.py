"""Aritmética fija explícita para simulaciones didácticas.

Todos los valores se guardan como enteros ``raw``. Un formato con F bits
fraccionarios representa ``raw / 2**F``. Esta regla evita la ambigüedad de
la notación Q, que cambia ligeramente entre herramientas.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


class RoundingMode(str, Enum):
    FLOOR = "floor"
    CEIL = "ceil"
    TOWARD_ZERO = "toward_zero"
    NEAREST = "nearest"  # Empates se alejan de cero.
    CONVERGENT = "convergent"  # Empates al entero par.


class OverflowMode(str, Enum):
    SATURATE = "saturate"
    WRAP = "wrap"


@dataclass(frozen=True)
class FixedFormat:
    """Formato binario fijo.

    ``word_length`` (W) incluye siempre el signo si ``signed`` es verdadero.
    ``fraction_length`` (F o QF) cuenta los bits a la derecha del punto.
    ``integer_bits`` (QI) no incluye el signo, una convención que se muestra
    de forma explícita para no confundir Q1.15 con otras convenciones.
    """

    signed: bool
    word_length: int
    fraction_length: int

    def __post_init__(self) -> None:
        if self.word_length < 1:
            raise ValueError("La longitud de palabra debe ser al menos 1.")
        if self.fraction_length < 0:
            raise ValueError("La longitud fraccionaria no puede ser negativa.")
        if self.integer_bits < 0:
            raise ValueError("W no deja espacio para el signo y los bits fraccionarios.")

    @property
    def integer_bits(self) -> int:
        return self.word_length - self.fraction_length - int(self.signed)

    @property
    def q_notation(self) -> str:
        return f"Q{self.integer_bits}.{self.fraction_length}"

    @property
    def matlab_notation(self) -> str:
        return f"numerictype({int(self.signed)}, {self.word_length}, {self.fraction_length})"

    @property
    def scale(self) -> int:
        return 1 << self.fraction_length

    @property
    def raw_min(self) -> int:
        return -(1 << (self.word_length - 1)) if self.signed else 0

    @property
    def raw_max(self) -> int:
        return (1 << (self.word_length - 1)) - 1 if self.signed else (1 << self.word_length) - 1

    @property
    def minimum(self) -> float:
        return self.raw_min / self.scale

    @property
    def maximum(self) -> float:
        return self.raw_max / self.scale

    @property
    def lsb(self) -> float:
        return 1 / self.scale

    def summary(self) -> dict[str, object]:
        return {
            "signed": self.signed,
            "W": self.word_length,
            "F / QF": self.fraction_length,
            "QI (sin signo)": self.integer_bits,
            "Q": self.q_notation,
            "MATLAB": self.matlab_notation,
            "mínimo": self.minimum,
            "máximo": self.maximum,
            "LSB": self.lsb,
        }

    def _round_float(self, value: float, mode: RoundingMode) -> int:
        if mode is RoundingMode.FLOOR:
            return math.floor(value)
        if mode is RoundingMode.CEIL:
            return math.ceil(value)
        if mode is RoundingMode.TOWARD_ZERO:
            return math.trunc(value)
        if mode is RoundingMode.CONVERGENT:
            return int(round(value))
        # nearest, con empate alejándose de cero
        return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)

    def quantize(
        self,
        value: float,
        rounding: RoundingMode = RoundingMode.NEAREST,
        overflow: OverflowMode = OverflowMode.SATURATE,
    ) -> tuple[int, bool]:
        """Convierte un valor real a entero raw y reporta si hubo overflow."""
        raw = self._round_float(value * self.scale, rounding)
        return self.apply_overflow(raw, overflow)

    def apply_overflow(self, raw: int, mode: OverflowMode) -> tuple[int, bool]:
        overflowed = raw < self.raw_min or raw > self.raw_max
        if not overflowed:
            return raw, False
        if mode is OverflowMode.SATURATE:
            return min(max(raw, self.raw_min), self.raw_max), True
        modulus = 1 << self.word_length
        wrapped = raw & (modulus - 1)
        if self.signed and wrapped >= (1 << (self.word_length - 1)):
            wrapped -= modulus
        return wrapped, True

    def from_raw(self, raw: int) -> float:
        return raw / self.scale

    def rescale_raw(
        self,
        raw: int,
        source_fraction_length: int,
        rounding: RoundingMode,
        overflow: OverflowMode,
    ) -> tuple[int, bool]:
        """Reinterpreta un entero raw en este formato, con cuantización."""
        shift = source_fraction_length - self.fraction_length
        if shift <= 0:
            scaled = raw << (-shift)
        else:
            divisor = 1 << shift
            if rounding is RoundingMode.FLOOR:
                scaled = raw // divisor
            elif rounding is RoundingMode.CEIL:
                scaled = -((-raw) // divisor)
            elif rounding is RoundingMode.TOWARD_ZERO:
                scaled = (abs(raw) // divisor) * (1 if raw >= 0 else -1)
            else:
                magnitude, remainder = divmod(abs(raw), divisor)
                twice_remainder = 2 * remainder
                increment = twice_remainder > divisor
                if twice_remainder == divisor:
                    increment = rounding is RoundingMode.NEAREST or magnitude % 2 == 1
                scaled = (magnitude + int(increment)) * (1 if raw >= 0 else -1)
        return self.apply_overflow(scaled, overflow)
