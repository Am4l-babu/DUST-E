#include "eyes.h"
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <string.h>
#include "../config/pins.h"
#include "../core/eventLog.h"

Eyes eyes;

static const int16_t SCR_W = 128;
static const int16_t SCR_H = 64;

// Both panels hold their clock at EYE_I2C_HZ. The library's default is to
// drop back to 100 kHz after every frame, which is a third of the frame rate.
static Adafruit_SSD1306 panelL(SCR_W, SCR_H, &Wire,  -1, EYE_I2C_HZ, EYE_I2C_HZ);
static Adafruit_SSD1306 panelR(SCR_W, SCR_H, &Wire1, -1, EYE_I2C_HZ, EYE_I2C_HZ);
static Adafruit_SSD1306 panelRShared(SCR_W, SCR_H, &Wire, -1, EYE_I2C_HZ, EYE_I2C_HZ);
static Adafruit_SSD1306* right = nullptr;

// ---------------------------------------------------------------------------
// What loop() asks for. Written under the spinlock, copied out once a frame.
// ---------------------------------------------------------------------------
struct Request {
    uint8_t  base       = EXPR_NEUTRAL;
    uint8_t  flash      = EXPR_COUNT;
    uint32_t flashUntil = 0;
    int8_t   lookX      = 0;
    int8_t   lookY      = 0;
    uint32_t lookMs     = 0;       // 0 = never steered
    bool     blink      = false;
};
static Request req;
static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;

// ---------------------------------------------------------------------------
// The expression table. One row per EyeExpr, describing the LEFT eye; the
// right eye is its mirror image. Sizes in pixels on a 128x64 panel.
//
//   lid    flat top lid, pixels covered from the top
//   slant  inner top corner pulled down (angry); negative pulls the OUTER
//          corner down instead (sad)
//   happy  pixels covered from the bottom by a rounded cut (the ^ ^ look)
//   gx/gy  gaze bias added to wherever the eyes are looking
// ---------------------------------------------------------------------------
struct Shape { int8_t w, h, r, lid, slant, happy, gx, gy; };

static const Shape kShapes[EXPR_COUNT] = {
    //  w   h   r  lid slant happy  gx  gy
    { 60, 50, 14,  0,   0,    0,    0,  0 },   // NEUTRAL
    { 62, 50, 16,  0,   0,   24,    0, -4 },   // HAPPY
    { 64, 50, 10, 26,   0,    0,    0, 30 },   // BORED
    { 58, 50, 14,  0,   0,    0,  -20,  0 },   // CONFUSED (right eye shrinks, see below)
    { 60, 46, 10,  0,  24,    0,    0,  6 },   // ANGRY
    { 58, 44, 10, 14,   8,    0,   70,  0 },   // REBELLIOUS
    { 64,  4,  2,  0,   0,    0,    0, 40 },   // SLEEPING
    { 60, 50, 14,  0,   0,    0,    0,  0 },   // CHAOS (jittered at draw time)
    { 34, 34, 17,  0,   0,    0,    0,  0 },   // PANIC
    { 70, 60, 22,  0,   0,    0,    0,  0 },   // SURPRISED
    { 64, 18,  8,  0,   4,    0,   40,  0 },   // SUSPICIOUS
    { 58, 44, 12,  0, -20,    0,    0, 20 },   // SAD
    { 60, 50, 14,  0,   0,    0,    0,  0 },   // LOVE (hearts drawn instead)
    { 60, 50, 14,  0,   0,    0,    0,  0 },   // ESTOP (crosses drawn instead)
};

static const char* const kNames[EXPR_COUNT] = {
    "neutral", "happy", "bored", "confused", "angry", "rebellious", "sleeping",
    "chaos", "panic", "surprised", "suspicious", "sad", "love", "estop"
};

const char* eyeExprName(uint8_t e) { return e < EXPR_COUNT ? kNames[e] : "?"; }

