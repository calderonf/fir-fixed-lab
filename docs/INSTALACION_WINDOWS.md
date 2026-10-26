# Instalar y usar el Laboratorio FIR de punto fijo en Windows

## Requisitos

- Windows 10 u 11 de 64 bits.
- Un navegador moderno (Edge, Chrome o Firefox).
- Una conexión USB y el controlador de la tarjeta si se hará una prueba de
  hardware. La aplicación no requiere conexión a Internet después de instalarse.

No se necesita instalar Python, Streamlit, Arduino IDE ni Thonny para abrir el
laboratorio.

## Instalación

1. Abra la pestaña [Releases](https://github.com/calderonf/fir-fixed-lab/releases) del repositorio oficial.
2. Descargue `FIR-Fixed-Lab-Setup-<versión>-Windows-x64.exe` de la versión más
   reciente.
3. Compruebe que la descarga procede de ese repositorio y ejecute el instalador.
4. Elija la carpeta de instalación y, si lo desea, cree el acceso directo de
   escritorio.
5. Abra **Laboratorio FIR de punto fijo** desde el menú Inicio o el escritorio.

El programa inicia un servidor Streamlit sólo en `127.0.0.1` y abre la
interfaz en el navegador predeterminado. No publica la aplicación en la red
local ni en Internet.

Mantenga abierta la pequeña ventana de consola mientras utiliza el laboratorio:
cerrarla detiene el servidor local y la página deja de responder. Para abrirla
de nuevo, ejecute el acceso directo otra vez.

## Aviso de seguridad de Windows

En las primeras versiones el instalador puede no tener firma de código, por lo
que Windows SmartScreen podría mostrar una advertencia de reputación. No ignore
esa advertencia automáticamente: confirme primero que el archivo procede de la
página oficial de Releases y que corresponde a la versión esperada. La firma
digital es una mejora prevista para distribución institucional amplia.

## Prueba por puerto serial

1. Diseñe y cuantice el filtro en la aplicación.
2. Descargue y cargue el programa correspondiente en la tarjeta:
   - Arduino: `FIRFixedSerial.zip` y el sketch `FIRFixedSerial.ino`.
   - MicroPython: `FIRPicoSerial.zip`, copiando `main.py`, `fir_config.py` y
     `fir_fixed.py` al sistema de archivos de la tarjeta.
3. Cierre Arduino IDE, Serial Monitor, Serial Plotter, Thonny, `mpremote` y
   cualquier otro programa que pueda tener abierto el puerto.
4. Conecte la tarjeta por USB, recargue la página si es necesario y seleccione
   su puerto `COM` en **Prueba en hardware por puerto serial**.
5. Pulse **Enviar muestras y comparar**. La aplicación envía una muestra raw y
   espera la respuesta antes de enviar la siguiente, evitando llenar el buffer
   de tarjetas pequeñas.

La comparación es bit-exacta: la aplicación verifica `x_raw,y_raw` muestra por
muestra frente a su propia simulación Python. No mide rendimiento de tiempo
real, porque el enlace USB/serial añade esperas.

## Actualizar o desinstalar

- Para actualizar, instale una versión posterior desde Releases; el instalador
  reemplaza los archivos de la aplicación.
- Para desinstalar, use **Aplicaciones instaladas** de Windows y busque
  *Laboratorio FIR de punto fijo*.

## Solución de problemas

| Síntoma | Acción recomendada |
| --- | --- |
| No aparece ningún puerto `COM` | Verifique el cable USB, el controlador de la tarjeta y cierre otras aplicaciones seriales. Desconecte y conecte de nuevo la tarjeta. |
| El puerto aparece, pero la prueba falla | Asegúrese de haber cargado el programa exportado desde la misma configuración actual. Cierre el IDE y vuelva a intentar; la aplicación enviará `RESET`. |
| La página no abre | Espere hasta 30 segundos; si no abre, cierre la consola y ejecute el acceso directo otra vez. |
| La página dejó de responder | La consola del lanzador fue cerrada o el proceso local terminó. Ejecute de nuevo el acceso directo. |
| SmartScreen advierte sobre el archivo | Verifique el origen y la versión en Releases. No ejecute archivos recibidos desde fuentes no verificadas. |

Para conocer las tarjetas comprobadas y el protocolo, vea
[Hardware, exportaciones y protocolo serial](HARDWARE.md).
