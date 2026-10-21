// AssistVision camera glasses: XIAO ESP32S3 Sense on a spectacle frame.
//
// A caregiver wears the glasses. One press when the meal is served and one
// press when the plate is cleared; each press records a short burst of JPEG
// frames into PSRAM. The host (src/glasses_client.py) pulls the burst over
// Wi-Fi and works out the share of the meal that was eaten. All geometry runs
// on the host; the glasses only capture.
//
// HTTP API
//   GET  /status          firmware, camera settings, heap, rssi, last burst id + frame count
//   GET  /capture         image/jpeg, one fresh frame (live preview / aiming)
//   POST /trigger         same as pressing the button (remote test)
//   GET  /frame?i=0       image/jpeg, frame i of the last burst (X-Burst-Id header)
//   POST /camera?framesize=UXGA&quality=10&vflip=0&hmirror=0

#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include "esp_camera.h"

#include "config.h"
#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif

#define FW_VERSION "glasses-1.0"

WebServer server(80);

struct Frame { uint8_t *buf = nullptr; size_t len = 0; uint32_t t_ms = 0; };
Frame g_frames[MAX_FRAMES];
int g_count = 0;
uint32_t g_burst_id = 0;
volatile bool g_trigger = false;
framesize_t g_framesize = FRAMESIZE_UXGA;
int g_quality = DEFAULT_JPEG_QUALITY;

static const char *framesizeName(framesize_t f) {
  switch (f) {
    case FRAMESIZE_VGA: return "VGA";
    case FRAMESIZE_SVGA: return "SVGA";
    case FRAMESIZE_XGA: return "XGA";
    case FRAMESIZE_SXGA: return "SXGA";
    case FRAMESIZE_UXGA: return "UXGA";
    default: return "OTHER";
  }
}

static bool parseFramesize(const String &s, framesize_t &out) {
  if (s == "VGA") out = FRAMESIZE_VGA;
  else if (s == "SVGA") out = FRAMESIZE_SVGA;
  else if (s == "XGA") out = FRAMESIZE_XGA;
  else if (s == "SXGA") out = FRAMESIZE_SXGA;
  else if (s == "UXGA") out = FRAMESIZE_UXGA;
  else return false;
  return true;
}

void led(bool on) { digitalWrite(LED_PIN, on ? LOW : HIGH); }

void blink(int n, int ms) {
  for (int i = 0; i < n; i++) { led(true); delay(ms); led(false); delay(ms); }
}

bool cameraInit() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = CAM_PIN_D0; c.pin_d1 = CAM_PIN_D1; c.pin_d2 = CAM_PIN_D2; c.pin_d3 = CAM_PIN_D3;
  c.pin_d4 = CAM_PIN_D4; c.pin_d5 = CAM_PIN_D5; c.pin_d6 = CAM_PIN_D6; c.pin_d7 = CAM_PIN_D7;
  c.pin_xclk = CAM_PIN_XCLK; c.pin_pclk = CAM_PIN_PCLK; c.pin_vsync = CAM_PIN_VSYNC;
  c.pin_href = CAM_PIN_HREF; c.pin_sccb_sda = CAM_PIN_SIOD; c.pin_sccb_scl = CAM_PIN_SIOC;
  c.pin_pwdn = CAM_PIN_PWDN; c.pin_reset = CAM_PIN_RESET;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = g_framesize;
  c.jpeg_quality = g_quality;
  c.fb_count = 2;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;
  return esp_camera_init(&c) == ESP_OK;
}

camera_fb_t *freshFrame() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (fb) esp_camera_fb_return(fb);
  return esp_camera_fb_get();
}

void clearBurst() {
  for (int i = 0; i < MAX_FRAMES; i++) {
    if (g_frames[i].buf) free(g_frames[i].buf);
    g_frames[i] = Frame();
  }
  g_count = 0;
}

// Record one burst into PSRAM. Keeps whatever frames succeeded.
void captureBurst() {
  clearBurst();
  uint32_t t0 = millis();
  for (int i = 0; i < BURST_FRAMES && i < MAX_FRAMES; i++) {
    led(true);
    camera_fb_t *fb = freshFrame();
    led(false);
    if (fb) {
      uint8_t *copy = (uint8_t *)ps_malloc(fb->len);
      if (copy) {
        memcpy(copy, fb->buf, fb->len);
        g_frames[g_count].buf = copy;
        g_frames[g_count].len = fb->len;
        g_frames[g_count].t_ms = millis() - t0;
        g_count++;
      }
      esp_camera_fb_return(fb);
    }
    delay(BURST_GAP_MS);
  }
  g_burst_id++;
  Serial.printf("burst %lu: %d frames\n", (unsigned long)g_burst_id, g_count);
  blink(g_count == BURST_FRAMES ? 2 : 6, g_count == BURST_FRAMES ? 120 : 50);
}

