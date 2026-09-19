# BRAIN

### The part of the trash bin that has opinions

The high-level brain of the DUST-E companion. It runs on the
**Arduino UNO Q's Linux side**: it sees, remembers, and decides. The ESP32 body
executes, and has the last word on anything that moves.

The full design, including why things are split this way, is in
[../docs/COMPANION_ARCHITECTURE.md](../docs/COMPANION_ARCHITECTURE.md).

**Status: phase 1 done, phase 2 nearly done.** Phase 1 is the camera,
detection, tracking and world model: it prints what the robot would believe
about the room. Phase 2 is the link to the XIAO ESP32-S3 body: the wire
protocol, the command validator, a Python reference implementation of the
body's reflex safety (section 7), `BodyLink` (section 8) - the real client -
and now the DRIVE + HW + DEBUG dashboard (section 9). `firmware/DustESensorNode/`
has been compiled and flashed on a real UNO Q (19 Sep 2026 - see its own
README section 5); `firmware/DustEBody/` still only builds, no XIAO has run
it yet. Nothing has driven a real motor.

```
USB camera ─► latest-frame grabber ─► detector (ONNX, ≤ 5 Hz) ─► torso signature
          ─► tracker ─► world model ─► events + LLM summary
```

---

## 1. What it tells you

```
[        0] VISION_ONLINE
[      400] PERSON_DETECTED      #1 4.8 m right FAR UNKNOWN
[     1200] PERSON_APPROACHING   #1 4.4 m right FAR APPROACHING
[     3600] PERSON_ZONE_CHANGED  #1 2.9 m ahead NOTICE APPROACHING previous=FAR
[     6200] PERSON_ZONE_CHANGED  #1 ~1.4 m ahead INTERACTION APPROACHING previous=APPROACH
[    11200] PERSON_WALKING_AWAY  #1 ~1.9 m ahead APPROACH WALKING_AWAY
[    13000] PERSON_LEAVING       #1 3.1 m ahead FAR WALKING_AWAY
[    17600] PERSON_LOST          #1 last_zone=FAR seen_for_s=14.6
```

`~` means the distance is an estimate the camera cannot vouch for (§4).

| Event | Meaning |
|---|---|
| `PERSON_DETECTED` | A new person, confirmed over several frames. One false-positive frame never gets greeted. |
| `PERSON_RETURNED` | Someone whose departure was announced is back: the "you again?" moment. |
| `PERSON_APPROACHING` / `PERSON_WALKING_AWAY` | Their own motion, with the robot's own motion subtracted once body telemetry exists. |
| `PERSON_LEAVING` | Walking away **and** beyond the notice zone. |
| `PERSON_LOST` | Out of view for `person_lost_s` (2.5 s). A detector blink is not a departure. |
| `PERSON_ZONE_CHANGED` | FAR / NOTICE / APPROACH / INTERACTION / TOO_CLOSE, with hysteresis. |
| `OBJECT_DETECTED` | A class not seen in the last 8 s. The same cup is news once. |
| `VISION_OFFLINE` | The camera went quiet. The summary then says *unknown*, never *nobody*. |

---

## 2. Run it

### Without any hardware (any PC with Python 3.10+)

```bash
cd brain
pip install numpy pyyaml pytest
python -m pytest                                   # 55 tests, no camera, no model
python -m dustebrain.apps.vision_node --sim walk_in  # a scripted person
```

Scenarios: `walk_in`, `flicker`, `returning`, `two_people_swap`,
`robot_drives_to_statue`, `person_with_cup`. Add `--realtime` to watch at real
speed, and `--snapshot 1` to print the LLM summary every second.

### On the UNO Q

```bash
sudo apt install python3-opencv python3-numpy python3-yaml python3-pytest
cd brain
python3 -m pytest
python3 -m dustebrain.apps.vision_node --bench 50      # acceptance: >= 3 Hz
python3 -m dustebrain.apps.vision_node --snapshot 2    # live
```