uint8_t parseEyeExpr(const char* s) {
    if (!s) return EXPR_COUNT;
    for (uint8_t i = 0; i < EXPR_COUNT; ++i)
        if (!strcmp(s, kNames[i])) return i;
    return EXPR_COUNT;
}

// ---------------------------------------------------------------------------
// Loop-side API
// ---------------------------------------------------------------------------
void Eyes::setBase(uint8_t expr) {
    if (expr >= EXPR_COUNT) return;
    portENTER_CRITICAL(&mux);
    req.base = expr;
    portEXIT_CRITICAL(&mux);
}

void Eyes::flash(uint8_t expr, uint16_t ms) {
    if (expr >= EXPR_COUNT) return;
    uint32_t until = millis() + ms;
    if (until == 0) until = 1;
    portENTER_CRITICAL(&mux);
    req.flash = expr;
    req.flashUntil = until;
    portEXIT_CRITICAL(&mux);
}

void Eyes::lookAt(int8_t x, int8_t y) {
    uint32_t now = millis();
    portENTER_CRITICAL(&mux);
    req.lookX = x;
    req.lookY = y;
    req.lookMs = now ? now : 1;
    portEXIT_CRITICAL(&mux);
}

void Eyes::blink() {
    portENTER_CRITICAL(&mux);
    req.blink = true;
    portEXIT_CRITICAL(&mux);
}

// ---------------------------------------------------------------------------
static bool probe(TwoWire& bus, uint8_t addr) {
    bus.beginTransmission(addr);
    return bus.endTransmission() == 0;
}

void Eyes::begin() {
    if (!HW_EYES) return;

    Wire.begin(PIN_EYE_SDA, PIN_EYE_SCL, EYE_I2C_HZ);
    TwoWire* busR = &Wire;
    right = &panelRShared;
    if (EYES_SPLIT_BUS) {
        Wire1.begin(PIN_EYE_R_SDA, PIN_EYE_R_SCL, EYE_I2C_HZ);
        busR  = &Wire1;
        right = &panelR;
    }

    okL_ = probe(Wire, EYE_ADDR_LEFT) &&
           panelL.begin(SSD1306_SWITCHCAPVCC, EYE_ADDR_LEFT, true, false);
    // On a shared bus the two eyes must answer at different addresses, or
    // they are one eye drawn twice.
    bool sameAddr = !EYES_SPLIT_BUS && EYE_ADDR_LEFT == EYE_ADDR_RIGHT;
    okR_ = !sameAddr && probe(*busR, EYE_ADDR_RIGHT) &&
           right->begin(SSD1306_SWITCHCAPVCC, EYE_ADDR_RIGHT, true, false);

    eventLog.push("EYES", "left %s @0x%02X, right %s @0x%02X%s",
                  okL_ ? "ok" : "MISSING", EYE_ADDR_LEFT,
                  okR_ ? "ok" : "MISSING", EYE_ADDR_RIGHT,
                  EYES_SPLIT_BUS ? " (split bus)" : "");
    if (okL_ && !okR_ && !EYES_SPLIT_BUS)
        eventLog.push("EYES", "right eye: move its address resistor to 0x7A, or set EYES_SPLIT_BUS");

    if (!online()) return;
    // Core 0, low priority: below Wi-Fi and AsyncTCP, never competing with
    // loop() for core 1. The I2C transfer blocks on interrupts, so it yields.
    xTaskCreatePinnedToCore(taskEntry, "eyes", 4096, this, 1, nullptr, 0);
}

void Eyes::taskEntry(void* arg) {
    static_cast<Eyes*>(arg)->run();
}

