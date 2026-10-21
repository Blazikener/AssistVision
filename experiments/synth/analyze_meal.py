"""E5: consumed volume from before/after reconstructions of partly eaten plates.

Pairs each results/synth/meal.jsonl run (scene X__after) with the 24-view
dense run of X in main.jsonl and writes results/synth/e5_meal.csv,
paper/sections/e5.tex and paper/tables/e5_abstract.tex.

    python experiments/synth/analyze_meal.py
"""
import csv
import glob
import json
import os
import sys

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
import stats

RES = os.path.join(ROOT, "results", "synth")
PAPER = os.path.join(ROOT, "paper")


def runs(exp):
    out = {}
    lines = []
    for path in sorted(glob.glob(os.path.join(RES, f"{exp}.jsonl")) + glob.glob(os.path.join(RES, f"{exp}_*.jsonl"))):
        with open(path) as f:
            lines += f.read().splitlines()
    for line in lines:
        r = json.loads(line)
        if r.get("status") == "ok" and r.get("views") == 24 and r.get("jpeg", 0) == 0 \
                and r.get("resize", 1.0) == 1.0 and r.get("scale_factor", 1.0) == 1.0 and r.get("rep", 0) == 0:
            out[r["scene"]] = r
    return out


def main():
    before, after = runs("main"), runs("meal")
    rows = []
    for scene, a in sorted(after.items()):
        b = before.get(scene[: -len("__after")])
        if b is None:
            continue
        gt_eaten = b["gt_volume_ml"] - a["gt_volume_ml"]
        est_eaten = b["volume_ml"] - a["volume_ml"]
        rows.append({"scene": scene, "plate": a["plate"], "gt_served_ml": b["gt_volume_ml"], "gt_left_ml": a["gt_volume_ml"],
                         "est_served_ml": b["volume_ml"], "est_left_ml": a["volume_ml"], "gt_eaten_ml": gt_eaten,
                         "est_eaten_ml": est_eaten, "eaten_err_pct": 100 * (est_eaten - gt_eaten) / gt_eaten,
                         "left_err_ml": a["volume_ml"] - a["gt_volume_ml"],
                         "left_err_pct": 100 * (a["volume_ml"] - a["gt_volume_ml"]) / a["gt_volume_ml"],
                         "gt_eaten_frac": 100 * gt_eaten / b["gt_volume_ml"],
                         "est_eaten_frac": 100 * est_eaten / b["volume_ml"]})
    with open(os.path.join(RES, "e5_meal.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    def summ(sel):
        e = np.abs([r["eaten_err_pct"] for r in sel])
        fp = np.abs([r["est_eaten_frac"] - r["gt_eaten_frac"] for r in sel])
        med, lo, hi = stats.bootstrap_ci(e, np.median) if len(e) > 2 else (np.median(e), np.nan, np.nan)
        return {"n": len(sel), "med": med, "lo": lo, "hi": hi, "within": int((e <= 10).sum()), "frac_pp": float(np.median(fp))}

    groups = [("All", rows)] + [(p.capitalize(), [r for r in rows if r["plate"] == p]) for p in ("ceramic", "steel")]
    S = {g: summ(sel) for g, sel in groups if sel}
    a = S["All"]
    ci = f"[{a['lo']:.1f}, {a['hi']:.1f}]"
    lines = [r"\begin{table}[t]\centering\small",
             r"\caption{E5: eaten volume from before/after 24-view dense MVS on partly eaten synthetic plates (exact mesh volumes). Share: error in the eaten fraction of the serving, percentage points.}",
             r"\label{tab:e5}", r"\setlength{\tabcolsep}{4pt}", r"\begin{tabular}{lrrrr}", r"\toprule",
             r"Plate & $n$ & Median $|$err$|$ \% [95\,\% CI] & $\le$10\,\% & Share (pp) \\", r"\midrule"]
    for g, s in S.items():
        cis = "" if np.isnan(s["lo"]) else f" [{s['lo']:.1f}, {s['hi']:.1f}]"
        lines.append(f"{g} & {s['n']} & {s['med']:.1f}{cis} & {s['within']}/{s['n']} & {s['frac_pp']:.1f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    worst = max(rows, key=lambda r: abs(r["eaten_err_pct"]))
    left_pct = float(np.median(np.abs([r["left_err_pct"] for r in rows])))
    left_ml = float(np.median(np.abs([r["left_err_ml"] for r in rows])))
    lines.append(
        "Each of the six plates from E3 was paired with a leftover version on ceramic and steel: one or more items "
        "removed, the rest reduced in height and radius (e.g.\\ the rice eaten and 60\\,\\% of the dal height left), "
        "rendered with the same seed, camera path and plate. Eaten volume is the difference of two independent "
        "reconstructions, so the errors of both scans add. "
        f"Across {a['n']} pairs the median absolute error of the eaten volume is {a['med']:.1f}\\,\\% {ci}, "
        f"{a['within']}/{a['n']} within 10\\,\\%, and the eaten share of the serving is off by a median of "
        f"{a['frac_pp']:.1f} percentage points (Table~\\ref{{tab:e5}}). The largest error is "
        f"{worst['scene'].split('__')[0].replace('_', ' ')} on {worst['plate']} ({worst['eaten_err_pct']:+.1f}\\,\\%). "
        f"The leftover scans alone are much worse in relative terms (median {left_pct:.0f}\\,\\% of the leftover "
        f"volume), because thin remains on a plate are hard to reconstruct; in absolute terms that is a median "
        f"{left_ml:.1f}\\,ml, small next to the served portion. "
        "These scans follow the 24-view turntable path of our first design; E6 repeats the same pairs from the "
        "glasses' viewpoint. Both are synthetic, not physical, measurements.")
    with open(os.path.join(PAPER, "sections", "e5.tex"), "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(PAPER, "tables", "e5_abstract.tex"), "w") as f:
        f.write(
        f"On partly eaten plates, the before/after volume difference matches the exact eaten volume to a median "
        f"{a['med']:.1f}\\,\\% {ci} ({a['within']}/{a['n']} within 10\\,\\%).\n")
    for g, s in S.items():
        print(g, s)
    for r in rows:
        print(f"{r['scene']:32s} gt_eaten {r['gt_eaten_ml']:6.1f} est {r['est_eaten_ml']:6.1f} err {r['eaten_err_pct']:+6.1f}%")


if __name__ == "__main__":
    main()
