"""
eventlog.py - the brain's half of the event log.

Same discipline as firmware/DustEWeb/src/core/eventLog: every event is a
code plus a human-readable line, so "it greeted me twice" can be checked
against what the robot actually believed. One line per event on stdout in the
firmware's format, and optionally one JSON object per line in a file for the
dashboard and for replaying a session.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO, Iterable

from .events import Event


def describe(ev: Event) -> str:
    d = ev.data
    parts: list[str] = []
    if ev.person_id is not None:
        parts.append(f"#{ev.person_id}")
    if "distance_m" in d:
        dist = d["distance_m"]
        approx = "" if d.get("distance_reliable") else "~"
        parts.append("? m" if dist is None else f"{approx}{dist:.1f} m")
    for key in ("direction", "zone", "motion"):
        if key in d:
            parts.append(str(d[key]))
    for key, value in d.items():
        if key not in ("distance_m", "distance_reliable", "direction", "zone", "motion"):
            parts.append(f"{key}={value}")
    return " ".join(parts)


class EventLog:
    def __init__(self, t0: float, jsonl_path: str | Path | None = None,
                 stream: IO[str] | None = None) -> None:
        self._t0 = t0
        self._stream = stream if stream is not None else sys.stdout
        self._jsonl = open(jsonl_path, "a", encoding="utf-8") if jsonl_path else None

    def emit(self, events: Iterable[Event]) -> None:
        for ev in events:
            ms = (ev.t - self._t0) * 1000.0
            self._stream.write(f"[{ms:9.0f}] {ev.type.value:<20} {describe(ev)}\n")
            if self._jsonl is not None:
                self._jsonl.write(json.dumps(ev.to_dict()) + "\n")
        self._stream.flush()
        if self._jsonl is not None:
            self._jsonl.flush()

    def close(self) -> None:
        if self._jsonl is not None:
            self._jsonl.close()
            self._jsonl = None
