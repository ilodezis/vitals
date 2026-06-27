FROM python:3.11-slim

# Sync timezone to Chisinau wall-clock time
ENV TZ=Europe/Chisinau
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -sf /usr/share/zoneinfo/Europe/Chisinau /etc/localtime \
    && echo "Europe/Chisinau" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run alembic migrations, then launch FastAPI + APScheduler process
CMD ["sh", "-c", "alembic upgrade head && uvicorn web.main:app --host 0.0.0.0 --port 8000"]
