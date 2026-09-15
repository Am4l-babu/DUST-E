// =============================================================================
//  body.h - what the face and the arms do about what just happened.
//
//  The sound bank already turns everything interesting into a SoundEvent, so
//  the body listens to the same events rather than inventing a second
//  vocabulary: react() is the sound bank's listener, so it hears every
//  triggered event whether or not a clip is assigned to it and whether or not
//  the sound cooldown let it through. The mapping is one table in body.cpp.
//
//  tick() handles the continuous part: the mood becomes the resting
//  expression, the gaze follows the steering (and the person, when vision
//  has one), and the emergency stop overrides everything - crossed-out eyes,
//  arms parked and limp.
//
//  Like the personality engine, nothing here can move a motor.
// =============================================================================
#pragma once
#include <stdint.h>
#include "../config/settings.h"

class Body {
  public:
    void begin();
    void react(uint8_t soundEvent, uint32_t now);
    void tick(uint32_t now);

    // Dashboard test buttons. Bypass the gesture cooldown, not the e-stop.
    bool testGesture(uint8_t gesture, uint32_t now);
    bool testFace(uint8_t expr);

  private:
    void gesture(uint8_t g, uint32_t now, bool force);

    uint32_t lastGesture_ = 0;
    uint32_t gazeHoldUntil_ = 0;
    int8_t   holdX_ = 0, holdY_ = 0;
    uint32_t lastGaze_ = 0;
};

extern Body body;
