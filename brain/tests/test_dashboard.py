"""
Integration test for dustebrain.dashboard against a real body reference.

Real HTTP requests, over a real socket (127.0.0.1, an OS-assigned port), hit
a real DashboardServer wired to a real BodyLink over a LoopbackPipe, answered
by a real SimBody run the same way dashboard_app.py's --sim mode runs it.
Nothing here is mocked; this is the same "no hardware, still exercises the
real stack" discipline as test_body_link.py, just over HTTP instead of in
one Python process's call stack.

Real wall-clock time is used (not a stepped simulated clock) because the
dashboard's own tick thread runs on wall-clock timers - that thread is
exactly what this test is verifying works, so simulating it away would
defeat the point.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request

import pytest

from dustebrain.apps.dashboard import _run_sim_body
from dustebrain.body.link import BodyLink, LoopbackPipe
from dustebrain.body.simbody import SimBody
from dustebrain.dashboard import DashboardServer


class Rig:
    def __init__(self, cfg):
        self.pipe = LoopbackPipe()
        self.link = BodyLink(self.pipe, cfg.body)
        self.body = SimBody(cfg.body)
        self.dash = DashboardServer(self.link, host="127.0.0.1", port=0)
        self._stop = threading.Event()
        self._sim_thread = threading.Thread(
            target=_run_sim_body,
            args=(self.pipe, self.body, self._stop, time.monotonic, time.monotonic()),
            daemon=True,
        )

    def start(self) -> None:
        self._sim_thread.start()
        self.dash.start()

    def stop(self) -> None:
        self._stop.set()
        self._sim_thread.join(timeout=2.0)
        self.dash.stop()

    def get(self, path: str) -> dict:
        with urllib.request.urlopen(self.dash.url.rstrip("/") + path, timeout=2) as r:
            return json.loads(r.read())

    def post(self, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(
            self.dash.url.rstrip("/") + path, data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.loads(r.read())


@pytest.fixture
def rig(cfg):
    r = Rig(cfg)
    r.start()
    yield r
    r.stop()


def _wait_until(predicate, timeout_s: float = 2.0, interval_s: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def test_the_page_and_static_assets_are_served(rig):
    with urllib.request.urlopen(rig.dash.url, timeout=2) as r:
        assert r.status == 200
        assert b"DUST-E BRAIN" in r.read()
    with urllib.request.urlopen(rig.dash.url + "style.css", timeout=2) as r:
        assert r.status == 200
    with urllib.request.urlopen(rig.dash.url + "app.js", timeout=2) as r:
        assert r.status == 200


def test_status_reaches_handshaken_and_online_on_its_own(rig):
    assert _wait_until(lambda: rig.get("/api/status")["handshaken"])
    assert _wait_until(lambda: rig.get("/api/status")["online"])


def test_a_drive_command_reaches_the_real_body_reference(rig):
    assert _wait_until(lambda: rig.get("/api/status")["online"])

    # Hold-to-drive: the dashboard's JS resends every 100ms. Model that here
    # rather than sending once, matching the command's real TTL behaviour.
    stop_sending = threading.Event()

    def resend():
        while not stop_sending.is_set():
            rig.post("/api/drive", {"l": 60, "r": 60})
            time.sleep(0.05)

    t = threading.Thread(target=resend, daemon=True)
    t.start()
    try:
        moved = _wait_until(lambda: rig.get("/api/status")["telemetry"].get("ml", 0) > 0)
    finally:
        stop_sending.set()
        t.join(timeout=1.0)
    assert moved

    rig.post("/api/stop")
    assert _wait_until(lambda: rig.get("/api/status")["telemetry"].get("ml", -1) == 0)


def test_the_dashboard_cannot_exceed_the_effective_ceiling(rig):
    # manual_max_pct is a HIGHER number than auto_max_pct in config (a human
    # at the dashboard is meant to be allowed more than autonomous driving),
    # but neither SimBody (_ramp_to, simbody.py) nor the real firmware
    # (Motors::setCeiling, motors.cpp) actually implement that: the ceiling
    # starts at auto_max_pct and both bodies only ever allow LOWERING it,
    # for any source. So the ceiling this test can actually observe being
    # enforced today is auto_max_pct, not manual_max_pct - see the note in
    # docs/COMPANION_ARCHITECTURE.md section 8 flagging that as a known gap.
    assert _wait_until(lambda: rig.get("/api/status")["online"])
    effective_ceiling = rig.get("/api/status")["auto_max_pct"]

    # One-shot sends let the command TTL expire before the ramp catches up
    # (see test_body_link.py's note on the same trap) - hold it, like a real
    # dashboard user with a finger on the button.
    stop_sending = threading.Event()

    def resend():
        while not stop_sending.is_set():
            rig.post("/api/drive", {"l": 100, "r": 100})
            time.sleep(0.05)

    t = threading.Thread(target=resend, daemon=True)
    t.start()
    try:
        reached = _wait_until(lambda: rig.get("/api/status")["telemetry"].get("ml", 0) >= effective_ceiling)
        status = rig.get("/api/status")
    finally:
        stop_sending.set()
        t.join(timeout=1.0)
    assert reached
    assert status["telemetry"]["ml"] == effective_ceiling
    rig.post("/api/stop")


def test_estop_over_http_latches_and_reset_clears_it(rig):
    assert _wait_until(lambda: rig.get("/api/status")["online"])

    resp = rig.post("/api/estop", {"reason": "test"})
    assert resp["ok"]
    assert _wait_until(lambda: rig.get("/api/status")["estop"])
    assert rig.get("/api/status")["estop_reason"]

    resp = rig.post("/api/reset_estop")
    assert resp["ok"]
    assert _wait_until(lambda: not rig.get("/api/status")["estop"])


def test_a_malformed_drive_body_is_rejected_not_crashed(rig):
    resp = rig.post("/api/drive", {"l": "not a number", "r": 10})
    assert resp["ok"] is False
    assert "error" in resp


def test_debug_log_shows_real_wire_traffic(rig):
    assert _wait_until(lambda: rig.get("/api/status")["handshaken"])
    log = rig.get("/api/log")
    assert any(e.get("type") == "hello" for e in log["wire"])
    assert any(e["dir"] == "rx" for e in log["wire"])
    assert any(e["dir"] == "tx" for e in log["wire"])
