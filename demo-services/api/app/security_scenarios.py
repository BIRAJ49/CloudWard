"""Fixed, benign runtime-security signals for local Incident Lab scenarios."""

from __future__ import annotations

import asyncio
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter

router = APIRouter(prefix="/demo/security", tags=["security-demo"])

EXPECTED_C2_HOST = "cloudward-c2-simulator.cloudward-staging.svc.cluster.local"


def _c2_url() -> str:
    value = os.getenv("CLOUDWARD_C2_URL", f"http://{EXPECTED_C2_HOST}:8080/observe")
    parsed = urllib.parse.urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname != EXPECTED_C2_HOST
        or parsed.port != 8080
        or parsed.path != "/observe"
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("CLOUDWARD_C2_URL must reference the fixed internal simulator")
    return value


def _probe() -> bool:
    request = urllib.request.Request(_c2_url(), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


@router.get("/egress-probe")
async def controlled_egress_probe() -> dict[str, bool | str]:
    reachable = await asyncio.to_thread(_probe)
    return {
        "scenario": "security.unexpected-egress",
        "target": "internal-c2-simulator",
        "reachable": reachable,
    }


@router.api_route("/suspicious-shell", methods=["GET", "POST"])
async def suspicious_shell() -> dict[str, bool | str]:
    def fixed_shell_and_probe() -> bool:
        subprocess.run(  # noqa: S603
            ["/bin/sh", "-c", "printf cloudward-benign-shell-signal >/dev/null"],
            check=True,
            timeout=2,
            cwd="/tmp/cloudward-demo",
            env={"PATH": "/usr/bin:/bin"},
        )
        return _probe()

    reachable = await asyncio.to_thread(fixed_shell_and_probe)
    return {
        "scenario": "security.suspicious-shell-pattern",
        "shell_signal": "completed",
        "internal_simulator_reachable": reachable,
        "external_connection": False,
    }


@router.api_route("/unexpected-egress", methods=["GET", "POST"])
async def unexpected_egress() -> dict[str, bool | str]:
    reachable = await asyncio.to_thread(_probe)
    return {
        "scenario": "security.unexpected-egress",
        "target": "internal-c2-simulator",
        "reachable": reachable,
        "external_connection": False,
    }


@router.api_route("/privilege-attempt", methods=["GET", "POST"])
async def privilege_attempt() -> dict[str, bool | str]:
    def fixed_denied_read() -> bool:
        try:
            with open("/proc/1/mem", "rb") as stream:  # noqa: PTH123
                stream.read(1)
        except (OSError, PermissionError):
            return True
        return False

    denied = await asyncio.to_thread(fixed_denied_read)
    return {
        "scenario": "security.privilege-related-behavior",
        "operation": "controlled-read-/proc/1/mem",
        "denied": denied,
        "exploit_attempted": False,
    }
