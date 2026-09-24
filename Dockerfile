FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080
WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

# Jalan sebagai non-root: batas kerusakan kalau ada celah di app yang publik
RUN useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser . .
USER appuser

# Cloud Run nyuntik PORT sendiri (8080); nilai ini cuma default buat lokal
EXPOSE 8080
CMD ["sh","-c","uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
