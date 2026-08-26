# Structured incident memory

CloudWard stores incident memory in PostgreSQL as bounded, typed facts. It deliberately does not
use embeddings or a vector database in this phase, so retrieval remains deterministic,
explainable, and operable with the existing data platform.

One terminal incident produces or updates one memory record containing the stable service key,
environment, incident and alert type, namespace, stable labels, root-cause category, runbook,
action, result, verification outcome, duration, model/confidence metadata, and a bounded evidence
summary. Successful outcomes are identified only when verification succeeded and the result is
resolved/succeeded. Failed and blocked attempts remain stored because suppressing them would teach
an unsafe history.

## Fingerprints and matching

The fingerprint is SHA-256 over canonical JSON built from normalized service, incident type,
alert name, namespace, root-cause category, and an explicit stable-label allowlist. Random IDs,
timestamps, pod suffixes, and arbitrary high-cardinality labels are excluded.

Similarity first requires the same service. It then assigns fixed points for the same fingerprint,
incident type, alert, namespace, and root-cause category. Verified successful outcomes receive a
small tie-breaking bonus; failures are still eligible and visible. Responses include the exact
match score and reasons, not an opaque similarity claim. Queries inspect a bounded recent set and
return at most twenty records.

`GET /api/v1/incidents/{id}/similar` derives the query from the current incident and returns only
factual stored fields. AI context receives no more than ten matches.

## Trust boundary

Evidence and operator summaries are recursively redacted before persistence and again before
retrieval. Historical text is marked untrusted when used in a prompt and cannot override system
instructions. A previous action is evidence about an outcome, never permission to repeat it;
current registry, risk, OPA, approval, execution, verification, and rollback controls still apply.
