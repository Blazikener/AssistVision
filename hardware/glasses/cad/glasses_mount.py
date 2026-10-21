"""Parametric 3D-printable parts for the AssistVision camera glasses.

    ~/cadenv/bin/python hardware/glasses/cad/glasses_mount.py hardware/glasses/cad/out

Parts (all clip onto the RIGHT temple arm, on its outer side):
  camera_pod      holds a Seeed XIAO ESP32S3 Sense, camera looking forward and
                  TILT_DEG down (eyes look below the head line at a plate)
  camera_pod_lid  friction-fit back lid with a window over BOOT/RESET + charge LED
  battery_pod     holds a 502040 LiPo (5 x 20 x 40 mm, ~500 mAh) behind the camera
Frame: +X forward (camera view), +Y outward (away from the head), +Z up, mm.
The temple arm slides into the hook slot under each pod's inner jaw; measure
your temple and set TEMPLE_T / TEMPLE_H (foam tape fills any spare gap).
"""
import json
import os
import sys

import cadquery as cq

P = dict(
    wall=1.6, clr=0.5,                       # wall, clearance around the board
    board_y=21.0, board_z=17.8, stack_x=15.0,  # XIAO ESP32S3 Sense: 21 x 17.8 x 15 mm (Seeed wiki)
    lid_t=1.6, lid_lip=1.5, fit=0.15,
    lens_win=11.0, lens_dy=0.0, lens_dz=0.0,
    tilt_deg=20.0,
    temple_t=3.5, temple_h=8.0, bridge_t=2.0, jaw_t=1.2,
    bat_t=5.0, bat_w=20.0, bat_l=40.0, bat_wall=1.4, bat_gap=4.0,
)

cx = P["stack_x"] + 1.0 + P["lid_lip"]
cy = P["board_y"] + 2 * P["clr"]
cz = P["board_z"] + 2 * P["clr"]
ox, oy, oz = cx + P["wall"], cy + 2 * P["wall"], cz + 2 * P["wall"]
Y_IN = -oy / 2                       # inner face (touches the temple), shared by both pods
Z_TOP = 10.3                         # top of the hook bridge, both pods


def box(lx, ly, lz, x0, y0, z0):
    """Axis-aligned box from (x0, y0, z0) with size (lx, ly, lz)."""
    return cq.Workplane("XY").box(lx, ly, lz, centered=False).translate((x0, y0, z0))


def hook(x0, x1):
    """Inverted-U clip over the temple, inner side of the pod."""
    g, jt, bt, th = P["temple_t"], P["jaw_t"], P["bridge_t"], P["temple_h"]
    bridge = box(x1 - x0, g + jt + 0.3, bt, x0, Y_IN - g - jt, Z_TOP - bt)
    jaw = box(x1 - x0, jt, bt + th, x0, Y_IN - g - jt, Z_TOP - bt - th)
    return bridge.union(jaw).edges("|X").fillet(0.5)


def camera_pod_local():
    w = P["wall"]
    body = box(ox, oy, oz, -ox, -oy / 2, -oz / 2).edges("|X").fillet(2.5)
    body = body.faces(">X").edges().fillet(1.0)
    body = body.cut(box(cx + 1, cy, cz, -ox - 1, -cy / 2, -cz / 2))
    lw, dy, dz = P["lens_win"], P["lens_dy"], P["lens_dz"]
    win = (cq.Workplane("YZ").workplane(offset=-w - 0.1).center(dy, dz).rect(lw, lw)
           .workplane(offset=w + 0.4).rect(lw + 3.5, lw + 3.5).loft())
    body = body.cut(win)
    body = body.cut(box(10, 2 * w, 13, -ox - 1, cy / 2 - 0.5, -6.5))            # USB-C, outer side
    body = body.cut(box(4, 4.5, 2 * w, -ox - 1, -cy / 2 + 1.0, -oz / 2 - w / 2))  # battery wires, bottom
    body = body.cut(cq.Workplane("XY").circle(1.25).extrude(3 * w).translate((-ox + 5, 0, oz / 2 - 2 * w)))  # optional button wires
    for x in (-5.0, -7.5, -10.0):                                               # vents
        body = body.cut(box(1.2, 10, 2 * w, x - 0.6, -2.0, oz / 2 - 1.5 * w))
    return body


