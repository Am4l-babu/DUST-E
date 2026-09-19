# DUST-E SENSOR NODE

### The UNO Q's half of physical safety

Firmware for the **Arduino UNO Q, MCU side** (STM32U585, Zephyr-based Arduino
core, board `arduino:zephyr:unoq`). This board owns every sensor that can stop
the robot and drives no motor. It talks to the XIAO body over exactly one
signal.

Design and reasoning: [../../docs/COMPANION_ARCHITECTURE.md](../../docs/COMPANION_ARCHITECTURE.md)
section 6.2. The XIAO side of this conversation is
[../DustEBody/](../DustEBody/README.md).

---

## 1. The one signal that matters: MOTION_OK

This board's **D9** goes to the XIAO's **D7**. It is a pulse train, not a
level: this loop toggles it every pass while nothing it can see is a hazard,
and holds it low the instant something is. The XIAO requires at least two
edges inside a 150 ms window before it will drive forward at all
(`firmware/DustEBody/src/safety/reflex.cpp`).

That design means a crashed MCU, a hung loop, a cut wire, an obstacle, a cliff
and a pressed bumper all produce **exactly the same signal**: no pulses. The
XIAO does not need to know which one happened to do the right thing. It only
needs to know that this board is no longer vouching for the space ahead.

Worst-case loop period here is one `pulseIn()` timeout (12 ms, one HC-SR04 read
per pass, round-robin). That leaves enormous margin under the XIAO's 150 ms
window - this board does not need to be fast, only reliably not-stuck.

---

## 2. Wiring

Same physical pins as `firmware/UselessBox/UselessBox_UnoQ/` - this is a
different program for the same bench wiring, not a new harness. Only the six
pins the L298N and the flip-switch servo used to occupy are repurposed, because
both of those moved to the XIAO.

| Pin | Net | Status |
|---|---|---|
| D2 / D4 | HC-SR04 #1 TRIG / ECHO | fitted (ECHO through a 5 V→3.3 V divider) |
| A0 / A1 | HC-SR04 #2 TRIG / ECHO | fitted |
| A2 / A3 | HC-SR04 #3 TRIG / ECHO | fitted |
| D3 | active buzzer | fitted |
| D12 | NORMAL MODE switch | fitted, `INPUT_PULLUP` |
| D13 | IR throat sensor | fitted |
| SDA/SCL (`Wire2`) | SSD1306 OLED | fitted |
| SDA/SCL (`Wire2`) | INA219 battery monitor @0x40 | **not fitted** - [BOM row 4](../../docs/COMPANION_BOM.md) |
| D5 / D6 | `BUMPER_L` / `BUMPER_R` | **not fitted** - row 9 |
| D7 / D8 | `CLIFF_L` / `CLIFF_R` | **not fitted** - row 8 |
| D9 | `MOTION_OK` → XIAO D7 | fitted, this board is the source |
| D10 | `ESTOP_SENSE` | **not fitted** - fit with the E-stop, row 1 |
| D11 | camera tilt servo | fitted (19 Sep 2026) - see section 6 below. Not driven by this sketch yet |

Bumpers and the E-stop sense contact are wired **NC to ground through a
pull-up**: the resting, safe state is a closed circuit reading LOW. A press
*or* a broken wire both open the circuit and read HIGH - deliberately the same
outcome, because "I don't know" and "it's pressed" should never be told apart
by a robot deciding whether to keep driving.

---

## 3. Hardware inventory - honesty, not auto-detection

None of the new sensors can be detected on these pins, so nothing is guessed.
Flip a flag in the sketch at the same time the part is soldered in:

```cpp
#define HW_CLIFF     0   // TCRT5000 x2
#define HW_BUMPERS   0   // micro limit switch x2
#define HW_ESTOP     0   // aux NC contact on the mushroom switch
#define HW_BATTERY   0   // INA219 on Wire2 @0x40
```

An uninstalled sensor is **left out of the hazard vote entirely** - not read
as "safe" (which would be worse than not having it) and not read as a
permanent hazard (which would just wedge MOTION_OK forever on an empty pin).
Today, with cliff, bumpers, E-stop-sense and battery all unfitted, MOTION_OK
tracks the ultrasonic fan and the IR throat sensor only. **Autonomous roaming
must not be enabled** (`docs/COMPANION_ARCHITECTURE.md` §7, `docs/COMPANION_BOM.md`
§2) until the cliff sensors and bumpers exist - that is a brain-side
configuration decision, not something this firmware can enforce by itself.

