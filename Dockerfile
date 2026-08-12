# Sotuvchi AI — production image.
#
# Two stages so the build toolchain needed to compile wheels (argon2-cffi,
# asyncpg) never ships in the final image.

# ─── build ────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Dependencies resolve in their own layer, so editing application code does not
# reinstall them on every build.
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt

# ─── runtime ──────────────────────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8080 \
    HOST=0.0.0.0 \
    DEBUG=False \
    WEB_CONCURRENCY=2 \
    TELEGRAM_POLLING=false \
    FORWARDED_ALLOW_IPS=*

# curl is here for the HEALTHCHECK below; nothing else needs it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 sotuvchi

COPY --from=build /opt/venv /opt/venv

WORKDIR /app
COPY --chown=sotuvchi:sotuvchi . .
RUN chmod +x /app/docker-entrypoint.sh

# Uploaded product images are written at runtime and must be writable by the
# unprivileged user. Mount a volume here to keep them across deploys.
RUN mkdir -p /app/static/uploads && chown -R sotuvchi:sotuvchi /app/static/uploads

USER sotuvchi
EXPOSE 8080

# Liveness only — /api/ready touches Postgres, and a database blip should take
# the instance out of the load balancer, not restart the container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

# Migrations run first, then the server replaces the shell as PID 1 so it
# receives the platform's stop signal directly and shuts down gracefully.
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Shell form so ${PORT} expands: hosts inject their own port. --proxy-headers
# makes the app see the client's real IP through the platform's load balancer,
# which the login throttle keys on.
#
# FORWARDED_ALLOW_IPS defaults to '*' because managed hosts (Railway, Render)
# do not publish a fixed proxy address. That setting makes uvicorn take the
# LEFTMOST X-Forwarded-For entry, which the client controls — so the per-IP
# throttle can be sidestepped by forging the header. The account-level
# counter in app/core/security.py is what actually stops brute force; set
# this to the real proxy's address wherever you know it, and the per-IP
# counter becomes trustworthy again.
CMD uvicorn main:app \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WEB_CONCURRENCY" \
    --proxy-headers \
    --forwarded-allow-ips "$FORWARDED_ALLOW_IPS" \
    --timeout-graceful-shutdown 20
