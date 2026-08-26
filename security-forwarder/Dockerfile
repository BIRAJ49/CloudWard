# syntax=docker/dockerfile:1.7
FROM python:3.13.15-alpine3.22

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN addgroup -S -g 65532 cloudward \
    && adduser -S -D -H -u 65532 -G cloudward cloudward

WORKDIR /app
COPY --chown=65532:65532 forwarder.py /app/forwarder.py

USER 65532:65532
ENTRYPOINT ["python", "/app/forwarder.py"]

