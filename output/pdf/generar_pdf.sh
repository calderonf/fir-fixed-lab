#!/usr/bin/env bash
# Compila la presentación Beamer y deja el PDF actualizado en este directorio.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SOURCE_FILE="$PROJECT_DIR/material_docente/formatos_punto_fijo.tex"
BUILD_DIR="$PROJECT_DIR/tmp/latex_build"
PDF_FILE="$SCRIPT_DIR/formatos_punto_fijo.pdf"

if ! command -v pdflatex >/dev/null 2>&1; then
  echo "Error: no se encontró pdflatex en PATH." >&2
  echo "Instale una distribución LaTeX (MacTeX o TeX Live) y vuelva a intentarlo." >&2
  exit 1
fi

if [[ ! -f "$SOURCE_FILE" ]]; then
  echo "Error: no se encontró la fuente: $SOURCE_FILE" >&2
  exit 1
fi

mkdir -p "$BUILD_DIR"
pdflatex -interaction=nonstopmode -halt-on-error \
  -output-directory="$BUILD_DIR" "$SOURCE_FILE" >/dev/null
pdflatex -interaction=nonstopmode -halt-on-error \
  -output-directory="$BUILD_DIR" "$SOURCE_FILE" >/dev/null

cp "$BUILD_DIR/formatos_punto_fijo.pdf" "$PDF_FILE"
echo "PDF actualizado: $PDF_FILE"
