"""
Generate a printable ArUco scale reference sheet.

Why this exists
---------------
Structure from Motion reconstructs geometry only up to an unknown similarity
transform -- meaning COLMAP will hand you a beautifully shaped point cloud in
arbitrary units. A plate could be 26 cm across or 26 units across; the images
cannot tell you which. This is the same scale ambiguity that defeats monocular
depth, and SfM does NOT solve it.

Putting a marker of precisely known physical size in the scene fixes it. Detect
the marker in the reconstructed images, compare its size in reconstruction units
against its true size in millimetres, and you have the scale factor that converts
the whole cloud to metric. Everything downstream -- volume, and therefore mass --
depends on this one number being right.

Because volume scales with the CUBE of linear scale, a 5% error here becomes a
16% error in grams. Measure the printed marker with calipers or a steel ruler.
Do not assume the printer honoured the size.

Usage
-----
  python src/make_aruco.py --marker-mm 50 --out data/aruco_sheet.png

Then print at 100% / "Actual size" -- NOT "fit to page", which silently rescales
and would corrupt every measurement you take for the rest of the project.
"""

import argparse
import os

import cv2
import numpy as np

A4_MM = (210.0, 297.0)          # width, height
DICT = cv2.aruco.DICT_4X4_50    # 4x4 is plenty for 4 markers and detects robustly


def mm(value, dpi):
    """Millimetres -> pixels at the given print resolution."""
    return int(round(value * dpi / 25.4))


def build_sheet(marker_mm, dpi, ids):
    page_w, page_h = mm(A4_MM[0], dpi), mm(A4_MM[1], dpi)
    sheet = np.full((page_h, page_w), 255, np.uint8)

    dictionary = cv2.aruco.getPredefinedDictionary(DICT)
    side = mm(marker_mm, dpi)

    # Two columns, two rows, centred on the page with a wide quiet zone.
    # ArUco needs white space around the black border to detect reliably;
    # crowding markers together is a common reason detection fails.
    gap = mm(30, dpi)
    block_w = 2 * side + gap
    block_h = 2 * side + gap
    x0 = (page_w - block_w) // 2
    y0 = mm(45, dpi)

    placed = []
    for i, marker_id in enumerate(ids[:4]):
        img = cv2.aruco.generateImageMarker(dictionary, marker_id, side)
        r, c = divmod(i, 2)
        x = x0 + c * (side + gap)
        y = y0 + r * (side + gap)
        sheet[y:y + side, x:x + side] = img
        placed.append((marker_id, x, y))
        cv2.putText(sheet, f"id {marker_id}", (x, y - mm(4, dpi)),
                    cv2.FONT_HERSHEY_SIMPLEX, dpi / 250, 0, max(1, dpi // 200))

    # Header: the facts you will need months from now when you have forgotten
    # which sheet this was. Printed metadata beats a filename every time.
    cv2.putText(sheet, f"ArUco DICT_4X4_50   marker = {marker_mm:.1f} mm",
                (x0, mm(25, dpi)), cv2.FONT_HERSHEY_SIMPLEX,
                dpi / 180, 0, max(2, dpi // 150))
    cv2.putText(sheet, "PRINT AT 100% / ACTUAL SIZE -- do not fit to page",
                (x0, mm(34, dpi)), cv2.FONT_HERSHEY_SIMPLEX,
                dpi / 260, 0, max(1, dpi // 220))

    # A 100 mm verification ruler. After printing, measure this with a steel rule.
    # If it is not exactly 100 mm, the printer rescaled -- work out the true
    # marker size from the ratio, or fix the print settings and reprint.
    ruler_y = y0 + block_h + mm(25, dpi)
    ruler_x = x0
    ruler_len = mm(100, dpi)
    cv2.line(sheet, (ruler_x, ruler_y), (ruler_x + ruler_len, ruler_y), 0, max(2, dpi // 150))
    for t in range(11):                       # ticks every 10 mm
        tx = ruler_x + mm(10 * t, dpi)
        h = mm(4 if t % 5 else 7, dpi)
        cv2.line(sheet, (tx, ruler_y), (tx, ruler_y - h), 0, max(1, dpi // 200))
    cv2.putText(sheet, "this line must measure exactly 100 mm",
                (ruler_x, ruler_y + mm(10, dpi)), cv2.FONT_HERSHEY_SIMPLEX,
                dpi / 260, 0, max(1, dpi // 220))

    return sheet, placed


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--marker-mm", type=float, default=50.0,
                    help="physical marker side length in mm")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--ids", type=int, nargs=4, default=[0, 1, 2, 3])
    ap.add_argument("--out", default="data/aruco_sheet.png")
    args = ap.parse_args()

    sheet, placed = build_sheet(args.marker_mm, args.dpi, args.ids)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    cv2.imwrite(args.out, sheet)
    print(f"Wrote {args.out}  ({sheet.shape[1]}x{sheet.shape[0]} px @ {args.dpi} dpi)")
    print(f"Markers: ids {[p[0] for p in placed]}, {args.marker_mm} mm each")
    print("\nAfter printing:")
    print("  1. Measure the 100 mm ruler line. It must be exactly 100 mm.")
    print("  2. Measure one marker's black square edge to edge.")
    print("  3. Record the measured value -- that number, not the nominal one,")
    print("     is what you feed the scaling step. Log it in NOTES.md.")
    print("  4. Glue or tape the sheet flat to stiff card. A curled marker")
    print("     introduces error you cannot recover later.")


if __name__ == "__main__":
    main()
