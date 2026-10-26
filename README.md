# Laboratorio FIR de punto fijo

Aplicación didáctica para diseñar, cuantizar, simular y llevar filtros FIR a
hardware de bajo costo. Está diseñada para explicar qué representa cada entero,
no sólo para obtener coeficientes.

> La aplicación se distribuye para ejecutarse **localmente** en Windows. Así
> conserva acceso al puerto USB/serial de Arduino, Raspberry Pi Pico y ESP32,
> mientras el estudiante usa la interfaz en su navegador.

## Empezar

| Para… | Consulte… |
| --- | --- |
| Instalar y usar la aplicación en Windows | [Guía de instalación para Windows](docs/INSTALACION_WINDOWS.md) |
| Conectar y validar una tarjeta | [Hardware, exportaciones y protocolo serial](docs/HARDWARE.md) |
| Ejecutar, probar o publicar una versión desde el código fuente | [Guía de desarrollo y lanzamientos](docs/DESARROLLO.md) |
| Estudiar formatos `W`, `F/QF`, `QI`, signo y desbordamiento | [Presentación de punto fijo](output/pdf/formatos_punto_fijo.pdf) |

La descarga oficial se publicará en la pestaña [Releases](../../releases) como
`FIR-Fixed-Lab-Setup-<versión>-Windows-x64.exe`. Descargue el instalador desde
allí, no desde copias recibidas por mensajería.

## Incluye

- Diseño FIR pasobajo por ventanas: rectangular, Hann, Hamming, Blackman y
  Kaiser.
- Formatos de punto fijo explícitos: signo, longitud de palabra `W`, longitud
  fraccionaria `F`/`QF` y bits enteros `QI`.
- Rango mínimo/máximo y LSB de entrada, coeficientes y salida.
- Simulación de entrada, producto, acumulador y salida con redondeo y
  saturación o wrap.
- Respuesta al impulso, paso, coseno y ruido; respuesta en frecuencia ideal y
  cuantizada.
- Taps y orden mostrados por separado; admite números pares e impares de taps.
- Recomendación conservadora de formato para la salida a partir de los formatos
  de entrada y coeficientes.
- Ganancia DC ideal y cuantizada, más la explicación del reescalamiento a la
  salida.
- Dos exportaciones Arduino: respuesta impulso y FIR interactivo por Serial;
  ambas incluyen `fir_config.h` y `FIRFixed.h`.

## Idea numérica central

Un entero `raw` con `F` bits fraccionarios representa:

```text
valor_real = raw / 2^F
```

Así, si la entrada tiene `F_x` y el coeficiente `F_h`, el producto tiene
`F_x + F_h`. El acumulador conserva esa escala. Si la salida elegida tiene
`F_y`, la conversión de acumulador a salida debe desplazar:

```text
shift = F_acumulador - F_salida
```

Un `shift` positivo descarta bits fraccionarios; esa operación siempre utiliza
el redondeo y overflow seleccionados. El exportador escribe esta explicación y
el valor del corrimiento en el archivo generado, de modo que no haya un
"`>> 8`" sin justificación.

## Ejecutar desde el código fuente

Requiere Python 3.10 o superior.

```bash
cd fir_fixed_lab
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
streamlit run firlab/app.py
```

Para validar el núcleo numérico:

```bash
python -m unittest discover -s tests -v
```

## Arduino

La exportación está pensada para Arduino Uno: los formatos con signo de
entrada, coeficientes y salida pueden usar hasta 32 bits; los formatos sin
signo, hasta 31 bits, porque el runtime almacena los valores raw en `int32_t`.
Producto y acumulador pueden usar hasta 60 bits internamente. El Uno emula
`int64_t` por software, así que formatos anchos privilegian claridad y
exactitud antes que velocidad.

Los tres archivos exportados deben quedar juntos en una carpeta de sketch:

