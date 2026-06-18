"""Proxy + distill the IB-backed price server's /health endpoint.

Only meaningful in local IB mode (the frontend polls this every few seconds
under `npm run dev`). In production the site serves Yahoo data and there is no
IB server, so this just returns 502 — the deployed UI never calls it.

Points at the same server as ib_client via the IB_API_URL env var
(defaults to http://192.168.1.19:8198).
"""
import json
import os
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))
from _common import authed, respond  # noqa: E402

BASE_URL = os.environ.get("IB_API_URL", "http://192.168.1.19:8198")
TIMEOUT = 10

# Checks the server marks "critical" gate whether the IB API is usable at all;
# if any of those fail we call the IB API "down" regardless of the trust score.
def _classify(verdict: dict) -> str:
    """Reduce the server's verdict to ok | degraded | down for the UI."""
    checks = verdict.get("checks", [])
    critical_failed = any(
        not c.get("ok", True) and c.get("severity") == "critical" for c in checks
    )
    if critical_failed:
        return "down"
    # Defer to the server's holistic verdict otherwise: it can hold "ok" through
    # info-level blips (e.g. a slow gateway-latency check) — no need to be more
    # pessimistic than it is. Anything other than "ok" surfaces as degraded.
    return "ok" if verdict.get("trust") == "ok" else "degraded"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not authed(self):
            return respond(self, 401, {"error": "Not authenticated"})
        try:
            with urllib.request.urlopen(f"{BASE_URL}/health", timeout=TIMEOUT) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            # Server unreachable / errored — surface as "down" so the UI shows red.
            return respond(self, 200, {
                "state": "down",
                "summary": f"IB server unreachable: {exc}",
                "trust": None,
                "score": None,
                "failed": [],
                "checks": [],
            })

        verdict = body.get("verdict", {})
        respond(self, 200, {
            "state": _classify(verdict),
            "trust": verdict.get("trust"),
            "score": verdict.get("score"),
            "summary": verdict.get("summary"),
            "failed": verdict.get("failed", []),
            # Forward the per-check breakdown (name/ok/severity/detail) for tooltips.
            "checks": verdict.get("checks", []),
            "marketOpen": body.get("market", {}).get("open"),
        })