// ---------------------------------------------------------------------------
// Renderer
// ---------------------------------------------------------------------------
namespace {

struct Live {                       // eased toward the target every frame
    float w = 60, h = 50, r = 14, lid = 0, slant = 0, happy = 0;
    float gx = 0, gy = 0;           // gaze in pixels
};

inline void ease(float& v, float target, float k) { v += (target - v) * k; }

// One eye into one panel. `mirror` flips everything that has a side.
void drawEye(Adafruit_SSD1306& d, const Live& e, float blink, bool mirror,
             uint8_t expr, uint32_t now, float scaleH) {
    d.clearDisplay();

    float h = e.h * scaleH * (1.0f - blink);
    if (h < 2) h = 2;
    int16_t w  = (int16_t)e.w;
    int16_t hh = (int16_t)h;
    int16_t cx = SCR_W / 2 + (int16_t)e.gx;     // both eyes look the same way
    int16_t cy = SCR_H / 2 + (int16_t)e.gy;
    int16_t x  = constrain(cx - w / 2, 0, SCR_W - w);
    int16_t y  = constrain(cy - hh / 2, 0, SCR_H - hh);
    int16_t r  = min<int16_t>((int16_t)e.r, min<int16_t>(w, hh) / 2);

    if (expr == EXPR_ESTOP) {
        // Crosses, not a cartoon. Thick enough to read from across a room.
        for (int8_t t = -3; t <= 3; ++t) {
            d.drawLine(cx - 20 + t, cy - 20, cx + 20 + t, cy + 20, SSD1306_WHITE);
            d.drawLine(cx + 20 + t, cy - 20, cx - 20 + t, cy + 20, SSD1306_WHITE);
        }
        d.display();
        return;
    }

    if (expr == EXPR_LOVE && blink < 0.5f) {
        // Beats: 14 px at rest, 17 px on the beat.
        float beat = (now % 700) < 120 ? 1.2f : 1.0f;
        int16_t R = (int16_t)(12 * beat);
        d.fillCircle(cx - R, cy - R / 2, R, SSD1306_WHITE);
        d.fillCircle(cx + R, cy - R / 2, R, SSD1306_WHITE);
        d.fillTriangle(cx - 2 * R - 1, cy - R / 4, cx + 2 * R + 1, cy - R / 4,
                       cx, cy + 2 * R, SSD1306_WHITE);
        d.display();
        return;
    }

    d.fillRoundRect(x, y, w, hh, r, SSD1306_WHITE);

    // Flat top lid.
    int16_t lid = (int16_t)(e.lid * (h / e.h));
    if (lid > 0) d.fillRect(x - 1, y - 1, w + 2, lid + 1, SSD1306_BLACK);

    // Slanted lid. Inner corner = the side facing the other eye.
    int16_t s = (int16_t)e.slant;
    if (s != 0) {
        bool innerRight = !mirror;                // left panel's inner edge is its right side
        bool pullRight  = (s > 0) ? innerRight : !innerRight;
        int16_t depth   = lid + abs(s);
        int16_t xl = x - 1, xr = x + w + 1, yt = y + lid - 1;
        if (pullRight) d.fillTriangle(xl, yt, xr, yt, xr, y + depth, SSD1306_BLACK);
        else           d.fillTriangle(xl, yt, xr, yt, xl, y + depth, SSD1306_BLACK);
    }

    // Happy: a rounded cut from below.
    int16_t hap = (int16_t)e.happy;
    if (hap > 0) d.fillRoundRect(x - 1, y + hh - hap + 1, w + 2, (int16_t)e.h, r, SSD1306_BLACK);

    if (expr == EXPR_SLEEPING && mirror) {
        // Zzz drifting up off the right eye.
        uint32_t p = now % 1800;
        d.setTextColor(SSD1306_WHITE);
        d.setTextSize(1);
        d.setCursor(96, 40 - (int16_t)(p / 60));
        d.print("z");
        if (p > 600) { d.setTextSize(2); d.setCursor(106, 30 - (int16_t)((p - 600) / 60)); d.print("Z"); }
    }

    d.display();
}

}  // namespace

