"""rig_client against an in-process fake of the firmware HTTP API.

Exercises the same endpoints, argument names and JSON keys as
hardware/firmware/assistvision_rig/assistvision_rig.ino, so a renamed field
on either side fails here before it fails on the bench.
"""
import json
import os
import re
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(__file__))
import rig_client  # noqa: E402

STEPS_PER_REV = 4075.77
FW = os.path.join(os.path.dirname(__file__), "..", "hardware", "firmware", "assistvision_rig", "assistvision_rig.ino")


class FakeRig(BaseHTTPRequestHandler):
    state = {"pos": 0, "tare": 1000, "cpg": 420.0, "load_g": 250.0, "fail_next_capture": 1}

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", headers=None):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _route(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        s = self.state
        raw = int(s["tare"] + s["load_g"] * s["cpg"])
        if u.path == "/status":
            return self._send(200, {"firmware": "fake", "step_position": s["pos"], "steps_per_rev": STEPS_PER_REV})
        if u.path == "/weight":
            return self._send(200, {"grams": (raw - s["tare"]) / s["cpg"], "raw": raw, "std_counts": 3.0, "n": int(q.get("n", 15)), "ms": 1})
        if u.path == "/tare":
            s["tare"] = raw
            return self._send(200, {"tare_raw": raw, "std_counts": 2.0})
        if u.path == "/calibrate":
            s["cpg"] = (raw - s["tare"]) / float(q["grams"])
            return self._send(200, {"counts_per_gram": s["cpg"]})
        if u.path == "/rotate":
            steps = round(float(q["deg"]) / 360 * STEPS_PER_REV)
            s["pos"] += steps
            return self._send(200, {"steps": steps, "position": s["pos"]})
        if u.path == "/home":
            s["pos"] = 0
            return self._send(200, {"position": 0})
        if u.path == "/camera":
            return self._send(200, {"firmware": "fake"})
        if u.path == "/capture":
            if s["fail_next_capture"]:
                s["fail_next_capture"] -= 1
                self.close_connection = True
                return  # drop the connection: client must retry
            return self._send(200, b"\xff\xd8fakejpeg\xff\xd9", "image/jpeg", {"X-Frame-Size": "1600x1200"})
        self._send(404, {"error": "no route"})

    do_GET = do_POST = _route


def serve():
    srv = HTTPServer(("127.0.0.1", 0), FakeRig)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_scan_roundtrip():
    srv = serve()
    rig = rig_client.Rig(f"http://127.0.0.1:{srv.server_port}", timeout=2, retries=3)
    with tempfile.TemporaryDirectory() as d:
        meta = rig_client.scan(rig, views=24, out=d, label="t")
        assert len(meta["views"]) == 24
        assert len([f for f in os.listdir(d) if f.endswith(".jpg")]) == 24
        angles = [v["angle_deg"] for v in meta["views"]]
        steps = [b - a for a, b in zip(angles, angles[1:])]
        # integer half-steps: per-view angle quantised to 360/4075.77 = 0.088 deg
        assert all(abs(s - 15.0) < 360 / STEPS_PER_REV for s in steps), steps
        assert abs(meta["weight_before"]["grams"] - 250.0) < 0.01
        assert json.load(open(os.path.join(d, "scan.json")))["label"] == "t"
    srv.shutdown()
    print("PASS  scan: 24 views, dropped frame retried, angle quantisation < 0.088 deg")


def test_tare_calibrate():
    srv = serve()
    FakeRig.state.update(tare=1000, cpg=420.0, load_g=0.0)
    rig = rig_client.Rig(f"http://127.0.0.1:{srv.server_port}", timeout=2)
    rig.tare()
    FakeRig.state["load_g"] = 500.0
    rig.calibrate(500)
    assert abs(rig.weight()["grams"] - 500.0) < 1e-6
    srv.shutdown()
    print("PASS  tare + calibrate with 500 g reference")


def test_firmware_api_matches_client():
    """Every endpoint the client calls is registered in the firmware."""
    src = open(FW).read()
    routes = set(re.findall(r'server\.on\("(/\w+)"', src))
    client = set(re.findall(r'_json\("(?:GET|POST)", "(/\w+)"', open(rig_client.__file__).read()))
    client |= set(re.findall(r'_req\("(?:GET|POST)", "(/\w+)"', open(rig_client.__file__).read()))
    assert client <= routes, client - routes
    for key in ["step_position", "steps_per_rev", "grams", "raw", "std_counts", "counts_per_gram"]:
        assert f'\\"{key}\\"' in src, key
    print(f"PASS  firmware registers all {len(client)} client endpoints and JSON keys")


def test_meal_served_cleared():
    srv = serve()
    FakeRig.state.update(tare=1000, cpg=420.0, load_g=0.0)
    rig = rig_client.Rig(f"http://127.0.0.1:{srv.server_port}", timeout=2)
    rig.tare()
    with tempfile.TemporaryDirectory() as d:
        FakeRig.state["load_g"] = 420.0
        rig_client.meal(rig, "served", "lunch", d, views=0, label="rice + dal")
        FakeRig.state["load_g"] = 105.0
        rec = rig_client.meal(rig, "cleared", "lunch", d, views=0)
        assert abs(rec["intake"]["eaten_g"] - 315.0) < 0.01 and abs(rec["intake"]["eaten_pct"] - 75.0) < 0.01
        assert json.load(open(os.path.join(d, "lunch", "meal.json")))["label"] == "rice + dal"
    srv.shutdown()
    print("PASS  meal: served 420 g, cleared 105 g -> 315 g eaten (75 %)")


if __name__ == "__main__":
    test_scan_roundtrip()
    test_tare_calibrate()
    test_meal_served_cleared()
    test_firmware_api_matches_client()
