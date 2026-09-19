// =============================================================================
//  xiao_motor_test.ino - standalone bring-up test for the XIAO ESP32-S3 +
//  L298N, on the pin map firmware/DustEBody actually uses.
//
//  This is the test tests/l298n_motor_test and tests/obstacle_avoid_test used
//  to be. Both of those drove the L298N from the Arduino UNO Q; the driver
//  moved to the XIAO (docs/COMPANION_ARCHITECTURE.md section 6.2, decided
//  2026-09-17), so this test replaces them for motor bring-up. They stay in
//  the repo as a record of the earlier wiring - see the note at the top of
//  each.
//
//  Board: Seeed XIAO ESP32-S3 (plain). Unlike the UNO Q, this one has a real
//  PlatformIO target - `pio run` in this folder actually builds.
//
//  Wiring, exactly as firmware/DustEBody/src/config/pins.h and
//  src/motor/motors.cpp:
//    D0 (GPIO1) -> L298N IN1   left  motor, PWM        10k pull-down to GND
//    D1 (GPIO2) -> L298N IN2   left  motor, PWM
//    D8 (GPIO7) -> L298N IN3   right motor, PWM         10k pull-down to GND
//    D9 (GPIO8) -> L298N IN4   right motor, PWM
//    L298N ENA / ENB jumpers ON (not driven from the XIAO - see motors.cpp
//    for why: 4 GPIOs instead of 6)
//    L298N GND  -> XIAO GND  (mandatory - the single most common "nothing
//                             happens" cause)
//    L298N +12V -> external motor supply, NEVER the XIAO's 5V/3V3 pin
//
//  Driving scheme (same as motors.cpp): PWM on INx with the other IN of that
//  pair held LOW is forward; swap which one carries the PWM for reverse; both
//  LOW is a brake, not a coast.
//
//  If a motor does not spin: check the common ground first, then swap its
//  two OUT wires rather than rewiring code.
//
//  Known trap this test exists to catch before firmware/DustEBody ever runs
//  the full stack: without the 10k pull-downs on IN1/IN2/IN3/IN4, both
//  motors can twitch the instant power is applied, before setup() ever runs.
//  Watch for that on first power-up, wheels OFF THE GROUND, before trusting
//  anything else about this board.
// =============================================================================

const int PIN_L_IN1 = 1;   // D0
const int PIN_L_IN2 = 2;   // D1
const int PIN_R_IN3 = 7;   // D8
const int PIN_R_IN4 = 8;   // D9

const uint32_t PWM_FREQ_HZ = 5000;
const uint8_t  PWM_BITS    = 8;
const uint8_t  FULL_DUTY   = 200;   // not 255: see the note in the loop() header

#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  #define PWM_ATTACH(pin)        ledcAttach((pin), PWM_FREQ_HZ, PWM_BITS)
  #define PWM_WRITE(pin, ch, d)  ledcWrite((pin), (d))
#else
  #define PWM_ATTACH(pin)        /* channels set up explicitly below */
  #define PWM_WRITE(pin, ch, d)  ledcWrite((ch), (d))
#endif

const uint8_t CH_L_IN1 = 0, CH_L_IN2 = 1, CH_R_IN3 = 2, CH_R_IN4 = 3;

void stopAll() {
    digitalWrite(PIN_L_IN1, LOW); digitalWrite(PIN_L_IN2, LOW);
    digitalWrite(PIN_R_IN3, LOW); digitalWrite(PIN_R_IN4, LOW);
    PWM_WRITE(PIN_L_IN1, CH_L_IN1, 0);
    PWM_WRITE(PIN_L_IN2, CH_L_IN2, 0);
    PWM_WRITE(PIN_R_IN3, CH_R_IN3, 0);
    PWM_WRITE(PIN_R_IN4, CH_R_IN4, 0);
}

