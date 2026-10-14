"""Write the synthetic scene specs (fixed seed) and a render manifest.

    python experiments/synth/make_suite.py --out data/synth
    bash data/synth/render_all.sh        # ~6-10 min/scene on 4 CPU threads

Factors: food configuration (8) x plate material (ceramic, steel), plus
textureless-food and banana-leaf variants. Food dimensions are drawn from
ranges typical of a South-Indian thali (cups of 40-350 mL).
"""
import argparse
import json
import os

import numpy as np

CONFIGS = [
    ("rice_mound", [dict(shape="cap", r=0.065, h=0.040, texture="rice")]),
    ("rice_dal", [dict(shape="cap", r=0.055, h=0.035, texture="rice", x=-0.03),
                  dict(shape="gauss", r=0.045, h=0.022, texture="dal", x=0.055, y=0.02)]),
    ("idli_pair", [dict(shape="disc", r=0.035, h=0.022, texture="idli", x=-0.04),
                   dict(shape="disc", r=0.035, h=0.022, texture="idli", x=0.04)]),
    ("curry_heap", [dict(shape="gauss", r=0.07, h=0.035, texture="curry")]),
    ("lumpy_rice", [dict(shape="lumpy", r=0.07, h=0.045, texture="rice")]),
    ("thali3", [dict(shape="cap", r=0.05, h=0.03, texture="rice", x=-0.04, y=-0.02),
                dict(shape="gauss", r=0.035, h=0.02, texture="dal", x=0.05, y=-0.03),
                dict(shape="lumpy", r=0.035, h=0.025, texture="curry", x=0.01, y=0.06)]),
    ("small_portion", [dict(shape="cap", r=0.035, h=0.018, texture="rice")]),
    ("tall_mound", [dict(shape="cap", r=0.05, h=0.055, texture="rice")]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/synth")
    ap.add_argument("--views", type=int, default=24)
    ap.add_argument("--samples", type=int, default=24)
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rng = np.random.default_rng(7)
    scenes = []
    for name, foods in CONFIGS:
        for plate in ("ceramic", "steel"):
            scenes.append((f"{name}__{plate}", plate, foods))
    for name, foods in CONFIGS[:4]:
        scenes.append((f"{name}__ceramic__flat", "ceramic", [{**f, "texture": "flat"} for f in foods]))
    for name, foods in CONFIGS[1:3]:
        scenes.append((f"{name}__banana_leaf", "banana_leaf", foods))
    lines = ["#!/usr/bin/env bash", "set -e", 'B=${BLENDER:-blender}', 'cd "$(dirname "$0")/../.."']
    for sid, plate, foods in scenes:
        spec = {"plate": plate, "views": a.views, "samples": a.samples, "width": 1600, "height": 1200,
                "hfov_deg": 60.0, "elev_deg": 45.0, "cam_dist": 0.40, "threads": a.threads,
                "depth_views": [0], "foods": foods, "seed": int(rng.integers(1 << 30))}
        p = os.path.join(a.out, sid, "spec.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(spec, open(p, "w"), indent=1)
        lines.append(f'[ -f {a.out}/{sid}/gt.json ] || "$B" -b -P experiments/synth/render_scene.py -- '
                     f'--spec {a.out}/{sid}/spec.json --out {a.out}/{sid} > {a.out}/{sid}/render.log 2>&1 && echo "rendered {sid}"')
    open(os.path.join(a.out, "render_all.sh"), "w").write("\n".join(lines) + "\n")
    print(f"{len(scenes)} scenes -> {a.out}/render_all.sh")


if __name__ == "__main__":
    main()
