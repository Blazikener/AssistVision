"""Wiring diagram of the capture rig, drawn with orthogonal wires (matplotlib)."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = os.path.join(os.path.dirname(__file__), "..")
RED, BLK, ORG, BLU, PUR, GRN, GRY = "#C53030", "#1A202C", "#DD6B20", "#2B6CB0", "#805AD5", "#2F855A", "#718096"


def module(ax, x, y, w, title, pins, side="right", fill="#F4F6F8"):
    h = 0.42 * len(pins) + 0.55
    ax.add_patch(FancyBboxPatch((x, y - h), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc=fill, ec="#5B6770", lw=1))
    ax.text(x + w / 2, y - 0.3, title, ha="center", va="center", fontsize=8.5, weight="bold")
    pos = {}
    for i, p in enumerate(pins):
        py = y - 0.75 - 0.42 * i
        px = x + w if side == "right" else x
        ax.text(px + (-0.08 if side == "right" else 0.08), py, p, ha="right" if side == "right" else "left",
                va="center", fontsize=7, family="monospace")
        ax.plot(px, py, "o", ms=3, color="#5B6770")
        pos[p] = (px, py)
    return pos


def wire(ax, pts, color, label=None):
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, lw=1.6, solid_capstyle="round", solid_joinstyle="round")
    if label:
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
        ax.text((x0 + x1) / 2, y0 + 0.09, label, ha="center", va="bottom", fontsize=6, color=color)


fig, ax = plt.subplots(figsize=(7.16, 3.5))
ax.set_xlim(0, 14); ax.set_ylim(-0.75, 6.6); ax.axis("off")

esp = module(ax, 0.6, 6.3, 3.0, "ESP32-S3 CAM (N16R8)",
             ["5V", "GND", "3V3", "GPIO1", "GPIO2", "GPIO14", "GPIO21", "GPIO47", "GPIO41"])
hx = module(ax, 6.6, 6.3, 2.2, "HX711", ["VCC", "GND", "DT", "SCK"], side="left")
uln = module(ax, 6.6, 3.5, 2.2, "ULN2003", ["IN1", "IN2", "IN3", "IN4", "+5V", "GND"], side="left")
psu = module(ax, 0.6, 1.25, 3.0, "5 V / 2 A USB-C", ["+5V", "GND"])

# right-hand peripherals (no pin rows)
for (x, y, w, h, t) in [(10.6, 6.0, 2.9, 1.0, "5 kg load cell\nE+ E- A+ A-"), (10.6, 3.2, 2.9, 1.0, "28BYJ-48 stepper\n5-pin JST"),
                        (10.6, 1.4, 2.9, 0.9, "Lazy-susan bearing\n+ turntable top")]:
    ax.add_patch(FancyBboxPatch((x, y - h), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc="#F4F6F8", ec="#5B6770", lw=1))
    ax.text(x + w / 2, y - h / 2, t, ha="center", va="center", fontsize=7.5)

bus5, busg = 4.6, 4.95
wire(ax, [esp["5V"], (bus5, esp["5V"][1]), (bus5, psu["+5V"][1]), psu["+5V"]], RED)
wire(ax, [(bus5, uln["+5V"][1]), uln["+5V"]], RED)
wire(ax, [esp["GND"], (busg, esp["GND"][1]), (busg, psu["GND"][1]), psu["GND"]], BLK)
wire(ax, [(busg, uln["GND"][1]), uln["GND"]], BLK)
wire(ax, [(busg, hx["GND"][1]), hx["GND"]], BLK)
wire(ax, [esp["3V3"], (5.6, esp["3V3"][1]), (5.6, hx["VCC"][1]), hx["VCC"]], ORG, "3.3 V")
wire(ax, [esp["GPIO1"], (5.8, esp["GPIO1"][1]), (5.8, hx["DT"][1]), hx["DT"]], BLU, "DT")
wire(ax, [esp["GPIO2"], (6.0, esp["GPIO2"][1]), (6.0, hx["SCK"][1]), hx["SCK"]], PUR, "SCK")
for k, (a, b) in enumerate([("GPIO14", "IN1"), ("GPIO21", "IN2"), ("GPIO47", "IN3"), ("GPIO41", "IN4")]):
    xm = 5.4 + 0.2 * k
    wire(ax, [esp[a], (xm, esp[a][1]), (xm, uln[b][1]), uln[b]], GRN)
ax.plot([bus5, bus5, busg], [uln["+5V"][1], psu["+5V"][1], psu["GND"][1]], "o", ms=3.5, color=BLK, zorder=5)
ax.plot([busg, busg], [uln["GND"][1], hx["GND"][1]], "o", ms=3.5, color=BLK, zorder=5)
wire(ax, [(8.8, 5.5), (10.6, 5.5)], GRY, "4-wire bridge")
wire(ax, [(8.8, 2.7), (10.6, 2.7)], GRY, "coils A-D, +5 V")
ax.annotate("", xy=(12.05, 1.4), xytext=(12.05, 2.2), arrowprops=dict(arrowstyle="-|>", color=GRY, lw=1))
ax.text(12.15, 1.8, "drives", fontsize=6, color=GRY, va="center")
ax.text(0.6, -0.6, "HX711 on the 3V3 rail (quiet reference, 3.3 V logic). Motor on 5 V via ULN2003; coils released while weighing/capturing.",
        fontsize=6.3, color="#4A5568")
fig.savefig(os.path.join(OUT, "wiring.pdf"), bbox_inches="tight")
fig.savefig("/tmp/wiring.png", dpi=160, bbox_inches="tight")
