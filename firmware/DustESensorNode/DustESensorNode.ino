// =============================================================================
//  DUST-E SENSOR NODE - Arduino UNO Q, MCU side (STM32U585, Zephyr Arduino core)
//
//  This is the UNO Q's contribution to physical safety. It owns every sensor
//  that can stop the robot, and it never touches a motor - the XIAO ESP32-S3
//  ("DustEBody") is the only thing that drives the wheels. The two boards
//  agree on exactly one signal:
//
//      MOTION_OK (this board's D9 -> XIAO D7)
//
//  toggled here every loop pass while nothing this board can see is a hazard,
//  read there as a pulse train (edges required, not a level - see
//  firmware/DustEBody/src/safety/reflex.cpp and
//  brain/dustebrain/body/simbody.py). A crashed MCU, a hung loop, a cut wire
//  and an actual obstacle all stop the pulses, and the XIAO treats them all
//  the same way: forward motion blocked.
//
//  Board: Arduino UNO Q (arduino:zephyr:unoq). Same board, same core, same
//  OLED driver approach as firmware/UselessBox/UselessBox_UnoQ/ - this is a
//  different program for the same physical wiring, repurposed for DUST-E:
//
//      D2  / D4   HC-SR04 #1 TRIG / ECHO   (unchanged)
//      A0  / A1   HC-SR04 #2 TRIG / ECHO   (unchanged)
//      A2  / A3   HC-SR04 #3 TRIG / ECHO   (unchanged)
//      D3         active buzzer            (unchanged)
//      D12        NORMAL MODE switch       (unchanged)
//      D13        IR obstacle sensor       (unchanged)
//      SDA/SCL    SSD1306 OLED (Wire2), + INA219 battery monitor @0x40
//      D5         BUMPER_L   (NC to GND, pull-up: a broken wire reads "hit")
//      D6         BUMPER_R   (same)
//      D7         CLIFF_L    (digital IR reflectance, fail-safe polarity)
//      D8         CLIFF_R    (same)
//      D9         MOTION_OK  -> XIAO D7
//      D10        ESTOP_SENSE (aux NC contact of the mushroom switch)
//      D11        spare (the lid servo moved to the XIAO)
//
//  See docs/COMPANION_ARCHITECTURE.md section 6.2 for the full reasoning.
//
//  HONESTY RULE: cliff sensors and bumpers are not fitted on the bench yet
//  (docs/COMPANION_BOM.md rows 8-9). HW_CLIFF and HW_BUMPERS below are false
//  until they are. An uninstalled input is never read as a hazard AND never
//  read as "safe" - it is simply left out of the hazard vote, and its true
//  state is reported honestly in the periodic status line so nobody mistakes
//  "not wired" for "checked and clear". The brain is the thing that decides
//  whether autonomy may run without them (it must not - see the BOM).
// =============================================================================
#include <Wire.h>
#include <Adafruit_GFX.h>

// ---------------------------------------------------------------------------
// Hardware inventory - flip to true at the same time the part is soldered in.
// ---------------------------------------------------------------------------
#define HW_CLIFF     0   // TCRT5000 x2 - docs/COMPANION_BOM.md row 8
#define HW_BUMPERS   0   // micro limit switch x2 - row 9
#define HW_ESTOP     0   // aux NC contact wired to D10 - fit with the E-stop, row 1
#define HW_BATTERY   0   // INA219 on Wire2 @0x40 - row 4
#define HW_IR_THROAT 1   // the IR sensor already on D13 from the UselessBox wiring

// ---------------------------------------------------------------------------
// Pins
// ---------------------------------------------------------------------------
#define SENSOR_COUNT 3
const int TRIG_PINS[SENSOR_COUNT] = { 2, A0, A2 };
const int ECHO_PINS[SENSOR_COUNT] = { 4, A1, A3 };
#define ECHO_TIMEOUT_US 12000UL     // ~2 m; keeps a no-echo read from stalling the loop
#define STOP_DISTANCE_CM 20.0f      // any sensor closer than this is a hazard

#define BUZZER_PIN 3
#define IR_THROAT_PIN 13
#define IR_THROAT_NO_OBJECT HIGH    // flip if your module's output logic is opposite

