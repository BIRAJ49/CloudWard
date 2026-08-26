# Remediation safety boundary

CloudWard uses defense in depth. An action must pass every layer below; success at one layer is never permission to skip another.

1. The runbook is schema-valid, version controlled, and contains no command or shell field.
2. The action is a known member of the central action registry.
3. Registry metadata allows the target environment and defines verification behavior.
4. Preconditions constrain the target and blast radius.
5. Deterministic risk records the operational risk but grants no authority.
6. OPA allows the exact structured request and independently applies hard-deny rules.
7. RBAC and, when required, a human approval authorize the actor.
8. A typed executor invokes a preimplemented Kubernetes client method.
9. Multiple health signals verify the outcome before resolution.
10. The complete decision and outcome are audited.

## Absolute denials

Part 1 does not expose executable implementations for arbitrary commands, arbitrary `kubectl`, `kubectl exec`, arbitrary outbound HTTP actions, infrastructure destruction, IAM or credential mutation, network-topology changes, production data or database deletion, persistent-volume deletion, secret extraction or display, production-secret rotation, disabling policy/audit/runtime controls, or creation of cluster-admin credentials.

OPA also hard-denies these action identifiers even when a caller submits a manipulated low risk score. Unknown actions are denied by both the registry boundary and policy.

## Demo guardrails

The automated scenario targets `cloudward-staging` and requires `cloudward.io/demo-target: "true"`. The local `cloudward-production` namespace exists for policy tests, but the demo workflow must not perform destructive actions there. The unhealthy target must be controller-managed and the runbook limits the target to one pod.

