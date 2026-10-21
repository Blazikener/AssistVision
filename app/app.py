"""AssistVision Care: companion app for the meal-intake rig.

One page per older adult for family members and the doctor: what was served,
how much was eaten, the two-week trend, low-intake alerts and a printable
weekly report. The rig posts each cleared plate to /api/meals.

    python app/app.py --seed      # demo data (fictional residents), then serve on :5000
    python app/app.py             # serve existing data

Prototype: notifications are recorded in the app, not sent (no SMS/email
provider is configured).
"""
from __future__ import annotations

import argparse
import os
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta

from flask import Flask, abort, g, jsonify, redirect, render_template, request, url_for

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from intake import (
    photo_intake,
    LOW_MEAL_PCT,
    LOW_STREAK,
    Meal,
    daily_totals,
    low_intake_alert,
    meal_intake,
    trend_g_per_day,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS residents (id INTEGER PRIMARY KEY, name TEXT NOT NULL, age INTEGER, notes TEXT,
  low_pct REAL NOT NULL DEFAULT 50, streak INTEGER NOT NULL DEFAULT 3);
CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY, resident_id INTEGER NOT NULL, name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('family', 'doctor')), reach TEXT);
CREATE TABLE IF NOT EXISTS meals (id INTEGER PRIMARY KEY, resident_id INTEGER NOT NULL, served_at TEXT NOT NULL,
  label TEXT, served_g REAL NOT NULL, left_g REAL NOT NULL, source TEXT NOT NULL DEFAULT 'manual');
CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY, resident_id INTEGER NOT NULL, created TEXT NOT NULL,
  message TEXT NOT NULL, notified TEXT NOT NULL);
