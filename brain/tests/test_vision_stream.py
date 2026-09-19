"""
Integration test for dustebrain.vision.stream against a real HTTP socket.

Real requests, over a real socket (127.0.0.1, an OS-assigned port), against a
real VisionStreamServer fed real JPEG-encoded frames via cv2 - nothing
mocked, same discipline as test_dashboard.py and test_body_link.py.

Needs cv2 (FrameStream.update() encodes with it) - the same dependency
brain/requirements.txt already declares for anything camera-related, so this
is not a new requirement on top of what vision already needs.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from dustebrain.vision.stream import FrameStream, VisionStreamServer  # noqa: E402


def _fake_frame(fill: int = 128) -> np.ndarray:
    return np.full((60, 80, 3), fill, dtype=np.uint8)


def test_framestream_encodes_and_reports_a_frame_number():
    fs = FrameStream()
    assert fs.get() is None
    assert fs.frame_no == 0

    fs.update(_fake_frame())
    jpeg = fs.get()
    assert jpeg is not None
    assert jpeg[:2] == b"\xff\xd8"          # JPEG SOI marker - really a JPEG, not just bytes
    assert fs.frame_no == 1

    decoded = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (60, 80, 3)


@pytest.fixture
def server():
    srv = VisionStreamServer(host="127.0.0.1", port=0)
    srv.start()
    yield srv
    srv.stop()


def test_snapshot_returns_503_before_any_frame_then_a_real_jpeg(server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(server.url + "snapshot.jpg", timeout=2)
    assert exc_info.value.code == 503

    server.stream.update(_fake_frame(fill=200))
    with urllib.request.urlopen(server.url + "snapshot.jpg", timeout=2) as r:
        assert r.status == 200
        assert r.headers["Content-Type"] == "image/jpeg"
        body = r.read()
    assert body[:2] == b"\xff\xd8"
    decoded = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (60, 80, 3)


def test_index_page_points_at_the_mjpeg_stream(server):
    with urllib.request.urlopen(server.url, timeout=2) as r:
        assert r.status == 200
        body = r.read()
    assert b"/stream.mjpg" in body


def test_mjpeg_stream_delivers_multiple_real_frames(server):
    for i in range(3):
        server.stream.update(_fake_frame(fill=10 + i))

    with urllib.request.urlopen(server.url + "stream.mjpg", timeout=2) as r:
        assert r.status == 200
        assert r.headers["Content-Type"].startswith("multipart/x-mixed-replace")

        chunks_seen = 0
        deadline = time.monotonic() + 3.0
        buf = b""
        while chunks_seen < 2 and time.monotonic() < deadline:
            # read1(), not read(): read() blocks trying to fill the whole
            # buffer, which a multipart stream sending small frames may
            # never do within one socket timeout window.
            buf += r.read1(4096)
            while b"\xff\xd8" in buf and b"\xff\xd9" in buf:
                start = buf.find(b"\xff\xd8")
                end = buf.find(b"\xff\xd9", start) + 2
                if end <= start + 2:
                    break
                jpeg = buf[start:end]
                decoded = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                assert decoded is not None
                assert decoded.shape == (60, 80, 3)
                chunks_seen += 1
                buf = buf[end:]
                server.stream.update(_fake_frame(fill=50 + chunks_seen))
        assert chunks_seen >= 2
