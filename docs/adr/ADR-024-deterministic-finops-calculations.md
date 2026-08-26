# ADR-024: Deterministic FinOps calculations

## Status

Accepted for Part 3.

## Context

Rightsizing changes can impair reliability, and cost estimates are unreliable when based on short or incomplete samples. An LLM is not a calculation engine or an authorization boundary.

## Decision

CloudWard calculates FinOps recommendations from normalized Prometheus utilization, Kubernetes resource configuration, and OpenCost allocation. Configurable minimum windows, coverage, sample counts, p95 headroom, safe minimums, and meaningful-reduction thresholds fail closed. The stored record includes current and proposed state, evidence window, confidence, risk, limitations, and a deterministic source fingerprint.

AI may explain an already persisted recommendation but cannot calculate, alter, approve, or execute it. A workload change is proposed only through an allowlisted draft GitHub PR with stale-blob protection. GitHub review is the authority for persistent configuration; CloudWard never merges or directly resizes production resources.

## Consequences

Recommendations remain reproducible and auditable. Missing or insufficient data yields no recommendation. Local cost results are labeled as a demo model, and AWS savings are not claimed until a later real EKS validation.
