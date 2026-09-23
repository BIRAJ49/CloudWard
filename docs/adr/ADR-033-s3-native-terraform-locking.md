# ADR-033: S3 remote state with native Terraform lockfiles

Status: Accepted

## Context

Terraform state is sensitive and concurrent writes can corrupt infrastructure. DynamoDB locking adds a resource no longer needed for the selected Terraform backend behavior.

## Decision

A dedicated bootstrap configuration creates a narrowly scoped S3 bucket with versioning, server-side encryption, TLS enforcement, and Block Public Access. Main infrastructure uses partial backend configuration and `use_lockfile = true`. Access is restricted to the CloudWard state bucket/prefix. DynamoDB is not added.

## Consequences

Bootstrap begins with sensitive local state that operators must protect. Bucket versions enable recovery but also retain sensitive history and cost. The backend survives ordinary environment teardown and requires a separate reviewed decision to remove.
