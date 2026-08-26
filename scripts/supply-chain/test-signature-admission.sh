#!/usr/bin/env bash

set -Eeuo pipefail

readonly expected_context="${EXPECTED_KUBE_CONTEXT:-k3d-cloudward}"
readonly namespace="${SIGNATURE_TEST_NAMESPACE:-cloudward-staging}"
readonly approved_identity_subject="${APPROVED_IDENTITY_SUBJECT:-https://github.com/biraj49/CloudWard/.github/workflows/release.yml@refs/heads/main}"
readonly github_oidc_issuer="https://token.actions.githubusercontent.com"

for command_name in kubectl jq cosign; do
  command -v "$command_name" >/dev/null 2>&1 || {
    printf 'error: required command not found: %s\n' "$command_name" >&2
    exit 69
  }
done
[[ -n "${WRONG_IDENTITY_SUBJECT:-}" ]] || {
  printf 'error: WRONG_IDENTITY_SUBJECT must identify the signer of WRONG_IDENTITY_IMAGE\n' >&2
  exit 64
}
for variable_name in UNSIGNED_IMAGE WRONG_IDENTITY_IMAGE APPROVED_SIGNED_IMAGE; do
  [[ -n "${!variable_name:-}" ]] || {
    printf 'error: %s must contain a real digest-pinned test image\n' "$variable_name" >&2
    exit 64
  }
  [[ "${!variable_name}" =~ ^ghcr\.io/biraj49/cloudward-[a-z0-9._-]+@sha256:[a-f0-9]{64}$ ]] || {
    printf 'error: %s is not an allowed immutable CloudWard image reference\n' "$variable_name" >&2
    exit 65
  }
done
[[ "$(kubectl config current-context)" == "$expected_context" ]] || {
  printf 'error: refusing context %s; expected %s\n' \
    "$(kubectl config current-context)" "$expected_context" >&2
  exit 77
}

unsigned_output=""
if unsigned_output="$(cosign verify \
  --certificate-identity-regexp '.*' \
  --certificate-oidc-issuer-regexp '.*' \
  "$UNSIGNED_IMAGE" 2>&1)"; then
  printf 'error: UNSIGNED_IMAGE has a verifiable keyless signature\n' >&2
  exit 1
fi
if [[ "$unsigned_output" != *"no signatures found"* && \
      "$unsigned_output" != *"no matching signatures"* ]]; then
  printf 'error: unable to prove the unsigned fixture is unsigned: %s\n' \
    "$unsigned_output" >&2
  exit 1
fi
cosign verify \
  --certificate-identity "$WRONG_IDENTITY_SUBJECT" \
  --certificate-oidc-issuer "$github_oidc_issuer" \
  "$WRONG_IDENTITY_IMAGE" >/dev/null
cosign verify \
  --certificate-identity "$approved_identity_subject" \
  --certificate-oidc-issuer "$github_oidc_issuer" \
  "$APPROVED_SIGNED_IMAGE" >/dev/null

pod_manifest() {
  local name="$1"
  local image="$2"
  jq -n --arg name "$name" --arg namespace "$namespace" --arg image "$image" '{
    apiVersion: "v1",
    kind: "Pod",
    metadata: {
      name: $name,
      namespace: $namespace,
      labels: {"app.kubernetes.io/name": "cloudward-signature-test"}
    },
    spec: {
      automountServiceAccountToken: false,
      restartPolicy: "Never",
      securityContext: {
        runAsNonRoot: true,
        runAsUser: 10001,
        seccompProfile: {type: "RuntimeDefault"}
      },
      containers: [{
        name: "probe",
        image: $image,
        command: ["/bin/true"],
        securityContext: {
          allowPrivilegeEscalation: false,
          privileged: false,
          readOnlyRootFilesystem: true,
          capabilities: {drop: ["ALL"]}
        }
      }]
    }
  }'
}

assert_signature_rejected() {
  local name="$1"
  local image="$2"
  local output
  if output="$(pod_manifest "$name" "$image" | kubectl create --dry-run=server -f - 2>&1)"; then
    printf 'error: admission unexpectedly allowed %s\n' "$name" >&2
    exit 1
  fi
  if [[ "$output" != *"cloudward-verify-signed-images"* ]]; then
    printf 'error: %s was rejected for a reason other than signature policy: %s\n' \
      "$name" "$output" >&2
    exit 1
  fi
  printf 'REJECTED %s\n' "$name"
}

assert_signature_allowed() {
  local name="$1"
  local image="$2"
  pod_manifest "$name" "$image" | kubectl create --dry-run=server -f - >/dev/null
  printf 'ALLOWED %s\n' "$name"
}

assert_signature_rejected cloudward-unsigned "$UNSIGNED_IMAGE"
assert_signature_rejected cloudward-wrong-identity "$WRONG_IDENTITY_IMAGE"
assert_signature_allowed cloudward-approved-signed "$APPROVED_SIGNED_IMAGE"
