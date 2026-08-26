package cloudward.chaos

import rego.v1

protected_namespaces := {
  "cloudward-production",
  "kube-system",
  "argocd",
  "observability",
  "kyverno",
  "tetragon",
  "chaos-mesh",
}

valid_role if input.actor_role in {"Operator", "Admin"}
valid_scenario if startswith(input.scenario_id, "reliability.")
valid_scenario if startswith(input.scenario_id, "security.")

allowed if {
  valid_role
  valid_scenario
  input.namespace == "cloudward-staging"
  not input.namespace in protected_namespaces
  input.selector == {"cloudward.io/demo-target": "true"}
  input.duration_seconds > 0
  input.duration_seconds <= 300
}

decision := {"allowed": true, "reason": "typed staging demo scenario allowed"} if allowed
else := {"allowed": false, "reason": "chaos target, actor, selector, or duration denied"}
