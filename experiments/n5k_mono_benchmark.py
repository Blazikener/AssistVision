"""
E1: monocular depth models vs the RealSense D435 on Nutrition5k (real food,
real depth sensor, weighed mass).

  python experiments/n5k_mono_benchmark.py --n5k ~/n5k --models all

Per dish and per model it writes one row: depth errors on the food+plate
region, height error above the table, and the volume under three alignment
protocols (raw / anchor / oracle -- see src/depth_metrics.py). Ground-truth
volume comes from the D435 depth through the SAME height-field integral.

Intrinsics: Nutrition5k gives a 35.9 cm camera-to-plane distance and a
per-pixel area of 5.957e-3 cm^2, i.e. fx = fy = 359 / 0.7718 = 465.1 px at
640x480. The principal point is assumed at the image centre.
"""

import argparse
import csv
import os
import sys
import time

import cv2
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import depth_metrics as dm  # noqa: E402
import volume as vol  # noqa: E402

FX = 35.9 / np.sqrt(5.957e-3)
K = np.array([[FX, 0, 319.5], [0, FX, 239.5], [0, 0, 1.0]])
ROI_MIN_HEIGHT = 0.005   # 5 mm above the table = plate or food
FLOOR_CUT = 0.395        # floor under the tray is at ~0.41 m
DEPTHPRO_SUBSET = 200    # DepthPro is ~30 s/image on CPU; seeded random subset


def load_masses(root):
    masses = {}
    for f in ("dish_metadata_cafe1.csv", "dish_metadata_cafe2.csv"):
        with open(os.path.join(root, f)) as fh:
            for row in csv.reader(fh):
                masses[row[0]] = float(row[2])
    return masses


def gt_geometry(gt):
    """Support plane, heights, dish ROI, table pixels and a food mask from D435 depth.

    The capture scene is plate -> tray (~0.37 m) -> floor (~0.41 m). Points
    beyond FLOOR_CUT are excluded before RANSAC, otherwise the floor wins on
    dishes where little tray is visible. The plate floor is a second RANSAC
    plane inside the dish ROI; food = ROI pixels > 5 mm above it, away from
    the rim. Where no plate floor is found (plate fills the tray) the support
    plane is the plate."""
    valid = (gt > 0) & (gt < FLOOR_CUT)
    pts = vol.backproject(gt, K, valid)
    plane, _ = vol.fit_plane_ransac(pts, threshold=0.003, iters=300)
    plane = vol.orient_towards(plane, np.zeros(3))
    n, d = plane
    h = np.full(gt.shape, np.nan)
    h[valid] = pts @ n + d
    raised = valid & (h > ROI_MIN_HEIGHT)
    raised = ndimage.binary_opening(raised, iterations=2)
    lab, nlab = ndimage.label(raised)
    if nlab == 0:
        return None
    sizes = ndimage.sum(raised, lab, range(1, nlab + 1))
    roi = lab == (1 + int(np.argmax(sizes)))
    roi = ndimage.binary_fill_holes(ndimage.binary_closing(roi, iterations=3))
    table = valid & (np.abs(h) < 0.003) & ~ndimage.binary_dilation(roi, iterations=10)

    low = roi & valid & (h < 0.03)
    plate_px = np.zeros_like(roi)
    plate_plane = plane
    if low.sum() > 500:
        lp = vol.backproject(gt, K, low)
        cand, inl = vol.fit_plane_ransac(lp, threshold=0.003, iters=300, seed=1)
        cand = vol.orient_towards(cand, np.zeros(3))
        tilt = np.degrees(np.arccos(min(1.0, abs(cand[0] @ n))))
        if inl.mean() > 0.25 and inl.sum() > 0.15 * roi.sum() and tilt < 8:
            plate_plane = cand
            plate_px[low] = inl
    hp = np.full(gt.shape, np.nan)
    allp = vol.backproject(gt, K, valid)
    hp[valid] = allp @ plate_plane[0] + plate_plane[1]
    inner = ndimage.binary_erosion(roi, iterations=12) if plate_px.any() else roi
    food = inner & valid & (hp > ROI_MIN_HEIGHT)
    food = ndimage.binary_opening(food, iterations=1)
    return plane, h, roi, table, plate_plane, plate_px, food


