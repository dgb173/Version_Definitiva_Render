#!/bin/bash

echo "==== Contenido de requirements.txt: ===="
cat requirements.txt
echo "========================================="

echo "==== Instalando dependencias de Python... ===="
pip install -r requirements.txt
echo "========================================="


echo "==== Iniciando instalacion opcional de navegadores Playwright (Chromium)... ===="
PLAYWRIGHT_CACHE_DIR="/home/appuser/.cache/ms-playwright/"
if command -v playwright >/dev/null 2>&1; then
    echo "Playwright detectado, instalando Chromium..."
    if playwright install chromium; then
        if [ -d "${PLAYWRIGHT_CACHE_DIR}" ]; then
            echo "==== Contenido de ${PLAYWRIGHT_CACHE_DIR} ===="
            ls -R "${PLAYWRIGHT_CACHE_DIR}"
        else
            echo "Directorio ${PLAYWRIGHT_CACHE_DIR} no encontrado tras la instalacion de Playwright."
        fi
    else
        echo "La instalacion de Playwright fallo; continuamos sin navegadores."
    fi
else
    echo "Playwright no esta instalado en este entorno, se omite la instalacion de navegadores."
fi
echo "==== Fin de la verificacion de Playwright ===="

echo "==== Fin de setup.sh ===="
