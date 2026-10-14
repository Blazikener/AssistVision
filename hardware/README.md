# Capture rig hardware

One button press (or one `rig_client.py scan`) produces N calibrated views of a
plate on a turntable plus its weight in grams. The scale is the ground truth;
the camera, turntable and marker mat produce the input.

![wiring](../paper/figs/wiring.pdf)

## Bill of materials

Prices are **indicative assumptions** (typical Indian hobby-retailer listings,
Oct 2026, not quotes). Replace with your invoice totals before publishing.

| # | Part | Qty | Why this part | Approx. INR (assumption) |
|---|------|-----|---------------|--------------------------|
| 1 | ESP32-S3 CAM board, N16R8 (8 MB PSRAM), OV2640 | 1 | PSRAM is required for UXGA JPEG double-buffering; S3 has native USB for flashing | 900–1,300 |
| 2 | 5 kg bar load cell + HX711 module | 1 | 24-bit ADC, 10 SPS, ~1 g resolution at 5 kg; thalis weigh 300–1,500 g | 250–400 |
| 3 | 28BYJ-48 5 V stepper + ULN2003 board | 1 | 0.088°/half-step after the 63.68:1 gearbox, self-locking, no driver tuning | 150–250 |
| 4 | Lazy-susan bearing, 6" | 1 | Carries the plate load off the motor shaft | 150–300 |
| 5 | 5 V / 2 A USB-C supply | 1 | Wi-Fi TX peaks + motor stay below 1 A; 2 A gives headroom | 250–400 |
| 6 | Printed ArUco mat (src/make_aruco.py, 50 mm markers, 100% scale) | 1 | Metric scale + support plane; verify with a ruler | 20 |
| 7 | MDF/acrylic base, camera arm (45°, 40 cm), M3 hardware | 1 set | Fixed camera, rotating object: lighting moves relative to food exactly as in the synthetic benchmark | 300–600 |
| 8 | Reference masses (or sealed water bottles weighed on a calibrated scale) | 50/100/200/500/1000 g | Scale calibration and linearity test | 0–400 |
| 9 | Jumper wires (F-F, M-F) + mini breadboard | 1 set | HX711 and ULN2003 hook-up without soldering | 100–200 |
| 10 | USB-C data cable | 1 | Flashing and power | 100–150 |
| 11 | 5 V USB LED strip, ~0.5 m, with paper diffuser | 1 | Even, constant light so the views match each other | 100–200 |
| | **Total** | | | **≈ 2,320–4,220** |

### Budget: hard cap ₹5,000

Even at the top of every price range the rig costs about ₹4,220, which leaves
about ₹780 for shipping and breakages. To spend less:

- Reuse a phone charger (≥ 2 A) and a USB-C cable you already own: saves up to ₹550.
- Build the base and arm from 6 mm plywood or thick cardboard: saves up to ₹300.
- Use sealed water bottles weighed once on a shop scale as reference masses: saves up to ₹400.
- Do **not** cut the 8 MB PSRAM ESP32-S3 board or the HX711 + load cell. Without
  them there are no UXGA frames and no ground-truth grams, and the experiments
  depend on both. A cheaper AI-Thinker ESP32-CAM (~₹500) would also work, but
  it has a different pin map and no native USB, so `config.h` would need
  changes. The firmware has only been compiled for the S3.

## Pin map (`firmware/assistvision_rig/config.h`)

| Signal | ESP32-S3 GPIO | Notes |
|---|---|---|
| HX711 DT / SCK | 1 / 2 | HX711 powered from 3V3, not 5 V: logic levels match and the ADC reference is quieter |
| ULN2003 IN1–IN4 | 14 / 21 / 47 / 41 | Clear of camera, PSRAM (35–37) and strapping pins (0, 3, 45, 46) |
| Scan / weigh button | 0 | The on-board BOOT button |
| Camera | 4,5,6,7,8–13,15–18 | ESP32-S3-EYE / Freenove S3 CAM mapping; check your board |

## Power budget (datasheet values, measure with `bench` below)

| Load | State | Datasheet typical | Source |
|---|---|---|---|
| ESP32-S3 | Wi-Fi TX peak | ~340 mA @ 3.3 V | ESP32-S3 datasheet, RF current table |
| ESP32-S3 | Wi-Fi RX / idle connected | ~90–100 mA | same |
| OV2640 | active UXGA | ~40 mA | OV2640 datasheet (140 mW active) |
| HX711 | normal | < 1.5 mA | HX711 datasheet |
| 28BYJ-48 (5 V) | moving, 2 coils on | ~200–250 mA @ 5 V | coil 50 Ω nominal per phase |
| 28BYJ-48 | idle | 0 mA (coils released by firmware) | firmware |

Worst case ≈ 0.34 + 0.04 + 0.25 ≈ **0.65 A** — a 2 A USB-C supply has ~3× headroom.
The motor never moves during a capture or a weighing, so the camera and the
load cell never see motor current noise.

## Bring-up and bench tests (fill `results/hw/` with real numbers)

```bash
# flash (Arduino CLI; board: ESP32S3 Dev Module, PSRAM: OPI, 16 MB flash)
cp firmware/assistvision_rig/secrets.example.h firmware/assistvision_rig/secrets.h   # edit Wi-Fi
arduino-cli compile --fqbn "esp32:esp32:esp32s3:PSRAM=opi,FlashSize=16M,PartitionScheme=app3M_fat9M_16MB" firmware/assistvision_rig
arduino-cli upload  --fqbn "esp32:esp32:esp32s3:PSRAM=opi,FlashSize=16M,PartitionScheme=app3M_fat9M_16MB" -p /dev/ttyACM0 firmware/assistvision_rig

python src/rig_client.py status
python src/rig_client.py tare                 # empty plate on the turntable
python src/rig_client.py calibrate --grams 500
python src/rig_client.py bench-scale --masses 0,50,100,200,500,1000 --repeats 10 --out results/hw/scale.csv
python src/rig_client.py bench-turntable --revs 10 --out results/hw/turntable.csv
python src/rig_client.py scan --views 24 --out captures/rig/plate_001 --label "rice+dal, steel thali"
python experiments/hw_analysis.py            # linearity, repeatability, drift, angle error -> tables + figures
```

| Test | Metric | Pass criterion | Measured |
|---|---|---|---|
| Scale linearity | max residual vs reference, 0–1000 g | < 2 g | _to fill_ |
| Scale repeatability | std of 10 reads at 500 g | < 0.5 g | _to fill_ |
| Drift over a scan | weight_after − weight_before | < 1 g | _to fill_ |
| Turntable repeatability | ArUco angle after 10 revs | < 0.5° | _to fill_ |
| Scan time | 24 views, UXGA q10 | < 60 s | _to fill_ |
| Frame transfer | median `transfer_s` | < 1 s | _to fill_ |

Firmware compiled with Arduino CLI 1.3.1 + ESP32 core 3.3.12 (on the
development VM): 1,042,155 B flash (33%), 60,484 B RAM (18%).