def lid_local():
    f, t, lip = P["fit"], P["lid_t"], P["lid_lip"]
    plate = box(t, oy, oz, -ox - t, -oy / 2, -oz / 2).edges("|X").fillet(2.5)
    ring = box(lip, cy - 2 * f, cz - 2 * f, -ox, -cy / 2 + f, -cz / 2 + f).cut(
        box(lip + 1, cy - 2 * f - 2.4, cz - 2 * f - 2.4, -ox - 0.5, -cy / 2 + f + 1.2, -cz / 2 + f + 1.2))
    ring = ring.cut(box(lip + 1, 4, cz, -ox - 0.5, cy / 2 - 3.5, -cz / 2))      # clear the USB plug
    lid = plate.union(ring)
    lid = lid.cut(box(3 * t, 9, 14, -ox - 2 * t, cy / 2 - 10, -7))              # BOOT/RESET + charge LED window
    lid = lid.cut(box(3 * t, 4.5, 3, -ox - 2 * t, -cy / 2 + 1.0, -oz / 2 - 0.5))  # wire exit
    return lid


def tilt(wp):
    return wp.rotate((0, 0, 0), (0, 1, 0), P["tilt_deg"])


def battery_pod(x_front):
    bw, t, w, l = P["bat_wall"], P["bat_t"] + 0.6, P["bat_w"] + 1.2, P["bat_l"] + 2.0
    lx, ly, lz = l + bw, t + 2 * bw, w + 2 * bw
    x0, z0 = x_front - lx, Z_TOP - lz
    body = box(lx, ly, lz, x0, Y_IN, z0).edges("|X").fillet(1.8)
    body = body.faces("<X").edges().fillet(1.0)
    body = body.cut(box(l + 1, t, w, x0 + bw, Y_IN + bw, z0 + bw))             # open towards the camera pod
    body = body.cut(box(12, 2 * bw, 2.0, x0 + bw + 2, Y_IN + ly - 1.5 * bw, z0 + lz - 2 * bw - 3))  # grip slot to push the cell out
    return body.union(hook(x0, x_front))


def main(out):
    os.makedirs(out, exist_ok=True)
    pod = tilt(camera_pod_local()).union(hook(-15.0, -1.0))
    lid = tilt(lid_local())
    bat = battery_pod(-22.0 - P["bat_gap"])
    parts = {"camera_pod": pod, "camera_pod_lid": lid, "battery_pod": bat}
    asm = cq.Assembly()
    for k, v in parts.items():
        asm.add(v, name=k)
        cq.exporters.export(v, os.path.join(out, f"{k}__assembly_pose.stl"), tolerance=0.02, angularTolerance=0.1)
    asm.save(os.path.join(out, "assistvision_glasses_parts.step"))
    # print poses: pods lie on their flat outer (+Y) face, lid on its back face
    printable = {
        "camera_pod": pod.rotate((0, 0, 0), (1, 0, 0), -90),
        "camera_pod_lid": lid_local().rotate((0, 0, 0), (0, 1, 0), -90),
        "battery_pod": bat.rotate((0, 0, 0), (1, 0, 0), -90),
    }
    info = {"params": P}
    for k, v in printable.items():
        bb = v.val().BoundingBox()
        v = v.translate((-bb.xmin, -bb.ymin, -bb.zmin))
        cq.exporters.export(v, os.path.join(out, f"{k}.stl"), tolerance=0.02, angularTolerance=0.1)
        bb = v.val().BoundingBox()
        vol = v.val().Volume()
        info[k] = {"size_mm": [round(bb.xlen, 1), round(bb.ylen, 1), round(bb.zlen, 1)],
                   "volume_mm3": round(vol), "solid_pla_g": round(vol * 1.24e-3, 1),
                   "valid": v.val().isValid()}
    json.dump(info, open(os.path.join(out, "parts.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in info.items() if k != "params"}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out")
