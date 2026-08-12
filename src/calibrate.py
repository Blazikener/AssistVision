"""
Camera calibration: recover the intrinsic matrix K and the lens distortion
coefficients for a given camera.

Why this exists
---------------
Every geometric step later in this project needs K. Back-projecting a depth
map to 3D points needs fx, fy, cx, cy. COLMAP runs far more reliably when you
hand it known intrinsics instead of making it solve for them. And the pixel
footprint term in the volume integral, Z^2 / (fx*fy), is meaningless without it.

The idea
--------
A chessboard is a known 3D object: the corners lie on a plane in a perfectly
regular grid, and we decide the grid spacing by measuring the printed squares.
So for many views we know both where each corner *is* in the world and where it
*landed* on the sensor. Calibration solves for the camera parameters that best
explain that mapping, by minimising reprojection error.

Usage
-----
  python src/calibrate.py capture --out captures/laptop
  python src/calibrate.py solve   --images captures/laptop --squares 25.0 --preview

Board convention: --board is the number of INNER corners, not squares.
A board printed with 10x7 squares has 9x6 inner corners. This trips up
everyone exactly once; findChessboardCorners silently fails if you get it wrong.
"""

import argparse
import glob
import json
import os

import cv2
import numpy as np

# Sub-pixel corner refinement stops when it moves less than 0.001 px or after
# 30 iterations. Corners found on the integer pixel grid are not accurate
# enough for calibration; this typically buys a factor of several in precision.
SUBPIX_CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
SUBPIX_WINDOW = (11, 11)


def parse_board(text):
    cols, rows = (int(v) for v in text.lower().split("x"))
    return cols, rows


