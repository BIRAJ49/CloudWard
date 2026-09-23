# Portfolio screenshot checklist

Use a clean demo account and staging-only data. Crop browser chrome where useful but retain timestamps/status context. Before capture, scan every frame for secrets, account IDs, private endpoints/IPs, OAuth state, cookies, authorization headers, GitHub App IDs/keys, OpenRouter keys, Teams URLs, database values, Terraform plan attributes, and personal notifications.

| Capture | Evidence to retain | Redaction/safety check |
| --- | --- | --- |
| Architecture | System and AWS trust boundaries | Domain/account aliases only |
| Overview | Fresh real status and limitations | No fabricated aggregate |
| Incident timeline | Correlation, states, attempts, verification | No raw secret-bearing evidence |
| Metrics/logs/traces | Bounded before/after window | Sanitize labels, URLs, payloads |
| AI vs OPA | Separate diagnosis/model from risk/policy authority | No prompt/hidden reasoning/key |
| Reliability remediation | Typed action, Git/Argo attribution, outcome | Staging namespace visible |
| Tetragon detection | Normalized controlled event | No host-sensitive process data |
| Cilium quarantine | Exact target and traffic verification | Prove required health remains |
| FinOps | Window, samples, recommendation, limitations | Label estimates; no invented savings |
| GitHub PR | Draft status, allowlisted file/digest | Hide installation/private repo data |
| Supply chain | Trivy/SBOM/Cosign/Kyverno evidence | No workflow tokens or full plan |
| Argo CD | Desired/live digest and health | Hide cluster endpoint |
| Karpenter | bounded NodePools/capacity attribution | Hide instance/account IDs |
| Audit | evidence→decision→action→verification | Hide user email if not consented |

Store screenshots under an intentional documentation path only after review. Never commit raw screen recordings or exports that have not passed the same sanitization.
