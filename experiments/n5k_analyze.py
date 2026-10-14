"""Aggregate the Nutrition5k monocular benchmark into tables, tests and figures.

    python experiments/n5k_analyze.py --res results/n5k --figs paper/figs

All intervals are 95% percentile-bootstrap CIs over dishes (10k resamples,
seed 0). Model comparisons are paired over the same dishes (Wilcoxon signed
rank on per-dish volume error, Holm-corrected against the best model).
"""
import argparse
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import stats  # noqa: E402
from mono_depth import MODELS  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({"font.size": 7, "axes.titlesize": 7, "axes.labelsize": 7, "legend.fontsize": 6,
                     "xtick.labelsize": 6, "ytick.labelsize": 6, "figure.dpi": 150, "savefig.bbox": "tight",
                     "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42})
COL1 = 3.5  # IEEE column width, inches
PROTOCOLS = ["raw", "anchor", "oracle"]


def read(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def num(r, k):
    try:
        v = float(r.get(k, "nan"))
    except ValueError:
        return np.nan
    return v


def load(res):
    gt = {r["dish"]: r for r in read(os.path.join(res, "gt.csv")) if r["status"] == "ok"}
    models = {}
    for name in MODELS:
        p = os.path.join(res, f"{name}.csv")
        if os.path.exists(p):
            models[name] = {r["dish"]: r for r in read(p) if r["status"] == "ok"}
    return gt, models


def ape(v, ref):
    return np.abs(v - ref) / ref * 100


def summarise(gt, models):
    rows = []
    for name, rs in models.items():
        kind = MODELS[name][1]
        dishes = sorted(set(rs) & set(gt))
        vgt = np.array([num(gt[d], "gt_volume_ml") for d in dishes])
        lat = np.array([num(rs[d], "infer_s") for d in dishes])
        for proto in PROTOCOLS:
            if proto == "raw" and kind != "metric":
                continue
            v = np.array([num(rs[d], f"{proto}_volume_ml") for d in dishes])
            ok = np.isfinite(v) & (vgt > 0)
            e = ape(v[ok], vgt[ok])
            absrel = np.array([num(rs[d], f"{proto}_absrel") for d in dishes])[ok]
            hmae = np.array([num(rs[d], f"{proto}_height_mae_mm") for d in dishes])[ok]
            d105 = np.array([num(rs[d], f"{proto}_delta_1.05") for d in dishes])[ok]
            vg = np.array([num(rs[d], f"{proto}_volume_gtplane_ml") for d in dishes])[ok]
            eg = ape(vg, vgt[ok])
            trms = np.array([num(rs[d], f"{proto}_table_rms_mm") for d in dishes])[ok]
            within = int((e <= 20).sum())
            med, lo, hi = stats.bootstrap_ci(e, np.median)
            ar, arlo, arhi = stats.bootstrap_ci(absrel, np.mean)
            hm, hmlo, hmhi = stats.bootstrap_ci(hmae, np.mean)
            w = stats.wilson_ci(within, len(e))
            rows.append({"model": name, "kind": kind, "params_m": MODELS[name][2], "protocol": proto,
                         "n": int(ok.sum()), "n_total": len(dishes),
                         "absrel": ar, "absrel_lo": arlo, "absrel_hi": arhi,
                         "delta_1.05": float(np.nanmean(d105)),
                         "height_mae_mm": hm, "height_mae_lo": hmlo, "height_mae_hi": hmhi,
                         "vol_ape_median": med, "vol_ape_lo": lo, "vol_ape_hi": hi,
                         "vol_signed_median": float(np.median((v[ok] - vgt[ok]) / vgt[ok] * 100)),
                         "within20": within / len(e), "within20_lo": w[1], "within20_hi": w[2],
                         "vol_gtplane_ape_median": float(np.nanmedian(eg)) if np.isfinite(eg).any() else np.nan,
                         "table_rms_mm": float(np.nanmedian(trms)) if np.isfinite(trms).any() else np.nan,
                         "latency_s": float(np.median(lat)),
                         "_err": e, "_dishes": [d for d, k in zip(dishes, ok) if k]})
    return rows


def paired_tests(rows, proto):
    rs = [r for r in rows if r["protocol"] == proto]
    if len(rs) < 2:
        return []
    best = min(rs, key=lambda r: r["vol_ape_median"])
    out, pv = [], []
    for r in rs:
        if r is best:
            continue
        common = sorted(set(r["_dishes"]) & set(best["_dishes"]))
        a = dict(zip(r["_dishes"], r["_err"]))
        b = dict(zip(best["_dishes"], best["_err"]))
        stat, p, _ = stats.paired_wilcoxon(np.array([a[d] for d in common]), np.array([b[d] for d in common]))
        out.append({"protocol": proto, "best": best["model"], "model": r["model"], "n_paired": len(common), "p": p})
        pv.append(p)
    for o, ph in zip(out, stats.holm(pv)):
        o["p_holm"] = ph
    return out


def mass_cv(vol_ml, mass_g, k=5, seed=0):
    """mass = rho * V (through origin), rho fitted on k-1 folds, scored on the held-out fold."""
    ok = np.isfinite(vol_ml) & np.isfinite(mass_g) & (vol_ml > 0) & (mass_g > 0)
    v, m = vol_ml[ok], mass_g[ok]
    idx = np.random.default_rng(seed).permutation(len(v))
    pred = np.empty_like(m)
    for f in np.array_split(idx, k):
        tr = np.setdiff1d(idx, f)
        rho = np.sum(v[tr] * m[tr]) / np.sum(v[tr] ** 2)
        pred[f] = rho * v[f]
    return pred, m


def fmt(x, lo=None, hi=None, p=1):
    if lo is None:
        return f"{x:.{p}f}"
    return f"{x:.{p}f} [{lo:.{p}f}, {hi:.{p}f}]"


def figures(gt, models, rows, figs):
    os.makedirs(figs, exist_ok=True)
    # 1. volume error per model and protocol (median + 95% CI)
    names = [n for n in MODELS if n in models]
    fig, ax = plt.subplots(figsize=(COL1 * 2, 2.1))
    width = 0.27
    colors = {"raw": "#C53030", "anchor": "#2B6CB0", "oracle": "#A0AEC0"}
    for j, proto in enumerate(PROTOCOLS):
        xs, ys, lo, hi = [], [], [], []
        for i, n in enumerate(names):
            r = next((r for r in rows if r["model"] == n and r["protocol"] == proto), None)
            if r is None:
                continue
            xs.append(i + (j - 1) * width); ys.append(r["vol_ape_median"])
            lo.append(r["vol_ape_median"] - r["vol_ape_lo"]); hi.append(r["vol_ape_hi"] - r["vol_ape_median"])
        ax.bar(xs, ys, width, color=colors[proto], label=proto, yerr=[lo, hi], error_kw=dict(lw=0.6, capsize=1.5))
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([n.replace("-Metric-Indoor", "-MI") for n in names], rotation=30, ha="right")
    ax.set_ylabel("median |volume error| (%)")
    ax.set_yscale("log")
    ax.axhline(20, color="k", lw=0.5, ls=":")
    ax.legend(frameon=False, ncol=3, loc="upper left")
    fig.savefig(os.path.join(figs, "n5k_volume_error.pdf")); plt.close(fig)

    # 2. latency vs accuracy (oracle and anchor), marker size ~ params
    fig, ax = plt.subplots(figsize=(COL1, 2.2))
    for proto, mk in [("oracle", "o"), ("anchor", "s")]:
        for r in rows:
            if r["protocol"] != proto:
                continue
            ax.scatter(r["latency_s"], r["vol_ape_median"], s=8 + r["params_m"] / 12, marker=mk,
                       c=colors[proto], alpha=0.85, lw=0)
            if proto == "oracle":
                ax.annotate(r["model"].replace("-Metric-Indoor", "-MI"), (r["latency_s"], r["vol_ape_median"]),
                            fontsize=4.5, xytext=(3, 2), textcoords="offset points")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("CPU latency per image (s, dev VM)"); ax.set_ylabel("median |volume error| (%)")
    ax.scatter([], [], c=colors["oracle"], marker="o", label="oracle (upper bound)")
    ax.scatter([], [], c=colors["anchor"], marker="s", label="anchor (deployable)")
    ax.legend(frameon=False, loc="best")
    fig.savefig(os.path.join(figs, "n5k_latency_pareto.pdf")); plt.close(fig)

    # 3. sensor volume vs weighed mass
    dishes = sorted(gt)
    v = np.array([num(gt[d], "gt_volume_ml") for d in dishes])
    m = np.array([num(gt[d], "mass_g") for d in dishes])
    ok = np.isfinite(v) & np.isfinite(m) & (m > 0)
    fig, ax = plt.subplots(figsize=(COL1, 2.2))
    ax.scatter(v[ok], m[ok], s=3, c="#2D3748", alpha=0.5, lw=0)
    from scipy.stats import pearsonr, spearmanr
    r_p = pearsonr(v[ok], m[ok])[0]; r_s = spearmanr(v[ok], m[ok])[0]
    ax.set_xlabel("volume from RealSense depth (mL)"); ax.set_ylabel("weighed mass (g)")
    ax.set_title(f"n={ok.sum()}  Pearson r={r_p:.2f}  Spearman ρ={r_s:.2f}")
    fig.savefig(os.path.join(figs, "n5k_volume_vs_mass.pdf")); plt.close(fig)

    # 4. Bland-Altman for the best anchor model and best oracle model
    fig, axs = plt.subplots(1, 2, figsize=(COL1 * 2, 2.0), sharey=True)
    for ax, proto in zip(axs, ["anchor", "oracle"]):
        rs = [r for r in rows if r["protocol"] == proto]
        if not rs:
            continue
        best = min(rs, key=lambda r: r["vol_ape_median"])
        d = best["_dishes"]
        pred = np.array([num(models[best["model"]][x], f"{proto}_volume_ml") for x in d])
        ref = np.array([num(gt[x], "gt_volume_ml") for x in d])
        bias, loa_lo, loa_hi = stats.bland_altman(pred, ref)
        ba = {"bias": bias, "loa_low": loa_lo, "loa_high": loa_hi}
        mean = (pred + ref) / 2
        ax.scatter(mean, pred - ref, s=3, alpha=0.5, lw=0, c="#2D3748")
        for y, ls in [(ba["bias"], "-"), (ba["loa_low"], "--"), (ba["loa_high"], "--")]:
            ax.axhline(y, color=colors[proto], lw=0.8, ls=ls)
        ax.set_title(f"{best['model']} ({proto}): bias {ba['bias']:.0f} mL, LoA [{ba['loa_low']:.0f}, {ba['loa_high']:.0f}]")
        ax.set_xlabel("mean of predicted and sensor volume (mL)")
    axs[0].set_ylabel("predicted − sensor (mL)")
    fig.savefig(os.path.join(figs, "n5k_bland_altman.pdf")); plt.close(fig)

    # 5. anchor conditioning for relative models
    conds = [num(r, "anchor_condition_number") for rs in models.values() for r in rs.values()
             if np.isfinite(num(r, "anchor_condition_number"))]
    cvs = [num(r, "anchor_table_invdepth_cv") for rs in models.values() for r in rs.values()
           if np.isfinite(num(r, "anchor_table_invdepth_cv"))]
    if conds:
        fig, axs = plt.subplots(1, 2, figsize=(COL1, 1.6))
        axs[0].hist(np.log10(conds), bins=30, color="#2B6CB0")
        axs[0].set_xlabel("log10 cond. number (anchor fit)")
        axs[1].hist(np.array(cvs) * 100, bins=30, color="#2B6CB0")
        axs[1].set_xlabel("table inverse-depth CV (%)")
        fig.tight_layout()
        fig.savefig(os.path.join(figs, "n5k_anchor_conditioning.pdf")); plt.close(fig)
    return {"pearson_volume_mass": r_p, "spearman_volume_mass": r_s, "n": int(ok.sum())}


def latex_table(rows, path):
    lines = [r"\begin{tabular}{llrrrrrrr}", r"\toprule",
             r"Model & Prot. & AbsRel & $h$ MAE (mm) & Vol. APE med. (\%) & $\le$20\% (\%) & APE, sensor plane (\%) & table RMS (mm) & s/img \\", r"\midrule"]
    for r in sorted(rows, key=lambda r: (PROTOCOLS.index(r["protocol"]), r["vol_ape_median"])):
        lines.append(f"{r['model']} & {r['protocol']} & {r['absrel']:.3f} & {r['height_mae_mm']:.1f} & "
                     f"{r['vol_ape_median']:.1f} [{r['vol_ape_lo']:.1f}, {r['vol_ape_hi']:.1f}] & "
                     f"{r['within20']*100:.0f} & {r['vol_gtplane_ape_median']:.1f} & {r['table_rms_mm']:.1f} & "
                     f"{r['latency_s']:.2f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    open(path, "w").write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default="results/n5k")
    ap.add_argument("--figs", default="paper/figs")
    a = ap.parse_args()
    gt, models = load(a.res)
    rows = summarise(gt, models)
    tests = [t for p in PROTOCOLS for t in paired_tests(rows, p)]
    corr = figures(gt, models, rows, a.figs)

    # volume -> mass (5-fold CV density), sensor ceiling and per-model
    dishes = sorted(gt)
    mass = np.array([num(gt[d], "mass_g") for d in dishes])
    mass_rows = []
    pred, m = mass_cv(np.array([num(gt[d], "gt_volume_ml") for d in dishes]), mass)
    e = np.abs(pred - m)
    mass_rows.append({"source": "RealSense depth (sensor ceiling)", "n": len(m),
                      "mae_g": stats.bootstrap_ci(e, np.mean), "mape": stats.bootstrap_ci(e / m * 100, np.median)})
    for r in rows:
        if r["protocol"] == "raw":
            continue
        dd = r["_dishes"]
        vv = np.array([num(models[r["model"]][d], f"{r['protocol']}_volume_ml") for d in dd])
        mm = np.array([num(gt[d], "mass_g") for d in dd])
        pred, m2 = mass_cv(vv, mm)
        e = np.abs(pred - m2)
        mass_rows.append({"source": f"{r['model']} ({r['protocol']})", "n": len(m2),
                          "mae_g": stats.bootstrap_ci(e, np.mean), "mape": stats.bootstrap_ci(e / m2 * 100, np.median)})
    mean_baseline = np.abs(mass - np.nanmean(mass))
    mass_rows.append({"source": "predict the mean mass (no image)", "n": len(mass),
                      "mae_g": stats.bootstrap_ci(mean_baseline, np.mean),
                      "mape": stats.bootstrap_ci(mean_baseline / mass * 100, np.median)})

    os.makedirs(a.res, exist_ok=True)
    keep = [k for k in rows[0] if not k.startswith("_")] if rows else []
    with open(os.path.join(a.res, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keep)
        w.writeheader()
        w.writerows([{k: r[k] for k in keep} for r in rows])
    os.makedirs(os.path.join(a.figs, "..", "tables"), exist_ok=True)
    latex_table(rows, os.path.join(a.figs, "..", "tables", "n5k_models.tex"))
    report = {"volume_mass_correlation": corr, "tests": tests,
              "mass": [{"source": r["source"], "n": r["n"], "mae_g": list(r["mae_g"]), "median_ape": list(r["mape"])} for r in mass_rows]}
    json.dump(report, open(os.path.join(a.res, "summary.json"), "w"), indent=1, default=float)

    md = ["| Model | Protocol | n | AbsRel | height MAE mm | vol APE median % [95% CI] | within 20% [Wilson] | s/img |", "|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (PROTOCOLS.index(r["protocol"]), r["vol_ape_median"])):
        md.append(f"| {r['model']} | {r['protocol']} | {r['n']}/{r['n_total']} | {fmt(r['absrel'], r['absrel_lo'], r['absrel_hi'], 3)} | "
                  f"{fmt(r['height_mae_mm'], r['height_mae_lo'], r['height_mae_hi'])} | {fmt(r['vol_ape_median'], r['vol_ape_lo'], r['vol_ape_hi'])} | "
                  f"{r['within20']*100:.0f}% [{r['within20_lo']*100:.0f}, {r['within20_hi']*100:.0f}] | {r['latency_s']:.2f} |")
    md += ["", "| Mass source | n | MAE g [95% CI] | median APE % [95% CI] |", "|---|---|---|---|"]
    for r in mass_rows:
        md.append(f"| {r['source']} | {r['n']} | {fmt(*r['mae_g'])} | {fmt(*r['mape'])} |")
    md += ["", "| Protocol | Best | Model | n | p (Wilcoxon) | p (Holm) |", "|---|---|---|---|---|---|"]
    for t in tests:
        md.append(f"| {t['protocol']} | {t['best']} | {t['model']} | {t['n_paired']} | {t['p']:.2g} | {t['p_holm']:.2g} |")
    open(os.path.join(a.res, "summary.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))
    print(json.dumps(corr))


if __name__ == "__main__":
    main()
