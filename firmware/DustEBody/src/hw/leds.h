// =============================================================================
//  leds.h - the WS2812B ring (12 pixels).
//
//  One pattern at a time, advanced by update() every LED_FRAME_MS. Patterns
//  are pure functions of (frame, pattern): no blocking, no delays, and no
//  per-pattern state that can get stuck half way through.
//
//  Same enum as firmware/DustE/src/hardware/leds.h, so the brain's LED_SET
//  vocabulary did not have to be invented twice.
// =============================================================================
#pragma once
#include <stdint.h>

enum LedPattern : uint8_t {
    LED_IDLE = 0,   // slow warm breathe
    LED_ALERT,      // fast amber pulse - something is happening
    LED_HAPPY,      // green sweep
    LED_ANGRY,      // hard red strobe
    LED_AI,         // blue scanner - "thinking", reluctantly
    LED_SLEEP,      // barely-there blue breathe
    LED_ERROR,      // amber double-blink
    LED_OFF,
    LED_PATTERN_COUNT
};

const char *ledPatternName(uint8_t p);
bool        ledPatternFromName(const char *name, uint8_t &out);

class Leds {
  public:
    bool begin();
    void update(uint32_t now);
    void set(uint8_t pattern);
    uint8_t pattern() const { return pattern_; }

  private:
    void render(uint32_t frame);

    uint8_t  pattern_   = LED_IDLE;
    uint32_t lastFrame_ = 0;
    uint32_t frame_     = 0;
    bool     ready_     = false;
};

extern Leds leds;
