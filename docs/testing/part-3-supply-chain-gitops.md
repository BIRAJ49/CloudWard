# Part 3 supply-chain and GitOps verification

Implementation and executable validation are separate. These controls are not
accepted until the commands run against real registries and admission webhooks.

## Offline/CI gates

```bash
trivy fs --config trivy.yaml .
helm lint helm/cloudward-demo --strict
kyverno test k8s/kyverno
scripts/gitops/test-promotion-assets.sh
```

The CI workflow additionally runs backend/worker/demo/frontend lint and tests,
frontend build, environment Helm lint, Kustomize rendering, and the Trivy source
gate.

## Release evidence

Trigger `Release signed demo image` on `main`. Preserve the workflow URL and the
following outputs:

| Control | Required evidence |
| --- | --- |
| Trivy source | successful CI repository gate |
| Trivy image | release gate before GHCR login/push |
| SBOM | CycloneDX artifact and digest attestation |
| GHCR | `repository@sha256:<64 hex>` |
| Cosign | verification against exact workflow identity and GitHub issuer |

## Admission evidence

Maintain three real digest fixtures, then run:

```bash
UNSIGNED_IMAGE=ghcr.io/biraj49/cloudward-test@sha256:... \
WRONG_IDENTITY_IMAGE=ghcr.io/biraj49/cloudward-test@sha256:... \
WRONG_IDENTITY_SUBJECT=https://github.com/example/other/.github/workflows/release.yml@refs/heads/main \
APPROVED_SIGNED_IMAGE=ghcr.io/biraj49/cloudward-demo-api@sha256:... \
scripts/supply-chain/test-signature-admission.sh
```

Required output is two `REJECTED` decisions attributed to the signature policy and
one `ALLOWED` decision.

## GitOps evidence

Run `staging-validation.yml` for the exact released digest. Capture Argo sync and
health status, Deployment rollout, health/smoke results, signature decisions, and
the Git commit recording passed validation. Then run `gitops-promotion.yml` and
capture the unmerged PR. Verify the PR includes every release field and that
production still points to the prior digest.

After review and merge, capture Argo production revision and digest. Demonstrate
a rollback PR restoring the recorded rollback digest. Query
`/api/v1/gitops/drift/production` before and after a controlled Git drift test.

## Current execution status

No Part 3 workflow, scan, image push, signature, admission decision, Argo
reconciliation, or promotion test has been executed as part of implementation.
All results remain **NOT RUN** until evidence is collected.
