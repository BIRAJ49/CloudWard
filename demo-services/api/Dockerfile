# syntax=docker/dockerfile:1.7
FROM python:3.13.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

ARG DEMO_BAD_RELEASE_ENABLED=false
ENV DEMO_BAD_RELEASE_ENABLED=${DEMO_BAD_RELEASE_ENABLED}

WORKDIR /app

RUN groupadd --system --gid 10001 cloudward \
    && useradd --system --uid 10001 --gid cloudward --home-dir /nonexistent --shell /usr/sbin/nologin cloudward \
    && mkdir -p /tmp/cloudward-demo \
    && chown cloudward:cloudward /tmp/cloudward-demo \
    && pip install uv==0.12.3

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=cloudward:cloudward app ./app

USER cloudward
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/live', timeout=2)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]
