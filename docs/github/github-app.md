# GitHub App integration

CloudWard uses a GitHub App, never a personal access token. It signs a short-lived RS256 App JWT
only to mint an installation token. Installation tokens are held in process memory, refreshed
before expiry, and never persisted or returned by an API.

## Installation permissions

Grant only the capabilities enabled for the installation:

- Metadata: read (required by GitHub Apps).
- Contents: read for explicitly configured source repositories.
- Issues: write only for repositories allowed to receive CloudWard incident issues.
- Contents and pull requests: write only for repositories where CloudWard may create an
  allowlisted file change and a draft pull request.

Do not grant administration, actions, members, secrets, or merge permissions. Protect target
branches so App-created pull requests still require the repository's normal review and checks.

## Configuration

`GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, and `GITHUB_APP_PRIVATE_KEY` configure
authentication. A private key stored in an environment variable may use literal `\\n` separators;
CloudWard normalizes them in memory.

Authorization is separate from authentication:

- `GITHUB_APP_READ_REPOSITORIES` is a comma-separated `owner/repository` allowlist.
- `GITHUB_APP_ISSUE_REPOSITORIES` is the independent issue-write allowlist.
- `GITHUB_APP_WRITE_ALLOWLIST` is a JSON object mapping a repository to relative glob patterns,
  for example `{"acme/cloudward-gitops":["environments/staging/*.yaml"]}`.

Repository names and paths are normalized before every operation. Absolute paths, traversal,
unlisted repositories, and unlisted file paths fail closed.

## Bounded operations

Source correlation compares the explicitly supplied running commit with the explicitly supplied
previous-healthy commit. It returns at most twenty diff entries with bounded patches and states
that correlation is not causation. Source files are capped at 20 KB. Commit messages, patches, and
source are redacted and treated as untrusted evidence before they can reach AI context.

Reliability alert processing also invokes this correlation best-effort when labels or annotations
provide `cloudward.io/source-repository`, `cloudward.io/running-commit`, and
`cloudward.io/previous-healthy-commit` (bounded aliases are supported). Optional branch and image
digest metadata is retained as deployment context. Missing configuration, invalid metadata, or a
GitHub failure records evidence as unavailable after deterministic remediation has committed; it
never fails or rolls back remediation.

Incident issues are deduplicated by incident and repository. The stored automation record links
the incident to the external issue number and URL. The generic change-proposal service creates one
new branch, updates one allowlisted path with an expected blob SHA, and opens a draft pull request.
It includes current/proposed state, evidence, risk, verification, and rollback information. It
cannot merge a pull request or directly change a protected environment.

`GET /api/v1/integrations/github` exposes readiness booleans, allowlist counts, and the security
posture only. It never returns App IDs, installation IDs, keys, or tokens.

Source and issue APIs are under `/api/v1/integrations/github`. Every write records an audit event;
failure messages exclude credentials and response bodies.
