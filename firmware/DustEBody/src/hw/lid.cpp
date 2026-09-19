#include "lid.h"
#include <Arduino.h>
#include <ESP32Servo.h>
#include <math.h>
#include "../config/pins.h"
#include "../config/settings.h"

Lid lid;
static Servo servo;

bool Lid::installed() const { return HW_LID_SERVO; }

const char *Lid::stateName() const {
    switch (state_) {
        case LID_OPENING: return "OPENING";
        case LID_OPEN:    return "OPEN";
        case LID_CLOSING: return "CLOSING";
        default:          return "CLOSED";
    }
}

bool Lid::begin() {
    if (!HW_LID_SERVO) return false;
    angle_ = startAngle_ = target_ = LID_ANGLE_CLOSED;
    state_ = LID_CLOSED;
    attachServo();
    apply(LID_ANGLE_CLOSED);
    restingSince_ = millis();
    return true;
}

void Lid::attachServo() {
    if (attached_ || !HW_LID_SERVO) return;
    servo.setPeriodHertz(50);
    servo.attach(PIN_SERVO_LID, SERVO_MIN_US, SERVO_MAX_US);
    attached_ = true;
}

void Lid::detachServo() {
    if (!attached_) return;
    servo.detach();
    attached_ = false;
}

void Lid::apply(uint8_t a) {
    angle_ = a;
    if (attached_) servo.write(a);
}

void Lid::startMove(uint8_t target, uint16_t durationMs, LidState moving, uint32_t now) {
    if (!HW_LID_SERVO) return;
    attachServo();
    startAngle_ = angle_;
    target_     = target;
    moveMs_     = durationMs ? durationMs : 1;
    moveStart_  = now;
    lastStep_   = now;
    state_      = moving;
}

void Lid::open(uint32_t now)  { startMove(LID_ANGLE_OPEN,   LID_MS_OPEN, LID_OPENING, now); }
void Lid::peek(uint32_t now)  { startMove(LID_ANGLE_PEEK,   LID_MS_OPEN, LID_OPENING, now); }

void Lid::close(uint32_t now) {
    // No obstruction sensor fitted -> the slow profile, every time. The lid
    // being boring is preferable to the lid being quick and blind.
    const uint16_t ms = HW_TOF_THROAT ? LID_MS_CLOSE : LID_MS_CLOSE_SAFE;
    startMove(LID_ANGLE_CLOSED, ms, LID_CLOSING, now);
}

void Lid::update(uint32_t now) {
    if (!HW_LID_SERVO) return;

    if (state_ == LID_OPENING || state_ == LID_CLOSING) {
        if ((uint32_t)(now - lastStep_) < LID_STEP_MS) return;
        lastStep_ = now;

        const uint32_t elapsed = now - moveStart_;
        if (elapsed >= moveMs_) {
            apply(target_);
            state_ = (target_ == LID_ANGLE_CLOSED) ? LID_CLOSED : LID_OPEN;
            restingSince_ = now;
            openedAt_ = now;
            return;
        }
        // Cosine ease in and out: no step change at either end, which is what
        // stops a servo lid from slamming.
        const float f = (float)elapsed / (float)moveMs_;
        const float eased = 0.5f - 0.5f * cosf(3.14159265f * f);
        const int16_t span = (int16_t)target_ - (int16_t)startAngle_;
        apply((uint8_t)((float)startAngle_ + eased * (float)span));
        return;
    }

    if (state_ == LID_OPEN && autoClose_ && (uint32_t)(now - openedAt_) > LID_HOLD_OPEN_MS) {
        close(now);
        return;
    }
    if (attached_ && (uint32_t)(now - restingSince_) > LID_IDLE_DETACH_MS) {
        detachServo();
    }
}
