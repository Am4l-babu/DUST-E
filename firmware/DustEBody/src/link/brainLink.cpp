#include "brainLink.h"
#include <Arduino.h>
#include <ArduinoJson.h>
#include <string.h>
#include "../config/settings.h"
#include "../core/crc16.h"
#include "../hw/leds.h"
#include "../hw/lid.h"
#include "../motor/motors.h"
#include "../safety/reflex.h"

BrainLink brainLink;

static const uint8_t PROTOCOL_VERSION = 1;

// Error codes, spelled exactly as brain/dustebrain/body/protocol.py spells them.
static const char *E_SCHEMA        = "E_SCHEMA";
static const char *E_VERSION       = "E_VERSION";
static const char *E_ESTOP_LATCHED = "E_ESTOP_LATCHED";
static const char *E_NOT_INSTALLED = "E_NOT_INSTALLED";
static const char *E_BUSY          = "E_BUSY";

void BrainLink::begin() {
    len_ = 0;
    overlong_ = false;
}

// ---------------------------------------------------------------------------
// Inbound
// ---------------------------------------------------------------------------
void BrainLink::poll(uint32_t now) {
    while (Serial.available()) {
        const char c = (char)Serial.read();
        if (c == '\n' || c == '\r') {
            if (overlong_) { overlong_ = false; len_ = 0; rejected_++; continue; }
            if (len_) {
                line_[len_] = '\0';
                handleLine(line_, len_, now);
                len_ = 0;
            }
        } else if (len_ < LINK_LINE_MAX - 1) {
            line_[len_++] = c;
        } else {
            overlong_ = true;      // discard to end of line rather than truncating
        }
    }
}

void BrainLink::handleLine(char *line, uint16_t len, uint32_t now) {
    if (line[0] != '{') return;                       // boot log, debug prints: not ours

    // Split off the *XXXX suffix.
    char *star = nullptr;
    for (int16_t i = (int16_t)len - 1; i >= 0; --i) {
        if (line[i] == '*') { star = &line[i]; break; }
    }
    if (!star || (uint16_t)(&line[len] - star) != 5) { rejected_++; return; }

    char *endptr = nullptr;
    const uint16_t want = (uint16_t)strtoul(star + 1, &endptr, 16);
    if (endptr != &line[len]) { rejected_++; return; }

    const uint16_t bodyLen = (uint16_t)(star - line);
    const uint16_t got = crc16_ccitt((const uint8_t *)line, bodyLen);
    if (got != want) { crcErrors_++; rejected_++; return; }

    *star = '\0';
    received_++;
    dispatch(line, bodyLen, now);
}

