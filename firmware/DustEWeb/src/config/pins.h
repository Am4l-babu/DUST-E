// =============================================================================
//  pins.h - GPIO map for DUST-E WEB REMOTE (plain ESP32 dev module).
//
//  This is NOT the DUST-E pin map. DUST-E is an ESP32-S3 driving servos;
//  this board is a classic ESP32 driving an L298N and two DC motors. The two
//  firmwares share no pins, no protocol and no wiring.
//
//  The assignment below is the one already proven on the bench by
//  tests/l298n_motor_test - do not renumber it without re-running that sketch.
// =============================================================================
#pragma once

// ---------------------------------------------------------------------------
// L298N motor driver
//
//   ENA/ENB are PWM (speed). IN1..IN4 are plain digital (direction).
//   L298N GND -> ESP32 GND is mandatory; without the common ground the
//   driver sees no logic levels at all and "nothing happens".
//   L298N +12V -> external motor supply. Never the ESP32 5V/3V3 pin.
// ---------------------------------------------------------------------------
#define PIN_MOTOR_ENA 18   // left motor  speed  (PWM)
#define PIN_MOTOR_ENB 19   // right motor speed  (PWM)
#define PIN_MOTOR_IN1 27   // left motor  direction A
#define PIN_MOTOR_IN2 26   // left motor  direction B
#define PIN_MOTOR_IN3 25   // right motor direction A
#define PIN_MOTOR_IN4 33   // right motor direction B

// ---------------------------------------------------------------------------
// Vision link - UART2 to an optional camera board (ESP32-CAM, XIAO ESP32-S3
// Sense, anything that can print a line). Text protocol, see
// src/vision/vision.h. Cross the wires: camera board TX -> PIN_VISION_RX.
// Both boards must share GND. 3.3 V logic on both sides.
//
// GPIO 16/17 are free on a WROOM module. On a WROVER module they are the
// PSRAM bus and must be moved (13/14 are free).
// ---------------------------------------------------------------------------
#define PIN_VISION_RX 16   // <- camera board TX
#define PIN_VISION_TX 17   // -> camera board RX (unused by the current protocol)

// ---------------------------------------------------------------------------
// Eyes - two SSD1306 128x64 I2C OLEDs, one eye each (src/face/eyes.h).
//
//   Default: both on ONE bus, left at 0x3C and right at 0x3D. Most modules
//   ship at 0x3C; move the address resistor on the back of the right-hand
//   one (marked 0x78 / 0x7A) to get 0x3D.
//
//   Can't resolder? Set EYES_SPLIT_BUS in settings.h and wire the right eye
//   to its own bus on PIN_EYE_R_SDA/SCL instead - both modules can then stay
//   at 0x3C. 5 and 15 are strapping pins that want to be HIGH at boot, which
//   is exactly what the OLED module's pull-ups do to them.
//
//   OLED VCC -> 3V3. The hardware I2C pins (21/22) matter: the SSD1306 sends
//   a whole 1 KB frame per eye, and a slow bus is a slow blink.
// ---------------------------------------------------------------------------
#define PIN_EYE_SDA   21   // both eyes (or the left eye only, split bus)
#define PIN_EYE_SCL   22
#define PIN_EYE_R_SDA 5    // right eye, EYES_SPLIT_BUS only
#define PIN_EYE_R_SCL 15

// ---------------------------------------------------------------------------
// Speaker - MAX98357A I2S class-D amplifier (src/sound/speaker.h).
//
//   MAX98357A VIN -> 5 V servo/audio rail (not the ESP32 3V3), GND -> GND.
//   SD left floating = mono mix of L+R. GAIN floating = 9 dB.
//   Speaker 4-8 ohm, 3 W max, across the module's + and - (never to GND).
// ---------------------------------------------------------------------------
#define PIN_I2S_BCLK 14
#define PIN_I2S_LRC  32
#define PIN_I2S_DOUT 4

// ---------------------------------------------------------------------------
// Hands - two hobby servos, SG90 / MG90S class (src/hands/hands.h).
//
//   Signal only. Servo red -> a separate 5 V supply of at least 2 A, servo
//   brown -> that supply's GND AND the ESP32 GND. Powering two servos from
//   the ESP32's 5 V pin is the brownout-reset bug everyone hits first.
// ---------------------------------------------------------------------------
#define PIN_HAND_LEFT  13
#define PIN_HAND_RIGHT 23

// ---------------------------------------------------------------------------
// Reserved for later. Deliberately NOT #defined: an undefined pin cannot be
// driven by accident, and the firmware must build and run with none of this
// hardware fitted. Add the #define at the same time as the driver module.
//
//   lid servo ............ PCA9685 channel on the eye I2C bus (no GPIOs left
//                          that are free of strapping duties)
//   WS2812 data .......... 2   (strapping; fine for a data line, it floats at boot)
//   ToF / INA219 ......... on the eye I2C bus (21/22), unique addresses
//   limit switches ....... 34 / 35  (input-only pins, external pull-ups needed)
//
// GPIO 6-11 are the SPI flash and are never available.
// GPIO 12 is the flash-voltage strap: anything pulling it high at boot bricks
// the boot until it is removed. Leave it alone.
// GPIO 34-39 are input-only and have no internal pull-ups.
// ---------------------------------------------------------------------------
