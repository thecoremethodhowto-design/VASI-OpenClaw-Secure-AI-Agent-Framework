FROM python@sha256:a630a63cdb314e2d138a2fca3e375e319e8568346ffafac5b980f888630ac4f1


WORKDIR /app

# Sistem paketleri
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Python bağımlılıkları
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

# Uygulama dosyaları
COPY vasi.py .
COPY observability.py .
COPY evaluation ./evaluation
COPY policies ./policies
COPY tests ./tests
COPY pytest.ini .
COPY access.py .
COPY context.py .
COPY execution.py .
COPY decision.py .
COPY litellm ./litellm

# Security: Non-root user oluştur
RUN useradd -m -u 1000 vasi && chown -R vasi:vasi /app
USER vasi

# Health check (isteğe bağlı)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import os; print('OK')" || exit 1

CMD ["python", "vasi.py"]
