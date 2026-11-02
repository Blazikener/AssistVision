"""Blender scene generator for food-on-plate scenes with exactly known volume.

Run headless:
    blender -b -P experiments/synth/render_scene.py -- --spec scene.json --out data/synth/s00

Emulates the hardware rig: camera and lights are fixed, the turntable (with
plate, food and ArUco markers on it) rotates by 360/N degrees per view. So
specular highlights move across the food between views exactly as they would
on the real rig -- the case that hurts photometric MVS on steel plates.

Writes view_XX.png, depth_XX.exr (Z pass, metres along the optical axis) for
view 0, and gt.json with K, per-view camera-from-turntable extrinsics, the
food mesh volume (signed tetrahedra -> exact for the mesh), plate geometry and
marker corners in turntable coordinates.
"""
import json
import math
import os
import sys

import bpy
import bmesh
from mathutils import Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))


def args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = {"spec": None, "out": None}
    for i in range(0, len(a), 2):
        out[a[i].lstrip("-")] = a[i + 1]
    return out


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    s = bpy.context.scene
    s.unit_settings.system = "METRIC"
    return s


def material(name, base=(0.8, 0.8, 0.8), rough=0.5, metal=0.0, noise=None, image=None, spec=0.5):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    bsdf.inputs["Specular IOR Level"].default_value = spec
    if image:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(image)
        tex.interpolation = "Closest"
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    elif noise:
        # Two-octave texture: voronoi grains (rice-like) modulated by noise.
        scale, c1, c2, kind = noise["scale"], noise["c1"], noise["c2"], noise.get("kind", "noise")
        coord = nt.nodes.new("ShaderNodeTexCoord")
        if kind == "voronoi":
            t = nt.nodes.new("ShaderNodeTexVoronoi")
            t.inputs["Scale"].default_value = scale
            fac = t.outputs["Distance"]
        else:
            t = nt.nodes.new("ShaderNodeTexNoise")
            t.inputs["Scale"].default_value = scale
            t.inputs["Detail"].default_value = 8.0
            fac = t.outputs["Fac"]
        nt.links.new(coord.outputs["Object"], t.inputs["Vector"])
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = (*c1, 1)
        ramp.color_ramp.elements[1].color = (*c2, 1)
        nt.links.new(fac, ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    else:
        bsdf.inputs["Base Color"].default_value = (*base, 1)
    return m


def height_fn(shape, r, h):
    """Height of the food surface at radius rho (and angle th) above the plate."""
    if shape == "cap":            # rice mound
        R = (r * r + h * h) / (2 * h)
        return lambda rho, th: max(0.0, math.sqrt(max(R * R - rho * rho, 0)) - (R - h))
    if shape == "gauss":          # heaped curry/sabzi
        s = r / 2.2
        return lambda rho, th: h * math.exp(-rho * rho / (2 * s * s)) if rho < r else 0.0
    if shape == "disc":           # idli / dosa / chapati stack: flat top, rounded edge
        e = min(0.006, r * 0.2)
        return lambda rho, th: h if rho < r - e else (h * math.sqrt(max(0, 1 - ((rho - r + e) / e) ** 2)) if rho < r else 0.0)
    if shape == "lumpy":          # irregular: cap with angular harmonics
        R = (r * r + h * h) / (2 * h)
        base = lambda rho: max(0.0, math.sqrt(max(R * R - rho * rho, 0)) - (R - h))
        return lambda rho, th: base(rho) * (1 + 0.18 * math.sin(3 * th) + 0.10 * math.cos(5 * th + 1.0)) if rho < r else 0.0
    raise ValueError(shape)


def food_mesh(name, shape, r, h, z0, cx=0.0, cy=0.0, n_r=64, n_t=128):
    """Closed polar-grid height-field mesh sitting on z = z0."""
    f = height_fn(shape, r, h)
    bm = bmesh.new()
    top, bot = [], []
    centre_t = bm.verts.new((cx, cy, z0 + f(0.0, 0.0)))
    centre_b = bm.verts.new((cx, cy, z0))
    for i in range(1, n_r + 1):
        rho = r * i / n_r
        ring_t, ring_b = [], []
        for j in range(n_t):
            th = 2 * math.pi * j / n_t
            x, y = cx + rho * math.cos(th), cy + rho * math.sin(th)
            zt = z0 + (f(rho, th) if i < n_r else 0.0)
            ring_t.append(bm.verts.new((x, y, zt)))
            ring_b.append(bm.verts.new((x, y, z0)) if i == n_r else None)
        top.append(ring_t)
        bot.append(ring_b)
    for j in range(n_t):
        k = (j + 1) % n_t
        bm.faces.new((centre_t, top[0][j], top[0][k]))
        for i in range(n_r - 1):
            bm.faces.new((top[i][j], top[i + 1][j], top[i + 1][k], top[i][k]))
        bm.faces.new((centre_b, top[-1][k], top[-1][j]))  # flat base (outer ring is at z0)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    vol = bm.calc_volume(signed=False)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    return ob, vol


def main():
    a = args()
    spec = json.load(open(a["spec"]))
    out = os.path.abspath(a["out"])
    os.makedirs(out, exist_ok=True)
    sc = reset()

    W, H = spec.get("width", 1600), spec.get("height", 1200)
    hfov = math.radians(spec.get("hfov_deg", 60.0))
    fx = (W / 2) / math.tan(hfov / 2)

    turntable = bpy.data.objects.new("turntable", None)
    bpy.context.collection.objects.link(turntable)

    # Turntable disc with a printed random-dot mat: gives SfM texture that rotates
    # with the object (a static background would fight the turntable motion).
    bpy.ops.mesh.primitive_cylinder_add(radius=0.22, depth=0.01, location=(0, 0, -0.005), vertices=128)
    disc = bpy.context.object
    disc.data.materials.append(material("mat", noise={"scale": 140, "c1": (0.03, 0.03, 0.035), "c2": (0.45, 0.45, 0.42), "kind": "voronoi"}, rough=0.8))
    disc.parent = turntable

    plate_kind = spec.get("plate", "ceramic")
    plate_r, plate_t = spec.get("plate_radius", 0.13), 0.008
    bpy.ops.mesh.primitive_cylinder_add(radius=plate_r, depth=plate_t, location=(0, 0, plate_t / 2), vertices=192)
    plate = bpy.context.object
    if plate_kind == "steel":
        plate.data.materials.append(material("steel", base=(0.9, 0.9, 0.92), rough=0.12, metal=1.0))
    elif plate_kind == "banana_leaf":
        plate.data.materials.append(material("leaf", noise={"scale": 25, "c1": (0.05, 0.25, 0.04), "c2": (0.15, 0.45, 0.08)}, rough=0.35))
    else:
        plate.data.materials.append(material("ceramic", base=(0.92, 0.91, 0.88), rough=0.25, spec=0.6))
    plate.parent = turntable

    # ArUco markers on the mat, outside the plate. Side = black-square side.
    side = spec.get("marker_side", 0.05)
    markers = []
    for mid, (mx, my) in enumerate([(0.17, 0.0), (-0.17, 0.0)]):
        bpy.ops.mesh.primitive_plane_add(size=side * 1.5, location=(mx, my, 0.0002))
        p = bpy.context.object
        p.data.materials.append(material(f"aruco{mid}", image=os.path.join(HERE, "assets", f"marker{mid}.png"), rough=0.9, spec=0.1))
        p.parent = turntable
        hs = side / 2
        markers.append({"id": mid, "corners": [[mx - hs, my + hs, 0], [mx + hs, my + hs, 0], [mx + hs, my - hs, 0], [mx - hs, my - hs, 0]]})

    foods, total = [], 0.0
    for k, fd in enumerate(spec["foods"]):
        ob, v = food_mesh(f"food{k}", fd["shape"], fd["r"], fd["h"], plate_t, fd.get("x", 0.0), fd.get("y", 0.0))
        tex = fd.get("texture", "rice")
        palettes = {
            "rice": {"scale": 900, "c1": (0.75, 0.72, 0.62), "c2": (0.97, 0.96, 0.92), "kind": "voronoi"},
            "dal": {"scale": 120, "c1": (0.75, 0.50, 0.08), "c2": (0.95, 0.75, 0.2)},
            "curry": {"scale": 90, "c1": (0.25, 0.08, 0.02), "c2": (0.6, 0.25, 0.05)},
            "idli": {"scale": 400, "c1": (0.88, 0.86, 0.80), "c2": (0.96, 0.95, 0.91), "kind": "voronoi"},
        }
        if tex == "flat":
            ob.data.materials.append(material("flat", base=(0.9, 0.88, 0.82), rough=0.6))
        else:
            ob.data.materials.append(material(tex, noise=palettes[tex], rough=fd.get("rough", 0.55), spec=fd.get("spec", 0.5)))
        ob.parent = turntable
        foods.append({**fd, "volume_m3": v})
        total += v

    # Fixed camera on the rig arm.
    elev, dist = math.radians(spec.get("elev_deg", 45.0)), spec.get("cam_dist", 0.40)
    cam_data = bpy.data.cameras.new("cam")
    cam_data.sensor_fit = "HORIZONTAL"
    cam_data.sensor_width = 36.0
    cam_data.lens = fx * 36.0 / W
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = (0, -dist * math.cos(elev), dist * math.sin(elev))
    target = Vector((0, 0, 0.02))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam

    # Fixed lights: one soft key (ring light on the arm) + one hard light for highlights.
    for name, loc, energy, size in [("key", (0.0, -0.25, 0.55), spec.get("key_w", 4.0), 0.3), ("rim", (0.35, 0.3, 0.45), spec.get("rim_w", 1.5), 0.05)]:
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy, ld.size = energy, size
        lo = bpy.data.objects.new(name, ld)
        lo.location = loc
        lo.rotation_euler = (Vector((0, 0, 0)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        bpy.context.collection.objects.link(lo)
    world = bpy.data.worlds.new("w")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.35, 0.35, 0.37, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.15
    sc.world = world

    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = spec.get("samples", 48)
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = W, H
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.view_settings.view_transform = "Standard"
    sc.render.threads_mode = "FIXED"
    sc.render.threads = int(spec.get("threads", 4))

    # Z pass for view 0 (monocular ground truth) via the compositor.
    sc.view_layers[0].use_pass_z = True
    sc.use_nodes = True
    nt = sc.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    rl = nt.nodes.new("CompositorNodeRLayers")
    comp = nt.nodes.new("CompositorNodeComposite")
    nt.links.new(rl.outputs["Image"], comp.inputs["Image"])
    fo = nt.nodes.new("CompositorNodeOutputFile")
    fo.base_path = out
    fo.format.file_format = "OPEN_EXR"
    fo.format.color_depth = "32"
    fo.file_slots[0].path = "depth_"
    nt.links.new(rl.outputs["Depth"], fo.inputs[0])

    # cam_poses: a moving head-mounted camera over a static scene (E6, glasses).
    poses = spec.get("cam_poses")
    n_views = len(poses) if poses else spec.get("views", 36)
    K = [[fx, 0, (W - 1) / 2], [0, fx, (H - 1) / 2], [0, 0, 1]]
    # Blender camera looks down -Z with +Y up; OpenCV looks down +Z with +Y down.
    flip = Matrix(((1, 0, 0, 0), (0, -1, 0, 0), (0, 0, -1, 0), (0, 0, 0, 1)))
    views = []
    depth_views = set(spec.get("depth_views", [0]))
    for i in range(n_views):
        if poses:
            p = poses[i]
            az, el, d = math.radians(p["az"]), math.radians(p["elev"]), p["dist"]
            tgt = Vector((p.get("tx", 0.0), p.get("ty", 0.0), 0.02))
            cam.location = tgt + Vector((d * math.cos(el) * math.sin(az), -d * math.cos(el) * math.cos(az), d * math.sin(el)))
            q = (tgt - cam.location).to_track_quat("-Z", "Y") @ Quaternion((0, 0, 1), math.radians(p.get("roll", 0.0)))
            cam.rotation_euler = q.to_euler()
        else:
            turntable.rotation_euler = (0, 0, 2 * math.pi * i / n_views)
        bpy.context.view_layer.update()
        sc.frame_set(i)
        fo.mute = i not in depth_views
        sc.render.filepath = os.path.join(out, f"view_{i:02d}.png")
        bpy.ops.render.render(write_still=True)
        T_world_cam = cam.matrix_world @ flip
        T_cam_tt = T_world_cam.inverted() @ turntable.matrix_world
        views.append({"file": f"view_{i:02d}.png", "angle_deg": poses[i]["az"] if poses else 360.0 * i / n_views,
                      "T_cam_from_turntable": [list(r) for r in T_cam_tt]})

    gt = {
        "spec": spec, "K": K, "width": W, "height": H,
        "food_volume_m3": total, "foods": foods,
        "plate": {"kind": plate_kind, "radius": plate_r, "top_z": plate_t},
        "markers": markers, "marker_side": side, "views": views,
        "depth_files": {str(i): f"depth_{i:04d}.exr" for i in sorted(depth_views)},
    }
    json.dump(gt, open(os.path.join(out, "gt.json"), "w"), indent=1)
    print(f"done {out}: {n_views} views, food {total * 1e6:.2f} mL")


main()