The camera goes through the **powered USB-C hub**: the UNO Q has one USB-C
port, and the camera, the ESP32 link and the microphone all need it.

Other flags: `--source clip.mp4` replays a recording at its own frame rate,
`--show` draws the tracks in a window (needs a display), `--serve 8081` does
the same drawing but serves it as an MJPEG stream any browser can open - the
one that matters on a headless UNO Q, where `--show` has no display to open -
and `--jsonl events.jsonl` keeps every event for later. `--show` and `--serve`
can run together; both draw from the same `_annotate()` call, so the bench
window and the browser tab show identical frames.

Verified against a real camera and a real HTTP client (19 Sep 2026, `--serve`
only - no UNO Q involved, a laptop webcam): `/` serves a page pointing at
`/stream.mjpg`, `/snapshot.jpg` returns a real, decodable JPEG matching the
camera's actual resolution, and `/stream.mjpg` delivers a live
multipart-replace stream. `brain/tests/test_vision_stream.py` covers the same
ground with synthetic frames, no camera required.

---

## 3. Detector model

Not committed: it is a binary, and its licence is its own. Export on a PC, not
on the board:

```bash
pip install ultralytics
yolo export model=yolov8n.pt format=onnx imgsz=320 opset=12 simplify=True
# copy yolov8n.onnx to brain/models/yolov8n-320.onnx
```

YOLOv8/YOLO11 (`[1, 84, N]`) and YOLOv5 (`[1, N, 85]`) output layouts are both
decoded. If you use a model with other classes, set `detector.labels` to its
class list in export order. The decoder refuses a label count that does not
match the tensor instead of guessing.

**Licence:** Ultralytics weights are AGPL-3.0. YOLOX-nano and NanoDet are
Apache-2.0 alternatives with the same box format, if that matters for you.

`detector.backend: none` runs the node with no detector at all. It then
reports no people, which in that configuration is the truth.

---

## 4. Calibration that actually matters

Distance comes from geometry, so these four numbers in `config/default.yaml`
(or your override file) decide whether "1.5 m" means 1.5 m:

| Key | How to get it |
|---|---|
| `camera.hfov_deg`, `camera.vfov_deg` | From the camera's datasheet, or measure: tape a 1 m ruler flat at a known distance and see how much of the frame it fills. |
| `geometry.camera_height_m` | Floor to lens, with the robot on its wheels. |
| `geometry.camera_pitch_deg` | Positive when tilted up. A phone inclinometer on the camera body is good enough. |

Then check: stand at 3 m with your feet in frame. The log should say ~3.0 m,
without a `~`.

**The honest limit.** A camera at bin height cannot see a whole standing
person up close. With the defaults (43° vertical FOV, 0.6 m, 5° up), feet leave
the frame at about 2 m. Closer than that, the estimate falls back to shoulder
width and is marked unreliable, but it is clamped to that 2 m bound. It can be
wrong, but not wrong in the direction that walks the robot into someone. A
wide-angle camera (VFOV ≥ 55°) moves the limit in. Collisions are the body's
range sensors' job, never the camera's.

---

## 5. Layout

