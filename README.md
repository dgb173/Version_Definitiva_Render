# Qwen Code Preferences

- Do not verify code with Python automatically. I will provide feedback instead.

---

# Despliegue en Render.com

Este proyecto está configurado para un despliegue robusto y sencillo en Render utilizando **Docker**.

## Prerrequisitos

1.  Una cuenta en [Render.com](https://render.com/).
2.  Este repositorio subido a tu cuenta de GitHub.
3.  Un fichero `data.json` en la raíz del proyecto.

## ¿Cómo funciona?

Este proyecto utiliza un **`Dockerfile`** para crear un entorno de ejecución personalizado. Esto resuelve todos los problemas de dependencias que encontramos.

-   **Entorno Personalizado**: El `Dockerfile` parte de la imagen `python:3.11-slim` y solo instala las librerias del sistema necesarias. `cloudscraper` se encarga de desbloquear NowGoal sin navegadores.
-   **Configuración de Render**: El fichero `render.yaml` ha sido simplificado. Ahora simplemente le dice a Render que construya la aplicación usando el `Dockerfile` y la inicie.
-   **Lógica de la App**: La aplicación sigue leyendo los partidos desde `data.json`, y solo hace scraping en vivo para los análisis detallados, como querías.

Este es el método recomendado para aplicaciones complejas como la tuya.

## Pasos para el Despliegue

1.  **Crea el fichero `data.json`**: Antes de nada, asegúrate de tener un fichero `data.json` en la raíz de tu proyecto. Puedes generarlo ejecutando el scraper localmente:
    ```bash
    py scripts/run_scraper.py
    ```
    Asegúrate de que este fichero existe en tu repositorio de GitHub.

2.  **Ve a Render**:
    - Inicia sesión en tu cuenta de Render.
    - Ve al [Dashboard](https://dashboard.render.com/).
    - Haz clic en **New +** y selecciona **Blueprint**.

3.  **Conecta tu Repositorio**:
    - Selecciona el repositorio de GitHub que contiene este proyecto.
    - Render detectará automáticamente los ficheros `render.yaml` y `Dockerfile` y configurará todo.

4.  **Confirma y Despliega**:
    - Render te mostrará el servicio que va a crear. No necesitas cambiar nada.
    - Haz clic en **Apply** o **Create New Services**.

Render se encargará del resto. La construcción puede tardar unos minutos, ya que tiene que construir la imagen de Docker. Una vez terminado, tu aplicación estará online.

## Cómo Actualizar la Lista de Partidos

El flujo para actualizar los partidos no cambia:

1.  **Ejecuta el scraper en tu ordenador**:
    ```bash
    py scripts/run_scraper.py
    ```
    Esto actualizará tu fichero local `data.json`.

2.  **Sube los cambios a GitHub**:
    ```bash
    git add data.json
    git commit -m "Actualizar lista de partidos"
    git push
    ```

3.  **Despliegue Automático**: Render detectará los cambios y redesplegará la aplicación automáticamente con la nueva lista de partidos.
## Uso local y Análisis Profundo

Puedes levantar el proyecto en local para comprobar que el botón de análisis profundo funciona. El scraper usa `cloudscraper` con caché integrado, por lo que no necesitas Selenium ni navegadores.

1.  **Crear entorno (opcional pero recomendable)**:
    ```powershell
    py -3 -m venv .venv
    .\.venv\Scripts\activate
    ```
2.  **Instalar dependencias**:
    ```powershell
    pip install -r requirements.txt
    ```
3.  **Iniciar la app Flask** (carga `src/app.py`, donde viven `/api/preview` y `/api/analisis`):
    ```powershell
    py -3 src/app.py
    ```
4.  **Probar el análisis profundo**:
    - Entra en `http://127.0.0.1:5000` y usa el botón del panel.
    - O llama directo a `http://127.0.0.1:5000/api/analisis/<match_id>` para obtener el JSON/HTML del estudio.

Si necesitas refrescar `data.json`, ejecuta:
```powershell
py scripts/run_scraper.py
```

> `modules/estudio_scraper.py` mantiene un caché corto (45 s) y comparte sesión `cloudscraper`, así que los análisis consecutivos se sirven rápido incluso sin internet de alta velocidad. Asegúrate de correr los comandos desde la carpeta raíz del repo para que las rutas relativas funcionen.
