# ADR-020: AI is advisory, never remediation authority

Status: Accepted

Model output may diagnose, summarize, correlate, and suggest only registered actions. It cannot
invoke an executor or bypass deterministic controls. Selecting a suggested action runs it through
the registry, deterministic risk engine, and OPA and persists only a proposal. Existing approval,
execution, verification, and rollback components remain the sole remediation path. AI failure
therefore cannot stop or weaken deterministic incident handling.
