"""Pruebas ligeras de los recorridos didácticos de la interfaz Streamlit."""

from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).parents[1] / "firlab" / "app.py"


class AppTests(unittest.TestCase):
    def test_app_offers_impulse_and_interactive_serial_exports(self) -> None:
        app = AppTest.from_file(str(APP_PATH)).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(
            [button.label for button in app.download_button],
            [
                "Descargar demostración de impulso",
                "Descargar FIR interactivo por Serial",
                "Descargar Pico: demostración de impulso",
                "Descargar Pico: FIR interactivo por Serial",
            ],
        )

    def test_custom_internal_precision_shows_explained_product_and_accumulator_bounds(self) -> None:
        app = AppTest.from_file(str(APP_PATH)).run(timeout=30)
        app.checkbox(key="customize-internal").set_value(True).run(timeout=30)

        self.assertFalse(app.exception)
        headers = {header.value: header.help for header in app.subheader}
        product_title = "Producto x·h: cota teórica y cota de este FIR"
        accumulator_title = "Acumulador: peor caso teórico y peor caso de este FIR"
        self.assertIn(product_title, headers)
        self.assertIn(accumulator_title, headers)
        self.assertIn("cuatro combinaciones", headers[product_title])
        self.assertIn("cada retardo", headers[accumulator_title])
        self.assertTrue(
            any(
                list(dataframe.value["caso"]) == [
                    "Teórico (formatos)",
                    "Este FIR (h[k] cuantizado)",
                ]
                for dataframe in app.dataframe
                if "caso" in dataframe.value.columns
            )
        )

    def test_cutoff_is_reset_to_quarter_sample_rate_when_fs_decreases(self) -> None:
        app = AppTest.from_file(str(APP_PATH)).run(timeout=30)
        app.number_input(key="sample-rate").set_value(100.0).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.number_input(key="cutoff-hz").value, 25.0)

        app.number_input(key="cutoff-hz").set_value(49.0).run(timeout=30)
        app.number_input(key="sample-rate").set_value(80.0).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.number_input(key="cutoff-hz").value, 20.0)
        self.assertEqual(app.number_input(key="signal-frequency").value, 20.0)

    def test_fraction_length_clamps_when_word_length_or_sign_changes(self) -> None:
        app = AppTest.from_file(str(APP_PATH)).run(timeout=30)
        app.button[0].click().run(timeout=30)  # Q1.15: W=16, F=15.

        for title in ("Entrada x[n]", "Coeficientes h[k]", "Salida y[n]"):
            app.number_input(key=f"{title}-w").set_value(9).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(app.number_input(key=f"{title}-f").value, 8, title)

        app.checkbox(key="Entrada x[n]-signed").set_value(False).run(timeout=30)
        app.number_input(key="Entrada x[n]-f").set_value(9).run(timeout=30)
        app.checkbox(key="Entrada x[n]-signed").set_value(True).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.number_input(key="Entrada x[n]-f").value, 8)

        app.checkbox(key="customize-internal").set_value(True).run(timeout=30)
        for title in ("Producto x·h", "Acumulador"):
            app.number_input(key=f"{title}-w").set_value(9).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(app.number_input(key=f"{title}-f").value, 8, title)

    def test_examples_load_and_the_overflow_cases_change_policy(self) -> None:
        app = AppTest.from_file(str(APP_PATH)).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(
            [button.label for button in app.button][:5],
            ["Q1.15", "Pocos bits", "Saturación", "Wrap", "Todo sin signo"],
        )

        app.button[2].click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox(key="signal-kind").value, "Paso")
        self.assertEqual(app.selectbox(key="overflow-mode").value, "saturate")

        app.button[3].click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox(key="overflow-mode").value, "wrap")

        app.button[4].click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.segmented_control(key="design-mode").value, "Media móvil")
        for title in ("Entrada x[n]", "Coeficientes h[k]", "Salida y[n]"):
            self.assertFalse(app.checkbox(key=f"{title}-signed").value)
            self.assertEqual(app.number_input(key=f"{title}-w").value, 16)
            self.assertEqual(app.number_input(key=f"{title}-f").value, 16)
        self.assertEqual(app.number_input(key="signal-amplitude").value, 0.4)
        self.assertTrue(any("No hubo desbordamientos" in message.value for message in app.success))

        app.segmented_control(key="design-mode").set_value("Paso alto por ventana").run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.slider(key="windowed-taps").value, 31)


if __name__ == "__main__":
    unittest.main()
