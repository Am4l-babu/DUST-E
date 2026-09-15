#include "body.h"
#include <Arduino.h>
#include "../core/types.h"
#include "../face/eyes.h"
#include "../hands/hands.h"
#include "../sound/soundBank.h"
#include "../motor/motors.h"
#include "../safety/safety.h"
#include "../personality/personality.h"
#include "../vision/vision.h"

Body body;

// A personality-driven gesture at most this often. The arms are slower than
// the events, and a bin that never stops waving is not reacting to anything.
static const uint16_t GESTURE_GAP_MS = 2500;

// ---------------------------------------------------------------------------
// Event -> reaction. One row per SoundEvent, same order as the enum.
//   expr     a flash on the eyes, EXPR_COUNT for none
//   gesture  GEST_COUNT for none
//   force    skips the gesture cooldown
// ---------------------------------------------------------------------------
struct Reaction { uint8_t expr; uint8_t gesture; bool force; };

static const Reaction kReact[SND_COUNT] = {
    /* boot             */ { EXPR_SURPRISED,  GEST_WAVE,      true  },
    /* connected        */ { EXPR_HAPPY,      GEST_WAVE,      false },
    /* disconnected     */ { EXPR_SAD,        GEST_COUNT,     false },
    /* human_detected   */ { EXPR_SURPRISED,  GEST_POINT,     false },
    /* human_lost       */ { EXPR_BORED,      GEST_COUNT,     false },
    /* object_detected  */ { EXPR_SUSPICIOUS, GEST_COUNT,     false },
    /* command_obeyed   */ { EXPR_COUNT,      GEST_COUNT,     false },   // while driving: no fuss
    /* command_modified */ { EXPR_SUSPICIOUS, GEST_SHRUG,     false },
    /* command_ignored  */ { EXPR_REBELLIOUS, GEST_REFUSE,    false },
    /* command_rejected */ { EXPR_COUNT,      GEST_COUNT,     false },   // safety said no - not a bit
    /* command_delayed  */ { EXPR_BORED,      GEST_COUNT,     false },
    /* stop             */ { EXPR_COUNT,      GEST_COUNT,     false },
    /* estop            */ { EXPR_COUNT,      GEST_COUNT,     false },   // tick() owns the e-stop look
    /* safety_reset     */ { EXPR_NEUTRAL,    GEST_COUNT,     false },
    /* lid_open         */ { EXPR_HAPPY,      GEST_COUNT,     false },
    /* lid_close        */ { EXPR_COUNT,      GEST_COUNT,     false },
    /* please           */ { EXPR_LOVE,       GEST_BOW,       false },
    /* sorry            */ { EXPR_SUSPICIOUS, GEST_FACEPALM,  false },
    /* panic            */ { EXPR_PANIC,      GEST_FLAIL,     true  },
    /* do_nothing       */ { EXPR_BORED,      GEST_COUNT,     false },   // literally nothing
    /* normal_mode_on   */ { EXPR_NEUTRAL,    GEST_COUNT,     false },
    /* normal_mode_off  */ { EXPR_ANGRY,      GEST_POKE,      true  },   // mechanical intervention
    /* mood_normal      */ { EXPR_COUNT,      GEST_COUNT,     false },
    /* mood_happy       */ { EXPR_COUNT,      GEST_CELEBRATE, false },
    /* mood_bored       */ { EXPR_COUNT,      GEST_COUNT,     false },
    /* mood_confused    */ { EXPR_COUNT,      GEST_SHRUG,     false },
    /* mood_angry       */ { EXPR_COUNT,      GEST_ANGRY,     false },
    /* mood_rebellious  */ { EXPR_COUNT,      GEST_REFUSE,    false },
    /* mood_sleeping    */ { EXPR_COUNT,      GEST_SLEEP,     true  },
    /* mood_chaos       */ { EXPR_COUNT,      GEST_FLAIL,     false },
    /* mood_panic       */ { EXPR_COUNT,      GEST_FLAIL,     false },
};

// Mood -> resting expression. Same order as the Mood enum.
static const uint8_t kMoodFace[MOOD_COUNT] = {
    EXPR_NEUTRAL, EXPR_HAPPY, EXPR_BORED, EXPR_CONFUSED, EXPR_ANGRY,
    EXPR_REBELLIOUS, EXPR_SLEEPING, EXPR_CHAOS, EXPR_PANIC
};

void Body::begin() {
    eyes.begin();
    hands.begin();
}

void Body::gesture(uint8_t g, uint32_t now, bool force) {
    if (g >= GEST_COUNT || safety.estopActive()) return;
    if (!force && (uint32_t)(now - lastGesture_) < GESTURE_GAP_MS) return;
    if (hands.play(g, now)) lastGesture_ = now;
}

void Body::react(uint8_t ev, uint32_t now) {
    if (ev >= SND_COUNT || safety.estopActive()) return;
    const Reaction& r = kReact[ev];
    if (r.expr < EXPR_COUNT) eyes.flash(r.expr);
    gesture(r.gesture, now, r.force);

    if (ev == SND_NORMAL_OFF) {
        // Look at the button first. Telegraphing the move is the joke.
        holdX_ = 80; holdY_ = 90;
        gazeHoldUntil_ = now + 1600;
    } else if (ev == SND_HUMAN_DETECTED) {
        holdX_ = 0; holdY_ = -30;
        gazeHoldUntil_ = now + 1200;
    } else if (ev == SND_SAFETY_RESET) {
        eyes.blink();
    }
}

bool Body::testGesture(uint8_t g, uint32_t now) {
    if (g >= GEST_COUNT || safety.estopActive()) return false;
    if (!hands.play(g, now)) return false;
    lastGesture_ = now;
    return true;
}

bool Body::testFace(uint8_t expr) {
    if (expr >= EXPR_COUNT || !eyes.online()) return false;
    eyes.flash(expr, 3000);
    return true;
}

void Body::tick(uint32_t now) {
    bool estop = safety.estopActive();
    hands.tick(now, estop);

    if (!eyes.online()) return;

    uint8_t mood = personality.mood();
    eyes.setBase(mood < MOOD_COUNT ? kMoodFace[mood] : EXPR_NEUTRAL);

    if ((uint32_t)(now - lastGaze_) < 50) return;
    lastGaze_ = now;

    if (estop) {
        // Refreshed every 50 ms, so no reaction can flash over it.
        eyes.flash(EXPR_ESTOP, 200);
        eyes.lookAt(0, 0);
        return;
    }

    if ((int32_t)(gazeHoldUntil_ - now) > 0) {
        eyes.lookAt(holdX_, holdY_);
    } else if (motors.moving()) {
        // Look where it is turning. Duty difference is the turn; the sign
        // convention is "+x toward the right-hand eye", which is the bin
        // turning right when the left track runs faster.
        int32_t turn = ((int32_t)motors.leftDuty() - motors.rightDuty()) * 100 / 255;
        int32_t fwd  = ((int32_t)motors.leftDuty() + motors.rightDuty()) / 2;
        eyes.lookAt((int8_t)constrain(turn, -100, 100), fwd < 0 ? 40 : -20);
    } else if (vision.personPresent()) {
        eyes.lookAt(0, -30);                       // at the person, roughly face height
    }
    // Otherwise leave it alone: the eyes glance around on their own.
}
