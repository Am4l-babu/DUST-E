// =============================================================================
//  pins.h - GPIO map for the DUST-E BODY (Seeed XIAO ESP32-S3, plain).
//
//  This is NOT the DustE (ESP32-S3-DevKitC) map and NOT the DustEWeb (classic
//  ESP32) map. The XIAO exposes eleven pads and they are all spoken for.
//  Decided 2026-09-17, documented in docs/COMPANION_ARCHITECTURE.md section 6.2.
//
//      pad   GPIO   net
//      D0     1     MOTOR_L_IN1   PWM   10k pull-down REQUIRED
//      D1     2     MOTOR_L_IN2   PWM   10k pull-down REQUIRED
//      D2     3     LED_DATA            330R series, strapping pin (see below)
//      D3     4     SERVO_LID     PWM   servo rail, never the XIAO's 5V
//      D4     5     I2C_SDA             VL53L0X throat, PCA9685 later
//      D5     6     I2C_SCL
//      D6    43     (spare)             reserved for I2S_BCLK
//      D7    44     MOTION_OK     in    100k pull-down REQUIRED
//      D8     7     MOTOR_R_IN3   PWM   10k pull-down REQUIRED
//      D9     8     MOTOR_R_IN4   PWM   10k pull-down REQUIRED
//      D10    9     (spare)             reserved for I2S_DOUT
//
//  The four pull-downs are not optional. While the XIAO is resetting, being
//  flashed or unpowered, its pins are inputs; without them the L298N inputs
//  float and a motor can twitch. They are the cheapest safety part in the
//  build.
//
//  GPIO3 is a strapping pin (JTAG source select) but is only sampled at reset
//  and only matters with an eFuse burned, so a WS2812 data input is harmless
//  there. The motor pins deliberately avoid GPIO43/44, which the boot ROM
//  toggles as UART0.
//
//  The L298N is driven on its IN pins with ENA/ENB jumpered high: 4 GPIOs
//  instead of 6. PWM on IN1 with IN2 low is forward, the reverse is backward,
//  both low is a brake.
// =============================================================================
#pragma once

#define PIN_MOTOR_L_IN1   1
#define PIN_MOTOR_L_IN2   2
#define PIN_MOTOR_R_IN3   7
#define PIN_MOTOR_R_IN4   8

#define PIN_LED_DATA      3
#define PIN_SERVO_LID     4

#define PIN_I2C_SDA       5
#define PIN_I2C_SCL       6

#define PIN_MOTION_OK    44

// Reserved, deliberately NOT #defined so they cannot be driven by accident.
// Add the #define at the same time as the driver module (see settings.h,
// HARDWARE INVENTORY):
//   GPIO 43  I2S_BCLK   \  fitting the MAX98357A also needs a PCA9685, so the
//   GPIO  9  I2S_DOUT   /  lid servo can move off D3 and free it for LRCLK
