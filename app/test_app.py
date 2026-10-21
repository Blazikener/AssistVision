"""Tests for the companion app.  python app/test_app.py"""
import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import create_app, seed

TODAY = date(2026, 10, 14)


def make():
    d = tempfile.mkdtemp()
    app = create_app(os.path.join(d, "t.db"), today=TODAY)
    seed(app, TODAY)
    return app, app.test_client()


def test_pages_render():
    _app, c = make()
    for url in ["/", "/r/1", "/r/2", "/r/1/report", "/api/residents/1/summary"]:
        assert c.get(url).status_code == 200, url
    assert c.get("/r/99").status_code == 404


def test_seed_alerts_only_declining_resident():
    _app, c = make()
    by_name = {s["resident"]["name"]: s for s in (c.get(f"/api/residents/{i}/summary").get_json() for i in (1, 2))}
    assert by_name["Abdul Kareem"]["alert"] is not None
    assert by_name["Lakshmi Narayanan"]["alert"] is None


def test_api_posts_and_alerts_once():
    app, c = make()
    rid = next(i for i in (1, 2) if c.get(f"/api/residents/{i}/summary").get_json()["alert"] is None)
    for k in range(3):
        r = c.post("/api/meals", json={"resident_id": rid, "when": f"2026-10-14T2{k}:00", "served_g": 300, "left_g": 240})
        assert r.status_code == 201
    assert r.get_json()["alert"]["meals"] == 3
    with app.app_context():
        n = app.db().execute("SELECT COUNT(*) FROM alerts WHERE resident_id = ?", (rid,)).fetchone()[0]
    assert n == 1
    assert c.post("/api/meals", json={"resident_id": rid}).status_code == 400


def test_api_accepts_glasses_volumes():
    app, c = make()
    r = c.post("/api/meals", json={"resident_id": 1, "when": "2026-10-14T13:00", "served_ml": 400, "left_ml": 100})
    assert r.status_code == 201
    assert abs(r.get_json()["intake"]["eaten_pct"] - 75.0) < 1e-6
    with app.app_context():
        src = app.db().execute("SELECT source FROM meals ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert src == "glasses"
    assert c.post("/api/meals", json={"resident_id": 1, "served_ml": 2, "left_ml": 0}).status_code == 422
    assert c.post("/api/meals", json={"resident_id": 1, "served_ml": 400}).status_code == 400


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} passed")
