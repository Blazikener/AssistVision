"""E3/E4 driver: multi-view reconstruction over the rendered synthetic suite.

  python experiments/synth/run_suite.py --exp main      # 24 views, every scene
  python experiments/synth/run_suite.py --exp views     # 6/8/12/16/24 views
  python experiments/synth/run_suite.py --exp sensor    # resolution x JPEG quality
  python experiments/synth/run_suite.py --exp scale     # marker-side error 0.98-1.02

One JSON line per run is appended to results/synth/<exp>.jsonl; runs already
present are skipped, so the driver can be interrupted and resumed.
"""

import argparse
import itertools
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")


def scenes(root, only=None):
    out = []
    for s in sorted(os.listdir(root)):
        if os.path.exists(os.path.join(root, s, "gt.json")) and (not only or any(o in s for o in only)):
            out.append(os.path.join(root, s))
    return out


def grid(exp, all_scenes):
    # Ablations use the single-food, ceramic and steel scenes so plate material
    # stays a crossed factor; each condition changes exactly one variable.
    abl = [s for s in all_scenes if "__flat" not in s and "banana" not in s]
    if exp == "main":
        return [dict(scene=s, views=24) for s in all_scenes]
    if exp == "views":
        return [dict(scene=s, views=v) for s, v in itertools.product(abl, (6, 8, 12, 16, 24))]
    if exp == "sensor":
        # 1600x1200 = OV2640 UXGA; 0.5 = SVGA 800x600; 0.4 = VGA 640x480
        conds = [(1.0, 0), (1.0, 30), (1.0, 10), (0.5, 0), (0.5, 10), (0.4, 10)]
        return [dict(scene=s, views=24, resize=r, jpeg=q) for s, (r, q) in itertools.product(abl, conds)]
    if exp == "scale":
        return [dict(scene=s, views=24, scale=f, dense="sparse")
                for s, f in itertools.product(abl, (0.98, 0.99, 1.0, 1.01, 1.02))]
    if exp == "repeat":  # run-to-run spread of the whole SfM+MVS pipeline
        return [dict(scene=s, views=24, rep=r) for s in all_scenes if "rice_mound" in s or "thali3" in s
                for r in range(1, 4)]
    if exp == "sparse":
        return [dict(scene=s, views=24, dense="sparse") for s in all_scenes]
    raise ValueError(exp)


def key(c):
    return (os.path.basename(c["scene"]), c.get("views", 24), c.get("resize", 1.0), c.get("jpeg", 0),
            c.get("scale", 1.0), c.get("dense", "openmvs"), c.get("rep", 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", required=True, choices=["main", "views", "sensor", "scale", "sparse", "repeat"])
    ap.add_argument("--scenes", default=os.path.join(ROOT, "data", "synth"))
    ap.add_argument("--only", default="", help="comma-separated scene-name substrings")
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "synth"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, f"{a.exp}.jsonl")
    done = set()
    if os.path.exists(path):
        for line in open(path):
            r = json.loads(line)
            done.add((r["scene"], r["views"], r["resize"], r["jpeg"], r["scale_factor"], r["dense"], r.get("rep", 0)))
    todo = [c for c in grid(a.exp, scenes(a.scenes, [o for o in a.only.split(",") if o])) if key(c) not in done]
    print(f"{a.exp}: {len(todo)} runs to do, {len(done)} done", flush=True)
    for i, c in enumerate(todo):
        work = os.path.join(a.out, "runs", f"{a.exp}_{i}")
        cmd = [sys.executable, os.path.join(HERE, "reconstruct.py"), "--scene", c["scene"], "--out", work,
               "--views", str(c.get("views", 24)), "--resize", str(c.get("resize", 1.0)),
               "--jpeg", str(c.get("jpeg", 0)), "--scale", str(c.get("scale", 1.0)),
               "--dense", c.get("dense", "openmvs"), "--rep", str(c.get("rep", 0))]
        r = subprocess.run(cmd, capture_output=True, text=True)
        try:
            res = json.loads(r.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            res = dict(zip(("scene", "views", "resize", "jpeg", "scale_factor", "dense", "rep"), key(c)))
            res["status"] = "error: no result " + r.stderr[-300:]
        with open(path, "a") as f:
            f.write(json.dumps(res) + "\n")
        print(f"[{i + 1}/{len(todo)}] {res['scene']} v={res['views']} r={res['resize']} q={res['jpeg']} "
              f"s={res['scale_factor']} {res['dense']}: {res.get('volume_err_pct', float('nan')):+.1f}% "
              f"{res['status'][:60]}", flush=True)


if __name__ == "__main__":
    main()
