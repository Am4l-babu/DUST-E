// =============================================================================
//  settings.h - every tunable number in the DUST-E body.
//
//  These values are the same numbers as the `body:` block in
//  brain/config/default.yaml. That is not a coincidence and not decoration:
//  brain/dustebrain/body/simbody.py is a reference implementation of the rules
//  below, and brain/tests/test_simbody.py is the failsafe matrix as tests. If
//  a number here and a number there disagree, the tests are testing a robot
//  that does not exist.
//
//  Anything that can stop a motor lives in this file. Nothing in the protocol
//  can raise a ceiling defined here - the `limits` message may only lower one.
// =============================================================================
#pragma once
#include <stdint.h>

#define DUSTE_BODY_VERSION "0.1.0"
#define SERIAL_BAUD 115200

// ---------------------------------------------------------------------------
// LINK (USB CDC to the UNO Q)
// ---------------------------------------------------------------------------
static const uint16_t LINK_TIMEOUT_MS      = 300;   // no heartbeat -> hard stop
static const uint16_t CMD_TTL_DEFAULT_MS   = 300;   // a velocity command expires
static const uint16_t CMD_TTL_MAX_MS       = 500;   // ...and is clamped to this
static const uint16_t TELEMETRY_MS         = 50;    // 20 Hz
static const uint16_t LINK_LINE_MAX             = 512;   // longer inbound lines are dropped

// ---------------------------------------------------------------------------
// MOTORS
//
//   Percent in, percent out: the brain never sends raw duty. MIN_PCT exists
//   because a loaded DC motor below roughly a quarter duty buzzes and heats
//   instead of turning, so any non-zero request is lifted to it.
//
//   DECEL_MULT is the one asymmetry that matters: stopping is always allowed
//   to outrun starting. Never set it below 1.
// ---------------------------------------------------------------------------
static const uint32_t MOTOR_PWM_FREQ_HZ    = 5000;
static const uint8_t  MOTOR_PWM_BITS       = 8;
static const uint8_t  MOTOR_AUTO_MAX_PCT   = 45;    // ceiling while driving itself
static const uint8_t  MOTOR_MANUAL_MAX_PCT = 70;    // ceiling for a human at the dashboard
static const uint8_t  MOTOR_MIN_PCT        = 22;
static const uint8_t  MOTOR_ACCEL_PCT      = 6;     // per tick
static const uint8_t  MOTOR_DECEL_MULT     = 3;
static const uint16_t MOTOR_TICK_MS        = 20;

// ---------------------------------------------------------------------------
// MOTION_OK - the sensor veto from the UNO Q MCU.
//
//   One wire, toggled by the MCU's main loop while its sensors see no hazard.
//   Edges are required, not a level: a stuck-high wire, a stuck-low wire, a
//   cut wire, a crashed MCU and a hung loop then all look identical, and are
//   all handled identically.
//
//   While the pulses are absent, only a short slow reverse is allowed. Every
//   sensor faces forward or down-forward, so backing away is the one safe
//   escape - and the cooldown stops it becoming a habit.
// ---------------------------------------------------------------------------
static const uint16_t MOTION_OK_WINDOW_MS   = 150;
static const uint8_t  MOTION_OK_MIN_EDGES   = 2;
static const uint8_t  ESCAPE_DUTY_PCT       = 25;
static const uint16_t ESCAPE_MS             = 800;
static const uint16_t ESCAPE_COOLDOWN_MS    = 2000;


// ---------------------------------------------------------------------------
// BATTERY
//
//   Measured by the INA219 on the UNO Q sensor node and forwarded over the
//   link; the body enforces the limit because the body owns the motors.
//   Until a pack is fitted the value stays unknown and is never invented.
//   These defaults are sized for a 3S Li-ion pack - set yours.
// ---------------------------------------------------------------------------
static const uint16_t BATTERY_LOW_MV      = 10500;  // brain: head home
static const uint16_t BATTERY_CRITICAL_MV = 9800;   // body: refuse to move

// ---------------------------------------------------------------------------
// LID
//
//   Soft-close, eased at both ends, and slow enough that it cannot hurt a
//   hand. Obstruction DETECTION needs the throat ToF; until that is fitted
//   (HW_TOF_THROAT below) the lid reports its safety as degraded rather than
//   pretending, and closes at the slow profile only.
// ---------------------------------------------------------------------------
static const uint8_t  LID_ANGLE_CLOSED   = 12;
static const uint8_t  LID_ANGLE_OPEN     = 96;
static const uint8_t  LID_ANGLE_PEEK     = 34;
static const uint16_t LID_MS_OPEN        = 380;
static const uint16_t LID_MS_CLOSE       = 900;    // soft close
static const uint16_t LID_MS_CLOSE_SAFE  = 1400;   // with no obstruction sensor fitted
static const uint16_t LID_STEP_MS        = 15;
static const uint16_t LID_IDLE_DETACH_MS = 700;    // kills idle jitter and buzz
static const uint16_t LID_HOLD_OPEN_MS   = 3000;
static const uint16_t SERVO_MIN_US       = 500;
static const uint16_t SERVO_MAX_US       = 2500;

// ---------------------------------------------------------------------------
// LEDS
// ---------------------------------------------------------------------------
static const uint16_t LED_COUNT      = 12;
static const uint8_t  LED_BRIGHTNESS = 90;
static const uint16_t LED_FRAME_MS   = 25;

// ---------------------------------------------------------------------------
// HARDWARE INVENTORY
//
//   Fitted or not, as of 2026-09-17. Anything false is reported to the brain
//   as not_installed and its commands are refused with E_NOT_INSTALLED rather
//   than silently ignored. Nothing here is auto-detected, because none of it
//   can be detected on these pins.
// ---------------------------------------------------------------------------
static const bool HW_LID_SERVO   = true;
static const bool HW_LEDS        = true;
static const bool HW_TOF_THROAT  = false;  // lid hand safety - see docs/COMPANION_BOM.md row 10
static const bool HW_SPEAKER     = false;  // needs a PCA9685 first, to free a pin for I2S
static const bool HW_EYE_SERVO   = false;
static const bool HW_FINGER      = false;
