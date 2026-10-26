# Compilar la presentación Beamer

La fuente editable está dos niveles arriba, en:

```text
../../material_docente/formatos_punto_fijo.tex
```

El script `generar_pdf.sh` compila esa fuente dos veces y deja el PDF actualizado
en este mismo directorio. La segunda compilación actualiza la tabla de contenidos,
los enlaces y la numeración interna de Beamer.

## Requisito

Debe existir el comando `pdflatex` en la terminal. En macOS se obtiene al instalar
MacTeX; en Linux, TeX Live. Verifique la instalación con:

```bash
pdflatex --version
```

## Uso en macOS o Linux

Abra una terminal y ejecute:

```bash
cd /Users/francisco/Documents/ChatGPT/FIR_IIR_filters/fir_fixed_lab/output/pdf
chmod +x generar_pdf.sh
./generar_pdf.sh
```

Edite primero el archivo `.tex`, guárdelo y vuelva a ejecutar el script. El
resultado reemplaza `formatos_punto_fijo.pdf`.

Los archivos intermedios de LaTeX se guardan en:

```text
../../tmp/latex_build
```

Puede eliminarlos cuando quiera sin afectar la fuente ni el PDF final.
