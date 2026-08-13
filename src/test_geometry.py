"""
Geometry sanity checks.

Run this after any OpenCV upgrade, or whenever a number downstream looks wrong
and you need to know whether the foundation or your new code is at fault.

  python src/test_geometry.py

Both checks use synthetic data with a known answer, so a failure means the
library or the code changed -- never that the data was bad. That property is
what makes them worth having: they isolate "is my toolchain sane" from "is my
capture sane", and you will want that separation at 2am in week 6.

No pytest dependency on purpose; this must run anywhere, including Colab.
"""

import sys

import cv2
import numpy as np

from make_aruco import build_sheet


def check_calibration_recovers_known_intrinsics():
    """Project a chessboard through a known camera, then calibrate and see if
    we get that camera back. If this fails, cv2.calibrateCamera changed."""
    np.random.seed(0)

    K_true = np.array([[900.0, 0.0, 640.0],
                       [0.0, 900.0, 360.0],
                       [0.0, 0.0, 1.0]])
    dist_true = np.array([-0.25, 0.08, 0.0, 0.0, 0.0])
    image_size = (1280, 720)

    cols, rows, square = 9, 6, 25.0
    objp = np.zeros((cols * rows, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    objp *= square

    obj_points, img_points = [], []
    for _ in range(20):
        rvec = np.random.uniform(-0.4, 0.4, 3)
        tvec = np.array([np.random.uniform(-60, 60),
                         np.random.uniform(-40, 40),
                         np.random.uniform(400, 700)])
        proj, _ = cv2.projectPoints(objp, rvec, tvec, K_true, dist_true)
        obj_points.append(objp)
        img_points.append(proj.astype(np.float32))

    rms, K, dist, _, _ = cv2.calibrateCamera(
        obj_points, img_points, image_size, None, None
    )

    err = max(abs(K[0, 0] - 900), abs(K[1, 1] - 900),
              abs(K[0, 2] - 640), abs(K[1, 2] - 360))
    print(f"  rms reprojection      {rms:.2e} px")
    print(f"  max intrinsic error   {err:.4f} px")
    print(f"  k1 recovered          {dist.ravel()[0]:.4f}  (true -0.2500)")

    # Noise-free input, so recovery should be near-exact. A loose bound here
    # would let a real regression slip through.
    assert err < 1.0, f"intrinsics not recovered: {err:.4f} px error"
    assert rms < 1e-2, f"rms unexpectedly high on synthetic data: {rms}"


def check_aruco_roundtrip():
    """Generate the marker sheet, detect the markers back out, and confirm the
    measured size matches what the generator claims it rendered.

    This is the check that protects the metric scale of the whole project: if
    the generator says 50 mm and the detector measures something else, every
    volume downstream is wrong by the cube of that ratio.
    """
    dpi = 300
    requested_mm = 50.0
    ids = [0, 1, 2, 3]

    sheet, placed, rendered_mm = build_sheet(requested_mm, dpi, ids)

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
    corners, found_ids, _ = detector.detectMarkers(sheet)

    assert found_ids is not None, "no markers detected at all"
    found = sorted(found_ids.ravel().tolist())
    print(f"  requested             {requested_mm:.3f} mm")
    print(f"  generator reports     {rendered_mm:.3f} mm")
    print(f"  detected ids          {found}")
    assert found == sorted(ids), f"expected ids {sorted(ids)}, detected {found}"

    # Measure every marker's edges and convert pixels back to millimetres.
    measured = []
    for quad in corners:
        c = quad.reshape(4, 2)
        edges = [np.linalg.norm(c[i] - c[(i + 1) % 4]) for i in range(4)]
        measured.append(np.mean(edges) * 25.4 / dpi)
    mean_mm = float(np.mean(measured))
    spread = float(np.max(measured) - np.min(measured))

    # The detector should read exactly one pixel SHORTER than the rendered
    # size, and this is a convention difference rather than an error:
    #
    #   - the generator draws a marker spanning N pixels, columns 0..N-1
    #   - the detector returns corner coordinates at pixel CENTRES, so the
    #     distance between opposite corners is (N-1) pixels, not N
    #
    # An off-by-one of this kind is precisely the sort of thing that silently
    # biases a metric pipeline, so assert the exact expected value rather than
    # waving it through with a loose tolerance.
    one_pixel_mm = 25.4 / dpi
    expected_mm = rendered_mm - one_pixel_mm

    print(f"  detector measures     {mean_mm:.3f} mm  (spread {spread:.3f} mm)")
    print(f"  expected (centres)    {expected_mm:.3f} mm  "
          f"= rendered - 1 px ({one_pixel_mm:.4f} mm)")
    print(f"  residual              {abs(mean_mm - expected_mm):.5f} mm")

    assert abs(mean_mm - expected_mm) < 0.01, (
        f"expected {expected_mm:.4f} mm from pixel-centre convention, "
        f"detector measured {mean_mm:.4f} mm"
    )
    assert spread < 0.01, f"markers disagree with each other by {spread:.4f} mm"

    # None of this decides your real scale factor. The printed marker is what
    # goes in the scene, so MEASURE IT with a steel rule and use that number.
    # These checks only prove the generate/detect pair is self-consistent.


CHECKS = [
    ("calibration recovers known intrinsics", check_calibration_recovers_known_intrinsics),
    ("aruco generate/detect roundtrip", check_aruco_roundtrip),
]


def main():
    print(f"OpenCV {cv2.__version__}, NumPy {np.__version__}\n")
    failed = 0
    for name, fn in CHECKS:
        print(f"{name}")
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

    total = len(CHECKS)
    print(f"{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
