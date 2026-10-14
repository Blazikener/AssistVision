# Vision Assist — metric food volume estimation from multi-view images

Estimating the mass of served food from images, with metric scale recovered from
multi-view reconstruction and validated against gravimetric ground truth.

> **Status: in progress.** Hardware rig designed and firmware compiled; physical
> measurements pending. Target: arXiv preprint and a workshop submission.
> Paper: `paper/main.pdf` (built from `paper/main.tex`).

**Results so far (no physical-rig numbers yet).** Synthetic = Blender scenes with exact
mesh volume; Nutrition5k = volume relative to RealSense sensor depth (not true food volume).

| Finding | Number | Source |
|---|---|---|
| Dense 24-view MVS, 16 textured-food scenes | 4.6 % median abs. error [2.0, 6.1], 13/16 within 10 % | Synthetic |
| Sparse SfM only, 22 scenes | 91.3 % median error | Synthetic |
| Textureless food on white ceramic, 4 scenes | 45.1 % median error | Synthetic |
| Views per scan: 6 / 8 / 12 / 16 / 24 | 91.6 / 71.4 / 3.3 / 1.6 / 4.2 % | Synthetic, 60 runs |
| OpenCV JPEG quality 10 (any resolution) | 73–90 % error; 800×600 lossless is 3.2 % | Synthetic, 72 runs |
| Best deployable monocular model (ZoeDepth-NYU, table-scale anchor) | 44.1 % median volume error | Nutrition5k, 498 dishes |
| Relative models, table anchor (5 models) | 88.4–99.4 % | Nutrition5k |
| Oracle upper bound (DA-V2-L) | 25.9 % | Nutrition5k |
| Sensor-depth volume → grams vs predicting the mean mass | 68.2 % vs 52.0 % median error | Nutrition5k |

Reproduce: `experiments/n5k_mono_benchmark.py` + `experiments/n5k_analyze.py` (Nutrition5k),
`experiments/synth/run_suite.py --exp {main,sparse,views,sensor,scale,repeat}` +
`experiments/synth/analyze.py` (synthetic). Timings are CPU timings on 8-vCPU cloud VMs.

## The problem

Nutrition estimation from images needs portion size in grams, and portion size
needs volume. A single image cannot supply it: perspective projection discards
scale, so a small plate held close and a large plate held far away are pixel-wise
identical. Metric scale must be injected from outside the image.

This project injects it two ways and compares them:

1. **Multi-view path.** Photographs orbiting the plate → COLMAP structure-from-motion
   and dense MVS → point cloud scaled by a printed ArUco marker of known size →
   volume by integrating above the fitted table plane.
2. **Single-view path.** Off-the-shelf monocular depth on one frame → back-projection
   → the same volume integral.

Every plate is weighed on a kitchen scale, so both paths are scored against real
grams rather than against each other.

## Contribution

A small multi-view food dataset with **gravimetric ground truth** and metric scale,
plus a benchmark of how single-view depth estimation degrades relative to multi-view
reconstruction — including on specular metal serveware common in Indian homes, which
is a known-hard case for classical MVS.

## Layout

```
src/         calibration, marker generation, reconstruction, evaluation
captures/    raw images, by camera and session (git-ignored)
data/        printable assets, ground-truth logs, dataset manifests
results/     error tables, figures
paper/       manuscript
NOTES.md     lab notebook -- every run, every number
STUDY.md     the learning path this project is built on
```

## Setup

```bash
pip install -r requirements.txt
```

Generate and print the scale reference (print at **100% / actual size**, never
"fit to page"):

```bash
python src/make_aruco.py --marker-mm 50 --out data/aruco_sheet.png
```

Calibrate a camera:

```bash
python src/calibrate.py capture --out captures/laptop
python src/calibrate.py solve --images captures/laptop --squares 25.0 --preview
```

## Hardware capture rig

`hardware/` holds an ESP32-S3 + OV2640 rig: stepper turntable, HX711 load cell
under the plate, printed ArUco mat. One scan returns N views plus the plate's
weighed mass. Firmware, wiring, BOM, power budget and the bench-test protocol
are in [`hardware/README.md`](hardware/README.md); the host client is
`src/rig_client.py` (tested against a fake firmware: `python src/test_rig_client.py`).

```bash
python src/rig_client.py scan --views 24 --out captures/rig/plate_001 --label "rice, steel thali"
```

## Experiments

Every number in the paper comes from one of four evidence sources, labelled as such:
**Nutrition5k** (public real RGB-D), **synthetic** (Blender renders with exact
mesh volume), **VM** (CPU timings on the dev VM, not the ESP32) and
**physical** (rig bench tests -- empty until the rig is built and measured).

| ID | What | Command |
|---|---|---|
| E1/E2 | 11 monocular depth models vs RealSense depth and weighed mass, Nutrition5k depth test split (507 dishes); raw / anchor / oracle protocols | `python experiments/n5k_mono_benchmark.py --models all` then `python experiments/n5k_analyze.py` |
| E3 | Dense MVS (COLMAP + OpenMVS) vs sparse SfM vs monocular depth on exact-volume scenes | `bash data/synth/render_all.sh`, `python experiments/synth/run_suite.py --exp main`, `python experiments/synth/mono_synth.py` |
| E4 | Ablations: views, resolution x JPEG, marker-scale error, plate material, run-to-run repeat | `python experiments/synth/run_suite.py --exp views\|sensor\|scale\|sparse\|repeat`, then `python experiments/synth/analyze.py` |
| HW | Load-cell linearity/repeatability/drift, turntable error, scan time | `python src/rig_client.py bench-scale ...`, `python experiments/hw_analysis.py` |

Unit tests: `python src/test_volume.py`, `python src/test_geometry.py`, `python src/test_rig_client.py`.

The manuscript is `paper/main.tex` (`cd paper && latexmk -pdf main.tex`).

## Compute

Everything runs on CPU. Dense MVS uses the OpenMVS Docker image
(`openmvs/openmvs-ubuntu`), monocular models load through Hugging Face
`transformers`; Depth Pro (~30 s/image on CPU) is run on a fixed random subset
of 200 dishes.

## Data and licences

Public benchmark evaluation uses [Nutrition5k](https://github.com/google-research-datasets/Nutrition5k)
(CC-BY-4.0). Captured data in this repository contains food on tables only — no
human subjects and no identifiable bystanders.

