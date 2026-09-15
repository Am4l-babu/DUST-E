"""
vision_node.py - phase 1, standalone: camera -> detector -> tracker -> world model.

No motors, no body, no LLM. It prints what the robot would believe.

    # the real thing, on the UNO Q
    python -m binbrain.apps.vision_node

    # no camera, no model: a scripted person (also the DEBUG "simulate a person")
    python -m binbrain.apps.vision_node --sim walk_in

    # can the board keep up? (acceptance: >= 3 Hz)
    python -m binbrain.apps.vision_node --bench 50

    # replay a recording, draw what it saw
    python -m binbrain.apps.vision_node --source hallway.mp4 --show

Exit with Ctrl+C. Loop order, like the firmware's, is not arbitrary:
grab newest frame -> detect -> signatures -> track -> world -> events.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import statistics
import sys
import time

import numpy as np

from ..config import BrainConfig, ConfigError, load_config
from ..eventlog import EventLog
from ..sim.scenario import SCENARIOS
from ..vision.tracker import Tracker
from ..world.model import WorldModel

log = logging.getLogger("vision_node")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        overrides = {"camera": {"source": args.source}} if args.source is not None else None
        cfg = load_config(args.config, overrides)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2

    logging.basicConfig(level=cfg.logging.level, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    jsonl = args.jsonl or cfg.logging.events_jsonl or None

    try:
        if args.sim:
            return run_sim(cfg, args.sim, jsonl, args.realtime, args.snapshot)
        if args.bench:
            return run_bench(cfg, args.bench)
        return run_live(cfg, jsonl, args.show, args.snapshot, args.duration)
    except KeyboardInterrupt:
        return 0
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 2


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="vision_node", description=__doc__.split("\n\n")[0])
    p.add_argument("--config", help="override YAML merged over config/default.yaml")
    p.add_argument("--source", help="camera index or video file (overrides camera.source)")
    p.add_argument("--sim", choices=sorted(SCENARIOS), help="run a scripted scenario instead of a camera")
    p.add_argument("--realtime", action="store_true", help="pace --sim at real speed")
    p.add_argument("--bench", type=int, metavar="N", help="time N detector runs and exit")
    p.add_argument("--show", action="store_true", help="draw tracks in a window (needs a display)")
    p.add_argument("--jsonl", help="append events as JSON lines to this file")
    p.add_argument("--snapshot", type=float, metavar="S", default=0.0,
                   help="print the LLM summary every S seconds")
    p.add_argument("--duration", type=float, metavar="S", default=0.0, help="stop after S seconds")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
def run_sim(cfg: BrainConfig, name: str, jsonl: str | None, realtime: bool, snapshot_s: float) -> int:
    scenario = SCENARIOS[name]()
    print(f"# scenario {scenario.name}: {scenario.description}")
    tracker = Tracker(cfg)
    world = WorldModel(cfg)
    events = EventLog(0.0, jsonl)
    next_snapshot = 0.0
    started = time.monotonic()
    try:
        for frame in scenario.frames(cfg):
            if realtime:
                time.sleep(max(0.0, started + frame.t - time.monotonic()))
            tracks = tracker.update(frame.detections, frame.t)
            events.emit(world.update(tracks, frame.t, frame.ego_forward_mps))
            if snapshot_s and frame.t >= next_snapshot:
                print("  summary " + json.dumps(world.summary(frame.t)))
                next_snapshot = frame.t + snapshot_s
    finally:
        events.close()
    return 0


def run_live(cfg: BrainConfig, jsonl: str | None, show: bool, snapshot_s: float, duration_s: float) -> int:
    from ..vision.appearance import torso_signature
    from ..vision.camera import CameraSource
    from ..vision.detector import create_detector

    detector = create_detector(cfg)
    camera = CameraSource(cfg.camera)
    tracker = Tracker(cfg)
    world = WorldModel(cfg)
    t0 = time.monotonic()
    events = EventLog(t0, jsonl)
    period = 1.0 / cfg.detector.rate_hz
    last_index = -1
    next_snapshot = t0
    det_ms: list[float] = []

    camera.start()
    log.info("vision node running: detector %s at <= %.1f Hz", detector.name, cfg.detector.rate_hz)
    try:
        while True:
            loop_start = time.monotonic()
            if duration_s and loop_start - t0 >= duration_s:
                break
            frame = camera.latest(after_index=last_index, timeout=period)
            if frame is None:
                events.emit(world.tick(time.monotonic()))
                if camera.ended:
                    break
                continue
            last_index = frame.index

            d0 = time.monotonic()
            detections = detector.detect(frame.image)
            det_ms.append((time.monotonic() - d0) * 1000.0)
            detections = [
                dataclasses.replace(d, signature=torso_signature(frame.image, d.box))
                if d.label == cfg.world.person_label else d
                for d in detections
            ]
            tracks = tracker.update(detections, frame.t)
            events.emit(world.update(tracks, frame.t))

            now = time.monotonic()
            if snapshot_s and now >= next_snapshot:
                recent = det_ms[-20:]
                print(f"  camera {camera.fps:4.1f} fps, detector {statistics.fmean(recent):5.0f} ms  "
                      + json.dumps(world.summary(now)))
                next_snapshot = now + snapshot_s
            if show and not _draw(frame.image, tracks, world):
                break

            time.sleep(max(0.0, period - (time.monotonic() - loop_start)))
    finally:
        camera.stop()
        events.close()
        if show:
            import cv2
            cv2.destroyAllWindows()
    return 0


def run_bench(cfg: BrainConfig, n: int) -> int:
    from ..vision.camera import CameraSource
    from ..vision.detector import create_detector

    detector = create_detector(cfg)
    camera = CameraSource(cfg.camera)
    camera.start()
    frame = camera.latest(timeout=5.0)
    camera.stop()
    if frame is not None:
        image, what = frame.image, f"camera frame {frame.image.shape[1]}x{frame.image.shape[0]}"
    else:
        # Timing does not depend on content; say so rather than pretend.
        image = np.random.default_rng(1).integers(0, 255, (cfg.camera.height, cfg.camera.width, 3), dtype=np.uint8)
        what = f"noise image {cfg.camera.width}x{cfg.camera.height} (no camera)"

    for _ in range(3):
        detector.detect(image)                  # warm-up: first runs allocate
    times = []
    for _ in range(n):
        s = time.perf_counter()
        detector.detect(image)
        times.append((time.perf_counter() - s) * 1000.0)
    times.sort()
    mean = statistics.fmean(times)
    p95 = times[min(len(times) - 1, int(0.95 * len(times)))]
    print(f"detector {detector.name} on {what}")
    print(f"  runs {n}  mean {mean:.1f} ms  p95 {p95:.1f} ms  -> {1000.0 / mean:.1f} Hz")
    print("  acceptance (phase 1): >= 3 Hz  " + ("PASS" if 1000.0 / mean >= 3.0 else "FAIL"))
    return 0


def _draw(image: np.ndarray, tracks, world: WorldModel) -> bool:
    import cv2

    h, w = image.shape[:2]
    canvas = image.copy()
    for tr in tracks:
        if not tr.visible:
            continue
        b = tr.box
        p1, p2 = (int(b.x1 * w), int(b.y1 * h)), (int(b.x2 * w), int(b.y2 * h))
        person = world.person_for_track(tr.track_id)
        if person is not None:
            dist = "?" if person.distance_m is None else f"{'' if person.distance_reliable else '~'}{person.distance_m:.1f}m"
            text = f"#{person.person_id} {dist} {person.zone.value} {person.motion.value}"
            colour = (0, 200, 255)
        else:
            text = f"{tr.label} {tr.score:.2f}"
            colour = (200, 200, 0)
        cv2.rectangle(canvas, p1, p2, colour, 2)
        cv2.putText(canvas, text, (p1[0], max(12, p1[1] - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, colour, 1)
    cv2.imshow("binbrain vision", canvas)
    return (cv2.waitKey(1) & 0xFF) not in (27, ord("q"))


if __name__ == "__main__":
    sys.exit(main())
