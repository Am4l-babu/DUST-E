# BRAIN

### The part of the trash bin that has opinions

The high-level brain of the DUST-E companion. It runs on the
**Arduino UNO Q's Linux side**: it sees, remembers, and decides. The ESP32 body
executes, and has the last word on anything that moves.

The full design, including why things are split this way, is in
[../docs/COMPANION_ARCHITECTURE.md](../docs/COMPANION_ARCHITECTURE.md).

**Status: phase 1 of 7.** Camera, detection, tracking and the world model. It
drives no motors, talks to no body and has no voice. It prints what the robot
would believe about the room.

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
`--show` draws the tracks in a window (needs a display), and
`--jsonl events.jsonl` keeps every event for later.

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
| `dustebrain/world/model.py` | People, identity across track breaks, zones, motion, objects, events, summaries. |
| `dustebrain/sim/scenario.py` | Deterministic scripted scenarios through the real geometry. |
| `dustebrain/apps/vision_node.py` | The phase-1 entry point. |
| `tests/` | One file per module; `test_world_model.py` is the phase-1 acceptance suite. |

Importing `dustebrain` does not import OpenCV. Only the camera, the detector
backends and `--show` do, so everything else runs on a machine with nothing
but numpy.

---

## 6. Verified how

- `python -m pytest`: 55 passed on Windows, Python 3.12, numpy 2.4 (no OpenCV
  installed, which is the point).
- Every `--sim` scenario produces the expected event sequence.
- With `opencv-python-headless` 5.0 in a clean virtualenv: the letterbox puts
  pixels exactly where the decoder expects, and a generated video replays
  through the camera thread and the full live loop (a colour-threshold
  stand-in for the model) to a clean exit.

**Not verified:** anything on a UNO Q, a real USB webcam, a real ONNX model
through `cv2.dnn` or onnxruntime, or detector speed on the A53 cores. The first
run on the board is a bring-up: run `--bench` before trusting `--snapshot`.
