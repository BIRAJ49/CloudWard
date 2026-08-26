"""Harmless internal HTTP receiver for the controlled S1/S2 security scenarios."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    server_version = "CloudWardSimulator/1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/health", "/observe"}:
            self._write(404, {"status": "not_found"})
            return
        if self.path == "/observe":
            print(
                json.dumps(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "event": "controlled_connection_observed",
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
        self._write(200, {"status": "ok", "simulator": "internal-only"})

    def log_message(self, _format: str, *args: object) -> None:
        del args

    def _write(self, status: int, payload: dict[str, str]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()

