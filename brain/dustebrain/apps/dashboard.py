"""
dashboard_app.py - run the Phase 2 DRIVE + HW + DEBUG dashboard.

    # against a real XIAO body
    python -m dustebrain.apps.dashboard --port COM5

    # no hardware at all - drives an in-process SimBody over a LoopbackPipe,
    # so the page can be clicked around and demoed before any board exists
    python -m dustebrain.apps.dashboard --sim

Then open the printed URL. Every command this page sends is src="manual",
same as tools/body_probe.py - the dashboard is a client of BodyLink, not a
replacement for the safety layer underneath it.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

from ..body import protocol as P
from ..body.link import BodyLink, LoopbackPipe, SerialTransport
from ..body.simbody import SimBody
from ..config import ConfigError, load_config
from ..dashboard import DashboardServer


def _run_sim_body(pipe: LoopbackPipe, body: SimBody, stop: threading.Event,
                   now_fn, t0: float, hz: float = 100.0, telemetry_every_ms: int = 50) -> None:
    """Stands in for both the XIAO and its sensor node: reads what the
    dashboard's link wrote, feeds it to the reference reflex implementation,
    reports a permanently healthy MOTION_OK (no hazard - there is no real
    sensor node in --sim mode), and pushes telemetry on the same cadence a
    real body would. Mirrors tests/test_body_link.py's Harness.step()."""
    period = 1.0 / hz
    last_telemetry = 0
    while not stop.is_set():
        now_ms = int((now_fn() - t0) * 1000)
        incoming = pipe.peer_read_available()
        if incoming:
            for reply in body.feed(incoming, now_ms):
                pipe.peer_write(P.encode(reply))
        body.motion_ok_edge(now_ms)
        body.tick(now_ms)
        if now_ms - last_telemetry >= telemetry_every_ms:
            last_telemetry = now_ms
            pipe.peer_write(P.encode(body.telemetry()))
        stop.wait(period)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2

    sim_stop = threading.Event()
    sim_thread = None

    if args.sim:
        pipe = LoopbackPipe()
        body = SimBody(cfg.body)
        t0 = time.monotonic()
        sim_thread = threading.Thread(
            target=_run_sim_body, args=(pipe, body, sim_stop, time.monotonic, t0), daemon=True
        )
        sim_thread.start()
        transport = pipe
        print("# --sim: no hardware needed, driving an in-process SimBody")
    else:
        if not args.port:
            print("--port is required unless --sim is given", file=sys.stderr)
            return 2
        try:
            transport = SerialTransport(args.port, args.baud)
        except Exception as e:
            print(f"could not open {args.port}: {e}", file=sys.stderr)
            return 2

    link = BodyLink(transport, cfg.body)
    dash = DashboardServer(link, host=args.host, port=args.web_port)
    dash.start()
    print(f"# dashboard: {dash.url}")
    print("# Ctrl+C to stop")

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        dash.stop()
        sim_stop.set()
        if sim_thread:
            sim_thread.join(timeout=2.0)
        transport.close()
        print("# closed")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="dashboard_app", description=__doc__.split("\n\n")[0])
    p.add_argument("--port", help="serial port, e.g. COM5 or /dev/ttyACM0")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--sim", action="store_true", help="no hardware - drive an in-process SimBody instead")
    p.add_argument("--config", help="override YAML merged over config/default.yaml")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--web-port", type=int, default=8080)
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())
