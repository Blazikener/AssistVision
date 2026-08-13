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

## 2026-08-12 — moved to E:, environment installed, geometry verified

Repo moved from `C:\Users\abdulahad\Documents\vision-assist` to `E:\7thSemProject`.
C: only had ~10 GB free, which will not hold the capture dataset (~15-25 GB) plus
COLMAP dense intermediates. E: has 82 GB.

Two Windows issues resolved on the way:
- `E:\` granted only Read+Execute to non-elevated users; fixed with
  `icacls "E:\" /grant "abdulahad:(OI)(CI)M"`.
- Folder was owned by BUILTIN\Administrators, so git refused it as "dubious
  ownership"; fixed with `takeown`.

Installed the stack. **pip pulled OpenCV 5.0.0**, a major version jump from the
4.13 the scripts were written against, so added `src/test_geometry.py` to verify
the geometry rather than assume it:

- `cv2.calibrateCamera` recovers known synthetic intrinsics to 0.0001 px. Good.
- ArUco `ArucoDetector` API unchanged, all 4 markers detected.

One real finding from the test. The generator renders a nominal 50 mm marker at
**50.038 mm** (pixel-grid rounding at 300 dpi), and the detector measures
**49.953 mm**. The gap is exactly one pixel, because the generator draws a marker
spanning N pixels while the detector returns corner *centres*, which are N-1
pixels apart. Residual after accounting for it: 0.00000 mm.

Not an error, but exactly the class of off-by-one that would quietly bias every
volume, so `make_aruco.py` now reports the true rendered size and the test asserts
the convention explicitly.

Reminder for when the sheet is printed: none of the above sets the real scale
factor. The **measured** printed marker does.

---