void sendJson(int code, const String &body) {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(code, "application/json", body);
}

void handleStatus() {
  String j = "{";
  j += "\"firmware\":\"" FW_VERSION "\",";
  j += "\"framesize\":\"" + String(framesizeName(g_framesize)) + "\",";
  j += "\"jpeg_quality\":" + String(g_quality) + ",";
  j += "\"burst_id\":" + String(g_burst_id) + ",";
  j += "\"frames\":" + String(g_count) + ",";
  j += "\"burst_frames\":" + String(BURST_FRAMES) + ",";
  j += "\"free_psram\":" + String(ESP.getFreePsram()) + ",";
  j += "\"free_heap\":" + String(ESP.getFreeHeap()) + ",";
  j += "\"rssi\":" + String(WiFi.RSSI()) + ",";
  j += "\"uptime_ms\":" + String(millis());
  j += "}";
  sendJson(200, j);
}

void handleCapture() {
  camera_fb_t *fb = freshFrame();
  if (!fb) { sendJson(503, "{\"error\":\"capture failed\"}"); return; }
  server.sendHeader("X-Frame-Size", String(fb->width) + "x" + String(fb->height));
  server.send_P(200, "image/jpeg", (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
}

void handleTrigger() {
  g_trigger = true;
  sendJson(202, "{\"queued\":true,\"next_burst_id\":" + String(g_burst_id + 1) + "}");
}

void handleFrame() {
  int i = server.hasArg("i") ? server.arg("i").toInt() : 0;
  if (i < 0 || i >= g_count) { sendJson(404, "{\"error\":\"no such frame\"}"); return; }
  server.sendHeader("X-Burst-Id", String(g_burst_id));
  server.sendHeader("X-Frame-Ms", String(g_frames[i].t_ms));
  server.send_P(200, "image/jpeg", (const char *)g_frames[i].buf, g_frames[i].len);
}

void handleCamera() {
  sensor_t *s = esp_camera_sensor_get();
  if (server.hasArg("framesize")) {
    framesize_t f;
    if (!parseFramesize(server.arg("framesize"), f)) { sendJson(400, "{\"error\":\"framesize\"}"); return; }
    g_framesize = f;
    s->set_framesize(s, f);
  }
  if (server.hasArg("quality")) {
    g_quality = constrain(server.arg("quality").toInt(), 4, 63);
    s->set_quality(s, g_quality);
  }
  if (server.hasArg("vflip")) s->set_vflip(s, server.arg("vflip") == "1");
  if (server.hasArg("hmirror")) s->set_hmirror(s, server.arg("hmirror") == "1");
  handleStatus();
}

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(BOOT_BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  led(false);

  if (!psramFound()) Serial.println("WARNING: no PSRAM; enable Tools > PSRAM > OPI PSRAM");
  if (!cameraInit()) { Serial.println("ERROR: camera init failed; check the camera ribbon"); blink(20, 50); }

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) { led(true); delay(100); led(false); delay(150); }
  Serial.printf("WiFi %s  IP %s\n", WiFi.status() == WL_CONNECTED ? "up" : "DOWN",
                WiFi.localIP().toString().c_str());
  MDNS.begin("assistvision-glasses");

  server.on("/status", HTTP_GET, handleStatus);
  server.on("/capture", HTTP_GET, handleCapture);
  server.on("/trigger", HTTP_POST, handleTrigger);
  server.on("/frame", HTTP_GET, handleFrame);
  server.on("/camera", HTTP_POST, handleCamera);
  server.begin();
  blink(1, 400);
}

void loop() {
  server.handleClient();
  static uint32_t last = 0;
  bool pressed = digitalRead(BUTTON_PIN) == LOW || digitalRead(BOOT_BUTTON_PIN) == LOW;
  if ((pressed || g_trigger) && millis() - last > 1500) {
    last = millis();
    g_trigger = false;
    captureBurst();
  }
}
