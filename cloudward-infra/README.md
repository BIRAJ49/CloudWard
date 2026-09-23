# CloudWard AWS infrastructure

This repository provisions the cost-conscious, ephemeral AWS foundation for
CloudWard in `eu-north-1`. Terraform owns AWS infrastructure and bootstrap
controllers; Argo CD remains the owner of platform and application workloads.

## Architecture and trade-offs

- One EKS cluster hosts `cloudward-staging` and `cloudward-production` as
  separate namespaces. It is not equivalent to account or cluster isolation.
- The EKS API has private access enabled. Public access is fail-closed to the
  explicit `/32` or `/128` CIDRs supplied by the operator.
- A one-node On-Demand managed node group bootstraps critical controllers.
  Karpenter has bounded On-Demand critical capacity and bounded Spot-preferred
  demo capacity with On-Demand fallback.
- There is no NAT gateway. EKS nodes use tightly controlled public subnets,
  public IPv4 addresses, IMDSv2, encrypted EBS, and security groups with no
  inbound Internet rules. This saves NAT hourly/data charges but is weaker than
  private nodes with controlled egress and creates public IPv4 charges.
- Two isolated private subnets are retained for future private resources. They
  have no Internet route and are not used for nodes in v1.
- The single AL2023 control-plane EC2 host is reachable on HTTPS only from
  configured Cloudflare address ranges, has no SSH rule or key pair, and is
  administered through Systems Manager. IMDSv2 tokens remain mandatory; its
  hop limit is 2 so trusted bridged Compose containers can use the instance
  role. Do not run untrusted containers on this host. Application secrets are
  not accepted by Terraform and must be delivered separately through an
  approved secret process.
- EBS volumes are encrypted and the observability StorageClass uses bounded
  `gp3` volumes. Prometheus/Loki/Tempo retention must remain seven days in the
  GitOps configuration.

An always-on environment cannot meet a USD 50 monthly target: the EKS control
plane alone is a major fixed cost, before EC2, public IPv4, EBS, ALB, logs, and
data transfer. Treat this environment as a short-lived validation/demo system;
local k3d remains the daily environment.

## Layout

```text
bootstrap/state-backend/          S3 backend created from local state
modules/                          Small, reusable AWS modules
environments/aws-eu-north-1/      The only real v1 environment
```

## Remote-state bootstrap

The backend cannot create itself. Keep this sequence explicit:

1. Copy `bootstrap/state-backend/terraform.tfvars.example` to the ignored
   `terraform.tfvars`, choose a globally unique bucket name, and initialize the
   bootstrap configuration with local state.
2. Review its plan. Only after explicit approval, apply that plan to create the
   encrypted, versioned, public-blocked S3 bucket and restricted IAM policy.
3. Attach the output state-access policy only to the CI/operator roles that
   need Terraform state access.
4. Copy `environments/aws-eu-north-1/backend.hcl.example` to the ignored
   `backend.hcl` and set the created bucket name.
5. Initialize the environment with `terraform init -backend-config=backend.hcl`.
   The checked-in backend uses native S3 locking (`use_lockfile = true`); there
   is deliberately no DynamoDB table.
6. If local environment state already exists, use `terraform init
   -migrate-state -backend-config=backend.hcl`, inspect both locations, then
   protect the remaining bootstrap state offline.

Never move or delete state manually. Never remove the backend bucket as part of
the main environment teardown.

## Deliberate prerequisites

Before planning, replace every placeholder in the example variables and verify:

- the operator CIDRs and Terraform administrator role ARNs;
- EKS 1.35 remains supported in `eu-north-1`;
- selected EC2 instance types and Karpenter version are available/compatible;
- current Cloudflare origin CIDRs if public control-plane ingress is enabled;
- the CI/operator identity has only the required backend and provisioning roles.

The dependency lock file is not fabricated. Generate `.terraform.lock.hcl`
during the later approved `terraform init` validation step, then review and
commit it. No initialization, plan, apply, AWS call, or validation was run while
this implementation was created.

## Apply boundary

Planning does not authorize provisioning. Before any apply, report resources,
changes/destroys, IAM and networking implications, costs, public exposure,
state impact, and rollback strategy, then obtain explicit approval.

## Safe teardown order

Do not execute this automatically:

1. Remove Argo-managed `Gateway`, `Service`, and Karpenter workloads that own
   ALBs, target groups, ENIs, or nodes; wait for their AWS resources to disappear.
2. Confirm Karpenter workload nodes and interruption resources can be removed.
3. Produce and review a destroy plan for `environments/aws-eu-north-1`.
4. Obtain explicit approval, then run the exact reviewed destroy plan.
5. Preserve the S3 backend. Its deletion is a separate, explicitly approved
   operation after state has been retained according to policy.
