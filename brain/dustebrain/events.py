"""
events.py - the vocabulary the brain's subsystems agree on.

One enum for the whole brain, the way firmware/DustEWeb/src/core/types.h is
one header for the whole bin: the social planner, the navigation state machine,
the dashboard and the event log all read the same names.

Only the events marked "phase 1" are emitted yet. The others are declared now
so later phases extend this list rather than inventing a second one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    # --- phase 1: vision / world model -------------------------------------
    VISION_ONLINE = "VISION_ONLINE"
    VISION_OFFLINE = "VISION_OFFLINE"
    PERSON_DETECTED = "PERSON_DETECTED"          # a new person, confirmed over several frames
    PERSON_RETURNED = "PERSON_RETURNED"          # someone announced as lost is back
    PERSON_APPROACHING = "PERSON_APPROACHING"
    PERSON_WALKING_AWAY = "PERSON_WALKING_AWAY"
    PERSON_LEAVING = "PERSON_LEAVING"            # walking away AND beyond the notice zone
    PERSON_LOST = "PERSON_LOST"
    PERSON_ZONE_CHANGED = "PERSON_ZONE_CHANGED"
    OBJECT_DETECTED = "OBJECT_DETECTED"

    # --- later phases (declared, not yet emitted) --------------------------
    PERSON_LOOKING_AT_ROBOT = "PERSON_LOOKING_AT_ROBOT"   # phase 6, face detector
    PERSON_AVOIDING_ROBOT = "PERSON_AVOIDING_ROBOT"       # phase 3/6, social governor
    PERSON_SPEAKING = "PERSON_SPEAKING"                   # phase 4, VAD
    PERSON_SILENT = "PERSON_SILENT"
    USER_REQUEST = "USER_REQUEST"                         # phase 5
    USER_LAUGHED = "USER_LAUGHED"
    USER_IGNORED_ROBOT = "USER_IGNORED_ROBOT"             # phase 6
    OBSTACLE_DETECTED = "OBSTACLE_DETECTED"               # phase 2/3, body telemetry
    PATH_BLOCKED = "PATH_BLOCKED"
    BATTERY_LOW = "BATTERY_LOW"
    DOCK_REQUIRED = "DOCK_REQUIRED"
    BODY_LOST = "BODY_LOST"


@dataclass(frozen=True)
class Event:
    type: EventType
    t: float                           # monotonic seconds, the brain's clock
    person_id: int | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type.value, "t": round(self.t, 3)}
        if self.person_id is not None:
            out["person_id"] = self.person_id
        out.update(self.data)
        return out
