# ADR-021: Strict AI contracts and structured incident memory

Status: Accepted

CloudWard places bounded, redacted, explicitly untrusted evidence behind strict Pydantic input and
output contracts. It stores validated operator-facing results, not raw prompts or hidden reasoning.
Historical incident memory uses PostgreSQL facts and deterministic fingerprints instead of vector
search. Matches expose fixed scores and reasons, prioritize verified success only as a small
tie-breaker, and retain failed outcomes. This is explainable, auditable, and uses the existing
operational data platform.
