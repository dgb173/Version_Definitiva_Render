@echo off

:: Título de la ventana
title Instalador y Ejecutor del Scraper


:: ===================================================================
::                    BIENVENIDO
:: ===================================================================
echo.
echo Este script va a instalar todo lo necesario y ejecutara la 
echo aplicacion de scraping.

echo.
echo Por favor, ten paciencia, ya que la primera vez puede tardar 
echo varios minutos en descargar e instalar todo.

echo.
echo Presiona cualquier tecla para comenzar...
pause > NUL


:: ===================================================================
::                    PASO 1 de 2: INSTALACION
:: ===================================================================
echo.
echo [INFO] Instalando y/o actualizando librerias de Python...

:: Instalar dependencias de Python
py -m pip install --upgrade pip > NUL
py -m pip install -r requirements.txt

:: Comprobar si hubo un error
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Ha ocurrido un error instalando las librerias de Python.
    echo         Por favor, asegurate de que tienes Python bien instalado
    echo         y de que tienes conexion a internet.
    echo.
    pause
    exit /b
)


echo [INFO] Instalando navegadores para Playwright (esto puede tardar)...

:: Instalar navegadores de Playwright
py -m playwright install

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Ha ocurrido un error instalando los navegadores web.
    echo.
    pause
    exit /b
)

echo.
echo [OK] Todas las dependencias se han instalado correctamente.
echo.


:: ===================================================================


::                    PASO 2 de 3: DESCARGA DE DATOS


:: ===================================================================


echo.


echo [INFO] Ejecutando el scraper para descargar los datos de los partidos...


echo [INFO] Esto puede tardar unos segundos.





:: Ejecutar el script de scraping























py scripts/run_scraper.py





:: Comprobar si hubo un error


if %errorlevel% neq 0 (


    echo.


    echo [ERROR] Ha ocurrido un error al ejecutar el scraper.


    echo         Revisa la salida en la consola para ver el detalle.


    echo.


    pause


    exit /b


)





echo [OK] Datos descargados y guardados en data.json.








:: ===================================================================


::                    PASO 3 de 3: EJECUCION


:: ===================================================================


echo.


echo [INFO] Todo listo para arrancar la aplicacion.





echo.


echo    *********************************************************


echo.    *                                                       *


echo.    *    La aplicacion se esta iniciando ahora...           *


echo.    *                                                       *


echo.    *    Cuando arranque, abre tu navegador web y ve a:     *


echo.    *                                                       *


echo.    *    http://127.0.0.1:5000                              *


echo.    *                                                       *


echo.    *********************************************************


echo.


echo [IMPORTANTE] Para detener la aplicacion, simplemente cierra esta ventana.





echo.








:: Ejecutar la aplicación Flask







































































py src/app.py








:: Mensaje final por si el servidor se detiene solo


echo.


echo La aplicacion se ha detenido.


pause
