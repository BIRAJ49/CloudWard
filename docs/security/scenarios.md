# Controlled runtime-security scenarios

## S1 — suspicious shell pattern

`scripts/scenarios/security/s1-suspicious-shell.sh` calls a fixed demo endpoint. The application
starts `/bin/sh` with a fixed `printf` command, then contacts only the internal simulator. There
is no caller-supplied command, public address, persistence, download, destructive operation, or
usable remote shell. `cloudward-s1-unexpected-shell` detects the exec syscall.

## S2 — unexpected egress

`scripts/scenarios/security/s2-unexpected-egress.sh` first proves the harmless
`cloudward-c2-simulator` service is reachable, then makes the same fixed internal request.
`cloudward-s2-unexpected-egress` detects the connect syscall to port 8080. Quarantine acceptance
requires the retry to fail, and cleanup requires it to succeed again. No public C2 endpoint is
used.

## S3 — privilege-related behavior

`scripts/scenarios/security/s3-privilege-behavior.sh` attempts to read one byte from
`/proc/1/mem` and treats the expected permission denial as success.
`cloudward-s3-privilege-attempt` observes the `openat` syscall. The scenario does not exploit a
vulnerability, request extra capabilities, escape the container, or modify the host. Its
`PRIVILEGE_BEHAVIOR` category receives higher central risk sensitivity than S1/S2.

All scripts have a 120-second default deadline, require the exact `k3d-cloudward` context, select
only a running demo-labeled staging pod, verify containment through the API, and remove it before
returning success.

