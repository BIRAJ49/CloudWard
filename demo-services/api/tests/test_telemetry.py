from prometheus_client import generate_latest

from app.telemetry import HTTP_DURATION


def test_latency_histogram_has_slow_scenario_buckets() -> None:
    HTTP_DURATION.labels("test-service", "GET", "/demo/slow", "200").observe(12.5)
    output = generate_latest().decode()
    assert 'cloudward_demo_http_request_duration_seconds_bucket{le="20.0"' in output
    assert 'cloudward_demo_http_request_duration_seconds_bucket{le="30.0"' in output
