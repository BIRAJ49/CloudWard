# AI and GitHub automation threat model

| Threat | Boundary and mitigation |
| --- | --- |
| Prompt injection in logs, traces, source, diffs, or history | All such material is bounded, recursively redacted, labelled untrusted, and placed below an immutable system instruction. Strict output schemas accept only known fields and registered action enums. |
| Secret disclosure to a model or audit log | Redaction runs before prompt construction and again at persistence boundaries. Credentials, authorization headers, private keys, JWTs, cloud keys, database URLs, and token-like values are replaced. Raw prompts and hidden reasoning are not stored. |
| Hallucinated or malicious action | AI has no executor dependency. A selected candidate must be in the latest validated diagnosis and then pass the registry, deterministic risk calculation, and fail-closed OPA. The AI gate creates a proposal only. |
| Provider outage or compromised response | Timeouts and retries are bounded, response JSON is schema-validated, model identity is recorded, fallback/escalation is explicit, and exhaustion becomes `AI_UNAVAILABLE` without blocking deterministic remediation. |
| GitHub credential theft | No PAT is supported. The App private key is a secret input, App JWTs are short-lived, installation tokens are memory-only and refreshed before expiry, and readiness APIs expose no identifiers or secrets. |
| Excessive GitHub write | Repository allowlists are separate for read, issues, and contents. File writes require a normalized relative path matching a configured glob. Pull requests are draft review artifacts; CloudWard has no merge operation. |
| Confused-deputy source attribution | Correlation requires explicit running and previous-healthy SHAs and always states correlation is not causation. Diff/source sizes are bounded and their content remains untrusted. |
| Retry creates duplicate external records | Issue and change-proposal operations use persisted deterministic deduplication keys and return the recorded external reference on retry. |

Residual risk includes a compromised GitHub App key or model provider observing already-redacted
incident context. Operators must rotate App keys, restrict the installation to required
repositories, review provider data-retention terms, and keep AI disabled where those controls are
not acceptable.
