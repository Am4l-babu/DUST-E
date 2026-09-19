"""
server.py - dustebrain.dashboard: the Phase 2 DRIVE + HW + DEBUG web dashboard.

An HTTP server, stdlib only (no new dependency - `http.server`), serving a
small static page and a JSON API. Real-time-enough for driving and bring-up:
the page polls /api/status every 150 ms, well under the body's own command
TTL, and holding a drive control resends /api/drive on the same cadence so
the command never expires while a key is held.

This is a thin, honest wrapper around BodyLink - no new safety logic, no
shortcut around the Validator. Every command this server sends goes in as
src="manual", exactly like tools/body_probe.py's CLI; the dashboard can do
nothing that CLI could not already do, and the XIAO's reflex layer still has
the last word regardless of what either one asks for.

    from dustebrain.body.link import BodyLink, SerialTransport
    from dustebrain.dashboard import DashboardServer

    link = BodyLink(SerialTransport("COM5"), cfg.body)
    dash = DashboardServer(link)
    dash.start()   # background threads: link ticker + HTTP server
    ...
    dash.stop()
"""

from __future__ import annotations

import json
import logging
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ..body.link import BodyLink

log = logging.getLogger(__name__)

WWW_DIR = Path(__file__).parent / "www"


class DashboardServer:
    def __init__(self, link: BodyLink, host: str = "0.0.0.0", port: int = 8080,
                 tick_hz: float = 50.0, now_fn=time.monotonic) -> None:
        self.link = link
        self.lock = threading.Lock()
        self._now_fn = now_fn
        self._t0 = now_fn()
        self._tick_period = 1.0 / tick_hz
        self._stop = threading.Event()
        self._tick_thread: threading.Thread | None = None

        handler = _make_handler(self)
        self._httpd = ThreadingHTTPServer((host, port), handler)

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[0], self._httpd.server_address[1]
        return f"http://{host if host not in ('0.0.0.0', '') else 'localhost'}:{port}/"

    def now_ms(self) -> int:
        return int((self._now_fn() - self._t0) * 1000)

    def start(self) -> None:
        self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._tick_thread.start()
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        log.info("dashboard: serving %s", self.url)

    def stop(self) -> None:
        self._stop.set()
        if self._tick_thread:
            self._tick_thread.join(timeout=2.0)
        self._httpd.shutdown()
        self._httpd.server_close()

    def _tick_loop(self) -> None:
        while not self._stop.is_set():
            with self.lock:
                self.link.tick(self.now_ms())
            self._stop.wait(self._tick_period)

    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        s = self.link.state
        stale_after_s = (self.link.cfg.link_timeout_ms * 3) / 1000.0
        now_s = self._now_fn()
        return {
            "now_ms": self.now_ms(),
            "handshaken": s.handshaken,
            "online": s.online(now_s, stale_after_s),
            "fw_version": s.fw_version,
            "hw": s.hw,
            "limits": s.limits,
            "estop": s.estop,
            "estop_reason": s.estop_reason,
            "inhibit": s.inhibit,
            "motion_ok": s.motion_ok,
            "battery_mv": s.battery_mv,
            "telemetry": s.telemetry,
            "crc_errors": s.crc_errors,
            "rejected_local": s.rejected_local,
            "manual_max_pct": self.link.cfg.manual_max_pct,
            "auto_max_pct": self.link.cfg.auto_max_pct,
        }

    def log_snapshot(self, limit: int = 100) -> dict[str, Any]:
        return {
            "wire": self.link.wire_log[-limit:],
            "events": self.link.state.events[-limit:],
        }

    # ------------------------------------------------------------------
    def do_drive(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            l, r = int(body["l"]), int(body["r"])
        except (KeyError, TypeError, ValueError):
            return {"ok": False, "error": "expected integer fields 'l' and 'r'"}
        with self.lock:
            ok = self.link.velocity(l, r, self.now_ms(), src="manual")
        return {"ok": ok}

    def do_stop(self) -> dict[str, Any]:
        with self.lock:
            ok = self.link.stop("manual", self.now_ms())
        return {"ok": ok}

    def do_estop(self, body: dict[str, Any]) -> dict[str, Any]:
        reason = str(body.get("reason", "dashboard"))
        with self.lock:
            ok = self.link.estop(reason, "manual", self.now_ms())
        return {"ok": ok}

    def do_reset_estop(self) -> dict[str, Any]:
        with self.lock:
            ok = self.link.send("reset_estop", "manual", self.now_ms())
        return {"ok": ok}


def _make_handler(dash: DashboardServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "DustEDashboard/1"

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            log.debug("%s - %s", self.address_string(), fmt % args)

        def _json(self, payload: dict[str, Any], status: int = 200) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _static(self, rel_path: str) -> None:
            path = (WWW_DIR / rel_path).resolve()
            if WWW_DIR.resolve() not in path.parents and path != WWW_DIR.resolve():
                self.send_error(404)
                return
            if not path.is_file():
                self.send_error(404)
                return
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {}

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/" or self.path == "/index.html":
                self._static("index.html")
            elif self.path == "/api/status":
                self._json(dash.status())
            elif self.path.startswith("/api/log"):
                self._json(dash.log_snapshot())
            elif self.path in ("/style.css", "/app.js"):
                self._static(self.path.lstrip("/"))
            else:
                self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            body = self._read_json_body()
            if self.path == "/api/drive":
                self._json(dash.do_drive(body))
            elif self.path == "/api/stop":
                self._json(dash.do_stop())
            elif self.path == "/api/estop":
                self._json(dash.do_estop(body))
            elif self.path == "/api/reset_estop":
                self._json(dash.do_reset_estop())
            else:
                self.send_error(404)

    return Handler
