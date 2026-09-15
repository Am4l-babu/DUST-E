#include "hands.h"
#include <Arduino.h>
#include <string.h>
#include "../config/pins.h"
#include "../core/eventLog.h"

Hands hands;

// Same core 2 / core 3 split as motors.cpp. The motors hold LEDC channels 0/1
// (timer 0) at 5 kHz; the hands take 4/5, which sit on timer 2, so the two
// frequencies can never be forced onto one timer.
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  #define HAND_WRITE(pin, ch, d) ledcWrite((pin), (d))
#else
  #define HAND_WRITE(pin, ch, d) ledcWrite((ch), (d))
#endif
static const uint8_t CH_LEFT  = 4;
static const uint8_t CH_RIGHT = 5;

static const uint8_t REST = HAND_LIMIT_LO_DEG;

// ---------------------------------------------------------------------------
// Gesture tables. {left, right, ms-to-get-there}. Every table ends at rest so
// an arm is never left in the air.
// ---------------------------------------------------------------------------
static const HandKey kRest[]      = {{REST, REST, 600}, {0, 0, 0}};
static const HandKey kWave[]      = {{10, 150, 400}, {10, 115, 260}, {10, 165, 260}, {10, 115, 260},
                                     {10, 165, 260}, {10, 150, 200}, {REST, REST, 600}, {0, 0, 0}};
static const HandKey kShrug[]     = {{70, 70, 260}, {70, 70, 500}, {REST, REST, 500}, {0, 0, 0}};
static const HandKey kCelebrate[] = {{165, 165, 450}, {125, 125, 220}, {170, 170, 220}, {125, 125, 220},
                                     {170, 170, 220}, {REST, REST, 700}, {0, 0, 0}};
static const HandKey kAngry[]     = {{110, 110, 300}, {95, 125, 130}, {125, 95, 130}, {95, 125, 130},
                                     {125, 95, 130}, {110, 110, 130}, {REST, REST, 500}, {0, 0, 0}};
static const HandKey kFlail[]     = {{40, 150, 260}, {150, 40, 300}, {40, 150, 300}, {150, 40, 300},
                                     {40, 150, 300}, {REST, REST, 600}, {0, 0, 0}};
static const HandKey kRefuse[]    = {{95, 95, 400}, {95, 95, 900}, {REST, REST, 500}, {0, 0, 0}};
// The pause before the jab is the joke - same rule as the real finger.
static const HandKey kPoke[]      = {{10, 45, 500}, {10, 45, 900}, {10, 115, 160}, {10, 115, 300},
                                     {REST, REST, 500}, {0, 0, 0}};
static const HandKey kBow[]       = {{45, 45, 700}, {45, 45, 500}, {REST, REST, 700}, {0, 0, 0}};
static const HandKey kFacepalm[]  = {{REST, 160, 550}, {REST, 160, 1200}, {REST, REST, 600}, {0, 0, 0}};
static const HandKey kPoint[]     = {{REST, 90, 350}, {REST, 90, 1000}, {REST, REST, 500}, {0, 0, 0}};
static const HandKey kSleep[]     = {{20, 20, 1500}, {REST, REST, 1500}, {0, 0, 0}};

static const HandKey* const kTables[GEST_COUNT] = {
    kRest, kWave, kShrug, kCelebrate, kAngry, kFlail, kRefuse, kPoke, kBow, kFacepalm, kPoint, kSleep
};

static const char* const kNames[GEST_COUNT] = {
    "rest", "wave", "shrug", "celebrate", "angry", "flail", "refuse", "poke", "bow",
    "facepalm", "point", "sleep"
};

const char* gestureName(uint8_t g) { return g < GEST_COUNT ? kNames[g] : "?"; }

uint8_t parseGesture(const char* s) {
    if (!s) return GEST_COUNT;
    for (uint8_t i = 0; i < GEST_COUNT; ++i)
        if (!strcmp(s, kNames[i])) return i;
    return GEST_COUNT;
}

// ---------------------------------------------------------------------------
static inline float clampDeg(float d) {
    if (d < HAND_LIMIT_LO_DEG) return HAND_LIMIT_LO_DEG;
    if (d > HAND_LIMIT_HI_DEG) return HAND_LIMIT_HI_DEG;
    return d;
}

static uint32_t dutyFor(float logical, bool invert, int8_t trim) {
    float phys = invert ? 180.0f - logical : logical;
    phys += trim;
    if (phys < 0)   phys = 0;
    if (phys > 180) phys = 180;
    float us = HAND_MIN_US + (HAND_MAX_US - HAND_MIN_US) * (phys / 180.0f);
    const float periodUs = 1000000.0f / HAND_PWM_HZ;
    return (uint32_t)(us / periodUs * ((1UL << HAND_PWM_BITS) - 1));
}