#define SWITCH_NORMAL_PIN 12        // NORMAL MODE gag switch, active LOW

#define PIN_BUMPER_L   5
#define PIN_BUMPER_R   6
#define PIN_CLIFF_L    7
#define PIN_CLIFF_R    8
#define PIN_MOTION_OK  9
#define PIN_ESTOP_SENSE 10

// Bumpers and E-stop sense are wired NC-to-GND through a pull-up: closed
// circuit (LOW) is the safe, at-rest state. A press OR a broken wire both
// open the circuit and read HIGH - "unknown" and "hit" are deliberately the
// same failure here.
#define CONTACT_SAFE LOW
#define CONTACT_HAZARD HIGH

// Cliff sensor polarity depends on the module; TCRT5000-style reflectance
// boards read LOW when the beam bounces back off a floor (safe) and HIGH
// when there is nothing to reflect off (a drop-off). Flip if yours differs.
#define CLIFF_SAFE LOW
#define CLIFF_HAZARD HIGH

#define INA219_ADDR 0x40

// ---------------------------------------------------------------------------
// OLED - same minimal driver as UselessBox_UnoQ: Adafruit_SSD1306 does not
// compile against the Zephyr core, and U8g2's hardware-I2C path is hard-wired
// to Wire, but on the UNO Q the header SDA/SCL pins are i2c3 (Wire2). Adafruit
// GFX only needs drawPixel(), so subclass it and drive the bus directly.
// ---------------------------------------------------------------------------
#define OLED_BLACK 0
#define OLED_WHITE 1
#define FRAME_MS 50

class OledFace : public Adafruit_GFX {
  public:
    OledFace() : Adafruit_GFX(128, 64) {}

    bool begin() {
        TwoWire *buses[] = { &Wire2, &Wire1, &Wire };
        const uint8_t addrs[] = { 0x3C, 0x3D };
        for (uint8_t b = 0; b < 3; b++) {
            buses[b]->begin();
            for (uint8_t a = 0; a < 2; a++) {
                buses[b]->beginTransmission(addrs[a]);
                if (buses[b]->endTransmission() == 0) {
                    wire = buses[b];
                    addr = addrs[a];
                    initPanel();
                    return true;
                }
            }
        }
        return false;
    }

    void drawPixel(int16_t x, int16_t y, uint16_t color) override {
        if (x < 0 || x >= 128 || y < 0 || y >= 64) return;
        uint16_t i = x + (y / 8) * 128;
        uint8_t bit = 1 << (y & 7);
        if (color) buf[i] |= bit; else buf[i] &= ~bit;
    }

    void clear() { memset(buf, 0, sizeof(buf)); }

    void flush() {
        cmd(0x21); cmd(0); cmd(127);
        cmd(0x22); cmd(0); cmd(7);
        for (uint16_t i = 0; i < sizeof(buf); i += 128) {
            wire->beginTransmission(addr);
            wire->write((uint8_t)0x40);
            wire->write(buf + i, 128);
            wire->endTransmission();
        }
    }

  private:
    void cmd(uint8_t c) {
        wire->beginTransmission(addr);
        wire->write((uint8_t)0x00);
        wire->write(c);
        wire->endTransmission();
    }

    void initPanel() {
        static const uint8_t seq[] = {
            0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40,
            0x8D, 0x14, 0x20, 0x00, 0xA1, 0xC8, 0xDA, 0x12,
            0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0x2E, 0xAF
        };
        for (uint8_t i = 0; i < sizeof(seq); i++) cmd(seq[i]);
    }

    TwoWire *wire = nullptr;
    uint8_t addr = 0x3C;
    uint8_t buf[1024];
};

OledFace face;
bool hasDisplay = false;
unsigned long nextFrame = 0;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
int sensorIndex = 0;
float lastDistanceCm[SENSOR_COUNT] = { -1, -1, -1 };

bool motionOkLevel = LOW;
unsigned long lastStatusPrint = 0;
#define STATUS_PRINT_MS 1000

bool buzzing = false;
unsigned long buzzStopAt = 0;
#define BUZZER_DURATION_MS 10000UL

