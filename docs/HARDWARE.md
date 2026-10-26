# Hardware, exportaciones y protocolo serial

## Tarjetas comprobadas

| Familia | Tarjetas probadas | Entorno |
| --- | --- | --- |
| Arduino AVR | Uno y Mega 2560 | Arduino IDE y runtime C++ incluido en la exportación |
| Raspberry Pi RP2040 | Pico y Pico H | MicroPython v1.29.0 |
| Raspberry Pi RP2350 | Pico 2 | MicroPython v1.29.0 |
| ESP32 | ESP32 y ESP32-CAM | MicroPython v1.29.0, firmware `Generic ESP32 module with ESP32` |

La aplicación identifica puertos seriales, no el modelo de tarjeta. Por ello
el resultado de una comparación correcta dice *El hardware y la simulación
Python coinciden exactamente, muestra por muestra.*

## Arduino

La exportación Arduino genera dos ZIP:

- `FIRFixedImpulse.zip`: contiene `FIRFixedImpulse.ino`, `FIRFixed.h` y
  `fir_config.h`; imprime la respuesta al impulso como `entrada_raw,salida_raw`.
- `FIRFixedSerial.zip`: contiene `FIRFixedSerial.ino`, `FIRFixed.h` y
  `fir_config.h`; procesa una muestra raw por línea.

El Arduino Uno almacena las entradas, coeficientes y salidas raw en `int32_t`:
los formatos con signo pueden usar hasta 32 bits y los sin signo hasta 31 bits.
Producto y acumulador pueden usar hasta 60 bits internos. El Uno emula
`int64_t` por software, de modo que los formatos amplios priorizan exactitud y
claridad didáctica sobre velocidad.

Para cargar un sketch, los tres archivos deben permanecer en la misma carpeta:

```text
FIRFixedSerial/
├── FIRFixedSerial.ino
├── FIRFixed.h
└── fir_config.h
```

## MicroPython

Las descargas conservan los nombres `FIRPicoImpulse.zip` y
`FIRPicoSerial.zip`, pero son programas MicroPython que funcionan en las
tarjetas comprobadas de la tabla anterior.

- `FIRPicoImpulse.zip`: imprime la respuesta al impulso.
- `FIRPicoSerial.zip`: recibe y procesa muestras por USB serial.

Cada ZIP contiene estos tres archivos. Cópielos juntos al sistema de archivos
de la tarjeta usando Thonny, `mpremote` o una herramienta equivalente:

```text
placa/
├── main.py
├── fir_config.py
└── fir_fixed.py
```

`main.py` se ejecuta al reiniciar. El runtime no usa flotantes durante el
filtrado: reproduce el redondeo, saturación o wrap del simulador para entrada,
producto, acumulador y salida.

## Escala y protocolo

La comunicación usa enteros `raw`; así no se pierde la cuantización elegida:

```text
x_real = x_raw / 2^F_x
y_real = y_raw / 2^F_y
```

La aplicación y todos los programas seriales comparten este protocolo ASCII,
una petición por línea:

```text
PC       -> tarjeta:  x_raw\n
tarjeta  -> PC:       x_raw,y_raw\n
```

También están disponibles estos comandos:

| Comando | Respuesta | Efecto |
| --- | --- | --- |
| `PING` | `^..^` | Comprueba que el programa serial está disponible. |
| `RESET` | `OK` | Borra los retardos FIR. |
| `INFO` | Información de taps y formatos | Ayuda a confirmar la configuración cargada. |

El host espera cada respuesta antes de enviar la siguiente muestra. Antes de la
comparación envía `PING` y `RESET`, de forma que hardware y simulación comienzan
con estados internos en cero.

## Antes de comparar

El puerto puede ser abierto por una sola aplicación. Cierre Arduino IDE,
Serial Monitor, Serial Plotter, Thonny, `mpremote` y cualquier terminal serial
antes de utilizar **Prueba en hardware por puerto serial**.

La prueba valida la aritmética y el estado FIR; no mide el rendimiento de
tiempo real de la tarjeta ni la frecuencia de muestreo alcanzable por USB.
