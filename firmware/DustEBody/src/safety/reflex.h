// =============================================================================
//  reflex.h - the layer no joke, no LLM and no navigation bug gets through.
//
//  This is the C++ twin of brain/dustebrain/body/simbody.py. That file is the
//  reference implementation and brain/tests/test_simbody.py is the failsafe
//  matrix as tests; this code exists to behave identically on the hardware.
//  If the two ever disagree, this one is wrong.
//
//  The rules, in the order they are applied every loop:
//
//    1. E-stop latched        -> hard stop. Cleared only by reset_estop from a
//                                human, with the motors already at zero.
//    2. Battery critical      -> refuse to move. (Reported by the sensor node;
//                                until it is wired, this stays unknown and is
//                                not invented.)
//    3. Link timeout          -> hard stop. Crashed brain, yanked cable and
//                                hung Linux side are the same failure here.
//    4. Command TTL expired   -> ramp to zero. Normal, not a fault.
//    5. MOTION_OK absent      -> forward blocked; a short slow reverse escape.
//    6. Ceiling + ramp        -> motors.cpp, which clamps whatever it is given.
//
//  Anything not on that list cannot move this robot.
// =============================================================================
#pragma once
#include <stdint.h>

enum Inhibit : uint8_t {
    INH_NONE = 0,
    INH_ESTOP,
    INH_BATTERY,
    INH_LINK,
    INH_MOTION_OK
};

const char *inhibitName(uint8_t i);

class Reflex {
  public:
    void begin();

    // --- inputs ----------------------------------------------------------
    void noteLink(uint32_t now)      { lastLink_ = now; }
    void setIntent(int16_t leftPct, int16_t rightPct, uint16_t ttlMs, uint32_t now);
    void clearIntent(uint32_t now);
    void latchEstop(const char *why, uint32_t now);
    bool resetEstop(uint32_t now, const char *&err);      // false + reason if refused
    void setBatteryMv(uint16_t mv, uint32_t now)          { batteryMv_ = mv; batteryAt_ = now; }
    void setHandshaken(bool v)                            { handshaken_ = v; }

    // --- the loop --------------------------------------------------------
    // Called every pass, after commands are processed and before motors.tick().
    void enforce(uint32_t now);

    // --- state -----------------------------------------------------------
    bool        estopActive()  const { return estop_; }
    const char *estopReason()  const { return estopReason_; }
    uint8_t     inhibit()      const { return inhibit_; }
    bool        handshaken()   const { return handshaken_; }
    bool        motionOk(uint32_t now) const;
    bool        batteryKnown() const { return batteryAt_ != 0; }
    uint16_t    batteryMv()    const { return batteryMv_; }

  private:
    void escapeOnly(int16_t &l, int16_t &r, uint32_t now);

    volatile bool estop_ = false;
    const char   *estopReason_ = "";
    bool          handshaken_ = false;

    uint32_t lastLink_   = 0;
    int16_t  intentL_    = 0;
    int16_t  intentR_    = 0;
    uint32_t intentUntil_ = 0;

    uint16_t batteryMv_ = 0;
    uint32_t batteryAt_ = 0;

    uint32_t escapeStart_ = 0;
    uint32_t escapeEnd_   = 0;

    uint8_t  inhibit_ = INH_LINK;     // the safe state is the default state
};

extern Reflex reflex;

// MOTION_OK edge counting lives with the ISR, in reflex.cpp.
void motionOkBegin();
