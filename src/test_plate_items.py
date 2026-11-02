"""Per-item leftover estimator on a drawn top-down mat (no Blender needed)."""
import cv2
import numpy as np

from plate_items import ARUCO, MAT_MARKERS, items_eaten

S, CX, CY = 2000.0, 600, 450  # px per m, plate centre in the image


def px(x, y):
    return int(round(CX + S * x)), int(round(CY - S * y))


def scene(items):
    img = np.full((900, 1200, 3), 120, np.uint8)
    for i, c in MAT_MARKERS.items():
        (x0, y0), (x1, y1) = px(*c[0]), px(*c[2])
        cv2.rectangle(img, (x0 - 20, y0 - 20), (x1 + 20, y1 + 20), (255, 255, 255), -1)
        img[y0:y1, x0:x1] = cv2.cvtColor(cv2.aruco.generateImageMarker(ARUCO, i, x1 - x0), cv2.COLOR_GRAY2BGR)
    cv2.circle(img, (CX, CY), int(S * 0.13), (70, 70, 70), -1)
    for x, y, r, bgr in items:
        cv2.circle(img, px(x, y), int(S * r), bgr, -1)
    return img


DAL, CURRY = (40, 200, 230), (30, 60, 170)


def test_left_item_is_found():
    served = scene([(-0.05, 0.0, 0.04, DAL), (0.05, 0.03, 0.035, CURRY)])
    cleared = scene([(-0.05, 0.0, 0.02, DAL), (0.05, 0.03, 0.035, CURRY)])
    out = sorted(items_eaten(served, cleared, 2), key=lambda d: d["x"])
    assert abs(out[0]["eaten_area_pct"] - 75.0) < 5, out[0]
    assert out[1]["eaten_area_pct"] < 3, out[1]
    assert out[0]["eaten_pct"] > out[0]["eaten_area_pct"]


def test_clean_plate_is_all_eaten():
    served = scene([(0.0, 0.0, 0.05, DAL)])
    out = items_eaten(served, scene([]), 1)
    assert out[0]["eaten_pct"] > 99


def test_needs_both_markers():
    img = scene([(0.0, 0.0, 0.05, DAL)])
    img[:, :400] = 120
    try:
        items_eaten(img, img, 1)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} passed")
