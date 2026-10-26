# Desarrollo y lanzamientos

## Preparar el entorno

Se requiere Python 3.10 o superior. Desde la raíz del repositorio:

```bash
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Ejecute la interfaz local:

```bash
python -m streamlit run firlab/app.py
```

Ejecute todas las pruebas antes de enviar cambios:

```bash
python -m unittest discover -s tests -v
```

## Estructura y responsabilidades

- `firlab/fixed_point.py`: formatos, cuantización, redondeo y overflow.
- `firlab/fir.py`: diseño FIR, análisis de precisión y simulador bit-exacto.
- `firlab/app.py`: interfaz Streamlit y exportaciones descargables.
- `firlab/export_arduino.py`: programas C++ para Arduino.
- `firlab/export_micropython.py`: programas MicroPython.
- `firlab/serial_protocol.py`: cliente Python del protocolo de prueba.
- `tests/`: pruebas del núcleo, exportadores y recorridos de la interfaz.
- `packaging/windows/`: artefactos para construir el instalador de Windows.

## Construir el instalador manualmente en Windows

La construcción debe hacerse en Windows porque PyInstaller genera binarios para
la plataforma donde se ejecuta. Instale Python 3.12 de 64 bits, Inno Setup y
después ejecute:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install . pyinstaller
choco install innosetup --no-progress --yes
python -m unittest discover -s tests -v
python packaging\windows\build_windows.py --version 0.1.0
```

El resultado queda en:

```text
release/FIR-Fixed-Lab-Setup-0.1.0-Windows-x64.exe
```

El lanzador empaquetado mantiene el servidor en `127.0.0.1`, espera la ruta de
salud de Streamlit y abre el navegador sólo cuando la interfaz está lista.

## Construcción automática y Releases

El flujo [`.github/workflows/windows-release.yml`](../.github/workflows/windows-release.yml)
usa un runner `windows-latest` para:

1. Instalar dependencias y PyInstaller.
2. Ejecutar la suite de pruebas.
3. Construir el bundle PyInstaller y el instalador Inno Setup.
4. Conservar el instalador como artefacto de CI.
5. Crear una GitHub Release automáticamente cuando se publique una etiqueta
   que empiece por `v`.

Para publicar una versión estable, después de revisar pruebas y documentación:

```bash
git checkout main
git pull --ff-only
git tag -a v0.1.0 -m "Laboratorio FIR de punto fijo v0.1.0"
git push origin v0.1.0
```

Cuando finalice el workflow, la sección Releases contendrá el instalador
`FIR-Fixed-Lab-Setup-0.1.0-Windows-x64.exe` y notas generadas por GitHub.

## Lista de verificación antes de etiquetar

- [ ] Todas las pruebas automáticas pasan.
- [ ] La aplicación abre y sus descargas contienen los archivos esperados.
- [ ] Se comprobó el instalador en Windows 10 u 11 sin Python previamente
      instalado.
- [ ] Se probó la comparación serial en, como mínimo, una tarjeta Arduino y
      una tarjeta MicroPython.
- [ ] README, guía de Windows y tabla de hardware reflejan la versión real.
- [x] El repositorio incluye la licencia GNU GPL v3.0.

## Licencia y contribuciones

El proyecto está publicado bajo la [GNU GPL v3.0](../LICENSE). Las
contribuciones que se incorporen al repositorio deben ser compatibles con esa
licencia. El software se distribuye sin garantía, según se detalla en el
archivo `LICENSE`.
