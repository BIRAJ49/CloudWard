# syntax=docker/dockerfile:1.7
FROM python:3.13.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --system --gid 10001 cloudward \
    && useradd --system --uid 10001 --gid cloudward --home-dir /nonexistent --shell /usr/sbin/nologin cloudward \
    && pip install --no-cache-dir uv==0.12.3

COPY worker/pyproject.toml worker/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=cloudward:cloudward worker ./worker

USER cloudward

HEALTHCHECK --interval=20s --timeout=8s --start-period=15s --retries=3 \
  CMD ["celery", "-A", "worker.celery_app:celery_app", "inspect", "ping", "--destination", "celery@cloudward-worker", "--timeout", "5"]

CMD ["celery", "-A", "worker.celery_app:celery_app", "worker", "--loglevel=INFO", "--hostname=celery@cloudward-worker", "--concurrency=2", "--queues=incident-ingestion,evidence,remediation,verification,notifications"]
