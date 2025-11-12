# Qwen Code Preferences

- Do not verify code with Python automatically. I will provide feedback instead.

---

# Despliegue en Render.com

Este proyecto está configurado para un despliegue rápido y sencillo en Render utilizando "Blueprints".

## Prerrequisitos

1.  Una cuenta en [Render.com](https://render.com/).
2.  Este repositorio subido a tu cuenta de GitHub.
3.  Un fichero `data.json` en la raíz del proyecto.

## ¿Cómo funciona?

El fichero `render.yaml` en este repositorio le indica a Render todo lo que necesita saber para poner en marcha la aplicación:

-   **Servicio Web**: Crea un servicio web para la aplicación Flask.
-   **Comando de Construcción**: Instala todas las dependencias de Python desde `requirements.txt` y, muy importante, descarga los navegadores que `playwright` necesita para que funcione el análisis de partidos ("Estudio").
-   **Comando de Inicio**: Inicia la aplicación utilizando `gunicorn`, un servidor web de producción.

La aplicación está diseñada para leer los listados de partidos directamente desde el fichero `data.json` que tú proporcionas. El scraping en vivo solo se utiliza para los análisis detallados de partidos individuales.

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
    - Render detectará y leerá automáticamente el fichero `render.yaml`.

4.  **Confirma y Despliega**:
    - Render te mostrará el servicio que va a crear. No necesitas cambiar nada.
    - Haz clic en **Apply** o **Create New Services**.

Render se encargará del resto. La primera vez, la construcción puede tardar unos minutos debido a la descarga de los navegadores de Playwright. Una vez terminado, tu aplicación estará online en la URL que Render te proporcione.

## Cómo Actualizar la Lista de Partidos

Cuando quieras actualizar los partidos que se muestran en la web, sigue estos pasos:

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

3.  **Despliegue Automático**: Por defecto, Render detectará el `push` a tu repositorio y automáticamente volverá a desplegar la aplicación con el nuevo `data.json`. Si no tienes activado el despliegue automático, puedes iniciarlo manualmente desde el dashboard de Render.
