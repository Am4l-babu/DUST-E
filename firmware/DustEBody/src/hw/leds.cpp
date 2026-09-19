#include "leds.h"
#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <string.h>
#include "../config/pins.h"
#include "../config/settings.h"

Leds leds;
static Adafruit_NeoPixel strip(LED_COUNT, PIN_LED_DATA, NEO_GRB + NEO_KHZ800);

static const char *const kNames[LED_PATTERN_COUNT] = {
    "IDLE", "ALERT", "HAPPY", "ANGRY", "AI", "SLEEP", "ERROR", "OFF"
};

const char *ledPatternName(uint8_t p) {
    return (p < LED_PATTERN_COUNT) ? kNames[p] : "?";
}

bool ledPatternFromName(const char *name, uint8_t &out) {
    if (!name) return false;
    for (uint8_t i = 0; i < LED_PATTERN_COUNT; ++i) {
        if (strcmp(name, kNames[i]) == 0) { out = i; return true; }
    }
    return false;
}

static uint8_t breathe(uint32_t frame, uint16_t periodFrames) {
    const float phase = (float)(frame % periodFrames) / (float)periodFrames;
    return (uint8_t)(127.0f + 127.0f * sinf(6.2831853f * phase));
}

bool Leds::begin() {
    if (!HW_LEDS) return false;
    strip.begin();
    strip.setBrightness(LED_BRIGHTNESS);
    strip.clear();
    strip.show();
    ready_ = true;
    return true;
}

void Leds::set(uint8_t pattern) {
    if (pattern < LED_PATTERN_COUNT) pattern_ = pattern;
}

void Leds::update(uint32_t now) {
    if (!ready_) return;
    if ((uint32_t)(now - lastFrame_) < LED_FRAME_MS) return;
    lastFrame_ = now;
    render(frame_++);
}

void Leds::render(uint32_t frame) {
    strip.clear();
    switch (pattern_) {
        case LED_IDLE: {
            const uint8_t v = breathe(frame, 160);
            for (uint16_t i = 0; i < LED_COUNT; ++i)
                strip.setPixelColor(i, strip.Color(v, (uint8_t)(v / 2), (uint8_t)(v / 8)));
            break;
        }
        case LED_ALERT: {
            const uint8_t v = (frame % 10 < 5) ? 255 : 40;
            for (uint16_t i = 0; i < LED_COUNT; ++i)
                strip.setPixelColor(i, strip.Color(v, (uint8_t)(v * 2 / 3), 0));
            break;
        }
        case LED_HAPPY: {
            const uint16_t head = (uint16_t)(frame % LED_COUNT);
            for (uint16_t i = 0; i < LED_COUNT; ++i) {
                const uint16_t d = (uint16_t)((i + LED_COUNT - head) % LED_COUNT);
                const uint8_t v = (d < 4) ? (uint8_t)(255 >> d) : 0;
                strip.setPixelColor(i, strip.Color(0, v, (uint8_t)(v / 4)));
            }
            break;
        }
        case LED_ANGRY: {
            const uint8_t v = (frame % 6 < 3) ? 255 : 0;
            for (uint16_t i = 0; i < LED_COUNT; ++i) strip.setPixelColor(i, strip.Color(v, 0, 0));
            break;
        }
        case LED_AI: {
            const uint16_t head = (uint16_t)((frame / 2) % LED_COUNT);
            for (uint16_t i = 0; i < LED_COUNT; ++i) {
                const uint16_t d = (uint16_t)((i + LED_COUNT - head) % LED_COUNT);
                const uint8_t v = (d < 3) ? (uint8_t)(200 >> d) : 10;
                strip.setPixelColor(i, strip.Color(0, (uint8_t)(v / 3), v));
            }
            break;
        }
        case LED_SLEEP: {
            const uint8_t v = (uint8_t)(breathe(frame, 400) / 6);
            for (uint16_t i = 0; i < LED_COUNT; ++i) strip.setPixelColor(i, strip.Color(0, 0, v));
            break;
        }
        case LED_ERROR: {
            const uint32_t p = frame % 40;
            const uint8_t v = (p < 4 || (p >= 8 && p < 12)) ? 255 : 0;
            for (uint16_t i = 0; i < LED_COUNT; ++i)
                strip.setPixelColor(i, strip.Color(v, (uint8_t)(v * 3 / 5), 0));
            break;
        }
        default:
            break;      // LED_OFF: cleared above
    }
    strip.show();
}
