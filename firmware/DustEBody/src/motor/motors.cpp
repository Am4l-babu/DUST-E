#include "motors.h"
#include <Arduino.h>
#include "../config/pins.h"
#include "../config/settings.h"

Motors motors;

// Arduino-ESP32 3.x binds PWM to the pin itself; 2.x needs explicit channels.
// The XIAO ships with 3.x, but supporting both is one #if and saves the single
// most common "it will not compile" report.
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  #define PWM_ATTACH(pin, ch)   ledcAttach((pin), MOTOR_PWM_FREQ_HZ, MOTOR_PWM_BITS)
  #define PWM_WRITE(pin, ch, d) ledcWrite((pin), (d))
#else
  #define PWM_ATTACH(pin, ch)   do { ledcSetup((ch), MOTOR_PWM_FREQ_HZ, MOTOR_PWM_BITS); \
                                     ledcAttachPin((pin), (ch)); } while (0)
  #define PWM_WRITE(pin, ch, d) ledcWrite((ch), (d))
#endif

static const uint8_t CH_L_IN1 = 0;
static const uint8_t CH_L_IN2 = 1;
static const uint8_t CH_R_IN3 = 2;
static const uint8_t CH_R_IN4 = 3;

void Motors::begin() {
    // Drive every input low before the PWM peripheral is attached, so the
    // window between reset and setup() is as short as the hardware allows.
    pinMode(PIN_MOTOR_L_IN1, OUTPUT); digitalWrite(PIN_MOTOR_L_IN1, LOW);
    pinMode(PIN_MOTOR_L_IN2, OUTPUT); digitalWrite(PIN_MOTOR_L_IN2, LOW);
    pinMode(PIN_MOTOR_R_IN3, OUTPUT); digitalWrite(PIN_MOTOR_R_IN3, LOW);
    pinMode(PIN_MOTOR_R_IN4, OUTPUT); digitalWrite(PIN_MOTOR_R_IN4, LOW);

    PWM_ATTACH(PIN_MOTOR_L_IN1, CH_L_IN1);
    PWM_ATTACH(PIN_MOTOR_L_IN2, CH_L_IN2);
    PWM_ATTACH(PIN_MOTOR_R_IN3, CH_R_IN3);
    PWM_ATTACH(PIN_MOTOR_R_IN4, CH_R_IN4);

    ceiling_ = MOTOR_AUTO_MAX_PCT;
    hardStop();
}

void Motors::setCeiling(uint8_t pct) {
    if (pct == 0) return;
    if (pct > MOTOR_MANUAL_MAX_PCT) pct = MOTOR_MANUAL_MAX_PCT;  // the compile-time wall
    ceiling_ = pct;
}

int16_t Motors::clampPct(int32_t pct) const {
    const int32_t lim = (int32_t)ceiling_;
    if (pct >  lim) pct =  lim;
    if (pct < -lim) pct = -lim;
    return (int16_t)pct;
}

void Motors::setTarget(int16_t leftPct, int16_t rightPct) {
    tgtL_ = clampPct(leftPct);
    tgtR_ = clampPct(rightPct);
}

void Motors::hardStop() {
    tgtL_ = tgtR_ = 0;
    curL_ = curR_ = 0;
    writeSide(true, 0);
    writeSide(false, 0);
}

int16_t Motors::ramp(int16_t cur, int16_t tgt) const {
    int16_t accel = MOTOR_ACCEL_PCT;
    int16_t step  = (abs(tgt) > abs(cur)) ? accel : (int16_t)(accel * MOTOR_DECEL_MULT);
    int16_t diff  = (int16_t)(tgt - cur);
    if (diff >= -step && diff <= step) return tgt;
    return (int16_t)(cur + (diff > 0 ? step : -step));
}

void Motors::tick(uint32_t now) {
    if ((uint32_t)(now - lastTick_) < MOTOR_TICK_MS) return;
    lastTick_ = now;
    curL_ = ramp(curL_, clampPct(tgtL_));
    curR_ = ramp(curR_, clampPct(tgtR_));
    writeSide(true,  curL_);
    writeSide(false, curR_);
}

void Motors::writeSide(bool isLeft, int16_t pct) {
    const uint8_t pinA = isLeft ? PIN_MOTOR_L_IN1 : PIN_MOTOR_R_IN3;
    const uint8_t pinB = isLeft ? PIN_MOTOR_L_IN2 : PIN_MOTOR_R_IN4;
    const uint8_t chA  = isLeft ? CH_L_IN1 : CH_R_IN3;
    const uint8_t chB  = isLeft ? CH_L_IN2 : CH_R_IN4;

    int16_t mag = pct < 0 ? (int16_t)-pct : pct;
    if (mag != 0 && mag < MOTOR_MIN_PCT) mag = MOTOR_MIN_PCT;   // below this it buzzes
    if (mag > ceiling_) mag = ceiling_;
    const uint32_t duty = (uint32_t)mag * 255u / 100u;

    // One pair of these is unused, depending on the core version: 3.x binds
    // PWM to the pin, 2.x to a channel. Silence both rather than #if here.
    (void)pinA; (void)pinB; (void)chA; (void)chB;
    if (pct > 0) {
        PWM_WRITE(pinB, chB, 0);
        PWM_WRITE(pinA, chA, duty);
    } else if (pct < 0) {
        PWM_WRITE(pinA, chA, 0);
        PWM_WRITE(pinB, chB, duty);
    } else {
        PWM_WRITE(pinA, chA, 0);
        PWM_WRITE(pinB, chB, 0);
    }
}
