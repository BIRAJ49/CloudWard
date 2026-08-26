# Security policy

CloudWard is a portfolio and local-development platform, not a hosted security service. Do not use Part 1 against production infrastructure.

## Reporting a vulnerability

Do not open a public issue containing secrets, credentials, exploit details, personal data, or access tokens. Contact the repository owner privately with the affected revision, impact, and a minimal reproduction.

## Secret handling

Only placeholder values belong in version control. Put local credentials in `.env`, which is ignored. Logs, incident evidence, API errors, and audit metadata must pass through redaction and must never include authorization headers, cookies, private keys, Kubernetes Secret values, or OAuth client secrets.

## Remediation boundary

CloudWard Part 1 permits only registered, typed actions after deterministic evidence, runbook, risk, OPA, and approval gates. It intentionally provides no general shell, `kubectl`, `exec`, secret-reading, infrastructure-destruction, IAM-mutation, or arbitrary outbound-request facility. See `docs/architecture/safety-boundary.md` for the full boundary.

