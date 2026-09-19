// =============================================================================
//  lid.h - the only part of this robot that can pinch a finger.
//
//  Carries over the rules from firmware/DustE/src/hardware/lid.*:
//    1. The lid never moves faster than its configured profile.
//    2. Closing is eased at both ends - it cannot slam.
//    3. The servo is detached when parked, so it stops buzzing and the lid can
//       be lifted by hand without fighting the gearbox.
//
//  What is NOT carried over yet: obstruction detection. That needs the throat
//  ToF sensor, which is not fitted (settings.h HW_TOF_THROAT). Rather than
//  pretend, the lid reports `safety: degraded` to the brain and uses the slow
//  closing profile only. When the sensor arrives, closing gains the retreat
//  behaviour and this comment gets deleted.
// =============================================================================
#pragma once
#include <stdint.h>

enum LidState : uint8_t {
    LID_CLOSED,
    LID_OPENING,
    LID_OPEN,
    LID_CLOSING
};

class Lid {
  public:
    bool begin();
    void update(uint32_t now);

    void open(uint32_t now);
    void close(uint32_t now);
    void peek(uint32_t now);

    LidState state()    const { return state_; }
    uint8_t  angle()    const { return angle_; }
    bool     installed() const;
    const char *stateName() const;

  private:
    void startMove(uint8_t target, uint16_t durationMs, LidState moving, uint32_t now);
    void apply(uint8_t angle);
    void attachServo();
    void detachServo();

    LidState state_      = LID_CLOSED;
    uint8_t  angle_      = 0;
    uint8_t  startAngle_ = 0;
    uint8_t  target_     = 0;
    uint32_t moveStart_  = 0;
    uint16_t moveMs_     = 1;
    uint32_t lastStep_   = 0;
    uint32_t restingSince_ = 0;
    uint32_t openedAt_   = 0;
    bool     attached_   = false;
    bool     autoClose_  = true;
};

extern Lid lid;
