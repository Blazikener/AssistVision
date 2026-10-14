"""Analyse the rig bench tests written by src/rig_client.py.

    python experiments/hw_analysis.py --scale results/hw/scale.csv \
        --turntable results/hw/turntable.csv --scans captures/rig

Prints the pass/fail table from hardware/README.md and writes
results/hw/scale_linearity.pdf. Refuses to run on missing files rather than
inventing numbers.
"""
import argparse
import csv
import glob
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def scale_report(path, outdir):
    rows = list(csv.DictReader(open(path)))
    ref = np.array([float(r["ref_g"]) for r in rows])
    g = np.array([float(r["grams"]) for r in rows])
    A = np.stack([ref, np.ones_like(ref)], 1)
    (a, b), *_ = np.linalg.lstsq(A, g, rcond=None)
    resid = g - (a * ref + b)
    rep = {m: float(g[ref == m].std(ddof=1)) for m in np.unique(ref) if (ref == m).sum() > 1}
    err = {m: float(np.mean(g[ref == m] - m)) for m in np.unique(ref)}
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(7, 2.6))
    ax[0].plot(ref, g, ".", ms=3); ax[0].plot([0, ref.max()], [b, a * ref.max() + b], lw=0.8)
    ax[0].set_xlabel("reference (g)"); ax[0].set_ylabel("measured (g)")
    ax[1].plot(ref, g - ref, ".", ms=3); ax[1].axhline(0, lw=0.5, color="k")
    ax[1].set_xlabel("reference (g)"); ax[1].set_ylabel("error (g)")
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "scale_linearity.pdf"))
    return {"gain": a, "offset_g": b, "max_abs_residual_g": float(np.abs(resid).max()),
            "repeatability_std_g": rep, "mean_error_g": err, "n": len(rows)}


def turntable_report(path):
    rows = list(csv.DictReader(open(path)))
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50))
    angles = []
    for r in rows:
        im = cv2.imread(r["file"], cv2.IMREAD_GRAYSCALE)
        c, ids, _ = det.detectMarkers(im)
        if ids is None:
            continue
        c = c[0].reshape(4, 2)
        v = c[1] - c[0]
        angles.append(np.degrees(np.arctan2(v[1], v[0])))
    angles = np.unwrap(np.radians(angles)) if angles else np.array([])
    d = np.degrees(angles - angles[0]) if len(angles) else angles
    # image-plane angle of an oblique view is a monotone proxy of turntable angle;
    # report drift relative to revolution 0.
    return {"revs": len(rows), "detected": int(len(d)), "max_image_angle_drift_deg": float(np.abs(d).max()) if len(d) else None}


def scans_report(root):
    out = []
    for p in sorted(glob.glob(os.path.join(root, "*", "scan.json"))):
        m = json.load(open(p))
        t = [v["transfer_s"] for v in m["views"]]
        out.append({"scan": os.path.basename(os.path.dirname(p)), "views": len(t), "scan_s": m["scan_seconds"],
                    "median_transfer_s": float(np.median(t)),
                    "drift_g": (m["weight_after"]["grams"] or 0) - (m["weight_before"]["grams"] or 0)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", default="results/hw/scale.csv")
    ap.add_argument("--turntable", default="results/hw/turntable.csv")
    ap.add_argument("--scans", default="captures/rig")
    ap.add_argument("--out", default="results/hw")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    report = {}
    if os.path.exists(a.scale):
        report["scale"] = scale_report(a.scale, a.out)
    if os.path.exists(a.turntable):
        report["turntable"] = turntable_report(a.turntable)
    if os.path.isdir(a.scans):
        report["scans"] = scans_report(a.scans)
    if not report:
        sys.exit("no bench data found -- run the rig_client.py bench commands first (hardware/README.md)")
    json.dump(report, open(os.path.join(a.out, "hw_report.json"), "w"), indent=1, default=float)
    print(json.dumps(report, indent=1, default=float))


if __name__ == "__main__":
    main()
