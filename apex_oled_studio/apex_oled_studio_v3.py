#!/usr/bin/env python3
"""
Apex OLED Studio v3

Linux OLED controller for SteelSeries Apex keyboards.

Features
- Text tab with 5 reusable text slots
- Images tab with 5 saved image slots
- GIF Playlist tab with 5 GIF slots and per-slot duration
- Media tab (music/video metadata + controls through optional playerctl/MPRIS)
- System Monitor tab (CPU/RAM and GPU when exposed by Linux)
- App Profiles / Onboard tab
- Save active GIF playlist + optional Linux autostart
- One live OLED source at a time: GIF, Media, or Monitor

Required Python packages (already used by the earlier app):
    Pillow
    hidapi

Optional Linux package for Media tab:
    sudo apt install playerctl

Known Apex 7 ID: 1038:1612
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import hid
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageTk, ImageSequence

VID = 0x1038
WIDTH = 128
HEIGHT = 40

DEVICES = {
    0x1610: ("Apex Pro", "legacy", 1),
    0x1612: ("Apex 7", "legacy", 1),
    0x1614: ("Apex Pro TKL", "legacy", 1),
    0x1618: ("Apex 7 TKL", "legacy", 1),
    0x161C: ("Apex 5", "legacy", 1),
    0x1640: ("Apex Pro Gen 3", "gen3_single", 1),
    0x1646: ("Apex Pro TKL Wireless Gen 3 (wired)", "gen3_chunked", 3),
    0x1644: ("Apex Pro TKL Wireless Gen 3 (dongle)", "gen3_chunked_wireless", 3),
}

APP_DIR = Path.home() / ".config" / "apex-oled-studio"
ASSET_DIR = APP_DIR / "assets"
CONFIG_FILE = APP_DIR / "config.json"
AUTOSTART_FILE = Path.home() / ".config" / "autostart" / "apex-oled-studio.desktop"


def defaults():
    return {
        "text_slots": [
            {"name": f"Text {i}", "text": "KLIGHT" if i == 1 else "", "size": 18, "x": 2, "y": 9}
            for i in range(1, 6)
        ],
        "image_slots": [{"name": f"Image {i}", "path": ""} for i in range(1, 6)],
        "gif_slots": [{"name": f"GIF {i}", "path": "", "seconds": 10.0} for i in range(1, 6)],
        "profiles": [{"name": f"Profile {i}", "data": {}} for i in range(1, 6)],
        "active_playlist": {"enabled": False, "autoplay": False, "loop": True},
    }


def ensure_dirs():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    ensure_dirs()
    cfg = defaults()
    if not CONFIG_FILE.exists():
        return cfg
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        for k, v in data.items():
            cfg[k] = v
    except Exception:
        pass
    return cfg


def save_config(cfg):
    ensure_dirs()
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def find_font(size, bold=True):
    choices = []
    if bold:
        choices += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]
    choices += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for p in choices:
        if Path(p).exists():
            return ImageFont.truetype(p, max(5, int(size)))
    return ImageFont.load_default()


def threshold_image(img, threshold=128):
    return img.convert("L").point(lambda p: 255 if p >= threshold else 0).convert("L")


def fit_to_oled(img):
    src = ImageOps.autocontrast(img.convert("L"))
    fitted = ImageOps.contain(src, (WIDTH, HEIGHT), method=Image.Resampling.LANCZOS)
    out = Image.new("L", (WIDTH, HEIGHT), 0)
    out.paste(fitted, ((WIDTH - fitted.width) // 2, (HEIGHT - fitted.height) // 2))
    return threshold_image(out)


def render_text(text, size=18, x=2, y=9):
    img = Image.new("L", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(img)
    draw.text((int(x), int(y)), str(text), font=find_font(size, True), fill=255)
    return threshold_image(img, 110)


def shorten(draw, text, font, max_width=126):
    text = str(text or "")
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return text
    while text:
        text = text[:-1]
        test = text + "..."
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
            return test
    return "..."


def render_two_lines(top, bottom="", footer=""):
    img = Image.new("L", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(img)
    f1, f2, f3 = find_font(12, True), find_font(9, False), find_font(7, False)
    draw.text((1, 1), shorten(draw, top, f1), font=f1, fill=255)
    if bottom:
        draw.text((1, 16), shorten(draw, bottom, f2), font=f2, fill=255)
    if footer:
        draw.text((1, 31), shorten(draw, footer, f3), font=f3, fill=255)
    return threshold_image(img, 110)


def draw_bar(draw, x, y, width, percent):
    percent = max(0.0, min(100.0, float(percent)))
    draw.rectangle((x, y, x + width - 1, y + 6), outline=255)
    fill = int((width - 2) * percent / 100.0)
    if fill > 0:
        draw.rectangle((x + 1, y + 1, x + fill, y + 5), fill=255)


def render_monitor(stats):
    img = Image.new("L", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(img)
    font = find_font(8, True)
    tiny = find_font(7, False)
    cpu, ram, gpu = stats["cpu"], stats["ram"], stats.get("gpu")
    draw.text((0, 0), f"CPU {cpu:3.0f}%", font=font, fill=255)
    draw_bar(draw, 43, 1, 84, cpu)
    draw.text((0, 11), f"RAM {ram:3.0f}%", font=font, fill=255)
    draw_bar(draw, 43, 12, 84, ram)
    if gpu is None:
        draw.text((0, 22), "GPU N/A", font=font, fill=255)
    else:
        draw.text((0, 22), f"GPU {gpu:3.0f}%", font=font, fill=255)
        draw_bar(draw, 43, 23, 84, gpu)
    footer = f"RAM {stats['used']:.1f}/{stats['total']:.1f}GB"
    if stats.get("cpu_temp") is not None:
        footer = f"CPU {stats['cpu_temp']:.0f}C  " + footer
    draw.text((0, 33), footer[:27], font=tiny, fill=255)
    return threshold_image(img, 110)


def pack_legacy(img):
    bw = threshold_image(img)
    px = bw.load()
    report = bytearray(642)
    report[0] = 0x61
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if px[x, y]:
                idx = y * WIDTH + x
                report[1 + idx // 8] |= 1 << (7 - idx % 8)
    return bytes(report)


def pack_page_major(img):
    bw = threshold_image(img)
    px = bw.load()
    report = bytearray(642)
    report[0] = 0x61
    for y in range(HEIGHT):
        page, bit = y // 8, y % 8
        for x in range(WIDTH):
            if px[x, y]:
                report[1 + page * WIDTH + x] |= 1 << bit
    return bytes(report)


def enumerate_apex():
    out = []
    for info in hid.enumerate(VID, 0):
        pid = info.get("product_id")
        if pid in DEVICES and info.get("interface_number", -1) == DEVICES[pid][2]:
            out.append(info)
    return out


class OLEDTransport:
    def __init__(self):
        self.dev = None
        self.path = None
        self.pid = None

    def open(self, path, pid):
        if self.dev is not None and self.path == path and self.pid == pid:
            return
        self.close()
        self.dev = hid.device()
        self.dev.open_path(path)
        self.path, self.pid = path, pid

    def close(self):
        if self.dev is not None:
            try:
                self.dev.close()
            except Exception:
                pass
        self.dev = self.path = self.pid = None

    def send(self, img):
        if self.dev is None:
            raise RuntimeError("OLED device is not open")
        protocol = DEVICES[self.pid][1]
        if protocol == "legacy":
            self.dev.send_feature_report(pack_legacy(img))
            return
        if protocol == "gen3_single":
            self.dev.send_feature_report(pack_page_major(img))
            return
        fb = pack_page_major(img)[1:641]
        cmd = 0x4C if protocol == "gen3_chunked_wireless" else 0x0C
        offsets = (0x0000, 0x0050, 0x00A0, 0x00F0, 0x0140, 0x0190, 0x01E0, 0x0230)
        for i, offset in enumerate(offsets):
            report = bytearray(641)
            report[0] = cmd
            report[1] = 0x01
            report[2] = offset & 0xFF
            report[3] = (offset >> 8) & 0xFF
            report[4] = 80
            report[6:86] = fb[i * 80:i * 80 + 80]
            self.dev.send_feature_report(bytes(report))


def load_gif_frames(path):
    gif = Image.open(path)
    frames, delays = [], []
    for frame in ImageSequence.Iterator(gif):
        delay = frame.info.get("duration", gif.info.get("duration", 100))
        try:
            delay = int(delay)
        except Exception:
            delay = 100
        delay = max(80, delay)
        rgba = frame.copy().convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
        bg.alpha_composite(rgba)
        frames.append(fit_to_oled(bg.convert("L")))
        delays.append(delay)
    if not frames:
        raise ValueError("No GIF frames found")
    return frames, delays


def playerctl_available():
    return shutil.which("playerctl") is not None


def playerctl(args):
    if not playerctl_available():
        return ""
    try:
        r = subprocess.run(["playerctl", *args], text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=1.5, check=False)
        return r.stdout.strip()
    except Exception:
        return ""


def media_info():
    if not playerctl_available():
        return {"status": "playerctl not installed", "title": "", "artist": "", "player": ""}
    return {
        "status": playerctl(["status"]) or "No active player",
        "title": playerctl(["metadata", "title"]) or "No title",
        "artist": playerctl(["metadata", "artist"]),
        "player": playerctl(["metadata", "--format", "{{playerName}}"]),
    }


class SystemStats:
    def __init__(self):
        self.prev = self._cpu()

    def _cpu(self):
        try:
            vals = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            return sum(vals), idle
        except Exception:
            return 0, 0

    def cpu(self):
        cur = self._cpu()
        dt, di = cur[0] - self.prev[0], cur[1] - self.prev[1]
        self.prev = cur
        return 0.0 if dt <= 0 else max(0.0, min(100.0, 100.0 * (1 - di / dt)))

    def ram(self):
        d = {}
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                k, v = line.split(":", 1)
                d[k] = int(v.strip().split()[0])
        except Exception:
            return 0.0, 0.0, 0.0
        total = d.get("MemTotal", 0)
        avail = d.get("MemAvailable", d.get("MemFree", 0))
        used = max(0, total - avail)
        pct = 100.0 * used / total if total else 0.0
        return pct, used / 1048576, total / 1048576

    def gpu(self):
        for p in Path("/sys/class/drm").glob("card*/device/gpu_busy_percent"):
            try:
                return max(0.0, min(100.0, float(p.read_text().strip())))
            except Exception:
                pass
        return None

    def temp(self, gpu=False):
        root = Path("/sys/class/hwmon")
        if not root.exists():
            return None
        for hw in root.glob("hwmon*"):
            try:
                name = (hw / "name").read_text().strip().lower()
            except Exception:
                name = ""
            tokens = ("amdgpu", "radeon", "nouveau", "nvidia") if gpu else ("k10temp", "coretemp", "cpu", "acpitz")
            if not any(t in name for t in tokens):
                continue
            for p in hw.glob("temp*_input"):
                try:
                    v = float(p.read_text().strip()) / 1000.0
                    if -20 <= v <= 150:
                        return v
                except Exception:
                    pass
        return None

    def sample(self):
        ram, used, total = self.ram()
        return {"cpu": self.cpu(), "ram": ram, "used": used, "total": total,
                "gpu": self.gpu(), "cpu_temp": self.temp(False), "gpu_temp": self.temp(True)}


class ScrollTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=10)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        self.canvas.bind("<Enter>", lambda e: self._wheel_on())
        self.canvas.bind("<Leave>", lambda e: self._wheel_off())

    def _wheel(self, e):
        if getattr(e, "num", None) == 4:
            self.canvas.yview_scroll(-2, "units")
        elif getattr(e, "num", None) == 5:
            self.canvas.yview_scroll(2, "units")
        elif getattr(e, "delta", 0):
            self.canvas.yview_scroll(int(-e.delta / 120), "units")

    def _wheel_on(self):
        self.canvas.bind_all("<Button-4>", self._wheel)
        self.canvas.bind_all("<Button-5>", self._wheel)
        self.canvas.bind_all("<MouseWheel>", self._wheel)

    def _wheel_off(self):
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")
        self.canvas.unbind_all("<MouseWheel>")


class ApexOLEDStudio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.transport = OLEDTransport()
        self.stats = SystemStats()
        self.devices = []
        self.canvas_img = Image.new("L", (WIDTH, HEIGHT), 0)
        self.preview_photo = None
        self.live_mode = None
        self.live_after = None
        self.gif_cache = {}
        self.playlist = []
        self.playlist_pos = 0
        self.frame_pos = 0
        self.slot_started = 0.0
        self.paused = False

        self.title("Apex OLED Studio v3")
        self.geometry("920x760")
        self.minsize(760, 600)

        self.device_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.invert_var = tk.BooleanVar(value=False)
        self.text_var = tk.StringVar(value="KLIGHT")
        self.text_size = tk.IntVar(value=18)
        self.text_x = tk.IntVar(value=2)
        self.text_y = tk.IntVar(value=9)
        self.loop_var = tk.BooleanVar(value=self.cfg["active_playlist"].get("loop", True))
        self.autoplay_var = tk.BooleanVar(value=self.cfg["active_playlist"].get("autoplay", False))
        self.media_status = tk.StringVar(value="Media not checked")
        self.media_title = tk.StringVar(value="")
        self.media_artist = tk.StringVar(value="")
        self.cpu_var = tk.StringVar(value="CPU: --")
        self.ram_var = tk.StringVar(value="RAM: --")
        self.gpu_var = tk.StringVar(value="GPU: --")
        self.text_slots_ui, self.image_slots_ui, self.gif_slots_ui, self.profile_ui = [], [], [], []

        self.build_ui()
        self.refresh_devices()
        self.preview_text()
        self.update_media_ui()
        self.update_monitor_ui()
        self.protocol("WM_DELETE_WINDOW", self.close_window)
        if "--autostart" in sys.argv:
            self.after(900, self.autostart_begin)

    def build_ui(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        head = ttk.Frame(root)
        head.pack(fill="x", pady=(0, 8))
        ttk.Label(head, text="Apex OLED Studio", font=("Sans", 20, "bold")).pack(side="left")
        self.device_combo = ttk.Combobox(head, textvariable=self.device_var, state="readonly", width=42)
        self.device_combo.pack(side="left", fill="x", expand=True, padx=12)
        ttk.Button(head, text="Refresh", command=self.refresh_devices).pack(side="left", padx=2)
        ttk.Button(head, text="Test", command=self.test_device).pack(side="left", padx=2)

        preview = ttk.LabelFrame(root, text="OLED Preview — 128 × 40", padding=8)
        preview.pack(fill="x", pady=(0, 8))
        self.preview = ttk.Label(preview)
        self.preview.pack()
        pbar = ttk.Frame(preview)
        pbar.pack(fill="x", pady=(5, 0))
        ttk.Checkbutton(pbar, text="Invert output", variable=self.invert_var, command=self.update_preview).pack(side="left")
        ttk.Button(pbar, text="Clear OLED", command=self.clear_oled).pack(side="right", padx=3)
        ttk.Button(pbar, text="Send Current Frame", command=self.send_current).pack(side="right", padx=3)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True)
        self.text_tab, self.image_tab, self.gif_tab = ScrollTab(nb), ScrollTab(nb), ScrollTab(nb)
        self.media_tab, self.monitor_tab, self.settings_tab = ScrollTab(nb), ScrollTab(nb), ScrollTab(nb)
        for tab, name in [(self.text_tab, "Text"), (self.image_tab, "Images"), (self.gif_tab, "GIF Playlist"),
                          (self.media_tab, "Media"), (self.monitor_tab, "System Monitor"), (self.settings_tab, "Onboard / Profiles")]:
            nb.add(tab, text=name)

        self.build_text_tab()
        self.build_image_tab()
        self.build_gif_tab()
        self.build_media_tab()
        self.build_monitor_tab()
        self.build_settings_tab()

        foot = ttk.Frame(root)
        foot.pack(fill="x", pady=(8, 0))
        ttk.Label(foot, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        ttk.Button(foot, text="Hide / Keep Running", command=self.hide_window).pack(side="right", padx=3)
        ttk.Button(foot, text="Exit Completely", command=self.exit_app).pack(side="right", padx=3)

    def title_block(self, parent, title, desc):
        ttk.Label(parent, text=title, font=("Sans", 14, "bold")).pack(anchor="w")
        ttk.Label(parent, text=desc, wraplength=790, justify="left").pack(anchor="w", pady=(2, 10))

    def build_text_tab(self):
        p = self.text_tab.inner
        self.title_block(p, "Text Renderer", "Render text and keep five reusable text slots.")
        box = ttk.LabelFrame(p, text="Editor", padding=10)
        box.pack(fill="x", pady=5)
        r = ttk.Frame(box); r.pack(fill="x")
        ttk.Entry(r, textvariable=self.text_var).pack(side="left", fill="x", expand=True)
        ttk.Button(r, text="Preview", command=self.preview_text).pack(side="left", padx=3)
        ttk.Button(r, text="OLED", command=self.send_text).pack(side="left", padx=3)
        r = ttk.Frame(box); r.pack(fill="x", pady=8)
        for label, var, lo, hi in [("Size", self.text_size, 6, 40), ("X", self.text_x, -128, 128), ("Y", self.text_y, -40, 40)]:
            ttk.Label(r, text=label).pack(side="left")
            ttk.Spinbox(r, from_=lo, to=hi, width=6, textvariable=var).pack(side="left", padx=(4, 14))
        slots = ttk.LabelFrame(p, text="Text slots", padding=10); slots.pack(fill="x", pady=8)
        for i in range(5):
            s = self.cfg["text_slots"][i]
            nv, tv = tk.StringVar(value=s.get("name", f"Text {i+1}")), tk.StringVar(value=s.get("text", ""))
            self.text_slots_ui.append((nv, tv))
            r = ttk.Frame(slots); r.pack(fill="x", pady=4)
            ttk.Entry(r, textvariable=nv, width=14).pack(side="left")
            ttk.Entry(r, textvariable=tv).pack(side="left", fill="x", expand=True, padx=5)
            ttk.Button(r, text="Load", command=lambda n=i: self.load_text_slot(n)).pack(side="left", padx=2)
            ttk.Button(r, text="Save Current", command=lambda n=i: self.save_text_slot(n)).pack(side="left", padx=2)
            ttk.Button(r, text="OLED", command=lambda n=i: self.send_text_slot(n)).pack(side="left", padx=2)

    def build_image_tab(self):
        p = self.image_tab.inner
        self.title_block(p, "Image Slots", "Five image slots. Chosen files are copied into the app config folder.")
        box = ttk.LabelFrame(p, text="Saved images", padding=10); box.pack(fill="x")
        for i in range(5):
            s = self.cfg["image_slots"][i]
            nv, pv = tk.StringVar(value=s.get("name", f"Image {i+1}")), tk.StringVar(value=s.get("path", ""))
            self.image_slots_ui.append((nv, pv))
            r = ttk.Frame(box); r.pack(fill="x", pady=5)
            ttk.Entry(r, textvariable=nv, width=14).pack(side="left")
            ttk.Label(r, textvariable=pv, anchor="w").pack(side="left", fill="x", expand=True, padx=5)
            ttk.Button(r, text="Choose", command=lambda n=i: self.choose_image(n)).pack(side="left", padx=2)
            ttk.Button(r, text="Preview", command=lambda n=i: self.preview_image(n)).pack(side="left", padx=2)
            ttk.Button(r, text="OLED", command=lambda n=i: self.send_image_slot(n)).pack(side="left", padx=2)
            ttk.Button(r, text="Clear", command=lambda n=i: self.clear_image_slot(n)).pack(side="left", padx=2)

    def build_gif_tab(self):
        p = self.gif_tab.inner
        self.title_block(p, "GIF Playlist", "Load up to five GIFs. Each slot plays for its own duration, then moves to the next non-empty slot.")
        box = ttk.LabelFrame(p, text="GIF slots", padding=10); box.pack(fill="x")
        for i in range(5):
            s = self.cfg["gif_slots"][i]
            nv, pv, sv = tk.StringVar(value=s.get("name", f"GIF {i+1}")), tk.StringVar(value=s.get("path", "")), tk.DoubleVar(value=s.get("seconds", 10.0))
            self.gif_slots_ui.append((nv, pv, sv))
            r = ttk.Frame(box); r.pack(fill="x", pady=5)
            ttk.Entry(r, textvariable=nv, width=11).pack(side="left")
            ttk.Label(r, textvariable=pv, anchor="w").pack(side="left", fill="x", expand=True, padx=4)
            ttk.Label(r, text="sec").pack(side="left")
            ttk.Spinbox(r, from_=1, to=3600, width=6, textvariable=sv).pack(side="left", padx=4)
            ttk.Button(r, text="Choose", command=lambda n=i: self.choose_gif(n)).pack(side="left", padx=2)
            ttk.Button(r, text="Preview", command=lambda n=i: self.preview_gif(n)).pack(side="left", padx=2)
            ttk.Button(r, text="Clear", command=lambda n=i: self.clear_gif(n)).pack(side="left", padx=2)
        ctl = ttk.LabelFrame(p, text="Playlist", padding=10); ctl.pack(fill="x", pady=8)
        r = ttk.Frame(ctl); r.pack(fill="x")
        ttk.Button(r, text="▶ Preview", command=lambda: self.start_playlist(False)).pack(side="left", padx=2)
        ttk.Button(r, text="▶ Play on OLED", command=lambda: self.start_playlist(True)).pack(side="left", padx=2)
        ttk.Button(r, text="⏸ Pause / Resume", command=self.pause_playlist).pack(side="left", padx=2)
        ttk.Button(r, text="■ Stop", command=self.stop_live).pack(side="left", padx=2)
        ttk.Checkbutton(r, text="Loop", variable=self.loop_var).pack(side="right")
        r = ttk.Frame(ctl); r.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(r, text="Auto-play after Linux login", variable=self.autoplay_var).pack(side="left")
        ttk.Button(r, text="Save as Active Playlist", command=self.save_active_playlist).pack(side="right", padx=2)
        ttk.Button(r, text="Install Autostart", command=self.install_autostart).pack(side="right", padx=2)
        ttk.Label(ctl, text="Active Playlist is stored locally. With Autostart enabled, Linux launches this app in the background and keeps streaming it to the OLED.", wraplength=760, justify="left").pack(anchor="w", pady=(8, 0))

    def build_media_tab(self):
        p = self.media_tab.inner
        self.title_block(p, "Media / Music / Video", "Uses playerctl/MPRIS. Works with many Linux players and browser media sessions when they expose MPRIS.")
        box = ttk.LabelFrame(p, text="Now playing", padding=10); box.pack(fill="x")
        ttk.Label(box, textvariable=self.media_status, font=("Sans", 10, "bold")).pack(anchor="w")
        ttk.Label(box, textvariable=self.media_title, wraplength=760).pack(anchor="w", pady=(5, 0))
        ttk.Label(box, textvariable=self.media_artist, wraplength=760).pack(anchor="w")
        r = ttk.Frame(box); r.pack(fill="x", pady=(10, 0))
        ttk.Button(r, text="⏮ Previous", command=lambda: self.media_cmd("previous")).pack(side="left", padx=2)
        ttk.Button(r, text="⏯ Play/Pause", command=lambda: self.media_cmd("play-pause")).pack(side="left", padx=2)
        ttk.Button(r, text="⏭ Next", command=lambda: self.media_cmd("next")).pack(side="left", padx=2)
        ttk.Button(r, text="Refresh", command=self.update_media_ui).pack(side="left", padx=2)
        ttk.Button(r, text="Preview OLED", command=self.preview_media).pack(side="right", padx=2)
        ttk.Button(r, text="▶ Live OLED", command=self.start_media).pack(side="right", padx=2)
        ttk.Button(r, text="■ Stop", command=self.stop_live).pack(side="right", padx=2)
        if not playerctl_available():
            ttk.Label(p, text="playerctl is optional and is not currently detected. Install later with: sudo apt install playerctl", wraplength=760).pack(anchor="w", pady=10)

    def build_monitor_tab(self):
        p = self.monitor_tab.inner
        self.title_block(p, "System Monitor", "CPU/RAM use /proc. GPU usage appears when the Linux driver exposes gpu_busy_percent.")
        box = ttk.LabelFrame(p, text="Live statistics", padding=10); box.pack(fill="x")
        ttk.Label(box, textvariable=self.cpu_var, font=("Sans", 12, "bold")).pack(anchor="w", pady=3)
        ttk.Label(box, textvariable=self.ram_var, font=("Sans", 12, "bold")).pack(anchor="w", pady=3)
        ttk.Label(box, textvariable=self.gpu_var, font=("Sans", 12, "bold")).pack(anchor="w", pady=3)
        r = ttk.Frame(box); r.pack(fill="x", pady=(10, 0))
        ttk.Button(r, text="Preview OLED", command=self.preview_monitor).pack(side="left", padx=2)
        ttk.Button(r, text="▶ Live OLED", command=self.start_monitor).pack(side="left", padx=2)
        ttk.Button(r, text="■ Stop", command=self.stop_live).pack(side="left", padx=2)
        ttk.Label(p, text="Older Radeon drivers may report GPU as N/A. CPU and RAM still work.", wraplength=760).pack(anchor="w", pady=10)

    def build_settings_tab(self):
        p = self.settings_tab.inner
        self.title_block(p, "Profiles / Onboard Settings", "App profiles are fully supported. Direct onboard profile/brightness writes are intentionally disabled until the Apex 7 persistent HID protocol is verified.")
        box = ttk.LabelFrame(p, text="Apex OLED Studio profiles", padding=10); box.pack(fill="x")
        for i in range(5):
            nv = tk.StringVar(value=self.cfg["profiles"][i].get("name", f"Profile {i+1}"))
            self.profile_ui.append(nv)
            r = ttk.Frame(box); r.pack(fill="x", pady=4)
            ttk.Entry(r, textvariable=nv).pack(side="left", fill="x", expand=True)
            ttk.Button(r, text="Save App State", command=lambda n=i: self.save_profile(n)).pack(side="left", padx=2)
            ttk.Button(r, text="Load", command=lambda n=i: self.load_profile(n)).pack(side="left", padx=2)
        box = ttk.LabelFrame(p, text="Apex 7 onboard controls", padding=10); box.pack(fill="x", pady=8)
        ttk.Label(box, text=("Profile switching: SteelSeries Function key + Profile Switching key\n\n"
                             "Illumination brightness: SteelSeries Function key + Brightness Down / Brightness Up keys\n\n"
                             "These brightness keys control keyboard illumination, not the OLED framebuffer."),
                  wraplength=750, justify="left").pack(anchor="w")
        r = ttk.Frame(box); r.pack(fill="x", pady=(10, 0))
        ttk.Button(r, text="Direct Profile Write — Disabled", state="disabled").pack(side="left", padx=2)
        ttk.Button(r, text="Direct Brightness Write — Disabled", state="disabled").pack(side="left", padx=2)
        box = ttk.LabelFrame(p, text="Background / startup", padding=10); box.pack(fill="x", pady=8)
        ttk.Button(box, text="Install Linux Autostart", command=self.install_autostart).pack(side="left", padx=2)
        ttk.Button(box, text="Remove Autostart", command=self.remove_autostart).pack(side="left", padx=2)
        ttk.Button(box, text="Hide / Keep Running", command=self.hide_window).pack(side="left", padx=2)
        ttk.Button(box, text="Exit Completely", command=self.exit_app).pack(side="right", padx=2)

    def selected_device(self):
        i = self.device_combo.current()
        return self.devices[i] if 0 <= i < len(self.devices) else None

    def refresh_devices(self):
        try:
            self.devices = enumerate_apex()
        except Exception as e:
            self.devices = []
            self.status_var.set(f"Device detection error: {e}")
        vals = []
        for d in self.devices:
            pid = d["product_id"]
            vals.append(f"{DEVICES[pid][0]} [1038:{pid:04x}] interface {d.get('interface_number', '?')}")
        self.device_combo["values"] = vals
        if vals:
            self.device_combo.current(0)
            self.status_var.set(f"Detected {vals[0]}")
        else:
            self.device_var.set("")
            self.status_var.set("No supported Apex OLED interface detected")

    def test_device(self):
        d = self.selected_device()
        if not d:
            messagebox.showwarning("Keyboard", "No supported keyboard selected")
            return
        try:
            dev = hid.device(); dev.open_path(d["path"]); dev.close()
            messagebox.showinfo("Keyboard", f"Connection OK: {DEVICES[d['product_id']][0]}")
        except Exception as e:
            messagebox.showerror("Device open failed", f"{e}\n\nCheck the USB + hidraw udev rule and reconnect the keyboard.")

    def open_transport(self):
        d = self.selected_device()
        if not d:
            raise RuntimeError("No supported keyboard selected")
        self.transport.open(d["path"], d["product_id"])

    def output(self, img):
        out = threshold_image(img)
        return threshold_image(ImageOps.invert(out)) if self.invert_var.get() else out

    def set_preview(self, img):
        self.canvas_img = threshold_image(img)
        self.update_preview()

    def update_preview(self):
        img = self.output(self.canvas_img).resize((WIDTH * 4, HEIGHT * 4), Image.Resampling.NEAREST).convert("RGB")
        self.preview_photo = ImageTk.PhotoImage(img)
        self.preview.configure(image=self.preview_photo)

    def send_once(self, img):
        self.stop_live()
        try:
            self.open_transport(); self.transport.send(self.output(img)); self.status_var.set("OLED frame sent")
        except Exception as e:
            messagebox.showerror("OLED send failed", str(e))
        finally:
            self.transport.close()

    def send_current(self):
        self.send_once(self.canvas_img)

    def clear_oled(self):
        blank = Image.new("L", (WIDTH, HEIGHT), 0); self.set_preview(blank); self.send_once(blank)

    def text_image(self):
        return render_text(self.text_var.get(), self.text_size.get(), self.text_x.get(), self.text_y.get())

    def preview_text(self):
        self.stop_live(); self.set_preview(self.text_image()); self.status_var.set("Text preview")

    def send_text(self):
        img = self.text_image(); self.set_preview(img); self.send_once(img)

    def save_text_slot(self, i):
        nv, tv = self.text_slots_ui[i]
        s = {"name": nv.get() or f"Text {i+1}", "text": self.text_var.get(), "size": int(self.text_size.get()), "x": int(self.text_x.get()), "y": int(self.text_y.get())}
        self.cfg["text_slots"][i] = s; nv.set(s["name"]); tv.set(s["text"]); save_config(self.cfg)

    def load_text_slot(self, i):
        s = self.cfg["text_slots"][i]
        self.text_var.set(s.get("text", "")); self.text_size.set(s.get("size", 18)); self.text_x.set(s.get("x", 2)); self.text_y.set(s.get("y", 9)); self.preview_text()

    def send_text_slot(self, i):
        self.load_text_slot(i); self.send_text()

    def choose_image(self, i):
        f = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.webp *.gif"), ("All files", "*.*")])
        if not f: return
        try:
            src = Path(f); target = ASSET_DIR / f"image_slot_{i+1}{src.suffix.lower() or '.png'}"
            for old in ASSET_DIR.glob(f"image_slot_{i+1}.*"):
                try: old.unlink()
                except Exception: pass
            shutil.copy2(src, target)
            nv, pv = self.image_slots_ui[i]; self.cfg["image_slots"][i] = {"name": nv.get() or f"Image {i+1}", "path": str(target)}; pv.set(str(target)); save_config(self.cfg); self.preview_image(i)
        except Exception as e: messagebox.showerror("Image", str(e))

    def image_for_slot(self, i):
        p = self.cfg["image_slots"][i].get("path", "")
        if not p or not Path(p).exists(): raise FileNotFoundError(f"Image slot {i+1} is empty")
        return fit_to_oled(Image.open(p))

    def preview_image(self, i):
        self.stop_live()
        try: self.set_preview(self.image_for_slot(i)); self.status_var.set(f"Previewing image slot {i+1}")
        except Exception as e: messagebox.showerror("Image", str(e))

    def send_image_slot(self, i):
        try:
            img = self.image_for_slot(i); self.set_preview(img); self.send_once(img)
        except Exception as e: messagebox.showerror("Image", str(e))

    def clear_image_slot(self, i):
        p = self.cfg["image_slots"][i].get("path", "")
        if p:
            try: Path(p).unlink(missing_ok=True)
            except Exception: pass
        self.cfg["image_slots"][i]["path"] = ""; self.image_slots_ui[i][1].set(""); save_config(self.cfg)

    def sync_gifs(self):
        for i, (nv, pv, sv) in enumerate(self.gif_slots_ui):
            try: sec = max(1.0, float(sv.get()))
            except Exception: sec = 10.0
            self.cfg["gif_slots"][i] = {"name": nv.get() or f"GIF {i+1}", "path": pv.get(), "seconds": sec}

    def choose_gif(self, i):
        f = filedialog.askopenfilename(filetypes=[("GIF Animation", "*.gif"), ("All files", "*.*")])
        if not f: return
        try:
            target = ASSET_DIR / f"gif_slot_{i+1}.gif"; shutil.copy2(f, target)
            nv, pv, sv = self.gif_slots_ui[i]; pv.set(str(target)); self.sync_gifs(); self.gif_cache.pop(str(target), None); self.gif_frames(i); save_config(self.cfg); self.preview_gif(i)
        except Exception as e: messagebox.showerror("GIF", str(e))

    def gif_frames(self, i):
        p = self.cfg["gif_slots"][i].get("path", "")
        if not p or not Path(p).exists(): raise FileNotFoundError(f"GIF slot {i+1} is empty")
        if p not in self.gif_cache: self.gif_cache[p] = load_gif_frames(p)
        return self.gif_cache[p]

    def preview_gif(self, i):
        self.stop_live()
        try:
            frames, _ = self.gif_frames(i); self.set_preview(frames[0]); self.status_var.set(f"GIF slot {i+1}: {len(frames)} frames")
        except Exception as e: messagebox.showerror("GIF", str(e))

    def clear_gif(self, i):
        p = self.cfg["gif_slots"][i].get("path", ""); self.gif_cache.pop(p, None)
        if p:
            try: Path(p).unlink(missing_ok=True)
            except Exception: pass
        self.cfg["gif_slots"][i]["path"] = ""; self.gif_slots_ui[i][1].set(""); save_config(self.cfg)

    def playlist_slots(self):
        self.sync_gifs(); save_config(self.cfg)
        return [i for i, s in enumerate(self.cfg["gif_slots"]) if s.get("path") and Path(s["path"]).exists()]

    def start_playlist(self, oled):
        self.stop_live(); slots = self.playlist_slots()
        if not slots:
            messagebox.showinfo("GIF Playlist", "Add at least one GIF first"); return
        if oled:
            try: self.open_transport()
            except Exception as e: messagebox.showerror("Keyboard", str(e)); return
        self.live_mode = "gif_oled" if oled else "gif_preview"; self.playlist = slots; self.playlist_pos = self.frame_pos = 0; self.slot_started = time.monotonic(); self.paused = False; self.gif_tick()

    def gif_tick(self):
        if self.live_mode not in ("gif_oled", "gif_preview") or self.paused or not self.playlist: return
        i = self.playlist[self.playlist_pos]; s = self.cfg["gif_slots"][i]
        try: frames, delays = self.gif_frames(i)
        except Exception:
            self.advance_slot(); self.schedule(100, self.gif_tick); return
        if self.frame_pos >= len(frames): self.frame_pos = 0
        frame = frames[self.frame_pos]; self.set_preview(frame)
        if self.live_mode == "gif_oled":
            try: self.transport.send(self.output(frame))
            except Exception as e: self.stop_live(); messagebox.showerror("GIF OLED", str(e)); return
        delay = delays[self.frame_pos]; self.frame_pos += 1
        if time.monotonic() - self.slot_started >= max(1.0, float(s.get("seconds", 10))): self.advance_slot()
        self.status_var.set(f"GIF {i+1}/5 — {s.get('name','')} — frame {self.frame_pos}/{len(frames)}")
        self.schedule(delay, self.gif_tick)

    def advance_slot(self):
        self.playlist_pos += 1; self.frame_pos = 0; self.slot_started = time.monotonic()
        if self.playlist_pos >= len(self.playlist):
            if self.loop_var.get(): self.playlist_pos = 0
            else: self.stop_live()

    def pause_playlist(self):
        if self.live_mode not in ("gif_oled", "gif_preview"):
            self.status_var.set("No GIF playlist is playing"); return
        self.paused = not self.paused; self.cancel_timer()
        if self.paused: self.status_var.set("GIF playlist paused")
        else: self.slot_started = time.monotonic(); self.gif_tick()

    def save_active_playlist(self):
        self.sync_gifs(); self.cfg["active_playlist"] = {"enabled": True, "autoplay": bool(self.autoplay_var.get()), "loop": bool(self.loop_var.get())}; save_config(self.cfg)
        messagebox.showinfo("Active Playlist", "Saved. If you want it to start after login, enable Auto-play and click Install Autostart once.")

    def update_media_ui(self):
        info = media_info(); self.media_status.set((info["status"] + (f" — {info['player']}" if info["player"] else ""))); self.media_title.set(f"Title: {info['title']}"); self.media_artist.set(f"Artist: {info['artist']}")
        self.after(2000, self.update_media_ui)

    def media_cmd(self, cmd):
        if not playerctl_available(): messagebox.showinfo("Media", "playerctl is not installed"); return
        playerctl([cmd]); self.after(200, self.update_media_ui)

    def media_image(self):
        i = media_info(); return render_two_lines(i["title"] or "No active media", i["artist"] or i["status"], i["player"] or "MPRIS")

    def preview_media(self):
        self.stop_live(); self.set_preview(self.media_image())

    def start_media(self):
        self.stop_live()
        if not playerctl_available(): messagebox.showinfo("Media", "Install playerctl first: sudo apt install playerctl"); return
        try: self.open_transport()
        except Exception as e: messagebox.showerror("Keyboard", str(e)); return
        self.live_mode = "media"; self.media_tick()

    def media_tick(self):
        if self.live_mode != "media": return
        img = self.media_image(); self.set_preview(img)
        try: self.transport.send(self.output(img))
        except Exception as e: self.stop_live(); messagebox.showerror("Media OLED", str(e)); return
        self.schedule(1000, self.media_tick)

    def update_monitor_ui(self):
        s = self.stats.sample(); self.last_stats = s
        ct = f" | {s['cpu_temp']:.0f}°C" if s.get("cpu_temp") is not None else ""
        gt = f" | {s['gpu_temp']:.0f}°C" if s.get("gpu_temp") is not None else ""
        self.cpu_var.set(f"CPU: {s['cpu']:.1f}%{ct}")
        self.ram_var.set(f"RAM: {s['ram']:.1f}% ({s['used']:.1f}/{s['total']:.1f} GB)")
        self.gpu_var.set((f"GPU: {s['gpu']:.1f}%{gt}" if s.get("gpu") is not None else f"GPU: N/A{gt}"))
        self.after(1000, self.update_monitor_ui)

    def preview_monitor(self):
        self.stop_live(); self.set_preview(render_monitor(self.stats.sample()))

    def start_monitor(self):
        self.stop_live()
        try: self.open_transport()
        except Exception as e: messagebox.showerror("Keyboard", str(e)); return
        self.live_mode = "monitor"; self.monitor_tick()

    def monitor_tick(self):
        if self.live_mode != "monitor": return
        img = render_monitor(self.stats.sample()); self.set_preview(img)
        try: self.transport.send(self.output(img))
        except Exception as e: self.stop_live(); messagebox.showerror("Monitor OLED", str(e)); return
        self.schedule(1000, self.monitor_tick)

    def capture_state(self):
        self.sync_gifs(); return {"text_slots": self.cfg["text_slots"], "image_slots": self.cfg["image_slots"], "gif_slots": self.cfg["gif_slots"], "active_playlist": self.cfg["active_playlist"]}

    def save_profile(self, i):
        self.cfg["profiles"][i] = {"name": self.profile_ui[i].get() or f"Profile {i+1}", "data": self.capture_state()}; save_config(self.cfg); self.status_var.set(f"Saved app profile {i+1}")

    def load_profile(self, i):
        data = self.cfg["profiles"][i].get("data", {})
        if not data: messagebox.showinfo("Profile", "That profile is empty"); return
        for k in ("text_slots", "image_slots", "gif_slots", "active_playlist"):
            if k in data: self.cfg[k] = data[k]
        save_config(self.cfg); messagebox.showinfo("Profile", "Profile loaded. Restart the app to refresh all slot fields.")

    def schedule(self, ms, fn):
        self.cancel_timer(); self.live_after = self.after(max(20, int(ms)), fn)

    def cancel_timer(self):
        if self.live_after is not None:
            try: self.after_cancel(self.live_after)
            except Exception: pass
        self.live_after = None

    def stop_live(self):
        self.cancel_timer(); old = self.live_mode; self.live_mode = None; self.paused = False; self.transport.close()
        if old: self.status_var.set(f"Stopped {old}")

    def install_autostart(self):
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        py = Path(sys.executable).resolve(); script = Path(__file__).resolve()
        AUTOSTART_FILE.write_text(f"[Desktop Entry]\nType=Application\nName=Apex OLED Studio\nExec={py} {script} --autostart\nTerminal=false\nX-GNOME-Autostart-enabled=true\n", encoding="utf-8")
        self.cfg["active_playlist"]["autoplay"] = bool(self.autoplay_var.get()); save_config(self.cfg)
        messagebox.showinfo("Autostart", f"Installed:\n{AUTOSTART_FILE}")

    def remove_autostart(self):
        try: AUTOSTART_FILE.unlink(missing_ok=True); self.status_var.set("Autostart removed")
        except Exception as e: messagebox.showerror("Autostart", str(e))

    def autostart_begin(self):
        self.refresh_devices()
        if self.cfg.get("active_playlist", {}).get("enabled") and self.autoplay_var.get():
            self.start_playlist(True)
            if self.live_mode == "gif_oled": self.withdraw()

    def hide_window(self):
        if not self.live_mode:
            messagebox.showinfo("Background", "Start GIF, Media, or System Monitor live OLED mode first."); return
        self.withdraw()

    def close_window(self):
        if self.live_mode: self.withdraw()
        else: self.exit_app()

    def exit_app(self):
        self.stop_live(); self.destroy()


if __name__ == "__main__":
    ensure_dirs()
    ApexOLEDStudio().mainloop()
