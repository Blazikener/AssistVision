"""Statistics used in every results table: bootstrap CIs and paired tests.

Small-n hardware papers routinely report a bare percentage (\"24/25 = 96%\").
With n = 25 the 95% interval on that number is roughly 80-99%, which is the
honest claim. Everything here returns intervals, not point estimates."""

import numpy as np
from scipy import stats as _st


def bootstrap_ci(x, fn=np.mean, n_boot=10000, alpha=0.05, seed=0):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), (n_boot, len(x)))
    boots = np.array([fn(x[i]) for i in idx]) if fn not in (np.mean, np.median) else fn(x[idx], axis=1)
    return float(fn(x)), float(np.quantile(boots, alpha / 2)), float(np.quantile(boots, 1 - alpha / 2))


def wilson_ci(successes, n, alpha=0.05):
    """Wilson score interval for a binomial proportion (detection-rate tables)."""
    z = _st.norm.ppf(1 - alpha / 2)
    p = successes / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, c - half, c + half


def paired_wilcoxon(a, b):
    """Two-sided Wilcoxon signed-rank on paired per-sample errors."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    res = _st.wilcoxon(a[ok], b[ok])
    return float(res.statistic), float(res.pvalue), int(ok.sum())


def holm(pvals):
    """Holm-Bonferroni adjusted p-values (same order as input)."""
    p = np.asarray(pvals, float)
    order = np.argsort(p)
    m = len(p)
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * p[i])
        adj[i] = min(1.0, running)
    return adj


def bland_altman(pred, ref):
    pred, ref = np.asarray(pred, float), np.asarray(ref, float)
    diff = pred - ref
    bias = diff.mean()
    sd = diff.std(ddof=1)
    return float(bias), float(bias - 1.96 * sd), float(bias + 1.96 * sd)