void BrainLink::dispatch(const char *json, uint16_t len, uint32_t now) {
    JsonDocument doc;
    if (deserializeJson(doc, json, len)) { rejected_++; return; }

    const uint32_t seq = doc["seq"] | 0;
    const int v = doc["v"] | PROTOCOL_VERSION;
    if (v != PROTOCOL_VERSION) { sendAck(seq, false, E_VERSION, "", now); return; }

    const char *type = doc["type"] | "";

    if (!strcmp(type, "hello")) {
        reflex.setHandshaken(true);
        reflex.noteLink(now);
        sendAck(seq, true, "", "", now);
        sendHello(now);
        return;
    }
    if (!strcmp(type, "estop")) {
        // Latched here, the moment it is parsed, before anything else runs.
        reflex.latchEstop("brain", now);
        sendAck(seq, true, "", "", now);
        sendEvent("ESTOP", doc["reason"] | "brain", now);
        return;
    }
    if (!strcmp(type, "reset_estop")) {
        const char *err = "";
        const bool ok = reflex.resetEstop(now, err);
        sendAck(seq, ok, ok ? "" : E_BUSY, err, now);
        if (ok) sendEvent("ESTOP_RESET", "cleared by operator", now);
        return;
    }
    if (!strcmp(type, "hb")) {
        reflex.noteLink(now);
        if (doc["ack"] | false) sendAck(seq, true, "", "", now);
        return;
    }
    if (!strcmp(type, "stop")) {
        reflex.clearIntent(now);
        reflex.noteLink(now);
        sendAck(seq, true, "", "", now);
        return;
    }
    if (!strcmp(type, "vel")) {
        if (reflex.estopActive()) { sendAck(seq, false, E_ESTOP_LATCHED, "", now); return; }
        if (!reflex.handshaken())  { sendAck(seq, false, E_SCHEMA, "no hello yet", now); return; }
        reflex.setIntent((int16_t)(doc["l"] | 0), (int16_t)(doc["r"] | 0),
                         (uint16_t)(doc["ttl"] | CMD_TTL_DEFAULT_MS), now);
        sendAck(seq, true, "", "", now);
        return;
    }
    if (!strcmp(type, "motion")) {
        if (reflex.estopActive()) { sendAck(seq, false, E_ESTOP_LATCHED, "", now); return; }
        if (!reflex.handshaken())  { sendAck(seq, false, E_SCHEMA, "no hello yet", now); return; }
        const char *cmd = doc["cmd"] | "STOP";
        const int16_t speed = (int16_t)(doc["speed"] | MOTOR_AUTO_MAX_PCT);
        int16_t l = 0, r = 0;
        if      (!strcmp(cmd, "MOVE_FORWARD"))  { l =  speed; r =  speed; }
        else if (!strcmp(cmd, "MOVE_BACKWARD")) { l = -speed; r = -speed; }
        else if (!strcmp(cmd, "TURN_LEFT"))     { l = -speed; r =  speed; }
        else if (!strcmp(cmd, "TURN_RIGHT"))    { l =  speed; r = -speed; }
        else if (!strcmp(cmd, "ROTATE"))        { l =  speed; r = -speed; }
        else if (strcmp(cmd, "STOP") != 0)      { sendAck(seq, false, E_SCHEMA, "bad cmd", now); return; }
        reflex.setIntent(l, r, (uint16_t)(doc["ms"] | 500), now);
        sendAck(seq, true, "", "", now);
        return;
    }
    if (!strcmp(type, "limits")) {
        // Lower only. setCeiling() clamps to the compile-time wall; there is
        // no message in this protocol that raises a ceiling.
        const uint8_t asked = (uint8_t)(doc["auto_max"] | motors.ceiling());
        if (asked && asked < motors.ceiling()) motors.setCeiling(asked);
        sendAck(seq, true, "", "", now);
        return;
    }
    if (!strcmp(type, "lid")) {
        if (!lid.installed()) { sendAck(seq, false, E_NOT_INSTALLED, "no lid servo", now); return; }
        const char *action = doc["action"] | "";
        if      (!strcmp(action, "OPEN"))  lid.open(now);
        else if (!strcmp(action, "CLOSE")) lid.close(now);
        else if (!strcmp(action, "PEEK"))  lid.peek(now);
        else { sendAck(seq, false, E_SCHEMA, "bad action", now); return; }
        sendAck(seq, true, "", "", now);
        return;
    }
    if (!strcmp(type, "leds")) {
        uint8_t pattern = LED_IDLE;
        if (!ledPatternFromName(doc["pattern"] | "", pattern)) {
            sendAck(seq, false, E_SCHEMA, "unknown pattern", now);
            return;
        }
        leds.set(pattern);
        sendAck(seq, true, "", "", now);
        return;
    }
    // Fitted on paper, not on the robot. Refused with a reason rather than
    // silently ignored, so the brain's inventory stays honest.
    if (!strcmp(type, "look") || !strcmp(type, "gesture")) {
        sendAck(seq, false, E_NOT_INSTALLED, "no eye servo", now);
        return;
    }
    if (!strcmp(type, "face")) {
        sendAck(seq, false, E_NOT_INSTALLED, "display is on the UNO Q", now);
        return;
    }
    if (!strcmp(type, "clip") || !strcmp(type, "pcm") || !strcmp(type, "pcm_stop")) {
        sendAck(seq, false, E_NOT_INSTALLED, "no speaker", now);
        return;
    }

    rejected_++;
    sendAck(seq, false, E_SCHEMA, "unknown type", now);
}

// ---------------------------------------------------------------------------
// Outbound
// ---------------------------------------------------------------------------
void BrainLink::sendLine(const char *payload) {
    const uint16_t crc = crc16_ccitt((const uint8_t *)payload, strlen(payload));
    Serial.print(payload);
    Serial.printf("*%04X\n", crc);
}

