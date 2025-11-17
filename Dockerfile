# Imagen base con Playwright + Chromium listo (incluye Node y dependencias del sistema)
FROM mcr.microsoft.com/playwright/python:v1.55.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["gunicorn", "--workers", "1", "--timeout", "300", "--bind", "0.0.0.0:$PORT", "src.app:app"]
