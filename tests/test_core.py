import unittest

import numpy as np

from firlab.export_arduino import build_arduino_export, build_arduino_serial_export
from firlab.export_micropython import (
    build_micropython_impulse_export,
    build_micropython_serial_export,
)
from firlab.fir import (
    FIRConfiguration,
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
from firlab.serial_protocol import PING_REPLY, process_samples_sequentially


class FixedPointTests(unittest.TestCase):
    def test_micropython_runtime_matches_the_bit_exact_fir_simulation(self) -> None:
        input_format = FixedFormat(True, 8, 5)
        coefficient_format = FixedFormat(True, 8, 6)
        output_format = FixedFormat(True, 9, 5)
        configuration = FIRConfiguration(
            input_format,
            coefficient_format,
            output_format,
            RoundingMode.CONVERGENT,
            OverflowMode.WRAP,
            product_format=FixedFormat(True, 11, 8),
            accumulator_format=FixedFormat(True, 12, 8),
        )
        coefficients = np.array([0.5, -0.25, 0.125])
        signal = np.array([0.8, -0.7, 0.5, 0.0, -0.25])
        expected = simulate_fir(coefficients, signal, configuration)
        export = build_micropython_impulse_export(coefficients, configuration)

        namespace: dict[str, object] = {}
        exec(export.config, namespace)
        exec(export.runtime, namespace)
        pico_filter = namespace["FirFixed"](namespace["COEFFICIENTS_RAW"], namespace["CONFIG"])
        actual = [pico_filter.process(int(raw)) for raw in expected.input_raw]

        self.assertEqual(actual, list(expected.output_raw))
        compile(export.main, "main.py", "exec")

    def test_micropython_serial_export_uses_the_same_protocol_as_arduino(self) -> None:
        q = FixedFormat(True, 16, 15)
        export = build_micropython_serial_export(np.array([0.5, 0.5]), FIRConfiguration(q, q, q))

        self.assertIn("MicroPython v1.29.0", export.main)
        self.assertIn('command == "PING"', export.main)
        self.assertIn('reply("^..^")', export.main)
        self.assertIn('command == "RESET"', export.main)
        self.assertIn('command == "INFO"', export.main)
        self.assertIn("FIR_SERIAL_READY", export.main)
        self.assertIn("x_raw,y_raw", export.main)
        self.assertIn("apply_overflow", export.runtime)

    def test_arduino_serial_sketch_exposes_the_line_protocol_and_ascii_ping(self) -> None:
        q = FixedFormat(True, 16, 12)
        export = build_arduino_serial_export(np.array([0.5, 0.5]), FIRConfiguration(q, q, q))
        self.assertIn("PC -> Arduino:  x_raw", export.sketch)
        self.assertIn("Arduino -> PC:  x_raw,y_raw", export.sketch)
        self.assertIn('strcmp(line, "PING")', export.sketch)
        self.assertIn('Serial.println(F("^..^"));', export.sketch)
        self.assertIn('strcmp(line, "RESET")', export.sketch)
        self.assertIn('strcmp(line, "INFO")', export.sketch)
        self.assertIn("FIR_SERIAL_READY", export.sketch)
        self.assertNotIn("String", export.sketch)

    def test_serial_client_waits_for_each_response_and_resets_first(self) -> None:
        class FakeSerial:
            def __init__(self, *_args, **_kwargs) -> None:
                self.responses: list[bytes] = []
                self.commands: list[str] = []
                self.buffer_was_reset = False

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def reset_input_buffer(self) -> None:
                self.buffer_was_reset = True

            def write(self, payload: bytes) -> None:
                command = payload.decode("ascii").strip()
                self.commands.append(command)
                if command == "PING":
                    self.responses.append((PING_REPLY + "\n").encode("ascii"))
                elif command == "RESET":
                    self.responses.append(b"OK\n")
                else:
                    self.responses.append(f"{command},{int(command) + 1}\n".encode("ascii"))

            def flush(self) -> None:
                return None

            def readline(self) -> bytes:
                return self.responses.pop(0)

        instances: list[FakeSerial] = []

        def factory(*args, **kwargs) -> FakeSerial:
            device = FakeSerial(*args, **kwargs)
            instances.append(device)
            return device

        output = process_samples_sequentially(
            "/dev/fake",
            np.array([3, -4, 0]),
            serial_factory=factory,
            sleep=lambda _seconds: None,
        )
        np.testing.assert_array_equal(output, [4, -3, 1])
        self.assertTrue(instances[0].buffer_was_reset)
        self.assertEqual(instances[0].commands, ["PING", "RESET", "3", "-4", "0"])

    def test_internal_precision_analysis_distinguishes_theoretical_and_actual_signed_ranges(self) -> None:
        input_format = FixedFormat(True, 4, 2)  # raw: -8 … 7
        coefficient_format = FixedFormat(True, 4, 2)  # raw: -8 … 7
        configuration = FIRConfiguration(
            input_format,
            coefficient_format,
            FixedFormat(True, 8, 2),
            product_format=FixedFormat(True, 8, 4),
            accumulator_format=FixedFormat(True, 10, 4),
        )

        analysis = analyze_internal_precision(np.array([0.5, -0.25]), configuration)

        # Teórico: las cuatro esquinas de [-8, 7] × [-8, 7].
        self.assertEqual(
            (analysis.product_theoretical.raw_min, analysis.product_theoretical.raw_max), (-56, 64)
        )
        self.assertEqual(analysis.product_theoretical.required_word_length, 8)
        # Real: h raw = [2, -1], no los extremos [-8, 7] del formato h.
        self.assertEqual((analysis.product_actual.raw_min, analysis.product_actual.raw_max), (-16, 14))
        self.assertEqual(analysis.product_actual.required_word_length, 5)
        # Acumulador: 2·[-56, 64] frente a (-16 + -7, 14 + 8).
        self.assertEqual(
            (analysis.accumulator_theoretical.raw_min, analysis.accumulator_theoretical.raw_max),
            (-112, 128),
        )
        self.assertEqual((analysis.accumulator_actual.raw_min, analysis.accumulator_actual.raw_max), (-23, 22))
        self.assertEqual(analysis.accumulator_actual.required_word_length, 6)
        self.assertEqual(analysis.actual_contributions[1].input_for_min_raw, 7)

    def test_internal_precision_analysis_supports_unsigned_formats(self) -> None:
        unsigned = FixedFormat(False, 3, 0)  # raw: 0 … 7
        configuration = FIRConfiguration(
            unsigned,
            unsigned,
            FixedFormat(False, 8, 0),
            product_format=FixedFormat(False, 6, 0),
            accumulator_format=FixedFormat(False, 8, 0),
        )

        analysis = analyze_internal_precision(np.array([1.0, 2.0]), configuration)

        self.assertEqual((analysis.product_theoretical.raw_min, analysis.product_theoretical.raw_max), (0, 49))
        self.assertEqual(analysis.product_theoretical.required_word_length, 6)
        self.assertEqual((analysis.product_actual.raw_min, analysis.product_actual.raw_max), (0, 14))
        self.assertEqual(analysis.product_actual.required_word_length, 4)
        self.assertEqual(
            (analysis.accumulator_theoretical.raw_min, analysis.accumulator_theoretical.raw_max), (0, 98)
        )
        self.assertEqual((analysis.accumulator_actual.raw_min, analysis.accumulator_actual.raw_max), (0, 21))
        self.assertEqual(analysis.accumulator_actual.required_word_length, 5)

    def test_exact_product_bounds_do_not_change_with_the_selected_product_register(self) -> None:
        input_format = FixedFormat(True, 4, 2)
        coefficient_format = FixedFormat(True, 4, 2)
        coefficients = np.array([0.5, -0.25])
        wide_registers = FIRConfiguration(
            input_format,
            coefficient_format,
            FixedFormat(True, 8, 2),
            product_format=FixedFormat(True, 12, 4),
            accumulator_format=FixedFormat(True, 14, 4),
        )
        narrow_fraction_registers = FIRConfiguration(
            input_format,
            coefficient_format,
            FixedFormat(True, 8, 2),
            product_format=FixedFormat(True, 6, 1),
            accumulator_format=FixedFormat(True, 8, 0),
        )

        wide = analyze_internal_precision(coefficients, wide_registers)
        narrow_fraction = analyze_internal_precision(coefficients, narrow_fraction_registers)

        self.assertEqual(
            (wide.product_theoretical.raw_min, wide.product_theoretical.raw_max),
            (narrow_fraction.product_theoretical.raw_min, narrow_fraction.product_theoretical.raw_max),
        )
        self.assertEqual(
            wide.product_actual.required_word_length,
            narrow_fraction.product_actual.required_word_length,
        )
        # Sólo la comprobación del registro cambia de escala raw al cambiar F.
        self.assertNotEqual(
            wide.product_actual_in_register.raw_max,
            narrow_fraction.product_actual_in_register.raw_max,
        )

    def test_signed_q_range_and_wrap(self) -> None:
        q = FixedFormat(True, 4, 2)
        self.assertEqual(q.minimum, -2.0)
        self.assertEqual(q.maximum, 1.75)
        self.assertEqual(q.apply_overflow(8, OverflowMode.WRAP), (-8, True))

    def test_matlab_and_q_notations_agree(self) -> None:
        q = FixedFormat(True, 8, 7)
        self.assertEqual(q.q_notation, "Q0.7")
        self.assertEqual(q.matlab_notation, "numerictype(1, 8, 7)")

    def test_fir_matches_simple_average(self) -> None:
        q = FixedFormat(True, 8, 6)
        configuration = FIRConfiguration(q, q, q, RoundingMode.NEAREST, OverflowMode.SATURATE)
        result = simulate_fir(np.array([0.5, 0.5]), np.array([1.0, 1.0, 0.0]), configuration)
        np.testing.assert_allclose(result.output, [0.5, 1.0, 0.5])

    def test_export_describes_scaling(self) -> None:
        q = FixedFormat(True, 16, 12)
        export = build_arduino_export(np.array([0.5, 0.5]), FIRConfiguration(q, q, q))
        self.assertIn("Ganancia DC", export.header)
        self.assertIn("FIR_ACCUMULATOR_TO_OUTPUT_SHIFT", export.header)
        self.assertIn("class FirFixed", export.runtime)

    def test_arduino_sketch_explains_equation_formats_and_raw_conversion(self) -> None:
        q = FixedFormat(True, 16, 12)
        export = build_arduino_export(np.array([0.5, 0.5]), FIRConfiguration(q, q, q))
        self.assertIn("ECUACIÓN DE ESTE FIR (2 taps)", export.sketch)
        self.assertIn("(2048/2^12)·x[n]", export.sketch)
        self.assertIn("FORMATOS DE LOS REGISTROS RAW", export.sketch)
        self.assertIn("xRaw y delayLine[k]: int32_t; Q3.12", export.sketch)
        self.assertIn("productRaw: int64_t; Q7.24", export.sketch)
        self.assertIn("CORRIMIENTO", export.sketch)
        self.assertIn("EJEMPLOS RAW -> REAL", export.sketch)
        self.assertIn("y_real = yRaw / 2^12", export.sketch)

    def test_arduino_sketch_explains_left_shift_when_output_has_more_fraction_bits(self) -> None:
        source = FixedFormat(True, 8, 4)
        output = FixedFormat(True, 16, 10)
        export = build_arduino_export(np.array([0.5, 0.5]), FIRConfiguration(source, source, output))
        self.assertIn("corrimiento a la izquierda de 2 bits", export.sketch)

    def test_export_allows_32_bit_signed_output(self) -> None:
        q = FixedFormat(True, 16, 15)
        output = FixedFormat(True, 32, 30)
        export = build_arduino_export(np.array([0.5, 0.5]), FIRConfiguration(q, q, output))
        self.assertIn("{32, 30, true}", export.header)

    def test_lowpass_is_normalized(self) -> None:
        coefficients = design_lowpass(1_000, 100, 31, "hamming")
        self.assertAlmostEqual(float(coefficients.sum()), 1.0, places=12)

    def test_highpass_rejects_dc_and_has_unity_gain_at_nyquist(self) -> None:
        coefficients = design_highpass(1_000, 100, 31, "hamming")
        frequency, response = frequency_response(coefficients)
        low_frequency = int(np.argmin(np.abs(frequency - 0.05)))
        high_frequency = int(np.argmin(np.abs(frequency - 0.4)))
        self.assertLess(abs(response[0]), 0.01)
        self.assertAlmostEqual(abs(response[-1]), 1.0, places=12)
        self.assertLess(abs(response[low_frequency]), abs(response[high_frequency]))
        np.testing.assert_allclose(coefficients, coefficients[::-1])

    def test_highpass_supports_even_taps_with_antisymmetric_response(self) -> None:
        coefficients = design_highpass(1_000, 100, 30, "hamming")
        _, response = frequency_response(coefficients)
        self.assertLess(abs(response[0]), 1e-12)
        self.assertAlmostEqual(abs(response[-1]), 1.0, places=12)
        np.testing.assert_allclose(coefficients, -coefficients[::-1])

    def test_impulse_response_uses_zero_initial_states(self) -> None:
        """Con un impulso unitario, y[n] debe reproducir los coeficientes."""
        q = FixedFormat(True, 12, 8)  # +1 se representa exactamente.
        configuration = FIRConfiguration(q, q, FixedFormat(True, 24, 16))
        coefficients = np.array([0.25, -0.5, 0.125])
        result = simulate_fir(coefficients, test_signal("Impulso", 6, 1_000, amplitude=1.0), configuration)
        np.testing.assert_allclose(result.output[:3], result.coefficient_values, atol=1 / 2**16)
        np.testing.assert_array_equal(result.output[3:], np.zeros(3))

    def test_recommended_output_preserves_product_fraction(self) -> None:
        x = FixedFormat(True, 8, 4)
        h = FixedFormat(True, 8, 5)
        configuration = FIRConfiguration(x, h, FixedFormat(True, 8, 4))
        recommendation = recommend_output_format(np.array([16, -8, 16]), configuration)
        self.assertTrue(recommendation.signed)
        self.assertEqual(recommendation.fraction_length, 9)
        self.assertGreaterEqual(recommendation.word_length, 1)

    def test_recommended_output_is_valid_when_quantized_coefficients_are_zero(self) -> None:
        q = FixedFormat(True, 8, 7)
        configuration = FIRConfiguration(q, q, q)
        recommendation = recommend_output_format(np.zeros(4, dtype=np.int64), configuration)
        self.assertEqual(recommendation.fraction_length, 14)
        self.assertGreaterEqual(recommendation.word_length, 15)

    def test_sample_trace_reproduces_simulated_output(self) -> None:
        q = FixedFormat(True, 8, 6)
        configuration = FIRConfiguration(q, q, q)
        coefficients = np.array([0.5, 0.5])
        signal = np.array([1.0, 1.0, 0.0])
        simulation = simulate_fir(coefficients, signal, configuration)
        trace = trace_fir_sample(coefficients, signal, configuration, sample_index=1)
        self.assertEqual(trace.output_raw, int(simulation.output_raw[1]))
        self.assertEqual(trace.accumulator_raw, trace.rows[-1].accumulator_raw)
        self.assertEqual([row.input_raw for row in trace.rows], [64, 64])
        self.assertEqual([row.coefficient_raw for row in trace.rows], [32, 32])

    def test_overflow_events_keep_stage_and_stored_raw_value(self) -> None:
        q = FixedFormat(True, 4, 0)
        configuration = FIRConfiguration(q, q, q, overflow=OverflowMode.SATURATE)
        result = simulate_fir(np.array([2.0]), np.array([7.0]), configuration)
        output_events = [event for event in result.overflow_events if event.stage == "Salida"]
        self.assertEqual(len(output_events), 1)
        self.assertEqual((output_events[0].raw_before, output_events[0].raw_after), (14, 7))

    def test_product_overflow_is_reported_separately(self) -> None:
        q = FixedFormat(True, 4, 0)
        configuration = FIRConfiguration(
            q,
            q,
            q,
            product_format=FixedFormat(True, 4, 0),
        )
        result = simulate_fir(np.array([2.0]), np.array([7.0]), configuration)
        product_events = [event for event in result.overflow_events if event.stage == "Producto"]
        self.assertEqual(len(product_events), 1)
        self.assertEqual((product_events[0].raw_before, product_events[0].raw_after), (14, 7))

    def test_unipolar_test_signals_do_not_inject_negative_samples(self) -> None:
        cosine = test_signal("Coseno", 64, 1_000, amplitude=0.8, frequency_hz=50, unipolar=True)
        noise = test_signal("Ruido", 64, 1_000, amplitude=0.8, unipolar=True)
        self.assertGreaterEqual(float(cosine.min()), 0.0)
        self.assertLessEqual(float(cosine.max()), 1.6)
        self.assertGreaterEqual(float(noise.min()), 0.0)
        self.assertLessEqual(float(noise.max()), 0.8)

    def test_centered_cosine_is_preserved_for_signed_inputs(self) -> None:
        cosine = test_signal("Coseno", 64, 1_000, amplitude=0.8, frequency_hz=50)
        self.assertLess(float(cosine.min()), 0.0)

    def test_unsigned_moving_average_preset_has_no_overflows(self) -> None:
        unsigned_q016 = FixedFormat(False, 16, 16)
        configuration = FIRConfiguration(unsigned_q016, unsigned_q016, unsigned_q016)
        coefficients = np.full(31, 1.0 / 31)
        signal = test_signal("Coseno", 256, 1_000, amplitude=0.4, frequency_hz=50, unipolar=True)
        result = simulate_fir(coefficients, signal, configuration)
        self.assertEqual(result.overflow_events, ())
        self.assertTrue(np.all(result.coefficient_values >= 0))

    def test_unsigned_moving_average_is_a_normalized_rectangular_fir(self) -> None:
        taps = 31
        coefficients = np.full(taps, 1.0 / taps)
        frequency, response = frequency_response(coefficients)
        self.assertTrue(np.all(coefficients >= 0.0))
        self.assertAlmostEqual(float(coefficients.sum()), 1.0)
        self.assertEqual(float(frequency[0]), 0.0)
        self.assertAlmostEqual(abs(response[0]), 1.0)

    def test_unsigned_moving_average_preset_is_safe_for_all_test_signals(self) -> None:
        unsigned_q016 = FixedFormat(False, 16, 16)
        configuration = FIRConfiguration(unsigned_q016, unsigned_q016, unsigned_q016)
        coefficients = np.full(31, 1.0 / 31)
        self.assertFalse(configuration.resolved_product_format().signed)
        self.assertFalse(configuration.resolved_accumulator_format(len(coefficients)).signed)
        for signal_kind in ("Impulso", "Paso", "Coseno", "Ruido"):
            signal = test_signal(
                signal_kind,
                256,
                1_000,
                amplitude=0.4,
                frequency_hz=50,
                unipolar=True,
            )
            result = simulate_fir(coefficients, signal, configuration)
            self.assertEqual(result.overflow_events, (), signal_kind)
            self.assertGreaterEqual(float(result.output.min()), 0.0)
            self.assertLessEqual(float(result.output.max()), unsigned_q016.maximum)


if __name__ == "__main__":
    unittest.main()
