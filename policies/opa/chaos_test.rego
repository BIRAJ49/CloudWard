package cloudward.chaos_test

import data.cloudward.chaos
import rego.v1

base := {
  "scenario_id": "reliability.cpu-saturation",
  "actor_role": "Operator",
  "namespace": "cloudward-staging",
  "selector": {"cloudward.io/demo-target": "true"},
  "duration_seconds": 90,
}

test_valid_staging_target if chaos.decision.allowed with input as base

test_viewer_denied if not chaos.decision.allowed with input as object.union(base, {"actor_role": "Viewer"})

test_production_denied if not chaos.decision.allowed with input as object.union(base, {"namespace": "cloudward-production"})

test_unlabeled_denied if not chaos.decision.allowed with input as object.union(base, {"selector": {}})

test_long_duration_denied if not chaos.decision.allowed with input as object.union(base, {"duration_seconds": 301})
