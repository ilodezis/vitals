# ── Stage 1: build the React app ─────────────────────────────────────────────
# Vite writes to ../web/static/app (see frontend/vite.config.ts), so the layout
# mirrors the repo: /build/frontend in, /build/web/static/app out.
FROM node:24-alpine AS frontend

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: the app ─────────────────────────────────────────────────────────
FROM python:3.13-slim

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
COPY --from=frontend /build/web/static/app /app/web/static/app

# Run alembic migrations, then launch FastAPI + APScheduler process.
# --forwarded-allow-ips="*": trust X-Forwarded-For so per-IP login throttling
# sees the real client IP, not Caddy's. Safe here — the port binds loopback only
# and Caddy is the sole upstream.
CMD ["sh", "-c", "alembic upgrade head && uvicorn web.main:app --host 0.0.0.0 --port 8000 --forwarded-allow-ips=*"]
