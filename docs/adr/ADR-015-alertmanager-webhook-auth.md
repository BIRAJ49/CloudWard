# ADR-015: Native Alertmanager Bearer authentication

- Status: Accepted
- Date: 2026-08-22

## Context

The CloudWard alert webhook must authenticate requests, but Alertmanager does not natively calculate an application-specific HMAC over each outgoing body.

## Decision

Use Alertmanager's native `Authorization: Bearer` support with a high-entropy token stored in a Kubernetes Secret. The backend compares the token in constant time, applies schema/body/rate limits, and handles replay/deduplication through normalized payload digests and alert fingerprints. No token value is committed.

## Consequences

The transport contract uses an upstream-supported Alertmanager feature and is reproducible locally. Token rotation requires updating the backend environment and Kubernetes Secret together. Production additionally requires TLS and a managed secret lifecycle.
