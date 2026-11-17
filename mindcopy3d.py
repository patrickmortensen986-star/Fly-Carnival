#!/usr/bin/env python3
"""FLY CARNIVAL: a large 3D night carnival with a keyless AI ringmaster.
The real fly.ai MaleCNS connectome controls the flies. A built-in adventure
guide plans their adventures: no model download, no network, no extra installs.

FlyBrain receives simple visual, threat, and food signals from the simulated
stage; its descending-neuron spikes influence each fly's movement. The frozen
connectome does not generate language. The separate ringmaster selects goals
and narrates adventures; the map and abstraction are game rules.

Setup (Python 3.10+):
    python -m pip install flybrain
    python mindcopy3d.py

The first run downloads fly.ai's prebuilt connectome data (about 260 MB).
Tkinter is included with most Python installs; on Linux, you may need your
system's python3-tk package.

The side viewer plots a sample of real MaleCNS neuron soma locations. Orange
points show those sampled neurons firing during the live simulation. Choose a
fly and drag the view to rotate it; each fly has independent neural activity.

The flies are fully 3D: shaded ellipsoid bodies (striped abdomen, thorax, head, compound
eyes), six articulated legs, flapping wings, antennae and a proboscis, all rotating with the
fly's heading.

Camera: click a fly or select one under WATCH to follow it. Use +/- buttons or
scroll over the carnival to zoom; Map resets the overview. The same fly is shown
in the live brain panel. No WASD.

Abstraction: every fly has a fictional game glitch meter that rises over
simulated days. At 100% it transforms. Use ABSTRACT FLY on the selected fly to
trigger it instantly; Reset restores everyone. This is a story mechanic, not
a measurement of the fly brain. +1 MONTH also advances the meters.
Controls: Pause/Resume, Reset, ×1/×25/×100 time, +1 month.

Cast: "+ ADD FLY" (brain panel) opens a small dialog to name a new fly and pick
its costume and color; the camera then follows it. "DELETE FLY" removes the
selected fly. Up to NUM_FLIES flies can be on stage at once because FlyBrain
runs one batched brain slot per fly. Reset keeps your current cast.

Unraveling: as a fly's game glitch meter climbs it passes through "restless",
"unraveling" and "losing it" stages (jittery steering, hallucinated destinations,
shivering, a darkening body) before it abstracts at 100%. This is a story
mechanic, not a measurement of the fly brain.

Adventures: the ringmaster is also an adventure guide. It picks a small party
of flies (the first one leads) and a route of 3-4 attractions, then walks them
from stop to stop with a line of story at each. The route is drawn on the map
(numbered stops, current stop ringed), and party flies get a star. The guide is
a procedural planner that lives in this file, not a language model: it picks a
theme (snack run, thrill ride, stroll, show, mystery), favors flies who have
become friends, avoids repeating recent stops and leaders, and works unraveling
flies into the story. NEW QUEST cancels the current adventure and starts another.
"""
from __future__ import annotations

import math
import os
import queue
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
from dataclasses import dataclass

NUM_FLIES = 6  # max flies on stage = FlyBrain batch size (one brain slot per fly)
NO_FLY = "(none)"
BRAIN_DT = 0.020
STAGE_RADIUS = 36.0
SIM_SECONDS_PER_DAY = 4.0

# Original, simple costumes and names. No show art or external assets are used.
SKINS = [
    ("Ribbon", "#ff70c8", "#ffe5fb", "ribbon"),
    ("Shapes", "#52dfff", "#e8fbff", "diamond"),
    ("Bishop", "#ffb84f", "#fff0c7", "crown"),
    ("Yarn Doll", "#b38cff", "#f2e9ff", "halo"),
    ("Bunny", "#81efaa", "#eafff0", "ears"),
    ("Jester", "#ff647d", "#ffe5e9", "jester"),
]

# Choices offered when adding a new fly.
PALETTE = ["#ff70c8", "#52dfff", "#ffb84f", "#b38cff", "#81efaa",
           "#ff647d", "#c6ff5e", "#5ea8ff", "#ff9a5e", "#5effe0"]
COSTUMES = [("Ribbon", "ribbon"), ("Diamond", "diamond"), ("Crown", "crown"),
            ("Halo", "halo"), ("Bunny ears", "ears"), ("Jester horns", "jester"),
            ("Plain", "plain")]
EXTRA_NAMES = ["Pip", "Moth", "Buzz", "Clover", "Sprout", "Dot", "Fizz",
               "Waffles", "Nimbus", "Tango"]

# Attraction goals and sensory labels are symbolic controls, not trained models.
GOALS = [
    ("MAIN STAGE", -5.6, -2.5, "#ff6b4f", "stage"),
    ("POPCORN CART", 12.0, -8.0, "#ffda55", "food"),
    ("DUCK POND", 16.0, 7.0, "#5ec8ff", "water"),
    ("LANTERN GATE", -15.0, 8.0, "#ffa94d", "gate"),
    ("RING TOSS", 0.0, -15.0, "#71ffbd", "play"),
    ("CAROUSEL", 0.0, 12.0, "#ff8d5e", "stage"),
    ("CIDER ORCHARD", 25.0, -16.0, "#ff9f7a", "food"),
    ("HEDGE MAZE", -23.0, -14.0, "#7be08a", "gate"),
    ("CLOCK TOWER", -22.0, 18.0, "#ffd979", "tower"),
    ("FERRIS WHEEL", 22.0, 19.0, "#f4c3ff", "wheel"),
    ("FIREWORK FIELD", 0.0, -28.0, "#ffd66a", "play"),
    ("BOAT LAKE", 29.0, 3.0, "#8affd5", "water"),
    ("ROSE GARDEN", -28.0, 2.0, "#ff87a9", "play"),
    ("BAND TENT", 0.0, 28.0, "#d3a2ff", "stage"),
    ("WEST GATE", 13.0, -26.0, "#ffb27a", "gate"),
    ("GAME ARCADE", -13.0, -25.0, "#7ceeff", "play"),
]

EVENTS = [
    (1, "THE GATE OPENS", "Six connectome flies wake up beneath the big top."),
    (30, "FIRST ADVENTURE", "The flies chase a ribbon of bubbles around the carousel."),
    (60, "A LITTLE CLOSER", "Ribbon and Shapes keep choosing the same attractions."),
    (120, "LANTERN-GATE MYSTERY", "Bunny leads a brave little expedition through the glowing gate."),
    (180, "THE GREAT BLACKOUT", "The lights blink out. The flies regroup by the spotlight."),
    (270, "CARNIVAL PARADE", "The whole crew circles the stage together for one last parade."),
    (365, "ONE YEAR LATER", "The carnival glitches. Every fly begins to abstract."),
]


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def angle_delta(target: float, current: float) -> float:
    return (target - current + math.pi) % (2 * math.pi) - math.pi


def rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def tint(color: str, factor: float) -> str:
    r, g, b = rgb(color)
    return "#%02x%02x%02x" % (int(clamp(r * factor, 0, 255)),
                             int(clamp(g * factor, 0, 255)),
                             int(clamp(b * factor, 0, 255)))


def mix(color: str, other: str, amount: float) -> str:
    a, b = rgb(color), rgb(other)
    return "#%02x%02x%02x" % tuple(int(a[i] * (1 - amount) + b[i] * amount) for i in range(3))


# Lighting for the 3D fly models. VIEW points from the scene toward the camera
# of the isometric projection (used to cull faces that face away from it).
_LL = math.sqrt(0.35 ** 2 + 0.85 ** 2 + 0.40 ** 2)
LIGHT = (-0.35 / _LL, 0.85 / _LL, -0.40 / _LL)
VIEW = (0.0, 0.433, -0.902)


def _fly_icon_png(size, style):
    """Draw a little fly icon (pure Python, no extra libraries) and return PNG bytes."""
    import struct, zlib
    hexrgb = lambda h: tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
    pal = {"carnival": dict(top="#4b1f86", bot="#14091f", glow="#ff70c8", body="#ff70c8", rim="#2a0f3d", head="#ffe5fb",
                            eye="#52dfff", wing="#e8fbff", leg="#ffe5fb", edge="#ffd65c"),
           "nightmare": dict(top="#4a0608", bot="#050000", glow="#ff2a2a", body="#4a4a55", rim="#120000", head="#62626e",
                             eye="#ff2a2a", wing="#ffb0b0", leg="#8a8a96", edge="#ff2a2a")}[style]
    P = {k: hexrgb(v) for k, v in pal.items()}
    n = size
    R = [[0.0] * (n * n) for _ in range(3)]; A = [0.0] * (n * n)
    clamp = lambda v: 0.0 if v < 0 else 1.0 if v > 1 else v
    for py in range(n):
        y = (py + 0.5) / n
        for px in range(n):
            x = (px + 0.5) / n
            qx, qy = abs(x - 0.5) - 0.26, abs(y - 0.5) - 0.26
            d = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - 0.2
            a = clamp(0.5 - d * n)
            i = py * n + px; A[i] = a
            if a > 0:
                for c in range(3):
                    R[c][i] = P["top"][c] * (1 - y) + P["bot"][c] * y
                # soft glow behind the fly + thin edge line
                g = clamp(1 - math.hypot(x - 0.5, y - 0.5) / 0.42) ** 2 * 0.55
                e = clamp(0.5 - abs(d + 0.012) * n) * 0.8
                for c in range(3):
                    R[c][i] = R[c][i] * (1 - g) + P["glow"][c] * g
                    R[c][i] = R[c][i] * (1 - e) + P["edge"][c] * e

    def paint(bbox, cover, color, alpha=1.0):
        x0, y0, x1, y1 = bbox
        for py in range(max(0, int(y0 * n)), min(n, int(y1 * n) + 2)):
            for px in range(max(0, int(x0 * n)), min(n, int(x1 * n) + 2)):
                i = py * n + px
                if A[i] <= 0:
                    continue
                cv = cover((px + 0.5) / n, (py + 0.5) / n) * alpha
                if cv > 0:
                    for c in range(3):
                        R[c][i] = R[c][i] * (1 - cv) + color[c] * cv

    def ell(cx, cy, rx, ry, ang, color, alpha=1.0):
        ca, sa = math.cos(ang), math.sin(ang); m = max(rx, ry) + 0.02
        def cover(x, y):
            u, v = (x - cx) * ca + (y - cy) * sa, -(x - cx) * sa + (y - cy) * ca
            return clamp(0.5 - (math.sqrt((u / rx) ** 2 + (v / ry) ** 2) - 1) * min(rx, ry) * n)
        paint((cx - m, cy - m, cx + m, cy + m), cover, color, alpha)

    def seg(ax_, ay_, bx_, by_, w, color):
        def cover(x, y):
            vx, vy = bx_ - ax_, by_ - ay_
            t = clamp(((x - ax_) * vx + (y - ay_) * vy) / (vx * vx + vy * vy))
            return clamp(0.5 - (math.hypot(x - ax_ - t * vx, y - ay_ - t * vy) - w) * n)
        paint((min(ax_, bx_) - w - 0.02, min(ay_, by_) - w - 0.02, max(ax_, bx_) + w + 0.02, max(ay_, by_) + w + 0.02), cover, color)

    for s in (-1, 1):                                           # wings, then legs (mirrored)
        ell(0.5 + s * 0.20, 0.43, 0.22, 0.085, s * -0.62, P["wing"], 0.55)
        ell(0.5 + s * 0.17, 0.50, 0.16, 0.06, s * -0.20, P["wing"], 0.30)
        for a_, b_ in (((0.45, 0.41), (0.25, 0.33)), ((0.44, 0.45), (0.21, 0.50)), ((0.46, 0.49), (0.29, 0.69))):
            seg(0.5 + s * (0.5 - a_[0]), a_[1], 0.5 + s * (0.5 - b_[0]), b_[1], 0.011, P["leg"])
    ell(0.5, 0.645, 0.150, 0.215, 0, P["rim"]); ell(0.5, 0.645, 0.133, 0.198, 0, P["body"])      # abdomen
    for k in range(3):
        ell(0.5, 0.56 + k * 0.08, 0.125 - k * 0.012, 0.012, 0, P["rim"], 0.65)                   # stripes
    ell(0.5, 0.43, 0.135, 0.125, 0, P["rim"]); ell(0.5, 0.43, 0.118, 0.108, 0, P["head"])       # thorax
    ell(0.5, 0.28, 0.115, 0.095, 0, P["rim"]); ell(0.5, 0.28, 0.098, 0.078, 0, P["body"])       # head
    for s in (-1, 1):
        ell(0.5 + s * 0.075, 0.265, 0.062, 0.075, s * 0.3, P["rim"]); ell(0.5 + s * 0.075, 0.265, 0.052, 0.065, s * 0.3, P["eye"])
        ell(0.5 + s * 0.060, 0.245, 0.016, 0.022, 0, (255, 255, 255), 0.85)
    raw = bytearray()
    for py in range(n):
        raw.append(0)
        for px in range(n):
            i = py * n + px
            raw += bytes((int(clamp(R[0][i] / 255) * 255), int(clamp(R[1][i] / 255) * 255),
                          int(clamp(R[2][i] / 255) * 255), int(A[i] * 255)))
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def _write_icons(name, style):
    """Create PNG (Linux/macOS) and ICO (Windows) icon files in ~/.fly_shortcuts. Returns (png, ico)."""
    import struct
    d = os.path.join(os.path.expanduser("~"), ".fly_shortcuts"); os.makedirs(d, exist_ok=True)
    base = "".join(ch if ch.isalnum() else "_" for ch in name)
    png_big = _fly_icon_png(256, style)
    png = os.path.join(d, base + ".png"); ico = os.path.join(d, base + ".ico")
    open(png, "wb").write(png_big)
    sizes = [(256, png_big)] + [(s, _fly_icon_png(s, style)) for s in (64, 48, 32, 16)]
    head = struct.pack("<HHH", 0, 1, len(sizes)); body = b""; off = 6 + 16 * len(sizes); entries = b""
    for s, data in sizes:
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), off + len(body)); body += data
    open(ico, "wb").write(head + entries + body)
    return png, ico


