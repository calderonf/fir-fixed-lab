"""Pruebas de la frontera entre los JSON de pyfda y el núcleo FIR."""

import json
import unittest

import numpy as np

from firlab.pyfda import PyfdaImportError, load_pyfda_fir


def _document(*, family="fir", a=None, b=None, fs=48_000) -> bytes:
    return json.dumps(
        {
            "a": [1.0] if a is None else a,
            "b": [0.25, 0.5, 0.25] if b is None else b,
            "method": "Equiripple",
            "order": 2,
            "specs": {
                "filterFamily": family,
                "responseType": "lowpass",
                "designMethod": "remez",
                "fs": fs,
            },
        }
    ).encode("utf-8")


class PyfdaImportTests(unittest.TestCase):
    def test_loads_fir_coefficients_and_sampling_rate(self) -> None:
        imported = load_pyfda_fir(_document())

        np.testing.assert_allclose(imported.coefficients, [0.25, 0.5, 0.25])
        self.assertEqual(imported.sample_rate, 48_000)
        self.assertEqual(imported.taps, 3)
        self.assertEqual(imported.order, 2)
        self.assertEqual(imported.design_method, "remez")

    def test_rejects_iir_before_its_coefficients_can_be_used(self) -> None:
        with self.assertRaisesRegex(PyfdaImportError, "sólo importa FIR"):
            load_pyfda_fir(_document(family="iir", a=[1.0, -0.8]))

    def test_rejects_a_nontrivial_denominator_even_if_metadata_says_fir(self) -> None:
        with self.assertRaisesRegex(PyfdaImportError, "denominador `a`"):
            load_pyfda_fir(_document(a=[1.0, -0.8]))

    def test_rejects_missing_or_invalid_sampling_frequency(self) -> None:
        with self.assertRaisesRegex(PyfdaImportError, "specs.fs"):
            load_pyfda_fir(_document(fs=0))

    def test_rejects_nonfinite_coefficients(self) -> None:
        with self.assertRaisesRegex(PyfdaImportError, "finitos"):
            load_pyfda_fir(_document(b=[0.25, float("inf")]))
