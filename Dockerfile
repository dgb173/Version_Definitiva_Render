# Use the official Playwright image which comes with browsers and all dependencies
FROM mcr.microsoft.com/playwright/python:v1.55.0-jammy

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
# We don't need 'playwright install' because the browsers are already in the image
RUN apt-get update && apt-get install -y \
    libgtk-4-1 \
    libgraphene-1.0-0 \
    gstreamer1.0-plugins-base \
    libenchant-2-2 \
    libsecret-1-0 \
    libmanette-0.2-0 \
    libgles2 \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# The start command will be taken from render.yaml, but it's good practice to have a CMD
# Gunicorn will bind to the port specified by the $PORT environment variable provided by Render.
CMD ["gunicorn", "--workers", "1", "--timeout", "120", "--bind", "0.0.0.0:$PORT", "src.app:app"]
