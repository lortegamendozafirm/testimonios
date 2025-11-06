# ========= Base =========
FROM python:3.11-slim

# Seguridad / rendimiento
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencias del sistema mínimas
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Requerimientos
COPY requirements.txt .
RUN pip install -r requirements.txt

# Código fuente (sin credenciales ni .env)
COPY src ./src

# Puertos/Entrypoint (Cloud Run inyecta $PORT)
ENV PORT=8080
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
