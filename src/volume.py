"""
Depth / point cloud -> metric volume above a support plane.

Every reconstruction path in this project (RealSense depth, monocular depth,
multi-view point cloud) ends here, so all of them are scored by exactly the
same integral. Differences in the results are therefore differences in the
geometry each path recovered, never differences in how volume was computed.

Conventions: camera frame, metres, +Z forward, pinhole K without distortion
(undistort before calling). A plane is (n, d) with unit normal n and
n . X + d = 0; heights are signed distances, positive on the camera side.
"""

import numpy as np


def backproject(depth, K, mask=None):
    """Depth map (H, W) in metres -> (N, 3) camera-frame points."""
    h, w = depth.shape
    v, u = np.mgrid[0:h, 0:w]
    valid = np.isfinite(depth) & (depth > 0)
    if mask is not None:
        valid &= mask
    z = depth[valid]
    x = (u[valid] - K[0, 2]) * z / K[0, 0]
    y = (v[valid] - K[1, 2]) * z / K[1, 1]
    return np.stack([x, y, z], axis=1)


def fit_plane(points):
    """Least-squares plane through points (SVD)."""
    c = points.mean(axis=0)
    _, _, vt = np.linalg.svd(points - c, full_matrices=False)
    n = vt[-1]
    return n, -float(n @ c)


def orient_towards(plane, viewpoint):
    """Flip the plane so heights are positive on the side of `viewpoint`."""
    n, d = plane
    if n @ viewpoint + d < 0:
        n, d = -n, -d
    return n, d


def fit_plane_ransac(points, threshold=0.003, iters=500, seed=0, max_score_pts=50000):
    """RANSAC plane, refit on inliers. threshold in metres.

    Returns ((n, d), inlier_mask). Food is the minority structure in every
    capture, so the dominant plane is the table (or the flat thali)."""
    rng = np.random.default_rng(seed)
    n_pts = len(points)
    if n_pts < 3:
        raise ValueError("need at least 3 points to fit a plane")
    # Hypotheses are scored on a fixed random subset (inlier fractions are
    # estimated to <0.5% at 50k points); the final refit uses every inlier.
    score = points[rng.choice(n_pts, max_score_pts, replace=False)] if n_pts > max_score_pts else points
    best = None
    best_count = -1
    for _ in range(iters):
        p = points[rng.choice(n_pts, 3, replace=False)]
        n = np.cross(p[1] - p[0], p[2] - p[0])
        norm = np.linalg.norm(n)
        if norm < 1e-12:
            continue
        n /= norm
        d = -n @ p[0]
        count = int(np.count_nonzero(np.abs(score @ n + d) < threshold))
        if count > best_count:
            best_count, best = count, (n, d)
    n, d = best
    inliers = np.abs(points @ n + d) < threshold
    return fit_plane(points[inliers]), inliers


def plane_basis(n):
    """Two unit vectors spanning the plane orthogonal to n."""
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(n, a)
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(n, e1)


def heightmap(points, plane, cell=0.001, origin=None, extent=None, reduce="max"):
    """Rasterise points into a height field over the plane.

    Returns (H, (u0, v0)) where H[i, j] is the height of cell (i, j) or NaN if
    no point fell in it. `reduce` picks the visible surface: 'max' for a
    cloud that only samples the top surface (multi-view), 'median' to be
    robust to MVS speckle."""
    n, d = plane
    e1, e2 = plane_basis(n)
    h = points @ n + d
    uv = np.stack([points @ e1, points @ e2], axis=1)
    if origin is None:
        origin = uv.min(axis=0)
    idx = np.floor((uv - origin) / cell).astype(int)
    if extent is None:
        extent = idx.max(axis=0) + 1
    extent = tuple(int(e) for e in extent)
    keep = (idx[:, 0] >= 0) & (idx[:, 1] >= 0) & (idx[:, 0] < extent[0]) & (idx[:, 1] < extent[1])
    idx, h = idx[keep], h[keep]
    flat = idx[:, 0] * extent[1] + idx[:, 1]
    out = np.full(extent[0] * extent[1], np.nan)
    if len(flat):
        # Grouped reduction without a Python loop: sort by (cell, height), then
        # every group is a contiguous run with its values in ascending order.
        order = np.lexsort((h, flat))
        flat, h = flat[order], h[order]
        starts = np.r_[0, np.flatnonzero(np.diff(flat)) + 1]
        counts = np.diff(np.r_[starts, len(flat)])
        if reduce == "max":
            vals = h[starts + counts - 1]
        elif reduce == "median":
            vals = 0.5 * (h[starts + (counts - 1) // 2] + h[starts + counts // 2])
        else:
            vals = np.add.reduceat(h, starts) / counts
        out[flat[starts]] = vals
    return out.reshape(extent), origin


def fill_holes(H, footprint):
    """Nearest-neighbour fill of empty cells inside `footprint` (bool)."""
    from scipy import ndimage
    H = H.copy()
    empty = np.isnan(H)
    if not empty.any() or empty.all():
        return H
    _, (ii, jj) = ndimage.distance_transform_edt(empty, return_indices=True)
    filled = H[ii, jj]
    H[empty & footprint] = filled[empty & footprint]
    return H


def volume_from_points(points, plane, cell=0.001, footprint=None, origin=None,
                       extent=None, reduce="max", clip_negative=True):
    """Volume (m^3) between the plane and the visible surface of `points`.

    `footprint` (bool grid matching extent) restricts integration to the
    region of interest; empty cells inside it are filled from neighbours."""
    H, origin = heightmap(points, plane, cell, origin, extent, reduce)
    if footprint is None:
        footprint = ~np.isnan(H)
    H = fill_holes(H, footprint)
    H = np.where(footprint, H, 0.0)
    H = np.nan_to_num(H, nan=0.0)
    if clip_negative:
        H = np.clip(H, 0.0, None)
    return float(H.sum() * cell * cell), H, origin


def volume_from_depth(depth, K, plane, mask, cell=0.0015, reduce="median"):
    """Volume of the masked region of a depth map, via the height field.

    Back-project, rasterise onto the plane, integrate. Works for any camera
    tilt. Footprint = occupied cells, morphologically closed so sampling gaps
    inside the region are filled instead of counted as zero height."""
    from scipy import ndimage
    pts = backproject(depth, K, mask)
    H, origin = heightmap(pts, plane, cell, reduce=reduce)
    footprint = ndimage.binary_closing(~np.isnan(H), iterations=2)
    footprint = ndimage.binary_fill_holes(footprint)
    v, _, _ = volume_from_points(pts, plane, cell, footprint, origin, H.shape, reduce)
    return v


def volume_constant_footprint(depth, plane_depth_m, mask, pixel_area_m2):
    """Nutrition5k / Ando et al. estimator: sum of (plane depth - depth) times
    a constant per-pixel area. Only valid for a fronto-parallel camera; kept
    as the published baseline the height-field method is compared against."""
    h = np.clip(plane_depth_m - depth, 0, None)
    h = np.where(mask & (depth > 0), h, 0)
    return float(h.sum() * pixel_area_m2)
