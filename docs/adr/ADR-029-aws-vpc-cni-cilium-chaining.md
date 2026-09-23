# ADR-029: Retain AWS VPC CNI and chain Cilium on EKS

Status: Accepted

## Context

Local k3d uses Cilium as the primary CNI. EKS networking, VPC-native addresses, and AWS support expectations differ. Replacing AWS VPC CNI solely for local parity would add migration and operational risk.

## Decision

EKS retains AWS VPC CNI. Cilium is installed in AWS-CNI chaining mode for CloudWard network policy and quarantine. AWS values and acceptance tests remain separate from local full-CNI values. Completion requires agent, DNS, pod/service networking, policy, and quarantine tests—not only Helm success.

## Consequences

This preserves AWS-native pod networking while retaining required policy controls, but creates two explicit operating modes and limits assumptions about Cilium features. A standalone Cilium Gateway is not used for EKS ingress.
