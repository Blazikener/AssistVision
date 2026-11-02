"""Multi-view metric reconstruction of a synthetic (or rig) scan -> food volume.

    python experiments/synth/reconstruct.py --scene data/synth/rice_dal__ceramic \
        --views 24 --scale 1.0 --jpeg 0 --dense openmvs --out results/synth/runs/x

Pipeline (identical for synthetic renders and real rig scans):
  1. SIFT + exhaustive matching + incremental SfM (pycolmap), intrinsics fixed
     to the calibration (K from gt.json here, calibrate.py on the rig).
  2. Metric scale: detect the ArUco markers in every view, triangulate their
     corners with the recovered poses (DLT over all observing views), and set
     scale = known side / mean triangulated side. Same dictionary as
     src/make_aruco.py.
  3. Support plane: plane through the triangulated marker corners (the mat),
     then the plate top is the dominant height mode 2-30 mm above it.
  4. Dense points: OpenMVS DensifyPointCloud (CPU, Docker) or, with
     --dense sparse, the SfM points alone (to show why dense is needed).
  5. Volume: src/volume.volume_from_points on the plate frame -- the same
     integral every other path uses.

Ablation knobs: --views (subsample evenly), --resize (sensor resolution),
--jpeg (re-encode quality, emulates ESP32 JPEG), --scale (multiply the
marker side the pipeline believes, i.e. a mis-printed marker).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
import volume as vol  # noqa: E402

OPENMVS_IMAGE = "openmvs/openmvs-ubuntu:latest"
ARUCO = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


def prepare_images(scene, gt, views, resize, jpeg, work):
    img_dir = os.path.join(work, "images")
    os.makedirs(img_dir, exist_ok=True)
    n = len(gt["views"])
    idx = np.round(np.linspace(0, n, views, endpoint=False)).astype(int)
    names = []
    for i in idx:
        im = cv2.imread(os.path.join(scene, gt["views"][i]["file"]))
        if resize != 1.0:
            im = cv2.resize(im, None, fx=resize, fy=resize, interpolation=cv2.INTER_AREA)
        name = f"v{i:02d}.png"
        if jpeg:
            ok, buf = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, jpeg])
            im = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        cv2.imwrite(os.path.join(img_dir, name), im)
        names.append(name)
    K = np.array(gt["K"], float)
    K[:2] *= resize
    if resize != 1.0:  # pixel-centre convention: c' = (c + 0.5) * s - 0.5
        K[0, 2] = (gt["K"][0][2] + 0.5) * resize - 0.5
        K[1, 2] = (gt["K"][1][2] + 0.5) * resize - 0.5
    return img_dir, names, idx, K


def run_sfm(img_dir, names, K, work):
    import pycolmap
    db = os.path.join(work, "db.db")
    h, w = cv2.imread(os.path.join(img_dir, names[0])).shape[:2]
    ro = pycolmap.ImageReaderOptions()
    ro.camera_model = "PINHOLE"
    ro.camera_params = f"{K[0,0]},{K[1,1]},{K[0,2]},{K[1,2]}"
    pycolmap.extract_features(db, img_dir, image_names=names, camera_mode=pycolmap.CameraMode.SINGLE,
                              reader_options=ro, device=pycolmap.Device.cpu)
    pycolmap.match_exhaustive(db, device=pycolmap.Device.cpu)
    opts = pycolmap.IncrementalPipelineOptions()
    opts.ba_refine_focal_length = False
    opts.ba_refine_principal_point = False
    opts.ba_refine_extra_params = False
    sparse = os.path.join(work, "sparse")
    os.makedirs(sparse, exist_ok=True)
    recs = pycolmap.incremental_mapping(db, img_dir, sparse, options=opts)
    if not recs:
        return None, sparse
    best = max(recs.values(), key=lambda r: r.num_reg_images())
    out = os.path.join(sparse, "best")
    os.makedirs(out, exist_ok=True)
    best.write(out)
    return best, out


def projection_matrices(rec, K):
    P = {}
    for img in rec.images.values():
        if not img.has_pose:
            continue
        T = img.cam_from_world().matrix()  # 3x4
        P[img.name] = K @ T
    return P


def triangulate(obs):
    """DLT triangulation of one point from [(P, uv), ...]."""
    A = []
    for P, (u, v) in obs:
        A.append(u * P[2] - P[0])
        A.append(v * P[2] - P[1])
    _, _, vt = np.linalg.svd(np.asarray(A))
    X = vt[-1]
    return X[:3] / X[3]


def marker_corners_3d(img_dir, P):
    det = cv2.aruco.ArucoDetector(ARUCO, cv2.aruco.DetectorParameters())
    obs = {}
    for name, Pm in P.items():
        im = cv2.imread(os.path.join(img_dir, name), cv2.IMREAD_GRAYSCALE)
        corners, ids, _ = det.detectMarkers(im)
        if ids is None:
            continue
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.01)
        for c, i in zip(corners, ids.ravel()):
            c = cv2.cornerSubPix(im, c.reshape(-1, 1, 2).astype(np.float32), (5, 5), (-1, -1), crit).reshape(4, 2)
            for k in range(4):
                obs.setdefault((int(i), k), []).append((Pm, c[k]))
    pts = {key: triangulate(o) for key, o in obs.items() if len(o) >= 3}
    n_obs = {key: len(o) for key, o in obs.items()}
    return pts, n_obs


def metric_scale(pts, side):
    sides = []
    for mid in {k[0] for k in pts}:
        c = [pts.get((mid, k)) for k in range(4)]
        if any(x is None for x in c):
            continue
        sides += [np.linalg.norm(c[k] - c[(k + 1) % 4]) for k in range(4)]
    if not sides:
        return None, 0
    return side / float(np.mean(sides)), len(sides)


def densify_openmvs(work, threads=6, resolution_level=2):
    import pycolmap
    dense = os.path.join(work, "dense")
    pycolmap.undistort_images(dense, os.path.join(work, "sparse", "best"), os.path.join(work, "images"))
    # The OpenMVS 2019 build in the Docker image only reads the COLMAP text
    # model (cameras/images/points3D.txt), not the newer rigs/frames files.
    sp = os.path.join(dense, "sparse")
    rec = pycolmap.Reconstruction(sp)
    for f in os.listdir(sp):
        os.remove(os.path.join(sp, f))
    rec.write_text(sp)
    for f in ("rigs.txt", "frames.txt"):
        if os.path.exists(os.path.join(sp, f)):
            os.remove(os.path.join(sp, f))
    # OpenMVS's COLMAP importer expects sparse/ to hold the text or binary model.
    uid, gid = os.getuid(), os.getgid()
    # --image-folder makes this OpenMVS build write a scene that DensifyPointCloud
    # then fails to parse (std::length_error); the default image lookup works.
    cmd = (f"cd /w && InterfaceCOLMAP -i /w -o /w/scene.mvs && "
           f"DensifyPointCloud /w/scene.mvs --resolution-level {resolution_level} --max-threads {threads} "
           f"--number-views-fuse 2; rc=$?; chown -R {uid}:{gid} /w; exit $rc")
    t0 = time.time()
    r = subprocess.run(["docker", "run", "--rm", "-v", f"{os.path.abspath(dense)}:/w", OPENMVS_IMAGE, "bash", "-c", cmd],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stdout[-2000:] + r.stderr[-2000:])
    import open3d as o3d
    pc = o3d.io.read_point_cloud(os.path.join(dense, "scene_dense.ply"))
    return np.asarray(pc.points), time.time() - t0


def plate_plane(points, mat_plane):
    """Plate top = densest height mode 2-30 mm above the mat (after metric scaling)."""
    n, d = mat_plane
    hgt = points @ n + d
    sel = (hgt > 0.002) & (hgt < 0.030)
    if sel.sum() < 100:
        return mat_plane, 0.0
    hist, edges = np.histogram(hgt[sel], bins=np.arange(0.002, 0.0305, 0.0005))
    z = 0.5 * (edges[hist.argmax()] + edges[hist.argmax() + 1])
    band = sel & (np.abs(hgt - z) < 0.0015)
    plane = vol.orient_towards(vol.fit_plane(points[band]), points[band].mean(0) + n)
    return plane, z


def food_volume(points, plane, plate_radius, cell=0.002, k_sigma=2.0, min_height=0.003, open_iter=1,
                hysteresis=False, k_low=0.5):
    """Food volume above the plate from a (noisy) MVS point cloud.

    The plate plane (density mode, plate_plane) is accurate, but MVS on a
    smooth plate scatters cell medians a few mm above it, so a fixed 3 mm
    threshold doubles the footprint. The threshold is therefore set from the
    plate's own noise: median + k_sigma * robust sigma of cell heights in the
    outer annulus (0.75-0.95 R), where food rarely sits. Heights stay relative
    to the plate plane. Rule fixed on rice_mound__ceramic; all other scenes
    are held out.

    hysteresis=True is a post-hoc variant added after curry_heap__ceramic
    lost its low skirt (-26%) under the primary rule; both are reported."""
    from scipy import ndimage
    H, origin = vol.heightmap(points, plane, cell, reduce="median")
    ii, jj = np.indices(H.shape)
    n, d = plane
    u, v = vol.plane_basis(n)
    c0 = -d * n  # plate-plane point closest to the origin == projected plate centre (centred upstream)
    ci = (c0 @ u - origin[0]) / cell
    cj = (c0 @ v - origin[1]) / cell
    rho = np.hypot(ii - ci, jj - cj) * cell
    ann = (rho > 0.75 * plate_radius) & (rho < 0.95 * plate_radius) & ~np.isnan(H)
    level, sigma = 0.0, 0.0
    if ann.sum() > 50:
        level = float(np.median(H[ann]))
        sigma = float(1.4826 * np.median(np.abs(H[ann] - level)))
    thr = max(min_height, level + k_sigma * sigma)
    Hz = np.nan_to_num(H, nan=0.0)
    fp = Hz > thr
    if open_iter:
        fp = ndimage.binary_opening(fp, iterations=open_iter)
    if hysteresis:
        # grow the confident seeds into connected cells above a low threshold so
        # the thin skirt of a heap is kept; isolated plate noise has no seed
        low = Hz > max(min_height, level + k_low * sigma)
        lab_l, _ = ndimage.label(low | fp)
        fp = np.isin(lab_l, np.unique(lab_l[fp & (lab_l > 0)]))
    fp = ndimage.binary_fill_holes(ndimage.binary_closing(fp, iterations=2))
    lab, nl = ndimage.label(fp)
    if nl > 1:
        sizes = ndimage.sum(fp, lab, range(1, nl + 1))
        fp = np.isin(lab, 1 + np.flatnonzero(sizes * cell * cell >= 1e-4))
    V, _, _ = vol.volume_from_points(points, plane, cell, fp, origin, H.shape, reduce="median")
    return V, {"plate_level_mm": level * 1e3, "plate_noise_mm": sigma * 1e3,
               "footprint_thr_mm": thr * 1e3, "footprint_cm2": float(fp.sum() * cell * cell * 1e4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True)
    ap.add_argument("--views", type=int, default=24)
    ap.add_argument("--resize", type=float, default=1.0)
    ap.add_argument("--jpeg", type=int, default=0)
    ap.add_argument("--scale", type=float, default=1.0, help="believed/true marker side ratio")
    ap.add_argument("--dense", choices=["openmvs", "sparse"], default="openmvs")
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--rep", type=int, default=0, help="repeat index (recorded only; SfM/MVS are not bit-deterministic)")
    a = ap.parse_args()

    gt = json.load(open(os.path.join(a.scene, "gt.json")))
    work = os.path.abspath(a.out)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    res = {"scene": os.path.basename(os.path.normpath(a.scene)), "views": a.views, "resize": a.resize,
           "jpeg": a.jpeg, "scale_factor": a.scale, "dense": a.dense, "rep": a.rep,
           "gt_volume_ml": gt["food_volume_m3"] * 1e6, "plate": gt["plate"]["kind"]}
    t0 = time.time()
    try:
        img_dir, names, idx, K = prepare_images(a.scene, gt, a.views, a.resize, a.jpeg, work)
        rec, _ = run_sfm(img_dir, names, K, work)
        res["sfm_s"] = time.time() - t0
        if rec is None:
            raise RuntimeError("sfm failed")
        res["registered"] = rec.num_reg_images()
        res["sparse_points"] = rec.num_points3D()
        res["reproj_px"] = rec.compute_mean_reprojection_error()
        P = projection_matrices(rec, K)
        pts, n_obs = marker_corners_3d(img_dir, P)
        s, n_sides = metric_scale(pts, gt["marker_side"] * a.scale)
        res["marker_sides_used"] = n_sides
        if s is None:
            raise RuntimeError("no marker triangulated")
        res["metric_scale"] = s
        mat = vol.fit_plane(np.array(list(pts.values())) * s)
        cams = np.array([img.projection_center() for img in rec.images.values() if img.has_pose]) * s
        mat = vol.orient_towards(mat, cams.mean(0))
        res["marker_plane_rms_mm"] = float(np.sqrt(np.mean((np.array(list(pts.values())) * s @ mat[0] + mat[1]) ** 2)) * 1e3)

        # Pose accuracy vs ground truth: camera-centre error after the metric
        # (not similarity) alignment, in the turntable frame.
        gt_c = []
        for i in idx:
            T = np.array(gt["views"][i]["T_cam_from_turntable"])
            gt_c.append(-T[:3, :3].T @ T[:3, 3])
        est_c = np.array([rec.find_image_with_name(n).projection_center() for n in names
                          if rec.find_image_with_name(n) is not None and rec.find_image_with_name(n).has_pose]) * s
        gt_c = np.array([g for g, n in zip(gt_c, names) if rec.find_image_with_name(n) is not None
                         and rec.find_image_with_name(n).has_pose])
        if len(gt_c) >= 3:
            dg = np.linalg.norm(gt_c - gt_c.mean(0), axis=1)
            de = np.linalg.norm(est_c - est_c.mean(0), axis=1)
            res["scale_error_pct"] = float((de.mean() / dg.mean() - 1) * 100)

        if a.dense == "openmvs":
            points, dt = densify_openmvs(work)
            res["densify_s"] = dt
            points = points * s
        else:
            points = np.array([p.xyz for p in rec.points3D.values()]) * s
        res["dense_points"] = int(len(points))

        plane, plate_h = plate_plane(points, mat)
        res["plate_height_mm"] = plate_h * 1e3
        res["gt_plate_height_mm"] = gt["plate"]["top_z"] * 1e3
        # Restrict to the plate disc: centre = projection of marker-corner centroid
        # (markers sit symmetric about the turntable axis).
        centre = np.array(list(pts.values())).mean(0) * s
        n, d = plane
        centre = centre - (centre @ n + d) * n
        rad = np.linalg.norm(points - centre - ((points - centre) @ n)[:, None] * n, axis=1)
        on_plate = rad < gt["plate"]["radius"] * 0.97
        hgt = points @ n + d
        food = on_plate & (hgt > 0.003) & (hgt < 0.15)
        res["food_points"] = int(food.sum())
        # shift so the projected plate centre is the origin of the plane frame
        sel = points[on_plate & (hgt > -0.01)] - centre
        # ~8k sparse SfM points cannot fill 2 mm cells; use 6 mm and no opening
        cell, oi = (0.002, 1) if a.dense == "openmvs" else (0.006, 0)
        V, info = food_volume(sel, (n, d + n @ centre), gt["plate"]["radius"], cell=cell, open_iter=oi)
        res.update(info)
        Vh, info_h = food_volume(sel, (n, d + n @ centre), gt["plate"]["radius"], cell=cell, open_iter=oi,
                                 hysteresis=True)
        res["volume_hyst_ml"] = Vh * 1e6
        res["volume_hyst_err_pct"] = (Vh * 1e6 / res["gt_volume_ml"] - 1) * 100
        res["footprint_hyst_cm2"] = info_h["footprint_cm2"]
        # always kept (~10 MB) so footprint rules can be re-evaluated offline
        np.savez_compressed(os.path.join(work, "plate_points.npz"), points=points[on_plate & (hgt > -0.01)],
                            n=n, d=d, centre=centre)
        res["volume_ml"] = V * 1e6
        res["volume_err_pct"] = (res["volume_ml"] / res["gt_volume_ml"] - 1) * 100
        res["status"] = "ok"
    except Exception as e:  # recorded, not hidden: failures are results too
        res["status"] = f"error: {type(e).__name__}: {str(e)[:300]}"
    res["total_s"] = time.time() - t0
    json.dump(res, open(os.path.join(work, "result.json"), "w"), indent=1)
    if not a.keep:
        for sub in ("images", "dense", "db.db"):
            p = os.path.join(work, sub)
            shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else (os.path.exists(p) and os.remove(p))
    print(json.dumps(res))


if __name__ == "__main__":
    main()
