#!/bin/bash

echo "==== Contenido de requirements.txt: ===="
cat requirements.txt
echo "========================================="

echo "==== Instalando dependencias de Python... ===="
pip install -r requirements.txt
echo "========================================="


echo "==== Iniciando instalación de navegadores Playwright (Chromium)... ===="
playwright install chromium
# playwright install --with-deps chromium # --with-deps a veces causa problemas en Streamlit Cloud si no tiene permisos

# Para depuración, verifica dónde se instalaron los binarios (o si se instalaron)
echo "==== Verificando instalación de Playwright en .cache... ===="
ls -R /home/appuser/.cache/ms-playwright/
echo "==== Fin de la verificación de Playwright ===="

echo "==== Fin de setup.sh ===="
