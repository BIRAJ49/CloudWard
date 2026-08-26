# ADR-017: CloudWard and OPA authorize containment

Status: Accepted

Runtime events are untrusted evidence, not commands. A detection can propose quarantine, but a
fresh live-target check and OPA decision are required immediately before execution. Production
quarantine is denied in Part 2, high-risk follow-up is not automated, and OPA failure is closed.

