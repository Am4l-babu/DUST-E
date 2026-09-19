"""
stream.py - a live, browser-viewable feed of what the vision pipeline sees.

For a headless UNO Q (or anywhere `--show`'s local OpenCV window cannot open
a display), this is the alternative: an MJPEG stream any browser can already
render inside a plain `<img>` tag, no client-side code at all. Same transport
choice as dustebrain.dashboard and for the same reason - this is a bring-up
and monitoring tool, not a product, and stdlib `http.server` needs no new
dependency beyond the one vision already requires (cv2, for JPEG encoding).

    stream = VisionStreamServer(port=8081)
    stream.start()
    ...
    stream.stream.update(annotated_frame)   # call this once per frame
    ...
    stream.stop()

FrameStream itself has no cv2 import - only .update() does, lazily, matching
the lazy-import pattern the rest of the vision code already uses (camera.py,
detector.py) so nothing outside an actual camera pipeline needs it installed.
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

_BOUNDARY = "dustebrain-frame"


class FrameStream:
    """Holds the single latest annotated frame as JPEG bytes. One producer
    (the vision loop) calls update(); any number of HTTP viewers read the
    latest snapshot via get() - stale reads are fine, a video feed is
    allowed to skip frames, it is never allowed to block the vision loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._frame_no = 0

    def update(self, image: np.ndarray, quality: int = 80) -> None:
        import cv2

        ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            return
        with self._lock:
            self._jpeg = buf.tobytes()
            self._frame_no += 1

    def get(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    @property
    def frame_no(self) -> int:
        with self._lock:
            return self._frame_no


def _make_handler(stream: FrameStream) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "DustEVisionStream/1"

        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            pass  # quiet by default - this fires once per frame per viewer

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/index.html"):
                self._page()
            elif self.path == "/snapshot.jpg":
                self._snapshot()
            elif self.path == "/stream.mjpg":
                self._mjpeg()
            else:
                self.send_error(404)

        def _page(self) -> None:
            body = (
                b"<!doctype html><html><head><title>DUST-E VISION</title>"
                b"<meta name=viewport content='width=device-width,initial-scale=1'>"
                b"<style>html,body{background:#0d0f11;margin:0;height:100%}"
                b"body{display:flex;align-items:center;justify-content:center}"
                b"img{max-width:100%;max-height:100%}</style></head>"
                b"<body><img src='/stream.mjpg' alt='vision stream'></body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _snapshot(self) -> None:
            jpeg = stream.get()
            if jpeg is None:
                self.send_error(503, "no frame yet")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpeg)))
            self.end_headers()
            self.wfile.write(jpeg)

        def _mjpeg(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={_BOUNDARY}")
            self.end_headers()
            last_sent = -1
            try:
                while True:
                    if stream.frame_no == last_sent:
                        time.sleep(0.02)
                        continue
                    jpeg = stream.get()
                    if jpeg is None:
                        time.sleep(0.05)
                        continue
                    last_sent = stream.frame_no
                    self.wfile.write(f"--{_BOUNDARY}\r\n".encode("ascii"))
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # the viewer closed the tab - not an error

    return Handler


class VisionStreamServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8081) -> None:
        self.stream = FrameStream()
        self._httpd = ThreadingHTTPServer((host, port), _make_handler(self.stream))

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[0], self._httpd.server_address[1]
        return f"http://{host if host not in ('0.0.0.0', '') else 'localhost'}:{port}/"

    def start(self) -> None:
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
