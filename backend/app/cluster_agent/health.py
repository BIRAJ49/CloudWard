"""Exec probes: liveness tracks loop progress; readiness requires a successful delivery."""

import json
import os
import sys
import time
from pathlib import Path


def healthy(*, liveness: bool = False) -> bool:
    try:
        state = json.loads(
            (
                Path(os.getenv("AGENT_STATE_DIRECTORY", "/var/run/cloudward-agent")) / "status.json"
            ).read_text()
        )
        if not isinstance(state, dict):
            return False
        timestamp = state.get("cycle_at" if liveness else "delivered_at")
        return isinstance(timestamp, (int, float)) and 0 <= time.time() - timestamp < 180
    except (OSError, ValueError, TypeError):
        return False


if __name__ == "__main__":
    sys.exit(0 if healthy(liveness="--liveness" in sys.argv) else 1)
