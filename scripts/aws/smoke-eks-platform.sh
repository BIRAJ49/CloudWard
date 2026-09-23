#!/usr/bin/env bash

# Read-only acceptance inventory. It never creates, patches, deletes, or
# executes a failure scenario.
set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

aws_require_command kubectl
aws_require_context

aws_log "Reading EKS node and add-on status"
kubectl get nodes -L cloudward.io/capacity-class,karpenter.sh/capacity-type
kubectl get daemonsets,deployments -A \
  -l app.kubernetes.io/part-of=cloudward

aws_log "Reading CNI, runtime-security, admission, and capacity resources"
kubectl get daemonset -n kube-system cilium
kubectl get daemonset -n tetragon tetragon
kubectl get deployments -n kyverno
kubectl get nodepools.karpenter.sh,ec2nodeclasses.karpenter.k8s.aws
kubectl get clusterpolicies.kyverno.io

aws_log "Reading Gateway and bounded telemetry resources"
kubectl get gatewayclasses.gateway.networking.k8s.io
kubectl get gateways.gateway.networking.k8s.io -A
kubectl get httproutes.gateway.networking.k8s.io -A
kubectl get prometheus,alertmanager -n observability
kubectl get service -n opencost

aws_log "Checking CloudWard group authorization without performing mutations"
kubectl auth can-i list pods --all-namespaces \
  --as=cloudward-smoke \
  --as-group=cloudward:observer
kubectl auth can-i delete pods -n cloudward-staging \
  --as=cloudward-smoke \
  --as-group=cloudward:executor
if kubectl auth can-i delete pods -n cloudward-production \
  --as=cloudward-smoke \
  --as-group=cloudward:executor | rg -qx yes; then
  aws_die "cloudward:executor unexpectedly has production pod deletion permission"
fi

aws_log "Read-only EKS smoke inventory completed"
