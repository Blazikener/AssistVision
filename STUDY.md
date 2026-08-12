# Study plan

The rule: **learn each thing the day before you need it, not before.** You have
twelve weeks and no time for a general CV course. Everything below is tied to a
week of the build. If a topic isn't on this list, it isn't on the critical path
— skip it and come back after November.

Budget roughly **1 hour of study, 3–4 hours of building** per day. The study hour
is for the week you're in, not the week you're excited about.

---

## Tier 1 — Camera geometry (weeks 1–2) — must know cold

Everything else in this project sits on top of this. Do not move on until you
can explain each item without notes.

- Pinhole camera model; why a camera is a projection, not a measurement device
- The intrinsic matrix **K**: fx, fy, cx, cy — what each one physically means
- Extrinsics [R | t]; world → camera → image
- The projection equation **x = K[R|t]X** and why it loses one dimension
- Radial and tangential lens distortion
- **Reprojection error** — the single most important metric in this project
- Homography; when a plane-to-plane mapping is exact and when it isn't
- **RANSAC** — why every geometric estimate needs outlier rejection
- **Scale ambiguity** — why one image can never give you metric size

**Resources**
- Shree Nayar, *First Principles of Computer Vision* (Columbia) — short, geometric,
  free on YouTube. The fastest correct path into this material.
- Szeliski, *Computer Vision: Algorithms and Applications*, 2nd ed — free PDF at
  szeliski.org/Book. Chapter 2 (image formation), chapter 11 (structure from motion).

**You've truly learned it when** you can explain why `src/calibrate.py` needs
twenty views at varied angles rather than twenty flat-on views.

---

## Tier 2 — Multi-view geometry (weeks 2–4) — the job's core

This is the tier Track3D is actually screening for. Give it the most time.

- Epipolar geometry; the epipolar constraint
- **Fundamental vs essential matrix** — what each assumes about calibration
- Triangulation: two rays, one 3D point, and why they never quite meet
- **PnP** — pose from known 3D points
- **Bundle adjustment** — what it optimises and over what variables
- The SfM pipeline: feature detection (SIFT) → matching → geometric verification
  → incremental registration → repeated BA
- MVS: PatchMatch stereo, depth map fusion, why it needs texture
- Why SfM is scale-ambiguous *even with many views*, and how a known-size marker fixes it

**Resources**
- Szeliski chapters 11–12.
- COLMAP documentation (colmap.github.io) — read the tutorial *and* the FAQ.
  The FAQ is where the debugging knowledge lives.
- Schönberger & Frahm, *Structure-from-Motion Revisited*, CVPR 2016 — the COLMAP
  paper. Read it properly; it's directly interview-relevant.
- Schönberger et al., *Pixelwise View Selection for Unstructured Multi-View Stereo*,
  ECCV 2016 — the MVS half.
- Hartley & Zisserman, *Multiple View Geometry* — the rigorous reference. Dip into
  it for specific derivations; don't try to read it cover to cover.

---

## Tier 3 — Segmentation (week 5) — light, off the shelf

- Semantic vs instance vs panoptic segmentation
- IoU; mAP and how it's computed
- Promptable segmentation and how SAM 2 uses point/box prompts

You are **not** training a segmenter. Zero-shot SAM 2 with point prompts, and move on.

---

## Tier 4 — Monocular depth (week 7) — light, off the shelf

- Relative vs metric depth — the distinction that decides whether your volumes mean anything
- Scale-and-shift-invariant loss (the MiDaS idea) and why it produces *relative* depth
- Depth Anything V2 and its metric variants; UniDepth
- Why models trained on room-scale scenes misbehave at 40 cm

---

## Tier 5 — Research practice (weeks 8–12)

- Keshav, *How to Read a Paper* — the three-pass method. Read this first; it
  triples your reading throughput.
- Read properly, in this order:
  1. Thames et al., **Nutrition5k**, CVPR 2021 — your benchmark, and the paper
     that found direct regression beating geometric pipelines
  2. **MFP3D** — monocular portion estimation from point clouds
  3. The **MetaFood** workshop challenge reports (CVPR 2024/2025)
  4. Two or three depth-domain-adaptation papers for food energy estimation
- Structure of a benchmark/dataset paper vs a method paper — note how the
  contribution claim differs
- Reproducibility: seeds, splits, released code, error bars

---

## Interview preparation (parallel, ~2 hours/week from week 4)

Track3D will probe 3D vision. Be able to answer these cleanly out loud:

1. What's the difference between the fundamental and essential matrix?
2. Why is SfM scale-ambiguous, and how did you resolve it in your project?
3. What does bundle adjustment optimise, and over which variables?
4. How does RANSAC work, and why is it necessary in feature matching?
5. What is PnP and when would you use it?
6. Define reprojection error. Why is it the right thing to minimise?
7. Why does MVS fail on textureless or specular surfaces?
8. Semantic vs instance vs panoptic segmentation?
9. **How would you debug a COLMAP reconstruction that failed to register half the images?**

Question 9 is your advantage. By week 6 you'll have lived it — specular steel
katoris, textureless rice, insufficient overlap. A fresher who can describe a
real failure and how they diagnosed it outranks one who has only read about SfM.

---

## What to deliberately skip

Classical image processing (filters, morphology, edge detectors beyond what
OpenCV hands you), GANs, diffusion models, transformer internals, NeRF and
Gaussian splatting, and anything about training large models from scratch.
Interesting, not on the critical path, not before November.
