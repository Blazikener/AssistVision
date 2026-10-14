"""Tables and figures for E3/E4 from results/synth/*.jsonl and mono.csv.

  python experiments/synth/analyze.py
"""

import glob
import json
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
import stats  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
RES = os.path.join(ROOT, "results", "synth")
FIG = os.path.join(ROOT, "paper", "figs")
TAB = os.path.join(ROOT, "paper", "tables")
plt.rcParams.update({"font.size": 8, "font.family": "serif", "axes.spines.top": False, "axes.spines.right": False})


def load(exp):
    # {exp}.jsonl from this machine plus {exp}_<shard>.jsonl from parallel sessions
    paths = sorted(glob.glob(os.path.join(RES, f"{exp}.jsonl")) + glob.glob(os.path.join(RES, f"{exp}_*.jsonl")))
    if not paths:
        return pd.DataFrame()
    df = pd.DataFrame([json.loads(x) for p in paths for x in open(p)])
    df["ok"] = df["status"].eq("ok")
    df["ape"] = df["volume_err_pct"].abs()
    df["food"] = df["scene"].str.split("__").str[0]
    return df


def ci_str(x):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return f"{x.mean():.1f}" if len(x) else "--"
    _, lo, hi = stats.bootstrap_ci(x, np.median)
    return f"{np.median(x):.1f} [{lo:.1f}, {hi:.1f}]"


