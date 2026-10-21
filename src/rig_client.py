"""Host-side driver for the ESP32-S3 capture rig (hardware/firmware/assistvision_rig).

    python src/rig_client.py status
    python src/rig_client.py tare
    python src/rig_client.py calibrate --grams 500
    python src/rig_client.py scan --views 24 --out captures/plate_001 --label "rice+dal"
    python src/rig_client.py bench-scale --masses 0,50,100,200,500,1000 --repeats 10 --out results/hw/scale.csv
    python src/rig_client.py bench-turntable --revs 5 --out results/hw/turntable.csv
    python src/rig_client.py meal --phase served --id 2026-10-14_lunch --out captures/meals
    python src/rig_client.py meal --phase cleared --id 2026-10-14_lunch --out captures/meals --app http://localhost:5000

A scan writes view_XX.jpg, weight before and after (drift check), the exact
turntable angle of every view, firmware status and camera settings into
scan.json -- everything needed to reproduce the reconstruction later.
"""
from __future__ import annotations

import argparse
import csv
import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_HOST = os.environ.get("RIG_HOST", "http://assistvision.local")


class Rig:
    def __init__(self, host: str = DEFAULT_HOST, timeout: float = 30.0, retries: int = 3):
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.retries = retries

    def _req(self, method: str, path: str, **params):
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{self.host}{path}" + (f"?{q}" if q else "")
        last = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None)
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return r.read(), dict(r.headers)
            except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
                last = e
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"{method} {url} failed after {self.retries} tries: {last}")

    def _json(self, method, path, **params):
        body, _ = self._req(method, path, **params)
        return json.loads(body)

    def status(self):
        return self._json("GET", "/status")

    def weight(self, n=15):
        return self._json("GET", "/weight", n=n)

    def tare(self, n=30):
        return self._json("POST", "/tare", n=n)

    def calibrate(self, grams, n=30):
        return self._json("POST", "/calibrate", grams=grams, n=n)

    def rotate(self, deg):
        return self._json("POST", "/rotate", deg=deg)

    def home(self):
        return self._json("POST", "/home")

    def camera(self, **settings):
        return self._json("POST", "/camera", **settings)

    def capture(self):
        t0 = time.perf_counter()
        body, headers = self._req("GET", "/capture")
        return body, headers, time.perf_counter() - t0


