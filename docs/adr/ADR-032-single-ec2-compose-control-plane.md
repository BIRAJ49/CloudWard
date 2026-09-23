# ADR-032: Single EC2 Docker Compose control plane

Status: Accepted

## Context

Running CloudWard, PostgreSQL, Redis, OPA, and workers as managed services would improve availability but exceed the portfolio's cost and complexity goals.

## Decision

One encrypted, IMDSv2-required AL2023 EC2 instance runs Nginx, React, FastAPI, Celery, PostgreSQL, Redis, and OPA with Docker Compose. It has no SSH key or inbound SSH, uses SSM for exceptional access, receives an instance profile rather than static AWS keys, and exposes only origin TLS from Cloudflare. Root-owned secrets and verified PostgreSQL backups remain outside Git.

AWS CLI inside trusted bridged containers uses instance metadata; hop limit two is required and increases SSRF sensitivity. Containers remain non-root, tightly networked, and do not receive static credentials.

## Consequences

The architecture is understandable and inexpensive relative to managed alternatives, but it is a single point of failure and co-locates the database. Recovery is backup/rebuild based; v1 is not HA or production-ready.
