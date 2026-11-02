"""Which item on the plate was left.

Per-item eaten share from two photos: the centre frame of the served burst and
of the cleared burst. Both are warped to a top-down view of the marker mat, so
pose and distance changes between the two presses drop out. Food is whatever
differs from the bare plate rim in colour or texture; the served food pixels
are split into the K menu items by colour plus position, and the cleared food
pixels are assigned to the nearest served item.
"""
from __future__ import annotations

import cv2
import numpy as np

ARUCO = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
# Corner positions (m) of the two markers on the printed mat, plate centre at 0.
MAT_MARKERS = {0: [(0.145, 0.025), (0.195, 0.025), (0.195, -0.025), (0.145, -0.025)],
               1: [(-0.195, 0.025), (-0.145, 0.025), (-0.145, -0.025), (-0.195, -0.025)]}
HALF = 0.15          # top-down view covers +-15 cm around the plate centre
PX_PER_M = 1000      # 1 px = 1 mm
RIM = (0.110, 0.125)  # bare-rim ring used as the plate colour reference (m)
DELTA_E = 12.0       # Lab distance that counts as "not plate"
TEXTURE = 6.0        # extra local grey-level std that counts as "not plate"
POS_W = 0.5          # weight of position (mm) against colour (Lab units)
GATE = 60.0          # cleared pixels further than this from every item are ignored
SMOOTH = 9           # label vote window (px): fixes mixed-colour pixels on item edges
SHRINK_EXP = 1.5     # a mound that shrinks evenly keeps V proportional to A^1.5


def top_down(img: np.ndarray) -> np.ndarray:
    det = cv2.aruco.ArucoDetector(ARUCO, cv2.aruco.DetectorParameters())
    corners, ids, _ = det.detectMarkers(img)
    src, dst = [], []
    for c, i in zip(corners, [] if ids is None else ids.ravel()):
        if int(i) in MAT_MARKERS:
            src += list(c.reshape(4, 2))
            dst += [((x + HALF) * PX_PER_M, (HALF - y) * PX_PER_M) for x, y in MAT_MARKERS[int(i)]]
    if len(src) < 8:
        raise ValueError("both mat markers must be in the photo")
    H, _ = cv2.findHomography(np.float32(src), np.float32(dst))
    n = int(2 * HALF * PX_PER_M)
    return cv2.warpPerspective(img, H, (n, n))


def _radius(n: int) -> np.ndarray:
    yy, xx = np.mgrid[:n, :n]
    return np.hypot(xx - n / 2, yy - n / 2) / PX_PER_M


def food_mask(td: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = td.shape[0]
    r = _radius(n)
    lab = cv2.cvtColor(td, cv2.COLOR_BGR2LAB).astype(np.float32)
    ring = (r > RIM[0]) & (r < RIM[1])
    d = np.linalg.norm(lab - np.median(lab[ring], axis=0), axis=2)
    g = cv2.cvtColor(td, cv2.COLOR_BGR2GRAY).astype(np.float32)
    std = np.sqrt(np.maximum(cv2.blur(g * g, (7, 7)) - cv2.blur(g, (7, 7)) ** 2, 0))
    m = ((d > DELTA_E) | (std > np.median(std[ring]) + TEXTURE)) & (r < RIM[0])
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    m = cv2.erode(m, np.ones((7, 7), np.uint8))  # undo the 3 px spread of the 7x7 texture window
    return m.astype(bool), lab


def _features(lab: np.ndarray, m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ys, xs = np.nonzero(m)
    return np.column_stack([lab[ys, xs], POS_W * xs, POS_W * ys]).astype(np.float32), np.column_stack([xs, ys])


def _vote(labels: np.ndarray, m: np.ndarray, k: int) -> np.ndarray:
    """Majority label in a SMOOTH x SMOOTH window, so an item's edge joins that item."""
    img = np.full(m.shape, -1, int)
    img[m] = labels
    votes = np.stack([cv2.blur((img == i).astype(np.float32), (SMOOTH, SMOOTH)) for i in range(k)])
    out = votes.argmax(0)[m]
    return np.where(labels < 0, -1, out)


def items_eaten(served: np.ndarray, cleared: np.ndarray, k: int) -> list[dict]:
    """Per-item eaten share from a served and a cleared photo (BGR) of the same plate."""
    ms, labs = food_mask(top_down(served))
    mc, labc = food_mask(top_down(cleared))
    fs, ps = _features(labs, ms)
    if len(fs) < 50 * k:
        raise ValueError("too little food found in the served photo")
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.5)
    cv2.setRNGSeed(0)
    _, lab_s, centres = cv2.kmeans(fs, k, None, crit, 5, cv2.KMEANS_PP_CENTERS)
    lab_s = _vote(lab_s.ravel(), ms, k)
    fc, _ = _features(labc, mc)
    if len(fc):
        d = np.linalg.norm(fc[:, None, :] - centres[None], axis=2)
        lab_c = _vote(np.where(d.min(1) < GATE, d.argmin(1), -1), mc, k)
    else:
        lab_c = np.array([], int)
    n = ms.shape[0]
    out = []
    for i in range(k):
        a_s, a_c = int((lab_s == i).sum()), int((lab_c == i).sum())
        frac = min(a_c / a_s, 1.0) if a_s else 1.0
        cx, cy = ps[lab_s == i].mean(0) if a_s else (n / 2, n / 2)
        out.append({"x": (cx - n / 2) / PX_PER_M, "y": (n / 2 - cy) / PX_PER_M,
                    "lab": [float(v) for v in centres[i][:3]],
                    "served_cm2": a_s / 100.0, "left_cm2": a_c / 100.0,
                    "eaten_area_pct": 100.0 * (1 - frac),
                    "eaten_pct": 100.0 * (1 - frac ** SHRINK_EXP)})
    return out
