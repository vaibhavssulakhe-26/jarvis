"""Jarvis's face: a holographic, Blade Runner style window with a live transcript."""
import html
import math
import os
import random
import signal
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PyQt6.QtCore import QLockFile, QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QFont, QIcon, QKeySequence, QLinearGradient,
                         QPainter, QPen, QPixmap, QRadialGradient, QShortcut)
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QTextEdit, QVBoxLayout, QWidget)

from ..actions import browser, events, mpvctl, procs
from ..brain import brain
from ..core import config, main as core, state
from ..voice import voice, voices

AMBER = QColor("#ff9a1f")
ORANGE = QColor("#ff6a1a")
TEAL = QColor("#2ee6d6")
SAND = QColor("#f2d3a0")
SLATE = QColor("#6b7a99")

PALETTE = {
    "listening": (TEAL, AMBER, 1.0),
    "thinking": (AMBER, TEAL, 1.0),
    "speaking": (ORANGE, AMBER, 1.0),
    "muted": (AMBER, ORANGE, 0.6),
    "asleep": (SLATE, SLATE, 0.35),
}
LABELS = {"listening": "LISTENING", "thinking": "THINKING", "speaking": "SPEAKING",
          "muted": "VOICE MUTED", "asleep": "ASLEEP"}

QSS = """
QWidget { background: #07090b; color: #f2d3a0; font-family: "JetBrains Mono", "DejaVu Sans Mono", "Noto Sans Mono", monospace; font-size: 10pt; }
QTextEdit { background: #0a0c0e; border: 1px solid #5a3510; padding: 8px; selection-background-color: #ff9a1f; selection-color: #000000; }
QLineEdit { background: #0b0d10; border: 1px solid #ff9a1f; padding: 8px 10px; color: #ffd9a0; }
QLineEdit:focus { border: 1px solid #2ee6d6; }
QPushButton { background: #0b0d10; border: 1px solid #5a3510; padding: 7px 10px; color: #f2d3a0; }
QPushButton:hover { border: 1px solid #ff9a1f; color: #ffffff; }
QPushButton:checked { background: #3a1d08; border: 1px solid #ff6a1a; color: #ffb066; }
QLabel#tag { color: #2ee6d6; font-weight: bold; }
"""


def mix(a, b, f):
    f = max(0.0, min(1.0, f))
    return QColor(int(a.red() + (b.red() - a.red()) * f),
                  int(a.green() + (b.green() - a.green()) * f),
                  int(a.blue() + (b.blue() - a.blue()) * f))


def current_mode():
    st = state.read()
    if st["paused"]:
        return "asleep"
    if voice.SPEAKING.is_set():
        return "speaking"
    if st["activity"] == "thinking" and time.time() - float(st["activity_at"]) < 60:
        return "thinking"
    if st["muted"]:
        return "muted"
    return "listening"


def hud_lines():
    stt = "GROQ WHISPER" if config.stt_cloud() else "LOCAL WHISPER"
    if config.get("GROQ_API_KEY"):
        brain_name = "GROQ " + brain.MODEL.split("/")[-1].upper()
    else:
        brain_name = "LOCAL ONLY"
    return [("BRAIN", brain_name), ("EARS", stt), ("WAKE", config.wake_label()),
            ("VOICE", voices.current_name().upper())]


