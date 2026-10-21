"""Meal intake from before/after plate measurements (E5 and the companion app).

The rig weighs and scans the plate when a meal is served and again when it is
cleared. Eaten = served - left. Mass comes from the load cell; volume from the
multi-view reconstruction is kept as a cross-check and for the per-item view.

Alert thresholds below are configurable defaults chosen for this prototype,
not clinical cut-offs; a clinician sets them per person.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

PLATE_NOISE_G = 2.0      # below this, a difference is treated as load-cell noise
LOW_MEAL_PCT = 50.0      # default: a meal counts as "low" if under half was eaten
LOW_STREAK = 3           # default: alert after this many low meals in a row
PLATE_NOISE_ML = 5.0     # glasses: served volume below this is an empty plate
PHOTO_TOL = 0.10         # glasses: leftover may exceed served by 10 % before it is flagged


@dataclass
class Meal:
    when: str             # ISO timestamp of serving
    served_g: float       # food on the plate at serving (tare = empty plate)
    left_g: float         # food left when the plate was cleared
    served_ml: float | None = None
    left_ml: float | None = None
    label: str = ""

    @property
    def day(self) -> str:
        return self.when[:10]


def meal_intake(served_g: float, left_g: float, served_ml: float | None = None,
                left_ml: float | None = None) -> dict:
    """Grams and percent eaten. Flags impossible readings instead of hiding them."""
    if served_g <= PLATE_NOISE_G:
        return {"status": "empty_plate", "eaten_g": 0.0, "eaten_pct": None}
    status = "ok"
    if left_g > served_g + PLATE_NOISE_G:
        status = "more_after_than_before"   # food added, plate swapped, or re-tare needed
    left = min(max(left_g, 0.0), served_g)
    eaten = served_g - left
    out = {"status": status, "eaten_g": eaten, "left_g": left, "eaten_pct": 100.0 * eaten / served_g}
    if served_ml is not None and left_ml is not None and served_ml > 0:
        out["eaten_ml"] = max(served_ml - left_ml, 0.0)
        out["eaten_pct_volume"] = 100.0 * out["eaten_ml"] / served_ml
    return out


def photo_intake(served_ml: float, left_ml: float) -> dict:
    """Percent eaten from two image reconstructions (camera glasses, no scale).

    Plate, scale and density are the same in both scans, so the ratio needs no
    grams. Reconstruction noise is larger than load-cell noise, hence the
    relative tolerance before a leftover larger than the serving is flagged.
    """
    if served_ml <= PLATE_NOISE_ML:
        return {"status": "empty_plate", "eaten_pct": None}
    status = "ok"
    if left_ml > served_ml * (1 + PHOTO_TOL):
        status = "more_after_than_before"
    left = min(max(left_ml, 0.0), served_ml)
    return {"status": status, "eaten_pct": 100.0 * (served_ml - left) / served_ml, "left_ml": left}


def low_intake_alert(meals: list[Meal], pct: float = LOW_MEAL_PCT, streak: int = LOW_STREAK) -> dict | None:
    """Alert when the most recent `streak` scored meals were all below `pct` eaten."""
    scored = [(m, meal_intake(m.served_g, m.left_g)) for m in sorted(meals, key=lambda m: m.when)]
    scored = [(m, r) for m, r in scored if r["eaten_pct"] is not None and r["status"] == "ok"]
    tail = scored[-streak:]
    if len(tail) < streak or any(r["eaten_pct"] >= pct for _, r in tail):
        return None
    return {"since": tail[0][0].when, "meals": len(tail),
            "mean_eaten_pct": sum(r["eaten_pct"] for _, r in tail) / len(tail)}


def daily_totals(meals: list[Meal], start: date, days: int) -> list[dict]:
    """Per-day served/eaten grams for `days` days from `start` (missing days are zero meals)."""
    rows = []
    for k in range(days):
        d = (start + timedelta(days=k)).isoformat()
        ms = [meal_intake(m.served_g, m.left_g) for m in meals if m.day == d]
        ms = [r for r in ms if r["eaten_pct"] is not None]
        served = sum(r["eaten_g"] + r["left_g"] for r in ms)
        eaten = sum(r["eaten_g"] for r in ms)
        rows.append({"day": d, "meals": len(ms), "served_g": served, "eaten_g": eaten,
                     "eaten_pct": 100.0 * eaten / served if served else None})
    return rows


def trend_g_per_day(rows: list[dict]) -> float | None:
    """Least-squares slope of eaten grams over days that had meals."""
    pts = [(i, r["eaten_g"]) for i, r in enumerate(rows) if r["meals"]]
    if len(pts) < 3:
        return None
    n = len(pts)
    mx = sum(x for x, _ in pts) / n
    my = sum(y for _, y in pts) / n
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    return sum((x - mx) * (y - my) for x, y in pts) / sxx
