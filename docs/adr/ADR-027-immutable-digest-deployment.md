# ADR-027: Immutable digest deployment

- Status: Accepted
- Date: 2026-08-22

## Context

Tags can be moved after review, creating a gap between scanned, signed, and
deployed content.

## Decision

Staging and production render only `repository@sha256:<digest>`. Helm fails when a
release environment lacks a digest. GitOps records the source commit, scan, SBOM,
validation, and rollback digest next to the image reference. Tags remain
non-authoritative discovery metadata.

## Consequences

Every deployed image is content-addressed and evidence correlates to one artifact.
Initial staging/production values are intentionally non-deployable until a real
release supplies a digest. Rollback is a Git change to another known digest.
