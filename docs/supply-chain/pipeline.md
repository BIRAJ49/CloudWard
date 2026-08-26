# CloudWard software supply-chain pipeline

## Release authority

The release authority is `.github/workflows/release.yml` on `main`. A successful
CI run starts the release workflow; a manual release first invokes the same CI
workflow. Pull requests never receive publishing, OIDC, GitHub App, or cluster
credentials.

The released workload is `ghcr.io/biraj49/cloudward-demo-api`. The repository
owner and the identity in the Kyverno policy must be changed together when the
project moves to another GitHub organization.

```text
source -> CI -> local image build -> Trivy image gate -> CycloneDX SBOM
       -> GHCR push -> immutable digest -> keyless Cosign signature
       -> CycloneDX attestation -> constrained Cosign verification
       -> staging GitOps digest update
```

No `latest` tag is created or consumed. The `sha-<commit>` tag is only a discovery
label; promotion authority is always `repository@sha256:<digest>`.

## Pinned tools

The workflows pin released action/tool versions and Dependabot proposes updates:

- Trivy action `0.33.1`
- Cosign installer `3.10.0`, installing Cosign `2.5.3`
- Syft-backed Anchore SBOM action `0.20.6`
- yq `4.47.2`, downloaded with its release checksum
- Kyverno CLI and cluster policy version `1.18.2`
- Helm `3.19.0` and kubectl `1.35.0`

Action updates require normal pull-request review. Long-lived signing keys are
not used.

## Trivy policy

`trivy.yaml` and `.trivyignore.yaml` are the policy authority.

- Source scanning covers vulnerabilities, IaC/misconfiguration, and secrets.
- Image scanning covers operating-system and application-library findings.
- `HIGH` and `CRITICAL` findings fail both source and release gates.
- Unfixed findings are not ignored automatically.
- A failed image is never pushed or signed.
- There are currently no exceptions.

An exception must identify one finding, constrain the affected package/path,
name an owner, state the justification and expiry date, and be reviewed as a
security-sensitive PR. Blanket ignores and blanket `ignore-unfixed` are forbidden.

## SBOM

CycloneDX JSON is the primary SBOM format. The release workflow generates it
from the exact locally scanned image, uploads it as a 30-day workflow artifact,
and publishes it as a Cosign attestation on the immutable digest. GitOps metadata
stores `<repository>@<digest>#attestation=cyclonedx`, binding the deployment to
the retrievable SBOM.

## Keyless signing and admission

GitHub Actions requests a short-lived OIDC identity. Cosign records the signature
in Sigstore/Rekor. `k8s/kyverno/verify-cloudward-images.yaml` fails closed and
accepts only:

- images matching `ghcr.io/biraj49/cloudward-*`;
- a digest-pinned image reference;
- issuer `https://token.actions.githubusercontent.com`; and
- subject `https://github.com/biraj49/CloudWard/.github/workflows/release.yml@refs/heads/main`.

The rule is limited to CloudWard images in `cloudward-staging` and
`cloudward-production`. It does not intercept unrelated Kubernetes system or
third-party images. Local Part 1/2 images do not match the protected GHCR prefix.

## Real admission test

`scripts/supply-chain/test-signature-admission.sh` performs server-side dry-run
admission requests against the real Kyverno webhook. It requires three real,
digest-pinned fixtures:

```bash
UNSIGNED_IMAGE=ghcr.io/biraj49/cloudward-test@sha256:... \
WRONG_IDENTITY_IMAGE=ghcr.io/biraj49/cloudward-test@sha256:... \
WRONG_IDENTITY_SUBJECT=https://github.com/example/other/.github/workflows/release.yml@refs/heads/main \
APPROVED_SIGNED_IMAGE=ghcr.io/biraj49/cloudward-demo-api@sha256:... \
scripts/supply-chain/test-signature-admission.sh
```

The script first proves the unsigned fixture has no verifiable keyless signature,
the wrong-identity fixture has a valid signature from its declared other subject,
and the approved fixture matches the release identity. The first two admission
requests must then be rejected specifically by
`cloudward-verify-signed-images`; the approved identity must be admitted. A YAML
render alone is not acceptance evidence.

## Bootstrap behavior

Staging and production values intentionally start with an empty digest and
`requireDigest: true`. Helm refuses to render them until the first scanned,
signed release writes a real digest. This prevents a mutable bootstrap image from
becoming an accidental deployment authority.
