#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command kubectl
require_context
project_root="$(repo_root)"
readonly project_root

log "Validating Cilium is the active, healthy CNI"
kubectl -n kube-system rollout status daemonset/cilium --timeout=2m
kubectl -n kube-system rollout status deployment/cilium-operator --timeout=2m
kubectl -n kube-system get daemonset cilium -o jsonpath='{.status.numberReady}' | grep -Eq '^[1-9][0-9]*$'
if kubectl -n kube-system get daemonset kube-flannel-ds >/dev/null 2>&1; then
  die "Flannel is present; Cilium is not the sole intended CNI"
fi

log "Validating Argo CD and Git-managed demo application"
kubectl -n argocd wait --for=condition=Available deployments --all --timeout=2m
[[ "$(kubectl -n argocd get application cloudward-demo -o jsonpath='{.status.sync.status}')" == "Synced" ]]
[[ "$(kubectl -n argocd get application cloudward-demo -o jsonpath='{.status.health.status}')" == "Healthy" ]]

log "Validating Kyverno and baseline policies"
kubectl -n kyverno wait --for=condition=Available deployments --all --timeout=2m
for policy_name in \
  cloudward-disallow-privileged-containers \
  cloudward-disallow-host-namespaces \
  cloudward-disallow-unsafe-capabilities \
  cloudward-require-demo-target-safety \
  cloudward-restrict-chaos-targets; do
  kubectl get clusterpolicy "$policy_name" >/dev/null
done

log "Exercising Kyverno admission enforcement with server-side dry runs"
kubectl apply --dry-run=server -f - >/dev/null <<'YAML'
apiVersion: v1
kind: Pod
metadata:
  name: cloudward-policy-compliant
  namespace: cloudward-staging
spec:
  automountServiceAccountToken: false
  securityContext:
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: app
      image: registry.k8s.io/pause:3.10
      securityContext:
        allowPrivilegeEscalation: false
        privileged: false
        capabilities:
          drop: ["ALL"]
YAML

expect_admission_rejection() {
  local fixture_name="$1"
  if kubectl apply --dry-run=server -f "$fixture_name" >/dev/null 2>&1; then
    die "unsafe fixture unexpectedly passed admission: $fixture_name"
  fi
}

expect_admission_rejection "$project_root/k8s/kyverno/testdata/privileged-pod.yaml"
expect_admission_rejection "$project_root/k8s/kyverno/testdata/host-network-pod.yaml"
expect_admission_rejection "$project_root/k8s/kyverno/testdata/unsafe-capability-pod.yaml"
expect_admission_rejection "$project_root/k8s/kyverno/testdata/production-demo-target.yaml"

log "Validating namespaces and the controlled staging workload"
kubectl get namespace cloudward-staging cloudward-production >/dev/null
readonly executor_identity="system:serviceaccount:cloudward-staging:cloudward-executor"
[[ "$(kubectl auth can-i get pods -n cloudward-staging --as="$executor_identity")" == "yes" ]]
[[ "$(kubectl auth can-i delete pods -n cloudward-staging --as="$executor_identity")" == "yes" ]]
[[ "$(kubectl auth can-i delete pods -n cloudward-production --as="$executor_identity")" == "no" ]]
kubectl -n cloudward-staging rollout status deployment/cloudward-demo --timeout=3m
[[ "$(kubectl -n cloudward-staging get deployment cloudward-demo -o jsonpath='{.spec.replicas}')" -ge 2 ]]
[[ "$(kubectl -n cloudward-staging get deployment cloudward-demo -o jsonpath='{.spec.template.metadata.labels.cloudward\.io/demo-target}')" == "true" ]]

log "Platform validation passed"
