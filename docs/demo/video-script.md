# Short portfolio video script

Target: roughly 8–10 minutes. Prepare identifiers and sanitized tabs in advance; do not race through safety evidence.

| Time | Segment | Show and say |
| --- | --- | --- |
| 0:00–0:40 | Problem | Operations tools detect, explain, or automate in isolation. CloudWard closes the loop while keeping authority deterministic and auditable. |
| 0:40–1:30 | Architecture | Cloudflare→EC2 control plane, one EKS cluster/two namespaces, GitOps, telemetry, runtime security, and the policy boundary. State that AWS is ephemeral and v1 is not HA. |
| 1:30–2:00 | Healthy platform | Overview freshness, Argo health, EKS networking, system vs demo capacity, and signed digest. |
| 2:00–4:15 | Reliability | Trigger R1 in staging; show alert, incident, six evidence types, source correlation, optional AI diagnosis, risk, OPA, approval/action, Argo, and verified recovery. |
| 4:15–5:45 | Security | Trigger controlled S2; show Tetragon, normalized event, OPA-controlled Cilium quarantine, traffic proof, and cleanup. |
| 5:45–6:50 | FinOps | Show observed OpenCost/Prometheus inputs, deterministic F1 calculation, honest limitations, and draft GitOps PR requiring review. |
| 6:50–7:40 | Supply chain | Trivy, CycloneDX, keyless Cosign, immutable digest, Kyverno signed/unsigned/wrong-identity outcomes, and promotion PR. |
| 7:40–8:30 | Audit and close | Show the complete audit and max-three-attempt escalation. Repeat: AI investigates; runbooks, risk, OPA, approvals, typed execution, and verification authorize outcomes. |

If any dependency is unavailable, show the recorded unavailable/blocked state rather than a prepared success screen. End with limitations, cost/teardown ownership, and the local-first workflow.
