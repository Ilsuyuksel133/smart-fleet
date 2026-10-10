# Build context: repository root -> docker build -f agent/Dockerfile .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first: this layer stays cached even when the code changes
COPY agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The code is a package ("agent"), so it is copied into /app/agent
COPY agent/ ./agent/

RUN useradd --create-home app
USER app

EXPOSE 8100

# The slim image has no curl, so the health check uses Python
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/health', timeout=2)"

CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8100", "--no-access-log"]
