# Part 2 platform validation record

## Current evidence status

The Part 2 platform assets are implemented, but no cluster installation or runtime scenario validation is recorded by this document. The implementation request explicitly deferred checks. Therefore every runtime acceptance item below remains **NOT RUN** rather than passing.

## Static validation to run

```bash
./scripts/test-platform-assets.sh
```

This should render the pinned charts, Kustomize resources, and dashboard JSON without applying them.

## Runtime validation to run

```bash
./scripts/install-part2-platform.sh
./scripts/validate-part2-platform.sh
```

The second command requires an instrumented, exercised demo workload and a running CloudWard control plane.

| Criterion | Current result | Required evidence |
| --- | --- | --- |
| Prometheus, Alertmanager, Grafana healthy | NOT RUN | deployed Helm status and ready controllers |
| demo metrics scraped | NOT RUN | healthy Prometheus target plus real samples |
| Loki receives structured logs | NOT RUN | bounded query returns staging JSON records |
| Tempo receives traces | NOT RUN | trace search returns an instrumented request |
| trace/log correlation | NOT RUN | one Tempo trace ID is present in a Loki record |
| authenticated Alertmanager delivery | NOT RUN | accepted webhook with configured Bearer token and rejected unauthenticated request |
| R2/R3/R4 Chaos Mesh targets | NOT RUN | admitted staging resource and denied forbidden fixtures |
| seven-day logical retention | NOT RUN | rendered/running config inspection |

Scenario evidence must use this structure:

```text
scenario:
run identifier:
trigger:
alert or security event:
incident ID:
runbook:
risk:
OPA result:
action or attribution:
verification:
cleanup:
final state:
known limitation:
```

Do not replace missing values with guessed IDs or outcomes.
