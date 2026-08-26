# ADR-026: Keyless Cosign signing through GitHub OIDC

- Status: Accepted
- Date: 2026-08-22

## Context

CloudWard releases need verifiable provenance without storing a long-lived image
signing private key.

## Decision

The release workflow obtains a short-lived GitHub Actions OIDC identity and signs
the immutable GHCR digest with Cosign keyless signing. Verification constrains the
GitHub workflow subject and token issuer and uses Rekor transparency data. Kyverno
enforces the same identity at admission.

## Consequences

There is no normal Cosign private key to rotate or exfiltrate. Availability
depends on GitHub OIDC and Sigstore services, and repository/workflow renames
require an explicit policy update. Verification fails closed rather than silently
admitting an unverifiable release.
