"""
Volume pipeline checks against shapes whose volume is known in closed form.

  python src/test_volume.py

Same philosophy as test_geometry.py: synthetic input with an exact answer, so
a failure means the code is wrong, never the data.
"""

import sys

import numpy as np

import depth_metrics as dm
import stats
import volume as vol

K = np.array([[600.0, 0, 320], [0, 600.0, 240], [0, 0, 1]])


def spherical_cap_depth(h_cap=0.03, r_base=0.06, z_table=0.40, shape=(480, 640), tilt_deg=0.0):
    """Ray-cast a spherical cap sitting on a (possibly tilted) table plane."""
    h, w = shape
    v, u = np.mgrid[0:h, 0:w]
    r = np.stack([(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], np.ones((h, w))], -1)
    t = np.deg2rad(tilt_deg)
    n = np.array([0.0, np.sin(t), -np.cos(t)])        # normal points at the camera
    c0 = np.array([0.0, 0.0, z_table])                  # cap base centre on the plane
    d = -n @ c0
    depth = dm.plane_depth(K, (n, d), shape)
    # sphere radius R from cap height and base radius
    R = (r_base ** 2 + h_cap ** 2) / (2 * h_cap)
    centre = c0 + n * (h_cap - R)
    rn = r / np.linalg.norm(r, axis=-1, keepdims=True)
    b = rn @ centre
    disc = b ** 2 - (centre @ centre - R ** 2)
    hit = disc > 0
    s = b - np.sqrt(np.where(hit, disc, 0))
    pts = rn * s[..., None]
    above = hit & ((pts @ n + d) > 0)
    zc = s * rn[..., 2]
    depth = np.where(above & (zc < depth), zc, depth)
    true_v = np.pi * h_cap ** 2 * (3 * R - h_cap) / 3
    return depth, (n, d), true_v


def check_depth_volume_frontoparallel():
    depth, plane, true_v = spherical_cap_depth()
    mask = np.ones_like(depth, bool)
    est = vol.volume_from_depth(depth, K, plane, mask)
    err = abs(est - true_v) / true_v
    z0 = 0.40
    px_area = (z0 / K[0, 0]) * (z0 / K[1, 1])
    base = vol.volume_constant_footprint(depth, z0, mask, px_area)
    berr = abs(base - true_v) / true_v
    print(f"  true {true_v*1e6:8.2f} mL   height-field {est*1e6:8.2f} mL ({err*100:.2f}%)   "
          f"constant-footprint baseline {base*1e6:8.2f} mL ({berr*100:.2f}%)")
    assert err < 0.02, err


def check_depth_volume_tilted():
    depth, plane, true_v = spherical_cap_depth(tilt_deg=35.0, z_table=0.35)
    est = vol.volume_from_depth(depth, K, plane, np.ones_like(depth, bool))
    err = abs(est - true_v) / true_v
    print(f"  35 deg tilt: true {true_v*1e6:8.2f} mL   est {est*1e6:8.2f} mL   err {err*100:.2f}%")
    assert err < 0.02, err


def check_heightmap_volume_matches():
    depth, plane, true_v = spherical_cap_depth()
    pts = vol.backproject(depth, K)
    plane_fit, inl = vol.fit_plane_ransac(pts, threshold=0.001)
    plane_fit = vol.orient_towards(plane_fit, np.zeros(3))
    v, H, _ = vol.volume_from_points(pts, plane_fit, cell=0.001, reduce="max")
    err = abs(v - true_v) / true_v
    print(f"  heightmap (1 mm cells, RANSAC plane): {v*1e6:8.2f} mL   err {err*100:.2f}%   "
          f"plane inliers {inl.mean()*100:.1f}%")
    assert err < 0.02, err


def check_cube_law():
    """A scale error s on length is s^3 on volume -- the reason the marker matters."""
    depth, plane, true_v = spherical_cap_depth()
    pts = vol.backproject(depth, K) * 1.05
    pl = vol.orient_towards(vol.fit_plane_ransac(pts, 0.001)[0], np.zeros(3))
    v, _, _ = vol.volume_from_points(pts, pl, cell=0.00105)
    ratio = v / true_v
    print(f"  +5% length -> volume x{ratio:.4f}  (1.05^3 = {1.05**3:.4f})")
    assert abs(ratio - 1.05 ** 3) < 0.02


def check_relative_depth_needs_two_anchors():
    """A single fronto-parallel plane cannot fix scale AND shift of inverse depth."""
    depth, plane, _ = spherical_cap_depth()
    disp = 3.0 / depth + 1.0
    table = np.abs(depth - 0.40) < 1e-6
    _, _, cond = dm.align_disparity_affine(disp, depth, table)
    _, _, cond_all = dm.align_disparity_affine(disp, depth, np.ones_like(table))
    print(f"  condition number: table-only {cond:.2e}   table+food {cond_all:.2e}")
    assert cond > 1e6 and cond_all < 1e6


def check_stats():
    p, lo, hi = stats.wilson_ci(24, 25)
    print(f"  24/25 detections -> {p*100:.0f}% [95% CI {lo*100:.1f}, {hi*100:.1f}]")
    assert 0.79 < lo < 0.81 and hi > 0.99
    m, lo, hi = stats.bootstrap_ci(np.arange(100.0))
    assert lo < m < hi


CHECKS = [
    ("per-pixel volume, fronto-parallel cap", check_depth_volume_frontoparallel),
    ("per-pixel volume, tilted table", check_depth_volume_tilted),
    ("height-field volume from point cloud", check_heightmap_volume_matches),
    ("cube law under scale error", check_cube_law),
    ("relative depth is rank-deficient on one plane", check_relative_depth_needs_two_anchors),
    ("Wilson and bootstrap intervals", check_stats),
]


def main():
    failed = 0
    for name, fn in CHECKS:
        print(name)
        try:
            fn()
        except AssertionError as e:
            print(f"  FAIL: {e}\n")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}\n")
            failed += 1
        else:
            print("  PASS\n")
    print(f"{len(CHECKS) - failed}/{len(CHECKS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
