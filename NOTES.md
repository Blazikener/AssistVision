# Lab notebook

Dated entries, newest at the bottom. **Every experiment, every number, every
failure.** When you write the paper in week 9, this file is the difference
between assembling a draft and doing archaeology on your own project.

It is also where interview answers come from. "COLMAP registered 31 of 40 images
on the steel thali capture" is a far better answer than "it didn't work well on
shiny surfaces."

Rules:
- Log the number even when it's bad. Especially when it's bad.
- Log the command you actually ran, not the one you meant to run.
- If you change a capture setting, log it — lighting, distance, resolution.

---

## Rig constants

Fill these in as you establish them. Everything downstream depends on them.

| Item | Value | Measured on | Notes |
|---|---|---|---|
| Checkerboard square size | ___ mm | | measure with a ruler, don't trust the PDF |
| ArUco marker size (nominal) | 50.0 mm | | from `make_aruco.py` |
| ArUco marker size (**measured**) | ___ mm | | **this is the one that matters** |
| 100 mm ruler line, as printed | ___ mm | | if not 100.0, the printer rescaled |
| Laptop webcam resolution | ___ x ___ | | calibration only valid at this resolution |
| Laptop RMS reproj. error | ___ px | | target < 1.0 |
| Phone model + resolution | | | lock the resolution, don't let it vary |
| Phone RMS reproj. error | ___ px | | |
| Kitchen scale resolution | ___ g | | 1 g is fine, 0.1 g is better |

---

## 2026-08-12 — project set up

Repo created. `calibrate.py` and `make_aruco.py` written and smoke-tested.
ArUco sheet generated at 300 dpi, not yet printed.

Environment: OpenCV 4.13.0, NumPy 2.2.6, Python 3.12.10. **No NVIDIA GPU** —
COLMAP dense MVS needs CUDA, so dense reconstruction and any torch models run
on Colab. Sparse SfM can run locally on CPU.

Next: print the board and the marker sheet, measure both, calibrate the laptop
webcam.

---
