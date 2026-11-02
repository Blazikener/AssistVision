// AssistVision capture rig firmware: ESP32-S3 camera + HX711 load cell +
// 28BYJ-48 turntable, controlled over HTTP by src/rig_client.py.
//
// The firmware is deliberately thin. It captures, weighs and rotates; all
// geometry (SfM, MVS, depth, volume) runs on the host. An ESP32-S3 has 8 MB
// PSRAM and ~240 MHz x2 cores -- enough to stream UXGA JPEGs, three orders of
// magnitude short of running SfM or a 25M-parameter depth network at useful
// resolution. See paper Sec. "Why the compute is off-device".
//
// HTTP API (all JSON unless noted)
//   GET  /status                   firmware, camera settings, heap, rssi, calibration
//   GET  /weight?n=15              median-filtered grams + raw + std
//   POST /tare?n=30                zero the scale (stored in NVS)
//   POST /calibrate?grams=500&n=30 set scale factor from a known mass (NVS)
//   POST /rotate?deg=15            rotate turntable, then settle
//   POST /home                     return to step 0
//   GET  /capture                  image/jpeg (one fresh frame, stale buffer flushed)
//   POST /camera?framesize=UXGA&quality=10&lock=1   apply sensor settings
//
// There is no /scan endpoint on purpose: the host drives the rotate/capture
// loop, so one dropped Wi-Fi frame is retried instead of restarting a scan.

#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include "esp_camera.h"

#include "config.h"
#include "hx711.h"
#include "stepper.h"
#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif

WebServer server(80);
Preferences prefs;
HX711 scale;
Stepper28BYJ table;

int32_t g_tare = 0;
float g_counts_per_gram = 0.0f;   // 0 = uncalibrated
uint32_t g_settle_ms = DEFAULT_SETTLE_MS;
framesize_t g_framesize = FRAMESIZE_UXGA;
int g_quality = DEFAULT_JPEG_QUALITY;
bool g_locked = false;

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
  // LATEST, not WHEN_EMPTY: after the turntable moves we want the frame that
  // was exposed after it stopped, not one queued while it was still turning.
  c.grab_mode = CAMERA_GRAB_LATEST;
  return esp_camera_init(&c) == ESP_OK;
}

// Lock exposure, gain and white balance at their current converged values.
// Multi-view stereo matches patches by photometric similarity; if auto
// exposure re-meters on every view (it will -- the plate rotates bright rim
// towards and away from the light), the same rice grain changes brightness
// between views and PatchMatch scores drop.
void lockExposure(bool lock) {
  sensor_t *s = esp_camera_sensor_get();
  if (!s) return;
  s->set_exposure_ctrl(s, lock ? 0 : 1);
  s->set_gain_ctrl(s, lock ? 0 : 1);
  s->set_whitebal(s, lock ? 0 : 1);
  s->set_awb_gain(s, lock ? 0 : 1);
  g_locked = lock;
}

camera_fb_t *freshFrame() {
  // Two buffers: discard one so the returned frame post-dates the last motion.
  camera_fb_t *fb = esp_camera_fb_get();
  if (fb) esp_camera_fb_return(fb);
  return esp_camera_fb_get();
}

bool readGrams(int n, float &grams, int32_t &raw, float &std_counts) {
  if (!scale.readMedian(n, raw, std_counts)) return false;
  grams = g_counts_per_gram != 0.0f ? (raw - g_tare) / g_counts_per_gram : NAN;
  return true;
}

void sendJson(int code, const String &body) {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(code, "application/json", body);
}

int argInt(const char *name, int def) {
  return server.hasArg(name) ? server.arg(name).toInt() : def;
}

void handleStatus() {
  String j = "{";
  j += "\"firmware\":\"" FW_VERSION "\",";
  j += "\"framesize\":\"" + String(framesizeName(g_framesize)) + "\",";
  j += "\"jpeg_quality\":" + String(g_quality) + ",";
  j += "\"exposure_locked\":" + String(g_locked ? "true" : "false") + ",";
  j += "\"tare_raw\":" + String(g_tare) + ",";
  j += "\"counts_per_gram\":" + String(g_counts_per_gram, 4) + ",";
  j += "\"step_position\":" + String(table.position()) + ",";
  j += "\"steps_per_rev\":" + String(STEPS_PER_REV, 2) + ",";
  j += "\"settle_ms\":" + String(g_settle_ms) + ",";
  j += "\"free_heap\":" + String(ESP.getFreeHeap()) + ",";
  j += "\"free_psram\":" + String(ESP.getFreePsram()) + ",";
  j += "\"rssi_dbm\":" + String(WiFi.RSSI()) + ",";
  j += "\"uptime_ms\":" + String(millis());
  j += "}";
  sendJson(200, j);
}

