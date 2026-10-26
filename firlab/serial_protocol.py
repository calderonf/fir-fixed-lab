"""Cliente del protocolo didáctico de ``FIRFixedSerial.ino``.

El módulo no importa pyserial al cargarse: así el laboratorio y sus pruebas
numéricas siguen funcionando en equipos que todavía no conectan hardware.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import time

import numpy as np


PING_REPLY = "^..^"
READY_REPLY = "FIR_SERIAL_READY"


class SerialProtocolError(RuntimeError):
    """El Arduino respondió una línea distinta del contrato acordado."""


def parse_sample_reply(reply: str) -> tuple[int, int]:
    """Convierte la respuesta ``x_raw,y_raw`` en dos enteros Python."""
    parts = reply.strip().split(",")
    if len(parts) != 2:
        raise SerialProtocolError(f"Respuesta serial inválida: {reply!r}")
    try:
        return int(parts[0]), int(parts[1])
    except ValueError as error:
        raise SerialProtocolError(f"La respuesta no contiene dos enteros raw: {reply!r}") from error


def _read_line(device) -> str:
    raw = device.readline()
    if not raw:
        raise SerialProtocolError("No llegó respuesta del Arduino antes del tiempo límite.")
    return raw.decode("ascii", errors="replace").strip()


def _send_line(device, line: str) -> str:
    device.write((line + "\n").encode("ascii"))
    device.flush()
    return _read_line(device)


def process_samples_sequentially(
    port: str,
    samples_raw: Sequence[int] | np.ndarray,
    *,
    baudrate: int = 115200,
    timeout_seconds: float = 2.0,
    startup_seconds: float = 2.0,
    serial_factory: Callable[..., object] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_sample: Callable[[int, int], None] | None = None,
) -> np.ndarray:
    """Envía una muestra raw y espera su respuesta antes de enviar la siguiente.

    Abrir el puerto suele reiniciar un Arduino Uno por DTR; por eso se espera y
    se descarta el saludo antes de pedir ``PING``. El estado se reinicia con
    ``RESET`` para que el experimento coincida con la simulación de estados
    iniciales nulos.
    """
    if serial_factory is None:
        try:
            import serial
        except ImportError as error:
            raise RuntimeError(
                "Falta pyserial. Instálalo con `python -m pip install pyserial`."
            ) from error
        serial_factory = serial.Serial

    expected_inputs = np.asarray(samples_raw, dtype=np.int64)
    if expected_inputs.ndim != 1:
        raise ValueError("Las muestras seriales deben ser un vector unidimensional.")

    with serial_factory(port, baudrate=baudrate, timeout=timeout_seconds, write_timeout=timeout_seconds) as device:
        sleep(startup_seconds)
        device.reset_input_buffer()
        if _send_line(device, "PING") != PING_REPLY:
            raise SerialProtocolError(
                f"El puerto no respondió {PING_REPLY!r}. Verifica que tenga FIRFixedSerial.ino."
            )
        if _send_line(device, "RESET") != "OK":
            raise SerialProtocolError("El Arduino no confirmó RESET.")

        output_raw: list[int] = []
        for index, sample in enumerate(expected_inputs):
            expected_x = int(sample)
            received_x, received_y = parse_sample_reply(_send_line(device, str(expected_x)))
            if received_x != expected_x:
                raise SerialProtocolError(
                    f"El Arduino devolvió x_raw={received_x}, pero se envió {expected_x}."
                )
            output_raw.append(received_y)
            if on_sample is not None:
                on_sample(index + 1, len(expected_inputs))
    return np.asarray(output_raw, dtype=np.int64)
