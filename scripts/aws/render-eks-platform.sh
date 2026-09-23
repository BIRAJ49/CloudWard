#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

aws_require_command helm
aws_require_command kubectl

[[ $# -eq 1 ]] || aws_die "usage: $0 OUTPUT_DIRECTORY"
readonly output_directory="$1"
project_root="$(aws_repo_root)"
readonly project_root

mkdir -p "$output_directory"

aws_log "Refreshing pinned chart indexes for offline rendering"
helm repo add cilium https://helm.cilium.io/ --force-update
helm repo add kyverno https://kyverno.github.io/kyverno/ --force-update
helm repo add eks https://aws.github.io/eks-charts --force-update
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update
helm repo add grafana https://grafana.github.io/helm-charts --force-update
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts --force-update
helm repo add opencost https://opencost.github.io/opencost-helm-chart --force-update
helm repo add chaos-mesh https://charts.chaos-mesh.org --force-update
helm repo update

helm template cilium cilium/cilium \
  --namespace kube-system \
  --version "$CILIUM_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/cilium.yaml" \
  >"$output_directory/cilium.yaml"
helm template tetragon cilium/tetragon \
  --namespace tetragon \
  --version "$TETRAGON_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/tetragon.yaml" \
  >"$output_directory/tetragon.yaml"
helm template kyverno kyverno/kyverno \
  --namespace kyverno \
  --version "$KYVERNO_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/kyverno.yaml" \
  >"$output_directory/kyverno.yaml"
helm template karpenter oci://public.ecr.aws/karpenter/karpenter \
  --namespace kube-system \
  --version "$KARPENTER_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/karpenter.yaml" \
  >"$output_directory/karpenter.yaml"
helm template aws-load-balancer-controller eks/aws-load-balancer-controller \
  --namespace kube-system \
  --version "$AWS_LBC_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/aws-load-balancer-controller.yaml" \
  >"$output_directory/aws-load-balancer-controller.yaml"
helm template kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace observability \
  --version "$KUBE_PROMETHEUS_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/kube-prometheus-stack.yaml" \
  >"$output_directory/kube-prometheus-stack.yaml"
helm template loki grafana/loki \
  --namespace observability \
  --version "$LOKI_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/loki.yaml" \
  >"$output_directory/loki.yaml"
helm template tempo grafana/tempo \
  --namespace observability \
  --version "$TEMPO_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/tempo.yaml" \
  >"$output_directory/tempo.yaml"
helm template otel-collector open-telemetry/opentelemetry-collector \
  --namespace observability \
  --version "$OTEL_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/otel-collector.yaml" \
  >"$output_directory/otel-collector.yaml"
helm template opencost opencost/opencost \
  --namespace opencost \
  --version "$OPENCOST_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/opencost.yaml" \
  >"$output_directory/opencost.yaml"
helm template chaos-mesh chaos-mesh/chaos-mesh \
  --namespace chaos-mesh \
  --version "$CHAOS_MESH_AWS_CHART_VERSION" \
  --values "$project_root/k8s/aws/values/chaos-mesh.yaml" \
  >"$output_directory/chaos-mesh.yaml"

kubectl kustomize "$project_root/k8s/aws/platform" >"$output_directory/platform.yaml"
kubectl kustomize "$project_root/k8s/aws/karpenter" >"$output_directory/capacity.yaml"
kubectl kustomize "$project_root/k8s/aws/gateway" >"$output_directory/gateway.yaml"
kubectl kustomize "$project_root/k8s/aws/kyverno" >"$output_directory/executor-guards.yaml"
kubectl kustomize "$project_root/k8s/aws/forwarding" >"$output_directory/forwarding.yaml"
kubectl kustomize "$project_root/k8s/kyverno" >"$output_directory/cloudward-policies.yaml"

aws_log "Rendered pinned EKS assets to $output_directory without contacting a cluster"
