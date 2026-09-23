# Limitations and roadmap

## CloudWard v1 limitations

- Single tenant and one AWS account/region.
- One EKS cluster; staging and production are namespaces, not isolated accounts or clusters.
- One EC2 control plane with PostgreSQL on the same host; no control-plane/database HA.
- No multi-region or cross-cloud failover.
- AWS is an ephemeral portfolio environment; always-on EKS is incompatible with the approximate USD 50 target.
- Public-egress worker topology avoids NAT cost and is not an enterprise private-egress reference.
- Native Kubernetes Secrets remain; no AWS Secrets Manager/External Secrets integration yet.
- OpenCost is the only v1 cloud cost source. Its data and estimated impact can lag and must never be fabricated.
- No GCP implementation, predictive scaling, anomaly detection, or autonomous infrastructure optimization.
- Structured incident memory deliberately has no vector RAG.
- AI quality/provider availability varies; deterministic operation continues without it.
- Runtime/eBPF and telemetry controls have kernel, retention, coverage, and data-quality blind spots.
- One shared ALB and selected public demo routes are budget choices, not full service isolation.
- Disaster recovery is operator-driven; recovery objectives are unproven until real drills run.
- AWS definitions and tests in the repository are not proof of deployment. Unrun or credential-blocked checks remain unverified.

## Future roadmap

Potential v2/v3 work, intentionally not implemented in Part 4:

- GCP GKE and multi-cloud cluster registration.
- Separate management, staging, and production accounts/clusters.
- RDS PostgreSQL, HA control plane, and measured backup/recovery objectives.
- AWS Secrets Manager plus External Secrets and automated rotation.
- Multi-tenancy, tenant policy isolation, and delegated approvals.
- Anomaly detection and predictive scaling with offline evaluation and policy simulation.
- AWS Cost Explorer, Compute Optimizer, GCP Billing, and GCP Recommender adapters.
- Cross-cloud or multi-region failover and reliability game days.
- Advanced incident retrieval/RAG with poisoning, privacy, and provenance controls.
- Approval integrations and formal change-management evidence.
- Service mesh only where measured requirements justify its cost/complexity.
- Advanced eBPF detection with coverage and false-positive evaluation.

Roadmap items do not inherit authorization from Part 4 and require separate design, cost, threat-model, and approval work.
