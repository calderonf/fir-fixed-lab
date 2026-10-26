"""Lanzador local de Windows para el Laboratorio FIR de punto fijo.

El ejecutable empaquetado inicia Streamlit en 127.0.0.1 y abre el navegador
predeterminado. La interfaz sigue siendo web, pero el proceso y los puertos
seriales pertenecen al computador del estudiante.
"""

from __future__ import annotations

import atexit
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser


STARTUP_TIMEOUT_SECONDS = 30


def _resource_path(relative_path: str) -> Path:
    """Localiza recursos junto al ejecutable PyInstaller o en desarrollo."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return bundle_root / relative_path


def _available_local_port() -> int:
    """Reserva brevemente un puerto local libre y devuelve su número."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _server_command(port: int) -> list[str]:
    """Construye el comando hijo, también utilizable al probar sin empaquetar."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--serve", str(port)]
    return [sys.executable, str(Path(__file__).resolve()), "--serve", str(port)]


def _run_streamlit_server(port: int) -> None:
    """Ejecuta Streamlit en el hijo; esta llamada no retorna hasta cerrar la app."""
    project_root = _resource_path("")
    app_path = _resource_path("firlab/app.py")
    if not app_path.is_file():
        raise RuntimeError(f"No se encontró la aplicación: {app_path}")
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from streamlit.web import cli as streamlit_cli

    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--server.address=127.0.0.1",
        "--server.port",
        str(port),
        "--server.headless=true",
        "--server.runOnSave=false",
        "--browser.gatherUsageStats=false",
    ]
    streamlit_cli.main()


def _wait_for_server(port: int, process: subprocess.Popen[object]) -> bool:
    """Espera a que Streamlit acepte conexiones sin abrir el navegador demasiado pronto."""
    health_url = f"http://127.0.0.1:{port}/_stcore/health"
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urlopen(health_url, timeout=1) as response:
                if response.read().strip() == b"ok":
                    return True
        except (OSError, URLError):
            time.sleep(0.25)
    return False


def _stop(process: subprocess.Popen[object]) -> None:
    """Detiene el servidor hijo cuando se cierra el lanzador."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _start_launcher() -> int:
    port = _available_local_port()
    project_root = _resource_path("")
    process: subprocess.Popen[object] = subprocess.Popen(
        _server_command(port),
        cwd=project_root,
    )
    atexit.register(_stop, process)

    url = f"http://127.0.0.1:{port}"
    print("Laboratorio FIR de punto fijo")
    print("Iniciando la interfaz local…")
    if not _wait_for_server(port, process):
        print("No fue posible iniciar la aplicación. Cierra esta ventana y vuelve a intentarlo.")
        return 1

    print(f"Abriendo {url}")
    print("Cierra esta ventana para detener el laboratorio.")
    webbrowser.open(url)
    try:
        return int(process.wait())
    except KeyboardInterrupt:
        return 0


def main() -> int:
    arguments = sys.argv[1:]
    if arguments[:1] == ["--serve"]:
        if len(arguments) != 2:
            print("Uso interno inválido del lanzador.", file=sys.stderr)
            return 2
        try:
            port = int(arguments[1])
        except ValueError:
            print("Puerto interno inválido.", file=sys.stderr)
            return 2
        _run_streamlit_server(port)
        return 0
    return _start_launcher()


if __name__ == "__main__":
    raise SystemExit(main())
