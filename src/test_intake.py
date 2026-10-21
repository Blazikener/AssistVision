"""Tests for src/intake.py.  python src/test_intake.py"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from intake import Meal, daily_totals, low_intake_alert, meal_intake, photo_intake, trend_g_per_day


def test_basic():
    r = meal_intake(400, 100, 380, 90)
    assert r["status"] == "ok" and r["eaten_g"] == 300 and abs(r["eaten_pct"] - 75) < 1e-9
    assert abs(r["eaten_ml"] - 290) < 1e-9


def test_guards():
    assert meal_intake(1.0, 0.0)["status"] == "empty_plate"
    r = meal_intake(200, 260)
    assert r["status"] == "more_after_than_before" and r["eaten_g"] == 0
    assert meal_intake(200, -3)["eaten_g"] == 200


def test_photo_intake():
    r = photo_intake(200, 50)
    assert r["status"] == "ok" and abs(r["eaten_pct"] - 75) < 1e-9
    assert photo_intake(3, 0)["status"] == "empty_plate"
    assert photo_intake(200, 215)["status"] == "ok"          # within reconstruction noise
    r = photo_intake(200, 260)
    assert r["status"] == "more_after_than_before" and r["eaten_pct"] == 0
    assert photo_intake(200, -4)["eaten_pct"] == 100


def test_alert():
    ms = [Meal("2026-10-01T08:00", 300, 50), Meal("2026-10-01T13:00", 400, 300),
          Meal("2026-10-01T20:00", 350, 250), Meal("2026-10-02T08:00", 300, 200)]
    a = low_intake_alert(ms)
    assert a and a["meals"] == 3 and a["since"] == "2026-10-01T13:00"
    assert low_intake_alert(ms + [Meal("2026-10-02T13:00", 400, 100)]) is None
    assert low_intake_alert(ms[:2]) is None


def test_daily_and_trend():
    ms = [Meal(f"2026-10-0{d}T13:00", 400, 400 - 300 + 40 * d) for d in range(1, 6)]
    rows = daily_totals(ms, date(2026, 10, 1), 7)
    assert [r["meals"] for r in rows] == [1, 1, 1, 1, 1, 0, 0]
    assert abs(trend_g_per_day(rows) + 40) < 1e-9


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} passed")