def evaluate_depth(depth, gt, roi, table, h_gt, gt_plane):
    """Volume + errors for a metric depth map. Plane re-fitted on its own
    table pixels so a global scale/tilt error is not hidden by the GT plane.

    volume_ml uses that self-fitted plane (deployable). volume_gtplane_ml uses
    the sensor's plane instead, isolating relief error from support-plane
    error; table_rms_mm is the predicted table's deviation from flat."""
    # Table pixels are already selected from the sensor, so a plain
    # least-squares fit is used: RANSAC with a sensor-grade 3 mm threshold
    # latches onto arbitrary slivers of a noisy monocular table.
    pts_t = vol.backproject(depth, K, table & np.isfinite(depth) & (depth > 0))
    plane = vol.orient_towards(vol.fit_plane(pts_t), np.zeros(3))
    n, d = plane
    V = vol.volume_from_depth(depth, K, plane, roi & (gt > 0))
    Vg = vol.volume_from_depth(depth, K, gt_plane, roi & (gt > 0))
    table_rms = float(np.sqrt(np.mean((pts_t @ n + d) ** 2)) * 1000)
    m = roi & (gt > 0) & np.isfinite(depth) & (depth > 0)
    pts = vol.backproject(depth, K, m)
    h_pred = pts @ n + d
    e = dm.depth_errors(depth, gt, roi & (gt > 0))
    e["height_mae_mm"] = float(np.mean(np.abs(h_pred - h_gt[m])) * 1000)
    e["volume_ml"] = V * 1e6
    e["volume_gtplane_ml"] = Vg * 1e6
    e["table_rms_mm"] = table_rms
    return e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n5k", default=os.path.expanduser("~/n5k"))
    ap.add_argument("--models", default="all")
    ap.add_argument("--out", default="results/n5k")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true", help="re-run models whose CSV already exists")
    args = ap.parse_args()

    from mono_depth import MODELS, MonoDepth
    names = list(MODELS) if args.models == "all" else args.models.split(",")
    ids = sorted(open(os.path.join(args.n5k, "depth_test_ids.txt")).read().split())
    if args.limit:
        ids = ids[: args.limit]
    masses = load_masses(args.n5k)
    os.makedirs(args.out, exist_ok=True)

    # Ground truth first: one row per dish, shared by every model.
    gt_path = os.path.join(args.out, "gt.csv")
    cache = {}
    rows = []
    for did in ids:
        gt = cv2.imread(os.path.join(args.n5k, "overhead", did, "depth_raw.png"), -1)
        if gt is None:
            continue
        gt = gt.astype(np.float32) / 1e4
        geo = gt_geometry(gt)
        if geo is None or geo[2].sum() < 500:
            rows.append({"dish": did, "status": "no_roi"})
            continue
        plane, h, roi, table, plate_plane, plate_px, food = geo
        V = vol.volume_from_depth(gt, K, plane, roi & (gt > 0))
        Vf = vol.volume_from_depth(gt, K, plate_plane, food) if food.sum() > 50 else 0.0
        cache[did] = (gt, plane, h, roi, table)
        rows.append({"dish": did, "status": "ok", "mass_g": masses.get(did, np.nan),
                     "gt_volume_ml": V * 1e6, "gt_food_volume_ml": Vf * 1e6,
                     "plate_floor_found": bool(plate_px.any()), "food_px": int(food.sum()), "roi_px": int(roi.sum()),
                     "table_px": int(table.sum()), "gt_hole_frac_roi": float((gt[roi] == 0).mean()),
                     "camera_to_table_mm": float(abs(plane[1]) / abs(plane[0][2]) * 1000)})
    with open(gt_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r}))
        w.writeheader()
        w.writerows(rows)
    print(f"GT: {len(cache)} usable of {len(ids)} dishes -> {gt_path}", flush=True)

    rng = np.random.default_rng(0)
    pro_subset = set(rng.choice(sorted(cache), min(DEPTHPRO_SUBSET, len(cache)), replace=False))

    for name in names:
        out_path = os.path.join(args.out, f"{name}.csv")
        if os.path.exists(out_path) and not args.force:
            print(f"{name}: {out_path} exists, skipping", flush=True)
            continue
        model = MonoDepth(name, threads=args.threads)
        todo = [d for d in sorted(cache) if name != "DepthPro" or d in pro_subset]
        out_rows = []
        t_start = time.time()
        for i, did in enumerate(todo):
            gt, plane, h_gt, roi, table = cache[did]
            rgb = cv2.cvtColor(cv2.imread(os.path.join(args.n5k, "overhead", did, "rgb.png")), cv2.COLOR_BGR2RGB)
            pred, secs = model(rgb, fx=FX)
            row = {"dish": did, "model": name, "kind": model.kind, "infer_s": secs}
            evalm = roi | table
            try:
                if model.kind == "metric":
                    r = evaluate_depth(pred, gt, roi, table, h_gt, plane)
                    row.update({f"raw_{k}": v for k, v in r.items()})
                    row["raw_median_depth_m"] = float(np.median(pred[roi]))
                    # anchor: one scale from the table plane only (no food GT)
                    tp = dm.plane_depth(K, plane, gt.shape)
                    s = float(np.median(tp[table] / pred[table]))
                    r = evaluate_depth(pred * s, gt, roi, table, h_gt, plane)
                    row.update({f"anchor_{k}": v for k, v in r.items()})
                    row["anchor_scale"] = s
                    # oracle: least-squares scale on food+plate+table vs GT
                    ps, _ = dm.align_scale_lsq(pred, np.where(gt > 0, gt, np.nan), evalm & (gt > 0))
                    r = evaluate_depth(ps, gt, roi, table, h_gt, plane)
                    row.update({f"oracle_{k}": v for k, v in r.items()})
                else:
                    # anchor: scale+shift of inverse depth from the table plane
                    # only. Near-fronto-parallel tables make this ill-posed;
                    # we run it anyway and report what it does.
                    tp = dm.plane_depth(K, plane, gt.shape)
                    inv = 1.0 / tp[table]
                    row["anchor_table_invdepth_cv"] = float(inv.std() / inv.mean())
                    depth_a, _, cond = dm.align_disparity_affine(pred, tp, table)
                    row["anchor_condition_number"] = cond
                    try:
                        r = evaluate_depth(depth_a, gt, roi, table, h_gt, plane)
                        row.update({f"anchor_{k}": v for k, v in r.items()})
                    except Exception:
                        row["anchor_volume_ml"] = np.nan
                    depth, (s_, t_), _ = dm.align_disparity_affine(pred, gt, evalm & (gt > 0))
                    r = evaluate_depth(depth, gt, roi, table, h_gt, plane)
                    row.update({f"oracle_{k}": v for k, v in r.items()})
                row["status"] = "ok"
            except Exception as exc:  # degenerate fits are data, not crashes
                row["status"] = f"error:{type(exc).__name__}"
            out_rows.append(row)
            if i % 50 == 0:
                el = time.time() - t_start
                print(f"  {name}: {i+1}/{len(todo)}  {el/(i+1):.2f}s/dish", flush=True)
        with open(out_path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=sorted({k for r in out_rows for k in r}))
            w.writeheader()
            w.writerows(out_rows)
        print(f"{name}: wrote {out_path}", flush=True)
        del model


if __name__ == "__main__":
    main()