// ---------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    delay(300);
    Serial.println();
    Serial.println(F("=== DUST-E SENSOR NODE (UNO Q) ==="));

    for (int i = 0; i < SENSOR_COUNT; i++) {
        pinMode(TRIG_PINS[i], OUTPUT);
        digitalWrite(TRIG_PINS[i], LOW);
        pinMode(ECHO_PINS[i], INPUT);
    }

    pinMode(BUZZER_PIN, OUTPUT);
    digitalWrite(BUZZER_PIN, LOW);

    pinMode(IR_THROAT_PIN, INPUT);
    pinMode(SWITCH_NORMAL_PIN, INPUT_PULLUP);

    pinMode(PIN_BUMPER_L, INPUT_PULLUP);
    pinMode(PIN_BUMPER_R, INPUT_PULLUP);
    pinMode(PIN_CLIFF_L, INPUT);
    pinMode(PIN_CLIFF_R, INPUT);
    pinMode(PIN_ESTOP_SENSE, INPUT_PULLUP);

    pinMode(PIN_MOTION_OK, OUTPUT);
    digitalWrite(PIN_MOTION_OK, LOW);   // starts low: no pulses until the loop runs

    hasDisplay = face.begin();
    if (hasDisplay) { face.clear(); face.flush(); }

    if (HW_BATTERY) {
        Wire2.beginTransmission(INA219_ADDR);
        if (Wire2.endTransmission() != 0) {
            Serial.println(F("WARN: HW_BATTERY set but INA219 did not answer at 0x40"));
        }
    }

    // Serial (BridgeMonitor<>, Zephyr core) has print()/println() but no printf().
    Serial.print(F("display:")); Serial.print(hasDisplay);
    Serial.print(F(" cliff:"));  Serial.print(HW_CLIFF);
    Serial.print(F(" bumpers:")); Serial.print(HW_BUMPERS);
    Serial.print(F(" estop:")); Serial.print(HW_ESTOP);
    Serial.print(F(" battery:")); Serial.println(HW_BATTERY);
    Serial.println(F("MOTION_OK will start toggling once the loop is running."));
}

// ---------------------------------------------------------------------------
// One HC-SR04, blocking on pulseIn() for up to ECHO_TIMEOUT_US. That is fine
// here specifically because this board drives no motor: the worst case is a
// slightly stale reading on the OTHER two sensors this pass, never a stalled
// motor update. (On the XIAO this same call would be a straight-up bug - see
// docs/COMPANION_ARCHITECTURE.md section 6.2, "why sensors on the MCU are
// acceptable here".)
// ---------------------------------------------------------------------------
float readDistanceCm(int trigPin, int echoPin) {
    digitalWrite(trigPin, LOW);
    delayMicroseconds(2);
    digitalWrite(trigPin, HIGH);
    delayMicroseconds(10);
    digitalWrite(trigPin, LOW);

    unsigned long duration = pulseIn(echoPin, HIGH, ECHO_TIMEOUT_US);
    if (duration == 0) return -1.0f;          // no echo: out of range, not a reading of 0
    return duration * 0.0343f / 2.0f;
}

void pollOneUltrasonic() {
    lastDistanceCm[sensorIndex] = readDistanceCm(TRIG_PINS[sensorIndex], ECHO_PINS[sensorIndex]);
    sensorIndex = (sensorIndex + 1) % SENSOR_COUNT;
}

bool ultrasonicHazard() {
    for (int i = 0; i < SENSOR_COUNT; i++) {
        if (lastDistanceCm[i] > 0 && lastDistanceCm[i] < STOP_DISTANCE_CM) return true;
    }
    return false;
}

bool bumperHazard() {
    if (!HW_BUMPERS) return false;
    return digitalRead(PIN_BUMPER_L) == CONTACT_HAZARD
        || digitalRead(PIN_BUMPER_R) == CONTACT_HAZARD;
}

bool cliffHazard() {
    if (!HW_CLIFF) return false;
    return digitalRead(PIN_CLIFF_L) == CLIFF_HAZARD
        || digitalRead(PIN_CLIFF_R) == CLIFF_HAZARD;
}

bool estopHazard() {
    if (!HW_ESTOP) return false;
    return digitalRead(PIN_ESTOP_SENSE) == CONTACT_HAZARD;
}

