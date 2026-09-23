# AWS portfolio demo guide

This guide is a safe evidence script, not a claim that the AWS demo has run. Use only the controlled `cloudward-staging` targets. Confirm account, region, context `cloudward-eks`, demo labels, budget window, rollback, and observers before triggering anything.

## Preflight

- Terraform/state/IAM/network review is complete and no unexpected drift exists.
- EKS platform, CloudWard readiness, Argo applications, telemetry, Tetragon, Cilium, Kyverno, OpenCost, and the shared Gateway/ALB are healthy with recorded evidence.
- Production Incident Lab targets are rejected; staging targets carry `cloudward.io/demo-target=true`.
- The current staging image is digest-pinned, signed by the allowed identity, and has its SBOM attestation.
- No credentials, account IDs, private hostnames, IPs, webhook URLs, user data, or sensitive logs will appear on screen.
- A rollback owner and hard end time are named. Teardown is a separate user-approved procedure.

## Demonstration sequence

1. Show the architecture diagram and identify Cloudflare, EC2, EKS, GitOps, policy, telemetry, and trust boundaries.
2. Show the healthy Overview, clusters/services, staging/production separation, and data freshness.
3. Trigger the bounded bad-deployment scenario in staging only.
4. Show the real Prometheus alert and authenticated Alertmanager delivery.
5. Follow incident creation and SSE timeline.
6. Show bounded metrics, logs, traces, Kubernetes, deployment, and Git evidence.
7. Show advisory AI diagnosis and clearly label provider/model/confidence/limitations.
8. Show deterministic six-factor risk separately.
9. Show OPA's final policy decision and approval binding.
10. Show the typed remediation or draft GitOps revert—never arbitrary shell execution.
11. Show Argo reconcile the reviewed desired state.
12. Show multi-signal health verification and resolution/rollback/escalation result.
13. Show the durable audit answering who, what, evidence, policy, action, and result.
14. Trigger S2's controlled unexpected egress to the internal simulator.
15. Show the authentic Tetragon event and normalized security incident.
16. Show risk/OPA and the narrow Cilium quarantine.
17. Prove prohibited egress is blocked while required service health remains; then clean up.
18. Show F1's observed Prometheus/OpenCost window, deterministic recommendation, confidence, and limitations.
19. Show the draft staging PR and required human review; do not merge for the demo unless separately approved.
20. Show CI's Trivy gate, CycloneDX evidence, keyless Cosign identity, digest-only deployment, and Kyverno admission results.

## Evidence record

For each R1–R4, S1–S3, and F1–F2 run, capture:

| Field | Required evidence |
| --- | --- |
| Identity | Scenario ID, UTC window, incident/recommendation ID, correlation ID |
| Detection | Real alert/runtime/allocation source and freshness |
| Decision | Runbook, AI participation or unavailability, risk breakdown, OPA reason, approval identity/expiry |
| Action | Typed action or PR, exact target, attempt number, Git/Argo attribution |
| Verification | Before/after metrics plus workload/application/policy signals |
| Outcome | Resolved, rolled back, blocked, or escalated; notification/audit references |
| Limitations | Missing data, shortened demo window, delayed cost data, residual risk |

Never use attacker infrastructure, malware, a real exploit, host compromise, IAM escalation, database destruction, production chaos, or Terraform destruction. A blocked or unavailable dependency is reported honestly.
