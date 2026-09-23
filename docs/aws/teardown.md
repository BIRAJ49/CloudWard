# Safe AWS teardown

Never run this procedure automatically. Teardown is a new destructive operation requiring a current destroy plan and explicit user approval. The S3 state backend is separate and is preserved by default.

## 1. Preserve evidence and data

Export non-secret test evidence, Terraform outputs, audit records, and the final cost snapshot. Run the PostgreSQL backup procedure and verify the dump before removing the control plane. Record whether EBS data may be discarded.

## 2. Remove Kubernetes-created AWS resources

From the intended EKS context only, delete or suspend GitOps objects that own public AWS resources. Review each command before execution:

```bash
kubectl config current-context
kubectl get gateways,httproutes -A
kubectl delete -f k8s/aws/gateway/ --ignore-not-found
kubectl get ingress,service -A
```

Wait until the AWS Load Balancer Controller has removed ALBs, target groups, listeners, and related security groups. Do not proceed while finalizers are stuck. Remove demo capacity and confirm Karpenter-created nodes/claims are gone before deleting Karpenter itself.

## 3. Produce a destroy plan

```bash
cd cloudward-infra/environments/aws-eu-north-1
terraform init \
  -backend-config="bucket=<state-bucket>" \
  -backend-config="key=cloudward/aws-eu-north-1/terraform.tfstate" \
  -backend-config="region=eu-north-1" \
  -backend-config="use_lockfile=true"
terraform plan -destroy -out=destroy.tfplan
../../../scripts/aws/summarize-terraform-plan.sh destroy.tfplan
terraform show destroy.tfplan
```

Verify the target account, region, workspace, plan checksum, expected destroys, Kubernetes load-balancer cleanup, snapshots/backups, and resources intentionally retained. Stop and show the plan to the user.

## 4. User-controlled destruction

Only after explicit approval of that exact destroy plan may the authorized user choose to run:

```bash
terraform apply destroy.tfplan
```

CloudWard provides no scheduled or automatic destroy workflow. Do not replace the reviewed artifact with an unreviewed `terraform destroy` command.

## 5. Confirm the result

Use read-only AWS inventory to check EKS, EC2, EBS, load balancers/target groups, Elastic IPs/public IPv4, NAT Gateways, security groups, CloudWatch log groups, and Karpenter-created instances. Record retained objects and remaining charges.

## 6. Preserve the state backend

Do not automatically delete the S3 backend. Its version history and bootstrap local state are disaster-recovery assets and may contain sensitive values. If the owner separately decides to remove it, first archive required state, inspect all object versions and lockfiles, create a dedicated bootstrap destroy plan, and obtain a second explicit approval.