void Eyes::run() {
    Live L;
    Request r;
    uint32_t nextBlink  = millis() + 2000;
    uint32_t blinkStart = 0;
    uint32_t nextGlance = 0;
    int8_t   idleX = 0, idleY = 0;
    uint32_t nextChaos  = 0;
    int8_t   chaosW = 0, chaosH = 0;
    uint8_t  lastExpr   = EXPR_COUNT;
    TickType_t wake = xTaskGetTickCount();

    for (;;) {
        uint32_t now = millis();
        portENTER_CRITICAL(&mux);
        r = req;
        req.blink = false;
        if (req.flashUntil && (int32_t)(now - req.flashUntil) >= 0) {
            req.flash = EXPR_COUNT;
            req.flashUntil = 0;
        }
        portEXIT_CRITICAL(&mux);

        uint8_t expr = (r.flash < EXPR_COUNT) ? r.flash : r.base;
        const Shape& sh = kShapes[expr];

        if (expr != lastExpr) {
            // Sleep dims the panels: less glow in a dark room, less burn-in.
            bool dimmed = (expr == EXPR_SLEEPING);
            if (okL_) panelL.dim(dimmed);
            if (okR_) right->dim(dimmed);
            lastExpr = expr;
        }

        // ---- gaze: steered, or idle glancing
        int8_t gx, gy;
        bool steered = r.lookMs && (uint32_t)(now - r.lookMs) < EYE_IDLE_LOOK_MS;
        if (steered) {
            gx = r.lookX; gy = r.lookY;
        } else {
            if ((int32_t)(now - nextGlance) >= 0) {
                bool centre = random(100) < 45;
                idleX = centre ? 0 : (int8_t)random(-70, 71);
                idleY = centre ? 0 : (int8_t)random(-40, 41);
                nextGlance = now + (uint32_t)random(1200, 3500);
            }
            gx = idleX; gy = idleY;
        }
        float tgx = constrain(gx + sh.gx, -100, 100) * 0.30f;   // +-30 px
        float tgy = constrain(gy + sh.gy, -100, 100) * 0.12f;   // +-12 px

        // ---- shape targets, with the per-expression specials
        float tw = sh.w, th = sh.h;
        if (expr == EXPR_CHAOS) {
            if ((int32_t)(now - nextChaos) >= 0) {
                chaosW = (int8_t)random(-24, 12);
                chaosH = (int8_t)random(-30, 10);
                nextChaos = now + (uint32_t)random(90, 260);
            }
            tw += chaosW; th += chaosH;
        }
        float k = 0.35f;
        ease(L.w, tw, k);  ease(L.h, th, k);  ease(L.r, sh.r, k);
        ease(L.lid, sh.lid, k); ease(L.slant, sh.slant, k); ease(L.happy, sh.happy, k);
        ease(L.gx, tgx, 0.45f); ease(L.gy, tgy, 0.45f);
        // Draw copies, so per-frame noise never accumulates in the eased state.
        Live dl = L, dr = L;
        if (expr == EXPR_CHAOS) { dr.w = L.w - chaosH / 2; dr.h = L.h - chaosW / 2; }
        if (expr == EXPR_PANIC) {
            float shake = (float)random(-3, 4);
            dl.gx += shake; dr.gx += shake;
        }

        // ---- blinking. Sleeping eyes are already shut; the e-stop does not blink.
        if (r.blink || (int32_t)(now - nextBlink) >= 0) {
            blinkStart = now;
            nextBlink  = now + (uint32_t)random(EYE_BLINK_MIN_MS, EYE_BLINK_MAX_MS);
            if (expr == EXPR_PANIC) nextBlink = now + (uint32_t)random(400, 900);
        }
        float blink = 0;
        uint32_t bt = now - blinkStart;
        if (blinkStart && bt < 180 && expr != EXPR_SLEEPING && expr != EXPR_ESTOP)
            blink = bt < 90 ? bt / 90.0f : (180 - bt) / 90.0f;

        // CONFUSED is the one asymmetric expression: one eye doubts the other.
        float scaleR = (expr == EXPR_CONFUSED) ? 0.55f : 1.0f;

        if (okL_) drawEye(panelL, dl, blink, false, expr, now, 1.0f);
        if (okR_) drawEye(*right, dr, blink, true,  expr, now, scaleR);

        vTaskDelayUntil(&wake, pdMS_TO_TICKS(EYE_FRAME_MS));
    }
}
