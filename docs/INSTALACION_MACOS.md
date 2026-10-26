# Instalar y usar el Laboratorio FIR de punto fijo en macOS

Actualmente macOS se distribuye desde el código fuente. La aplicación se abre
en el navegador de este mismo equipo y conserva acceso local al puerto USB de
Arduino, Raspberry Pi Pico o ESP32.

## Requisitos

- macOS con Python 3.10 o superior.
- Git y un navegador moderno.

Compruebe la versión disponible:

```bash
python3 --version
```

Si no tiene Python 3.10 o posterior, instálelo desde
[python.org](https://www.python.org/downloads/macos/) y abra una Terminal
nueva antes de continuar. Si tampoco tiene Git, Xcode Command Line Tools suele
instalarlo con:

```bash
xcode-select --install
```

## Instalación y arranque

En Terminal ejecute:

```bash
git clone https://github.com/calderonf/fir-fixed-lab.git
cd fir-fixed-lab
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m streamlit run firlab/app.py
```

Abra la dirección que muestra Streamlit, normalmente `http://localhost:8501`.
Mantenga abierta esa ventana de Terminal mientras usa el laboratorio y pulse
`Ctrl+C` allí para detenerlo.

En usos posteriores:

```bash
cd fir-fixed-lab
source .venv/bin/activate
python -m streamlit run firlab/app.py
```

## Puerto serial

La primera vez macOS puede pedir permiso para que Terminal o el navegador
accedan a un accesorio USB. Acepte únicamente el permiso para la tarjeta que
conectó. Cierre Arduino IDE, Serial Monitor, Serial Plotter, Thonny, `mpremote`
y otros terminales antes de iniciar la prueba desde la aplicación: sólo un
programa puede abrir el puerto a la vez.

Para actualizar el código:

```bash
git pull --ff-only
source .venv/bin/activate
python -m pip install -e .
```

Consulte [la guía de hardware](HARDWARE.md) para cargar los programas
exportados y ejecutar la comparación muestra a muestra.
