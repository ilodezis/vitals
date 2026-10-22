# ── Stage 1: build the React app ─────────────────────────────────────────────
# Vite writes to ../web/static/app (see frontend/vite.config.ts), so the layout
# mirrors the repo: /build/frontend in, /build/web/static/app out.
# Base images are pinned by digest: a floating tag moves whenever upstream
# rebuilds it, and every move throws away the cached dependency layers below,
# so a one-line backend change reinstalled everything. Bump the digest on purpose.
FROM node:26-alpine@sha256:40cd011b55415bc894e45b02fdd5a5dfde056921b7d23a64c74f80497af48797 AS frontend

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
# The npm cache survives between builds, so a lockfile change only fetches
# what changed instead of the whole tree.
RUN --mount=type=cache,target=/root/.npm npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: the app ─────────────────────────────────────────────────────────
FROM python:3.13-slim@sha256:27b7c9d4f13ca20bb1170148f02095d50a5dfce1f7f2dabf5ca273727e43b7ea

# Sync timezone to Chisinau wall-clock time
ENV TZ=Europe/Chisinau
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -sf /usr/share/zoneinfo/Europe/Chisinau /etc/localtime \
    && echo "Europe/Chisinau" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies. The pip cache lives in a build cache mount, not in the
# image, so a requirements change re-downloads only the packages that changed.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

COPY . .
COPY --from=frontend /build/web/static/app /app/web/static/app

# Run alembic migrations, then launch FastAPI + APScheduler process.
# --forwarded-allow-ips="*": trust X-Forwarded-For so per-IP login throttling
# sees the real client IP, not Caddy's. Safe here — the port binds loopback only
# and Caddy is the sole upstream.
# `exec` hands PID 1 to uvicorn: a shell as PID 1 never passes SIGTERM on, so
# every stop waited out the 10 s grace period and ended in SIGKILL.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn web.main:app --host 0.0.0.0 --port 8000 --forwarded-allow-ips=*"]
