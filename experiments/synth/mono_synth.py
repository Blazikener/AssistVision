"""Monocular depth on the synthetic rig views, with the deployable marker anchor.

    python experiments/synth/mono_synth.py --scenes data/synth --models DA-V2-S,DepthPro --out results/synth/mono.csv

Uses view 0 of every scene (the same oblique 45 deg camera as the rig) and its
Z-pass depth. Unlike the overhead Nutrition5k camera, an oblique view sees the
mat over a range of depths, so scale AND shift of a relative model are
recoverable from the mat plane alone -- the plane is measured on-device by
solvePnP on the printed markers (known layout). Food masks come from ground
truth (segmentation is out of scope and identical for every model).
"""
import argparse
import csv
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
import depth_metrics as dm  # noqa: E402
import volume as vol  # noqa: E402

ARUCO = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


def read_exr(path):
    import OpenEXR
    with OpenEXR.File(path) as f:
        ch = f.channels()
        return np.array(list(ch.values())[0].pixels, dtype=np.float32)


def masks(gt, depth, K):
    """Food / plate / mat masks from GT depth in the turntable frame."""
    T = np.array(gt["views"][0]["T_cam_from_turntable"])
    h, w = depth.shape
    valid = np.isfinite(depth) & (depth > 0) & (depth < 5)
    v, u = np.mgrid[0:h, 0:w]
    X = np.stack([(u - K[0, 2]) / K[0, 0] * depth, (v - K[1, 2]) / K[1, 1] * depth, depth], -1)
    Xt = (X - T[:3, 3]) @ T[:3, :3]  # camera -> turntable
    r = np.hypot(Xt[..., 0], Xt[..., 1])
    z = Xt[..., 2]
    top = gt["plate"]["top_z"]
    R = gt["plate"]["radius"]
    food = valid & (r < R) & (z > top + 0.002)
    plate = valid & (r < R * 0.95) & (np.abs(z - top) < 0.001)
    from scipy import ndimage
    plate &= ~ndimage.binary_dilation(food, iterations=6)
    mat = valid & (r > R + 0.01) & (r < 0.21) & (np.abs(z) < 0.001)
    return food, plate, mat


def mat_plane_pnp(img, K, gt):
    """Mat plane in camera frame from the printed markers (8 corners, known layout)."""
    det = cv2.aruco.ArucoDetector(ARUCO, cv2.aruco.DetectorParameters())
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = det.detectMarkers(gray)
    if ids is None:
        return None
    layout = {m["id"]: np.array(m["corners"], float) for m in gt["markers"]}
    obj, imgp = [], []
    for c, i in zip(corners, ids.ravel()):
        if int(i) in layout:
            obj.append(layout[int(i)]); imgp.append(c.reshape(4, 2))
    if not obj:
        return None
    obj, imgp = np.concatenate(obj), np.concatenate(imgp).astype(np.float64)
    ok, rvec, tvec = cv2.solvePnP(obj, imgp, K, None, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        return None
    Rm, _ = cv2.Rodrigues(rvec)
    n = Rm[:, 2]
    d = -float(n @ tvec.ravel())
    return vol.orient_towards((n, d), np.zeros(3)), len(obj) // 4


def evaluate(depth, gtd, K, food, plate, mat, plate_gt):
    out = {}
    pts = vol.backproject(depth, K, plate & np.isfinite(depth) & (depth > 0))
    if len(pts) < 50:
        return {"volume_ml": np.nan}
    pl = vol.orient_towards(vol.fit_plane(pts), np.zeros(3))
    out["volume_ml"] = vol.volume_from_depth(depth, K, pl, food) * 1e6
    out.update(dm.depth_errors(depth, gtd, food | plate))
    out["plate_tilt_deg"] = float(np.degrees(np.arccos(min(1.0, abs(pl[0] @ plate_gt[0])))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", default="data/synth")
    ap.add_argument("--models", default="DA-V2-S,DA-V2-B,DA-V2-L,DA-V2-Metric-Indoor-S,DA-V2-Metric-Indoor-L,ZoeDepth-NYU,MiDaS-DPT-Hybrid,DepthPro")
    ap.add_argument("--out", default="results/synth/mono.csv")
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    from mono_depth import MonoDepth
    scenes = sorted(d for d in os.listdir(a.scenes) if os.path.exists(os.path.join(a.scenes, d, "gt.json")))
    cache = {}
    for s in scenes:
        gt = json.load(open(os.path.join(a.scenes, s, "gt.json")))
        K = np.array(gt["K"], float)
        img = cv2.imread(os.path.join(a.scenes, s, "view_00.png"))
        gtd = read_exr(os.path.join(a.scenes, s, gt["depth_files"]["0"]))
        food, plate, mat = masks(gt, gtd, K)
        mp = mat_plane_pnp(img, K, gt)
        pts = vol.backproject(gtd, K, plate)
        plate_gt = vol.orient_towards(vol.fit_plane(pts), np.zeros(3))
        v_gtdepth = vol.volume_from_depth(gtd, K, plate_gt, food) * 1e6
        cache[s] = (gt, K, img, gtd, food, plate, mat, mp, plate_gt, v_gtdepth)
    rows = []
    for name in a.models.split(","):
        model = MonoDepth(name, threads=a.threads)
        for s in scenes:
            gt, K, img, gtd, food, plate, mat, mp, plate_gt, v_gtdepth = cache[s]
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            pred, secs = model(rgb, fx=K[0, 0])
            base = {"scene": s, "plate": gt["plate"]["kind"], "model": name, "kind": model.kind, "infer_s": secs,
                    "gt_volume_ml": gt["food_volume_m3"] * 1e6, "gtdepth_volume_ml": v_gtdepth,
                    "markers_seen": mp[1] if mp else 0}
            protos = {}
            if model.kind == "metric":
                protos["raw"] = pred
            if mp is not None:
                tp = dm.plane_depth(K, mp[0], pred.shape)
                if model.kind == "metric":
                    protos["anchor"], _ = dm.align_scale_lsq(pred, tp, mat)
                else:
                    protos["anchor"], st, cond = dm.align_disparity_affine(pred, tp, mat)
                    base["anchor_condition_number"] = cond
            if model.kind == "metric":
                protos["oracle"], _ = dm.align_scale_lsq(pred, gtd, food | plate)
            else:
                protos["oracle"], _, _ = dm.align_disparity_affine(pred, gtd, food | plate)
            for p, dep in protos.items():
                e = evaluate(dep, gtd, K, food, plate, mat, plate_gt)
                rows.append({**base, "protocol": p, **e,
                             "vol_err_pct": (e["volume_ml"] / base["gt_volume_ml"] - 1) * 100})
            print(name, s, {r["protocol"]: round(r["vol_err_pct"], 1) for r in rows[-len(protos):]}, flush=True)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=sorted({k for r in rows for k in r}))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {a.out} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