The periodic status line on the serial console (`[sensor] hazard=...`) always
prints every channel's raw reading, `-1` for anything not installed, so a
bring-up can be checked against what is actually true.

---

## 4. Build and flash

Arduino IDE only - there is no PlatformIO board definition for the UNO Q yet
(the same limitation noted in `tests/l298n_motor_test/platformio.ini`).

1. Board: **Arduino UNO Q**.
2. Libraries: `Adafruit GFX Library` (only `drawPixel` is used; the OLED is
   driven directly because neither `Adafruit_SSD1306` nor U8g2's hardware-I2C
   path reaches the header pins' `Wire2` bus on this core).
3. Open `DustESensorNode.ino`, upload.
4. Serial monitor at 115200 baud.

---

## 5. Verified how

**Compiled and flashed on real hardware (19 Sep 2026)**, via `arduino-cli`
(`arduino:zephyr:unoq`, board core `arduino:zephyr@1.0.0`) against a UNO Q
connected over USB (`COM4` for the MCU/serial interface; the same composite
device also exposes an ADB interface and a network port for the Linux side).
This is the first time this sketch has run on hardware rather than just being
read against the documented API.

That first compile caught a real bug: `Serial.printf(...)` does not exist on
this core (`Serial` here is Zephyr's `BridgeMonitor<>`, which only has
`print()`/`println()`) - both status-print call sites were rewritten to plain
`print()` chains. Fixed and confirmed by a clean compile (13% flash, 17% RAM).

Live serial output after flashing:

```
[sensor] hazard=0 (clear) us=-1/-1/-1 cliff=-1,-1 bump=-1,-1 estop=-1 normal_sw=0 motion_ok=1
```

Read against the wiring table above: `cliff=-1,-1 bump=-1,-1 estop=-1` is
correct - those `HW_*` flags are `0` (not fitted) on this board today, so the
sketch is correctly leaving them out of the hazard vote rather than guessing.
`us=-1/-1/-1` is `readDistanceCm()`'s honest "no echo within the 12 ms/~2 m
timeout" value (line ~251) - on this particular bench run it never saw a
return echo from any of the three HC-SR04 units in an 8-second sample. That is
consistent with either the ultrasonic fan not being wired to *this specific*
board right now, or genuinely nothing within ~2 m of all three sensors; it is
**not** distinguishable from serial output alone, by design (a fabricated
reading would be worse than an honest "don't know"). Wave a hand within ~30 cm
of each sensor and re-read the line to tell those two cases apart before
trusting the ultrasonic fan for anything.

Not yet verified: the OLED face render, the buzzer, and the NORMAL MODE
switch under an actual press (this run only sampled its resting `normal_sw=0`
state).

---

## 6. Camera tilt servo (D11) - fitted, not yet driven

A servo tilts the USB webcam up/down. It lives on D11 because that pin was
already reserved and unused (the flip-switch servo moved to the XIAO's lid
early on - see `docs/COMPANION_ARCHITECTURE.md` section 6.2 - and nothing
had claimed D11 since). This sketch does not attach or move it yet.

**Bring-up test:** `tests/cam_tilt_test/` - a standalone sketch (Arduino IDE
/ `arduino-cli` only, same as this one). Confirmed by a real compile against
`arduino:zephyr:unoq` (19 Sep 2026, 11% flash) that Arduino's official
`Servo` library works on this core and this pin. **Not flashed or run**: the
camera mount's actual mechanical range (how far it can tilt before something
binds) is not known from here, so the test deliberately starts with a narrow,
slow sweep (90° ± 20°, one degree at a time) rather than the servo's full
range, and needs a human watching the first run before anything wider is
tried.

**Not yet decided:** how the brain's vision pipeline would actually command a
tilt angle. Today this sketch only talks to the Linux side one-way, over its
debug console (`Serial`, which is Zephyr's `BridgeMonitor<>` tunnelled
through the UNO Q's own Linux↔MCU bridge - a different channel from the
brain↔XIAO wire protocol in section 9 of the architecture doc). Commanding
the servo from `dustebrain.vision` would need a real two-way channel on that
bridge, which does not exist yet - a separate task from wiring up the servo
itself.
