# Runbook: unhealthy demo pod

The `reliability.unhealthy-pod` YAML runbook applies only to the controlled staging demo target. It requires Kubernetes state and readiness evidence, one controller-managed target pod, an allowlisted `DELETE_UNHEALTHY_POD` action, and post-action readiness and application-health verification.

## Expected lifecycle

1. A controlled event identifies the namespace, Deployment, and unhealthy pod.
2. CloudWard records the incident as `DETECTED`.
3. The Kubernetes client obtains the Deployment and pod state and stores structured evidence.
4. Deterministic classification matches this runbook.
5. Risk scoring records its six-factor calculation.
6. OPA evaluates the structured action input and hard-deny rules.
7. On allow, CloudWard calls the typed pod-deletion method.
8. Kubernetes reconciles the Deployment replica count.
9. CloudWard checks ready replicas, pod readiness, and application health.
10. Success becomes `RESOLVED`; bounded repeated failure becomes `ESCALATED`.

The runbook never creates a replacement pod and contains no shell command. Rollback is disabled because deletion cannot restore the same pod; recovery is the Deployment controller's ordinary reconciliation behavior.

