FROM python:3.10-slim

# Instalar dependencias del sistema necesarias para cadquery
RUN apt-get update && apt-get install -y \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Crear carpeta de trabajo
WORKDIR /app

# Copiar archivos
COPY . .

# Instalar Python deps
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Puerto
ENV PORT=10000

# Ejecutar app
CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:app"]
