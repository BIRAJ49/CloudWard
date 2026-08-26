# Staging-to-production GitOps promotion

## Repositories and Argo CD

The application repository owns source and release workflows. The tightly scoped
GitHub App writes deployment state to `biraj49/cloudward-gitops`. That repository
contains these two directories from this project:

```text
cloudward-gitops/
helm/cloudward-demo/
```

Keeping both paths preserves the local Helm dependency used by the environment
charts. Configure a different owner by changing the Argo `repoURL`, GitHub App
installation, GHCR references, Cosign identity, and Kyverno policy in one reviewed
change.

`cloudward-staging` watches `cloudward-gitops/environments/staging` on `main` and
reconciles automatically. `cloudward-production` watches the production path and
also self-heals, but production state can reach `main` only through a reviewed
promotion PR. Neither workflow patches a Deployment directly.

## Release to staging

After scan, SBOM, push, and keyless signing, `release.yml` uses a repository-scoped
GitHub App token to atomically update staging values. The update records:

- immutable image digest;
- full source commit;
- digest-bound CycloneDX reference;
- passed image-scan status;
- pending staging validation; and
- the previous validated staging digest for rollback.

A pending staging release cannot be overwritten by another release. This keeps
the rollback digest meaningful and prevents validation races.

## Staging validation

`staging-validation.yml` runs on a GitHub-hosted runner using the protected
`staging` environment. Its narrowly scoped kubeconfig must reach the intended
staging cluster. It checks:

1. Argo reports `Synced` and `Healthy`.
2. The Deployment becomes ready.
3. The deployed image exactly equals the Git digest.
4. Readiness and controlled demo smoke endpoints answer successfully.
5. Kyverno rejects unsigned and wrong-identity fixtures.
6. Kyverno admits the approved signed release.

Only then does the workflow record `stagingValidation: passed` in Git. For a
local k3d cluster, run the same scripts from a trusted host because a hosted
runner cannot reach a loopback-only API server.

## Production PR

`gitops-promotion.yml` is manual and requires the exact staging digest and risk
notes. `prepare-production-promotion.sh` refuses the promotion unless staging is
validated, the security scan passed, the SBOM matches the digest, and a rollback
digest is known. The workflow can push only a proposal branch and open a PR.

The PR body contains the image digest, source commit, staging validation,
security scan, SBOM reference, operator risk notes, and rollback digest. Configure
CODEOWNERS/branch protection to require human review. Production cannot change
before that PR merges. No mutable tag participates in this flow.

Only one production promotion PR may be open. A second request is rejected, and
an existing closed promotion branch is never overwritten. Require the PR branch
to be up to date before merge so stale validation cannot silently win a race.

The first production promotion requires a previously validated staging digest as
rollback authority. In practice: validate release A in staging, release and
validate B, then promote B with A as rollback. The system intentionally blocks a
first deployment that has no known recovery image.

## Rollback

Rollback is another reviewed Git change restoring
`cloudward-demo.image.digest` to `release.rollbackDigest`. Argo reconciles it.
Do not use `kubectl set image`, an Argo UI override, or a mutable tag.

## Drift classification

Temporary bounded operations such as deleting an unhealthy ReplicaSet-managed
pod are operational actions; the controller restores them and they are audited as
temporary. Images, replicas, resources, and policy configuration are persistent
desired state and must change through Git.

The read-only endpoint `GET /api/v1/gitops/drift/{staging|production}` reports
Argo sync/health/revision, out-of-sync resources, deployed image references, and
whether every image is digest pinned. Prometheus rules alert only after sustained
Argo drift. No drift observer is allowed to mutate the cluster.

## Local installation boundary

`scripts/install-part3-supply-chain.sh` installs the signature policy, observer
RBAC, ServiceMonitor, and drift alerts on the guarded `k3d-cloudward` context. It
does not install remote Applications. Apply `cloudward-project.yaml`, then the
staging/production Application manifests only after the GitOps repository and a
signed release exist.
