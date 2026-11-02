// Half-step driver for a 28BYJ-48 on a ULN2003, with a linear speed ramp.
// Open loop: position is counted, not measured, so the rig re-homes by
// returning to step 0 after every scan and never relies on absolute angle
// across power cycles. Coils are released when idle to keep the motor cool
// (it otherwise draws ~240 mA continuously and warms the load-cell platform).
#pragma once
#include <Arduino.h>

class Stepper28BYJ {
 public:
  void begin(int a, int b, int c, int d) {
    pins_[0] = a; pins_[1] = b; pins_[2] = c; pins_[3] = d;
    for (int p : pins_) { pinMode(p, OUTPUT); digitalWrite(p, LOW); }
  }

  // Signed half-steps. Blocks; the turntable must be still before a capture anyway.
  void move(long steps, uint32_t us_min, uint32_t us_start) {
    int dir = steps >= 0 ? 1 : -1;
    long n = labs(steps);
    long ramp = min(n / 2, 200L);
    for (long i = 0; i < n; i++) {
      long edge = min(i, n - 1 - i);
      uint32_t us = edge < ramp ? us_start - (us_start - us_min) * edge / max(ramp, 1L) : us_min;
      phase_ = (phase_ + dir + 8) % 8;
      apply(phase_);
      position_ += dir;
      delayMicroseconds(us);
    }
  }

  void release() { for (int p : pins_) digitalWrite(p, LOW); }
  long position() const { return position_; }
  void zero() { position_ = 0; }

 private:
  void apply(int ph) {
    static const uint8_t seq[8] = {0b1000, 0b1100, 0b0100, 0b0110, 0b0010, 0b0011, 0b0001, 0b1001};
    for (int i = 0; i < 4; i++) digitalWrite(pins_[i], (seq[ph] >> (3 - i)) & 1);
  }
  int pins_[4] = {-1, -1, -1, -1};
  int phase_ = 0;
  long position_ = 0;
};