| Path | Contents |
|---|---|
| `config/default.yaml` | Every threshold. The only place defaults live. |
| `dustebrain/config.py` | Loader: merges overrides, rejects unknown/missing keys, validates contradictions. |
| `dustebrain/events.py` | The event vocabulary for all phases. |
| `dustebrain/prng.py` | Bit-exact port of the firmware's xorshift32, so behaviour stays reproducible from a seed. |
| `dustebrain/vision/camera.py` | Latest-frame grabber thread, reconnect, file replay. |
| `dustebrain/vision/detector.py` | ONNX YOLO via `cv2.dnn` or onnxruntime; numpy decode + NMS. |
| `dustebrain/vision/appearance.py` | Torso colour histogram for short-term re-identification. RAM only. |
| `dustebrain/vision/tracker.py` | Association, track lifecycle, distance smoothing, radial velocity. |
| `dustebrain/vision/geometry.py` | Bearing, and ground/height/width distance with honest bounds. |
| `dustebrain/vision/stream.py` | `VisionStreamServer` - MJPEG-over-HTTP, viewable in a plain browser `<img>` tag. For a headless UNO Q, where `--show`'s local OpenCV window has no display to open. |
| `dustebrain/world/model.py` | People, identity across track breaks, zones, motion, objects, events, summaries. |
| `dustebrain/sim/scenario.py` | Deterministic scripted scenarios through the real geometry. |
| `dustebrain/apps/vision_node.py` | The phase-1 entry point. |
| `dustebrain/body/protocol.py` | Brain-to-body wire format: JSON lines, CRC-16, sequence numbers, a reader that survives boot-log noise. |
| `dustebrain/body/validator.py` | Source policy (the LLM cannot ask for a wheel speed), range clamps, rate limits, lower-only ceilings. |
| `dustebrain/body/simbody.py` | The body's reflex safety in Python: the reference the XIAO firmware is written against. |
| `dustebrain/body/link.py` | `BodyLink` - the real client: validate, frame, write; read, decode, update state. `SerialTransport` (pyserial) for the real port, `LoopbackPipe` for testing with no board. |
| `dustebrain/apps/body_probe.py` | Bring-up CLI: `--drive L R`, `--estop`, `--reset-estop`, a live status line. See firmware/DustEBody/README.md section 6. |
| `tests/` | One file per module; `test_world_model.py` is the phase-1 acceptance suite. |

Importing `dustebrain` does not import OpenCV. Only the camera, the detector
backends and `--show` do, so everything else runs on a machine with nothing
but numpy.

---

## 6. Verified how

- `python -m pytest`: 106 passed on Windows, Python 3.12, numpy 2.4 (no OpenCV
  installed, which is the point).
- Every `--sim` scenario produces the expected event sequence.
- With `opencv-python-headless` 5.0 in a clean virtualenv: the letterbox puts
  pixels exactly where the decoder expects, and a generated video replays
  through the camera thread and the full live loop (a colour-threshold
  stand-in for the model) to a clean exit.

**Not verified:** anything on a UNO Q, a real USB webcam, a real ONNX model
through `cv2.dnn` or onnxruntime, or detector speed on the A53 cores. The first
run on the board is a bring-up: run `--bench` before trusting `--snapshot`.


---

## 7. Phase 2: the body link

The XIAO is the only thing that can energise a motor, so its rules are the ones
that matter. They are written here first, in Python, so the failsafe matrix can
be tested before a wire is soldered - and so the firmware has an exact
specification instead of a paragraph of prose.

**The wire format** is one JSON object per line with a CRC:

```
{"v":1,"seq":1042,"t":583211,"type":"vel","l":35,"r":31,"ttl":300}*7A3F
```

Readable in a serial monitor on purpose: when the robot misbehaves at a demo,
the diagnosis has to be visible in a terminal. The CRC is there because the USB
line shares a chassis with motor wiring. A corrupted line is dropped and
counted, never guessed at, and the reader skips the ESP32 boot log without
complaining.

**The validator** is the box between everything clever and everything physical:

| Rule | Why |
|---|---|
| `vel` from `src: "llm"` is refused | The model may ask to look at someone; it may not ask for a wheel speed. Enforced in code, not in a prompt. |
| `reset_estop` only from `src: "manual"` | Clearing an emergency stop is a human decision. |
| `estop` from anyone, never rate limited | Stopping is always allowed. |
| Autonomous speed capped below manual | 45 % against 70 % by default. |
| `limits` may only **lower** a ceiling | No message in this protocol raises one. |

**The reflex safety** (`simbody.py`), in the order the body applies it:
E-stop latch, battery critical, link timeout, command TTL, MOTION_OK veto,
then ceiling and ramp. The MOTION_OK veto is worth spelling out: the UNO Q MCU
toggles one wire while its sensors see no hazard, and the body requires *edges*,
not a level. A wall, a cliff, a bumper, a crashed MCU, a hung loop and a broken
wire all produce the same thing - no pulses - and are all handled the same way:
forward motion blocked, a short slow reverse allowed to escape, then a cooldown
so escaping cannot become a habit.

