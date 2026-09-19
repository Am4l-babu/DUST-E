// =============================================================================
//  cam_tilt_test.ino - standalone bring-up test for the camera tilt servo on
//  the Arduino UNO Q's own MCU header.
//
//  Board: Arduino UNO Q (STM32U585 MCU side, Zephyr-based Arduino core,
//  arduino:zephyr:unoq). Arduino IDE / arduino-cli only - same limitation as
//  firmware/DustESensorNode/ (no PlatformIO target for this board yet).
//
//  Wiring:
//    D11  -> servo signal      (was "spare" in the pin table - see
//                                docs/COMPANION_ARCHITECTURE.md section 6.2
//                                and firmware/DustESensorNode/README.md;
//                                every other MCU header pin is already
//                                claimed by a sensor)
//    servo +  -> external 5V/6V supply, NOT the UNO Q's own 5V/3V3 pin -
//                a servo under load can brown out the board that shares its rail
//    servo -  -> common ground with the UNO Q
//
//  Confirmed by a real compile against arduino:zephyr:unoq (19 Sep 2026):
//  the official Arduino `Servo` library lists `zephyr` as a supported
//  architecture, and `camTilt.attach(11)` builds clean (9% flash on this
//  board). Not yet flashed or run - the safe mechanical range of the actual
//  camera mount is unknown from here, so this test deliberately starts with
//  a narrow, slow sweep rather than the servo's full 0-180 range.
//
//  TILT_MIN_DEG / TILT_MAX_DEG below are a conservative starting guess
//  (90 +/- 20 degrees), not a measured limit. Before widening them: watch
//  the very first sweep with a hand ready to cut power, confirm nothing
//  binds at the current range's edges, then widen a little at a time -
//  the same "small range first" caution as the drive motors' bring-up test
//  (tests/xiao_motor_test), for the same reason: a stripped servo gear is a
//  worse failure than a slightly-slow bring-up.
// =============================================================================

#include <Servo.h>

const int PIN_CAM_TILT = 11;

const int TILT_CENTER_DEG = 90;
const int TILT_MIN_DEG    = 70;    // conservative guess - confirm, then widen
const int TILT_MAX_DEG    = 110;   // conservative guess - confirm, then widen
const int STEP_DEG        = 1;     // degrees per step - slow, not a snap-to
const int STEP_DELAY_MS   = 20;    // ~1 second to cross the full test range
const int HOLD_MS         = 1000;  // pause at each end so a bind is easy to see

Servo camTilt;
int currentDeg = TILT_CENTER_DEG;

void moveTo(int targetDeg) {
    targetDeg = constrain(targetDeg, TILT_MIN_DEG, TILT_MAX_DEG);
    int step = (targetDeg > currentDeg) ? STEP_DEG : -STEP_DEG;
    while (currentDeg != targetDeg) {
        currentDeg += step;
        camTilt.write(currentDeg);
        Serial.print(F("tilt="));
        Serial.println(currentDeg);
        delay(STEP_DELAY_MS);
    }
}

void setup() {
    Serial.begin(115200);
    delay(300);
    Serial.println();
    Serial.println(F("=== UNO Q camera tilt servo bring-up test ==="));
    Serial.println(F("Wiring and safety notes: see the header comment in this file."));
    Serial.print(F("Range this run: "));
    Serial.print(TILT_MIN_DEG);
    Serial.print(F(".."));
    Serial.println(TILT_MAX_DEG);

    camTilt.attach(PIN_CAM_TILT);
    camTilt.write(TILT_CENTER_DEG);
    currentDeg = TILT_CENTER_DEG;
    delay(1000);
    Serial.println(F("Centered. Starting sweep in 2s..."));
    delay(2000);
}

void loop() {
    Serial.println(F("--- sweep to MIN (tilt down) ---"));
    moveTo(TILT_MIN_DEG);
    delay(HOLD_MS);

    Serial.println(F("--- sweep to MAX (tilt up) ---"));
    moveTo(TILT_MAX_DEG);
    delay(HOLD_MS);

    Serial.println(F("--- back to center ---"));
    moveTo(TILT_CENTER_DEG);
    delay(HOLD_MS);

    Serial.println(F("--- cycle done, pausing 3s ---"));
    delay(3000);
}
