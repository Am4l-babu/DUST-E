// =============================================================================
//  motors.h - L298N on four pins, ramped and clamped.
//
//  Adapted from firmware/DustEWeb/src/motor/motors.* - the ramp, the ceiling
//  and the min-duty lift are the same ideas - but driven on the IN pins with
//  ENA/ENB jumpered high, because the XIAO has four pads to spare and not six.
//
//      IN1 = PWM, IN2 = 0   forward
//      IN1 = 0,   IN2 = PWM reverse
//      both 0               brake
//
//  Everything above this layer speaks percent. Nothing above it can exceed the
//  ceiling: setMix() clamps after every transformation anyone else performed.
// =============================================================================
#pragma once
#include <stdint.h>

class Motors {
  public:
    void begin();

    // Percent, -100..100. Clamped to the current ceiling, always.
    void setTarget(int16_t leftPct, int16_t rightPct);

    // Immediate, ramp bypassed, targets zeroed. What the reflex layer uses.
    void hardStop();

    void tick(uint32_t now);

    // The link may lower this and may never raise it above MOTOR_AUTO_MAX_PCT.
    void setCeiling(uint8_t pct);
    uint8_t ceiling() const { return ceiling_; }

    int16_t leftPct()    const { return curL_; }
    int16_t rightPct()   const { return curR_; }
    int16_t leftTarget() const { return tgtL_; }
    int16_t rightTarget()const { return tgtR_; }
    bool    moving()     const { return curL_ != 0 || curR_ != 0; }

  private:
    void    writeSide(bool isLeft, int16_t pct);
    int16_t ramp(int16_t cur, int16_t tgt) const;
    int16_t clampPct(int32_t pct) const;

    int16_t  tgtL_ = 0, tgtR_ = 0;
    int16_t  curL_ = 0, curR_ = 0;
    uint8_t  ceiling_ = 0;
    uint32_t lastTick_ = 0;
};

extern Motors motors;
