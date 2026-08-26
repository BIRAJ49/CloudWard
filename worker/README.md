# CloudWard worker

Celery imports the application as `worker.celery_app:celery_app`. The worker
declares queues for incident ingestion, evidence, remediation, verification,
and notifications. The broker-safe task name for the Part 1 round-trip probe is
`cloudward.tasks.healthcheck`; it routes to `verification`.

The API can publish the task without importing worker code:

```python
celery.send_task(
    "cloudward.tasks.healthcheck",
    kwargs={"request_id": "request-correlation-id"},
    queue="verification",
)
```

For compatibility with the Part 1 API publisher, a non-default `value` is also
copied into the result's `request_id` when an explicit `request_id` is absent.

Run unit tests from the worker directory. The Redis round-trip test is opt-in,
so the ordinary suite stays hermetic:

```bash
cd worker
uv run --frozen pytest -m 'not integration'
CELERY_INTEGRATION=1 uv run --frozen pytest tests/test_redis_round_trip.py
```
