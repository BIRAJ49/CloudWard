# Part 3 supply-chain threat model

This is the Part 3 foundation, not the final Part 4 threat model.

## Assets and trust boundaries

Protected assets are source, workflow definitions, GitHub App credentials, OIDC
identity, GHCR images, SBOM attestations, GitOps desired state, production review,
cluster admission, and rollback authority. Trust boundaries exist between an
untrusted pull request and CI, CI and GHCR/Sigstore, the application and GitOps
repositories, Git and Argo CD, and Argo CD and Kubernetes admission.

## Threats and controls

| Threat | Control | Residual risk / response |
| --- | --- | --- |
| Malicious Git commit | protected branches, required CI, CODEOWNERS for workflows/policy/production | reviewer compromise; audit and revoke access |
| GitHub App compromise | repository-scoped installation, minimal contents/PR permissions, short-lived token | rotate App key, suspend installation, review Git audit log |
| GitHub write abuse | App writes staging or proposal branch only; production requires PR | compromised App may alter staging; Argo/Kyverno still require a trusted signed digest |
| CI secret leakage | no secrets on PR/forks, no `pull_request_target`, environment-scoped secrets, no token build args | compromised trusted workflow; rotate secrets and invalidate sessions |
| Action dependency compromise | pinned release versions and reviewed Dependabot updates | mutable upstream tags; move critical actions to audited commit SHAs as releases are reviewed |
| Vulnerable dependency/image | Trivy source and image gates fail HIGH/CRITICAL; no blanket unfixed ignore | scanner/database lag; monitor advisories and rescan releases |
| Secret committed in source | Trivy secret scan and Git review | encoded/novel secrets; use provider scanning and rotate on suspicion |
| SBOM substitution | CycloneDX attested to immutable image digest | signer/workflow compromise; verify OIDC identity and transparency log |
| Image substitution | GitOps uses digest, Kyverno verifies digest and signature | registry/Sigstore outage fails admission; use controlled break-glass process, never disable silently |
| Unsigned image | Kyverno fail-closed verification | policy deletion by cluster admin; audit policy changes and constrain RBAC |
| Incorrect signing identity | exact workflow subject and GitHub OIDC issuer | repository ownership transfer requires coordinated policy review |
| Supply-chain compromise | independent scan, SBOM, keyless signature, Git review, admission verification | coordinated control-plane compromise; isolate and rebuild from known source |
| Mutable-tag rollback | workflow and Helm require sha256; rollback digest stored in Git | loss of known-good registry object; retain release artifacts and prevent package deletion |
| Stale validation/race | pending release cannot be overwritten; exact digest input and workflow concurrency | manual Git bypass; branch protection and audit |
| Automatic production promotion | promotion workflow only opens a PR; Argo follows approved Git | reviewer error; PR carries scans, SBOM, risks, and rollback digest |
| Persistent cluster drift | Argo self-heal, drift metrics/API, persistent changes through Git | temporary reconciliation delay; alert after bounded window |

## Security invariants

1. A failed scan is not published or signed.
2. A tag is never deployment authority.
3. A valid signature from an unexpected identity is still rejected.
4. Staging readiness alone is insufficient for production.
5. Production changes require a reviewed Git diff and known rollback digest.
6. Operational temporary actions do not silently become persistent desired state.
