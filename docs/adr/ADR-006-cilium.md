# ADR-006: Cilium for local networking

- Status: Accepted
- Date: 2026-08-13

## Context

Part 1 must establish the networking layer that later security and observability work will build on.

## Decision

Disable k3s' default Flannel integration when creating the CloudWard cluster and install full Cilium before workloads.

## Consequences

Bootstrap has a strict ordering requirement and must verify Cilium health. Later network policy and runtime visibility can build on a consistent data plane.

