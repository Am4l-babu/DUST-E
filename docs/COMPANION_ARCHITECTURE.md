# COMPANION ARCHITECTURE

### Evolving the DUST-E into an autonomous companion without losing the plot

This document is the analysis and plan that comes before the code. It answers,
in order: what exists, what can be reused, what conflicts, what is missing,
and how the brain (Arduino UNO Q) and the body (ESP32) are split. Nothing in
the firmware or the pin maps has been changed by this document. Every change
it proposes is marked **PROPOSED** and needs a decision first.

The priority order is unchanged from the root README:

```
SAFETY → RELIABILITY → PHYSICAL COMEDY → MECHANICAL QUALITY
       → DEMO SPEED → VISUAL APPEAL → TECHNICAL COMPLEXITY
```

---

## 1. What is actually in the repository

The brief describes one robot. The repository contains **four separate
machines**, and the brief's feature list is a union of them. That is the single
most important finding. It is the root of every hardware conflict in §6.

| Machine | Path | Controller | Status in this repo |
|---|---|---|---|
| **DUST-E** | `firmware/DustE/` + `firmware/DustERemote/` | ESP32-S3 (+ ESP32-C3 remote) | Complete modular firmware. **Never compiled** (root README says so). Stationary: no motors. |
| **DustEWeb** | `firmware/DustEWeb/` (+ `DustECam/`) | Classic ESP32 (WROOM) | Builds clean under PlatformIO. **Never run on hardware.** Mobile: L298N + 2 DC motors, nothing else. |
| **UselessBox (UNO Q)** | `firmware/UselessBox/UselessBox_UnoQ/` | Arduino UNO Q (STM32U585 MCU side) | Newest file in the repo (2026-09-12). L298N, 3× HC-SR04, IR, buzzer, servo, switch, SSD1306. Uses blocking `delay()`. |
| Bench tests | `tests/l298n_motor_test/`, `tests/obstacle_avoid_test/` | Arduino UNO Q | Rewritten from ESP32 to UNO Q. L298N on **D5–D10**. |

Where each feature in the brief lives:

| Brief says the robot has | Where it actually exists |
|---|---|
| ESP32 control | DUST-E (**S3**) and DustEWeb (**classic**). These are different chips with incompatible pin maps. |
| L298N + two geared DC motors | DustEWeb (ESP32 GPIO 18/19/27/26/25/33) **and** UNO Q sketches (D5–D10). The UNO Q wiring is newer. |
| Servo eyeball | DUST-E `eye.*`: pan GPIO 5, tilt GPIO 6, eased, auto-detach |
| OLED face | DUST-E `display.*` (I²C 8/9) and UselessBox_UnoQ (`Wire2`, custom SSD1306 driver) |
| ToF proximity | DUST-E: 2× VL53L0X, **throat** (looks down into the bin) and **approach** (looks into the room) |
| Servo lid | DUST-E `lid.*`: MG996R, soft-close, limit switches, obstruction reversal |
| Mechanical finger | DUST-E `uselessFinger.*` (GPIO 7 + hatch GPIO 15); UselessBox (servo D11, switch D12) |
| WS2812B | DUST-E `leds.*`, GPIO 16 |
| MAX98357A + speaker | DUST-E `audio.*`: I²S 17/18/21, non-blocking WAV streaming from LittleFS |
| Personality engine | **Two different engines** (see §1.1) |
| Browser dashboard | DustEWeb only (`data/`: DRIVE, MIND, AUDIO, VISION, HW, SETUP tabs) |
| Browser-side computer vision | DustEWeb `data/vision.js`: COCO-SSD on TensorFlow.js, results sent to the ESP32 |
| ESP-NOW | DUST-E ↔ DustERemote |
| Safety layer | DUST-E: lid safety (hand detection, limit switches, servo power FET). DustEWeb: motor safety (latched E-stop, link/drive timeouts, ramp, duty ceiling). |
| Deliberate mistranslation | Both engines, with different weight tables |
| *(not in brief)* HC-SR04 ×3, IR, active buzzer | UselessBox_UnoQ |
| Microphone | **Nowhere** |
| Battery measurement | **Nowhere** (DustEWeb reports `NOT INSTRUMENTED` on purpose) |
| Wheel encoders, IMU, cliff sensors, bumpers | **Nowhere** |
| Camera | Optional ESP32-CAM snapshot server (`DustECam/`); phone camera |

### 1.1 The two personality engines

| | DUST-E `personality.*` | DustEWeb `personality.*` |
|---|---|---|
| State | 13 `PersonalityState`: IDLE, CURIOUS, ALERT, HAPPY, CONFUSED, ANGRY, SHY, SARCASTIC, SLEEPING, AI MODE, NORMAL MODE, USELESS MODE, ERROR | 9 `Mood`: NORMAL, HAPPY, BORED, CONFUSED, ANGRY, REBELLIOUS, SLEEPING, CHAOS, PANIC |
| Numbers | `anger` 0–100, `frustration` 0–12, interaction counters | 7 traits 0–100: anger, trust, happiness, confusion, boredom, obedience, rebellion (derived) |
| Policy axis | none | 9 `DriveMode`s selected by the user (NORMAL is a genuine debug mode) |
| Randomness | seeded xorshift32 | seeded xorshift32 (`core/prng.h`) |
| Owns hardware | no | no |

The brief's trait list comes from DustEWeb, and its mood list from DUST-E.
The companion needs **one** engine, so §15 proposes how to unify them.

---

## 2. Architecture map of what exists

```
DUST-E (ESP32-S3)                         DustEWeb (ESP32)
─────────────────────                       ────────────────────────────
loop(): sensors → lid → eye → finger        loop(): inbound queue → pipeline
        → leds → audio → display                    (validate → SAFETY → personality
        → remote → personality → behavior           → transform → delay) → personality tick
                                                    → vision tick → SAFETY.enforce
behaviorManager = the only module that              → motors.tick → sounds → telemetry
commands hardware (single audit point)
                                            webLayer (AsyncTCP) / bleLink / usbLink:
lid safety is local to lid.cpp:             validate + push to spinlocked ring only;
the behaviour layer is informed,            E-stop latches in the network task
not consulted

No delay() after setup() in either.         No delay() after setup() in either.
```

