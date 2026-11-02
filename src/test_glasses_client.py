"""Tests for glasses_client against a fake glasses HTTP server (no hardware)."""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(__file__))
import glasses_client as gc  # noqa: E402

JPEG = b"\xff\xd8fake\xff\xd9"


class Fake:
    def __init__(self, frames=8, bad=False):
        self.burst_id, self.count, self.frames, self.bad = 0, 0, frames, bad

    def handler(fake):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, body, ctype="application/json"):
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/status":
                    self._send(json.dumps({"firmware": "glasses-1.0", "burst_id": fake.burst_id, "frames": fake.count,
                                           "burst_frames": 8, "framesize": "UXGA", "jpeg_quality": 10}).encode())
                elif self.path.startswith("/frame"):
                    self._send(b"notjpeg" if fake.bad else JPEG, "image/jpeg")

            def do_POST(self):
                fake.burst_id += 1
                fake.count = fake.frames
                self._send(b'{"ok":true}')
        return H


def serve(fake):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), fake.handler())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def expect_error(fn, *a, **k):
    try:
        fn(*a, **k)
    except gc.GlassesError:
        return
    raise AssertionError("expected GlassesError")


def test_served_then_cleared():
    srv, base = serve(Fake())
    with tempfile.TemporaryDirectory() as root:
        for phase in gc.PHASES:
            st, frames = gc.take_burst(base, timeout_s=3)
            meta = gc.save_meal_phase(root, "m1", phase, st, frames)
            assert meta["frames"] == meta["expected"] == 8 and meta["fw"] == "glasses-1.0" and len(os.listdir(os.path.join(root, "m1", phase))) == 9
    srv.shutdown()


def test_cleared_before_served_and_duplicate():
    st, frames = {"burst_id": 1, "frames": 1}, [JPEG]
    with tempfile.TemporaryDirectory() as root:
        expect_error(gc.save_meal_phase, root, "m2", "cleared", st, frames)
        gc.save_meal_phase(root, "m2", "served", st, frames)
        expect_error(gc.save_meal_phase, root, "m2", "served", st, frames)
        expect_error(gc.save_meal_phase, root, "m2", "lunch", st, frames)


def test_failed_and_corrupt_bursts():
    for fake in (Fake(frames=0), Fake(bad=True)):
        srv, base = serve(fake)
        expect_error(gc.take_burst, base, timeout_s=3)
        srv.shutdown()


def test_timeout_without_press():
    srv, base = serve(Fake())
    expect_error(gc.take_burst, base, trigger=False, timeout_s=0.5)
    srv.shutdown()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print(f"{len(tests)}/{len(tests)} passed")