def create_desktop_shortcut(script_path, name, args=(), console=False, icon="carnival"):
    """Put a launcher for this script on the desktop. Returns (ok, message).
    Windows: .lnk | macOS: .command | Linux: .desktop"""
    import platform, shlex
    script = os.path.abspath(script_path)
    workdir = os.path.dirname(script)
    system = platform.system()
    args = [str(a) for a in args]
    try:
        png_icon, ico_icon = _write_icons(name, icon)
    except Exception:
        png_icon = ico_icon = None   # no icon is better than no shortcut
    safe = "".join(ch for ch in name if ch not in '\\/:*?"<>|').strip() or "Launcher"
    try:
        if system == "Windows":
            flags = 0x08000000  # CREATE_NO_WINDOW
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "[Environment]::GetFolderPath('Desktop')"],
                               capture_output=True, text=True, timeout=30, creationflags=flags)
            desktop = r.stdout.strip() or os.path.join(os.path.expanduser("~"), "Desktop")
            os.makedirs(desktop, exist_ok=True)
            exe = sys.executable
            pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if not console and os.path.exists(pyw):
                exe = pyw  # no console window behind the app
            lnk = os.path.join(desktop, safe + ".lnk")
            ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:SC_LNK);"
                  "$s.TargetPath=$env:SC_TARGET;$s.Arguments=$env:SC_ARGS;"
                  "$s.WorkingDirectory=$env:SC_DIR;$s.Description=$env:SC_NAME;"
                  "if($env:SC_ICO){$s.IconLocation=$env:SC_ICO};$s.Save()")
            env = dict(os.environ, SC_LNK=lnk, SC_TARGET=exe, SC_NAME=name, SC_DIR=workdir,
                       SC_ARGS=subprocess.list2cmdline([script, *args]), SC_ICO=(ico_icon + ",0") if ico_icon else "")
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env,
                               capture_output=True, text=True, timeout=30, creationflags=flags)
            if r.returncode != 0 or not os.path.exists(lnk):
                return False, "Could not create the shortcut:\n" + (r.stderr.strip() or "PowerShell failed")
            return True, f"Shortcut created on your desktop:\n{lnk}"
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if system == "Linux":
            try:
                out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=10).stdout.strip()
                if out:
                    desktop = out
            except Exception:
                pass
        os.makedirs(desktop, exist_ok=True)
        if system == "Darwin":
            path = os.path.join(desktop, safe + ".command")
            with open(path, "w") as fh:
                fh.write("#!/bin/bash\ncd " + shlex.quote(workdir) + "\nexec "
                         + " ".join(shlex.quote(p) for p in [sys.executable, script, *args]) + "\n")
            os.chmod(path, 0o755)
            if png_icon:  # best effort: give the file a custom Finder icon
                js = ("ObjC.import('AppKit');var i=$.NSImage.alloc.initWithContentsOfFile($(%r));"
                      "$.NSWorkspace.sharedWorkspace.setIconForFileOptions(i,$(%r),0);" % (png_icon, path))
                try:
                    subprocess.run(["osascript", "-l", "JavaScript", "-e", js], capture_output=True, timeout=15)
                except Exception:
                    pass
            return True, f"Shortcut created on your desktop:\n{path}\n(It opens in Terminal when double-clicked.)"
        # Linux / other Unix: freedesktop .desktop launcher
        def q(s):  # quoting rules for the Exec= line
            s = s.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
            return '"' + s + '"'
        path = os.path.join(desktop, safe + ".desktop")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[Desktop Entry]\nType=Application\nName=" + name + "\nComment=" + name + "\n"
                     + "Exec=" + " ".join(q(p) for p in [sys.executable, script, *args]) + "\n"
                     + ("Icon=" + png_icon + "\n" if png_icon else "") + "Path=" + workdir + "\nTerminal=" + ("true" if console else "false") + "\nCategories=Game;\n")
        os.chmod(path, 0o755)
        try:  # lets GNOME treat it as trusted so it launches on double-click
            subprocess.run(["gio", "set", path, "metadata::trusted", "true"], capture_output=True, timeout=10)
        except Exception:
            pass
        return True, (f"Shortcut created on your desktop:\n{path}\n"
                      "(If it shows as untrusted, right-click it and choose 'Allow Launching'.)")
    except Exception as exc:
        return False, f"Could not create the shortcut: {exc}"


@dataclass
class Fly:
    name: str
    color: str
    pale: str
    costume: str
    x: float
    z: float
    yaw: float
    goal: int
    motor: dict[str, int]
    age_days: float = 0.0
    goal_wait: float = 0.0
    mood: str = "waking up"
    abstracted: bool = False
    completed_goal: int = -1
    glitch: float = 0.0
    slot: int = 0  # index of this fly's batched FlyBrain instance

    @property
    def sanity_stage(self) -> str:
        if self.abstracted:
            return "ABSTRACTED"
        if self.glitch < 25:
            return "clear-headed"
        if self.glitch < 50:
            return "restless"
        if self.glitch < 75:
            return "unraveling"
        return "losing it"

    def advance_glitch(self, day_delta: float) -> None:
        # A fictional timer for the circus game, not a measurement of the fly
        # brain's feelings or consciousness. Flies have different thresholds.
        thresholds = {"Bunny": 60, "Ribbon": 85, "Shapes": 110,
                      "Yarn Doll": 140, "Bishop": 175, "Jester": 210}
        threshold = thresholds.get(self.name, 150)
        self.glitch = clamp(self.glitch + max(0.0, day_delta) * 100.0 / threshold, 0, 100)
        if self.glitch >= 100:
            self.abstracted = True

    def advance(self, dt: float, day_delta: float) -> None:
        self.age_days += day_delta
        self.advance_glitch(day_delta)
        self.goal_wait += dt
        steer_l = self.motor.get("steer_L", 0)
        steer_r = self.motor.get("steer_R", 0)
        forward = self.motor.get("forward_L", 0) + self.motor.get("forward_R", 0)
        escape = self.motor.get("escape_L", 0) + self.motor.get("escape_R", 0)
        backward = self.motor.get("backward_L", 0) + self.motor.get("backward_R", 0)

        # Descending-neuron spikes are mapped to simple legible movement.
        # A gentle idle gait keeps the stage alive when the frozen network is quiet.
        self.yaw += clamp((steer_l - steer_r) * 0.34, -2.4, 2.4) * dt
        speed = 0.48 + min(0.8, forward * 0.14)
        if backward:
            speed = -0.30 - min(0.5, backward * 0.07)
            self.mood = "backing away"
        elif escape:
            speed = 1.8 + min(1.0, escape * 0.10)
            self.mood = "startled!"
        elif forward:
            self.mood = "exploring"
        else:
            self.mood = "wandering"

        if not self.abstracted and self.glitch >= 25:
            # Gradual unraveling before abstraction: steering jitter first, then
            # hallucinated destinations, then lurching speed.
            g = (self.glitch - 25.0) / 75.0
            self.yaw += random.gauss(0.0, 1.0) * dt * (0.5 + 2.0 * g)
            if self.glitch >= 50 and random.random() < dt * 0.25 * g:
                self.goal = random.randrange(len(GOALS))
                self.goal_wait = 0.0
            if self.glitch >= 75:
                speed *= 1.0 + 0.8 * random.random()
            self.mood = self.sanity_stage

        if self.abstracted:
            # Visual/behavioral effect layered on the same live FlyBrain
            # outputs; this does not change the connectome itself.
            self.yaw += math.sin(self.age_days * 2.1 + len(self.name)) * dt * 0.7
            speed = max(abs(speed), 1.2) * 1.35
            self.mood = "ABSTRACTED"

        self.x += math.cos(self.yaw) * speed * dt
        self.z += math.sin(self.yaw) * speed * dt
        radius = math.hypot(self.x, self.z)
        if radius > STAGE_RADIUS - 0.45:
            self.x *= (STAGE_RADIUS - 0.45) / radius
            self.z *= (STAGE_RADIUS - 0.45) / radius
            self.yaw = math.atan2(-self.z, -self.x) + 0.45
            if not self.abstracted:
                self.mood = "found the stage edge"

        gx, gz = GOALS[self.goal][1:3]
        if math.hypot(self.x - gx, self.z - gz) < 1.05 and self.goal_wait > 2.0:
            self.completed_goal = self.goal
            self.goal = (self.goal + 1 + (sum(map(ord, self.name)) % 2)) % len(GOALS)
            self.goal_wait = 0.0
            if not self.abstracted:
                self.mood = "off to the next act"


