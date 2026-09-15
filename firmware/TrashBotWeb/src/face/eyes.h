// =============================================================================
//  eyes.h - two SSD1306 OLEDs, one eye each.
//
//  Cozmo-style solid eyes, drawn from a handful of numbers (size, corner
//  radius, lids, gaze) rather than stored bitmaps, and eased toward their
//  target every frame so every expression change is an animation for free.
//  The look is in the family of FluxGarage RoboEyes and playfultechnology's
//  esp32-eyes; the code is written for two panels instead of one, so each
//  eye gets the full 128x64.
//
//  Threading: loop() only ever calls the setters, which copy a few bytes
//  under a spinlock. A task on core 0 owns the I2C bus and does all the
//  drawing, so a slow bus cannot stall the motor ramp or the safety layer.
//
//  Nothing here can move a motor, and nothing here is load-bearing: with no
//  OLED fitted, begin() logs it and every setter is a no-op.
// =============================================================================
#pragma once
#include <stdint.h>
#include "../config/settings.h"

enum EyeExpr : uint8_t {
    EXPR_NEUTRAL = 0,
    EXPR_HAPPY,
    EXPR_BORED,
    EXPR_CONFUSED,
    EXPR_ANGRY,
    EXPR_REBELLIOUS,   // side-eye, heavy lids
    EXPR_SLEEPING,
    EXPR_CHAOS,
    EXPR_PANIC,
    EXPR_SURPRISED,
    EXPR_SUSPICIOUS,   // squint
    EXPR_SAD,
    EXPR_LOVE,         // hearts
    EXPR_ESTOP,        // X X - not a joke, and deliberately looks it
    EXPR_COUNT
};

const char* eyeExprName(uint8_t e);
uint8_t     parseEyeExpr(const char* s);     // EXPR_COUNT if unknown

class Eyes {
  public:
    void begin();

    // The resting expression, normally the mood.
    void setBase(uint8_t expr);
    // A reaction that wins over the base for `ms`, then fades back.
    void flash(uint8_t expr, uint16_t ms = EYE_FLASH_MS);
    // Gaze, -100..100 each axis (+x = toward the right-hand eye as you face
    // the bin, +y = down). Holding a
    // gaze suppresses the idle glancing until EYE_IDLE_LOOK_MS after the
    // last call.
    void lookAt(int8_t x, int8_t y);
    void blink();

    bool leftOk()  const { return okL_; }
    bool rightOk() const { return okR_; }
    bool online()  const { return okL_ || okR_; }

  private:
    static void taskEntry(void* arg);
    void run();

    bool okL_ = false, okR_ = false;
};

extern Eyes eyes;
