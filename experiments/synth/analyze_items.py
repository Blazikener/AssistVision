"""E7: which item was left, from the centre frame of each glasses burst.

Runs src/plate_items.py on the served and cleared view_00 of the 12 E6 pairs and
compares each item's eaten share with the ground truth from the scene volumes.
    python experiments/synth/analyze_items.py
"""
import glob
import json
import os
import sys

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
from plate_items import items_eaten  # noqa: E402

DATA = os.path.join(ROOT, "data", "synth_glasses")


def truth(before, after):
    out = []
    for f in before["foods"]:
        same = [a for a in after["foods"] if a["texture"] == f["texture"]
                and abs(a.get("x", 0) - f.get("x", 0)) < 1e-6 and abs(a.get("y", 0) - f.get("y", 0)) < 1e-6]
        left = same[0]["volume_m3"] if same else 0.0
        out.append({"food": f["texture"], "x": f.get("x", 0), "y": f.get("y", 0),
                    "eaten_pct": 100 * (1 - left / f["volume_m3"])})
    return out


def boot_median(v, n=10000, seed=0):
    rng = np.random.default_rng(seed)
    m = np.median(rng.choice(v, (n, len(v))), axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


rows, plates = [], []
for b in sorted(glob.glob(os.path.join(DATA, "*", "gt.json"))):
    scene = os.path.basename(os.path.dirname(b))
    if scene.endswith("__after"):
        continue
    gt = truth(json.load(open(b)), json.load(open(os.path.join(DATA, scene + "__after", "gt.json"))))
    est = items_eaten(cv2.imread(os.path.join(DATA, scene, "view_00.png")),
                      cv2.imread(os.path.join(DATA, scene + "__after", "view_00.png")), len(gt))
    cost = np.array([[np.hypot(e["x"] - g["x"], e["y"] - g["y"]) for g in gt] for e in est])
    pair = []
    for i, j in zip(*linear_sum_assignment(cost)):
        r = {"scene": scene, "plate": scene.split("__")[1], "food": gt[j]["food"], "gt_pct": gt[j]["eaten_pct"],
             "est_pct": est[i]["eaten_pct"], "est_area_pct": est[i]["eaten_area_pct"],
             "served_cm2": est[i]["served_cm2"], "pos_err_mm": 1000 * cost[i, j]}
        r["err"] = r["est_pct"] - r["gt_pct"]
        pair.append(r)
    rows += pair
    if len(pair) > 1:
        plates.append({"scene": scene, "most_left_ok": min(pair, key=lambda r: r["est_pct"])["food"] ==
                       min(pair, key=lambda r: r["gt_pct"])["food"] and
                       min(pair, key=lambda r: r["est_pct"]) is min(pair, key=lambda r: r["gt_pct"])})


def summary(sel):
    e = np.abs([r["err"] for r in sel])
    lo, hi = boot_median(e)
    return {"n": len(e), "med": float(np.median(e)), "lo": lo, "hi": hi, "w10": int((e <= 10).sum()),
            "max": float(e.max())}


res = {"all": summary(rows),
       "area_only": summary([dict(r, err=r["est_area_pct"] - r["gt_pct"]) for r in rows]),
       "steel": summary([r for r in rows if r["plate"] == "steel"]),
       "ceramic": summary([r for r in rows if r["plate"] == "ceramic"]),
       "most_left_ok": sum(p["most_left_ok"] for p in plates), "multi_item_plates": len(plates),
       "finished_found": sum(r["est_pct"] >= 90 for r in rows if r["gt_pct"] >= 99.9),
       "finished": sum(r["gt_pct"] >= 99.9 for r in rows),
       "untouched_found": sum(r["est_pct"] <= 10 for r in rows if r["gt_pct"] <= 0.1),
       "untouched": sum(r["gt_pct"] <= 0.1 for r in rows),
       "rows": rows, "plates": plates}
os.makedirs(os.path.join(ROOT, "results", "synth"), exist_ok=True)
json.dump(res, open(os.path.join(ROOT, "results", "synth", "e7_items.json"), "w"), indent=1)
for k in ("all", "area_only", "steel", "ceramic"):
    print(k, {a: round(b, 1) if isinstance(b, float) else b for a, b in res[k].items()})
print("most-left item right on", res["most_left_ok"], "of", res["multi_item_plates"], "multi-item plates;",
      "finished found", res["finished_found"], "/", res["finished"], "; untouched found",
      res["untouched_found"], "/", res["untouched"])
