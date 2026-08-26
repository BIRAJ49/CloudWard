# GitHub workflow security

CloudWard uses GitHub-hosted `ubuntu-24.04` runners; Actions Runner Controller is
not part of v1.

## Permissions and trust boundaries

- CI has only `contents: read` and receives no repository secrets on pull requests.
- Release grants `packages: write` and `id-token: write` only to the release job.
- GitOps writes use a short-lived GitHub App installation token scoped to the
  `cloudward-gitops` repository. A PAT is not supported.
- Staging cluster credentials exist only in the protected `staging` environment.
- Production promotion uses the protected `production-promotion` environment and
  can open a PR, not merge it or call Kubernetes.
- No workflow uses `write-all`, executes pull-request code with secrets, or uses
  `pull_request_target`.

Pin repository Actions to reviewed release versions and keep
`.github/dependabot.yml` enabled. A version update is a code-review event, not an
automatic trust decision.

## Required GitHub configuration

Create the environments `release`, `staging`, and `production-promotion`. Require
reviewers for staging credentials and production promotion. Configure these
secrets:

| Location | Name | Purpose |
| --- | --- | --- |
| release/staging/production-promotion | `CLOUDWARD_GITHUB_APP_ID` | App identity |
| same | `CLOUDWARD_GITHUB_APP_PRIVATE_KEY` | App key, masked and environment-scoped |
| staging | `STAGING_KUBECONFIG_B64` | Least-privilege staging validation only |

Configure staging variables `UNSIGNED_CLOUDWARD_TEST_IMAGE`,
`WRONG_IDENTITY_CLOUDWARD_TEST_IMAGE`, and `WRONG_IDENTITY_COSIGN_SUBJECT` with
maintained, immutable admission-test fixtures. The App installation needs
`Contents: read/write` and `Pull requests:
read/write` only on the GitOps repository. The application repository needs read
access. GHCR publication remains with the workflow's short-lived `GITHUB_TOKEN`.

Protect GitOps `main`: require pull-request review and CODEOWNERS for production
values, deny force pushes/deletions, and permit the App to write the automated
staging path. Protect the application `main` with required `CI` checks.

## Token and log handling

Checkout credential persistence is disabled unless a GitOps checkout must push.
Secrets are passed through action inputs or environment variables and never
printed. Build arguments do not carry tokens. Kubeconfig files use mode `0600`
and disappear with the hosted runner. GitHub masks App tokens automatically.
