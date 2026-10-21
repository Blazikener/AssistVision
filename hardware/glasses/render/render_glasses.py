"""Studio renders of the AssistVision camera glasses (printed pods on a generic frame).

    blender -b -P hardware/glasses/render/render_glasses.py -- --mode hero --out hero.png
    modes: hero | side | exploded | spin (writes frames to --out directory)

The spectacle frame is a generic stand-in drawn here; the pods are the real
STLs from hardware/glasses/cad/out (assembly pose, mm).
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
CAD = os.path.join(HERE, "..", "cad", "out")
MM = 0.001
T_Y, T_Z, T_T, T_H = -14.35, 4.3, 3.5, 8.0          # temple centre / size from glasses_mount.py hook()
HALF_W = 68.0                                         # half frame width (temple-to-centre), mm
YC = T_Y - HALF_W                                     # frame centre line


def mat(name, rgb, rough=0.5, metal=0.0, trans=0.0, ior=1.45):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Transmission Weight"].default_value = trans
    b.inputs["IOR"].default_value = ior
    return m


def add(obj, m):
    obj.data.materials.append(m)
    return obj


def cube(name, size, loc, m, bevel=0.6):
    bpy.ops.mesh.primitive_cube_add(size=1, location=[v * MM for v in loc])
    o = bpy.context.object
    o.name, o.scale = name, [v * MM for v in size]
    bpy.ops.object.transform_apply(scale=True)
    mod = o.modifiers.new("b", "BEVEL"); mod.width = bevel * MM; mod.segments = 4
    bpy.ops.object.shade_smooth()
    return add(o, m)


def rim(name, yc, zc, w, h, m_frame, m_lens, x=9.0):
    bpy.ops.curve.primitive_bezier_circle_add(radius=1.0, location=(x * MM, yc * MM, zc * MM), rotation=(0, math.pi / 2, 0))
    c = bpy.context.object
    c.name, c.scale = name, (h / 2 * MM, w / 2 * MM, 1)
    c.data.bevel_depth, c.data.bevel_resolution = 1.6 * MM, 6
    c.data.dimensions = "3D"
    add(c, m_frame)
    bpy.ops.mesh.primitive_circle_add(vertices=96, radius=1.0, fill_type="NGON",
                                      location=(x * MM, yc * MM, zc * MM), rotation=(0, math.pi / 2, 0))
    lens = bpy.context.object
    lens.scale = (h / 2 * MM * 0.99, w / 2 * MM * 0.99, 1)
    lens.modifiers.new("s", "SOLIDIFY").thickness = 1.5 * MM
    add(lens, m_lens)


def frame(m_frame, m_lens):
    lw, lh, lz = 50.0, 38.0, -3.0
    for s in (-1, 1):
        rim(f"rim{s}", YC + s * 33.0, lz, lw, lh, m_frame, m_lens)
    bpy.ops.curve.primitive_bezier_curve_add(location=(9 * MM, YC * MM, 6 * MM))
    br = bpy.context.object
    p = br.data.splines[0].bezier_points
    p[0].co, p[1].co = Vector((0, -8.5 * MM, 0)), Vector((0, 8.5 * MM, 0))
    p[0].handle_left, p[0].handle_right = Vector((0, -10 * MM, -2 * MM)), Vector((0, -5 * MM, 4 * MM))
    p[1].handle_left, p[1].handle_right = Vector((0, 5 * MM, 4 * MM)), Vector((0, 10 * MM, -2 * MM))
    br.data.bevel_depth, br.data.bevel_resolution = 1.4 * MM, 6
    add(br, m_frame)
    for s in (0, 1):
        y = T_Y if s == 0 else 2 * YC - T_Y
        cube(f"hinge{s}", (8, 6, 9), (6, y + (-1.5 if s == 0 else 1.5), T_Z), m_frame, 1.2)
        cube(f"end{s}", (3.5, 14, 6), (9, y + (-6 if s == 0 else 6), T_Z - 1), m_frame, 1.2)
        cube(f"temple{s}", (112, T_T, T_H), (-54, y, T_Z), m_frame, 1.0)
        tip = cube(f"tip{s}", (30, T_T, 6), (-118, y, T_Z - 8), m_frame, 1.0)
        tip.rotation_euler = (0, math.radians(-28), 0)


def pods(explode=False):
    m_pod = mat("pod", (0.035, 0.037, 0.042), 0.42)
    m_lid = mat("lid", (0.95, 0.38, 0.06), 0.38)
    offs = {"camera_pod": (0, 0, 0), "camera_pod_lid": (-24, 0, 0), "battery_pod": (-10, 0, 22)}
    out = []
    for k, m in (("camera_pod", m_pod), ("camera_pod_lid", m_lid), ("battery_pod", m_pod)):
        bpy.ops.wm.stl_import(filepath=os.path.join(CAD, f"{k}__assembly_pose.stl"))
        o = bpy.context.selected_objects[0]
        o.scale = (MM,) * 3
        if explode:
            o.location = [v * MM for v in offs[k]]
            if k != "battery_pod":
                o.location.z += 20 * MM
        bpy.ops.object.shade_auto_smooth(angle=math.radians(35))
        out.append(add(o, m))
    lift = 20 * MM if explode else 0.0
    tilt = math.radians(20.0)                         # glasses_mount.py tilt_deg; window centre at local x = -wall
    for r, ln, x, m in ((4.2, 2.5, -2.9, mat("barrel", (0.01, 0.01, 0.01), 0.3)),
                        (2.6, 0.4, -1.65, mat("glass", (0.05, 0.08, 0.2), 0.02, metal=0.6))):
        bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=r * MM, depth=ln * MM,
                                            location=(x * math.cos(tilt) * MM, 0, -x * math.sin(tilt) * MM + lift),
                                            rotation=(0, math.pi / 2 + tilt, 0))
        bpy.ops.object.shade_smooth()
        add(bpy.context.object, m)
    return out


def lights_and_stage():
    sc = bpy.context.scene
    w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.02, 0.022, 0.026, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
    bpy.ops.mesh.primitive_plane_add(size=4, location=(0, 0, -0.035))
    add(bpy.context.object, mat("floor", (0.06, 0.065, 0.075), 0.35))
    for name, loc, e, size, col in (("key", (0.25, 0.22, 0.30), 5.0, 0.35, (1, 0.96, 0.9)),
                                    ("fill", (-0.10, 0.30, 0.10), 1.2, 0.5, (0.85, 0.9, 1)),
                                    ("rim", (-0.30, -0.25, 0.25), 4.0, 0.25, (1, 0.6, 0.3))):
        l = bpy.data.objects.new(name, bpy.data.lights.new(name, "AREA"))
        l.data.energy, l.data.size, l.data.color = e, size, col
        l.location = loc
        l.rotation_euler = (Vector((-0.04, -0.07, 0)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        sc.collection.objects.link(l)


def camera(loc, tgt, lens=60):
    sc = bpy.context.scene
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    cam.data.lens = lens
    cam.data.dof.use_dof, cam.data.dof.aperture_fstop = True, 11.0
    cam.data.dof.focus_distance = (Vector(loc) - Vector(tgt)).length
    cam.location = loc
    cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam
    return cam


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="hero")
    ap.add_argument("--out", required=True)
    ap.add_argument("--samples", type=int, default=96)
    ap.add_argument("--res", type=int, nargs=2, default=[1600, 1066])
    ap.add_argument("--frames", type=int, default=96)
    ap.add_argument("--threads", type=int, default=0)
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    frame(mat("frame", (0.012, 0.012, 0.014), 0.25), mat("lens", (0.75, 0.82, 0.85), 0.03, trans=1.0, ior=1.5))
    pods(explode=a.mode == "exploded")
    lights_and_stage()
    tgt = (-0.012, -0.040, 0.0)
    views = {"hero": ((0.20, 0.13, 0.085), tgt, 55), "side": ((0.0, 0.26, 0.03), (-0.03, -0.02, 0.0), 60),
             "exploded": ((0.16, 0.17, 0.11), (-0.015, -0.01, 0.012), 70), "spin": ((0.22, 0.0, 0.08), tgt, 50)}
    loc, t, lens = views[a.mode]
    cam = camera(loc, t, lens)
    sc.render.engine = "CYCLES"
    sc.cycles.samples, sc.cycles.use_denoising = a.samples, True
    sc.render.resolution_x, sc.render.resolution_y = a.res
    sc.view_settings.view_transform, sc.view_settings.look = "AgX", "AgX - Medium High Contrast"
    if a.threads:
        sc.render.threads_mode, sc.render.threads = "FIXED", a.threads
    if a.mode != "spin":
        sc.render.filepath = a.out
        bpy.ops.render.render(write_still=True)
        return
    os.makedirs(a.out, exist_ok=True)
    pivot = Vector((tgt[0], tgt[1], 0))
    r, h = (Vector(loc) - pivot).length, loc[2]
    r = math.sqrt(r * r - h * h)
    for f in range(a.frames):
        th = 2 * math.pi * f / a.frames
        cam.location = pivot + Vector((r * math.cos(th), r * math.sin(th), h))
        cam.rotation_euler = (Vector(tgt) - cam.location).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = os.path.join(a.out, f"f{f:03d}.png")
        bpy.ops.render.render(write_still=True)


main()