// isLeft picks the pin pair; forward picks which one of the pair gets PWM.
void driveOne(bool isLeft, bool forward, uint8_t duty) {
    const int pwmPin  = isLeft ? (forward ? PIN_L_IN1 : PIN_L_IN2)
                                : (forward ? PIN_R_IN3 : PIN_R_IN4);
    const int lowPin  = isLeft ? (forward ? PIN_L_IN2 : PIN_L_IN1)
                                : (forward ? PIN_R_IN4 : PIN_R_IN3);
    const uint8_t ch  = isLeft ? (forward ? CH_L_IN1 : CH_L_IN2)
                                : (forward ? CH_R_IN3 : CH_R_IN4);
    (void)pwmPin;   // unused on the core-2.x PWM_WRITE branch (channel-addressed, not pin-addressed)
    digitalWrite(lowPin, LOW);
    PWM_WRITE(pwmPin, ch, duty);
}

void setup() {
    Serial.begin(115200);
    delay(300);
    Serial.println();
    Serial.println("=== XIAO ESP32-S3 + L298N bring-up test ===");
    Serial.println("Wiring: see the header comment in this file.");
    Serial.println("WHEELS SHOULD BE OFF THE GROUND for this test.");

    pinMode(PIN_L_IN1, OUTPUT); digitalWrite(PIN_L_IN1, LOW);
    pinMode(PIN_L_IN2, OUTPUT); digitalWrite(PIN_L_IN2, LOW);
    pinMode(PIN_R_IN3, OUTPUT); digitalWrite(PIN_R_IN3, LOW);
    pinMode(PIN_R_IN4, OUTPUT); digitalWrite(PIN_R_IN4, LOW);

#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    PWM_ATTACH(PIN_L_IN1); PWM_ATTACH(PIN_L_IN2);
    PWM_ATTACH(PIN_R_IN3); PWM_ATTACH(PIN_R_IN4);
#else
    ledcSetup(CH_L_IN1, PWM_FREQ_HZ, PWM_BITS); ledcAttachPin(PIN_L_IN1, CH_L_IN1);
    ledcSetup(CH_L_IN2, PWM_FREQ_HZ, PWM_BITS); ledcAttachPin(PIN_L_IN2, CH_L_IN2);
    ledcSetup(CH_R_IN3, PWM_FREQ_HZ, PWM_BITS); ledcAttachPin(PIN_R_IN3, CH_R_IN3);
    ledcSetup(CH_R_IN4, PWM_FREQ_HZ, PWM_BITS); ledcAttachPin(PIN_R_IN4, CH_R_IN4);
#endif

    stopAll();
    delay(1000);
    Serial.println("Setup complete. Starting sequence in 2s...");
    delay(2000);
}

// FULL_DUTY is 200/255 (~78%), not 255: this is a bring-up test run with
// wheels off the ground, and a bit of headroom means a wiring mistake shows
// up as "spinning too fast to be right" rather than immediately cooking a
// motor at 100% duty for six straight seconds.
void loop() {
    Serial.println("--- LEFT motor FORWARD, isolated ---");
    driveOne(true, true, FULL_DUTY);
    delay(3000);
    stopAll();
    delay(1000);

    Serial.println("--- LEFT motor REVERSE, isolated ---");
    driveOne(true, false, FULL_DUTY);
    delay(3000);
    stopAll();
    delay(1500);

    Serial.println("--- RIGHT motor FORWARD, isolated ---");
    driveOne(false, true, FULL_DUTY);
    delay(3000);
    stopAll();
    delay(1000);

    Serial.println("--- RIGHT motor REVERSE, isolated ---");
    driveOne(false, false, FULL_DUTY);
    delay(3000);
    stopAll();
    delay(1500);

    Serial.println("--- BOTH motors FORWARD together ---");
    driveOne(true, true, FULL_DUTY);
    driveOne(false, true, FULL_DUTY);
    delay(3000);
    stopAll();

    Serial.println("--- Cycle done. Pausing 3s before repeat. ---");
    delay(3000);
}