"""


def create_app(db_path: str | None = None, today: date | None = None) -> Flask:
    app = Flask(__name__)
    app.config["DB"] = db_path or os.environ.get("CARE_DB", os.path.join(os.path.dirname(__file__), "care.db"))
    app.config["TODAY"] = today

    def db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DB"])
            g.db.row_factory = sqlite3.Row
            g.db.executescript(SCHEMA)
        return g.db

    @app.teardown_appcontext
    def close(_):
        d = g.pop("db", None)
        if d is not None:
            d.close()

    def now() -> date:
        return app.config["TODAY"] or date.today()

    def resident(rid):
        r = db().execute("SELECT * FROM residents WHERE id = ?", (rid,)).fetchone()
        if r is None:
            abort(404)
        return r

    def meals_of(rid, since: date | None = None):
        q, args = "SELECT * FROM meals WHERE resident_id = ?", [rid]
        if since:
            q += " AND served_at >= ?"
            args.append(since.isoformat())
        rows = db().execute(q + " ORDER BY served_at", args).fetchall()
        return [Meal(r["served_at"], r["served_g"], r["left_g"], label=r["label"] or "") for r in rows], rows

    def summary(r, days=14):
        start = now() - timedelta(days=days - 1)
        meals, rows = meals_of(r["id"], start)
        daily = daily_totals(meals, start, days)
        week = daily[-7:]
        served = sum(d["served_g"] for d in week)
        eaten = sum(d["eaten_g"] for d in week)
        return {
            "resident": dict(r), "daily": daily, "meals": [dict(x, **meal_intake(x["served_g"], x["left_g"])) for x in rows],
            "week_eaten_pct": 100 * eaten / served if served else None,
            "week_eaten_g_per_day": eaten / 7,
            "trend_g_per_day": trend_g_per_day(week),
            "alert": low_intake_alert(meals, r["low_pct"], r["streak"]),
        }

    def record_meal(rid, served_at, label, served_g, left_g, source):
        r = resident(rid)
        before = low_intake_alert(meals_of(rid)[0], r["low_pct"], r["streak"])
        db().execute("INSERT INTO meals (resident_id, served_at, label, served_g, left_g, source) VALUES (?,?,?,?,?,?)",
                     (rid, served_at, label, served_g, left_g, source))
        alert = low_intake_alert(meals_of(rid)[0], r["low_pct"], r["streak"])
        if alert and not before:
            who = [c["name"] for c in db().execute("SELECT name FROM contacts WHERE resident_id = ?", (rid,))]
            msg = f"{r['name']} ate under {r['low_pct']:.0f}% of the last {alert['meals']} meals (average {alert['mean_eaten_pct']:.0f}%)."
            db().execute("INSERT INTO alerts (resident_id, created, message, notified) VALUES (?,?,?,?)",
                         (rid, served_at, msg, ", ".join(who)))
        db().commit()
        return meal_intake(served_g, left_g), alert

    @app.get("/")
    def home():
        cards = [summary(r) for r in db().execute("SELECT * FROM residents ORDER BY name")]
        return render_template("home.html", cards=cards, today=now())

    @app.get("/r/<int:rid>")
    def dashboard(rid):
        r = resident(rid)
        s = summary(r)
        today_meals = [m for m in s["meals"] if m["served_at"][:10] == now().isoformat()]
        contacts = db().execute("SELECT * FROM contacts WHERE resident_id = ? ORDER BY role, name", (rid,)).fetchall()
        alerts = db().execute("SELECT * FROM alerts WHERE resident_id = ? ORDER BY created DESC LIMIT 5", (rid,)).fetchall()
        return render_template("dashboard.html", s=s, r=r, today_meals=today_meals, contacts=contacts, alerts=alerts,
                               today=now(), recent=list(reversed(s["meals"]))[:12])

    @app.post("/r/<int:rid>/meals")
    def add_meal(rid):
        f = request.form
        served_at = f.get("served_at") or datetime.now().strftime("%Y-%m-%dT%H:%M")
        record_meal(rid, served_at, f.get("label", ""), float(f["served_g"]), float(f["left_g"]), "manual")
        return redirect(url_for("dashboard", rid=rid))

    @app.get("/r/<int:rid>/report")
    def report(rid):
        r = resident(rid)
        s = summary(r, days=7)
        return render_template("report.html", s=s, r=r, today=now())

    @app.post("/api/meals")
    def api_meal():
        j = request.get_json(force=True)
        source = j.get("source", "rig")
        try:
            rid = int(j["resident_id"])
            if "served_ml" in j:  # camera glasses: two reconstructed volumes, no scale
                photo = photo_intake(float(j["served_ml"]), float(j["left_ml"]))
                if photo["eaten_pct"] is None:
                    return jsonify(error=photo["status"]), 422
                # stored as a share of a nominal 100-unit serving; no grams are claimed
                served_g, left_g = 100.0, 100.0 - photo["eaten_pct"]
                source = j.get("source", "glasses")
            else:
                served_g, left_g = float(j["served_g"]), float(j["left_g"])
        except (KeyError, TypeError, ValueError):
            return jsonify(error="resident_id plus served_g/left_g or served_ml/left_ml are required numbers"), 400
        intake, alert = record_meal(rid, j.get("when") or datetime.now().strftime("%Y-%m-%dT%H:%M"),
                                    j.get("label", ""), served_g, left_g, source)
        return jsonify(intake=intake, alert=alert), 201

    @app.get("/api/residents/<int:rid>/summary")
    def api_summary(rid):
        return jsonify(summary(resident(rid)))

    @app.template_filter("pct")
    def pct(v):
        return "–" if v is None else f"{v:.0f}%"

    @app.template_filter("hm")
    def hm(v):
        return datetime.fromisoformat(v).strftime("%-I:%M %p")

    @app.template_filter("dshort")
    def dshort(v):
        return date.fromisoformat(v[:10]).strftime("%a %-d")

    app.jinja_env.globals.update(LOW_MEAL_PCT=LOW_MEAL_PCT, LOW_STREAK=LOW_STREAK)
    app.record_meal = record_meal
    app.db = db
    return app


MENU = {8: ["Idli, sambar", "Pongal, chutney", "Upma", "Dosa, chutney", "Ragi porridge"],
        13: ["Rice, dal, beans poriyal", "Rice, sambar, cabbage", "Curd rice, pickle", "Rice, rasam, keerai", "Chapati, dal"],
        19: ["Chapati, mixed veg", "Idiyappam, kurma", "Rice, dal", "Dosa, sambar", "Wheat upma"]}


def seed(app: Flask, today: date, days: int = 14):
    """Fictional demo data: one resident eating well, one whose intake falls over the last week."""
    rnd = random.Random(3)
    with app.app_context():
        d = app.db()
        d.executescript("DELETE FROM residents; DELETE FROM contacts; DELETE FROM meals; DELETE FROM alerts;")
        people = [("Lakshmi Narayanan", 78, "Type 2 diabetes. Prefers soft food.", False,
                   [("Priya (daughter)", "family", "+91 98xxx xxx21"), ("Dr. R. Meenakshi", "doctor", "Geriatric clinic")]),
                  ("Abdul Kareem", 84, "Recovering from a fall, on new medication since last week.", True,
                   [("Imran (son)", "family", "+971 5x xxx xx48"), ("Dr. S. Varadharajan", "doctor", "Family physician")])]
        for name, age, notes, declining, contacts in people:
            rid = d.execute("INSERT INTO residents (name, age, notes) VALUES (?,?,?)", (name, age, notes)).lastrowid
            for c in contacts:
                d.execute("INSERT INTO contacts (resident_id, name, role, reach) VALUES (?,?,?,?)", (rid, *c))
            d.commit()
            for k in range(days):
                day = today - timedelta(days=days - 1 - k)
                for hour, items in MENU.items():
                    if day == today and hour > 13:
                        continue
                    served = rnd.uniform(230, 420) if hour != 8 else rnd.uniform(180, 300)
                    eaten = rnd.uniform(0.7, 0.98)
                    if declining and k >= days - 6:
                        eaten = max(0.15, 0.72 - 0.09 * (k - (days - 6)) + rnd.uniform(-0.05, 0.05))
                    when = f"{day.isoformat()}T{hour:02d}:{rnd.randint(0, 40):02d}"
                    app.record_meal(rid, when, rnd.choice(items), round(served), round(served * (1 - eaten)),
                                    "rig" if rnd.random() < 0.8 else "manual")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--port", type=int, default=5000)
    a = ap.parse_args()
    application = create_app()
    if a.seed:
        seed(application, date.today())
    application.run(host="0.0.0.0", port=a.port)
