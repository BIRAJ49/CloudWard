# ADR-019: Provider-neutral AI with an OpenRouter adapter

Status: Accepted

CloudWard depends on a typed `LLMProvider` interface rather than an OpenRouter response shape.
OpenRouter is the initial adapter because it can route the configured primary, fallback, and
selective escalation models through one controlled integration. Model IDs remain configuration.
This keeps provider replacement local and makes fallback, timeout, token-bound, and audit behavior
consistent across diagnosis operations.
