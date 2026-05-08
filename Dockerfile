FROM python:3.11-slim

WORKDIR /app

# Sistem paketleri
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python bağımlılıkları
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama dosyaları
COPY vasi.py .

# Security: Non-root user oluştur
RUN useradd -m -u 1000 vasi && chown -R vasi:vasi /app
USER vasi

# Health check (isteğe bağlı)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import os; print('OK')" || exit 1

CMD ["python", "vasi.py"]
