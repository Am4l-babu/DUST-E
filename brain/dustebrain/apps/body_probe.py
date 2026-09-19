"""
body_probe.py - phase 2b bring-up tool: brain <-> XIAO body over a real serial port.

No navigation, no vision, no personality. It opens the link, watches the
handshake and telemetry, and can send exactly the handful of commands the
bring-up procedure in firmware/DustEBody/README.md section 6 calls for -
nothing else, because a bring-up tool that can do everything is a bring-up
tool that can also do something you did not mean to.

    # watch it connect and report, no motion (safe with wheels ON the ground)
    python -m dustebrain.apps.body_probe --port COM5

    # WHEELS OFF THE GROUND before this one:
    python -m dustebrain.apps.body_probe --port COM5 --drive 30 30 --duration-ms 1000

    python -m dustebrain.apps.body_probe --port COM5 --estop
    python -m dustebrain.apps.body_probe --port COM5 --reset-estop

Every command goes through the same Validator and BodyLink the rest of the
brain will use - this tool proves the wire, not a shortcut around it.
"""

from __future__ import annotations

import argparse
import sys
import time

from ..config import ConfigError, load_config
from ..body.link import BodyLink, SerialTransport


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2

    try:
        transport = SerialTransport(args.port, args.baud)
    except Exception as e:
        print(f"could not open {args.port}: {e}", file=sys.stderr)
        return 2

    link = BodyLink(transport, cfg.body)
    print(f"# opened {args.port} @ {args.baud}. waiting for the body to answer 'hello'...")

    t0 = time.monotonic()
    now_ms = lambda: int((time.monotonic() - t0) * 1000)  # noqa: E731
    next_snapshot = 0
    drive_until = None

    try:
        while True:
            t = now_ms()
            link.tick(t)

            if args.estop and link.state.handshaken and not link.state.estop:
                link.estop("body_probe --estop", "manual", t)
                print("# estop sent - Ctrl+C once the status line above confirms it")
                args.estop = False

            if args.reset_estop and link.state.handshaken:
                link.send("reset_estop", "manual", t)
                print("# reset_estop sent - Ctrl+C once the status line above confirms it")
                args.reset_estop = False

            if args.drive and drive_until is None and link.state.handshaken:
                drive_until = t + args.duration_ms
                print(f"# driving l={args.drive[0]} r={args.drive[1]} for {args.duration_ms} ms "
                      f"(src=manual, so the {cfg.body.manual_max_pct}% ceiling applies)")
            if drive_until is not None:
                if t < drive_until:
                    link.velocity(args.drive[0], args.drive[1], t, src="manual")
                else:
                    link.stop("manual", t)
                    print("# drive complete, stop sent")
                    drive_until = None
                    if not (args.estop or args.reset_estop):
                        break

            if args.snapshot and t >= next_snapshot:
                next_snapshot = t + int(args.snapshot * 1000)
                _print_status(link, t)

            if not args.drive and not args.estop and not args.reset_estop and args.once:
                if link.state.handshaken:
                    _print_status(link, t)
                    break

            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        link.stop("manual", now_ms())
        time.sleep(0.1)
        link.tick(now_ms())     # give the stop one more chance to go out and be seen
        transport.close()
        print("# closed")
    return 0


def _print_status(link: BodyLink, t: int) -> None:
    s = link.state
    online = "yes" if s.online(t / 1000.0, stale_after_s=cfg_stale(link)) else "NO"
    print(f"[{t:7d}ms] handshaken={s.handshaken} online={online} "
          f"estop={s.estop}{' (' + s.estop_reason + ')' if s.estop_reason else ''} "
          f"inhibit={s.inhibit!r} motion_ok={s.motion_ok} "
          f"battery_mv={s.battery_mv} crc_err={s.crc_errors}")


def cfg_stale(link: BodyLink) -> float:
    # A generous "still trustworthy" window for a human watching a terminal -
    # a few missed heartbeats, not the tight reflex-layer timeout itself.
    return (link.cfg.link_timeout_ms * 3) / 1000.0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="body_probe", description=__doc__.split("\n\n")[0])
    p.add_argument("--port", required=True, help="serial port, e.g. COM5 or /dev/ttyACM0")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--config", help="override YAML merged over config/default.yaml")
    p.add_argument("--snapshot", type=float, default=1.0, metavar="S",
                   help="print a status line every S seconds (0 to disable)")
    p.add_argument("--once", action="store_true",
                   help="print one status line once handshaken, then exit")
    p.add_argument("--drive", nargs=2, type=int, metavar=("L", "R"),
                   help="WHEELS OFF THE GROUND. Percent, -100..100, sent as src=manual.")
    p.add_argument("--duration-ms", type=int, default=1000)
    p.add_argument("--estop", action="store_true", help="send an emergency stop and keep watching")
    p.add_argument("--reset-estop", action="store_true", help="clear a latched emergency stop")
    args = p.parse_args(argv)
    if args.drive and (abs(args.drive[0]) > 100 or abs(args.drive[1]) > 100):
        p.error("--drive values must be within -100..100 (the validator would clamp them anyway)")
    return args


if __name__ == "__main__":
    sys.exit(main())