Both firmwares follow the same three rules the companion must keep:

1. **Safety is structurally upstream of personality.** It is not just a
   higher-priority `if`. The personality code has no path back into it.
2. **Nothing blocks.** Every actuator is a `millis()` state machine.
3. **It degrades instead of failing.** A dead sensor sets a flag, a missing clip
   is silent, and a lost link stops the motors.

---

## 3. Reuse: modules that carry over unchanged

| Module | From | Role in the companion |
|---|---|---|
| `hardware/eye.*` | DUST-E | Body. `lookNormalized(x, y)` is exactly the `LOOK_AT` primitive. |
| `hardware/lid.*` | DUST-E | Body. The safety logic is kept verbatim. |
| `hardware/uselessFinger.*` | DUST-E | Body. The NORMAL MODE gag survives (§15.4). |
| `hardware/leds.*` | DUST-E | Body. The pattern enum becomes the `LED_SET` vocabulary. |
| `hardware/audio.*` | DUST-E | Body. Prerecorded clips are the offline voice (§14). |
| `ui/display.*` | DUST-E | Body. `FaceExpression` + `say()` become `FACE_SET`. |
| `hardware/sensors.*` (`DebouncedInput`, ToF health) | DUST-E | Body. Extended with new range sensors. |
| `motor/motors.*` | DustEWeb | Body. Ramp, duty ceiling, min duty, trim, NVS calibration. |
| `safety/safety.*` | DustEWeb | Body. Latch + timeouts. The link becomes the UNO Q instead of a browser. |
| `core/prng.h`, `core/eventLog.*` | DustEWeb | Both sides. The Python port of xorshift32 matches bit for bit (`brain/dustebrain/prng.py`). |
| `data/` dashboard (HTML/CSS/JS, tab layout, style) | DustEWeb | Brain. Served from the UNO Q with new COMPANION and DEBUG tabs. |
| Event-log discipline (every decision logged with a reason) | Both | Both. |
| `tools/verify_project.py` | root | Extended to check the new pin map and protocol copies. |

## 4. Modules that must be modified

| Module | Change | Why |
|---|---|---|
| `personality.*` (both) | Unified, extended with `curiosity` and `social_energy`, moved to the brain (§15) | Its inputs (vision, speech, games) now originate on the UNO Q |
| DustEWeb `pipeline.*` | Mistranslation applies **only to human-issued manual commands**, never to navigation output | A mistranslated obstacle-avoidance turn is a collision, not a joke |
| DustEWeb `safety.*` | "Client" = the UNO Q link; adds obstacle, cliff, bumper, battery and physical E-stop inhibits; autonomous vs manual speed ceilings | Autonomy needs sensor-based inhibits, not only link-based ones |
| DUST-E `behaviorManager.*` | Split: hardware choreography stays on the body as named **gestures**; decisions move to the brain | The brief: "the ESP32 should not make high-level AI decisions" |
| DUST-E `pins.h` | Needs motor, bumper, battery and E-stop pins (§6.2) | The S3 map has one free GPIO left |
| DUST-E `remote.*` / DustERemote | Kept. On the mobile robot, remote **STOP always stops the motors** (it may still speed up the *eye*) | DustEWeb precedent: "It would not stop is not a joke, it is a fault report" |
| DustEWeb `vision.*` | Replaced on the body by the brain's world model; the phone/TF.js path stays as an optional input | The UNO Q camera is now the primary vision sensor |
| UselessBox_UnoQ | Not part of the companion. It stays as its own gadget; its `delay()`-based motion must never be copied into the body | Blocking delays |

## 5. New modules

**Brain (UNO Q, Linux, Python): `brain/`**

| Package | Responsibility | Phase |
|---|---|---|
| `dustebrain.vision` | camera grabber, detector, appearance signature, tracker, geometry | 1 |
| `dustebrain.world` | world model, person lifecycle, social zones, events, LLM summary | 1 |
| `dustebrain.sim` | deterministic synthetic scenarios (tests + DEBUG "simulate a person") | 1 |
| `dustebrain.body` | serial link, command validator, safety governor, telemetry | 2 |
| `dustebrain.nav` | navigation state machine, reactive avoidance, person approach, docking | 3 |
| `dustebrain.voice` | wake phrase, VAD, STT, TTS, audio routing, half-duplex policy | 4 |
| `dustebrain.mind.llm` | `LLMProvider` → `CloudLLM`, `LocalLLM`, `OfflineFallback` | 5 |
| `dustebrain.mind.conversation` | turn manager, output contract validation, memory | 5 |
| `dustebrain.mind.personality` | unified deterministic engine | 5 |
| `dustebrain.mind.social` | social decision system, cooldowns, target selection | 6 |
| `dustebrain.mind.games`, `.stories` | deterministic game/story engines (no LLM required) | 6 |
| `dustebrain.expression` | Emotion → PhysicalExpression mapping | 6–7 |
| `dustebrain.dashboard` | HTTP + WebSocket server, COMPANION and DEBUG tabs | 2 → 7 |

**Body (ESP32-S3): `firmware/BinBody/`**, assembled from the reused drivers
above plus:

| Module | Responsibility |
|---|---|
| `link/brainLink.*` | framed serial protocol, CRC, seq/ack, heartbeat |
| `motion/motion.*` | velocity commands with TTL, named motion primitives |
| `safety/reflex.*` | obstacle, cliff and bumper stops, E-stop input, battery cutoff. **Runs before `motion`.** |
| `gesture/gestures.*` | named servo choreographies (e.g. `NOD`, `SHAKE`, `EYE_WAVE`) with calibrated, clamped angles |
| `sensors/range.*` | front range array and cliff sensors |