class Stage(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(520, 420)
        self.t0 = time.time()
        self.mode = "listening"
        self.amp = 0.05
        self.pulse_at = 0.0
        self.glitch_until = 0.0
        self.next_glitch = time.time() + 3.0
        self.glitch_rows = {}
        self.parts = [self._particle(True) for _ in range(44)]
        self.scan = self._scan_tile()
        self.readouts = hud_lines()
        self.mono = QFont()
        self.mono.setFamilies(["JetBrains Mono", "DejaVu Sans Mono", "Noto Sans Mono", "monospace"])
        self.mono.setStyleHint(QFont.StyleHint.Monospace)
        self.mono.setPointSize(9)
        try:
            fps = max(6, min(40, int(config.get("JARVIS_UI_FPS", "12") or 12)))
        except ValueError:
            fps = 12
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.base_ms = int(1000 / fps)
        self.timer.start(self.base_ms)

    @staticmethod
    def _particle(initial):
        return [random.random(), random.random() if initial else 1.03,
                random.uniform(0.0012, 0.0042), random.uniform(1.0, 2.6),
                random.uniform(0.0, 6.28), random.random() < 0.4]

    @staticmethod
    def _scan_tile():
        pm = QPixmap(1, 4)
        pm.fill(Qt.GlobalColor.transparent)
        q = QPainter(pm)
        q.fillRect(0, 3, 1, 1, QColor(0, 0, 0, 80))
        q.end()
        return pm

    def tick(self):
        win = self.window()
        if not win.isVisible() or win.isMinimized():
            return
        want = self.base_ms if win.isActiveWindow() else max(self.base_ms, 150)
        if self.timer.interval() != want:
            self.timer.setInterval(want)
        now = time.time()
        t = now - self.t0
        self.mode = current_mode()
        if self.mode == "speaking":
            target = 0.55 + 0.35 * abs(math.sin(t * 7.3)) * (0.6 + 0.4 * math.sin(t * 2.1)) + 0.1 * random.random()
        elif self.mode == "listening":
            target = 0.08 + 0.7 * min(1.0, events.level * 12.0)
        elif self.mode == "thinking":
            target = 0.25 + 0.15 * math.sin(t * 5.0)
        elif self.mode == "muted":
            target = 0.08
        else:
            target = 0.03
        self.amp += (target - self.amp) * 0.35
        if now > self.next_glitch:
            self.glitch_until = now + random.uniform(0.08, 0.2)
            self.next_glitch = now + random.uniform(1.5 if self.mode == "speaking" else 2.5, 6.0)
            self.glitch_rows = {random.randrange(0, 90): random.randint(-18, 18)
                                for _ in range(random.randint(3, 9))}
        for q in self.parts:
            q[1] -= q[2] * (1.0 + self.amp * 2.0)
            if q[1] < -0.03:
                q[:] = self._particle(False)
        self.update()

    def _brackets(self, p, w, h, color):
        p.setPen(QPen(color, 1.5))
        m, length = 12, 24
        for sx, sy in ((m, m), (w - m, m), (m, h - m), (w - m, h - m)):
            dx = length if sx < w / 2 else -length
            dy = length if sy < h / 2 else -length
            p.drawLine(QPointF(sx, sy), QPointF(sx + dx, sy))
            p.drawLine(QPointF(sx, sy), QPointF(sx, sy + dy))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        t = time.time() - self.t0
        main_c, acc_c, dim = (QColor(PALETTE[self.mode][0]), QColor(PALETTE[self.mode][1]),
                              PALETTE[self.mode][2])

        # haze
        bg = QRadialGradient(QPointF(w * 0.5, h * 0.86), max(w, h) * 0.85)
        bg.setColorAt(0.0, QColor(int(92 * dim), int(44 * dim), int(12 * dim)))
        bg.setColorAt(0.45, QColor(int(30 * dim), int(16 * dim), int(8 * dim)))
        bg.setColorAt(1.0, QColor(6, 7, 9))
        p.fillRect(self.rect(), QBrush(bg))

        # floor grid
        horizon = h * 0.74
        gcol = QColor(main_c)
        gcol.setAlpha(int(46 * dim))
        p.setPen(QPen(gcol, 1))
        for i in range(-14, 15):
            p.drawLine(QPointF(w * 0.5 + i * w * 0.012, horizon), QPointF(w * 0.5 + i * w * 0.11, h))
        for k in range(9):
            f = (k + (t * 0.35) % 1.0) / 9.0
            y = horizon + (h - horizon) * (f * f)
            p.drawLine(QPointF(0, y), QPointF(w, y))
        hc = QColor(acc_c)
        hc.setAlpha(int(150 * dim))
        p.setPen(QPen(hc, 1.2))
        p.drawLine(QPointF(0, horizon), QPointF(w, horizon))

        # hologram globe
        cx, cy = w * 0.5, h * 0.40
        R = min(w * 0.27, h * 0.27)
        glow = QRadialGradient(QPointF(cx, cy), R * 1.9)
        gc = QColor(main_c)
        gc.setAlpha(int((40 + 60 * self.amp) * dim))
        glow.setColorAt(0.0, gc)
        gc2 = QColor(main_c)
        gc2.setAlpha(0)
        glow.setColorAt(1.0, gc2)
        p.setPen(Qt.PenStyle.NoPen)
        p.fillRect(QRectF(cx - R * 2, cy - R * 2, R * 4, R * 4), QBrush(glow))

        glitching = time.time() < self.glitch_until
        slices = max(10, int(R * 2 / 5.0))
        for i in range(slices):
            fy = (i + 0.5) / slices
            dy = (fy - 0.5) * 2.0
            base = math.sqrt(max(0.0, 1.0 - dy * dy))
            wob = 1.0 + self.amp * 0.22 * math.sin(t * 6.0 + dy * 9.0) + 0.04 * math.sin(t * 1.3 + dy * 3.0)
            half = R * base * wob
            if half < 1.0:
                continue
            y = cy - R + fy * 2.0 * R
            off = float(self.glitch_rows.get(i % 90, 0)) if glitching else 0.0
            col = mix(main_c, acc_c, fy)
            alpha = (120 + 90 * base) * dim
            if i % 2:
                alpha *= 0.55
            alpha *= 0.85 + 0.15 * math.sin(t * 23.0 + i)
            col.setAlpha(max(0, min(255, int(alpha))))
            p.setPen(QPen(col, 1.4))
            p.drawLine(QPointF(cx - half + off, y), QPointF(cx + half + off, y))

        # rings
        p.setBrush(Qt.BrushStyle.NoBrush)
        spin = 2.2 if self.mode == "thinking" else 1.0
        for k in range(3):
            tilt = 0.28 + 0.1 * k
            ang = t * (0.6 + 0.35 * k) * spin + k * 2.1
            rr = R * (1.18 + 0.16 * k)
            rc = QColor(acc_c if k % 2 else main_c)
            rc.setAlpha(int(120 * dim))
            p.setPen(QPen(rc, 1.2))
            p.save()
            p.translate(cx, cy)
            p.rotate(math.degrees(ang) * 0.15 + k * 25)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(-rr, -rr * tilt, 2 * rr, 2 * rr * tilt))
            p.setBrush(QBrush(rc))
            p.drawEllipse(QPointF(rr * math.cos(ang * 2.0), rr * tilt * math.sin(ang * 2.0)), 3, 3)
            p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)

        # wake pulse
        age = time.time() - self.pulse_at
        if 0.0 <= age < 0.9:
            f = age / 0.9
            pc = QColor(TEAL)
            pc.setAlpha(int(200 * (1.0 - f)))
            p.setPen(QPen(pc, 2))
            p.drawEllipse(QPointF(cx, cy), R * (1.05 + f * 0.9), R * (1.05 + f * 0.9))

        # muted slash
        if self.mode == "muted":
            p.setPen(QPen(QColor(255, 106, 26, 220), 3))
            p.drawLine(QPointF(cx - R * 0.6, cy + R * 0.6), QPointF(cx + R * 0.6, cy - R * 0.6))

        # equalizer
        n = 56
        bw = w * 0.5 / n
        x0 = w * 0.25
        for i in range(n):
            e = abs(math.sin(t * 3.1 + i * 0.7)) * (0.35 + 0.65 * abs(math.sin(t * 1.7 + i * 0.31)))
            hh = 4 + (h * 0.12) * self.amp * e * (1.0 - abs(i - n / 2) / (n / 2) * 0.6)
            bc = QColor(acc_c)
            bc.setAlpha(int(150 * dim))
            p.fillRect(QRectF(x0 + i * bw + 1, horizon - 14 - hh, max(1.0, bw - 2), hh), bc)

        # particles
        p.setPen(Qt.PenStyle.NoPen)
        for x, y, sp, size, ph, acc in self.parts:
            c = QColor(acc_c if acc else main_c)
            c.setAlpha(int((40 + 110 * (0.5 + 0.5 * math.sin(t * 2.0 + ph))) * dim))
            p.setBrush(QBrush(c))
            p.drawEllipse(QPointF(x * w + 9 * math.sin(t * 0.8 + ph), y * h), size, size)

        # sweep and scanlines
        sweep = ((t * 0.12) % 1.0) * h
        sg = QLinearGradient(0, sweep - 40, 0, sweep + 40)
        s0 = QColor(main_c)
        s0.setAlpha(0)
        s1 = QColor(main_c)
        s1.setAlpha(int(34 * dim))
        sg.setColorAt(0.0, s0)
        sg.setColorAt(0.5, s1)
        sg.setColorAt(1.0, s0)
        p.fillRect(QRectF(0, sweep - 40, w, 80), QBrush(sg))
        p.fillRect(self.rect(), QBrush(self.scan))

        # vignette
        vg = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.75)
        vg.setColorAt(0.55, QColor(0, 0, 0, 0))
        vg.setColorAt(1.0, QColor(0, 0, 0, 190))
        p.fillRect(self.rect(), QBrush(vg))

        # HUD
        hud = QColor(SAND)
        hud.setAlpha(int(210 * dim))
        br = QColor(AMBER)
        br.setAlpha(int(200 * dim))
        self._brackets(p, w, h, br)
        p.setFont(self.mono)
        p.setPen(hud)
        p.drawText(QPointF(26, 32), "A N A   //   VOICE INTERFACE")
        p.drawText(QRectF(0, 18, w - 26, 20), Qt.AlignmentFlag.AlignRight,
                   datetime.now().strftime("%a %d %b  %H:%M:%S").upper())
        for i, (k, v) in enumerate(self.readouts):
            y = h - 26 - (len(self.readouts) - 1 - i) * 16
            p.setPen(QColor(AMBER.red(), AMBER.green(), AMBER.blue(), int(200 * dim)))
            p.drawText(QPointF(26, y), k)
            p.setPen(hud)
            p.drawText(QPointF(86, y), v)
        big = QFont(self.mono)
        big.setPointSize(15)
        big.setBold(True)
        big.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 5)
        p.setFont(big)
        lc = QColor(main_c)
        lc.setAlpha(int(255 * dim))
        p.setPen(lc)
        cursor = "_" if int(t * 2) % 2 == 0 else " "
        p.drawText(QRectF(0, cy + R + 16, w, 34),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   LABELS[self.mode] + cursor)
        p.end()


