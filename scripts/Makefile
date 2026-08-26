SHELL := /usr/bin/env bash

.PHONY: create bootstrap validate validate-part2 destroy test import-demo-image e2e observability telemetry-bridge

create:
	./cluster-create.sh

bootstrap:
	./cluster-bootstrap.sh

validate:
	./validate-platform.sh

validate-part2:
	./validate-part2-platform.sh

destroy:
	./cluster-destroy.sh

test:
	./test-platform-assets.sh

import-demo-image:
	./import-demo-image.sh cloudward-demo-api:local

e2e:
	./e2e-unhealthy-pod.sh

observability:
	./port-forward-observability.sh grafana

telemetry-bridge:
	./port-forward-telemetry.sh
