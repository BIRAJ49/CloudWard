#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

aws_require_command helm
aws_require_command kubectl
aws_require_command rg
aws_require_context
aws_require_apply_opt_in
aws_require_resolved_inputs

project_root="$(aws_repo_root)"
readonly project_root

aws_log "Applying namespaces, service accounts, and bounded CloudWard RBAC"
kubectl apply --server-side -k "$project_root/k8s/aws/platform"

aws_log "Installing pinned Gateway API and AWS LBC Gateway CRDs"
kubectl apply --server-side -f "https://github.com/kubernetes-sigs/gateway-api/releases/download/$GATEWAY_API_VERSION/standard-install.yaml"
kubectl apply --server-side -f "https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/$AWS_LBC_APP_VERSION/docs/install/gateway_crds.yaml"

helm repo add cilium https://helm.cilium.io/ --force-update
helm repo add kyverno https://kyverno.github.io/kyverno/ --force-update
helm repo add eks https://aws.github.io/eks-charts --force-update
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update
helm repo add grafana https://grafana.github.io/helm-charts --force-update
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts --force-update
helm repo add opencost https://opencost.github.io/opencost-helm-chart --force-update
helm repo add chaos-mesh https://charts.chaos-mesh.org --force-update
helm repo update

aws_log "Installing Cilium in AWS VPC CNI chaining mode"
helm upgrade --install cilium cilium/cilium \
  --namespace kube-system \
  --version "$CILIUM_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/cilium.yaml" \
  --atomic --wait --timeout 15m

aws_log "Installing runtime and admission controls"
helm upgrade --install tetragon cilium/tetragon \
  --namespace tetragon \
  --version "$TETRAGON_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/tetragon.yaml" \
  --atomic --wait --timeout 15m
helm upgrade --install kyverno kyverno/kyverno \
  --namespace kyverno \
  --version "$KYVERNO_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/kyverno.yaml" \
  --atomic --wait --timeout 15m

aws_log "Installing bounded Karpenter and AWS Load Balancer Controller"
helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter \
  --namespace kube-system \
  --version "$KARPENTER_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/karpenter.yaml" \
  --atomic --wait --timeout 15m
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  --namespace kube-system \
  --version "$AWS_LBC_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/aws-load-balancer-controller.yaml" \
  --atomic --wait --timeout 15m

aws_log "Installing seven-day bounded observability and OpenCost"
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace observability \
  --version "$KUBE_PROMETHEUS_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/kube-prometheus-stack.yaml" \
  --atomic --wait --timeout 20m
helm upgrade --install loki grafana/loki \
  --namespace observability \
  --version "$LOKI_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/loki.yaml" \
  --atomic --wait --timeout 15m
helm upgrade --install tempo grafana/tempo \
  --namespace observability \
  --version "$TEMPO_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/tempo.yaml" \
  --atomic --wait --timeout 15m
helm upgrade --install otel-collector open-telemetry/opentelemetry-collector \
  --namespace observability \
  --version "$OTEL_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/otel-collector.yaml" \
  --atomic --wait --timeout 15m
helm upgrade --install opencost opencost/opencost \
  --namespace opencost \
  --version "$OPENCOST_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/opencost.yaml" \
  --atomic --wait --timeout 15m

aws_log "Installing Chaos Mesh with daemon placement restricted to demo capacity"
helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
  --namespace chaos-mesh \
  --version "$CHAOS_MESH_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/chaos-mesh.yaml" \
  --atomic --wait --timeout 15m

aws_log "Applying scoped policies, capacity, shared Gateway, and authenticated forwarding"
kubectl apply --server-side -k "$project_root/k8s/kyverno"
kubectl apply --server-side -k "$project_root/k8s/aws/kyverno"
kubectl apply --server-side -k "$project_root/k8s/aws/karpenter"
kubectl apply --server-side -k "$project_root/k8s/aws/gateway"
kubectl apply --server-side -k "$project_root/k8s/aws/forwarding"

aws_log "Platform install submitted. Existing pods are not restarted automatically for Cilium chaining."