def capture(args):
    """Interactively grab chessboard views from a live camera."""
    os.makedirs(args.out, exist_ok=True)
    board = parse_board(args.board)

    cam = cv2.VideoCapture(args.device, cv2.CAP_DSHOW)
    if not cam.isOpened():
        raise SystemExit(f"Could not open camera index {args.device}")

    # Ask for a specific resolution. Calibration is only valid for the
    # resolution you calibrated at, so pin it down now and reuse it later.
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    actual = (int(cam.get(cv2.CAP_PROP_FRAME_WIDTH)),
              int(cam.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    print(f"Capturing at {actual[0]}x{actual[1]} -> {args.out}")
    print("SPACE saves a frame (only when the board is found), Q quits.")

    saved = 0
    while True:
        ok, frame = cam.read()
        if not ok:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCorners(
            gray, board,
            cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE + cv2.CALIB_CB_FAST_CHECK,
        )

        view = frame.copy()
        if found:
            cv2.drawChessboardCorners(view, board, corners, found)
        cv2.putText(view, f"saved: {saved}   found: {found}", (12, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (0, 220, 0) if found else (0, 0, 255), 2)
        cv2.imshow("calibration capture", view)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord(" ") and found:
            path = os.path.join(args.out, f"cal_{saved:03d}.png")
            cv2.imwrite(path, frame)   # save the ORIGINAL, never the annotated one
            saved += 1
            print(f"  saved {path}")

    cam.release()
    cv2.destroyAllWindows()
    print(f"\n{saved} images saved. Aim for 20-30 with varied pose before solving.")


def solve(args):
    """Run the actual calibration over a folder of chessboard images."""
    board = parse_board(args.board)
    cols, rows = board

    # Object points: the corner coordinates in the board's own frame, in mm.
    # Z is zero for every corner because the board is planar -- that planarity
    # is what makes the problem well-conditioned from a handful of views.
    objp = np.zeros((cols * rows, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    objp *= args.squares

    paths = sorted(
        p for ext in ("png", "jpg", "jpeg")
        for p in glob.glob(os.path.join(args.images, f"*.{ext}"))
    )
    if not paths:
        raise SystemExit(f"No images found in {args.images}")

    obj_points, img_points, used = [], [], []
    image_size = None

    for path in paths:
        img = cv2.imread(path)
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        if image_size is None:
            image_size = gray.shape[::-1]          # (width, height)
        elif gray.shape[::-1] != image_size:
            print(f"  SKIP {os.path.basename(path)}: resolution differs from the rest")
            continue

        found, corners = cv2.findChessboardCorners(
            gray, board,
            cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE,
        )
        if not found:
            print(f"  SKIP {os.path.basename(path)}: board not found")
            continue

        corners = cv2.cornerSubPix(gray, corners, SUBPIX_WINDOW, (-1, -1), SUBPIX_CRITERIA)
        obj_points.append(objp)
        img_points.append(corners)
        used.append(path)

    if len(obj_points) < 8:
        raise SystemExit(f"Only {len(obj_points)} usable views; need at least ~8, ideally 20+.")

    print(f"\nCalibrating from {len(obj_points)} views at {image_size[0]}x{image_size[1]}...")
    rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(
        obj_points, img_points, image_size, None, None
    )

    # Per-view reprojection error. Project the known 3D corners back through the
    # solved camera and measure, in pixels, how far they land from the corners we
    # actually detected. This is THE diagnostic: a single bad view (motion blur,
    # a misdetected board) will stand out here and is worth deleting and re-solving.
    #
    # It is also the exact quantity bundle adjustment minimises inside COLMAP,
    # so understanding it here pays off in week 2 and in interviews.
    per_view = []
    for i in range(len(obj_points)):
        proj, _ = cv2.projectPoints(obj_points[i], rvecs[i], tvecs[i], K, dist)
        err = cv2.norm(img_points[i], proj, cv2.NORM_L2) / len(proj)
        per_view.append((err, used[i]))

    print(f"\nOverall RMS reprojection error: {rms:.4f} px")
    print("  < 0.5 px  excellent")
    print("  < 1.0 px  fine for this project")
    print("  > 1.0 px  something is wrong -- check focus, blur, or the --squares value\n")

    print("Worst views:")
    for err, path in sorted(per_view, reverse=True)[:5]:
        print(f"  {err:7.4f} px   {os.path.basename(path)}")

    fx, fy = K[0, 0], K[1, 1]
    cx, cy = K[0, 2], K[1, 2]
    print(f"\nfx = {fx:9.3f}    fy = {fy:9.3f}")
    print(f"cx = {cx:9.3f}    cy = {cy:9.3f}")
    print(f"distortion = {dist.ravel()}")

    # Sanity checks worth internalising:
    #  - cx, cy should sit near the image centre. Far off means bad input.
    #  - fx and fy should be within a percent or two of each other for any
    #    normal camera, since pixels are square.
    print(f"\nimage centre is ({image_size[0] / 2:.1f}, {image_size[1] / 2:.1f}) "
          f"-- cx, cy should be close to this")
    print(f"fx/fy = {fx / fy:.4f}  -- should be very near 1.000")

    out = {
        "image_width": image_size[0],
        "image_height": image_size[1],
        "K": K.tolist(),
        "fx": fx, "fy": fy, "cx": cx, "cy": cy,
        "dist_coeffs": dist.ravel().tolist(),
        "rms_reprojection_error_px": rms,
        "num_views": len(obj_points),
        "board_inner_corners": [cols, rows],
        "square_size_mm": args.squares,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {args.out}")

    if args.preview:
        img = cv2.imread(used[0])
        newK, _ = cv2.getOptimalNewCameraMatrix(K, dist, image_size, 1, image_size)
        undist = cv2.undistort(img, K, dist, None, newK)
        cv2.imshow("original (left) vs undistorted (right)", np.hstack([img, undist]))
        print("Straight lines that bowed outward should now be straight. Any key to close.")
        cv2.waitKey(0)
        cv2.destroyAllWindows()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("capture", help="grab chessboard frames from a live camera")
    c.add_argument("--out", default="captures/laptop")
    c.add_argument("--device", type=int, default=0)
    c.add_argument("--board", default="9x6", help="INNER corners, e.g. 9x6")
    c.add_argument("--width", type=int, default=1280)
    c.add_argument("--height", type=int, default=720)
    c.set_defaults(func=capture)

    s = sub.add_parser("solve", help="calibrate from a folder of images")
    s.add_argument("--images", required=True)
    s.add_argument("--board", default="9x6", help="INNER corners, e.g. 9x6")
    s.add_argument("--squares", type=float, required=True,
                   help="printed square size in mm -- MEASURE IT, do not trust the PDF")
    s.add_argument("--out", default="intrinsics.json")
    s.add_argument("--preview", action="store_true")
    s.set_defaults(func=solve)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
