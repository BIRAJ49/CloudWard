# syntax=docker/dockerfile:1.7
ARG CLOUDWARD_API_BASE_IMAGE=cloudward-api:local
FROM ${CLOUDWARD_API_BASE_IMAGE}

ARG AWS_CLI_DEBIAN_VERSION=2.9.19-1

USER root
RUN architecture="$(dpkg --print-architecture)" \
    && case "$architecture" in amd64|arm64) ;; *) printf 'unsupported architecture: %s\n' "$architecture" >&2; exit 1 ;; esac \
    && apt-get update \
    && apt-get install --yes --no-install-recommends "awscli=${AWS_CLI_DEBIAN_VERSION}" \
    && aws --version 2>&1 | grep -F "aws-cli/${AWS_CLI_DEBIAN_VERSION%-*}" \
    && rm -rf /var/lib/apt/lists/*

USER cloudward
