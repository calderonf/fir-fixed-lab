# Instalar y usar el Laboratorio FIR de punto fijo en Debian o Ubuntu

Esta guía ejecuta la aplicación localmente desde el código fuente. La interfaz
se abre en el navegador, pero Python permanece en el computador; por eso puede
acceder al puerto USB/serial de una tarjeta conectada.

## Requisitos

- Debian 12, Ubuntu 22.04 o una versión posterior compatible.
- Python 3.10 o superior.
- Un navegador moderno.

Instale Python, `venv` y las herramientas necesarias:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip git
```

## Instalación

Clone el repositorio y cree un entorno aislado:

```bash
git clone https://github.com/calderonf/fir-fixed-lab.git
cd fir-fixed-lab
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Inicie la aplicación:

```bash
python -m streamlit run firlab/app.py
```

Abra la dirección que aparece en la terminal, normalmente
`http://localhost:8501`. Para detenerla, vuelva a la terminal y pulse
`Ctrl+C`.

En una sesión posterior basta con entrar al repositorio, activar el entorno y
ejecutar el último comando:

```bash
cd fir-fixed-lab
source .venv/bin/activate
python -m streamlit run firlab/app.py
```

## Puerto serial

En muchos sistemas Linux el usuario debe pertenecer al grupo `dialout` para
abrir dispositivos como `/dev/ttyACM0` o `/dev/ttyUSB0`:

```bash
sudo usermod -aG dialout "$USER"
```

Después cierre la sesión gráfica y entre de nuevo (o reinicie) para que el
grupo tenga efecto. Antes de usar la prueba de hardware, cierre Arduino IDE,
Serial Monitor, Thonny, `mpremote` y cualquier terminal que esté usando el
puerto. Consulte también [la guía de hardware](HARDWARE.md).

## Actualizar

Desde la carpeta del repositorio:

```bash
git pull --ff-only
source .venv/bin/activate
python -m pip install -e .
```

Si no desea conservar modificaciones locales, no use `git pull` a ciegas:
guárdelas o revíselas primero con `git status`.
