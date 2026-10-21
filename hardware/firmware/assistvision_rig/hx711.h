// Minimal HX711 driver: channel A, gain 128. No third-party library so the
// timing is visible and auditable -- the 24th clock pulse must stay under
// 60 us or the chip enters power-down, which is why interrupts are masked.
#pragma once
#include <Arduino.h>

class HX711 {
 public:
  void begin(int dout, int sck) {
    dout_ = dout; sck_ = sck;
    pinMode(sck_, OUTPUT);
    pinMode(dout_, INPUT);
    digitalWrite(sck_, LOW);
  }
  bool ready() const { return digitalRead(dout_) == LOW; }

  // One 24-bit conversion, sign-extended. Blocks until data ready (<= 100 ms at 10 SPS).
  bool readRaw(int32_t &out, uint32_t timeout_ms = 200) {
    uint32_t t0 = millis();
    while (!ready()) {
      if (millis() - t0 > timeout_ms) return false;
      delay(1);
    }
    uint32_t v = 0;
    portDISABLE_INTERRUPTS();
    for (int i = 0; i < 24; i++) {
      digitalWrite(sck_, HIGH);
      delayMicroseconds(1);
      v = (v << 1) | (digitalRead(dout_) ? 1u : 0u);
      digitalWrite(sck_, LOW);
      delayMicroseconds(1);
    }
    // 25th pulse selects channel A / gain 128 for the next conversion.
    digitalWrite(sck_, HIGH);
    delayMicroseconds(1);
    digitalWrite(sck_, LOW);
    portENABLE_INTERRUPTS();
    if (v & 0x800000) v |= 0xFF000000;
    out = (int32_t)v;
    return true;
  }

  // Median of n readings: rejects the occasional glitch a mean would absorb.
  bool readMedian(int n, int32_t &median, float &stddev) {
    if (n < 1) n = 1;
    if (n > 64) n = 64;
    int32_t buf[64];
    double sum = 0, sq = 0;
    for (int i = 0; i < n; i++) {
      if (!readRaw(buf[i])) return false;
      sum += buf[i];
      sq += (double)buf[i] * buf[i];
    }
    for (int i = 1; i < n; i++) {               // insertion sort, n <= 64
      int32_t k = buf[i]; int j = i - 1;
      while (j >= 0 && buf[j] > k) { buf[j + 1] = buf[j]; j--; }
      buf[j + 1] = k;
    }
    median = buf[n / 2];
    double mean = sum / n;
    stddev = (float)sqrt(fmax(0.0, sq / n - mean * mean));
    return true;
  }

 private:
  int dout_ = -1, sck_ = -1;
};