void handleWeight() {
  int n = argInt("n", 15);
  float g, sd; int32_t raw;
  uint32_t t0 = millis();
  if (!readGrams(n, g, raw, sd)) { sendJson(503, "{\"error\":\"hx711 timeout\"}"); return; }
  String j = "{\"grams\":" + (isnan(g) ? String("null") : String(g, 2));
  j += ",\"raw\":" + String(raw) + ",\"std_counts\":" + String(sd, 2);
  j += ",\"n\":" + String(n) + ",\"ms\":" + String(millis() - t0) + "}";
  sendJson(200, j);
}

void handleTare() {
  int n = argInt("n", 30);
  int32_t raw; float sd;
  if (!scale.readMedian(n, raw, sd)) { sendJson(503, "{\"error\":\"hx711 timeout\"}"); return; }
  g_tare = raw;
  prefs.putInt("tare", g_tare);
  sendJson(200, "{\"tare_raw\":" + String(g_tare) + ",\"std_counts\":" + String(sd, 2) + "}");
}

void handleCalibrate() {
  if (!server.hasArg("grams")) { sendJson(400, "{\"error\":\"grams required\"}"); return; }
  float grams = server.arg("grams").toFloat();
  int n = argInt("n", 30);
  int32_t raw; float sd;
  if (grams <= 0 || !scale.readMedian(n, raw, sd)) { sendJson(400, "{\"error\":\"bad mass or hx711 timeout\"}"); return; }
  g_counts_per_gram = (raw - g_tare) / grams;
  prefs.putFloat("cpg", g_counts_per_gram);
  sendJson(200, "{\"counts_per_gram\":" + String(g_counts_per_gram, 4) + "}");
}

void handleRotate() {
  float deg = server.hasArg("deg") ? server.arg("deg").toFloat() : 360.0f / DEFAULT_VIEWS;
  long steps = lroundf(deg / 360.0f * STEPS_PER_REV);
  uint32_t t0 = millis();
  table.move(steps, STEP_US_MIN, STEP_US_START);
  table.release();
  delay(g_settle_ms);
  String j = "{\"steps\":" + String(steps) + ",\"position\":" + String(table.position());
  j += ",\"angle_deg\":" + String(table.position() * 360.0f / STEPS_PER_REV, 3);
  j += ",\"ms\":" + String(millis() - t0) + "}";
  sendJson(200, j);
}

void handleHome() {
  table.move(-table.position(), STEP_US_MIN, STEP_US_START);
  table.release();
  table.zero();
  sendJson(200, "{\"position\":0}");
}

void handleCapture() {
  uint32_t t0 = millis();
  camera_fb_t *fb = freshFrame();
  if (!fb) { sendJson(503, "{\"error\":\"capture failed\"}"); return; }
  server.sendHeader("X-Capture-Ms", String(millis() - t0));
  server.sendHeader("X-Step-Position", String(table.position()));
  server.sendHeader("X-Frame-Size", String(fb->width) + "x" + String(fb->height));
  server.send_P(200, "image/jpeg", (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
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
  if (server.hasArg("settle_ms")) g_settle_ms = constrain(server.arg("settle_ms").toInt(), 0, 5000);
  if (server.hasArg("lock")) {
    if (server.arg("lock") == "1") {
      // let AEC/AWB converge on the scene before freezing them
      for (int i = 0; i < 8; i++) { camera_fb_t *fb = esp_camera_fb_get(); if (fb) esp_camera_fb_return(fb); }
      lockExposure(true);
    } else {
      lockExposure(false);
    }
  }
  handleStatus();
}

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  prefs.begin("rig", false);
  g_tare = prefs.getInt("tare", 0);
  g_counts_per_gram = prefs.getFloat("cpg", 0.0f);

  scale.begin(HX711_DOUT, HX711_SCK);
  table.begin(STEP_IN1, STEP_IN2, STEP_IN3, STEP_IN4);

  if (!psramFound()) Serial.println("WARNING: no PSRAM, UXGA frames will not fit");
  if (!cameraInit()) Serial.println("ERROR: camera init failed");

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // modem sleep adds 100+ ms jitter to every frame transfer
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) delay(250);
  Serial.printf("WiFi %s  IP %s\n", WiFi.status() == WL_CONNECTED ? "up" : "DOWN",
                WiFi.localIP().toString().c_str());
  MDNS.begin("assistvision");

  server.on("/status", HTTP_GET, handleStatus);
  server.on("/weight", HTTP_GET, handleWeight);
  server.on("/tare", HTTP_POST, handleTare);
  server.on("/calibrate", HTTP_POST, handleCalibrate);
  server.on("/rotate", HTTP_POST, handleRotate);
  server.on("/home", HTTP_POST, handleHome);
  server.on("/capture", HTTP_GET, handleCapture);
  server.on("/camera", HTTP_POST, handleCamera);
  server.begin();
}

void loop() {
  server.handleClient();
  // BOOT button: quick on-device weight readout on serial, for bench checks
  static uint32_t last = 0;
  if (digitalRead(BUTTON_PIN) == LOW && millis() - last > 500) {
    last = millis();
    float g, sd; int32_t raw;
    if (readGrams(15, g, raw, sd)) Serial.printf("weight %.2f g  raw %ld  std %.1f\n", g, (long)raw, sd);
  }
}
