// =============================================================================
//  DUST-E BODY  -  the part that moves, and the part that says no.
//
//  Board:   Seeed XIAO ESP32-S3 (plain, not Sense)
//  Core:    Arduino-ESP32 3.x
//  Build:   pio run          (see platformio.ini)
//           or Arduino IDE, board "XIAO_ESP32S3", USB CDC On Boot = Enabled
//
//  The brain (Arduino UNO Q, Linux side) decides. This board executes, and has
//  the last word on anything that moves. Nothing the brain sends can disable
//  the reflex layer, raise a speed ceiling, or clear an emergency stop without
//  a human.
//
//  Loop order matters and is not arbitrary:
//
//      link.poll()        every command lands first...
//      reflex.enforce()   ...then safety decides what may survive...
//      motors.tick()      ...then, and only then, the motors are written.
//      lid / leds         expression, which cannot move the wheels.
//      telemetry
//
//  There is no delay() after setup() returns. The lid keeps easing, MOTION_OK
//  keeps being counted and the link keeps being checked while everything else
//  happens - which is the only reason any of the timeouts mean anything.
//
//  The rules this file orchestrates are specified, and tested, in
//  brain/dustebrain/body/simbody.py and brain/tests/test_simbody.py.
// =============================================================================
#include <Arduino.h>

#include "src/config/pins.h"
#include "src/config/settings.h"
#include "src/hw/leds.h"
#include "src/hw/lid.h"
#include "src/link/brainLink.h"
#include "src/motor/motors.h"
#include "src/safety/reflex.h"

static uint32_t lastHeartbeatLog = 0;

void setup() {
    Serial.begin(SERIAL_BAUD);

    // Motors first, and stopped, before anything else can ask them to move.
    motors.begin();
    reflex.begin();
    brainLink.begin();

    const bool okLid  = lid.begin();
    const bool okLeds = leds.begin();
    leds.set(LED_SLEEP);          // dim blue until the brain says hello

    Serial.println();
    Serial.printf("DUST-E BODY v%s  lid:%d leds:%d\n", DUSTE_BODY_VERSION, okLid, okLeds);
    Serial.println("waiting for the brain. motors are stopped and stay that way.");
}

void loop() {
    const uint32_t now = millis();

    brainLink.poll(now);      // commands land
    reflex.enforce(now);      // safety decides what survives
    motors.tick(now);         // only now do the wheels hear about it

    lid.update(now);
    leds.update(now);
    brainLink.sendTelemetry(now);

    // A heartbeat on the console. The fastest way to tell a hung loop from a
    // hung mechanism when there is a demo in ten minutes.
    if ((uint32_t)(now - lastHeartbeatLog) > 5000) {
        lastHeartbeatLog = now;
        Serial.printf("[hb] inhibit=%-16s l=%4d r=%4d motion_ok=%d estop=%d rx=%lu crc_err=%lu\n",
                      inhibitName(reflex.inhibit()), motors.leftPct(), motors.rightPct(),
                      (int)reflex.motionOk(now), (int)reflex.estopActive(),
                      (unsigned long)brainLink.received(), (unsigned long)brainLink.crcErrors());
    }
}
