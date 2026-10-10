# Build context: repository root -> docker build -f simulator/Dockerfile .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY simulator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY simulator/ .

RUN useradd --create-home app
USER app

CMD ["python", "simulate_data.py"]
