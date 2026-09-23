# syntax=docker/dockerfile:1.7
FROM python:3.13.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 cloudward \
    && useradd --system --uid 10001 --gid cloudward --home-dir /nonexistent --shell /usr/sbin/nologin cloudward \
    && pip install --no-cache-dir uv==0.12.3

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=cloudward:cloudward backend/app ./app
COPY --chown=cloudward:cloudward backend/migrations ./migrations
COPY --chown=cloudward:cloudward backend/alembic.ini ./alembic.ini
COPY --chown=cloudward:cloudward backend/pyproject.toml ./pyproject.toml

USER cloudward
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=4 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
