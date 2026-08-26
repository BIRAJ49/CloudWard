#!/usr/bin/env bash

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib.sh"

require_command docker
require_command git
require_command helm
require_command k3d
require_command kubectl
require_context

project_root="$(repo_root)"
readonly project_root
snapshot_root="$(mktemp -d "${TMPDIR:-/tmp}/cloudward-gitops.XXXXXXXX")"
readonly snapshot_root
readonly work_tree="$snapshot_root/work"
readonly bare_repo="$snapshot_root/cloudward-gitops.git"
readonly git_server_image="cloudward-git-server:bootstrap-$$"

cleanup() {
  if docker image inspect "$git_server_image" >/dev/null 2>&1; then
    docker image rm "$git_server_image" >/dev/null
  fi
  if [[ -d "$snapshot_root" && "$snapshot_root" == "${TMPDIR:-/tmp}"/cloudward-gitops.* ]]; then
    find "$snapshot_root" -depth -delete
  fi
}
trap cleanup EXIT

log "Creating an isolated GitOps snapshot (the user's working tree is not committed)"
mkdir -p "$work_tree/helm"
cp -R "$project_root/cloudward-gitops/." "$work_tree/cloudward-gitops"
cp -R "$project_root/helm/cloudward-demo" "$work_tree/helm/cloudward-demo"

# Reproduce Argo's exact checkout root and prove the local chart dependency is
# resolvable before publishing the snapshot.
helm dependency build "$work_tree/cloudward-gitops/environments/local"

git -C "$work_tree" init --initial-branch=main >/dev/null
git -C "$work_tree" config user.name "CloudWard Bootstrap"
git -C "$work_tree" config user.email "bootstrap@cloudward.invalid"
git -C "$work_tree" add cloudward-gitops helm
git -C "$work_tree" commit -m "Ephemeral CloudWard GitOps snapshot" >/dev/null
git clone --bare "$work_tree" "$bare_repo" >/dev/null
touch "$bare_repo/git-daemon-export-ok"

log "Building and importing the ephemeral Git server image"
docker build \
  --file "$project_root/scripts/git-server.Dockerfile" \
  --tag "$git_server_image" \
  "$snapshot_root"
k3d image import "$git_server_image" --cluster "$CLOUDWARD_CLUSTER_NAME"

kubectl create namespace git-server --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f - <<YAML
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cloudward-git
  namespace: git-server
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: cloudward-git
  template:
    metadata:
      labels:
        app.kubernetes.io/name: cloudward-git
    spec:
      automountServiceAccountToken: false
      initContainers:
        - name: seed-repository
          image: $git_server_image
          imagePullPolicy: Never
          command: ["/bin/sh", "-ec"]
          args:
            - >-
              cp -a /opt/cloudward-git-seed/cloudward-gitops.git /work/cloudward-gitops.git
              && git -C /work/cloudward-gitops.git config receive.denyNonFastForwards true
              && git -C /work/cloudward-gitops.git config receive.denyDeletes true
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            runAsNonRoot: true
            runAsUser: 10001
            runAsGroup: 10001
          volumeMounts:
            - name: git-data
              mountPath: /work
      containers:
        - name: git-reader
          image: $git_server_image
          imagePullPolicy: Never
          ports:
            - name: git-read
              containerPort: 9418
          readinessProbe:
            tcpSocket:
              port: git-read
            periodSeconds: 2
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            runAsNonRoot: true
            runAsUser: 10001
            runAsGroup: 10001
            readOnlyRootFilesystem: true
            seccompProfile:
              type: RuntimeDefault
          volumeMounts:
            - name: git-data
              mountPath: /srv/git
        - name: git-writer
          image: $git_server_image
          imagePullPolicy: Never
          command:
            - git
            - daemon
            - --reuseaddr
            - --verbose
            - --export-all
            - --enable=receive-pack
            - --port=9419
            - --base-path=/srv/git
            - /srv/git
          ports:
            - name: git-write
              containerPort: 9419
          readinessProbe:
            tcpSocket:
              port: git-write
            periodSeconds: 2
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            runAsNonRoot: true
            runAsUser: 10001
            runAsGroup: 10001
            readOnlyRootFilesystem: true
            seccompProfile:
              type: RuntimeDefault
          volumeMounts:
            - name: git-data
              mountPath: /srv/git
      volumes:
        - name: git-data
          emptyDir:
            sizeLimit: 128Mi
---
apiVersion: v1
kind: Service
metadata:
  name: cloudward-git
  namespace: git-server
spec:
  selector:
    app.kubernetes.io/name: cloudward-git
  ports:
    - name: git
      port: 9418
      targetPort: git-read
---
apiVersion: v1
kind: Service
metadata:
  name: cloudward-git-writer
  namespace: git-server
spec:
  type: NodePort
  selector:
    app.kubernetes.io/name: cloudward-git
  ports:
    - name: git-write
      port: 9419
      targetPort: git-write
      nodePort: 30918
YAML

kubectl -n git-server rollout status deployment/cloudward-git --timeout=180s
kubectl -n git-server run git-smoke-test \
  --image="$git_server_image" \
  --image-pull-policy=Never \
  --restart=Never \
  --rm --attach \
  --command -- git ls-remote \
  git://cloudward-git.git-server.svc.cluster.local/cloudward-gitops.git refs/heads/main

log "Ephemeral Git source is reachable at git://cloudward-git.git-server.svc.cluster.local/cloudward-gitops.git"
log "Typed local writer endpoint is reachable only on 127.0.0.1:19418"
log "The temporary source snapshot and host-side image will now be removed; k3d retains only its imported image"
