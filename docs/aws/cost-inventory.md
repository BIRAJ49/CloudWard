# AWS cost inventory and budget guardrails

The target is approximately USD 50 per month, but an always-on EKS control plane can by itself conflict with that target. CloudWard therefore treats AWS as an ephemeral validation environment. Local k3d remains the daily environment. Prices vary by region and date; check the current AWS pricing calculator and the Terraform plan before each apply. This document does not invent a dollar savings figure.

| Category | Why it exists | Fixed/usage characteristic | Guardrail |
| --- | --- | --- | --- |
| EKS control plane | Real managed Kubernetes validation | Hourly while cluster exists | Short-lived demo windows; tear down after evidence capture |
| Managed system EC2 | Stable essential controllers | Instance uptime | One small On-Demand node, min/desired 1, max 2 |
| Karpenter EC2 | Demo workload capacity | Instance uptime; Spot price varies | Bounded CPU/memory/families; Spot for non-critical only; fallback On-Demand |
| Control-plane EC2 | Nginx/API/worker/PostgreSQL/Redis/OPA | Instance uptime | One reviewed small instance; stop or remove with the demo environment |
| EBS | Node/control-plane and observability data | GB-month and I/O | Small encrypted volumes; seven-day telemetry retention; no oversized PVC defaults |
| Public ALB | Gateway API demo ingress | Hourly plus LCU | One shared ALB, selected routes only; remove Kubernetes resources before teardown |
| Public IPv4 | EC2/ALB/node public addressing where used | Address-hours | Inventory every address; release during teardown |
| Data transfer | Internet/AZ/container pulls/telemetry | Usage | Keep images and evidence bounded; avoid unnecessary cross-AZ flow |
| CloudWatch | EKS control-plane logs and metrics | Ingestion/storage | Only useful logs, bounded retention, monitor volume |
| S3 | Terraform state versions/lockfile | Storage/requests | Tiny encrypted bucket; lifecycle old non-current versions conservatively |
| AWS Budget | Alerts, not an enforcement cap | Usually no material infrastructure cost | Alerts at 50%, 80%, and 100%; named recipient supplied by owner |
| Cloudflare/GitHub/OpenRouter/Teams | External services | Plan/provider dependent | Record separately; AI disabled/fallback when no approved budget |

No NAT Gateway is included in the cost-conscious portfolio topology. Adding one is a material architecture and cost change that requires a new ADR and plan review. Avoiding NAT is a deliberate compromise, not proof of enterprise equivalence.

Before apply, record current estimates and the planned lifetime. During the demo, inspect AWS Cost Explorer/Billing and OpenCost but label lagging or estimated data. The AWS Budget sends notifications; it cannot stop spend. Teardown is the primary cost control.
