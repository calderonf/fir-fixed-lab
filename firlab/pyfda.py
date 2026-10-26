"""Importación deliberadamente pequeña de filtros FIR exportados por pyfda-web.

El laboratorio no reproduce los métodos de diseño de pyfda. Sólo toma el
filtro ya diseñado: sus coeficientes ``b`` y la frecuencia de muestreo
``specs.fs``. El denominador ``a`` se valida de forma explícita para evitar
que, por accidente, un IIR recursivo se simule como una FIR.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

import numpy as np


class PyfdaImportError(ValueError):
    """El archivo no contiene un FIR JSON compatible con este laboratorio."""


@dataclass(frozen=True)
class PyfdaFir:
    """Información estrictamente necesaria para reutilizar el análisis FIR."""

    coefficients: np.ndarray
    sample_rate: float
    response_type: str
    design_method: str
    method: str

    @property
    def taps(self) -> int:
        return len(self.coefficients)

    @property
    def order(self) -> int:
        return self.taps - 1


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PyfdaImportError(f"El campo `{name}` debe ser un objeto JSON.")
    return value


def _finite_coefficients(value: Any) -> np.ndarray:
    if not isinstance(value, list) or not value:
        raise PyfdaImportError("El campo `b` debe contener al menos un coeficiente FIR.")
    try:
        coefficients = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as error:
        raise PyfdaImportError("Los coeficientes `b` deben ser números reales.") from error
    if coefficients.ndim != 1 or not np.all(np.isfinite(coefficients)):
        raise PyfdaImportError("Los coeficientes `b` deben ser números reales finitos en una lista.")
    return coefficients


def load_pyfda_fir(payload: bytes | str) -> PyfdaFir:
    """Lee un JSON de pyfda-web y devuelve exclusivamente su FIR.

    pyfda-web escribe ``b`` para el numerador, ``a`` para el denominador y
    ``specs`` para los parámetros del diseño. Un FIR normalizado debe tener
    exactamente ``a = [1]``; cualquier otra cosa se rechaza, incluso si el
    archivo afirmara ser FIR en sus metadatos.
    """
    try:
        decoded = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        data = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PyfdaImportError("No se pudo leer un JSON válido de pyfda.") from error

    document = _mapping(data, "raíz")
    specs = _mapping(document.get("specs"), "specs")
    family = str(specs.get("filterFamily", "")).casefold()
    if family != "fir":
        found = specs.get("filterFamily", "ausente")
        raise PyfdaImportError(
            f"El archivo declara `filterFamily: {found}`. Este laboratorio sólo importa FIR; "
            "un IIR necesita realimentación y no se puede tratar como FIR."
        )

    denominator = document.get("a")
    if not isinstance(denominator, list) or len(denominator) != 1:
        raise PyfdaImportError(
            "El denominador `a` no es `[1]`: el archivo contiene realimentación (IIR) "
            "o no tiene el formato FIR esperado."
        )
    try:
        denominator_value = float(denominator[0])
    except (TypeError, ValueError) as error:
        raise PyfdaImportError("El denominador `a` debe contener el número 1.") from error
    if not np.isfinite(denominator_value) or denominator_value != 1.0:
        raise PyfdaImportError(
            "El denominador `a` no es `[1]`: este laboratorio sólo acepta FIR sin realimentación."
        )

    coefficients = _finite_coefficients(document.get("b"))
    try:
        sample_rate = float(specs["fs"])
    except (KeyError, TypeError, ValueError) as error:
        raise PyfdaImportError("Falta `specs.fs`, la frecuencia de muestreo del filtro.") from error
    if not np.isfinite(sample_rate) or sample_rate <= 0:
        raise PyfdaImportError("`specs.fs` debe ser una frecuencia de muestreo positiva y finita.")

    return PyfdaFir(
        coefficients=coefficients,
        sample_rate=sample_rate,
        response_type=str(specs.get("responseType", "no especificada")),
        design_method=str(specs.get("designMethod", "no especificado")),
        method=str(document.get("method", "no especificado")),
    )