void BrainLink::sendAck(uint32_t seq, bool ok, const char *err, const char *detail, uint32_t now) {
    JsonDocument doc;
    doc["v"] = PROTOCOL_VERSION;
    doc["seq"] = ++seqOut_;
    doc["t"] = now;
    doc["type"] = "ack";
    doc["ack_seq"] = seq;
    doc["ok"] = ok;
    if (err && *err)       doc["err"] = err;
    if (detail && *detail) doc["detail"] = detail;
    char buf[192];
    serializeJson(doc, buf, sizeof(buf));
    sendLine(buf);
}

void BrainLink::sendEvent(const char *code, const char *text, uint32_t now) {
    JsonDocument doc;
    doc["v"] = PROTOCOL_VERSION;
    doc["seq"] = ++seqOut_;
    doc["t"] = now;
    doc["type"] = "event";
    doc["code"] = code;
    doc["text"] = text;
    char buf[224];
    serializeJson(doc, buf, sizeof(buf));
    sendLine(buf);
}

void BrainLink::sendHello(uint32_t now) {
    JsonDocument doc;
    doc["v"] = PROTOCOL_VERSION;
    doc["seq"] = ++seqOut_;
    doc["t"] = now;
    doc["type"] = "hello";
    doc["fw"] = DUSTE_BODY_VERSION;
    JsonObject limits = doc["limits"].to<JsonObject>();
    limits["auto_max"] = MOTOR_AUTO_MAX_PCT;
    limits["manual_max"] = MOTOR_MANUAL_MAX_PCT;
    limits["ttl_max"] = CMD_TTL_MAX_MS;
    // The same honesty rule as DustEWeb: "configured" means the firmware is
    // driving those pins, not that anything was detected.
    JsonObject hw = doc["hw"].to<JsonObject>();
    hw["motors"]     = "configured";
    hw["lid_servo"]  = HW_LID_SERVO  ? "configured" : "not_installed";
    hw["leds"]       = HW_LEDS       ? "configured" : "not_installed";
    hw["tof_throat"] = HW_TOF_THROAT ? "configured" : "not_installed";
    hw["speaker"]    = HW_SPEAKER    ? "configured" : "not_installed";
    hw["eye"]        = HW_EYE_SERVO  ? "configured" : "not_installed";
    hw["battery"]    = "see_telemetry";
    hw["lid_safety"] = HW_TOF_THROAT ? "obstruction_detect" : "degraded_slow_close";
    char buf[512];
    serializeJson(doc, buf, sizeof(buf));
    sendLine(buf);
}

void BrainLink::sendTelemetry(uint32_t now) {
    if ((uint32_t)(now - lastTelemetry_) < TELEMETRY_MS) return;
    lastTelemetry_ = now;

    JsonDocument doc;
    doc["v"] = PROTOCOL_VERSION;
    doc["seq"] = ++seqOut_;
    doc["t"] = now;
    doc["type"] = "telemetry";
    doc["ml"] = motors.leftPct();
    doc["mr"] = motors.rightPct();
    doc["tl"] = motors.leftTarget();
    doc["tr"] = motors.rightTarget();
    doc["ceiling"] = motors.ceiling();
    doc["estop"] = reflex.estopActive();
    doc["estop_reason"] = reflex.estopReason();
    doc["inhibit"] = inhibitName(reflex.inhibit());
    doc["motion_ok"] = reflex.motionOk(now);
    doc["lid"] = lid.stateName();
    doc["leds"] = ledPatternName(leds.pattern());
    // No pack instrumented on this board: null, never a fabricated number.
    if (reflex.batteryKnown()) doc["battery_mv"] = reflex.batteryMv();
    else                       doc["battery_mv"] = nullptr;
    JsonObject link = doc["link"].to<JsonObject>();
    link["crc_err"] = crcErrors_;
    link["rejected"] = rejected_;
    link["rx"] = received_;
    doc["uptime"] = now;

    char buf[512];
    serializeJson(doc, buf, sizeof(buf));
    sendLine(buf);
}
