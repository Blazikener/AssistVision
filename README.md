<<<<<<< HEAD
# Vision Assist — metric food volume estimation from multi-view images

Estimating the mass of served food from images, with metric scale recovered from
multi-view reconstruction and validated against gravimetric ground truth.

> **Status: in progress (week 1 of 12).** Target: arXiv preprint and a workshop
> submission by early November 2026.

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

## Compute

Sparse SfM runs on CPU. Dense MVS requires CUDA, and monocular depth and SAM 2
want a GPU, so those steps run on Colab. See `NOTES.md` for the current split.

## Data and licences

Public benchmark evaluation uses [Nutrition5k](https://github.com/google-research-datasets/Nutrition5k)
(CC-BY-4.0). Captured data in this repository contains food on tables only — no
human subjects and no identifiable bystanders.
=======
# AssistVision
>>>>>>> c739b0b4f506c2d158429c0d6ae05f49a6c03c94
