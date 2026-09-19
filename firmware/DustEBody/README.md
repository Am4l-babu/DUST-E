# DUST-E BODY

### The part that moves, and the part that says no

Firmware for the **Seeed XIAO ESP32-S3** (plain, not Sense). The brain — the
Arduino UNO Q's Linux side — decides what the robot should do. This board
executes it, and has the last word on anything that moves.

Design and the reasoning behind the split:
[../../docs/COMPANION_ARCHITECTURE.md](../../docs/COMPANION_ARCHITECTURE.md).

---

## 1. Hardware

| XIAO pad | GPIO | Net | Fit this too |
|---|---:|---|---|
| D0 / D1 | 1, 2 | L298N `IN1` / `IN2`, left motor | **10 kΩ pull-down on each** |
| D8 / D9 | 7, 8 | L298N `IN3` / `IN4`, right motor | **10 kΩ pull-down on each** |
| D2 | 3 | WS2812B data (12 pixels) | 330 Ω in series |
| D3 | 4 | Lid servo signal | servo power from the servo rail, **never** the XIAO |
| D4 / D5 | 5, 6 | I²C — throat ToF (not fitted yet), PCA9685 later | 4.7 kΩ pull-ups |
| D7 | 44 | `MOTION_OK` from the UNO Q MCU D9 | **100 kΩ pull-down** |
| D6, D10 | 43, 9 | spare, reserved for I²S | — |
| USB-C | — | link to the UNO Q, through the powered hub | — |

`ENA`/`ENB` jumpers on the L298N stay **on**: the driver is controlled on its
IN pins, which costs four GPIOs instead of six.

**The pull-downs are not optional.** While this board is resetting, being
flashed or unpowered, its pins are inputs. Without the pull-downs the L298N
inputs float and a motor can twitch. They cost pennies and they are the
difference between a safe power-up and a surprise.

---

## 2. Build and flash

```bash
cd firmware/DustEBody
pio run              # build
pio run -t upload    # flash
pio device monitor   # watch the [hb] line and the telemetry
```

Arduino IDE works too: open `DustEBody.ino`, board **XIAO_ESP32S3**, and set
**USB CDC On Boot = Enabled** — `Serial` is the native USB port and is also the
brain link.

Libraries (PlatformIO installs them automatically): ArduinoJson 7, Adafruit
NeoPixel, ESP32Servo.

---

## 3. What it refuses to do

This is the whole point of the board, so it is worth stating plainly.

| Situation | What happens |
|---|---|
| The brain stops sending for 300 ms | Motors hard stop. A crashed brain, a yanked cable and a hung Linux side are the same failure here. |
| A velocity command is not refreshed | Its TTL expires (500 ms max) and the target ramps to zero. Normal, not a fault. |
| `MOTION_OK` pulses stop | Forward motion blocked within ~150 ms. A short, slow reverse is allowed to escape, then a cooldown. |
| The E-stop is hit | Latched. Motor power is also cut in hardware, upstream of this board. |
| `reset_estop` arrives while the motors are still turning | Refused, with `E_BUSY`. |
| Anything asks for more than the ceiling | Clamped to 45 % autonomous / 70 % manual. The `limits` message can only ever **lower** it. |
| A command arrives before `hello` | Refused. The safe state is the default state. |
| A line arrives with a bad CRC | Dropped and counted. Never half-parsed, never guessed at. |
| A command names hardware that is not fitted | Refused with `E_NOT_INSTALLED` and a reason — not silently ignored. |

`MOTION_OK` deserves the detail: the UNO Q MCU toggles one wire while its
sensors see no hazard, and this board counts **edges**, not a level. A wall, a
cliff, a bumper, a crashed MCU, a hung loop and a cut wire all produce the same
thing — no pulses — and all get the same answer.

---

## 4. Architecture

```
loop():  brainLink.poll()    commands land first
         reflex.enforce()    then safety decides what survives
         motors.tick()       then, and only then, the wheels hear about it
         lid / leds          expression, which cannot move the wheels
         telemetry
```

There is no `delay()` after `setup()` returns. That is what makes every timeout
in the table above mean anything.

| File | Contents |
|---|---|
| `src/config/pins.h` | The GPIO map, and why each pin is where it is. |
| `src/config/settings.h` | Every tunable number. The same values as the `body:` block in `brain/config/default.yaml`. |
| `src/link/brainLink.*` | JSON lines + CRC-16, command dispatch, telemetry, honest hardware inventory. |
| `src/safety/reflex.*` | The rules above, in the order they are applied. The `MOTION_OK` ISR lives here. |
| `src/motor/motors.*` | L298N on four pins, ramp, min-duty lift, ceiling. Adapted from `DustEWeb`. |
| `src/hw/lid.*` | Cosine-eased lid, auto-detach when parked. |
| `src/hw/leds.*` | 12-pixel WS2812B patterns, non-blocking. |
| `src/core/crc16.h` | CRC-16/CCITT-FALSE. Check value for `123456789` is `0x29B1`. |

**The specification lives in Python.** `brain/dustebrain/body/simbody.py` is a
reference implementation of the reflex rules, and `brain/tests/test_simbody.py`
is the failsafe matrix as 20 tests. This firmware is written to match it. If
the two disagree, this firmware is wrong.

---

## 5. Not yet on this board

Refused with `E_NOT_INSTALLED` until the hardware and its driver arrive
together — the inventory flags at the bottom of `settings.h` are the seam:

- **Throat ToF (VL53L0X).** Until it is fitted, the lid closes on the slow
  profile only and reports `lid_safety: degraded_slow_close`. It cannot detect
  an obstruction, and it does not claim to.
- **Speaker (MAX98357A).** I²S needs three pins and two are spare, so fitting
  the amp also means fitting a PCA9685 and moving the lid servo onto it.
- **Eye servo, finger.** No pads left; both arrive with the PCA9685.
- **Battery.** Measured by the INA219 on the UNO Q sensor node and forwarded
  over the link. Until then telemetry reports `battery_mv: null` rather than a
  fabricated number.

---

## 6. Verified how

`pio run` builds clean for `seeed_xiao_esp32s3` — 6.2 % RAM, 9.2 % of the app
partition. The only warnings come from inside ESP32Servo.

**Not verified:** none of this has run on a XIAO, driven a motor, or exchanged
a byte with a UNO Q. There is no serial client on the brain side yet. Treat the
first power-up as a bring-up, **with the wheels off the ground**, in this
order: `[hb]` line appears → `hello` handshake → MOTION_OK pulses seen in
telemetry → then, and only then, a velocity command.
