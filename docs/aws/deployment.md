# AWS bootstrap, deployment, and validation guide

This is an operator procedure, not evidence that AWS has been provisioned. Commands that create, modify, or destroy AWS resources require a fresh plan review and explicit user approval.

## Prerequisites

- An AWS account authorized for the portfolio environment and current AWS CLI v2.
- Terraform matching `cloudward-infra` version constraints, plus TFLint and Trivy.
- `kubectl`, Helm, `jq`, Cosign, and the other pinned repository tools.
- A narrow EKS public-access CIDR for the operator/bootstrap path; never use `0.0.0.0/0` as a lasting default.
- GitHub OIDC plan/apply roles and protected environments configured as described below.
- Optional Cloudflare domain configuration supplied by the owner. The repository never invents or purchases a domain.

Use the repository's selected EKS/Kubernetes and add-on versions. Re-check their support in `eu-north-1` immediately before provisioning; a committed version is a reviewed baseline, not a claim of perpetual support.

## 1. Bootstrap remote state

The S3 backend cannot create itself. Its configuration starts with local state:

```bash
cd cloudward-infra/bootstrap/state-backend
terraform init
terraform fmt -check
terraform validate
terraform plan -out=bootstrap.tfplan
terraform show bootstrap.tfplan
```

Review the single-purpose bucket, versioning, server-side encryption, public-access block, bucket policy, IAM implications, and cost. Only after explicit approval may an operator run:

```bash
terraform apply bootstrap.tfplan
```

Record the non-secret bucket name. Protect the bootstrap local state as sensitive recovery material. Do not add DynamoDB: main state uses Terraform's S3 native lockfile (`use_lockfile = true`). Do not move state manually without a recorded recovery procedure.

## 2. Configure main infrastructure

Copy the non-secret example variables to an ignored file and fill only reviewed values:

```bash
cd cloudward-infra/environments/aws-eu-north-1
cp terraform.tfvars.example terraform.tfvars
terraform init \
  -backend-config="bucket=<state-bucket>" \
  -backend-config="key=cloudward/aws-eu-north-1/terraform.tfstate" \
  -backend-config="region=eu-north-1" \
  -backend-config="use_lockfile=true"
```

Never commit real `terraform.tfvars`, state, plans, credentials, private keys, OAuth secrets, OpenRouter keys, or Teams webhook URLs.

## 3. Acceptance before apply

Run each gate once and retain its output:

```bash
terraform fmt -check -recursive ../../
terraform validate
tflint --recursive
trivy config ../../
terraform plan -out=tfplan
../../../scripts/aws/summarize-terraform-plan.sh tfplan
```

Complete [the plan-review record](terraform-plan-review.md). It must state creates, changes, destroys, IAM, networking, public exposure, cost categories, state/data implications, and rollback. Stop and request explicit approval. A plan with an unexpected destroy is not approvable.

## 4. Apply only an approved plan

The preferred path is `.github/workflows/terraform-apply.yml` on `main`. It requires:

1. manual `workflow_dispatch`;
2. exact `APPLY` confirmation;
3. a new plan generated from the checked-out commit;
4. approval from required reviewers on `aws-eu-north-1-apply`;
5. an apply-role OIDC session distinct from the plan role;
6. checksum verification of the exact plan artifact.

Configure the GitHub environments with no self-approval, trusted branches limited to `main`, and short-lived OIDC roles. Repository/environment variables are `AWS_TERRAFORM_PLAN_ROLE_ARN`, `AWS_TERRAFORM_APPLY_ROLE_ARN`, `TF_STATE_BUCKET`, `TF_STATE_KEY`, `EKS_PUBLIC_ACCESS_CIDRS`, and `MONTHLY_BUDGET_USD`. Secrets do not belong in those variables.

An authorized local operator may instead apply the already-reviewed binary plan:

```bash
terraform apply tfplan
```

Do not substitute a fresh unreviewed plan. Capture non-secret outputs and redact account IDs, hostnames, or identifiers when sharing publicly.

## 5. Bootstrap the cluster and control plane

Terraform provides infrastructure and prerequisites. Argo CD remains the ongoing Kubernetes deployer.

1. Confirm VPC, restricted EKS endpoint, system node group, EC2 instance profile, budget, and state controls.
2. Establish the dedicated CloudWard EKS access entry and bounded Kubernetes RBAC.
3. Bootstrap Argo CD and the platform applications from `cloudward-gitops`.
4. Confirm AWS VPC CNI before installing Cilium in AWS-CNI chaining mode.
5. Reconcile Kyverno, Tetragon, Karpenter, AWS Load Balancer Controller, observability, OpenCost, and Chaos Mesh with their AWS values.
6. Place reviewed secrets on the EC2 host in root-owned `.env.production`; never render them into Terraform state or Git.
7. Install Cloudflare origin material outside Git, restrict the EC2 security group to Cloudflare ingress, then run `scripts/aws/bootstrap-control-plane.sh` with its explicit confirmation. Using the EC2 instance role, it generates `/opt/cloudward/.aws/cloudward-kubeconfig` with alias `cloudward-eks`; it writes no static keys. It prepares the Compose and loopback-only telemetry systemd units but intentionally starts neither.
8. Start the stack only after inspecting `docker-compose.yml`, `docker-compose.production.yml`, and the resolved environment.

The EKS platform helpers have distinct safety boundaries:

```bash
scripts/aws/render-eks-platform.sh <explicit-output-directory>
scripts/aws/install-eks-platform.sh
scripts/aws/smoke-eks-platform.sh
```

Rendering writes pinned Helm/Kustomize output to the required directory and does not contact a cluster. Installation is state-changing: review the script, resolve every required real host/image value, set context `cloudward-eks`, satisfy its explicit apply opt-in, and obtain deployment approval before running it. It fails closed for `.invalid` forwarding hosts, a zero image digest, or `al2023@latest`. The smoke helper is read-only, verifies the expected context, inventories add-ons, and checks that CloudWard executor RBAC cannot delete production pods.

## 6. Post-deployment validation

Do not mark a component complete because Terraform or Helm returned success. Record real evidence for:

- VPC/subnets/routes/security groups, no inbound SSH, and expected public IPv4 exposure.
- EKS `ACTIVE`, private endpoint on, public endpoint CIDRs exact, `api`/`audit`/`authenticator` logs as configured.
- AWS VPC CNI, Cilium agents/chaining, DNS, pod/service networking, and quarantine enforcement.
- On-Demand system capacity and bounded Karpenter Spot/fallback behavior.
- Argo CD sync/health, namespace boundaries, digest-pinned staging and promotion-controlled production.
- Kyverno signed/unsigned/wrong-identity admission cases and system-namespace scope.
- Tetragon event delivery, observability stores, seven-day retention, Alertmanager webhook authentication, and OpenCost evidence.
- Shared ALB/Gateway routes only intended demo services; PostgreSQL, Redis, OPA, workers, and telemetry internals are unreachable publicly.
- Cloudflare full-strict TLS and authenticated origin pull; the origin is not reachable through an untrusted path.
- GitHub OAuth/RBAC/App, optional OpenRouter graceful degradation, Teams non-blocking delivery, SSE, and audit.
- R1–R4, S1–S3, and F1–F2 against staging-only controlled targets, including verification and bounded escalation.

Use `blocked` or `not run` for anything lacking credentials, a domain, real traffic, or AWS evidence. Never infer a pass.
