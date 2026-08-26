# ADR-022: GitHub App authentication instead of PATs

Status: Accepted

CloudWard authenticates GitHub operations with a short-lived App JWT that mints an installation
token. Installation tokens remain memory-only and are refreshed before expiry. Personal access
tokens are unsupported because they couple automation to a person, are commonly over-scoped, and
do not provide the same installation-level repository boundary.
