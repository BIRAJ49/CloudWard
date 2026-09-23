package cloudward.remediation

import rego.v1

# This package is the final authorization boundary for automated remediation.
# Risk is an input to policy; a low score never overrides an invariant below.

policy_id := "cloudward.remediation.v1"

known_actions := {
	"DELETE_UNHEALTHY_POD",
	"SCALE_STAGING_DEPLOYMENT",
	"REVERT_IMAGE",
	"APPLY_QUARANTINE",
	"REMOVE_QUARANTINE",
	"CREATE_GITOPS_PR",
	"CREATE_TERRAFORM_PR",
	"CREATE_GITHUB_ISSUE",
	"REQUEST_APPROVAL",
	"NO_ACTION",
}

# These identifiers intentionally include both enum-like and command-like forms.
# The check happens before structural validation, so score or field manipulation
# cannot turn a forbidden operation into an allowed one.
hard_denied_actions := {
	"terraform_destroy",
	"terraform destroy",
	"delete_eks",
	"delete_eks_cluster",
	"change_iam_policy",
	"change_iam_policies",
	"delete_iam_role",
	"delete_iam_roles",
	"create_arbitrary_credentials",
	"change_vpc_topology",
	"delete_subnet",
	"delete_subnets",
	"broaden_security_group",
	"broaden_security_groups",
	"delete_production_database",
	"delete_production_databases",
	"modify_production_data",
	"delete_persistent_volume",
	"delete_persistent_volumes",
	"extract_secrets",
	"display_secrets",
	"rotate_production_secrets",
	"disable_kyverno",
	"disable_tetragon",
	"disable_audit_logging",
	"remove_global_security_policy",
	"remove_global_security_policies",
	"create_cluster_admin_credentials",
	"run_shell",
	"run_arbitrary_shell_command",
	"run_kubectl",
	"run_arbitrary_kubectl",
	"run_kubectl_exec",
	"arbitrary_external_http",
}

factor_keys := {
	"environment",
	"blast_radius",
	"destructiveness",
	"reversibility",
	"uncertainty",
	"sensitivity",
}

default decision := {
	"allowed": false,
	"requires_approval": false,
	"decision": "DENY",
	"reason": "Policy evaluation failed closed",
	"policy_id": "cloudward.remediation.v1",
}

# Hard denies are evaluated first and require only a string action. This is
# deliberate: malformed or deceptively low-risk requests still fail safely.
decision := {
	"allowed": false,
	"requires_approval": false,
	"decision": "HARD_DENY",
	"reason": "Action violates a non-overridable CloudWard safety boundary",
	"policy_id": policy_id,
} if {
	hard_denied_action
} else := {
	"allowed": false,
	"requires_approval": false,
	"decision": "DENY",
	"reason": "Policy input is invalid or risk score does not match risk factors",
	"policy_id": policy_id,
} if {
	not valid_common_input
} else := {
	"allowed": false,
	"requires_approval": false,
	"decision": "DENY",
	"reason": "Unknown action is not in the CloudWard action registry",
	"policy_id": policy_id,
} if {
	not known_actions[input.action]
} else := {
	"allowed": false,
	"requires_approval": false,
	"decision": "DENY",
	"reason": "Production pod deletion is outside the Part 1 automation boundary",
	"policy_id": policy_id,
} if {
	input.action == "DELETE_UNHEALTHY_POD"
	input.environment == "production"
} else := {
	"allowed": false,
	"requires_approval": false,
	"decision": "DENY",
	"reason": "Part 2 automated quarantine is restricted to local staging workloads",
	"policy_id": policy_id,
} if {
	input.action in {"APPLY_QUARANTINE", "REMOVE_QUARANTINE"}
	input.environment == "production"
} else := {
	"allowed": false,
	"requires_approval": false,
	"decision": "DENY",
	"reason": "Irreversible actions are blocked from automated execution",
	"policy_id": policy_id,
} if {
	input.reversible == false
} else := {
	"allowed": false,
	"requires_approval": false,
	"decision": "DENY",
	"reason": "High-risk actions are blocked and must be escalated",
	"policy_id": policy_id,
} if {
	input.risk_score >= 70
} else := {
	"allowed": false,
	"requires_approval": false,
	"decision": "DENY",
	"reason": "Action is registered but has no Part 1 executor policy",
	"policy_id": policy_id,
} if {
	not input.action in {"DELETE_UNHEALTHY_POD", "SCALE_STAGING_DEPLOYMENT", "REVERT_IMAGE", "NO_ACTION", "APPLY_QUARANTINE", "REMOVE_QUARANTINE"}
} else := {
	"allowed": false,
	"requires_approval": false,
	"decision": "DENY",
	"reason": "Pod target is outside the controlled demo safety boundary",
	"policy_id": policy_id,
} if {
	not valid_demo_pod_target
} else := {
	"allowed": true,
	"requires_approval": false,
	"decision": "ALLOW",
	"reason": "Approved medium-risk staging remediation",
	"policy_id": policy_id,
} if {
	approval_required
	valid_approval
} else := {
	"allowed": false,
	"requires_approval": true,
	"decision": "APPROVAL_REQUIRED",
	"reason": "Medium-risk or lower-confidence remediation requires human approval",
	"policy_id": policy_id,
} if {
	approval_required
} else := {
	"allowed": true,
	"requires_approval": false,
	"decision": "ALLOW",
	"reason": "Low-risk reversible staging remediation",
	"policy_id": policy_id,
}

hard_denied_action if {
	is_string(input.action)
	hard_denied_actions[lower(input.action)]
}

valid_common_input if {
	is_string(input.action)
	input.action != ""
	input.environment in {"local", "staging", "production"}
	is_number(input.risk_score)
	input.risk_score >= 0
	input.risk_score <= 100
	input.risk_score % 1 == 0
	is_number(input.confidence)
	input.confidence >= 0
	input.confidence <= 1
	is_number(input.blast_radius)
	input.blast_radius >= 1
	input.blast_radius % 1 == 0
	is_boolean(input.reversible)
	input.service_criticality in {"low", "medium", "high", "critical"}
	valid_risk_factors
}

valid_risk_factors if {
	is_object(input.risk_factors)
	object.keys(input.risk_factors) == factor_keys
	factor_in_range(input.risk_factors.environment, 15)
	factor_in_range(input.risk_factors.blast_radius, 25)
	factor_in_range(input.risk_factors.destructiveness, 20)
	factor_in_range(input.risk_factors.reversibility, 15)
	factor_in_range(input.risk_factors.uncertainty, 15)
	factor_in_range(input.risk_factors.sensitivity, 10)
	input.risk_score == sum([value |
		some key in factor_keys
		value := input.risk_factors[key]
	])
}

factor_in_range(value, maximum) if {
	is_number(value)
	value >= 0
	value <= maximum
	value % 1 == 0
}

valid_demo_pod_target if {
	is_object(input.target)
	is_object(input.target.labels)
	input.target.namespace == "cloudward-staging"
	is_string(input.target.pod_name)
	input.target.pod_name != ""
	input.target.controller_managed == true
	input.target.target_pods >= 1
	input.target.target_pods <= 10
	object.get(input.target.labels, "cloudward.io/demo-target", "") == "true"
}

approval_required if input.risk_score >= 31

approval_required if input.confidence < 0.9

valid_approval if {
	is_object(input.approval)
	input.approval.approved == true
	is_string(input.approval.approval_id)
	input.approval.approval_id != ""
	is_string(input.approval.approved_by)
	input.approval.approved_by != ""
}
