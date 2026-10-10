# Build context: repository root -> docker build -f api/Dockerfile .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first: this layer stays cached even when the code changes
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ .

# Non-root user; the SQLite file lives under /app/data
RUN useradd --create-home app \
    && mkdir -p /app/data \
    && chown -R app:app /app/data
USER app
VOLUME ["/app/data"]

EXPOSE 8000

# The slim image has no curl, so the health check uses Python
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