class FlyBrainWorker(threading.Thread):
    """One real FlyBrain instance, batched across NUM_FLIES independent fly slots."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.inputs = {key: [0.0] * NUM_FLIES for key in
                       ("look_L", "look_R", "threat_L", "threat_R", "food")}
        self.messages: queue.SimpleQueue[str] = queue.SimpleQueue()
        self.outputs: queue.Queue[list[dict[str, int]]] = queue.Queue(maxsize=3)
        self.brain_view: queue.Queue[dict] = queue.Queue(maxsize=4)
        self.selected_fly = 0
        self.geometry = None

    def select_fly(self, index: int) -> None:
        with self.lock:
            self.selected_fly = max(0, min(NUM_FLIES - 1, index))

    def _publish_brain_view(self, data: dict) -> None:
        try:
            self.brain_view.put_nowait(data)
        except queue.Full:
            try:
                self.brain_view.get_nowait()
            except queue.Empty:
                pass
            try:
                self.brain_view.put_nowait(data)
            except queue.Full:
                pass

    def set_inputs(self, values: dict[str, list[float]]) -> None:
        with self.lock:
            self.inputs = {k: list(v) for k, v in values.items()}

    @staticmethod
    def _group(brain, group_name: str, cell_type: str, side: str):
        import numpy as np
        idx = brain.groups.get(group_name)
        if idx is None or len(idx) == 0:
            idx = brain.cells([cell_type], side=side)
        return np.asarray(idx, dtype=np.int64)

    @staticmethod
    def _count(fired, indices) -> int:
        import numpy as np
        if len(indices) == 0 or len(fired) == 0:
            return 0
        return int(np.isin(fired, indices).sum())

    def _publish(self, rows: list[dict[str, int]]) -> None:
        try:
            self.outputs.put_nowait(rows)
        except queue.Full:
            try:
                self.outputs.get_nowait()
            except queue.Empty:
                pass
            try:
                self.outputs.put_nowait(rows)
            except queue.Full:
                pass

    def run(self) -> None:
        try:
            import numpy as np
            from flybrain import FlyBrain

            self.messages.put("Loading FlyBrain. First run downloads about 260 MB; no API key needed.")
            brain = FlyBrain(device="auto", batch=NUM_FLIES, seed=64,
                             dt=BRAIN_DT, sensory_input=False)

            # Soma positions are recorded by FlyBrain in the MaleCNS data. We
            # display a fixed random sample for speed, not a fabricated brain.
            sample = np.array([], dtype=np.int64)
            lookup = np.full(brain.n, -1, dtype=np.int32)
            geometry = {"points": [], "located": 0, "total": int(brain.n),
                        "error": "Neuron position metadata is unavailable."}
            try:
                pos = getattr(brain, "positions", None)
                if pos is not None:
                    pos = np.asarray(pos, dtype=np.float32)
                    if pos.ndim == 2 and pos.shape == (brain.n, 3):
                        good = np.flatnonzero(np.isfinite(pos).all(axis=1))
                        if len(good):
                            rng = np.random.default_rng(73)
                            sample = np.sort(rng.choice(good, size=min(3000, len(good)), replace=False))
                            xyz = pos[sample].copy()
                            lo, hi = np.percentile(xyz, [1, 99], axis=0)
                            xyz = (xyz - (lo + hi) / 2) / max(float(np.max(hi - lo)), 1.0)
                            lookup[sample] = np.arange(len(sample), dtype=np.int32)
                            geometry = {"points": xyz.tolist(), "located": int(len(good)),
                                        "total": int(brain.n), "error": ""}
            except Exception as exc:
                geometry["error"] = "Cannot display neuron positions: " + str(exc)
            with self.lock:
                self.geometry = geometry
            sensors = {
                "look_L": brain.cells(["LC10a"], side="L"),
                "look_R": brain.cells(["LC10a"], side="R"),
                "threat_L": brain.cells(["LC4", "LPLC2"], side="L"),
                "threat_R": brain.cells(["LC4", "LPLC2"], side="R"),
                "food": brain.cells(["ORN_DM1", "ORN_DM2"], side="L"),
            }
            motors = {
                "steer_L": self._group(brain, "steer_L", "DNa02", "L"),
                "steer_R": self._group(brain, "steer_R", "DNa02", "R"),
                "forward_L": self._group(brain, "forward_L", "DNg100", "L"),
                "forward_R": self._group(brain, "forward_R", "DNg100", "R"),
                "escape_L": self._group(brain, "escape_L", "DNp01", "L"),
                "escape_R": self._group(brain, "escape_R", "DNp01", "R"),
                "backward_L": self._group(brain, "backward_L", "MDN", "L"),
                "backward_R": self._group(brain, "backward_R", "MDN", "R"),
            }
            self.messages.put("FLYBRAIN READY: six flies are on stage. Watch them explore.")
            active = np.zeros(len(sample), dtype=bool)
            last_publish = time.monotonic()
            last_focus = -1
            spikes_in_window = 0
            steps_in_window = 0

            while not self.stop_event.is_set():
                started = time.perf_counter()
                with self.lock:
                    inputs = {k: np.asarray(v, dtype=np.float32) for k, v in self.inputs.items()}
                    focus = self.selected_fly
                if focus != last_focus:
                    active.fill(False)
                    spikes_in_window = 0
                    steps_in_window = 0
                    last_focus = focus
                injections = [(idx, inputs[name] * 0.8) for name, idx in sensors.items()
                              if len(idx) and np.any(inputs[name] > 0)]
                fired = brain.step(inject=injections)
                rows = [{name: self._count(spikes, idx) for name, idx in motors.items()}
                        for spikes in fired]
                self._publish(rows)

                # Highlight only sampled neurons that actually fired in the
                # selected fly during this update window; the total is unsampled.
                selected_spikes = np.asarray(fired[focus], dtype=np.int64)
                spikes_in_window += len(selected_spikes)
                steps_in_window += 1
                if len(sample) and len(selected_spikes):
                    mapped = lookup[selected_spikes]
                    active[mapped[mapped >= 0]] = True
                if time.monotonic() - last_publish >= 0.12:
                    self._publish_brain_view({"fly": focus, "active": np.flatnonzero(active).tolist(),
                                              "spikes": int(spikes_in_window),
                                              "steps": int(steps_in_window)})
                    active.fill(False)
                    spikes_in_window = 0
                    steps_in_window = 0
                    last_publish = time.monotonic()
                time.sleep(max(0.0, BRAIN_DT - (time.perf_counter() - started)))
        except Exception as exc:
            self.messages.put("FlyBrain could not start: " + str(exc) +
                               " | Install with: python -m pip install flybrain")


GOAL_KIND = {g[0]: g[4] for g in GOALS}

# Past-tense lines read correctly for one fly or a whole party.
KIND_LINES = {
    "stage": ["{who} climbed up to {place} and the crowd cheered.",
              "{who} took center stage at {place}."],
    "food": ["{who} followed a sweet smell to {place}.",
             "{who} shared a snack at {place}."],
    "play": ["{who} tried their luck at {place}.",
             "{who} played a round at {place}."],
    "gate": ["{who} slipped through {place}, curious what lay beyond.",
             "{who} peeked through {place} and giggled."],
    "water": ["{who} skimmed over {place}, watching the ripples.",
              "{who} drifted across {place} under the lights."],
    "wheel": ["{who} rode {place} and watched the carnival glow below.",
              "{who} climbed aboard {place} for a view of everything."],
    "tower": ["{who} circled {place} just as the clock chimed.",
              "{who} buzzed around {place} to check the time."],
}


def join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


THEMES = {
    "snack": {
        "titles": ["The Great Snack Hunt", "Sweet Tooth Tour", "A Nibble Across the Fairground"],
        "weights": {"food": 4, "play": 1, "water": 1, "stage": 1},
        "intros": ["{who} smelled something delicious on the breeze. First stop: {first}.",
                   "{who} had a craving. The hunt begins at {first}!"],
        "finales": ["{who} finished the snack run happy and full.",
                    "{who} licked the last crumbs away and buzzed home."],
    },
    "thrill": {
        "titles": ["Thrill Seekers", "Up, Up and Away", "Midway Mayhem"],
        "weights": {"wheel": 4, "play": 2, "tower": 1, "stage": 1},
        "intros": ["{who} wanted a little excitement tonight. First stop: {first}!",
                   "{who} buzzed with nerves and joy. Let's start at {first}."],
        "finales": ["{who} came down from the excitement grinning.",
                    "{who} agreed it was the best thrill of the night."],
    },
    "stroll": {
        "titles": ["A Moonlit Stroll", "The Quiet Way Round", "Lantern Light Meander"],
        "weights": {"water": 3, "gate": 1, "tower": 1, "play": 1},
        "intros": ["{who} decided on a slow walk under the lanterns, starting at {first}.",
                   "The night was calm, so {who} wandered off to {first}."],
        "finales": ["{who} drifted home, calm and sleepy.",
                    "{who} watched the lights one last time and called it a night."],
    },
    "showtime": {
        "titles": ["Showtime!", "Curtain Up", "The Midway Revue"],
        "weights": {"stage": 4, "play": 1, "food": 1},
        "intros": ["The lights came up and {who} headed for {first}!",
                   "{who} felt like performing. The first act is at {first}."],
        "finales": ["{who} took a final bow to a cheering fairground.",
                    "{who} left the stage to a round of applause."],
    },
    "mystery": {
        "titles": ["The Mystery of the Midway", "Strange Lights", "Where Did the Lanterns Go?"],
        "weights": {"gate": 3, "tower": 2, "water": 1},
        "intros": ["Something felt odd tonight, so {who} went to investigate {first}.",
                   "{who} followed a flicker of light toward {first}."],
        "finales": ["{who} never quite solved the mystery, but it was a good night anyway.",
                    "{who} decided the strange lights were friendly after all."],
    },
}
CONNECTORS = ["Next, ", "Then ", "After that, ", "Soon after, "]


def weighted_pick(rng: random.Random, items: list, weights: list[float]):
    """Pick one item with probability proportional to its weight."""
    total = sum(weights)
    if total <= 0:
        return rng.choice(items)
    cut = rng.random() * total
    for item, weight in zip(items, weights):
        cut -= weight
        if cut <= 0:
            return item
    return items[-1]


class RingmasterAI(threading.Thread):
    """Built-in adventure guide that plans multi-stop adventures for a party of flies.

    This is a procedural planner that lives in this file, not a language model:
    it needs no downloads, network or API keys. It chooses a theme, a party that
    favors flies who have become friends, and a route that avoids recent repeats,
    then writes the story lines. Unraveling flies (high game glitch) get worked
    into the story. The flies themselves are driven by their brains; this guide
    only chooses where the story sends them.
    """

    def __init__(self):
        super().__init__(daemon=True)
        self.stop_event = threading.Event()
        self.requests = queue.Queue(maxsize=1)
        self.results = queue.Queue(maxsize=3)
        self.rng = random.Random()
        # Short memory so adventures feel varied.
        self.recent_goals: list[str] = []
        self.recent_themes: list[str] = []
        self.recent_leaders: list[str] = []

    def request(self, context):
        try:
            self.requests.put_nowait(context)
            return True
        except queue.Full:
            return False

    def _remember(self, store: list, values: list, keep: int) -> None:
        store.extend(values)
        del store[:-keep]

    def plan(self, state: dict) -> dict:
        rng = self.rng
        flies = state["flies"]
        days = {tuple(sorted((a, b))): d for a, b, d in state.get("pairs", [])}

        def bond(a: str, b: str) -> float:
            return days.get(tuple(sorted((a, b))), 0.0)

        # Leader: someone clear-headed who has not led recently.
        calm = [f for f in flies if f.get("glitch", 0) < 50] or flies
        leader = weighted_pick(rng, calm, [0.25 if f["name"] in self.recent_leaders else 1.0 for f in calm])
        party = [leader]
        pool = [f for f in flies if f is not leader]
        size = min(len(flies), rng.choice([1, 2, 2, 3]))
        while len(party) < size and pool:
            # Friends are favored; an unraveling fly is a fun wild card.
            weights = [1.0 + min(6.0, max(bond(leader["name"], f["name"]), 0.0))
                       + (0.8 if f.get("glitch", 0) >= 50 else 0.0) for f in pool]
            pick = weighted_pick(rng, pool, weights)
            party.append(pick)
            pool.remove(pick)
        names = [f["name"] for f in party]
        who = join_names(names)
        pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1:] if bond(a, b) >= 1.0]
        strange = any(f.get("glitch", 0) >= 50 for f in party)

        # Theme: avoid repeating the last one; strange parties lean toward mystery,
        # friends toward strolls and shows.
        keys = list(THEMES)
        theme_weights = []
        for key in keys:
            w = 0.2 if key in self.recent_themes else 1.0
            if strange and key == "mystery":
                w *= 3.0
            if pairs and key in ("stroll", "showtime"):
                w *= 2.0
            theme_weights.append(w)
        theme_key = weighted_pick(rng, keys, theme_weights)
        theme = THEMES[theme_key]

        # Route: weighted by theme, discouraging recently visited stops, then ordered
        # so each stop is the nearest unvisited one from the leader.
        candidates = list(GOALS)
        picks = []
        for _ in range(rng.choice([3, 3, 4])):
            weights = [theme["weights"].get(g[4], 0.3) * (0.25 if g[0] in self.recent_goals else 1.0)
                       for g in candidates]
            choice = weighted_pick(rng, candidates, weights)
            picks.append(choice)
            candidates.remove(choice)
        route, pos = [], (leader["x"], leader["z"])
        while picks:
            nxt = min(picks, key=lambda g: math.hypot(g[1] - pos[0], g[2] - pos[1]))
            picks.remove(nxt)
            route.append(nxt)
            pos = (nxt[1], nxt[2])

        # Story lines, with quirks drawn from the flies' actual state.
        wild = next((f["name"] for f in party[1:] if f.get("glitch", 0) >= 50), None)
        twitchy = leader.get("glitch", 0) >= 25
        lines = []
        for k, goal in enumerate(route):
            base = rng.choice(KIND_LINES.get(goal[4], KIND_LINES["play"])).format(
                who=who, place="the " + goal[0].title())
            line = (rng.choice(CONNECTORS) if k else "") + base
            if k == 0 and twitchy:
                line += f" {leader['name']} could not stop twitching with excitement."
            if k == 1 and wild:
                line += f" {wild} wandered off a little and had to be called back."
            lines.append(line)
        finale = rng.choice(theme["finales"]).format(who=who)
        if pairs:
            a, b = max(pairs, key=lambda p: bond(*p))
            finale += (" They agreed it was their best adventure yet." if len(names) == 2
                       else f" {a} and {b} agreed it was their best adventure yet.")

        self._remember(self.recent_goals, [g[0] for g in route], 8)
        self._remember(self.recent_themes, [theme_key], 2)
        self._remember(self.recent_leaders, [leader["name"]], 3)
        return {"title": rng.choice(theme["titles"]).upper(), "party": names,
                "stops": [g[0] for g in route],
                "intro": rng.choice(theme["intros"]).format(who=who, first="the " + route[0][0].title()),
                "lines": lines, "finale": finale, "mode": "BUILT-IN GUIDE"}

    def run(self):
        while not self.stop_event.is_set():
            try:
                state = self.requests.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                result = self.plan(state)
                result["epoch"] = state["epoch"]
                self.results.put_nowait(result)
            except Exception:
                pass  # the host asks again after its timeout


class Circus:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Fly Carnival | 3D fly.ai simulation")
        self.root.geometry("1500x780")
        self.root.minsize(980, 600)
        self.root.configure(bg="#11091f")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.view_fly = tk.StringVar(value=SKINS[0][0])
        self.brain_angle = 0.0
        self.brain_tilt = 0.2
        self.brain_drag = None
        self.brain_geometry = None
        self.brain_lit = {}
        self.brain_latest = None
        self.brain_last_draw = 0.0
        content = tk.Frame(self.root, bg="#11091f")
        content.pack(fill="both", expand=True)
        brain_panel = tk.Frame(content, width=400, bg="#120d23", padx=12, pady=12)
        brain_panel.pack(side="right", fill="y")
        brain_panel.pack_propagate(False)
        tk.Label(brain_panel, text="THE FLY BRAIN", bg="#120d23", fg="#f9eaff",
                 font=("Segoe UI", 16, "bold"), anchor="w").pack(fill="x")
        tk.Label(brain_panel, text="Real neuron locations  •  live activity", bg="#120d23",
                 fg="#b9a9cf", font=("Segoe UI", 10), anchor="w").pack(fill="x", pady=(1, 6))
        selector = tk.Frame(brain_panel, bg="#120d23")
        selector.pack(fill="x")
        tk.Label(selector, text="Fly:", bg="#120d23", fg="#f9eaff",
                 font=("Segoe UI", 10)).pack(side="left")
        self.brain_menu = tk.OptionMenu(selector, self.view_fly, *(s[0] for s in SKINS),
                                        command=self.select_brain_fly)
        self.brain_menu.config(bg="#3c2857", fg="white", activebackground="#69498b",
                               activeforeground="white", relief="flat", highlightthickness=0,
                               font=("Segoe UI", 10), width=12)
        self.brain_menu["menu"].config(bg="#241735", fg="white")
        self.brain_menu.pack(side="left", padx=8)
        tk.Label(selector, text="Drag to rotate", bg="#120d23", fg="#a894be",
                 font=("Segoe UI", 9)).pack(side="right")
        glitch_row = tk.Frame(brain_panel, bg="#120d23")
        glitch_row.pack(fill="x", pady=(6, 0))
        self.glitch_text = tk.StringVar(value="Glitch: 0%")
        tk.Label(glitch_row, textvariable=self.glitch_text, bg="#120d23", fg="#ffcc8f",
                 font=("Segoe UI", 10, "bold"), anchor="w").pack(side="left", fill="x", expand=True)
        tk.Button(glitch_row, text="ABSTRACT FLY", command=self.abstract_selected,
                  bg="#8f2b62", fg="white", activebackground="#bf3c82", activeforeground="white",
                  relief="flat", font=("Segoe UI", 9, "bold"), padx=8).pack(side="right")
        fly_row = tk.Frame(brain_panel, bg="#120d23")
        fly_row.pack(fill="x", pady=(6, 0))
        self.fly_count_text = tk.StringVar(value="")
        tk.Label(fly_row, textvariable=self.fly_count_text, bg="#120d23", fg="#b9a9cf",
                 font=("Segoe UI", 9), anchor="w").pack(side="left", fill="x", expand=True)
        tk.Button(fly_row, text="DELETE FLY", command=self.delete_selected,
                  bg="#7a2336", fg="white", activebackground="#a63049", activeforeground="white",
                  relief="flat", font=("Segoe UI", 9, "bold"), padx=8).pack(side="right", padx=(6, 0))
        tk.Button(fly_row, text="+ ADD FLY", command=self.open_add_dialog,
                  bg="#2f8f62", fg="white", activebackground="#3fb57f", activeforeground="white",
                  relief="flat", font=("Segoe UI", 9, "bold"), padx=8).pack(side="right")
        self.brain_canvas = tk.Canvas(brain_panel, bg="#0a0917", highlightthickness=1,
                                      highlightbackground="#674985")
        self.brain_canvas.pack(fill="both", expand=True, pady=(9, 6))
        self.brain_canvas.bind("<ButtonPress-1>", self.start_brain_drag)
        self.brain_canvas.bind("<B1-Motion>", self.drag_brain)
        self.brain_canvas.bind("<ButtonRelease-1>", self.end_brain_drag)
        self.brain_caption = tk.StringVar(value="Waiting for FlyBrain data...")
        tk.Label(brain_panel, textvariable=self.brain_caption, bg="#120d23", fg="#c4b3d9",
                 justify="left", anchor="w", wraplength=370, font=("Segoe UI", 9)).pack(fill="x")
        self.canvas = tk.Canvas(content, bg="#180d2b", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.toolbar = tk.Frame(self.root, bg="#11091f", padx=8, pady=7)
        self.toolbar.pack(fill="x", side="bottom")
        self.status = tk.StringVar(value="Starting the real FlyBrain connectome…")
        self.status_label = tk.Label(self.toolbar, textvariable=self.status, bg="#11091f",
                                     fg="#e8dcff", anchor="w", font=("Segoe UI", 9),
                                     wraplength=590, justify="left")
        self.status_label.pack(side="left", fill="x", expand=True)

        self.paused = False
        self.brain_live = False
        self.speed = 1
        self.sim_days = 0.0
        self.last_tick = time.time()
        self.camera_angle = 0.0
        self.last_event = -1
        self.event_title = "WELCOME TO THE BIG TOP"
        self.event_text = "The ringmaster is preparing the first adventure."
        self.host_mode = "STARTING HOST"
        self.quest = None  # the adventure in progress, or None
        self.host_epoch = 0
        self.host_pending = False
        self.host_next = time.monotonic() + 1.5
        self.abstraction_seen = set()
        self.abstraction_notice = ""
        self.abstraction_notice_until = 0.0
        self.camera_mode = "MAP"
        self.camera_zoom = 1.0
        self.zoom_text = tk.StringVar(value="1.0×")
        self.friend_days: dict[tuple[str, str], float] = {}
        self.add_dialog = None
        self.flies = self._default_flies()

        self.brain = FlyBrainWorker()
        self.brain.start()
        self.host = RingmasterAI()
        self.host.start()
        self._buttons()
        self._camera_controls()
        self.refresh_fly_menus()
        self.canvas.bind("<MouseWheel>", self.on_camera_wheel)
        self.canvas.bind("<Button-4>", self.on_camera_wheel)
        self.canvas.bind("<Button-5>", self.on_camera_wheel)
        self.canvas.bind("<Button-1>", self.click_fly)
        self.root.bind("<Escape>", lambda _e: self.close())
        self.root.after(25, self.tick)

    # ---- cast management: add / delete flies ------------------------------
    def _default_flies(self) -> list[Fly]:
        flies = []
        for i, (name, color, pale, costume) in enumerate(SKINS):
            a = i * 2 * math.pi / NUM_FLIES
            flies.append(Fly(name, color, pale, costume,
                             math.cos(a) * 5.2, math.sin(a) * 5.2,
                             a + math.pi, i % len(GOALS), {}, slot=i))
        return flies

    def selected_fly(self) -> Fly | None:
        name = self.view_fly.get()
        return next((f for f in self.flies if f.name == name), None)

    def free_slot(self) -> int | None:
        used = {f.slot for f in self.flies}
        return next((s for s in range(NUM_FLIES) if s not in used), None)

    def refresh_fly_menus(self) -> None:
        """Rebuild both fly dropdowns from the current cast."""
        names = [f.name for f in self.flies]
        for menu_widget, callback in ((self.brain_menu, self.select_brain_fly),
                                      (self.watch_menu, self.select_camera_fly)):
            menu = menu_widget["menu"]
            menu.delete(0, "end")
            for name in names:
                menu.add_command(label=name,
                                 command=lambda n=name, cb=callback: (self.view_fly.set(n), cb(n)))
            if not names:
                menu.add_command(label=NO_FLY, state="disabled")
        self.fly_count_text.set(f"Flies on stage: {len(self.flies)}/{NUM_FLIES}")

    def _suggest_name(self) -> str:
        taken = {f.name.casefold() for f in self.flies}
        for name in EXTRA_NAMES:
            if name.casefold() not in taken:
                return name
        i = 1
        while f"Fly {i}".casefold() in taken:
            i += 1
        return f"Fly {i}"

    def delete_selected(self) -> None:
        fly = self.selected_fly()
        if fly is None:
            self.status.set("No fly selected to delete.")
            return
        index = self.flies.index(fly)
        self.flies.remove(fly)
        # Forget everything that referred to this fly by name.
        self.friend_days = {k: v for k, v in self.friend_days.items() if fly.name not in k}
        self.abstraction_seen.discard(fly.name)
        self._drop_from_quest(fly.name)
        self.host_epoch += 1          # drop any in-flight ringmaster result
        self.host_pending = False
        self.host_next = min(self.host_next, time.monotonic() + 4.0)
        if self.flies:
            nxt = self.flies[min(index, len(self.flies) - 1)]
            self.view_fly.set(nxt.name)
            self.select_brain_fly(nxt.name)
            self.event_title = "A FLY LEAVES THE CARNIVAL"
            self.event_text = f"{fly.name} has left the big top. {nxt.name} is now in the spotlight."
        else:
            self.view_fly.set(NO_FLY)
            self.set_camera("MAP")
            self.event_title = "THE STAGE IS EMPTY"
            self.event_text = "Every fly has left. Press + ADD FLY to bring one in."
        self.refresh_fly_menus()
        self.update_glitch_ui()
        self.status.set(f"Deleted {fly.name}. Its brain slot is free for a new fly.")

    def open_add_dialog(self) -> None:
        if self.free_slot() is None:
            self.status.set(f"The stage is full: {NUM_FLIES} flies, one per brain slot. Delete a fly first.")
            return
        existing = self.add_dialog
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
        bg, fg = "#120d23", "#f9eaff"
        label_font = ("Segoe UI", 10, "bold")
        dlg = tk.Toplevel(self.root)
        self.add_dialog = dlg
        dlg.title("Add a fly")
        dlg.configure(bg=bg, padx=18, pady=16)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        name_var = tk.StringVar(value=self._suggest_name())
        costume_var = tk.StringVar(value=COSTUMES[0][0])
        color_var = tk.StringVar(value=random.choice(PALETTE))

        tk.Label(dlg, text="Name", bg=bg, fg=fg, font=label_font).grid(row=0, column=0, sticky="w", pady=4)
        entry = tk.Entry(dlg, textvariable=name_var, width=20, bg="#2a1b3f", fg="white",
                         insertbackground="white", relief="flat", font=("Segoe UI", 11))
        entry.grid(row=0, column=1, sticky="w", padx=(10, 0), pady=4, ipady=3)

        tk.Label(dlg, text="Costume", bg=bg, fg=fg, font=label_font).grid(row=1, column=0, sticky="w", pady=4)
        costume_menu = tk.OptionMenu(dlg, costume_var, *(label for label, _ in COSTUMES))
        costume_menu.config(bg="#3c2857", fg="white", activebackground="#69498b",
                            activeforeground="white", relief="flat", highlightthickness=0,
                            font=("Segoe UI", 10), width=14)
        costume_menu["menu"].config(bg="#241735", fg="white")
        costume_menu.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=4)

        tk.Label(dlg, text="Color", bg=bg, fg=fg, font=label_font).grid(row=2, column=0, sticky="nw", pady=8)
        swatch_frame = tk.Frame(dlg, bg=bg)
        swatch_frame.grid(row=2, column=1, sticky="w", padx=(10, 0), pady=4)
        swatches: dict[str, tk.Label] = {}

        def choose(color: str) -> None:
            color_var.set(color)
            for c, widget in swatches.items():
                widget.config(highlightbackground="white" if c == color else bg)

        for k, color in enumerate(PALETTE):
            swatch = tk.Label(swatch_frame, bg=color, width=3, height=1, cursor="hand2",
                              highlightthickness=3, highlightbackground=bg)
            swatch.grid(row=k // 5, column=k % 5, padx=2, pady=2)
            swatch.bind("<Button-1>", lambda _e, c=color: choose(c))
            swatches[color] = swatch
        choose(color_var.get())

        error = tk.Label(dlg, text="", bg=bg, fg="#ff9ab8", font=("Segoe UI", 9))
        error.grid(row=3, column=0, columnspan=2, sticky="w")

        def submit(_event=None) -> None:
            name = " ".join(name_var.get().split())[:14]
            if not name or name == NO_FLY:
                error.config(text="Give your fly a name.")
                return
            if any(f.name.casefold() == name.casefold() for f in self.flies):
                error.config(text=f"There is already a fly called {name}.")
                return
            if self.free_slot() is None:
                error.config(text="The stage is full.")
                return
            costume = dict(COSTUMES)[costume_var.get()]
            dlg.destroy()
            self.add_fly(name, color_var.get(), costume)

        buttons = tk.Frame(dlg, bg=bg)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        tk.Button(buttons, text="Cancel", command=dlg.destroy, bg="#34204d", fg="white",
                  activebackground="#56367a", activeforeground="white", relief="flat",
                  padx=10).pack(side="right", padx=(6, 0))
        tk.Button(buttons, text="ADD & WATCH", command=submit, bg="#2f8f62", fg="white",
                  activebackground="#3fb57f", activeforeground="white", relief="flat",
                  font=("Segoe UI", 9, "bold"), padx=10).pack(side="right")
        dlg.bind("<Return>", submit)
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        entry.focus_set()
        entry.select_range(0, "end")

    def add_fly(self, name: str, color: str, costume: str) -> None:
        slot = self.free_slot()
        if slot is None:
            self.status.set(f"The stage is full: {NUM_FLIES} flies. Delete a fly first.")
            return
        # Spawn on the starting ring, as far from the other flies as possible.
        best = None
        for _ in range(24):
            a = random.random() * math.tau
            px, pz = math.cos(a) * 5.2, math.sin(a) * 5.2
            gap = min((math.hypot(px - f.x, pz - f.z) for f in self.flies), default=99.0)
            if best is None or gap > best[0]:
                best = (gap, a, px, pz)
        _, a, px, pz = best
        fly = Fly(name, color, mix(color, "#ffffff", 0.82), costume, px, pz, a + math.pi,
                  random.randrange(len(GOALS)), {}, age_days=self.sim_days, slot=slot)
        self.flies.append(fly)
        self.refresh_fly_menus()
        self.select_camera_fly(name)  # select it, show its brain, and follow it
        self.event_title = "A NEW FLY ARRIVES"
        self.event_text = f"{name} joins the carnival! The ringmaster is thinking up an act."
        self.host_next = min(self.host_next, time.monotonic() + 6.0)
        self.update_glitch_ui()
        self.status.set(f"Added {name} (brain slot {slot + 1} of {NUM_FLIES}). Now following it.")

    def select_brain_fly(self, name: str) -> None:
        fly = next((f for f in self.flies if f.name == name), None)
        self.brain_lit.clear()
        self.brain_latest = None
        if hasattr(self, "brain"):
            if fly is not None:
                self.brain.select_fly(fly.slot)
            # Drop queued updates that belong to the previously selected slot.
            while True:
                try:
                    self.brain.brain_view.get_nowait()
                except queue.Empty:
                    break
        self.brain_last_draw = 0.0

    def start_brain_drag(self, event) -> None:
        self.brain_drag = (event.x, event.y)

    def drag_brain(self, event) -> None:
        if self.brain_drag is not None:
            x, y = self.brain_drag
            self.brain_angle += (event.x - x) * 0.012
            self.brain_tilt = clamp(self.brain_tilt + (event.y - y) * 0.012, -1.3, 1.3)
            self.brain_drag = (event.x, event.y)
            self.brain_last_draw = 0.0

    def end_brain_drag(self, _event) -> None:
        self.brain_drag = None

    def update_brain_view(self) -> None:
        # Read geometry and live spike IDs from the simulation worker only;
        # never create invented neuron locations or invented activity.
        with self.brain.lock:
            if self.brain_geometry is None and self.brain.geometry is not None:
                self.brain_geometry = self.brain.geometry
        selected = self.selected_fly()
        chosen = selected.slot if selected else -1
        while True:
            try:
                update = self.brain.brain_view.get_nowait()
            except queue.Empty:
                break
            if update["fly"] == chosen:
                now = time.monotonic()
                for index in update["active"]:
                    self.brain_lit[index] = now
                self.brain_latest = update
        now = time.monotonic()
        if now - self.brain_last_draw < 0.15:
            return
        self.brain_last_draw = now
        self.brain_lit = {i: t for i, t in self.brain_lit.items() if now - t < 0.45}
        c = self.brain_canvas
        w, h = max(c.winfo_width(), 1), max(c.winfo_height(), 1)
        c.delete("all")
        if selected is None:
            c.create_text(w / 2, h / 2, text="No fly selected.\nPress + ADD FLY to bring one in.",
                          fill="#cdb9e0", width=max(120, w - 30), font=("Segoe UI", 12), justify="center")
            self.brain_caption.set("The stage is empty.")
            return
        if not self.brain_geometry:
            c.create_text(w / 2, h / 2, text="Loading the fly brain...", fill="#cdb9e0",
                          width=max(120, w - 30), font=("Segoe UI", 12), justify="center")
            return
        geometry = self.brain_geometry
        points = geometry["points"]
        if not points:
            c.create_text(w / 2, h / 2, text=geometry["error"], fill="#ffd0de",
                          width=max(120, w - 30), font=("Segoe UI", 11), justify="center")
            self.brain_caption.set("No position metadata available. The fly simulation can still run.")
            return

        if self.brain_drag is None:
            self.brain_angle += 0.015
        a, tilt = self.brain_angle, self.brain_tilt
        ca, sa, ct, st = math.cos(a), math.sin(a), math.cos(tilt), math.sin(tilt)
        scale = min(w * 0.9, h * 0.72)
        cx, cy = w * 0.5, h * 0.48
        projected = []
        for i, (x, y, z) in enumerate(points):
            rx, rz = x * ca - z * sa, x * sa + z * ca
            ry, depth = y * ct - rz * st, y * st + rz * ct
            sx, sy = cx + rx * scale, cy - ry * scale
            if 2 < sx < w - 2 and 22 < sy < h - 30:
                projected.append((depth, i, sx, sy))
        for depth, index, sx, sy in sorted(projected):
            age = now - self.brain_lit.get(index, -999.0)
            if age < 0.45:
                color = "#fff0a4" if age < 0.18 else "#ff984f"
                radius = 2.3 if age < 0.18 else 1.7
            else:
                color = "#466c82" if depth < 0 else "#78bfd0"
                radius = 1.0
            c.create_oval(sx - radius, sy - radius, sx + radius, sy + radius,
                          fill=color, outline="")
        c.create_text(12, 12, anchor="nw", text=self.view_fly.get().upper(),
                      fill="#f4eaff", font=("Segoe UI", 11, "bold"))
        c.create_text(12, h - 12, anchor="sw", text="●", fill="#78bfd0", font=("Segoe UI", 10))
        c.create_text(27, h - 12, anchor="sw", text="neuron", fill="#d5c9e6", font=("Segoe UI", 9))
        c.create_text(85, h - 12, anchor="sw", text="●", fill="#ffb268", font=("Segoe UI", 10))
        c.create_text(100, h - 12, anchor="sw", text="fired recently", fill="#d5c9e6", font=("Segoe UI", 9))
        update = self.brain_latest
        recent = (f"  |  {update['spikes']:,} spikes across {update['steps']} steps"
                  if update else "  |  waiting for spikes")
        self.brain_caption.set(
            f"Showing {len(points):,} sampled neuron locations from {geometry['located']:,} located "
            f"of {geometry['total']:,} total. Yellow/orange dots fired in this fly's simulation.{recent}\n"
            "Each fly has the same connectome wiring but its own neural activity."
        )

    def request_adventure(self) -> None:
        # Cancel any adventure in progress and plan a new one right away.
        self.quest = None
        self.host_epoch += 1
        self.host_pending = False
        self.host_next = 0.0
        self.status.set("The ringmaster is planning a new adventure.")

    def set_camera(self, mode: str) -> None:
        self.camera_mode = mode
        self.camera_zoom = 5.0 if mode == "FOLLOW" else 1.0
        self.zoom_text.set(f"{self.camera_zoom:.1f}×")
        self.camera_button.config(text="Camera: " + self.camera_mode)

    def toggle_camera(self) -> None:
        self.set_camera("FOLLOW" if self.camera_mode == "MAP" else "MAP")

    def select_camera_fly(self, name: str) -> None:
        self.view_fly.set(name)
        self.select_brain_fly(name)
        self.set_camera("FOLLOW")

    def adjust_camera_zoom(self, factor: float) -> None:
        self.camera_zoom = clamp(self.camera_zoom * factor, 0.75, 16.0)
        self.zoom_text.set(f"{self.camera_zoom:.1f}×")

    def on_camera_wheel(self, event) -> str:
        # Windows/macOS use delta; X11/Linux often uses button 4 and 5.
        up = getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0
        down = getattr(event, "num", None) == 5 or getattr(event, "delta", 0) < 0
        if up:
            self.adjust_camera_zoom(1.25)
        elif down:
            self.adjust_camera_zoom(1 / 1.25)
        return "break"

    def click_fly(self, event) -> None:
        # Pick the nearest visible fly, not the (possibly overlapping) text.
        w, h = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        choices = []
        for fly in self.flies:
            x, y, _ = self._project((fly.x, 1.0, fly.z), w, h)
            choices.append((math.hypot(event.x - x, event.y - y), fly.name))
        if choices:
            distance, name = min(choices)
            if distance <= 32:
                self.select_camera_fly(name)

    def _camera_controls(self) -> None:
        # A dedicated strip above the scene avoids squeezing the bottom controls.
        bar = tk.Frame(self.canvas, bg="#241336", padx=7, pady=5,
                       highlightbackground="#75558f", highlightthickness=1)
        bar.place(x=14, y=72)
        tk.Label(bar, text="WATCH", bg="#241336", fg="#f5e6ff",
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 4))
        self.watch_menu = tk.OptionMenu(bar, self.view_fly, *(skin[0] for skin in SKINS),
                                        command=self.select_camera_fly)
        self.watch_menu.config(bg="#48305f", fg="white", activebackground="#69498b",
                               activeforeground="white", relief="flat", highlightthickness=0,
                               font=("Segoe UI", 9), width=9)
        self.watch_menu["menu"].config(bg="#241735", fg="white")
        self.watch_menu.pack(side="left", padx=3)
        button = {"bg": "#48305f", "fg": "white", "activebackground": "#69498b",
                  "activeforeground": "white", "relief": "flat", "font": ("Segoe UI", 10)}
        tk.Button(bar, text="Follow", command=lambda: self.set_camera("FOLLOW"),
                  **button).pack(side="left", padx=2)
        tk.Button(bar, text="−", command=lambda: self.adjust_camera_zoom(1 / 1.25),
                  width=2, **button).pack(side="left", padx=2)
        tk.Label(bar, textvariable=self.zoom_text, bg="#241336", fg="#f5e6ff",
                 font=("Segoe UI", 9, "bold"), width=5).pack(side="left")
        tk.Button(bar, text="+", command=lambda: self.adjust_camera_zoom(1.25),
                  width=2, **button).pack(side="left", padx=2)
        tk.Button(bar, text="Map", command=lambda: self.set_camera("MAP"),
                  **button).pack(side="left", padx=2)
        tk.Label(bar, text="Scroll to zoom", bg="#241336", fg="#c9b5dc",
                 font=("Segoe UI", 9)).pack(side="left", padx=(5, 0))

    def _buttons(self) -> None:
        self.camera_button = tk.Button(self.toolbar, text="Camera: MAP", command=self.toggle_camera,
                                       bg="#34204d", fg="white", relief="flat", padx=7)
        self.camera_button.pack(side="right", padx=2)
        tk.Button(self.toolbar, text="NEW QUEST", command=self.request_adventure,
                  bg="#9d3b78", fg="white", relief="flat", padx=7).pack(side="right", padx=2)
        self.pause_button = tk.Button(self.toolbar, text="Pause", command=self.toggle_pause,
                                      bg="#34204d", fg="white", activebackground="#56367a",
                                      activeforeground="white", relief="flat", padx=10)
        self.pause_button.pack(side="right", padx=2)
        tk.Button(self.toolbar, text="Desktop shortcut", command=self.make_shortcut,
                  bg="#2f6f8f", fg="white", activebackground="#3f8fb5", activeforeground="white",
                  relief="flat", padx=8).pack(side="right", padx=(2, 8))
        tk.Button(self.toolbar, text="Reset", command=self.reset, bg="#34204d", fg="white",
                  activebackground="#56367a", activeforeground="white", relief="flat", padx=10).pack(side="right", padx=2)
        tk.Button(self.toolbar, text="+1 MONTH", command=self.advance_month, bg="#633b82", fg="white",
                  activebackground="#80509f", activeforeground="white", relief="flat", padx=10).pack(side="right", padx=3)
        for speed in (100, 25, 1):
            tk.Button(self.toolbar, text=f"×{speed}", command=lambda s=speed: self.set_speed(s),
                      bg="#633b82" if speed == 1 else "#34204d", fg="white",
                      activebackground="#56367a", activeforeground="white", relief="flat", padx=8).pack(side="right", padx=2)

    def make_shortcut(self) -> None:
        ok, msg = create_desktop_shortcut(__file__, "Fly Carnival")
        (messagebox.showinfo if ok else messagebox.showerror)("Desktop shortcut", msg, parent=self.root)
        self.status.set(msg.splitlines()[0])

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.pause_button.config(text="Resume" if self.paused else "Pause")
        self.status.set("Simulation paused. FlyBrain keeps idling." if self.paused else "Live 3D carnival simulation.")

    def set_speed(self, speed: int) -> None:
        self.speed = speed
        self.status.set(f"Simulation speed ×{speed}. The connectome still runs at its real step rate.")

    def advance_month(self) -> None:
        self.sim_days += 30.0
        for fly in self.flies:
            fly.advance_glitch(30.0)
        self._process_events()
        self.status.set("Fast-forwarded one month. Watch the story ticker for what changed.")

    def reset(self) -> None:
        self.sim_days = 0.0
        self.last_event = -1
        self.friend_days.clear()
        self.abstraction_seen.clear()
        self.abstraction_notice = ""
        self.abstraction_notice_until = 0.0
        self.host_epoch += 1
        self.host_pending = False
        self.quest = None
        self.host_next = time.monotonic() + 1.0
        self.event_title, self.event_text = "WELCOME BACK", "The ringmaster is preparing a new adventure."
        if not self.flies:
            # An empty stage resets to the original cast.
            self.flies = self._default_flies()
            self.view_fly.set(self.flies[0].name)
            self.select_brain_fly(self.flies[0].name)
            self.refresh_fly_menus()
        count = len(self.flies)
        for i, fly in enumerate(self.flies):
            a = i * 2 * math.pi / count
            fly.x, fly.z = math.cos(a) * 5.2, math.sin(a) * 5.2
            fly.yaw, fly.goal, fly.goal_wait = a + math.pi, i % len(GOALS), 0.0
            fly.age_days, fly.abstracted, fly.mood = 0.0, False, "back on stage"
            fly.glitch, fly.completed_goal = 0.0, -1
        self.update_glitch_ui()
        self.status.set("Reset the stage. FlyBrain's neural state keeps running.")

    def _inputs_for_world(self) -> dict[str, list[float]]:
        values = {k: [0.0] * NUM_FLIES for k in ("look_L", "look_R", "threat_L", "threat_R", "food")}
        for fly in self.flies:
            i = fly.slot
            gx, gz = GOALS[fly.goal][1:3]
            target = math.atan2(gz - fly.z, gx - fly.x)
            error = angle_delta(target, fly.yaw)
            left, right = max(0.0, math.sin(error)), max(0.0, -math.sin(error))
            ahead = max(0.0, math.cos(error))
            values["look_L"][i] = 0.22 + 0.78 * max(left, ahead * 0.22)
            values["look_R"][i] = 0.22 + 0.78 * max(right, ahead * 0.22)

            radius = math.hypot(fly.x, fly.z)
            if radius > STAGE_RADIUS - 1.7:
                toward_center = angle_delta(math.atan2(-fly.z, -fly.x), fly.yaw)
                values["threat_L" if toward_center >= 0 else "threat_R"][i] = 0.9
            for other in self.flies:
                if other is fly:
                    continue
                dx, dz = other.x - fly.x, other.z - fly.z
                if math.hypot(dx, dz) < 1.0:
                    side = angle_delta(math.atan2(dz, dx), fly.yaw)
                    values["threat_L" if side >= 0 else "threat_R"][i] = 0.7
            if GOALS[fly.goal][4] == "food":
                values["food"][i] = clamp(1.0 - math.hypot(gx - fly.x, gz - fly.z) / 7.0, 0.0, 1.0)
        return values

    def _read_brain(self) -> None:
        while True:
            try:
                self.status.set(self.brain.messages.get_nowait())
            except queue.Empty:
                break
        latest = None
        while True:
            try:
                latest = self.brain.outputs.get_nowait()
            except queue.Empty:
                break
        if latest:
            self.brain_live = True
            for fly in self.flies:
                if fly.slot < len(latest):
                    fly.motor = latest[fly.slot]

    def abstract_selected(self) -> None:
        fly = next((item for item in self.flies if item.name == self.view_fly.get()), None)
        if fly is None:
            return
        fly.glitch = 100.0
        fly.abstracted = True
        self._process_events()
        self.set_camera("FOLLOW")
        self.status.set(f"{fly.name} abstracted. Reset restores the original form.")
        self.update_glitch_ui()

    def update_glitch_ui(self) -> None:
        fly = next((item for item in self.flies if item.name == self.view_fly.get()), None)
        if fly:
            text = "ABSTRACTED" if fly.abstracted else f"{fly.glitch:.0f}%"
            self.glitch_text.set(f"{fly.name}  |  {fly.sanity_stage}  |  GLITCH: {text}")
        else:
            self.glitch_text.set("No fly selected")

    def _process_events(self) -> None:
        newly_abstracted = []
        for fly in self.flies:
            fly.age_days = self.sim_days
            if fly.abstracted and fly.name not in self.abstraction_seen:
                self.abstraction_seen.add(fly.name)
                newly_abstracted.append(fly.name)
        if newly_abstracted:
            names = ", ".join(newly_abstracted)
            self.abstraction_notice = f"{names.upper()} ABSTRACTED!"
            self.abstraction_notice_until = time.monotonic() + 9.0
            self.event_title = "ABSTRACTION"
            self.event_text = f"{names} transformed into an abstracted form."
            for name in newly_abstracted:
                self._drop_from_quest(name)

    # ---- adventures -----------------------------------------------------------
    def quest_stop(self) -> int | None:
        q = self.quest
        return q["stops"][q["step"]] if q is not None else None

    def _quest_tag(self) -> str:
        q = self.quest
        if q is None:
            return ""
        return f"  [Quest: {', '.join(q['party'])} → stop {q['step'] + 1}/{len(q['stops'])}]"

    def _drop_from_quest(self, name: str) -> None:
        """A party member left or abstracted; end the quest if nobody is left."""
        q = self.quest
        if q is None or name not in q["party"]:
            return
        q["party"].remove(name)
        if not q["party"]:
            self.quest = None
            self.host_next = time.monotonic() + 6.0

    def _start_quest(self, plan: dict) -> None:
        by_name = {f.name: f for f in self.flies}
        party = [by_name[n] for n in plan["party"] if n in by_name and not by_name[n].abstracted]
        index = {g[0]: i for i, g in enumerate(GOALS)}
        stops = [index[s] for s in plan["stops"] if s in index]
        if not party or not stops:
            self.host_next = time.monotonic() + 2.0
            return
        lines = (plan["lines"] + [""] * len(stops))[:len(stops)]
        self.quest = {"title": plan["title"], "party": [f.name for f in party], "stops": stops,
                      "lines": lines, "finale": plan["finale"], "step": 0,
                      "step_day": self.sim_days, "last_pin": 0.0}
        for fly in party:
            fly.goal, fly.goal_wait, fly.completed_goal = stops[0], 0.0, -1
        self.event_title = plan["title"]
        self.event_text = plan["intro"] + self._quest_tag()
        self.host_next = time.monotonic() + 45.0

    def _advance_quest(self) -> None:
        q = self.quest
        if q is None:
            return
        by_name = {f.name: f for f in self.flies}
        party = [by_name[n] for n in q["party"] if n in by_name and not by_name[n].abstracted]
        if not party:
            self.quest = None
            self.host_next = time.monotonic() + 6.0
            return
        q["party"] = [f.name for f in party]
        leader, step = party[0], q["step"]
        stop = q["stops"][step]
        # The leader sets the pace; a stop is skipped if the leader loses the trail.
        if leader.completed_goal == stop or self.sim_days - q["step_day"] > 30.0:
            line = q["lines"][step]
            if step + 1 >= len(q["stops"]):
                self.event_title = "ADVENTURE COMPLETE!"
                self.event_text = f"{line}  {q['finale']}".strip()
                self.quest = None
                self.host_next = time.monotonic() + 8.0
                return
            q["step"], q["step_day"] = step + 1, self.sim_days
            nxt = q["stops"][q["step"]]
            for fly in party:
                fly.goal, fly.goal_wait, fly.completed_goal = nxt, 0.0, -1
            self.event_title = q["title"]
            self.event_text = f"{line}  Next: {GOALS[nxt][0].title()}.{self._quest_tag()}"
            return
        # Keep the party pointed at the current stop; unraveling flies drift off
        # and followers trail the leader.
        now = time.monotonic()
        if now - q["last_pin"] > 3.0:
            q["last_pin"] = now
            for fly in party:
                if fly.goal != stop:
                    fly.goal, fly.goal_wait = stop, 0.0

    def update_ringmaster(self) -> None:
        while True:
            try:
                result = self.host.results.get_nowait()
            except queue.Empty:
                break
            if result["epoch"] != self.host_epoch:
                continue
            self.host_pending = False
            self.host_mode = result["mode"]
            self._start_quest(result)
        self._advance_quest()
        now = time.monotonic()
        if self.host_pending and now >= self.host_next:
            self.host_pending = False  # the planner never answered; try again
        if (self.brain_live and not self.paused and not self.host_pending
                and self.quest is None and now >= self.host_next):
            remaining = [f for f in self.flies if not f.abstracted]
            if not remaining:
                self.host_next = now + 45.0
                if self.flies:
                    self.event_title = "THE CARNIVAL HAS ABSTRACTED"
                    self.event_text = "Every fly has transformed. Press Reset to start again."
                else:
                    self.event_title = "THE STAGE IS EMPTY"
                    self.event_text = "Press + ADD FLY to bring a fly into the carnival."
                return
            context = {"epoch": self.host_epoch, "day": round(self.sim_days, 1),
                       "flies": [{"name": f.name, "x": round(f.x, 1), "z": round(f.z, 1),
                                  "mood": f.mood, "glitch": round(f.glitch),
                                  "goal": GOALS[f.goal][0]} for f in remaining],
                       "pairs": [[a, b, round(d, 1)] for (a, b), d in self.friend_days.items()]}
            if self.host.request(context):
                self.host_pending = True
                self.host_next = now + 45.0

    def _build_quest_route(self, now: float) -> None:
        """Draw the adventure route on the map: dashed legs and ringed stops."""
        q = self.quest
        if q is None:
            return
        pts = [(GOALS[i][1], 0.14, GOALS[i][2]) for i in q["stops"]]
        for k, (a, b) in enumerate(zip(pts, pts[1:])):
            done = k < q["step"]
            self._line3(a, b, "#6b6480" if done else "#ffe27a", 2, None if done else (6, 5))
        for k, (px, _py, pz) in enumerate(pts):
            if k == q["step"]:
                pulse = 1.7 + 0.25 * math.sin(now * 4.0)
                self._ring(px, pz, 0.16, pulse, pulse, "#ffe27a", 24, 3)
            else:
                self._ring(px, pz, 0.16, 1.3, 1.3, "#8fffb5" if k < q["step"] else "#b9a9cf", 20, 2)

    def _update_friendships(self, dt_days: float) -> None:
        for i, a in enumerate(self.flies):
            for b in self.flies[i + 1:]:
                key = tuple(sorted((a.name, b.name)))
                if math.hypot(a.x - b.x, a.z - b.z) < 1.65:
                    self.friend_days[key] = self.friend_days.get(key, 0.0) + dt_days

    def tick(self) -> None:
        now = time.time()
        wall_dt = clamp(now - self.last_tick, 0.0, 0.1)
        self.last_tick = now
        self._read_brain()
        if not self.paused and self.brain_live:
            virtual_seconds = wall_dt * self.speed
            day_delta = virtual_seconds / SIM_SECONDS_PER_DAY
            # Small substeps keep the flies moving smoothly even when fast-forwarding.
            parts = max(1, min(40, math.ceil(virtual_seconds / 0.12)))
            sub_dt, sub_days = virtual_seconds / parts, day_delta / parts
            for _ in range(parts):
                for fly in self.flies:
                    fly.advance(sub_dt, sub_days)
                self._update_friendships(sub_days)
            self.sim_days += day_delta
            self._process_events()
            self.brain.set_inputs(self._inputs_for_world())
        self.update_ringmaster()
        self.update_glitch_ui()
        self.draw()
        self.update_brain_view()
        self.root.after(25, self.tick)

    # ---- 3D projection and painter's-order drawing -----------------------
    def _project(self, p: tuple[float, float, float], w: int, h: int) -> tuple[float, float, float]:
        x, y, z = p
        if self.camera_mode == "FOLLOW":
            focus = self.selected_fly() or (self.flies[0] if self.flies else None)
            if focus is not None:
                x, z = x - focus.x, z - focus.z
        a = self.camera_angle
        rx = x * math.cos(a) - z * math.sin(a)
        rz = x * math.sin(a) + z * math.cos(a)
        # Orthographic isometric camera keeps the whole giant park on screen;
        # follow mode magnifies the selected fly without WASD controls.
        scale = min(w, h) * 0.013 * self.camera_zoom
        sx = w * 0.5 + rx * scale
        sy = h * 0.56 - (rz * 0.48 + y) * scale
        depth = 160.0 + rz * 0.8 - y * 0.5
        return sx, sy, depth

    def _poly(self, points, color: str, outline: str = "") -> None:
        projected = [self._project(p, self.width, self.height) for p in points]
        if any(p[2] <= 0.35 for p in projected):
            return
        depth = sum(p[2] for p in projected) / len(projected)
        coords = [v for p in projected for v in p[:2]]
        self.items.append((depth, "poly", coords, color, outline))

    def _ellipse(self, center, rx: float, ry: float, color: str, outline: str = "", width: int = 1) -> None:
        sx, sy, depth = self._project(center, self.width, self.height)
        scale = min(self.width, self.height) * 0.013 * self.camera_zoom
        ax, ay = max(1.0, scale * rx), max(1.0, scale * ry)
        self.items.append((depth, "oval", [sx - ax, sy - ay, sx + ax, sy + ay], color, outline, width))

    def _line3(self, a, b, color: str, width: int = 1, dash=None) -> None:
        p, q = self._project(a, self.width, self.height), self._project(b, self.width, self.height)
        depth = (p[2] + q[2]) / 2
        self.items.append((depth, "line", [p[0], p[1], q[0], q[1]], color, width, dash))

    def _box(self, center, half, color: str, outline: str = "") -> None:
        x, y, z = center
        hx, hy, hz = half
        v = [(x-hx,y-hy,z-hz),(x+hx,y-hy,z-hz),(x+hx,y+hy,z-hz),(x-hx,y+hy,z-hz),
             (x-hx,y-hy,z+hz),(x+hx,y-hy,z+hz),(x+hx,y+hy,z+hz),(x-hx,y+hy,z+hz)]
        faces = [(0,1,2,3),(4,7,6,5),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)]
        shades = (0.78, 1.12, 0.62, 0.94, 1.20, 0.70)
        for face, shade in zip(faces, shades):
            self._poly([v[i] for i in face], tint(color, shade), outline)

    def _octa(self, center, size: float, color: str, outline: str = "") -> None:
        x, y, z = center
        v = [(x-size,y,z),(x+size,y,z),(x,y-size,z),(x,y+size,z),(x,y,z-size),(x,y,z+size)]
        faces = [(0,2,4),(0,5,2),(0,3,5),(0,4,3),(1,4,2),(1,2,5),(1,5,3),(1,3,4)]
        shades = (0.78, 0.9, 1.05, 0.86, 0.72, 0.93, 1.18, 0.88)
        for face, shade in zip(faces, shades):
            self._poly([v[i] for i in face], tint(color, shade), outline)

    def _ring(self, cx: float, cz: float, y: float, rx: float, rz: float, color: str, segments: int = 48, width: int = 2) -> None:
        pts = [(cx + math.cos(i * math.tau / segments) * rx, y,
                cz + math.sin(i * math.tau / segments) * rz) for i in range(segments + 1)]
        for a, b in zip(pts, pts[1:]):
            self._line3(a, b, color, width)

    def _cone_roof(self, cx: float, cz: float, radius: float, base_y: float, height: float, colors: list[str], segments: int = 12) -> None:
        apex = (cx, base_y + height, cz)
        for i in range(segments):
            a0, a1 = i * math.tau / segments, (i + 1) * math.tau / segments
            p0 = (cx + math.cos(a0) * radius, base_y, cz + math.sin(a0) * radius)
            p1 = (cx + math.cos(a1) * radius, base_y, cz + math.sin(a1) * radius)
            self._poly([p0, p1, apex], colors[i % len(colors)], "#ffe9c9")

    def _build_stage(self) -> None:
        # A large circus ground: four times the previous radius, sixteen times
        # the area. All attractions and fly movement use these world coordinates.
        # Draw the ground before depth-sorted objects, so it never hides distant
        # tents and attractions just because the floor polygon is enormous.
        corners = [(-36.0, -0.16, -36.0), (36.0, -0.16, -36.0),
                   (36.0, -0.16, 36.0), (-36.0, -0.16, 36.0)]
        ground = [self._project(p, self.width, self.height) for p in corners]
        ground_xy = [value for p in ground for value in p[:2]]
        self.canvas.create_polygon(*ground_xy, fill="#2c5a3a", outline="#f2c14e", width=3)
        self._ring(0, 0, 0.025, 35.0, 35.0, "#e8c98a", 64, 4)
        self._ring(0, 0, 0.045, 24.0, 24.0, "#d9b97a", 64, 3)
        self._ring(0, 0, 0.055, 12.0, 12.0, "#cfae6c", 64, 3)
        for i in range(20):
            a = i * math.tau / 20
            self._octa((math.cos(a) * 35.2, 0.18, math.sin(a) * 35.2), 0.45,
                       "#ffe27a" if i % 2 == 0 else "#ff9a5e")

        # Big-top tent, striped walls and a polygon canopy.
        tx, tz = 0.0, 6.2
        tent_colors = ["#d6452f", "#fff3dc", "#d6452f", "#fff3dc"]
        n = 12
        for i in range(n):
            a0, a1 = i * math.tau / n, (i + 1) * math.tau / n
            p0 = (tx + 4.1 * math.cos(a0), 0.0, tz + 4.1 * math.sin(a0))
            p1 = (tx + 4.1 * math.cos(a1), 0.0, tz + 4.1 * math.sin(a1))
            p2 = (p1[0], 3.1, p1[2])
            p3 = (p0[0], 3.1, p0[2])
            self._poly([p0, p1, p2, p3], tent_colors[i % len(tent_colors)], "#2d1d12")
        self._cone_roof(tx, tz, 4.15, 3.05, 4.0, tent_colors, n)
        self._octa((tx, 7.3, tz), 0.42, "#ffe06b", "#fff4b7")
        # Three additional big-top pavilions mark separate districts.
        for px, pz, color in [(-23, -6, "#e0573f"), (23, 1, "#3f8fe0"), (0, 25, "#e0b03f")]:
            self._cylinder(px, 0.0, pz, 3.4, 3.8, [color, "#fff3dc"], 10)
            self._cone_roof(px, pz, 3.5, 3.8, 3.8, [color, "#ffe8bb"], 10)
            self._octa((px, 7.8, pz), 0.45, "#ffe078")

        # Floating Ringmaster: the host is a character, not a fly connectome.
        self._octa((-3.0, 4.5, -3.0), 0.95, "#ffecfb", "#ff81da")
        self._box((-3.0, 5.6, -3.0), (0.9, 0.20, 0.7), "#a14ad0", "#ffe680")
        self._box((-3.0, 6.1, -3.0), (0.48, 0.55, 0.45), "#a14ad0", "#ffe680")
        self._ellipse((-3.32, 4.65, -3.85), 0.15, 0.2, "#23102c")
        self._ellipse((-2.68, 4.65, -3.85), 0.15, 0.2, "#23102c")

        # Carousel and spotlit dais.
        self._cylinder(0, 0.2, 0, 2.0, 0.35, ["#e0573f", "#ffd65c", "#3f8fe0", "#7bd88f"])
        self._cone_roof(0, 0, 2.0, 0.42, 1.0, ["#e0573f", "#ffd65c", "#3f8fe0", "#7bd88f"], 8)
        self._octa((0, 1.6, 0), 0.32, "#fff0ad")

        # String-light posts around the outer path.
        posts = 16
        for i in range(posts):
            a, a2 = i * math.tau / posts, (i + 1) * math.tau / posts
            px, pz = math.cos(a) * 32.5, math.sin(a) * 32.5
            qx, qz = math.cos(a2) * 32.5, math.sin(a2) * 32.5
            self._line3((px, 0.0, pz), (px, 2.3, pz), "#5a4632", 3)
            self._octa((px, 2.45, pz), 0.2, "#ffe9a0", "#fff7d6")
            sag = ((px + qx) / 2 * 0.985, 2.0, (pz + qz) / 2 * 0.985)
            self._line3((px, 2.4, pz), sag, "#ffe9a0", 1)
            self._line3(sag, (qx, 2.4, qz), "#ffe9a0", 1)

        # Attractions around the grounds.
        for idx, (name, gx, gz, color, kind) in enumerate(GOALS):
            if kind == "water":
                self._ellipse((gx, 0.03, gz), 3.3, 3.3 * 0.48, "#2d78b8", "#9ee3ff", 2)
                self._ellipse((gx, 0.04, gz), 2.1, 2.1 * 0.48, "#3c97d6", "", 1)
                if name == "BOAT LAKE":
                    self._box((gx, 0.22, gz), (0.8, 0.14, 0.32), "#c96b3b", "#fff3dc")
                    self._line3((gx, 0.3, gz), (gx, 1.7, gz), "#fff3dc", 2)
                    self._octa((gx + 0.1, 1.2, gz), 0.38, "#fff3dc")
                else:
                    for j in range(3):
                        self._octa((gx + (j - 1) * 0.9, 0.2, gz + (j % 2) * 0.6 - 0.3),
                                   0.22, "#ffd84a", "#fff3b0")
                continue
            self._box((gx, 0.18, gz), (1.10, 0.18, 0.92), "#5a4632", color)
            if kind == "gate":
                self._box((gx - 0.65, 1.0, gz), (0.12, 0.95, 0.15), color, "#fff1d6")
                self._box((gx + 0.65, 1.0, gz), (0.12, 0.95, 0.15), color, "#fff1d6")
                self._box((gx, 1.9, gz), (0.78, 0.12, 0.15), color, "#fff1d6")
            elif kind == "food":
                self._box((gx, 0.95, gz), (0.8, 0.6, 0.35), "#c9533a", "#fff1d6")
                self._cone_roof(gx, gz, 0.85, 1.5, 0.75, ["#ffe16b", "#e0573f"], 8)
            elif kind == "play":
                for j in range(4):
                    self._octa((gx + (j - 1.5) * 0.38, 0.85 + (j % 2) * 0.3, gz), 0.24, color)
            elif kind == "wheel":
                self._ferris_wheel(gx, gz, color)
            elif kind == "tower":
                self._clock_tower(gx, gz, color)
            else:
                self._spotlight(gx, gz, color)

    def _ferris_wheel(self, cx: float, cz: float, color: str) -> None:
        radius, hub = 3.2, 4.3
        spin = time.time() * 0.25
        for side in (-1.9, 1.9):
            self._line3((cx + side, 0.0, cz), (cx, hub, cz), "#cfd2e6", 4)
        steps = 24
        rim = [(cx + math.cos(i * math.tau / steps) * radius,
                hub + math.sin(i * math.tau / steps) * radius, cz) for i in range(steps + 1)]
        for a, b in zip(rim, rim[1:]):
            self._line3(a, b, color, 3)
        for k in range(8):
            ang = spin + k * math.tau / 8
            tip = (cx + math.cos(ang) * radius, hub + math.sin(ang) * radius, cz)
            self._line3((cx, hub, cz), tip, "#e9e3ff", 1)
            self._octa((tip[0], tip[1] - 0.35, tip[2]), 0.28,
                       "#ff6b4f" if k % 2 else "#ffd35c", "#fff7d6")
        self._octa((cx, hub, cz), 0.3, "#ffd35c", "#fff7d6")

    def _clock_tower(self, cx: float, cz: float, color: str) -> None:
        self._box((cx, 2.3, cz), (0.75, 2.1, 0.75), "#8a6a4a", "#2d1d12")
        self._cone_roof(cx, cz, 1.05, 4.4, 1.6, [color, "#e0573f"], 4)
        face = (cx, 3.7, cz - 0.78)
        self._ellipse(face, 0.4, 0.4, "#fff3dc", "#2d1d12", 2)
        minute = time.time() * 0.8
        self._line3(face, (face[0] + math.sin(minute) * 0.32, face[1] + math.cos(minute) * 0.32,
                           face[2] - 0.02), "#2d1d12", 2)
        self._line3(face, (face[0] + math.sin(minute / 12) * 0.2, face[1] + math.cos(minute / 12) * 0.2,
                           face[2] - 0.02), "#2d1d12", 3)

    def _cylinder(self, cx: float, y: float, cz: float, radius: float, height: float, colors: list[str], segments: int = 12) -> None:
        for i in range(segments):
            a0, a1 = i * math.tau / segments, (i + 1) * math.tau / segments
            p0 = (cx + math.cos(a0) * radius, y, cz + math.sin(a0) * radius)
            p1 = (cx + math.cos(a1) * radius, y, cz + math.sin(a1) * radius)
            p2 = (p1[0], y + height, p1[2])
            p3 = (p0[0], y + height, p0[2])
            self._poly([p0, p1, p2, p3], colors[i % len(colors)], "#432052")

    def _spotlight(self, x: float, z: float, color: str) -> None:
        self._cylinder(x, 0.38, z, 0.58, 0.75, ["#482761", "#704386", "#432354", "#80508f"], 8)
        self._octa((x, 1.55, z), 0.34, color)

    def _build_abstracted_fly(self, fly: Fly, now: float) -> None:
        """An animated, visibly transformed circus character, not real anatomy."""
        x, z = fly.x, fly.z
        pulse = math.sin(now * 5.0 + len(fly.name))
        bob = 1.65 + 0.18 * pulse
        self._ellipse((x, 0.08, z), 1.25, 0.45, "#110b22")
        self._octa((x, bob, z), 1.05, "#241733", "#9e438c")
        self._octa((x, bob + 0.75, z - 0.10), 0.70, "#321b46", "#ff59be")
        self._octa((x - 0.85, bob - 0.15, z), 0.53, "#182e40", "#6bffed")
        self._octa((x + 0.85, bob - 0.15, z), 0.53, "#392047", "#ff4abc")
        for i in range(5):
            ex = x + (i - 2) * 0.31
            ey = bob + 0.45 + 0.12 * (i % 2)
            self._ellipse((ex, ey, z - 0.82), 0.12, 0.15, "#fff078", "#ff65cf", 1)
            self._ellipse((ex, ey, z - 0.91), 0.04, 0.06, "#120f1f")
        for side in (-1, 1):
            for k in range(3):
                start = (x + side * 0.52, bob - 0.25, z + (k - 1) * 0.35)
                elbow = (x + side * (1.10 + k * 0.12), bob - 0.70, z + (k - 1) * 0.55)
                foot = (x + side * (1.50 + k * 0.15), 0.12, z + (k - 1) * 0.70)
                self._line3(start, elbow, "#ff5bc8" if k == 1 else "#62f8e7", 3)
                self._line3(elbow, foot, "#ff5bc8" if k == 1 else "#62f8e7", 3)
        for i in range(7):
            a = now * (1.1 if i % 2 else -0.8) + i * math.tau / 7
            radius = 1.45 + 0.12 * math.sin(now * 3 + i)
            self._octa((x + math.cos(a) * radius, bob + 0.45 + 0.4 * math.sin(a * 2),
                        z + math.sin(a) * radius), 0.14,
                       "#6affee" if i % 2 else "#ff4ecb")

    def _ellipsoid(self, origin, yaw: float, center, radii, color: str,
                   rings: int = 5, segs: int = 8, stripe: str | None = None,
                   bias: float = 0.0) -> None:
        """A lit, back-face-culled 3D ellipsoid made of polygon facets.

        center/radii are in the fly's local frame: (forward, up, side). The
        ellipsoid's poles lie along the forward axis, so every other ring can
        carry a stripe colour (used for the abdomen bands).
        """
        ox, oy, oz = origin
        fx, fz = math.cos(yaw), math.sin(yaw)
        sx, sz = -fz, fx
        cf, cu, cs = center
        rf, ru, rs = radii
        w, h = self.width, self.height
        grid = []
        for i in range(rings + 1):
            phi = math.pi * i / rings
            cp, sp = math.cos(phi), math.sin(phi)
            row = []
            for j in range(segs):
                th = math.tau * j / segs
                f = cf + rf * cp
                u = cu + ru * sp * math.cos(th)
                s = cs + rs * sp * math.sin(th)
                row.append(self._project((ox + fx * f + sx * s, oy + u, oz + fz * f + sz * s), w, h))
            grid.append(row)
        for i in range(rings):
            phi = math.pi * (i + 0.5) / rings
            cp, sp = math.cos(phi), math.sin(phi)
            base = stripe if (stripe and i % 2) else color
            for j in range(segs):
                th = math.tau * (j + 0.5) / segs
                nf, nu, ns = cp / rf, sp * math.cos(th) / ru, sp * math.sin(th) / rs
                inv = 1.0 / math.sqrt(nf * nf + nu * nu + ns * ns)
                nf, nu, ns = nf * inv, nu * inv, ns * inv
                wx, wy, wz = fx * nf + sx * ns, nu, fz * nf + sz * ns
                facing = wx * VIEW[0] + wy * VIEW[1] + wz * VIEW[2]
                if facing < -0.04:
                    continue  # faces away from the camera
                lam = max(0.0, wx * LIGHT[0] + wy * LIGHT[1] + wz * LIGHT[2])
                fill = tint(base, 0.50 + 0.62 * lam + 0.10 * max(0.0, facing))
                a, b = grid[i][j], grid[i][(j + 1) % segs]
                c, d = grid[i + 1][(j + 1) % segs], grid[i + 1][j]
                depth = (a[2] + b[2] + c[2] + d[2]) / 4 - bias
                self.items.append((depth, "poly", [a[0], a[1], b[0], b[1], c[0], c[1], d[0], d[1]],
                                   fill, fill))

    def _build_fly(self, fly: Fly, now: float) -> None:
        if fly.abstracted:
            self._build_abstracted_fly(fly, now)
            return
        x, z = fly.x, fly.z
        y = 0.88 + 0.10 * math.sin(now * 4.5 + fly.age_days)
        body, pale = fly.color, fly.pale
        if fly.glitch > 25:
            decay = min(1.0, (fly.glitch - 25) / 75.0) * 0.55
            body, pale = mix(body, "#3a2250", decay), mix(pale, "#9a7fb0", decay)
            if fly.glitch > 50:  # a shiver that grows as the fly unravels
                x += math.sin(now * 37 + len(fly.name)) * 0.05 * (fly.glitch - 50) / 50

        yaw = fly.yaw
        fx, fz = math.cos(yaw), math.sin(yaw)
        sx, sz = -fz, fx
        origin = (x, y, z)

        def P(f: float, u: float, s: float) -> tuple[float, float, float]:
            """Fly-local (forward, up, side) to world coordinates."""
            return (x + fx * f + sx * s, y + u, z + fz * f + sz * s)

        dark = tint(body, 0.42)
        # Eyes: whichever candidate colour stands out most from the body.
        eye = max(("#d62840", "#2b1445", "#1c8a96"),
                  key=lambda c: sum((p - q) ** 2 for p, q in zip(rgb(c), rgb(body))))
        thorax_col = mix(body, pale, 0.55)

        # Shadow on the ground.
        self._ellipse((x, 0.06, z), 0.55, 0.25, "#211430")

        # Wings: translucent-looking flat panels hinged on the thorax that flap.
        flap = math.sin(now * 22 + len(fly.name))
        theta = 0.55 + 0.45 * flap
        wing_fill, vein = mix(pale, "#ffffff", 0.6), mix(pale, "#8fa8ff", 0.45)
        for sgn in (-1, 1):
            span = (-0.30, math.sin(theta), sgn * math.cos(theta))
            n = math.sqrt(sum(v * v for v in span))
            span = tuple(v / n for v in span)
            root, length, chord = (0.0, 0.22, sgn * 0.14), 1.0, 0.30
            pts = []
            for k in range(14):
                a = math.tau * k / 14
                along = length * 0.5 * (1 + math.cos(a))
                across = chord * (0.9 + math.sin(a))
                pts.append(P(root[0] + span[0] * along - across,
                             root[1] + span[1] * along,
                             root[2] + span[2] * along))
            self._poly(pts, wing_fill, vein)
            tip = P(root[0] + span[0] * length * 0.92 - chord * 0.9,
                    root[1] + span[1] * length * 0.92, root[2] + span[2] * length * 0.92)
            self._line3(P(*root), tip, vein, 1)

        # Six legs, two segments each, swinging gently.
        for k, hip_f in enumerate((0.16, 0.0, -0.16)):
            for sgn in (-1, 1):
                sw = math.sin(now * 9 + k * 2.1 + (0.0 if sgn > 0 else math.pi)) * 0.07
                hip = P(hip_f, -0.16, sgn * 0.12)
                knee = P(hip_f + 0.10 - 0.10 * k + sw, -0.10, sgn * 0.42)
                foot = P(hip_f + 0.20 - 0.22 * k + sw * 1.5, -0.55, sgn * 0.36)
                self._line3(hip, knee, dark, 2)
                self._line3(knee, foot, dark, 2)

        # Body: abdomen with dark bands, thorax, head (all shaded 3D ellipsoids).
        self._ellipsoid(origin, yaw, (-0.50, -0.04, 0.0), (0.44, 0.28, 0.27), body,
                        rings=6, segs=9, stripe=dark)
        self._ellipsoid(origin, yaw, (0.0, 0.0, 0.0), (0.30, 0.27, 0.25), thorax_col,
                        rings=5, segs=9)
        self._ellipsoid(origin, yaw, (0.42, 0.03, 0.0), (0.22, 0.20, 0.22), pale,
                        rings=4, segs=8)

        # Compound eyes with a glint, proboscis and antennae.
        for sgn in (-1, 1):
            self._ellipsoid(origin, yaw, (0.47, 0.09, sgn * 0.15), (0.12, 0.13, 0.10), eye,
                            rings=4, segs=7, bias=0.05)
            self._ellipsoid(origin, yaw, (0.53, 0.18, sgn * 0.19), (0.03, 0.03, 0.03), "#ffffff",
                            rings=3, segs=5, bias=0.3)
            self._line3(P(0.52, 0.16, sgn * 0.06), P(0.68, 0.40, sgn * 0.13), pale, 2)
            self._octa(P(0.68, 0.40, sgn * 0.13), 0.045, dark)
        self._line3(P(0.60, -0.06, 0.0), P(0.80, -0.20, 0.0), dark, 3)

        # Costume accessories, positioned relative to the head.
        hx, hy, hz = P(0.42, 0.03, 0.0)
        if fly.costume == "ears":
            for side in (-1, 1):
                self._ellipsoid(origin, yaw, (0.36, 0.43, side * 0.12), (0.05, 0.22, 0.07),
                                pale, rings=4, segs=6)
        elif fly.costume == "crown":
            self._octa((hx, hy + 0.32, hz), 0.19, "#ffd65c", "#fff3b0")
        elif fly.costume == "diamond":
            self._octa((hx, hy + 0.32, hz), 0.17, "#7aebff", "#e6fbff")
        elif fly.costume == "jester":
            for side in (-1, 1):
                self._ellipsoid(origin, yaw, (0.38, 0.30, side * 0.20), (0.07, 0.15, 0.07),
                                body, rings=4, segs=6)
        elif fly.costume == "halo":
            self._ring(hx, hz, hy + 0.38, 0.30, 0.30, pale, 16, 2)
        elif fly.costume == "ribbon":
            for k in range(3):
                wob = 0.05 * math.sin(now * 6 + k)
                self._line3(P(-0.15, 0.24, 0.0),
                            P(-0.85 - 0.08 * k, 0.12 - 0.10 * k + wob, (k - 1) * 0.20),
                            "#ffd0ef", 3)

    def _draw_items(self) -> None:
        for item in sorted(self.items, key=lambda x: x[0], reverse=True):
            kind = item[1]
            if kind == "poly":
                _, _, coords, color, outline = item
                self.canvas.create_polygon(*coords, fill=color, outline=outline, width=1)
            elif kind == "oval":
                _, _, coords, color, outline, width = item
                self.canvas.create_oval(*coords, fill=color, outline=outline, width=width)
            elif kind == "line":
                _, _, coords, color, width, dash = item
                self.canvas.create_line(*coords, fill=color, width=width, dash=dash)

    def _projected_text(self, p, text: str, color: str, size: int, bold: bool = True) -> None:
        sx, sy, depth = self._project(p, self.width, self.height)
        if depth < 0.6 or sx < -100 or sx > self.width + 100 or sy < -60 or sy > self.height + 60:
            return
        px = max(7, int(size * 16 / depth))
        font = ("Segoe UI", min(19, px), "bold" if bold else "normal")
        self.canvas.create_text(sx, sy, text=text, fill=color, font=font)

    def draw(self) -> None:
        c = self.canvas
        c.delete("all")
        self.width, self.height = max(1, c.winfo_width()), max(1, c.winfo_height())
        now = time.time()
        self.camera_angle = 0.07 * math.sin(now * 0.10)
        self.items = []

        # Carnival night sky and distant stars.
        for i, color in enumerate(("#0b1230", "#111a40", "#1a2252", "#2a2a62")):
            y0 = self.height * i / 4
            y1 = self.height * (i + 1) / 4 + 1
            c.create_rectangle(0, y0, self.width, y1, fill=color, outline="")
        for i in range(36):
            sx = (i * 137 + 43) % self.width
            sy = (i * 73 + 29) % max(1, int(self.height * 0.35))
            r = 1 + i % 3
            c.create_oval(sx-r, sy-r, sx+r, sy+r, fill="#ffe88c" if i % 3 else "#79ecff", outline="")

        self._build_stage()
        self._build_quest_route(now)
        for fly in self.flies:
            self._build_fly(fly, now)
        self._draw_items()

        # Attraction labels float over the 3D set.
        self._projected_text((-3.0, 7.2, -3.0), "RINGMASTER", "#ffe27a", 8)
        for index, (name, gx, gz, color, _kind) in enumerate(GOALS):
            if self.camera_mode == "FOLLOW" or index % 2 == 0 or index == self.quest_stop():
                self._projected_text((gx, 2.7, gz), name, "#fff4ff", 7)

        if self.quest is not None:
            for k, gi in enumerate(self.quest["stops"]):
                gx, gz = GOALS[gi][1:3]
                self._projected_text((gx, 3.6, gz), f"{k + 1}",
                                     "#ffe27a" if k == self.quest["step"] else "#b9a9cf", 10)

        # The overview uses compact labels; follow view includes their mood.
        for fly in self.flies:
            sx, sy, depth = self._project((fly.x, 1.85, fly.z), self.width, self.height)
            if depth > 0 and -50 < sx < self.width + 50 and -40 < sy < self.height + 50:
                if fly.abstracted:
                    label = f"{fly.name}  •  ABSTRACTED"
                else:
                    label = f"{fly.name}  •  {fly.mood}" if self.camera_mode == "FOLLOW" else fly.name
                if self.quest is not None and fly.name in self.quest["party"]:
                    label = "★ " + label
                c.create_text(sx, sy - (18 if fly.abstracted else 0), text=label,
                              fill="#ff77d5" if fly.abstracted else "#fff4ff",
                              font=("Segoe UI", 9 if fly.abstracted else 8, "bold"))

        # HUD and story ticker.
        c.create_text(18, 16, anchor="nw", text="FLY CARNIVAL",
                      fill="#ffe3f7", font=("Segoe UI", 17, "bold"))
        c.create_text(20, 43, anchor="nw",
                      text=f"MALECNS V1.0 CONNECTOME  |  166,700 NEURONS  |  DAY {int(self.sim_days):03d}  |  YEAR {self.sim_days / 365:.2f}",
                      fill="#d7c7f5", font=("Segoe UI", 9, "bold"))
        state = "LOADING BRAIN" if not self.brain_live else ("PAUSED" if self.paused else "LIVE")
        c.create_text(self.width - 18, 20, anchor="ne",
                      text=f"×{self.speed}   {state}",
                      fill="#90ffcf" if state == "LIVE" else "#ffd478", font=("Segoe UI", 12, "bold"))
        # These are live spike counts from the connectome's body-command groups:
        # DNa02 steering, DNg100 forward, DNp01 escape, MDN backward.
        panel_w = min(330, max(245, self.width * 0.30))
        panel_x, panel_y = self.width - panel_w - 16, 54
        panel_h = 24 + max(1, len(self.flies)) * 16
        c.create_rectangle(panel_x, panel_y, self.width - 16, panel_y + panel_h,
                           fill="#160a28", outline="#71518d", width=1)
        c.create_text(panel_x + 8, panel_y + 6, anchor="nw", text="LIVE CONNECTOME OUTPUT  •  SPIKES / STEP",
                      fill="#7ceeff", font=("Segoe UI", 8, "bold"))
        for i, fly in enumerate(self.flies):
            m = fly.motor
            text = (f"{fly.name:<9} DNa {m.get('steer_L', 0):>2}/{m.get('steer_R', 0):<2}  "
                    f"DNg {m.get('forward_L', 0) + m.get('forward_R', 0):>2}  "
                    f"DNp {m.get('escape_L', 0) + m.get('escape_R', 0):>2}  "
                    f"MDN {m.get('backward_L', 0) + m.get('backward_R', 0):>2}")
            c.create_text(panel_x + 8, panel_y + 22 + i * 16, anchor="nw", text=text,
                          fill=fly.pale, font=("Consolas", 8))
        if not self.flies:
            c.create_text(panel_x + 8, panel_y + 22, anchor="nw",
                          text="No flies on stage. Press + ADD FLY.",
                          fill="#ffd0de", font=("Consolas", 8))
        if time.monotonic() < self.abstraction_notice_until:
            notice_width = min(460, self.width - 40)
            x0 = (self.width - notice_width) / 2
            c.create_rectangle(x0, 180, x0 + notice_width, 220,
                               fill="#2c112c", outline="#ff5cc8", width=3)
            c.create_text(self.width / 2, 200, text=self.abstraction_notice,
                          fill="#ff9ae2", font=("Segoe UI", 13, "bold"), width=notice_width - 20)
        box_y = self.height - 83
        c.create_rectangle(14, box_y, self.width - 14, self.height - 13,
                           fill="#140920", outline="#8a5aab", width=2)
        c.create_text(27, box_y + 12, anchor="nw", text=f"RINGMASTER  •  {self.host_mode}  |  {self.event_title}",
                      fill="#ffd16e", font=("Segoe UI", 10, "bold"))
        c.create_text(27, box_y + 34, anchor="nw", width=self.width - 58,
                      text=self.event_text, fill="#f0e4ff", font=("Segoe UI", 10))

        if self.status.get().startswith("FlyBrain could not start"):
            c.create_rectangle(self.width * 0.14, self.height * 0.42,
                               self.width * 0.86, self.height * 0.58,
                               fill="#1b0d2c", outline="#ff6f9e", width=2)
            c.create_text(self.width * 0.5, self.height * 0.5,
                          width=self.width * 0.67, text=self.status.get(),
                          fill="#ffe3ee", font=("Segoe UI", 11, "bold"), justify="center")

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        self.brain.stop_event.set()
        self.host.stop_event.set()
        self.root.destroy()


def main() -> None:
    Circus().run()


if __name__ == "__main__":
    main()
