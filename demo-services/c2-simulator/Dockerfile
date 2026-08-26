# syntax=docker/dockerfile:1.7
FROM python:3.13.15-alpine3.22

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN addgroup -S -g 10001 cloudward \
    && adduser -S -D -H -u 10001 -G cloudward cloudward
WORKDIR /app
COPY --chown=10001:10001 server.py /app/server.py
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["python", "/app/server.py"]