```text
MiFiltro/
├── FIRFixedImpulse.ino
├── FIRFixed.h
└── fir_config.h
```

La demostración `FIRFixedImpulse.ino` imprime `entrada_raw,salida_raw`. Estos
valores deben coincidir muestra a muestra con la simulación Python para la
respuesta impulso.

### FIR interactivo por Serial

`FIRFixedSerial.zip` contiene un segundo sketch, `FIRFixedSerial.ino`. Recibe una muestra **raw** por línea y responde antes de recibir la siguiente:

```text
PC -> Arduino:  x_raw\n
Arduino -> PC:  x_raw,y_raw\n
```

Usar enteros raw conserva exactamente la misma cuantización que la simulación:

```text
x_real = x_raw / 2^F_x
y_real = y_raw / 2^F_y
```

El sketch también acepta `RESET` (borra los retardos), `INFO` y `PING`, que responde `^..^`. La aplicación abre el puerto, hace `PING`, envía `RESET` y espera una respuesta por cada muestra; así no llena el buffer serial del Uno.

Antes de la prueba desde la aplicación, cierre Arduino IDE, Serial Monitor y Serial Plotter: sólo una aplicación puede usar el puerto serial a la vez. La prueba valida la aritmética y los estados FIR, pero no representa una frecuencia de muestreo de tiempo real porque el enlace USB/serial introduce esperas.

## Hardware MicroPython soportado y probado

Hay dos descargas adicionales de MicroPython, dirigidas a MicroPython v1.29.0
o posterior. Se han probado en hardware con:

- Raspberry Pi Pico (RP2040).
- Raspberry Pi Pico H (RP2040).
- Raspberry Pi Pico 2.
- ESP32-S, incluida la ESP32-CAM, usando el firmware `Generic ESP32 module with ESP32`.

Los ZIP conservan sus nombres históricos de Pico, pero el mismo código
MicroPython y protocolo serial se usan en las tarjetas de la lista:

- `FIRPicoImpulse.zip`: imprime la respuesta al impulso.
- `FIRPicoSerial.zip`: recibe y procesa muestras por USB serial.

Cada ZIP contiene tres archivos que deben copiarse juntos al sistema de
archivos de la tarjeta con Thonny, `mpremote` o una herramienta equivalente:

```text
placa/
├── main.py
├── fir_config.py
└── fir_fixed.py
```

`main.py` se ejecuta al reiniciar la tarjeta. La versión serial usa exactamente
el mismo protocolo que Arduino: `PING` responde `^..^`, `RESET` borra los
retardos, `INFO` informa el formato y cada `x_raw` recibe `x_raw,y_raw`.
Por ello la sección de prueba serial de la aplicación puede verificar cualquier
tarjeta de la lista sin cambios. Cierre Thonny, mpremote u otro terminal antes de que la aplicación
abra el puerto.

El runtime generado no usa flotantes para filtrar: aplica el mismo redondeo,
saturación o wrap en entrada, producto, acumulador y salida que el simulador.

Para una lista completa de tarjetas comprobadas, pasos de carga y el protocolo
serial, consulte [la guía de hardware](docs/HARDWARE.md).

## Organización del repositorio

```text
firlab/                 Aplicación Streamlit y núcleo numérico bit-exacto.
tests/                  Pruebas automáticas del núcleo y de la interfaz.
material_docente/       Fuente LaTeX de la presentación de punto fijo.
output/pdf/             PDF de la presentación e instrucciones para regenerarlo.
docs/                   Instalación, hardware y desarrollo.
packaging/windows/      Lanzador, build y script de Inno Setup.
.github/workflows/      Construcción automática del instalador Windows.
```

## Licencia

Copyright © 2026 Francisco Carlos Calderón. Este proyecto se distribuye bajo la
[GNU General Public License v3.0](LICENSE). Puede usarse, estudiarse,
modificarse y redistribuirse bajo sus condiciones; se ofrece sin garantía.
