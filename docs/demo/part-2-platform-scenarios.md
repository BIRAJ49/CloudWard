# Part 2 platform scenario contracts

These are platform contracts, not recorded execution results.

| Scenario | Trigger contract | Detection contract | Cleanup contract |
| --- | --- | --- | --- |
| R1 bad deployment | deterministic bad release through GitOps | real HTTP 5xx metric and `HighHTTPErrorRate` | restore Git desired state and wait for Argo CD |
| R2 CPU saturation | allowlisted `StressChaos` | CPU/request telemetry and `HighCPUSaturation` | delete the exact StressChaos resource |
| R3 memory pressure | allowlisted memory `StressChaos` | working set, termination reason, restart and Kubernetes event | delete exact resource and verify pod readiness |
| R4 workload failure | allowlisted `PodChaos` | unavailable replica and Kubernetes reconciliation | delete exact resource and attribute recovery to Kubernetes |

Alertmanager sends alerts as evidence to CloudWard. Runbook matching, risk calculation, OPA, action execution, and multi-signal verification remain separate deterministic stages. No alert label or Chaos annotation authorizes an action.

The local platform has not demonstrated these scenario contracts merely because their manifests exist. Runtime evidence belongs in `docs/testing/` and must include the alert, incident ID, runbook, risk, OPA decision, action or no-action attribution, verification, cleanup, and final state.