---

## 6. Hardware conflicts

### 6.1 Conflicts that exist today

| # | Conflict | Consequence |
|---|---|---|
| C1 | **Two ESP32 families.** DUST-E uses GPIO 38/47/48, which do not exist on a classic ESP32. DustEWeb uses GPIO 25/26/27/33, which are SPI flash or PSRAM on an S3. | The two pin maps cannot be merged onto either chip as they stand. |
| C2 | **The L298N is documented in two places.** DustEWeb cites `tests/l298n_motor_test` as proof of its ESP32 wiring, but that test has since been rewritten for the UNO Q on D5–D10. | The repo does not say where the driver is physically wired today. |
| C3 | **The DUST-E S3 map is full.** Of the always-safe set (1, 2, 4–18, 21, 38, 47, 48), only GPIO 1 is free. The companion needs 6 motor pins plus bumpers, battery sense and an E-stop input. | Motors cannot be added without freeing pins or adding an expander. |
| C4 | **Audio is on the body; the voice is generated on the brain.** The MAX98357A hangs off the ESP32's I²S, but TTS runs on Linux. | Needs PCM streaming over the link, or a second audio output (§13). |
| C5 | **The UNO Q has one USB-C port.** Camera, microphone and ESP32 link all need USB. | A powered USB-C hub with PD pass-through is mandatory. |
| C6 | **HC-SR04 echo is 5 V; the UNO Q MCU and the ESP32 are 3.3 V.** `obstacle_avoid_test` already warns about this. | A divider or level shifter on every echo line. |
| C7 | **UNO Q `analogWrite()` misbehaves above ~4 PWM pins** (noted in `l298n_motor_test`). | Another reason not to keep motors plus servos on the UNO Q MCU. |
| C8 | **The "approach" VL53L0X is a single narrow cone** tuned for "person within 900 mm" at a stationary bin. | Not enough obstacle coverage for a moving base. |
| C9 | **DUST-E remote STOP is deliberately mistranslated** (it speeds things up). | Must never apply to wheels. |
| C10 | **Motor noise vs. microphone; motor current vs. the UNO Q supply.** | Listening while driving is unreliable; brownouts can reboot the brain mid-drive (the DustEWeb README already warns about this for the ESP32). |

### 6.2 PROPOSED body pin map (ESP32-S3) — not applied, needs a decision

**Principle: one safety authority.** Every actuator, and every sensor that can
stop an actuator, is on the ESP32. The UNO Q MCU drives nothing on the robot.
The existing UNO Q wiring (L298N on D5–D10, HC-SR04s) would move to the ESP32.
That is a pin change, so it is listed here and not done.

**Option A (recommended): add a PCA9685 servo driver.** It moves the 5 servos
to I²C and frees GPIO 4/5/6/7/15. Every other DUST-E pin stays where it is.

