// Seeed Studio XIAO ESP32S3 Sense (OV2640 or OV3660 on the B2B camera connector).
// Camera pins match CAMERA_MODEL_XIAO_ESP32S3 in the ESP32 Arduino core's
// CameraWebServer/camera_pins.h.
#pragma once

#define CAM_PIN_PWDN  -1
#define CAM_PIN_RESET -1
#define CAM_PIN_XCLK  10
#define CAM_PIN_SIOD  40
#define CAM_PIN_SIOC  39
#define CAM_PIN_D7    48
#define CAM_PIN_D6    11
#define CAM_PIN_D5    12
#define CAM_PIN_D4    14
#define CAM_PIN_D3    16
#define CAM_PIN_D2    18
#define CAM_PIN_D1    17
#define CAM_PIN_D0    15
#define CAM_PIN_VSYNC 38
#define CAM_PIN_HREF  47
#define CAM_PIN_PCLK  13

// Capture button: a 6x6 mm tact switch between pad D1 and GND. The on-board
// BOOT button (GPIO0) also works, so the glasses run with no extra button.
#define BUTTON_PIN      2   // D1
#define BOOT_BUTTON_PIN 0
#define LED_PIN        21   // user LED, active LOW (shared with the unused SD CS)

// One press = one burst. Turn the head slowly across the plate while the LED
// blinks so the frames see the food from slightly different angles.
#define BURST_FRAMES   8
#define BURST_GAP_MS   350
#define MAX_FRAMES     12
#define DEFAULT_JPEG_QUALITY 10   // esp32-camera scale: lower = better (E4: heavy JPEG breaks SfM)
