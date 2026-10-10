# Build context: repo kökü -> docker build -f api/Dockerfile .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Önce sadece bağımlılıklar: kod değişse bile bu katman cache'ten gelir
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ .

# Root olmayan kullanıcı; SQLite dosyası /app/data altında tutulur
RUN useradd --create-home app \
    && mkdir -p /app/data \
    && chown -R app:app /app/data
USER app
VOLUME ["/app/data"]

EXPOSE 8000

# Slim imajda curl yok, health check'i python ile yapıyoruz
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
