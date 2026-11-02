"""Host client for the AssistVision camera glasses (firmware glasses-1.0).

    python src/glasses_client.py --host assistvision-glasses.local status
    python src/glasses_client.py --host ... meal --id 2026-10-14-lunch --phase served
    python src/glasses_client.py --host ... meal --id 2026-10-14-lunch --phase cleared --wait-button

One call downloads one burst into data/meals/<id>/<phase>/frame_XX.jpg with a
meta.json. "cleared" is refused until a "served" burst exists for that meal.
The glasses only take photos; % eaten is computed later on the host.
"""
import argparse
import json
import os
import time
import urllib.request
from datetime import datetime, timezone

PHASES = ("served", "cleared")


class GlassesError(RuntimeError):
    pass


def _get(base, path, timeout=10.0, method="GET"):
    req = urllib.request.Request(base + path, method=method, data=b"" if method == "POST" else None)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def status(base):
    return json.loads(_get(base, "/status"))


def wait_burst(base, after_id, timeout_s=30.0, poll_s=0.3):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        s = status(base)
        if s["burst_id"] > after_id:
            return s
        time.sleep(poll_s)
    raise GlassesError(f"no new burst within {timeout_s:.0f} s")


def take_burst(base, trigger=True, timeout_s=30.0):
    before = status(base)["burst_id"]
    if trigger:
        _get(base, "/trigger", method="POST")
    s = wait_burst(base, before, timeout_s)
    if s["frames"] == 0:
        raise GlassesError("burst finished with 0 frames (camera or PSRAM failure)")
    frames = [_get(base, f"/frame?i={i}", timeout=20.0) for i in range(s["frames"])]
    for i, f in enumerate(frames):
        if not f.startswith(b"\xff\xd8"):
            raise GlassesError(f"frame {i} is not a JPEG")
    return s, frames


def save_meal_phase(root, meal_id, phase, st, frames):
    if phase not in PHASES:
        raise GlassesError(f"phase must be one of {PHASES}")
    mdir = os.path.join(root, meal_id)
    if phase == "cleared" and not os.path.exists(os.path.join(mdir, "served", "meta.json")):
        raise GlassesError(f"meal {meal_id!r} has no served burst yet")
    d = os.path.join(mdir, phase)
    if os.path.exists(os.path.join(d, "meta.json")):
        raise GlassesError(f"meal {meal_id!r} already has a {phase} burst")
    os.makedirs(d, exist_ok=True)
    for i, f in enumerate(frames):
        with open(os.path.join(d, f"frame_{i:02d}.jpg"), "wb") as fh:
            fh.write(f)
    meta = {"meal_id": meal_id, "phase": phase, "time_utc": datetime.now(timezone.utc).isoformat(),
            "frames": len(frames), "expected": st.get("burst_frames"), "burst_id": st["burst_id"],
            "framesize": st.get("framesize"), "quality": st.get("jpeg_quality"), "fw": st.get("firmware")}
    with open(os.path.join(d, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=1)
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="assistvision-glasses.local")
    ap.add_argument("--root", default="data/meals")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    m = sub.add_parser("meal")
    m.add_argument("--id", required=True)
    m.add_argument("--phase", choices=PHASES, required=True)
    m.add_argument("--wait-button", action="store_true", help="wait for a button press instead of /trigger")
    a = ap.parse_args()
    base = a.host if a.host.startswith("http") else f"http://{a.host}"
    if a.cmd == "status":
        print(json.dumps(status(base), indent=1))
        return
    st, frames = take_burst(base, trigger=not a.wait_button, timeout_s=120 if a.wait_button else 30)
    meta = save_meal_phase(a.root, a.id, a.phase, st, frames)
    if meta["expected"] and meta["frames"] < meta["expected"]:
        print(f"warning: {meta['frames']}/{meta['expected']} frames captured")
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
