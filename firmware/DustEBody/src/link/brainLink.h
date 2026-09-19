// =============================================================================
//  brainLink.h - the UNO Q on the other end of the USB cable.
//
//  Wire format, identical to brain/dustebrain/body/protocol.py:
//
//      {"v":1,"seq":1042,"t":583211,"type":"vel","l":35,"r":31,"ttl":300}*7A3F
//
//  One JSON object per line, CRC-16/CCITT-FALSE over everything before the
//  '*'. A line that fails the check is dropped and counted; it is never
//  half-parsed and never guessed at. Anything that does not start with '{' is
//  ignored, so the boot log and stray printf debugging share the port happily.
//
//  This module validates and dispatches. It does not decide whether the robot
//  may move - that is reflex.cpp, which runs after every command has landed.
// =============================================================================
#pragma once
#include <stdint.h>
#include "../config/settings.h"

class BrainLink {
  public:
    void begin();
    void poll(uint32_t now);                 // read serial, dispatch complete lines
    void sendTelemetry(uint32_t now);        // rate limited to TELEMETRY_MS

    void sendEvent(const char *code, const char *text, uint32_t now);

    uint32_t crcErrors()   const { return crcErrors_; }
    uint32_t rejected()    const { return rejected_; }
    uint32_t received()    const { return received_; }

  private:
    void handleLine(char *line, uint16_t len, uint32_t now);
    void dispatch(const char *json, uint16_t len, uint32_t now);
    void sendAck(uint32_t seq, bool ok, const char *err, const char *detail, uint32_t now);
    void sendHello(uint32_t now);
    void sendLine(const char *payload);

    char     line_[LINK_LINE_MAX];
    uint16_t len_ = 0;
    bool     overlong_ = false;
    uint32_t seqOut_ = 0;
    uint32_t lastTelemetry_ = 0;
    uint32_t crcErrors_ = 0;
    uint32_t rejected_ = 0;
    uint32_t received_ = 0;
};

extern BrainLink brainLink;
