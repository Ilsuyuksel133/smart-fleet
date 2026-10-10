# Build context: repository root -> docker build -f dashboard/Dockerfile .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY dashboard/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dashboard/ .

RUN useradd --create-home app
USER app

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
