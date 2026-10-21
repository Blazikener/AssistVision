"""E6 scenes: the E5 before/after plates seen by a head-mounted (glasses) camera.

    python experiments/synth/make_glasses_suite.py --src data/synth --out data/synth_glasses
    bash data/synth_glasses/render_all.sh

Same food, plates, mat and lights as E5; only the camera changes. One button
press = a burst taken while the wearer turns the head slowly across the plate:
13 frames, azimuth -30..+30 deg in 5 deg steps around the diner's seat, about
55 deg above the table at about 0.5 m, with per-frame jitter in elevation,
distance, aim point and roll (a head is not a tripod). Frame 0 is the central
(az = 0) view, which the single-image methods use. Before and after scenes get
independent jitter, as two separate presses would.
"""
import argparse
import json
import os

import numpy as np

AZ = [0] + [a for a in range(-30, 31, 5) if a != 0]


def poses(rng):
    return [{"az": float(a + rng.normal(0, 1.0)), "elev": float(55 + rng.normal(0, 2.0)),
             "dist": float(0.50 + rng.normal(0, 0.015)), "tx": float(rng.normal(0, 0.008)),
             "ty": float(rng.normal(0, 0.008)), "roll": float(rng.normal(0, 2.0))} for a in AZ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/synth")
    ap.add_argument("--out", default="data/synth_glasses")
    ap.add_argument("--threads", type=int, default=6)
    a = ap.parse_args()
    rng = np.random.default_rng(2026)
    after = sorted(s for s in os.listdir(a.src) if s.endswith("__after"))
    lines = ["#!/usr/bin/env bash", "set -e", 'B=${BLENDER:-blender}', 'cd "$(dirname "$0")/../.."']
    for s_after in after:
        for sid in (s_after[: -len("__after")], s_after):
            spec = json.load(open(os.path.join(a.src, sid, "spec.json")))
            spec.update({"cam_poses": poses(rng), "depth_views": [0], "threads": a.threads, "rig": "glasses"})
            spec.pop("views", None)
            d = os.path.join(a.out, sid)
            os.makedirs(d, exist_ok=True)
            json.dump(spec, open(os.path.join(d, "spec.json"), "w"), indent=1)
            lines.append(f'[ -f {d}/gt.json ] || "$B" -b -P experiments/synth/render_scene.py -- '
                         f'--spec {d}/spec.json --out {d} > {d}/render.log 2>&1 && echo "rendered {sid}"')
    open(os.path.join(a.out, "render_all.sh"), "w").write("\n".join(lines) + "\n")
    print(f"{2 * len(after)} scenes -> {a.out}/render_all.sh")


if __name__ == "__main__":
    main()
