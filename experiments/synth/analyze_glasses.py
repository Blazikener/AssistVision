"""E6: % eaten from a head-mounted 13-frame sweep (camera glasses).

Pairs each served/cleared scene in results/synth/glasses.jsonl, compares the
eaten share of the serving with ground truth, and sets it beside E5 (24-view
turntable) on the same plates. Writes results/synth/e6_glasses.csv and
paper/sections/e6.tex.
"""
import csv
import json
import os

import numpy as np

from analyze_meal import PAPER, RES, runs, stats


def glasses_runs():
    out = {}
    path = os.path.join(RES, "glasses.jsonl")
    for line in open(path):
        r = json.loads(line)
        if r.get("views") == 13 and r.get("rep", 0) == 0:
            out[r["scene"]] = r
    return out


def share(b, a, key):
    return 100 * (b[key] - a[key]) / b[key]


def main():
    allg, t_before, t_after = glasses_runs(), runs("main"), runs("meal")
    g = {k: r for k, r in allg.items() if r.get("status") == "ok"}
    rows = []
    for scene in sorted(s for s in g if s.endswith("__after")):
        b, a = g.get(scene[: -len("__after")]), g[scene]
        if b is None:
            continue
        gt = share(b, a, "gt_volume_ml")
        r = {"scene": scene, "plate": a["plate"], "gt_share": gt,
             "served_err_pct": b["volume_err_pct"], "left_err_ml": a["volume_ml"] - a["gt_volume_ml"],
             "share": share(b, a, "volume_ml"), "share_hyst": share(b, a, "volume_hyst_ml"),
             "registered": f"{b['registered']}+{a['registered']}"}
        tb, ta = t_before.get(scene[: -len("__after")]), t_after.get(scene)
        r["share_turntable"] = share(tb, ta, "volume_ml") if tb and ta else np.nan
        for k in ("share", "share_hyst", "share_turntable"):
            r[k + "_err_pp"] = r[k] - gt
        rows.append(r)
    with open(os.path.join(RES, "e6_glasses.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    failed = sorted(s for s, r in allg.items() if r.get("status") != "ok")

    def summ(sel, k):
        e = np.abs([r[k] for r in sel if np.isfinite(r[k])])
        med, lo, hi = stats.bootstrap_ci(e, np.median) if len(e) > 2 else (np.median(e), np.nan, np.nan)
        return {"n": len(e), "med": med, "lo": lo, "hi": hi, "w10": int((e <= 10).sum()), "max": float(e.max())}

    cols = [("Glasses, fixed rule", "share_err_pp"), ("Glasses, region growing", "share_hyst_err_pp"),
            ("Turntable (E5), fixed rule", "share_turntable_err_pp")]
    S = {c: summ(rows, k) for c, k in cols}
    lines = [r"\begin{table}[t]\centering\small",
             r"\caption{E6: eaten share of the serving from a 13-frame head-mounted sweep (served and cleared), "
             r"synthetic plates. Error in percentage points (pp).}",
             r"\label{tab:e6}", r"\setlength{\tabcolsep}{4pt}", r"\begin{tabular}{lrrrr}", r"\toprule",
             r"Capture, footprint rule & $n$ & Median $|$err$|$ pp [95\,\% CI] & $\le$10 pp & Max \\", r"\midrule"]
    for c, s in S.items():
        cis = "" if np.isnan(s["lo"]) else f" [{s['lo']:.1f}, {s['hi']:.1f}]"
        lines.append(f"{c} & {s['n']} & {s['med']:.1f}{cis} & {s['w10']}/{s['n']} & {s['max']:.1f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    a = S["Glasses, fixed rule"]
    worst = max(rows, key=lambda r: abs(r["share_err_pp"]))
    served = float(np.median([r["served_err_pct"] for r in rows]))
    def plate_med(plate, k="share_err_pp"):
        e = [abs(r[k]) for r in rows if r["plate"] == plate and np.isfinite(r[k])]
        return (float(np.median(e)), len(e)) if e else (float("nan"), 0)
    st, ce = plate_med("steel"), plate_med("ceramic")
    sv_st = float(np.median([r["served_err_pct"] for r in rows if r["plate"] == "steel"] or [np.nan]))
    sv_ce = float(np.median([r["served_err_pct"] for r in rows if r["plate"] == "ceramic"] or [np.nan]))
    h = S["Glasses, region growing"]
    lines.append(
        f"Across {a['n']} served/cleared pairs, the eaten share from the glasses sweep is off by a median of "
        f"{a['med']:.1f} percentage points with the fixed footprint rule used as the main rule in E5, and "
        f"{a['w10']}/{a['n']} pairs fall within 10 points (Table~\\ref{{tab:e6}}). The same plates on the "
        f"turntable path give {S['Turntable (E5), fixed rule']['med']:.1f} points. The plate matters: on steel "
        f"the median miss is {st[0]:.1f} points ({st[1]} pairs), on white ceramic {ce[0]:.1f} points ({ce[1]} pairs). "
        f"The served scan alone is off by a median of {sv_st:+.1f}\\,\\% in volume on steel and "
        f"{sv_ce:+.1f}\\,\\% on ceramic, because a 60-degree sweep from one seat never sees the far side of the "
        "food, and, as in E3, white ceramic gives fewer features to match. Where the served and cleared scans are "
        "biased by different amounts, the bias does not cancel in the ratio. "
        f"The largest miss is {worst['scene'].split('__')[0].replace('_', ' ')} on {worst['plate']} "
        f"({worst['share_err_pp']:+.1f} points). The region-growing footprint, the second rule from E5, gives "
        f"{h['med']:.1f} points ({h['w10']}/{h['n']} within 10); we report it but did not choose it in advance. "
        + (f"Reconstruction failed for {len(failed)} scans ({', '.join(s.replace('_', ' ') for s in failed)}); "
           "they are counted as missing, not dropped silently. " if failed else "")
        + "These are rendered scenes with exact volumes and a simulated head path, not measurements from the "
        "printed glasses.")
    with open(os.path.join(PAPER, "sections", "e6.tex"), "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(PAPER, "tables", "e6_abstract.tex"), "w") as f:
        f.write(f"On {a['n']} simulated served/cleared pairs seen from the glasses, the eaten share is off by a "
                f"median of {a['med']:.1f} percentage points ({a['w10']}/{a['n']} within 10 points).\n")
    print("\n".join(f"{c}: {s}" for c, s in S.items()))
    print("failed:", failed)


if __name__ == "__main__":
    main()
