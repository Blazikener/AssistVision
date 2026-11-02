// Pin map and rig constants. Defaults target the Freenove ESP32-S3-WROOM CAM
// (N16R8, OV2640, same camera wiring as Espressif's ESP32-S3-EYE). Check your
// board's silkscreen before wiring: clone boards move pins around.
#pragma once

#define FW_VERSION "0.3.0"

// ---- camera (ESP32-S3-EYE / Freenove S3 CAM mapping) ----
#define CAM_PIN_PWDN   -1
#define CAM_PIN_RESET  -1
#define CAM_PIN_XCLK   15
#define CAM_PIN_SIOD   4
#define CAM_PIN_SIOC   5
#define CAM_PIN_D7     16
#define CAM_PIN_D6     17
#define CAM_PIN_D5     18
#define CAM_PIN_D4     12
#define CAM_PIN_D3     10
#define CAM_PIN_D2     8
#define CAM_PIN_D1     9
#define CAM_PIN_D0     11
#define CAM_PIN_VSYNC  6
#define CAM_PIN_HREF   7
#define CAM_PIN_PCLK   13

// ---- HX711 load-cell amplifier ----
#define HX711_DOUT     1
#define HX711_SCK      2

// ---- 28BYJ-48 stepper through a ULN2003 driver ----
#define STEP_IN1       14
#define STEP_IN2       21
#define STEP_IN3       47
#define STEP_IN4       41
// 28BYJ-48: 32 steps/rev x 63.68 gearbox, half-stepped = 4075.8 half-steps/rev
// (the often-quoted 4096 assumes a 64:1 gearbox; the real ratio is 63.684:1).
#define STEPS_PER_REV  4075.77f
#define STEP_US_MIN    1200     // fastest half-step period that does not stall
#define STEP_US_START  3000     // ramp start period

// ---- user interface ----
#define BUTTON_PIN     0        // BOOT button doubles as "scan" trigger

// ---- defaults ----
#define DEFAULT_VIEWS        24
#define DEFAULT_SETTLE_MS    400   // plate wobble decays within ~300 ms on a lazy-susan bearing
#define DEFAULT_JPEG_QUALITY 10    // esp32-camera scale: 0 = best, 63 = worst
