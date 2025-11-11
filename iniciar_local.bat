
@echo off
TITLE Probador Local de App

echo --------------------------------------------------------
echo       INICIADOR DE APLICACION LOCAL
echo --------------------------------------------------------
echo.

echo [PASO 1 de 2] Ejecutando el scraper para crear/actualizar data.json...
echo Este proceso puede tardar uno o dos minutos. Por favor, espera.
echo.

REM Usar primero el directorio del propio script
cd /d "%~dp0"

REM Elegir interprete de Python (prioriza el virtualenv local si existe)
set "PYTHON_CMD="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=.venv\Scripts\python.exe"
)
if defined PYTHON_CMD (
    "%PYTHON_CMD%" --version >NUL 2>&1
    if %errorlevel% NEQ 0 (
        set "PYTHON_CMD="
    )
)
if not defined PYTHON_CMD (
    where python >NUL 2>&1
    if %errorlevel% EQU 0 (
        set "PYTHON_CMD=python"
    )
)
if not defined PYTHON_CMD (
    set "PYTHON_CMD=py"
)

if not defined PYTHON_CMD (
    for %%P in (Python314 Python313 Python312 Python311) do (
        if exist "%LOCALAPPDATA%\Programs\Python\%%P\python.exe" (
            set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\%%P\python.exe"
            goto :PYTHON_CMD_READY
        )
    )
)

:PYTHON_CMD_READY

set "PROJECT_ROOT=%~dp0"
set "APP_DIR=%PROJECT_ROOT%src"
set "DATA_DIR=%PROJECT_ROOT%"

REM Ejecuta el script de scraping
"%PYTHON_CMD%" "%PROJECT_ROOT%scripts\run_scraper.py"

REM Comprueba si el scraper dio un error. Si el errorlevel no es 0, hubo un problema.
IF %errorlevel% NEQ 0 (
    echo.
    echo ***********************************************************
    echo *  ERROR: El script de scraping ha fallado.                *
    echo *  La aplicacion web no se puede iniciar.                 *
    echo *  Revisa los mensajes de error en esta ventana.          *
    echo ***********************************************************
    echo.
    pause
    exit /b %errorlevel%
)

echo.
echo [PASO 2 de 2] Scraper finalizado con exito.
echo Iniciando el servidor web de Flask...
echo.
echo >> Tu aplicacion estara disponible en: http://127.0.0.1:8080
echo >> Manten esta ventana abierta para que el servidor funcione.
echo >> Cierra la ventana para detener el servidor.
echo.

REM Si el scraper funciono, inicia la app
"%PYTHON_CMD%" "%APP_DIR%\app.py"
set "APP_EXIT=%errorlevel%"

IF %APP_EXIT% NEQ 0 (
    echo.
    echo ***********************************************************
    echo *  ERROR: La aplicacion Flask se cerro con un fallo.       *
    echo *  Revisa el mensaje anterior para conocer el motivo.      *
    echo ***********************************************************
    echo.
    pause
    exit /b %APP_EXIT%
)

echo.
echo --------------------------------------------------------
echo El servidor Flask se ha detenido.
echo Pulsa una tecla para cerrar esta ventana.
echo --------------------------------------------------------
pause
