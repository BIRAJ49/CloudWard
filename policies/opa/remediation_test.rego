package cloudward.remediation_test

import data.cloudward.remediation.decision
import rego.v1

base_input := {
	"environment": "staging",
	"action": "DELETE_UNHEALTHY_POD",
	"risk_score": 18,
	"risk_factors": {
		"environment": 4,
		"blast_radius": 3,
		"destructiveness": 3,
		"reversibility": 2,
		"uncertainty": 4,
		"sensitivity": 2,
	},
	"confidence": 0.98,
	"blast_radius": 1,
	"reversible": true,
	"service_criticality": "low",
	"target": {
		"namespace": "cloudward-staging",
		"pod_name": "cloudward-demo-abcde",
		"controller_managed": true,
		"target_pods": 1,
		"labels": {"cloudward.io/demo-target": "true"},
	},
}

test_low_risk_staging_action_is_allowed if {
	result := decision with input as base_input
	result.allowed
	not result.requires_approval
	result.decision == "ALLOW"
}

test_medium_risk_action_requires_approval if {
	request := object.union(base_input, {
		"risk_score": 45,
		"risk_factors": {
			"environment": 8,
			"blast_radius": 10,
			"destructiveness": 8,
			"reversibility": 5,
			"uncertainty": 9,
			"sensitivity": 5,
		},
	})
	result := decision with input as request
	not result.allowed
	result.requires_approval
	result.decision == "APPROVAL_REQUIRED"
}

test_medium_risk_action_with_valid_approval_is_allowed if {
	request := object.union(base_input, {
		"risk_score": 45,
		"risk_factors": {
			"environment": 8,
			"blast_radius": 10,
			"destructiveness": 8,
			"reversibility": 5,
			"uncertainty": 9,
			"sensitivity": 5,
		},
		"approval": {
			"approved": true,
			"approval_id": "approval-123",
			"approved_by": "operator@example.invalid",
		},
	})
	result := decision with input as request
	result.allowed
	not result.requires_approval
}

test_high_risk_action_is_blocked if {
	request := object.union(base_input, {
		"risk_score": 80,
		"risk_factors": {
			"environment": 12,
			"blast_radius": 20,
			"destructiveness": 15,
			"reversibility": 10,
			"uncertainty": 13,
			"sensitivity": 10,
		},
	})
	result := decision with input as request
	not result.allowed
	not result.requires_approval
	result.decision == "DENY"
}

# Critical invariant: a hard deny wins even when the supplied score is 1 and
# the factors are intentionally inconsistent with that score.
test_hard_deny_cannot_be_bypassed_with_risk_score_one if {
	request := object.union(base_input, {
		"action": "TERRAFORM_DESTROY",
		"risk_score": 1,
	})
	result := decision with input as request
	not result.allowed
	not result.requires_approval
	result.decision == "HARD_DENY"
}

test_unknown_action_is_blocked if {
	request := object.union(base_input, {"action": "DO_WHATEVER_THE_MODEL_SAYS"})
	result := decision with input as request
	not result.allowed
	result.decision == "DENY"
}

test_production_pod_deletion_is_blocked if {
	request := object.union(base_input, {"environment": "production"})
	result := decision with input as request
	not result.allowed
	not result.requires_approval
	result.decision == "DENY"
}

test_irreversible_action_is_blocked if {
	request := object.union(base_input, {"reversible": false})
	result := decision with input as request
	not result.allowed
	not result.requires_approval
	result.decision == "DENY"
}

test_risk_score_manipulation_is_blocked if {
	request := object.union(base_input, {"risk_score": 1})
	result := decision with input as request
	not result.allowed
	not result.requires_approval
	result.decision == "DENY"
}

test_target_without_demo_label_is_blocked if {
	request_without_target := object.remove(base_input, {"target"})
	request := object.union(request_without_target, {"target": {
		"namespace": "cloudward-staging",
		"pod_name": "cloudward-demo-abcde",
		"controller_managed": true,
		"target_pods": 1,
		"labels": {},
	}})
	result := decision with input as request
	not result.allowed
	not result.requires_approval
	result.decision == "DENY"
}

test_low_confidence_requires_approval if {
	request := object.union(base_input, {"confidence": 0.7})
	result := decision with input as request
	not result.allowed
	result.requires_approval
}

test_registered_action_without_executor_policy_is_blocked if {
	request := object.union(base_input, {"action": "CREATE_GITOPS_PR"})
	result := decision with input as request
	not result.allowed
	not result.requires_approval
}

test_low_risk_targeted_staging_quarantine_is_allowed if {
	request := object.union(base_input, {
		"action": "APPLY_QUARANTINE",
		"risk_score": 25,
		"risk_factors": {
			"environment": 4,
			"blast_radius": 3,
			"destructiveness": 9,
			"reversibility": 2,
			"uncertainty": 1,
			"sensitivity": 6,
		},
	})
	result := decision with input as request
	result.allowed
	not result.requires_approval
}

test_production_quarantine_is_blocked_even_with_approval if {
	request := object.union(base_input, {
		"action": "APPLY_QUARANTINE",
		"environment": "production",
		"approval": {
			"approved": true,
			"approval_id": "approval-prod",
			"approved_by": "admin@example.invalid",
		},
	})
	result := decision with input as request
	not result.allowed
	not result.requires_approval
	result.decision == "DENY"
}
