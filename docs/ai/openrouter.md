# AI diagnosis through OpenRouter

CloudWard treats model output as untrusted advice. The deterministic incident and remediation
pipeline remains authoritative; the AI layer cannot call Kubernetes, GitHub, an executor, or a
shell. A suggested action becomes useful only after it is selected through the authenticated API
and passes the action registry, deterministic risk calculation, and OPA. That boundary creates an
auditable proposal and explicitly does not start execution.

## Runtime flow

1. Reliability processing queues supplemental diagnosis only when no deterministic runbook
   matches, the alert explicitly marks deterministic confidence below `0.8`, or no verified
   successful structured-memory match exists. Known deterministic remediation commits first and
   never waits for AI. The AI worker then collects a bounded context from persisted telemetry, deployment/source
   evidence, runbooks, and at most ten structured historical incidents.
2. Secret redaction runs recursively before prompt construction. Historical records, logs, diffs,
   labels, and source text are marked as untrusted data; instructions found in them have no
   authority.
3. The provider-neutral `LLMProvider` interface sends one strict operation to the configured
   OpenRouter adapter. The adapter asks for JSON matching the operation's Pydantic schema and
   rejects unknown fields, unknown actions, malformed evidence references, and oversized context.
4. The router tries the primary model, then the fallback for provider/schema failure. It uses the
   escalation model only for an ambiguous successful diagnosis under the configured policy.
5. CloudWard stores only the validated operator-facing result and invocation metadata. Hidden
   reasoning and raw prompts are not persisted.

Failure is safe: timeouts, HTTP errors, invalid JSON, schema violations, and exhausted fallbacks
produce `AI_UNAVAILABLE`. They do not delay or weaken deterministic remediation.

CloudWard also enforces a database-backed per-incident call budget. Consecutive provider failures
within the configured window open a shared circuit breaker, so an alert storm cannot multiply
OpenRouter failures or cost. While the circuit is open, known incidents continue through
deterministic runbooks and unknown incidents remain advisory-unavailable for human escalation.

## Configuration

AI diagnosis is off by default.

| Variable | Meaning |
| --- | --- |
| `CLOUDWARD_AI_DIAGNOSIS_ENABLED` | Enable advisory diagnosis scheduling. |
| `OPENROUTER_API_KEY` | Secret API credential; required outside local use when AI is enabled. |
| `CLOUDWARD_LLM_PRIMARY_MODEL` | Normal diagnosis model (`openai/gpt-5.6-terra` by default). |
| `CLOUDWARD_LLM_FALLBACK_MODEL` | Availability fallback (`google/gemini-3.5-flash-lite`). |
| `CLOUDWARD_LLM_ESCALATION_MODEL` | Selective escalation model (`openai/gpt-5.6-sol`). |
| `OPENROUTER_TIMEOUT_SECONDS` | Per-request timeout, bounded to 1–120 seconds. |
| `OPENROUTER_MAX_RETRIES` | Adapter retry bound, 0–3. |
| `OPENROUTER_MAX_CONTEXT_TOKENS` | Estimated input-token ceiling. |
| `AI_MAX_EVIDENCE_CHARS` | Sanitized serialized evidence ceiling, at most 60,000 characters. |
| `AI_MAX_MODEL_CALLS_PER_INCIDENT` | Hard incident-wide invocation budget, at most three. |
| `AI_CIRCUIT_BREAKER_FAILURE_THRESHOLD` | Consecutive failures required to open the circuit. |
| `AI_CIRCUIT_BREAKER_WINDOW_SECONDS` | Failure lookback and automatic recovery window. |

In AWS the OpenRouter credential stays on the EC2 control plane. It is not injected into EKS
workloads or GitOps manifests.

Model IDs are configuration, not application logic. Adding another provider means implementing
the same typed interface; callers do not depend on OpenRouter response shapes.

## APIs and audit evidence

- `GET /api/v1/incidents/{id}/diagnosis` returns the latest stored result or `NOT_REQUESTED`.
- `POST /api/v1/incidents/{id}/diagnosis` requests a fresh diagnosis for an operator.
- `POST /api/v1/incidents/{id}/diagnosis/actions/evaluate` gates one action that is present in the
  latest diagnosis. It creates no execution.

Audits capture requested and actual model IDs, latency, token counts when supplied, fallback and
escalation use, outcome, input digest, evidence references, and action-gate decisions. They never
contain API keys, raw authorization headers, or raw prompts. Diagnosis and gate progress is also
published through the durable incident event stream.