def main():
    os.makedirs(FIG, exist_ok=True)
    os.makedirs(TAB, exist_ok=True)
    out = {}
    main_df = load("main")
    mono = pd.read_csv(os.path.join(RES, "mono.csv")) if os.path.exists(os.path.join(RES, "mono.csv")) else pd.DataFrame()

    # E3 main table: multi-view (dense, sparse) vs mono by protocol, per plate material.
    rows = []
    sparse = load("sparse")
    hyst = main_df.copy()
    if not hyst.empty and "volume_hyst_err_pct" in hyst:
        hyst["volume_err_pct"] = hyst["volume_hyst_err_pct"]
        hyst["ape"] = hyst["volume_err_pct"].abs()
    else:
        hyst = pd.DataFrame()
    for name, df in [("MVS dense (24 views)", main_df), ("MVS dense, hysteresis (post-hoc)", hyst),
                     ("SfM sparse (24 views)", sparse)]:
        if df.empty:
            continue
        for plate in ["all"] + sorted(df["plate"].unique()):
            d = df if plate == "all" else df[df["plate"] == plate]
            ok = d[d["ok"]]
            rows.append(dict(method=name, plate=plate, n=f"{len(ok)}/{len(d)}", ape=ci_str(ok["ape"]),
                             bias=f"{ok['volume_err_pct'].mean():+.1f}" if len(ok) else "--",
                             w10=len(ok[ok["ape"] < 10]), secs=f"{ok['total_s'].median():.0f}" if len(ok) else "--"))
    if not mono.empty:
        mono["ape"] = mono["volume_err_pct"].abs()
        for (m, proto), d in mono.groupby(["model", "protocol"]):
            for plate in ["all"]:
                rows.append(dict(method=f"{m} ({proto})", plate=plate, n=f"{d['volume_err_pct'].notna().sum()}/{len(d)}",
                                 ape=ci_str(d["ape"]), bias=f"{d['volume_err_pct'].mean():+.1f}",
                                 w10=int((d["ape"] < 10).sum()), secs=f"{d['infer_s'].median():.1f}"))
        gtd = mono.drop_duplicates("scene")
        e = (gtd["gtdepth_volume_ml"] / gtd["gt_volume_ml"] - 1) * 100
        rows.append(dict(method="Perfect single-view depth", plate="all", n=f"{len(gtd)}/{len(gtd)}",
                         ape=ci_str(e.abs()), bias=f"{e.mean():+.1f}", w10=int((e.abs() < 10).sum()), secs="--"))
    t = pd.DataFrame(rows)
    t.to_csv(os.path.join(RES, "e3_summary.csv"), index=False)
    if len(t):
        with open(os.path.join(TAB, "synth_main.tex"), "w") as f:
            f.write("\\begin{tabular}{llrlrrr}\\toprule\nMethod & Plate & $n$ ok & $|e|$ \\% median [95\\% CI] & bias \\% & $<$10\\% & s \\\\\n\\midrule\n")
            for r in t.itertuples():
                f.write(f"{r.method} & {r.plate.replace('_', ' ')} & {r.n} & {r.ape} & {r.bias} & {r.w10} & {r.secs} \\\\\n")
            f.write("\\bottomrule\n\\end{tabular}\n")
        out["e3"] = t.to_dict("records")

    # Paired: dense MVS vs best mono (anchor) per scene, Wilcoxon on |err|.
    if not main_df.empty and not mono.empty:
        a = main_df[main_df["ok"]].set_index("scene")["ape"]
        best = None
        for m, d in mono[mono["protocol"] == "anchor"].groupby("model"):
            b = d.set_index("scene")["ape"]
            j = a.index.intersection(b.index)
            if len(j) >= 5:
                st, p, n = stats.paired_wilcoxon(a[j].values, b[j].values)
                med = float(np.median(b[j]))
                if best is None or med < best["mono_median"]:
                    best = dict(model=m, n=n, p=p, mvs_median=float(np.median(a[j])), mono_median=med)
        out["paired_mvs_vs_best_mono"] = best

    # E4 ablations
    fig, axs = plt.subplots(1, 3, figsize=(7.0, 2.1))
    v = load("views")
    if not v.empty:
        for plate, d in v.groupby("plate"):
            g = d.groupby("views")
            med = g["ape"].median()
            fail = 100 * (1 - g["ok"].mean())
            axs[0].plot(med.index, med.values, "o-", label=plate.replace("_", " "))
            for x, fr in fail.items():
                if fr > 0:
                    axs[0].annotate(f"{fr:.0f}% fail", (x, med[x]), fontsize=6, xytext=(2, 4), textcoords="offset points")
        axs[0].set_xlabel("views per scan")
        axs[0].set_ylabel("median |volume error| %")
        axs[0].legend(frameon=False)
        out["views"] = v.groupby(["plate", "views"]).agg(n=("ok", "size"), ok=("ok", "sum"), median_ape=("ape", "median")).reset_index().to_dict("records")
    s = load("sensor")
    if not s.empty:
        s["cond"] = s.apply(lambda r: f"{int(1600 * r['resize'])}\n" + ("PNG" if r["jpeg"] == 0 else f"q{int(r['jpeg'])}"), axis=1)
        g = s.groupby("cond", sort=False)["ape"].median()
        axs[1].bar(range(len(g)), g.values, color="0.4")
        axs[1].set_xticks(range(len(g)), g.index, fontsize=6)
        axs[1].set_ylabel("median |volume error| %")
        axs[1].set_xlabel("image width px / encoding")
        out["sensor"] = s.groupby(["resize", "jpeg"]).agg(n=("ok", "size"), ok=("ok", "sum"), median_ape=("ape", "median")).reset_index().to_dict("records")
    sc = load("scale")
    if not sc.empty:
        ok = sc[sc["ok"]]
        g = ok.groupby("scale_factor")["volume_err_pct"]
        base = g.median().get(1.0, 0.0)
        x = np.array(sorted(ok["scale_factor"].unique()))
        axs[2].plot((x - 1) * 100, g.median().values - base, "o", label="measured (median)")
        xx = np.linspace(x.min(), x.max(), 50)
        axs[2].plot((xx - 1) * 100, ((1 / xx) ** 3 - 1) * 100, "-", lw=0.8, label=r"$(1/(1+\epsilon))^3-1$")
        axs[2].set_title("sparse SfM: run-to-run noise dominates", fontsize=6)
        axs[2].set_xlabel("marker-size error %")
        axs[2].set_ylabel("volume change %")
        axs[2].legend(frameon=False, fontsize=6)
        out["scale"] = ok.groupby("scale_factor")["volume_err_pct"].median().to_dict()
    rep = load("repeat")
    if not rep.empty:
        out["repeat"] = rep.groupby("scene")["volume_err_pct"].agg(["count", "mean", "std", "min", "max"]).reset_index().to_dict("records")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "synth_ablations.pdf"))
    json.dump(out, open(os.path.join(RES, "summary.json"), "w"), indent=1, default=float)
    print(json.dumps(out, indent=1, default=float)[:4000])


if __name__ == "__main__":
    main()