void Hands::begin() {
    if (!HW_HANDS) return;
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcAttach(PIN_HAND_LEFT,  HAND_PWM_HZ, HAND_PWM_BITS);
    ledcAttach(PIN_HAND_RIGHT, HAND_PWM_HZ, HAND_PWM_BITS);
#else
    ledcSetup(CH_LEFT,  HAND_PWM_HZ, HAND_PWM_BITS);
    ledcSetup(CH_RIGHT, HAND_PWM_HZ, HAND_PWM_BITS);
    ledcAttachPin(PIN_HAND_LEFT,  CH_LEFT);
    ledcAttachPin(PIN_HAND_RIGHT, CH_RIGHT);
#endif
    // Where the arms actually are at power-up is unknowable, so the first
    // pulse says "rest" and the servo gets there at its own speed, once.
    posL_ = posR_ = REST;
    write(REST, REST);
    restSince_ = millis();
    eventLog.push("HANDS", "servos on GPIO %d / %d", PIN_HAND_LEFT, PIN_HAND_RIGHT);
}

bool Hands::play(uint8_t gesture, uint32_t now) {
    if (!HW_HANDS || gesture >= GEST_COUNT) return false;
    if (safetyLatched_) return false;
    seq_ = kTables[gesture];
    gesture_ = gesture;
    key_ = 0;
    startKey(now);
    return true;
}

void Hands::startKey(uint32_t now) {
    keyStart_ = now;
    fromL_ = posL_;
    fromR_ = posR_;
}

void Hands::write(float left, float right) {
    HAND_WRITE(PIN_HAND_LEFT,  CH_LEFT,  dutyFor(left,  HAND_LEFT_INVERT,  HAND_LEFT_TRIM_DEG));
    HAND_WRITE(PIN_HAND_RIGHT, CH_RIGHT, dutyFor(right, HAND_RIGHT_INVERT, HAND_RIGHT_TRIM_DEG));
    powered_ = true;
}

void Hands::relax() {
    HAND_WRITE(PIN_HAND_LEFT,  CH_LEFT,  0);
    HAND_WRITE(PIN_HAND_RIGHT, CH_RIGHT, 0);
    powered_ = false;
}

void Hands::tick(uint32_t now, bool estop) {
    if (!HW_HANDS) return;
    if ((uint32_t)(now - lastTick_) < HAND_TICK_MS) return;
    float dt = lastTick_ ? (now - lastTick_) / 1000.0f : 0.0f;
    if (dt > 0.1f) dt = 0.1f;
    lastTick_ = now;
    safetyLatched_ = estop;

    float tgtL, tgtR, slew;

    if (estop) {
        // Abandon the gesture, park gently, then go limp.
        seq_ = nullptr;
        tgtL = tgtR = REST;
        slew = HAND_PARK_DEG_PER_S;
        bool parked = fabsf(posL_ - REST) < 1 && fabsf(posR_ - REST) < 1;
        if (parked) {
            if (powered_) relax();
            return;
        }
    } else if (seq_) {
        const HandKey& k = seq_[key_];
        uint32_t el = now - keyStart_;
        float p = k.ms ? (float)el / k.ms : 1.0f;
        if (p > 1) p = 1;
        float e = p * p * (3 - 2 * p);             // smoothstep
        tgtL = fromL_ + (k.left  - fromL_) * e;
        tgtR = fromR_ + (k.right - fromR_) * e;
        slew = HAND_SLEW_DEG_PER_S;
        if (el >= k.ms) {
            ++key_;
            if (seq_[key_].ms == 0) { seq_ = nullptr; restSince_ = now; }
            else startKey(now);
        }
    } else {
        // Idle at rest: hold briefly so the arm settles, then cut the pulses.
        if (powered_ && (uint32_t)(now - restSince_) >= HAND_RELAX_MS) relax();
        return;
    }

    float maxStep = slew * dt;
    float dL = clampDeg(tgtL) - posL_;
    float dR = clampDeg(tgtR) - posR_;
    if (dL >  maxStep) dL =  maxStep;
    if (dL < -maxStep) dL = -maxStep;
    if (dR >  maxStep) dR =  maxStep;
    if (dR < -maxStep) dR = -maxStep;
    posL_ += dL;
    posR_ += dR;
    write(posL_, posR_);
}