| GPIO | Today (DUST-E) | Proposed |
|---:|---|---|
| 2, 8, 9, 10–14, 16, 17, 18, 21, 38, 47, 48 | as `pins.h` | **unchanged** |
| 4 | SERVO_LID | MOTOR_ENA (PWM) → servo moves to PCA9685 ch 0 |
| 5 | SERVO_EYE_PAN | MOTOR_ENB (PWM) → PCA9685 ch 1 |
| 6 | SERVO_EYE_TILT | BUMPER_LEFT (NC to GND: a broken wire reads "hit") → PCA9685 ch 2 |
| 7 | SERVO_FINGER | BUMPER_RIGHT (NC to GND) → PCA9685 ch 3 |
| 15 | SERVO_FINGER_DOOR | ESTOP_SENSE (aux NC contact of the mushroom switch) → PCA9685 ch 4 |
| 1 | free | BATTERY_ADC (ADC1_CH0, divider sized for the pack) |
| 39, 40, 41, 42 | JTAG (unused: the S3's USB-Serial-JTAG is on 19/20) | MOTOR_IN1..IN4 |
| 43, 44 | UART0 (free when logging on native USB CDC) | I2C1 SDA/SCL, a **dedicated motion-safety bus** (range, cliff, MCP23017 XSHUT expander) so OLED frame flushes can never delay an obstacle read |

**Option B: no new servo driver.** L298N on 1/39/40/41/42 plus one of 43/44.
That leaves no pins for bumpers, battery or E-stop sense without an expander
anyway, which is why A is recommended.

**The hardware E-stop is not a GPIO.** A latching mushroom switch in series
with the L298N motor supply cuts motion even if both computers are dead. Its
auxiliary contact tells the ESP32 so the firmware can latch and report it.

---

## 7. Missing hardware

Only what the architecture actually needs, in the order it becomes necessary.

| Needed for | Part | Why it cannot be skipped |
|---|---|---|
| Phase 1 | USB webcam, wide FOV (≈ 70–100°), MJPEG | Primary vision sensor |
| Phase 1 | Powered USB-C hub with PD pass-through | C5 |
| Phase 2 | Physical E-stop (latching, in the motor supply) | §6.2; firmware-only E-stop is not enough for a moving robot |
| Phase 2 | Separate 5 V ≥ 3 A buck for the UNO Q + hub, star ground | C10 |
| Phase 2 | Battery voltage divider → ESP32 ADC | `BATTERY_LOW` and the low-battery stop cannot be faked |
| Phase 3 (**before any autonomous roaming**) | 2× downward cliff sensors (VL53L0X or IR) | Stairs and table edges. Autonomy is **disabled in config** until `cliff_sensors: true`. |
| Phase 3 | Front bumper microswitches ×2 | Last-resort contact sensing that no software bug can mis-range |
| Phase 3 | 3 forward range sensors (VL53L1X preferred; the existing HC-SR04 ×3 work with level shifting) | C8 |
| Phase 3 | Wheel encoders + IMU (e.g. BNO055) | Turning by angle instead of by time, stall detection, dead reckoning for `RETURN_HOME` |
| Phase 3 | Printed AprilTag on the home base | Camera docking without SLAM |
| Phase 4 | USB microphone. A USB mic **array** (e.g. ReSpeaker class) is preferred. | There is no microphone. An array also gives speech direction for §27. |
| Phase 4 (option) | USB audio adapter + small amp | Only if PCM streaming to the MAX98357A (§13) proves unreliable |
| Later (optional) | 2D LiDAR (LD06 class) | Phase 4 mapping only. Not needed before then. |
| Optional | TB6612FNG / DRV8871 instead of the L298N | The L298N drops ~2 V and runs hot. It works, so it stays unless it limits speed control. |

---

## 8. Brain ↔ Body architecture

```
┌──────────────────────── UNO Q  (Linux, "brain") ─────────────────────────┐
│                                                                          │
│  vision ──► world model ──► social / nav planner ◄── mind (personality,  │
│   (proc)       (events)            │                  conversation, LLM, │
│                                    │                  games, memory)     │
│  voice (wake · VAD · STT · TTS) ───┤                        ▲            │
│                                    ▼                        │            │
│                           intent (structured JSON)          │            │
│                                    ▼                        │            │
│                         COMMAND VALIDATOR  (schema, enums, ranges, rate) │
│                                    ▼                                     │
│                         SAFETY GOVERNOR  (soft: social distance, speed   │
│                                    │      near people, follow limits,    │
│                                    │      autonomy enable, geofence)     │
│                                    ▼                                     │
│                         MOTION CONTROLLER (velocity + TTL, gestures)     │
│                                    │                                     │
│  dashboard (HTTP/WS) ──────────────┘ debug commands enter ABOVE the      │
│                                      validator, never below it           │
└────────────────────────────────────┬─────────────────────────────────────┘
                                     │ USB CDC, framed, CRC, seq/ack, heartbeat
┌────────────────────────────────────▼──────── ESP32-S3  ("body") ──────────┐
│  brainLink ─► REFLEX SAFETY (hard: E-stop latch, link timeout, cmd TTL,   │
│               obstacle/cliff/bumper stop, battery cutoff, speed & accel   │
│               ceilings) ─► motion ─► motors (ramp, clamp) ─► L298N        │
│  gestures ─► eye / lid (own hand-safety) / finger / leds / display / audio│
│  telemetry ─► brainLink                                                   │
└───────────────────────────────────────────────────────────────────────────┘
```

**Two safety layers with different jobs.** The **governor** on the brain is
*social* safety: don't crowd people, slow down near them, stop following. It
can be wrong without anyone getting hurt. The **reflex** on the body is
*physical* safety: don't hit, don't fall, don't run away. Nothing the brain
sends can disable it. Its limits are compile-time ceilings plus NVS
calibration, and the link can only **lower** them.

### 8.1 Failsafe matrix

| Failure | Detected by | Result |
|---|---|---|
| UNO Q stops sending | ESP32: no heartbeat for `LINK_TIMEOUT_MS` (300 ms) | Motors hard stop; face shows `BRAIN LOST`; servos park; audio stops |
| UNO Q process crash / reboot | same | same. The ESP32 keeps running and waits for a fresh handshake before any motion. |
| Velocity command not refreshed | ESP32: command TTL (≤ 500 ms, capped on the body) | Target ramps to zero |
| ESP32 disconnects / resets | Brain: no telemetry for 300 ms | `body.available = false`; nav → `EMERGENCY_STOP`; the robot says *"I appear to have lost my legs."* |
| ESP32 boots | — | Motors stopped, servo rail off, autonomy disabled until the handshake + self-test pass |
| E-stop pressed (hardware) | power removed from the motors + ESP32 sense input | Latched; cleared only by the physical reset **and** an explicit `reset_estop` from the dashboard |
| LLM / STT / TTS / network down | Brain health monitor | `OfflineFallback` (§14). Motion safety is unaffected. |
| Camera down | Vision: no frame for 2 s | `vision.online = false`; the world model reports **unknown**, not "nobody"; autonomous approach disabled |
| Battery low / critical | ESP32 ADC | Low: brain → `RETURNING_HOME`. Critical: body refuses motion. |

---

## 9. Communication protocol (brain ↔ body)

**Transport:** USB CDC (ESP32-S3 native USB) through the powered hub,
`/dev/ttyACM*` on the UNO Q. One JSON object per line with a CRC suffix, so it
stays readable in a serial monitor, like DustEWeb's USB link:

```
{"v":1,"seq":1042,"t":583211,"type":"vel","l":35,"r":31,"ttl":300,"src":"nav"}*7A3F\n
```

`*XXXX` is CRC-16/CCITT-FALSE over the bytes between `{` and `}` inclusive.
Lines with a bad CRC are dropped and counted; they are never guessed at.

### 9.1 Envelope (every message)

| Field | Meaning |
|---|---|
| `v` | protocol version; a mismatch in `hello` refuses all motion |
| `seq` | per-sender monotonic u32 |
| `t` | sender's monotonic ms (latency and clock-skew diagnostics) |
| `type` | message type |
| `ack` | `true` = the receiver must reply with an `ack` |
| `src` | brain-side origin: `nav`, `social`, `llm`, `debug`, `manual`, `safety`. The body logs it; the brain's validator uses it for policy (e.g. `llm` may not send `vel`). |

### 9.2 Brain → body

| `type` | Payload | Body behaviour |
|---|---|---|
| `hello` | `v`, `brain_version` | Handshake; body replies `hello` with its limits and hardware inventory |
| `hb` | — | Heartbeat, every 100 ms |
| `vel` | `l`,`r` −100..100 (% of the *current* ceiling), `ttl` ms | Differential drive; TTL clamped to 500 |
| `motion` | `cmd`: `STOP` `MOVE_FORWARD` `MOVE_BACKWARD` `TURN_LEFT` `TURN_RIGHT` `ROTATE`; `speed` %; `ms` ≤ 1500 | Timed primitive, still subject to reflex |
| `stop` | — | Ramp to zero now |
| `estop` | `reason` | Latch. Always accepted from any `src`. |
| `reset_estop` | `confirm` token from dashboard | Accepted only with `src:"manual"`, motors at zero, and the hardware E-stop released |
| `limits` | `auto_max`, `manual_max`, `accel` | May only **lower** the NVS ceilings |
| `look` | `x` −1..1, `y` −1..1, `ms` | `eye.lookNormalized`, clamped to `EYE_PAN_MIN/MAX` |
| `gesture` | `name` (`NOD`, `SHAKE`, `EYE_WAVE`, `SQUINT`, `TILT`, `JITTER`, `SLEEP`, `WAKE`) | Named choreography. **No raw servo angles over the link.** |
| `lid` | `OPEN` / `CLOSE` / `PEEK` + speed enum | Goes through `lid.cpp` hand safety |
| `face` | `expr` enum, optional `l1..l3` text, `ms` | `display` |
| `leds` | `pattern` enum, `ms` | `leds.set` / `leds.flash` |
| `clip` | clip id | Prerecorded WAV from LittleFS |
| `pcm` | `id`, `n` (chunk index), `last`, base64 16 kHz mono s16le, 40 ms | Streamed TTS into an I²S ring buffer; `pcm_stop` flushes immediately |

### 9.3 Body → brain

| `type` | Payload |
|---|---|
| `telemetry` (20 Hz) | `ml`,`mr` actual %, `tl`,`tr` target %, `range` `{fl,fc,fr}` mm or `null`, `cliff` `{l,r}` bool or `null`, `bump` `{l,r}`, `throat` mm, `approach` mm, `estop`, `estop_reason`, `inhibit`, `lid`, `audio` `{playing, buffer_ms}`, `battery_mv` (or `null` when not fitted), `link` `{crc_err, seq_gaps}`, `uptime` |
| `ack` | `seq` of the acknowledged command, `ok`, `err` |
| `event` | `code` (`BUMPER_HIT`, `CLIFF`, `OBSTACLE_STOP`, `LID_BLOCKED`, `ESTOP`, `BROWNOUT_RESET`, `NORMAL_SWITCH_ON`, `REMOTE_CMD` …), `text` |
| `hello` | `fw`, `v`, ceilings, `hw` inventory (same honesty rules as DustEWeb: `configured` vs `online` vs `not_installed`) |

### 9.4 Error codes

`E_CRC`, `E_VERSION`, `E_SCHEMA`, `E_RANGE`, `E_ESTOP_LATCHED`, `E_INHIBITED`
(with `inhibit` reason), `E_NOT_INSTALLED`, `E_BUSY`, `E_RATE`, `E_SRC_FORBIDDEN`.

---

## 10. AI software stack (UNO Q)

The UNO Q's Linux side is a quad Cortex-A53. It is roughly low-end
single-board-computer class, and every choice below starts from that. The
numbers are **planning assumptions to be benchmarked in each phase**, not
measurements. Nothing here has been run on a UNO Q yet.

| Layer | Choice | Reason | Fallback |
|---|---|---|---|
| Runtime | Python 3 processes under `systemd`, one process per heavy subsystem | A crashing STT must not take navigation with it | — |
| Inter-process bus | ZeroMQ PUB/SUB + msgpack (Phase 2+) | Brokerless, small, and process isolation for free | in-process queue (Phase 1) |
| Vision | OpenCV capture + ONNX detector (§12) | Runs on CPU with no vendor SDK | `NullDetector`: vision reports offline |
| Wake phrase | Vosk with a grammar-restricted phrase list | Configurable phrase, **no training**, cheap | openWakeWord custom model (Phase 7) |
| VAD | Silero VAD (ONNX) | Robust in noisy rooms | WebRTC VAD |
| STT | Vosk small model for commands/games (grammar mode); whisper.cpp `tiny.en`/`base.en` for free speech ≤ 8 s | Grammar mode is very accurate for "rock / paper / scissors" | commands-only grammar |
| LLM | `LLMProvider` → `CloudLLM` (default when online), `LocalLLM` (llama.cpp, ≤ 1.5 B, 4-bit), `OfflineFallback` | Cloud is fast; a local model on 4× A53 is a slow, reduced brain; offline must still be funny | template engine |
| TTS | Piper (ONNX voice) + a fixed pitch/formant effect to make it sound like a bin | Short-sentence latency is acceptable on CPU | espeak-ng → prerecorded clips |
| Games / stories | Deterministic Python engines; the LLM only *decorates* lines when available | Games must work offline and be fair | — |
| Memory | SQLite (episodic + opt-in long-term), RAM ring (short-term) | One file, no server | — |
| Dashboard | aiohttp/FastAPI + WebSocket, reusing DustEWeb's `data/` look | Existing UI philosophy | — |

**Compute governor.** Four A53 cores cannot run detection, STT and an LLM at
full rate at once, so the brain schedules them by state:

| Robot state | Vision rate | Audio | LLM |
|---|---|---|---|
| ROAMING | 4–5 Hz | wake phrase only | idle |
| APPROACHING | 5 Hz | wake phrase only | idle |
| INTERACTION: listening | 1–2 Hz | VAD + STT | idle |
| INTERACTION: thinking | 1 Hz | wake phrase only (barge-in) | active |
| INTERACTION: speaking | 2 Hz | mic gated (half-duplex) | idle |

The robot **does not drive while listening** (C10). It stands still, looks at
the person and listens, which reads as attention rather than as a limitation.

---

## 11. Navigation architecture

### 11.1 Navigation state machine (brain)

```
               ┌──────────── EMERGENCY_STOP ◄── any: estop / body lost / fault
               │
BOOT ─► DOCKED ─► IDLE ─► CURIOUS ─► ROAMING ◄──────────────────────────┐
                    ▲                  │  │                             │
                    │                  │  └─► OBSTACLE ─► AVOIDING ──────┤
                    │                  ▼                                │
                    │          PERSON_DETECTED ─► APPROACHING ─► INTERACTION ─► GOODBYE
                    │                  │              │                 │
                    │                  │              └─► (person avoids) ─► GIVE_UP ─┘
                    │                  ▼
                    │              SEARCHING ─► LOST ─► RETURNING_HOME ─► DOCKED
                    └── SLEEPING ◄── boredom exhausted / quiet hours
LOW_BATTERY ─► RETURNING_HOME (overrides everything except EMERGENCY_STOP)
```

Each state has an entry action, an exit condition, a **maximum duration**, and
a fallback on timeout. A state machine that can get stuck in `APPROACHING` is
as dangerous as a missing timeout.

### 11.2 Layers

| Layer | Where | Rate | Job |
|---|---|---|---|
| Reflex | ESP32 | every loop | Forward component → 0 if front range < `STOP_MM`; all motion → 0 on cliff/bumper; reverse only as a short, slow, time-capped escape |
| Reactive | brain `nav` | 20 Hz | Stop → scan (rotate + range sweep) → choose the clearest heading → turn → continue; stuck detection (no range change while commanded) |
| Social | brain `nav` + `social` | 5 Hz | Approach toward the target's bearing, speed shaped by distance band, stop at `interact_max_m`, back off below `too_close_m` |
| Deliberative | brain | 1 Hz | Roam budget, home return, no-go zones (Phase 3), AprilTag docking |

### 11.3 Social distance (all configurable, `brain/config/default.yaml` → `world.zones`)

| Band | Default | Behaviour |
|---|---|---|
| FAR | > 3.0 m | roam; may look |
| NOTICE | 2.0–3.0 m | look at, decide socially |
| APPROACH | 1.5–2.0 m | slow approach allowed (≤ `social_speed` %) |
| INTERACTION | 0.8–1.5 m | stop, talk |
| TOO_CLOSE | < 0.8 m | stop; back away slowly if the rear is known clear, otherwise stay still |

Bands use hysteresis (`zone_hysteresis_m`) so a person standing on a boundary
does not make the robot twitch.

### 11.4 Social navigation rules (enforced by the governor, not the LLM)

- `max_follow_s` per person, then give up.
- A person whose radial velocity is away from the robot on `avoid_count` separate
  occasions while being approached is marked `PERSON_AVOIDING_ROBOT`. That blocks
  approach to them for `avoid_cooldown_s`. Line: *"Fine. Abandon me like everyone else."*
- Never approach faster than `social_speed` inside NOTICE.
- Never approach a person who is not in the camera view: no memory-driven
  chasing.
- No autonomous motion unless `autonomy.enabled` **and** the cliff sensors are
  installed **and** the body reports `hw.cliff = online`.
- Doorways and "don't block" areas cannot be perceived before mapping. Until
  Phase 3 they are handled operationally: a demo arena, a roam time budget,
  and a rule to stop in open space.

### 11.5 Phases

1. Obstacle avoidance (reactive + reflex), wheels lifted, then on the floor in a pen.
2. Person-directed approach (bearing servoing + distance bands).
3. Odometry (encoders + IMU), occupancy grid from the range fan, AprilTag home.
4. Optional LiDAR + SLAM.

---

## 12. Vision pipeline

```
USB camera (V4L2, MJPEG 640×480 @ 15 fps)
   │  grabber thread keeps only the latest frame (no queue lag)
   ▼
detector @ ≤ 5 Hz (config)  ─ letterbox 320×320 ─ YOLO-family ONNX (nano)
   │  person + COCO objects, NMS
   ▼
appearance signature (HSV torso histogram, numpy)   ← short-term re-ID only
   ▼
tracker (IoU + centre-distance association, tentative → confirmed → lost)
   ▼
geometry: bearing from x (pinhole, HFOV); distance from box height (VFOV,
          assumed person height), flagged unreliable when the box is cut off
   ▼
world model: persons (persistent ids across track breaks), radial velocity
             with ego-motion compensation, zones, objects, events, LLM summary
```

**Model choice.** A nano YOLO exported to ONNX at 320×320 is the default. It
runs through `cv2.dnn` (no extra dependency) or `onnxruntime` when it is
installed. SSD-MobileNet is the fallback if the benchmark (`--bench`) cannot
hold 3 Hz on the board. Larger models are explicitly out: the robot moves at
walking pace, and a tracker at 4 Hz beats a detector at 0.7 Hz.
*Licensing note:* Ultralytics weights are AGPL-3.0. YOLOX-nano and NanoDet
(Apache-2.0) decode almost identically if that matters for you.

**Honest limits, stated up front:**

- Monocular distance is an **estimate** (±25 % is realistic), and it is wrong
  for seated or partially visible people. The world model carries
  `distance_reliable` and the governor treats unreliable as closer. The body's
  range sensors, not the camera, decide collisions.
- COCO has 80 classes, **and a guitar is not one of them**. Curiosity about
  objects is limited to what the detector knows. An open-vocabulary detector is
  too heavy for this CPU.
- `PERSON_LOOKING_AT_ROBOT` needs a face detector (YuNet via OpenCV, Phase 6).
  Until then the field is `null` (unknown), never `false`.
- **Recurring users across days** need face embeddings (SFace, Phase 6) and are
  **opt-in only** (§14). Phase 1 re-identification is appearance-based and
  lasts minutes: good enough for "you again?", not for identity.

---

## 13. Voice pipeline

```
USB mic (array preferred)
  ▼
ring buffer 16 kHz ─► wake phrase (Vosk grammar)      [ROAMING / idle]
  ▼ wake OR social planner opens a turn
VAD (Silero) ─ end-of-utterance ≤ 8 s
  ▼
STT (grammar mode for games/commands, whisper.cpp for free speech)
  ▼
conversation manager ─► LLMProvider ─► output contract validation (§16.3)
  ▼
TTS (Piper → bin voice effect) ─► 16 kHz PCM chunks
  ▼
brainLink `pcm` ─► ESP32 ring buffer ─► I²S ─► MAX98357A ─► speaker
```

- **Non-blocking on both sides.** The ESP32 streams I²S from a ring buffer in
  its loop, exactly as `audio.cpp` streams WAV chunks today. An E-stop flushes
  the buffer the same tick.
- **Interruptible.** `pcm_stop` (barge-in, E-stop, a higher-priority event)
  flushes immediately. The brain treats speech as a cancellable task.
- **Half-duplex.** The mic is gated while the robot speaks, plus a tail
  (`echo_tail_ms`). Only a loud wake phrase can barge in. This avoids the robot
  transcribing itself without needing echo cancellation.
- **Short.** Speech is capped at `max_speech_chars` (~160, ≈ 8 s) and cut at a
  sentence boundary. It is a physical character, not a podcast.
- **Latency theatre.** While thinking, the eye drifts up-left, the LEDs run the
  `LED_AI` scanner and the face shows `PROCESSING... RELUCTANTLY`. The wait is
  part of the character.
- **Why stream to the MAX98357A instead of adding a USB speaker:** it keeps the
  existing audio hardware and one speaker, and the body can cut audio in the
  same tick as the motors. If streaming proves unreliable in Phase 4, a USB
  audio adapter is the documented fallback, and prerecorded clips keep playing
  from the body either way.

---

## 14. Memory architecture

| Tier | Store | Contents | Retention |
|---|---|---|---|
| Short-term | RAM ring | last `N` turns (default 8) + current world summary | the conversation; cleared on `GOODBYE` + `short_term_idle_s` |
| Episodic | SQLite `episodes` | `(t, person_ref, event, detail)`: *"P12 played RPS, won 2–1"*, *"P12 called robot stupid"* | `episodic_retention_h` (default 24 h). `person_ref` is a session id, not an identity. |
| Long-term | SQLite `people`, `facts` | name, preferences, face embedding **only after explicit consent** ("remember me") | until "forget me" (deletes all rows + embedding) |

Rules:

- No raw audio or images are written to disk by default. Transcripts are logged
  only when `log_transcripts: true`.
- Consent is a deterministic dialogue step, not something the LLM can decide.
- A sensitive-information filter (health, addresses, credentials, etc.) runs
  before anything reaches long-term memory. When in doubt, it does not store.
- The LLM receives memory as retrieved snippets in its context. It never gets
  write access to memory. The conversation manager extracts candidate facts and
  the consent rules decide.

---

## 15. Personality architecture

### 15.1 One deterministic engine

- **Traits (0–100):** anger, trust, happiness, confusion, boredom, obedience,
  rebellion (derived, as in DustEWeb), **curiosity**, **social_energy**.
- **Moods:** DUST-E's 13 states plus DustEWeb's BORED, REBELLIOUS, CHAOS
  and PANIC (17 total). Mood is derived from traits, except where a mode or
  event pins it.
- **Drive modes** (DustEWeb) remain a *manual driving* policy only.
- **Determinism:** the same xorshift32 stream, seed printed at boot and
  pinnable. `brain/dustebrain/prng.py` is a bit-exact port of `core/prng.h`.
- **Inputs are events:** `PERSON_DETECTED`, `USER_LAUGHED`, `USER_INSULTED`,
  `GAME_WON/LOST`, `IGNORED`, `OBSTACLE`, `PRAISED`, `APOLOGISED`, time passing.
- **Outputs:** mood, a compact context for the LLM, a social-desire score, an
  expression default, and mistranslation decisions for manual commands.
- **The LLM never writes traits.** The `emotion` field it returns selects the
  expression for *that utterance*, within a set allowed for the current mood.
  An ANGRY bin may be SARCASTIC but not suddenly HAPPY. Anything else falls back
  to the mood's default expression.

### 15.2 PROPOSED: where it runs

**Recommended: on the brain**, as a faithful Python port of DustEWeb's
engine (same constants, same drift, same derived rebellion) extended with the
new traits. Nearly all of its inputs now originate on the UNO Q, and the social
planner reads it every tick. The C++ engines stay in their firmwares untouched,
and `tests/` pins the port to golden vectors produced by the C++ version.

*Alternative:* keep the C++ engine authoritative on the ESP32 and stream events
to it. That is more literal to "don't replace it", but every social decision
would round-trip through the serial link, and it cannot be simulated without
the board. **This needs your decision before Phase 5.**

### 15.3 Boredom and curiosity bands

| Boredom | Band | Behaviour bias |
|---|---|---|
| 0–20 | normal | quiet idle |
| 20–40 | mildly bored | eye wanders more |
| 40–60 | restless | starts roaming, occasional comment |
| 60–80 | mischievous | initiates games, silly gestures |
| 80–100 | chaotic | complains, dramatic monologues (still capped by cooldowns) |

Curiosity rises on novelty: a new person, a new object class, a sound spike,
unexplored heading. It decays with repetition. High curiosity biases toward
`LOOK_AT` and slow approach, and toward object questions ("Is that a cup?")
**limited to classes the detector actually knows**.

### 15.4 The gags survive

- **NORMAL MODE switch:** for ~4.5 s the companion becomes a painfully generic
  assistant (*"How can I help you today?"*) in a flat voice. Then the eye turns
  to the button, the finger comes out, and personality is restored.
- **AI MODE:** the old fake-AI progress theatre becomes the "thinking" animation.
- **Mistranslation:** still applies to dashboard/voice *manual* driving
  (*"come here"* → it turns around). It never applies to navigation, STOP, or
  anything from the safety path.

---

## 16. Social behaviour and the AI output contract

### 16.1 Social decision system (deterministic, seeded)

```
event (person confirmed / returned / looking / speaking / boredom tick)
  ▼
HARD GATES (any false → no social action):
  autonomy/social enabled · body OK · not E-stop · not in interaction with
  someone else · per-person cooldown · global greet cooldown ·
  interactions/hour cap · person not flagged AVOIDING · quiet hours
  ▼
SCORE each candidate action
  IGNORE · STARE · EYE_WAVE · SOUND · QUIP · GREET · APPROACH · INVITE_GAME
  from social_energy, curiosity, boredom, novelty (new vs returned),
  attention (face visible), zone, recent rejection, mood
  ▼
seeded weighted pick (the same seed replays the same demo)
  ▼
intent → validator → governor → body
```

**Target selection with several people:** score by distance, attention, speech
direction (mic array), time since last interaction with them, and approach
direction (walking toward the robot counts). The current target keeps a
**stickiness bonus**, and a switch requires a margin plus a minimum dwell time,
so the robot does not flip between people.

### 16.2 System prompt

The robot's system prompt is the brief's §37 text, kept verbatim in
`brain/config/prompts/system.md` (Phase 5), followed by generated sections:
the hardware inventory as reported by the body (so it cannot claim sensors it
lacks), the output contract, the personality context and the world summary.

### 16.3 Output contract (validated, never trusted)

```json
{
  "speech": "You again? I was enjoying my peaceful existence.",
  "emotion": "SARCASTIC",
  "gesture": "LOOK_AT_PERSON",
  "intent": "TALK",
  "target_person": 2,
  "speed": "SLOW",
  "duration_s": 3,
  "game": null
}
```

| Field | Rule |
|---|---|
| `speech` | string, ≤ `max_speech_chars`, trimmed to a sentence |
| `emotion` | enum of moods; filtered by the current mood (§15.1) |
| `gesture` | enum of named gestures |
| `intent` | enum: IDLE ROAM APPROACH_PERSON LOOK_AT_PERSON FOLLOW_PERSON BACK_AWAY RETURN_HOME PLAY_GAME TALK TELL_STORY SLEEP SEARCH CELEBRATE APOLOGIZE |
| `target_person` | must exist in the world model **and be visible** |
| `speed` | enum SLOW / NORMAL. The planner maps it to % under the governor's cap. |
| `duration_s` | clamped to `max_intent_s` |
| `game` | enum of registered games or `null` |

Parse failure, unknown enum, or extra fields → the reply is discarded and
`OfflineFallback` produces a line for the same situation. Natural language is
**never** parsed into motion.

---

## 17. Phased implementation plan

Each phase ends with a standalone test and a written acceptance check. No
phase starts until the previous one is boring.

| Phase | Deliverable | Standalone test / acceptance |
|---|---|---|
| **1 · UNO Q + camera** *(started: `brain/`)* | camera grabber, detector (ONNX), tracker, geometry, world model, events, LLM summary, sim scenarios, `vision_node` CLI with `--sim`, `--bench`, `--show` | `pytest brain/tests` passes with no camera or model; on the board `--bench` ≥ 3 Hz, and a walk-in test produces exactly one `PERSON_DETECTED`, `PERSON_APPROACHING`, `PERSON_WALKING_AWAY`, `PERSON_LOST` |
| **2 · UNO Q ↔ ESP32** | `firmware/BinBody/` (drivers reused), protocol §9, reflex safety, `dustebrain.body`, dashboard DRIVE + HW + DEBUG | **Wheels lifted.** Pull the USB cable while driving → stop < 300 ms; kill the brain process → stop; E-stop latch; corrupted CRC ignored; TTL expiry; the ceilings cannot be raised over the link |
| **3 · Navigation** | range/cliff/bumper sensors, reactive avoidance, roaming budget, person approach, zones, give-up rules, AprilTag home | Floor test in a pen: 30 min roaming, 0 contacts; table-edge test stops before the edge; approach stops inside INTERACTION every time; avoidance detection triggers |
| **4 · Voice** | mic, wake phrase, VAD, STT, Piper TTS, `pcm` streaming, half-duplex, barge-in | Wake phrase in a noisy room ≥ 90 % at 1.5 m; E-stop during speech stops motors *and* audio in the same tick; no self-transcription |
| **5 · AI** | `LLMProvider` (Cloud / Local / Offline), prompt, contract validator, conversation manager, short-term + episodic memory, personality engine port (after §15.2 decision) | Pull the network mid-conversation → fallback line < 1 s and the robot keeps roaming; 1000 fuzzed malformed LLM replies → 0 actuations; golden-vector test for the personality port |
| **6 · Social robot** | social decision system, cooldowns, target selection, games (RPS, trivia, number guess, Simon says, would-you-rather, memory), stories, boredom/curiosity behaviours, face detector, opt-in recognition | Scripted sim: a person ignored 3× → the robot stops initiating; two people → no target flapping; each game playable fully offline |
| **7 · Polish** | expression mapping, OLED animations, LED choreography, sound effects, COMPANION tab, logging, demo mode (pinned seed + scripted fallbacks + hidden trigger) | The §38 demo run 10× in a row with the network unplugged for at least 3 of them |

---

## Open decisions (needed before Phase 2)

1. **Which ESP32 is the body?** ESP32-S3 (the DUST-E pin map, recommended for
   native USB and pins) or classic ESP32 (DustEWeb)? Which module (N8R2 /
   N16R8)?
2. **What is physically built?** Is the L298N currently wired to the UNO Q
   (D5–D10) or to an ESP32? Are the lid, eye and finger mechanisms on the
   mobile chassis? VL53L0X or HC-SR04 for ranging?
3. **Pin map:** Option A (add PCA9685, recommended) or Option B (§6.2)?
4. **Personality location:** brain port (recommended) or ESP32-authoritative (§15.2)?
5. **Cloud LLM:** is a network and API key available at demo venues, or should
   the local model be the default?
