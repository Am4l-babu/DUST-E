// =============================================================================
//  hands.h - two hobby-servo arms and the gestures they know.
//
//  A gesture is a short table of keyframes (left angle, right angle, time).
//  tick() eases between them with a smoothstep and then clamps the result
//  twice: to HAND_LIMIT_LO/HI_DEG (so no table can drive an arm into the
//  body) and to HAND_SLEW_DEG_PER_S (so no table can ask a servo for more
//  than it can do without slamming). Angles are logical - 0 is the arm
//  hanging down, 180 is straight up - for both arms; the mirrored mounting
//  is handled once, at the pulse.
//
//  Safety: while the emergency stop is latched, gestures are refused, the
//  current one is abandoned, the arms are parked at HAND_PARK_DEG_PER_S and
//  then their pulses are switched off so they go limp. After HAND_RELAX_MS
//  resting normally the pulses are also switched off, which stops the servo
//  hum and the jitter, and takes their idle current off the 5 V rail.
//
//  loop() only. No task, no blocking: the pulse is hardware LEDC.
// =============================================================================
#pragma once
#include <stdint.h>
#include "../config/settings.h"

enum Gesture : uint8_t {
    GEST_REST = 0,
    GEST_WAVE,
    GEST_SHRUG,
    GEST_CELEBRATE,
    GEST_ANGRY,       // shaking fists
    GEST_FLAIL,
    GEST_REFUSE,      // arms out, held: "no"
    GEST_POKE,        // the useless finger: raise, wait, jab, retract
    GEST_BOW,
    GEST_FACEPALM,
    GEST_POINT,
    GEST_SLEEP,
    GEST_COUNT
};

const char* gestureName(uint8_t g);
uint8_t     parseGesture(const char* s);     // GEST_COUNT if unknown

struct HandKey {
    uint8_t  left;     // logical degrees
    uint8_t  right;
    uint16_t ms;       // time to reach this key; 0 terminates the table
};

class Hands {
  public:
    void begin();

    // False if not fitted, the gesture is unknown, or the e-stop is latched.
    bool play(uint8_t gesture, uint32_t now);
    void tick(uint32_t now, bool estop);

    bool    busy()    const { return seq_ != nullptr; }
    uint8_t current() const { return busy() ? gesture_ : GEST_REST; }
    bool    powered() const { return powered_; }
    uint8_t leftDeg() const { return (uint8_t)posL_; }
    uint8_t rightDeg() const { return (uint8_t)posR_; }

  private:
    void startKey(uint32_t now);
    void write(float left, float right);
    void relax();

    const HandKey* seq_ = nullptr;
    uint8_t  gesture_ = GEST_REST;
    uint8_t  key_     = 0;
    uint32_t keyStart_ = 0;
    float    fromL_ = 0, fromR_ = 0;
    float    posL_ = 0, posR_ = 0;
    uint32_t lastTick_ = 0;
    uint32_t restSince_ = 0;
    bool     powered_ = false;
    bool     safetyLatched_ = false;   // last e-stop state tick() saw
};

extern Hands hands;