def scan(rig: Rig, views: int, out: str, label: str = "", framesize="UXGA", quality=10):
    os.makedirs(out, exist_ok=True)
    rig.home()
    rig.camera(framesize=framesize, quality=quality, lock=1)
    w0 = rig.weight(n=30)
    step = 360.0 / views
    records = []
    t_scan = time.perf_counter()
    for i in range(views):
        img, hdr, dt = rig.capture()
        path = os.path.join(out, f"view_{i:02d}.jpg")
        with open(path, "wb") as f:
            f.write(img)
        st = rig.status()
        records.append({
            "file": os.path.basename(path),
            "step_position": st["step_position"],
            "angle_deg": st["step_position"] * 360.0 / st["steps_per_rev"],
            "bytes": len(img),
            "transfer_s": dt,
            "frame_size": hdr.get("X-Frame-Size"),
        })
        if i < views - 1:
            rig.rotate(step)
    scan_s = time.perf_counter() - t_scan
    rig.home()
    w1 = rig.weight(n=30)
    meta = {
        "label": label,
        "views": records,
        "weight_before": w0,
        "weight_after": w1,
        "scan_seconds": scan_s,
        "status": rig.status(),
        "host_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    with open(os.path.join(out, "scan.json"), "w") as f:
        json.dump(meta, f, indent=2)
    return meta


def meal(rig: Rig, phase, meal_id, out, views=24, app=None, resident=1, label=""):
    """Weigh (and optionally scan) the plate when a meal is served and when it is cleared.

    The plate is tared empty before serving, so the reading is food mass.
    `cleared` computes intake with src/intake.py and can post it to the companion app.
    """
    from intake import meal_intake
    d = os.path.join(out, meal_id)
    os.makedirs(d, exist_ok=True)
    if views:
        m = scan(rig, views, os.path.join(d, phase), label)
        grams = m["weight_after"]["grams"]
    else:
        grams = rig.weight(n=30)["grams"]
    rec_path = os.path.join(d, "meal.json")
    rec = json.load(open(rec_path)) if os.path.exists(rec_path) else {"id": meal_id, "label": label}
    rec[phase] = {"grams": grams, "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "views": views}
    if phase == "cleared" and "served" in rec:
        rec["intake"] = meal_intake(rec["served"]["grams"], grams)
        if app:
            body = json.dumps({"resident_id": resident, "when": rec["served"]["time"], "label": rec.get("label", ""),
                               "served_g": rec["served"]["grams"], "left_g": grams, "source": "rig"}).encode()
            req = urllib.request.Request(app.rstrip("/") + "/api/meals", data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                rec["posted"] = json.loads(r.read())
    with open(rec_path, "w") as f:
        json.dump(rec, f, indent=2)
    return rec


def bench_scale(rig: Rig, masses, repeats, out):
    """Linearity / repeatability: place each reference mass when prompted."""
    rows = []
    for m in masses:
        input(f"Place {m} g reference mass (0 = empty plate) and press Enter...")
        for r in range(repeats):
            w = rig.weight(n=15)
            rows.append({"ref_g": m, "repeat": r, "grams": w["grams"], "raw": w["raw"],
                         "std_counts": w["std_counts"], "ms": w["ms"]})
            print(rows[-1])
    _write(out, rows)


def bench_turntable(rig: Rig, revs, out, views=24):
    """Angular repeatability: photograph a fiducial at the same angle after full revolutions.

    The angle error is recovered offline from the ArUco pose in each image
    (experiments/hw_turntable_analysis.py), so no encoder is needed.
    """
    os.makedirs(os.path.splitext(out)[0], exist_ok=True)
    rows = []
    rig.home()
    for k in range(revs):
        for i in range(views):
            rig.rotate(360.0 / views)
        img, _, dt = rig.capture()
        p = os.path.join(os.path.splitext(out)[0], f"rev_{k:02d}.jpg")
        with open(p, "wb") as f:
            f.write(img)
        rows.append({"rev": k, "file": p, "step_position": rig.status()["step_position"], "transfer_s": dt})
    rig.home()
    _write(out, rows)


def _write(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path} ({len(rows)} rows)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=DEFAULT_HOST)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("tare")
    c = sub.add_parser("calibrate"); c.add_argument("--grams", type=float, required=True)
    s = sub.add_parser("scan")
    s.add_argument("--views", type=int, default=24); s.add_argument("--out", required=True)
    s.add_argument("--label", default=""); s.add_argument("--framesize", default="UXGA")
    s.add_argument("--quality", type=int, default=10)
    b = sub.add_parser("bench-scale")
    b.add_argument("--masses", default="0,50,100,200,500,1000"); b.add_argument("--repeats", type=int, default=10)
    b.add_argument("--out", default="results/hw/scale.csv")
    t = sub.add_parser("bench-turntable")
    t.add_argument("--revs", type=int, default=5); t.add_argument("--out", default="results/hw/turntable.csv")
    ml = sub.add_parser("meal")
    ml.add_argument("--phase", choices=["served", "cleared"], required=True); ml.add_argument("--id", required=True)
    ml.add_argument("--out", default="captures/meals"); ml.add_argument("--views", type=int, default=24,
                    help="0 = weigh only, no scan"); ml.add_argument("--label", default="")
    ml.add_argument("--app", default=None, help="companion app URL to post the result to")
    ml.add_argument("--resident", type=int, default=1)
    a = ap.parse_args()
    rig = Rig(a.host)
    if a.cmd == "status":
        print(json.dumps(rig.status(), indent=2))
    elif a.cmd == "tare":
        print(rig.tare())
    elif a.cmd == "calibrate":
        print(rig.calibrate(a.grams))
    elif a.cmd == "scan":
        m = scan(rig, a.views, a.out, a.label, a.framesize, a.quality)
        print(f"{len(m['views'])} views in {m['scan_seconds']:.1f}s, "
              f"{m['weight_before']['grams']} g -> {m['weight_after']['grams']} g")
    elif a.cmd == "meal":
        r = meal(rig, a.phase, a.id, a.out, a.views, a.app, a.resident, a.label)
        print(json.dumps(r.get("intake", r[a.phase]), indent=2))
    elif a.cmd == "bench-scale":
        bench_scale(rig, [float(x) for x in a.masses.split(",")], a.repeats, a.out)
    elif a.cmd == "bench-turntable":
        bench_turntable(rig, a.revs, a.out)


if __name__ == "__main__":
    main()
