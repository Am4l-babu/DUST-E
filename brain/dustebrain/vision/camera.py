"""
camera.py - the USB webcam, read in a thread that only ever keeps the latest frame.

A queue of frames is how a robot ends up reacting to where a person was two
seconds ago. The grabber overwrites one slot; the detector takes whatever is
newest when it is ready and silently skips the rest.

The camera degrades instead of failing: an unplugged camera is retried every
`reconnect_s`, `online` goes false after `stale_after_s` without a frame, and
the world model turns that into VISION_OFFLINE - never into "nobody is here".

A video file path as `camera.source` replays that file at its recorded rate,
which is how detector and tracker changes get tested against the same footage.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass

import numpy as np

from ..config import CameraConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Frame:
    index: int
    t: float                 # time.monotonic() when grabbed
    image: np.ndarray        # BGR, HxWx3


class CameraSource:
    def __init__(self, cfg: CameraConfig) -> None:
        self._cfg = cfg
        self._cond = threading.Condition()
        self._frame: Frame | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fps = 0.0
        self.ended = False           # a replayed file ran out

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def latest(self, after_index: int = -1, timeout: float = 0.5) -> Frame | None:
        """The newest frame with index > after_index, waiting up to timeout."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while not self._stop.is_set():
                f = self._frame
                if f is not None and f.index > after_index:
                    return f
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self.ended:
                    return None
                self._cond.wait(remaining)
        return None

    @property
    def online(self) -> bool:
        f = self._frame
        return f is not None and time.monotonic() - f.t < self._cfg.stale_after_s

    @property
    def fps(self) -> float:
        return self._fps

    # ------------------------------------------------------------------
    def _open(self):
        import cv2

        src = self._cfg.source
        is_device = src.isdigit()
        if is_device and sys.platform.startswith("linux"):
            cap = cv2.VideoCapture(int(src), cv2.CAP_V4L2)
        else:
            cap = cv2.VideoCapture(int(src) if is_device else src)
        if not cap.isOpened():
            cap.release()
            return None, is_device
        if is_device:
            # MJPEG keeps USB bandwidth down, which matters behind a hub that
            # is also carrying the ESP32 link and a microphone.
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._cfg.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._cfg.height)
            cap.set(cv2.CAP_PROP_FPS, self._cfg.fps)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap, is_device

    def _run(self) -> None:
        import cv2

        index = 0
        cap = None
        is_device = True
        while not self._stop.is_set():
            if cap is None:
                cap, is_device = self._open()
                if cap is None:
                    log.warning("camera %r not available, retrying in %.1f s",
                                self._cfg.source, self._cfg.reconnect_s)
                    self._stop.wait(self._cfg.reconnect_s)
                    continue
                file_fps = cap.get(cv2.CAP_PROP_FPS) if not is_device else 0.0
                period = 1.0 / (file_fps if file_fps and file_fps > 0 else self._cfg.fps)
                log.info("camera %r open", self._cfg.source)

            ok, image = cap.read()
            now = time.monotonic()
            if not ok or image is None:
                cap.release()
                cap = None
                if not is_device:
                    log.info("replay file ended")
                    self.ended = True
                    with self._cond:
                        self._cond.notify_all()
                    return
                log.warning("camera read failed; reopening")
                continue

            if self._cfg.flip_horizontal:
                image = cv2.flip(image, 1)

            prev = self._frame
            if prev is not None and now > prev.t:
                rate = 1.0 / (now - prev.t)
                self._fps = rate if self._fps == 0.0 else 0.9 * self._fps + 0.1 * rate
            index += 1
            with self._cond:
                self._frame = Frame(index, now, image)
                self._cond.notify_all()

            if not is_device:
                self._stop.wait(period)     # pace a replay like the real camera

        if cap is not None:
            cap.release()