def shutdown_all():
    """Kill mpv, the controlled browser and every child process, and save the conversation summary."""
    mpvctl.stop()
    procs.stop_all()
    browser.shutdown()
    brain.finish()


class Bus(QObject):
    line = pyqtSignal(str, str)


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JARVIS")
        icon = config.ROOT / "assets" / "jarvis.png"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.resize(1120, 680)
        self.setStyleSheet(QSS)
        self.bus = Bus()
        self.bus.line.connect(self.add_line)
        events.listeners.append(lambda kind, text: self.bus.line.emit(kind, text))

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.stage = Stage()
        root.addWidget(self.stage, 3)

        panel = QWidget()
        panel.setMinimumWidth(380)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 14, 14, 14)
        pl.setSpacing(10)
        tag = QLabel("TRANSCRIPT")
        tag.setObjectName("tag")
        pl.addWidget(tag)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(500)
        pl.addWidget(self.log, 1)
        self.input = QLineEdit()
        self.input.setPlaceholderText("type a command, or say " + config.wake_label().title() + " ...")
        self.input.returnPressed.connect(self.send)
        pl.addWidget(self.input)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_talk = QPushButton("TALK")
        self.btn_talk.clicked.connect(self.talk)
        self.btn_stop = QPushButton("STOP")
        self.btn_stop.clicked.connect(self.stop_all)
        self.btn_mute = QPushButton("MUTE")
        self.btn_mute.setCheckable(True)
        self.btn_mute.toggled.connect(lambda on: state.update(muted=bool(on)))
        self.btn_sleep = QPushButton("SLEEP")
        self.btn_sleep.setCheckable(True)
        self.btn_sleep.toggled.connect(lambda on: state.update(paused=bool(on)))
        self.btn_pin = QPushButton("PIN")
        self.btn_pin.setCheckable(True)
        self.btn_pin.toggled.connect(self.toggle_pin)
        self.btn_quit = QPushButton("QUIT")
        self.btn_quit.clicked.connect(self.quit_app)
        for b in (self.btn_talk, self.btn_stop, self.btn_mute, self.btn_sleep, self.btn_pin, self.btn_quit):
            row.addWidget(b)
        pl.addLayout(row)
        root.addWidget(panel, 2)

        QShortcut(QKeySequence("F11"), self).activated.connect(self.toggle_full)
        QShortcut(QKeySequence("Esc"), self).activated.connect(self.leave_full)
        QShortcut(QKeySequence("Ctrl+."), self).activated.connect(self.btn_stop.click)
        QShortcut(QKeySequence("Ctrl+M"), self).activated.connect(self.btn_mute.toggle)
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(self.quit_app)

        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.sync)
        self.sync_timer.start(600)

    def sync(self):
        st = state.read()
        for btn, key in ((self.btn_mute, "muted"), (self.btn_sleep, "paused")):
            if btn.isChecked() != bool(st[key]):
                btn.blockSignals(True)
                btn.setChecked(bool(st[key]))
                btn.blockSignals(False)

    def add_line(self, kind, text):
        if kind == "sys" and text.startswith("wake"):
            self.stage.pulse_at = time.time()
        stamp = datetime.now().strftime("%H:%M")
        who, color = {"you": ("YOU", "#2ee6d6"), "jarvis": ("JARVIS", "#ffb347")}.get(kind, ("SYS", "#8a7a60"))
        body = html.escape(text).replace("\n", "<br>")
        self.log.append(
            f'<div style="margin-bottom:7px"><span style="color:#6f6250">{stamp}</span>&nbsp; '
            f'<span style="color:{color}"><b>{who}</b></span>&nbsp; '
            f'<span style="color:#f2d3a0">{body}</span></div>')

    def send(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        events.emit("you", text)
        threading.Thread(target=self._run, args=(text,), daemon=True).start()

    def _run(self, text):
        try:
            core.handle(text)
        except Exception as e:
            events.emit("sys", f"error: {type(e).__name__}")
            traceback.print_exc()

    def talk(self):
        state.update(talk_request=time.time(), paused=False)

    def toggle_pin(self, on):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(on))
        self.show()

    def toggle_full(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def leave_full(self):
        if self.isFullScreen():
            self.showNormal()

    def stop_all(self):
        state.update(stop_at=time.time())
        mpvctl.stop()

    def quit_app(self):
        state.update(activity="idle")
        shutdown_all()
        os._exit(0)

    def closeEvent(self, ev):
        self.quit_app()


def service_active(name):
    try:
        return subprocess.run(["systemctl", "--user", "is-active", "--quiet", name],
                              timeout=3).returncode == 0
    except Exception:
        return False


def start_core():
    background = service_active("jarvis-reminders") or service_active("jarvis")
    if background:
        events.emit("sys", "reminders are handled by a background service")
    core.start(watch_reminders=not background)

    def run():
        try:
            core.listen()
        except SystemExit as e:
            events.emit("sys", str(e))
        except Exception as e:
            events.emit("sys", f"my ears stopped: {type(e).__name__}")
            traceback.print_exc()

    threading.Thread(target=run, daemon=True).start()


def main():
    lock_dir = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    lock = QLockFile(os.path.join(lock_dir, "jarvis_ui.lock"))
    if not lock.tryLock(100):
        print("Jarvis is already running.")
        return
    app = QApplication(sys.argv)
    app.setApplicationName("Jarvis")
    win = Window()
    win.show()
    win.add_line("sys", "Say " + config.wake_label().title() + ", then your command. Or type below. F11 toggles full screen.")
    start_core()
    signal.signal(signal.SIGTERM, lambda *a: win.quit_app())
    signal.signal(signal.SIGINT, lambda *a: win.quit_app())
    ticker = QTimer()
    ticker.start(500)
    ticker.timeout.connect(lambda: None)
    code = app.exec()
    mpvctl.stop()
    os._exit(code)


if __name__ == "__main__":
    main()
