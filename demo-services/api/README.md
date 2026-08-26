# CloudWard demo API

This FastAPI workload is the controlled Kubernetes remediation target. It runs
one Uvicorn process on port 8080 and exposes:

- `GET /`
- `GET /health/live`
- `GET /health/ready`
- `GET /demo/state`
- `POST /demo/state/unhealthy`
- `POST /demo/state/healthy`
- `GET /metrics`
- `GET /demo/work`
- `GET /demo/slow`
- fixed, control-gated reliability and security scenario routes

The unhealthy endpoint writes a container-local sentinel file. The readiness
probe then returns HTTP 503 while liveness stays HTTP 200. Deleting the pod
removes that ephemeral state, and Kubernetes—not CloudWard—reconciles a clean
replacement. There is no random failure loop.

Set `DEMO_CONTROL_ENABLED=false` outside controlled demo environments to hide
all state-control routes. Keep a single Uvicorn worker so every request observes
the same container-local state.

Part 2 exposes low-cardinality Prometheus metrics, OTLP traces, and correlated
JSON logs. Health and metrics routes are excluded from traces. Latency buckets
extend through 30 seconds so the fixed 8-second slow scenario remains measurable.
