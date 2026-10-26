"""Construye el instalador x64 de Windows desde una copia limpia del proyecto."""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "packaging" / "windows" / "fir_fixed_lab_launcher.py"
INSTALLER_SCRIPT = ROOT / "packaging" / "windows" / "FIRFixedLab.iss"


def _run(command: list[str]) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def _find_iscc() -> str:
    for candidate in ("iscc", "ISCC.exe"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise RuntimeError(
        "No se encontró Inno Setup. Instálalo desde https://jrsoftware.org/isinfo.php "
        "o ejecuta: choco install innosetup -y"
    )


def build(version: str) -> Path:
    """Genera el bundle PyInstaller y después el instalador de Inno Setup."""
    if sys.platform != "win32":
        raise RuntimeError("El instalador Windows debe construirse en Windows.")

    separator = os.pathsep
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--console",
            "--name",
            "FIR Fixed Lab",
            "--add-data",
            f"firlab{separator}firlab",
            "--collect-all",
            "streamlit",
            "--collect-all",
            "altair",
            "--collect-all",
            "numpy",
            "--collect-all",
            "pandas",
            "--collect-submodules",
            "serial",
            "--collect-submodules",
            "firlab",
            "--hidden-import",
            "serial.tools.list_ports",
            str(LAUNCHER),
        ]
    )
    _run([_find_iscc(), f"/DMyAppVersion={version}", str(INSTALLER_SCRIPT)])
    installer = ROOT / "release" / f"FIR-Fixed-Lab-Setup-{version}-Windows-x64.exe"
    if not installer.is_file():
        raise RuntimeError(f"Inno Setup no generó el instalador esperado: {installer}")
    return installer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Versión sin el prefijo v, por ejemplo 0.1.0")
    arguments = parser.parse_args()
    print(f"Instalador creado: {build(arguments.version)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