`tests/test_simbody.py` is the failsafe matrix from
[the architecture doc](../docs/COMPANION_ARCHITECTURE.md) section 8.1, as tests.
When the firmware exists, the same scenarios get pointed at the real board: if
the firmware disagrees with any of them, the firmware is wrong.

**Not verified:** no serial port, no XIAO, no motor has been involved. This is
a specification with tests, not a driver.

---

## 8. Phase 2b: the real client

`BodyLink` is what `simbody.py` was written to be tested against - the actual
brain-side object that will talk to a real board:

```python
from dustebrain.config import load_config
from dustebrain.body.link import BodyLink, SerialTransport

cfg = load_config()
link = BodyLink(SerialTransport("/dev/ttyACM0"), cfg.body)

while True:
    t = ...                       # milliseconds, monotonic
    link.tick(t)                  # sends its own hello/heartbeats, drains the port
    if link.state.handshaken:
        link.velocity(30, 30, t, src="nav")
```

Every outbound call goes through the same `Validator` the tests exercise -
`link.send(P.VEL, src="llm", ...)` is refused locally, before a byte reaches
the wire, exactly as `test_validator.py` says it must be. `BodyState` tracks
what the brain currently believes: the handshake, the hardware inventory the
body reported, the last telemetry, and - the part worth reading twice -
`online()`, which answers "is this still trustworthy" rather than "did it ever
say hello". A body that stops sending telemetry stops being online, even if
the last thing it reported was perfectly healthy.

**`LoopbackPipe`** is the reason `test_body_link.py` can prove all of this
without a port: it is a real in-memory duplex pipe, wired directly to a real
`SimBody`. Nothing in that test file is mocked - `Validator`, `Framer`,
`protocol.encode`, the bytes, `protocol.decode`, `SimBody.handle()`, the reply
bytes, back through `protocol.decode`, into `BodyState` - the entire stack
runs for real, twice per message.

**`python -m dustebrain.apps.body_probe`** is the tool for the bring-up
procedure in `firmware/DustEBody/README.md` section 6: watch the handshake,
watch telemetry, and - **wheels off the ground** - send a short drive pulse,
an E-stop, or a reset. It does nothing `BodyLink` itself cannot do; it is a
terminal wrapped around the same calls.

**Not verified:** no real serial port, no real XIAO, has been involved. A bad
port name (`body_probe --port COM255`) does fail cleanly with a clear error
and exit code 2, which is the one thing that was checked against reality.

---

## 9. Phase 2: the dashboard

`dustebrain.dashboard.DashboardServer` is the DRIVE + HW + DEBUG web
dashboard the Phase 2 acceptance check names. It is a thin HTTP wrapper
around `BodyLink` - stdlib `http.server`, no new dependency, no WebSocket:
the page polls `/api/status` every 150 ms and, while a drive button is held,
resends `/api/drive` every 100 ms so the command never runs out its TTL
mid-press. Every command it sends is `src="manual"`, through the same
`Validator` as `body_probe.py` - this page can do nothing the CLI could not
already do, and the XIAO's reflex layer still has the final say regardless of
what either one asks for.

```
python -m dustebrain.apps.dashboard --sim          # no hardware - drives an in-process SimBody
python -m dustebrain.apps.dashboard --port COM5    # a real body
```

`brain/tests/test_dashboard.py` is a real integration test: real HTTP
requests, over a real socket, against a real `DashboardServer` wired to a
real `SimBody` the same way `--sim` runs it - nothing mocked, same discipline
as `test_body_link.py`. It is also what found a real, pre-existing gap: see
`docs/COMPANION_ARCHITECTURE.md` section 9.2's note on `manual_max_pct` never
actually being reachable as a ceiling, in either `simbody.py` or the real
firmware.

**Not verified:** no browser has opened the page, and no real XIAO has driven
the DRIVE tab. `--sim` mode and the automated test are what exist instead.
