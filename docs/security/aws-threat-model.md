# AWS threat model

Status: controls are designed in repository code; effectiveness requires real AWS and EKS validation. CloudWard reduces risk but does not claim zero risk.

## Assets and trust boundaries

Protected assets include AWS/IAM control, Terraform state, GitHub identities and source, EKS API and workloads, EC2 secrets/data, PostgreSQL incident/audit history, signing identity, OAuth sessions, webhooks, observability evidence, and production GitOps state.

Trust boundaries are Internet→Cloudflare, Cloudflare→Nginx origin, browser→FastAPI, GitHub→OAuth/App/webhooks, GitHub Actions→AWS OIDC, EC2→EKS, workload→AWS API, sensor/Alertmanager→CloudWard webhooks, evidence→AI provider, and staging→production promotion.

## Threats and controls

| Threat | Actor/path | Preventive controls | Detection/response | Residual risk |
| --- | --- | --- | --- | --- |
| Origin bypass/DDoS | Internet to EC2 | Cloudflare-only 443 security-group sources, full-strict TLS, authenticated origin pulls, Nginx limits, no SSH | VPC/Cloudflare/Nginx logs, health alerts; block/rotate origin | Cloudflare ranges/config drift; one EC2 can be exhausted |
| Credential theft | Repo, host, container, CI | No static AWS keys; IMDSv2; instance/OIDC/workload roles; root-owned env; redaction; no PAT | CloudTrail/GitHub/audit review, rotate/revoke, suspend automation | Host compromise can use its current role |
| IAM privilege escalation | Terraform/compromised workflow | Separate plan/apply roles, protected environment, least privilege, locked workflow, reviewed plan | CloudTrail/config review, budget/security alerts | Apply role can change resources within its scope |
| Terraform state disclosure/corruption | S3 access or concurrent writer | Dedicated encrypted versioned public-blocked bucket, TLS policy, native lockfile, narrow prefix permissions | S3/CloudTrail/version recovery, halt writers | State can still hold sensitive provider values |
| EKS API takeover | Public endpoint/EC2 role | Private endpoint plus narrow public CIDRs, EKS access entries, bounded Kubernetes RBAC, no cluster-admin CloudWard | Control-plane audit/authenticator logs | Misconfigured access entry/RBAC can expand impact |
| Container escape/runtime attack | Demo workload | Non-root images, seccomp/capability policies, Kyverno, Tetragon, Cilium segmentation, bounded demos | Runtime event→risk→OPA→verified quarantine | Kernel/eBPF blind spots; quarantine may affect legitimate traffic |
| Supply-chain substitution | CI/GHCR/GitOps | Trivy gate, CycloneDX, keyless Cosign, digest references, Kyverno identity verification, promotion PR | Admission rejection and CI attestations | Trusted workflow/repository compromise remains material |
| Prompt injection/data exfiltration | Logs, traces, source, diffs | Bounded redacted untrusted context, immutable instruction, schema validation, no tool authority, provider off switch | AI audit, fallback/circuit breaker, key rotation | Provider sees redacted context; model can still be wrong |
| Unauthorized remediation | User/model/forged event | GitHub OAuth RBAC, signed webhooks, typed allowlist, deterministic risk, fail-closed OPA, approval TTL/binding, max attempts | Immutable audit, verification, rollback/escalation | Valid privileged account or policy defect can authorize harm |
| Admission-policy outage | Bad Kyverno policy | Scope only CloudWard app namespaces/identities, test policies, stable system workloads, GitOps rollback | Admission errors, Kyverno metrics/logs | Fail-closed policy can block urgent deployments |
| Network-policy lockout | Bad Cilium quarantine | Target labels/namespaces, bounded policy templates, OPA, rollback, management-path preservation | Connectivity checks and multi-signal verification | CNI failure can affect broad cluster traffic |
| Public failure endpoint abuse | Demo API | Staging-only, explicit label, auth/RBAC/OPA, rate limits, hard production deny | Incident Lab audit and malicious-target tests | Authenticated operator can still create bounded disruption |
| Data loss | EC2/EBS/operator action | Encrypted EBS, private backups, GitOps source of truth, state versions, explicit restore/destroy confirmation | Restore drills and integrity checks | No HA database; RPO is last verified backup |
| Cost exhaustion | Compromised scaling/forgotten cluster | AWS Budget alerts, Karpenter limits, small node group, no NAT, teardown process, local-first use | Billing review/OpenCost, explicit lifetime owner | Budgets alert but do not cap spend; EKS fixed hourly cost |

## Control separation

- IAM constrains AWS API authority; Kubernetes RBAC constrains Kubernetes verbs/resources.
- OPA authorizes CloudWard decisions; Kyverno validates admitted resources.
- Cilium enforces network behavior; Tetragon detects runtime behavior.
- Git branch/environment protection governs persistent production change.
- Audit records decisions and actions but does not itself prevent them.

Webhook HMAC/signature verification, replay windows, body limits, and rate limits apply before parsing events. Secret values must never enter labels, Terraform variables/state unless unavoidable, URLs, screenshots, prompts, or logs. Native Kubernetes Secrets are an acknowledged v1 limitation; future External Secrets/Secrets Manager work is deferred.
