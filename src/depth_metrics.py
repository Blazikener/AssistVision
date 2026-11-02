"""Standard monocular-depth metrics and the alignment protocols they assume.

Three protocols, reported separately because they answer different questions:

  raw       metric model used as-is: what a deployed device would see.
  anchor    one scale (metric models) or scale+shift (relative models) fitted on
            SUPPORT-PLANE pixels only, against a plane the device can measure
            itself (ArUco PnP). Deployable: no food ground truth is used.
  oracle    least-squares fit on the evaluated pixels against ground truth. An
            upper bound that no device can achieve; the literature default.
"""

import numpy as np


def depth_errors(pred, gt, mask):
    m = mask & np.isfinite(pred) & (pred > 0) & (gt > 0)
    p, g = pred[m], gt[m]
    ratio = np.maximum(p / g, g / p)
    return {
        "absrel": float(np.mean(np.abs(p - g) / g)),
        "rmse_mm": float(np.sqrt(np.mean((p - g) ** 2)) * 1000),
        "mae_mm": float(np.mean(np.abs(p - g)) * 1000),
        "delta1": float(np.mean(ratio < 1.25)),
        "delta_1.05": float(np.mean(ratio < 1.05)),
    }


def align_scale_median(pred, gt, mask):
    m = mask & (pred > 0) & (gt > 0)
    return pred * (np.median(gt[m]) / np.median(pred[m]))


def align_scale_lsq(pred, target, mask):
    m = mask & np.isfinite(pred) & np.isfinite(target) & (pred > 0)
    s = float(np.sum(pred[m] * target[m]) / np.sum(pred[m] ** 2))
    return pred * s, s


def align_disparity_affine(disp, target_depth, mask):
    """Relative (affine-invariant inverse depth) -> metric depth.

    Fits s, t so that s*disp + t ~= 1/target on `mask`, then inverts. If the
    mask covers a single fronto-parallel plane, 1/target is ~constant and the
    system is rank deficient: one plane cannot fix two unknowns. We return the
    condition number so callers can report that rather than hide it."""
    m = mask & np.isfinite(disp) & (target_depth > 0)
    A = np.stack([disp[m], np.ones(m.sum())], 1)
    b = 1.0 / target_depth[m]
    (s, t), *_ = np.linalg.lstsq(A, b, rcond=None)
    cond = float(np.linalg.cond(A))
    inv = s * disp + t
    depth = np.where(inv > 1e-6, 1.0 / np.maximum(inv, 1e-6), np.nan)
    return depth, (float(s), float(t)), cond


def plane_depth(K, plane, shape):
    """Depth at which each pixel's ray meets the plane (n, d)."""
    n, d = plane
    h, w = shape
    v, u = np.mgrid[0:h, 0:w]
    r = np.stack([(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], np.ones((h, w))], -1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return -d / (r @ n)
