#include "reflex.h"
#include <Arduino.h>
#include "../config/pins.h"
#include "../config/settings.h"
#include "../motor/motors.h"

Reflex reflex;

// ---------------------------------------------------------------------------
// MOTION_OK: a pulse train from the UNO Q MCU, not a level.
//
// The ISR keeps the timestamps of the last few edges. A stuck-high wire, a
// stuck-low wire, a cut wire, a crashed MCU and a hung MCU loop all produce
// the same thing here - no new edges - which is exactly the point.
// ---------------------------------------------------------------------------
static const uint8_t EDGE_SLOTS = 8;
static volatile uint32_t edgeMs[EDGE_SLOTS] = {0};
static volatile uint8_t  edgeHead = 0;

static void IRAM_ATTR motionOkIsr() {
    edgeMs[edgeHead] = millis();
    edgeHead = (uint8_t)((edgeHead + 1) % EDGE_SLOTS);
}

void motionOkBegin() {
    pinMode(PIN_MOTION_OK, INPUT);    // external 100k pull-down: no wire = no pulses
    attachInterrupt(digitalPinToInterrupt(PIN_MOTION_OK), motionOkIsr, CHANGE);
}

bool Reflex::motionOk(uint32_t now) const {
    uint8_t fresh = 0;
    for (uint8_t i = 0; i < EDGE_SLOTS; ++i) {
        const uint32_t t = edgeMs[i];
        if (t != 0 && (uint32_t)(now - t) <= MOTION_OK_WINDOW_MS) fresh++;
    }
    return fresh >= MOTION_OK_MIN_EDGES;
}

// ---------------------------------------------------------------------------
const char *inhibitName(uint8_t i) {
    switch (i) {
        case INH_ESTOP:     return "EMERGENCY STOP";
        case INH_BATTERY:   return "BATTERY CRITICAL";
        case INH_LINK:      return "LINK TIMEOUT";
        case INH_MOTION_OK: return "SENSOR VETO";
        default:            return "";
    }
}

void Reflex::begin() {
    estop_ = false;
    estopReason_ = "";
    handshaken_ = false;
    lastLink_ = 0;
    intentL_ = intentR_ = 0;
    intentUntil_ = 0;
    inhibit_ = INH_LINK;              // nothing moves until the brain says hello
    motionOkBegin();
}

void Reflex::setIntent(int16_t leftPct, int16_t rightPct, uint16_t ttlMs, uint32_t now) {
    if (estop_ || !handshaken_) return;
    if (ttlMs > CMD_TTL_MAX_MS) ttlMs = CMD_TTL_MAX_MS;
    intentL_ = leftPct;
    intentR_ = rightPct;
    intentUntil_ = now + ttlMs;
    lastLink_ = now;                  // a command is also proof of life
}

void Reflex::clearIntent(uint32_t now) {
    intentL_ = intentR_ = 0;
    intentUntil_ = now;
}

void Reflex::latchEstop(const char *why, uint32_t now) {
    (void)now;
    if (!estop_) {
        estopReason_ = why;           // callers pass string literals
        estop_ = true;
        intentL_ = intentR_ = 0;
        motors.hardStop();
    }
}

bool Reflex::resetEstop(uint32_t now, const char *&err) {
    if (!estop_) return true;
    if (motors.moving()) { err = "motors not at zero"; return false; }
    estop_ = false;
    estopReason_ = "";
    intentL_ = intentR_ = 0;
    intentUntil_ = now;               // nothing moves until a fresh command
    err = "";
    return true;
}

void Reflex::escapeOnly(int16_t &l, int16_t &r, uint32_t now) {
    const bool forward   = (l + r) > 0;
    const bool reversing = (l < 0 && r < 0);

    if (forward || !reversing) {
        if (escapeStart_) { escapeEnd_ = now; escapeStart_ = 0; }
        l = r = 0;
        return;
    }
    if (escapeStart_ == 0) {
        if (escapeEnd_ && (uint32_t)(now - escapeEnd_) < ESCAPE_COOLDOWN_MS) {
            l = r = 0;                // backing away must not become a habit
            return;
        }
        escapeStart_ = now ? now : 1;
    } else if ((uint32_t)(now - escapeStart_) >= ESCAPE_MS) {
        escapeStart_ = 0;
        escapeEnd_ = now;
        l = r = 0;
        return;
    }
    const int16_t cap = -(int16_t)ESCAPE_DUTY_PCT;
    if (l < cap) l = cap;
    if (r < cap) r = cap;
}

void Reflex::enforce(uint32_t now) {
    int16_t wantL = intentL_, wantR = intentR_;
    uint8_t inhibit = INH_NONE;

    if (estop_) {
        inhibit = INH_ESTOP; wantL = wantR = 0;
    } else if (batteryAt_ != 0 && batteryMv_ != 0 && batteryMv_ < BATTERY_CRITICAL_MV) {
        inhibit = INH_BATTERY; wantL = wantR = 0;
    } else if (!handshaken_ || (uint32_t)(now - lastLink_) > LINK_TIMEOUT_MS) {
        inhibit = INH_LINK; wantL = wantR = 0;
    } else {
        if ((int32_t)(now - intentUntil_) >= 0) wantL = wantR = 0;   // TTL expired
        if (!motionOk(now)) {
            escapeOnly(wantL, wantR, now);
            inhibit = INH_MOTION_OK;
        }
    }

    if (inhibit == INH_ESTOP || inhibit == INH_LINK || inhibit == INH_BATTERY) {
        if (motors.moving() || motors.leftTarget() || motors.rightTarget()) motors.hardStop();
        intentL_ = intentR_ = 0;
    } else {
        motors.setTarget(wantL, wantR);
    }
    inhibit_ = inhibit;
}