// ---------------------------------------------------------------------------
void handleIrThroatBuzzer() {
    if (buzzing) {
        if (millis() >= buzzStopAt) { digitalWrite(BUZZER_PIN, LOW); buzzing = false; }
        return;
    }
    if (HW_IR_THROAT && digitalRead(IR_THROAT_PIN) == IR_THROAT_NO_OBJECT) {
        digitalWrite(BUZZER_PIN, HIGH);
        buzzing = true;
        buzzStopAt = millis() + BUZZER_DURATION_MS;
    }
}

void drawFace(bool hazard) {
    if (!hasDisplay) return;
    if (millis() < nextFrame) return;
    nextFrame = millis() + FRAME_MS;

    face.clear();
    // Deliberately minimal: this board's face is a status indicator, not the
    // expressive one - FACE_SET commands from the brain go through the XIAO's
    // lid/leds path today and the OLED here purely reports sensor node health.
    face.fillRoundRect(30, 18, 20, hazard ? 8 : 20, 6, OLED_WHITE);   // "eye" narrows on hazard
    face.fillRoundRect(78, 18, 20, hazard ? 8 : 20, 6, OLED_WHITE);
    if (hazard) {
        face.drawLine(40, 50, 88, 50, OLED_WHITE);   // flat "concerned" mouth
    } else {
        face.drawLine(40, 48, 64, 54, OLED_WHITE);
        face.drawLine(64, 54, 88, 48, OLED_WHITE);
    }
    face.flush();
}

void printStatus(bool hazard, const char *why) {
    if (millis() - lastStatusPrint < STATUS_PRINT_MS) return;
    lastStatusPrint = millis();
    // Serial (BridgeMonitor<>, Zephyr core) has print()/println() but no printf().
    Serial.print(F("[sensor] hazard=")); Serial.print(hazard);
    Serial.print(F(" (")); Serial.print(why); Serial.print(F(")"));
    Serial.print(F(" us=")); Serial.print(lastDistanceCm[0], 0);
    Serial.print(F("/")); Serial.print(lastDistanceCm[1], 0);
    Serial.print(F("/")); Serial.print(lastDistanceCm[2], 0);
    Serial.print(F(" cliff=")); Serial.print(HW_CLIFF ? digitalRead(PIN_CLIFF_L) : -1);
    Serial.print(F(",")); Serial.print(HW_CLIFF ? digitalRead(PIN_CLIFF_R) : -1);
    Serial.print(F(" bump=")); Serial.print(HW_BUMPERS ? digitalRead(PIN_BUMPER_L) : -1);
    Serial.print(F(",")); Serial.print(HW_BUMPERS ? digitalRead(PIN_BUMPER_R) : -1);
    Serial.print(F(" estop=")); Serial.print(HW_ESTOP ? digitalRead(PIN_ESTOP_SENSE) : -1);
    Serial.print(F(" normal_sw=")); Serial.print(digitalRead(SWITCH_NORMAL_PIN) == LOW);
    Serial.print(F(" motion_ok=")); Serial.println(motionOkLevel);
}

// ---------------------------------------------------------------------------
void loop() {
    pollOneUltrasonic();
    handleIrThroatBuzzer();

    const char *why = "clear";
    bool hazard = false;
    if (ultrasonicHazard())      { hazard = true; why = "obstacle"; }
    else if (cliffHazard())      { hazard = true; why = "cliff"; }
    else if (bumperHazard())     { hazard = true; why = "bumper"; }
    else if (estopHazard())      { hazard = true; why = "estop_sense"; }

    // Toggle every pass rather than on a timer: this IS the liveness signal,
    // so its own cadence should track the loop's health directly. Worst-case
    // loop period here is one pulseIn() timeout (12 ms), giving the XIAO's
    // 150 ms / 2-edge window enormous margin.
    if (!hazard) {
        motionOkLevel = !motionOkLevel;
        digitalWrite(PIN_MOTION_OK, motionOkLevel);
    } else {
        // Hold the line low while a hazard is active. A held level produces
        // no edges, which is exactly the "no pulses" state the XIAO already
        // treats as a veto - the same code path as a dead sensor node.
        motionOkLevel = LOW;
        digitalWrite(PIN_MOTION_OK, LOW);
    }

    drawFace(hazard);
    printStatus(hazard, why);
}
