"""The dashboard window: sidebar, top bar, centre pages, bottom bar, tray icon. The voice loop runs in a background thread and
talks to the window through Qt signals, so the window works with the microphone off and everything can be typed."""
import os
import sys
import threading
import time
import traceback
from datetime import datetime

import psutil
from PyQt6.QtCore import QObject, QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QStackedWidget,
                             QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget)

from ...actions import events, mpvctl
from ...core import config, state
from . import icons, pages, themes
from .theme import Theme
from .widgets import Clock, Waveform

NAV = (("Home", pages.Home), ("Media", pages.Media), ("Code", pages.Code), ("Notes", pages.Notes), ("Study", pages.Study),
       ("Web", pages.Web), ("Stats", pages.Stats), ("Settings", pages.Settings))
POLL_MS = 500
PAGE_MS = 2000
LOW_RAM_GB = 1.5
CHIP_RAM_GB = 1.0
OK_RAM_GB = 2.0
ERROR_SECONDS = 5


class Bus(QObject):
    line = pyqtSignal(str, str)


def current_mode():
    """idle, listening, thinking, speaking or error-free names the orb understands, plus a label for the status chip."""
    from ...voice import voice
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


class Dashboard(QWidget):
    def __init__(self, theme=None):
        super().__init__()
        self.setWindowTitle("JARVIS")
        self.resize(*themes.load_window())
        self.setMinimumSize(980, 640)
        self._size_timer = QTimer(self)
        self._size_timer.setSingleShot(True)
        self._size_timer.timeout.connect(lambda: themes.save_window(self.width(), self.height()))
        self.theme = theme or Theme()
        self.clock = Clock()
        self.ctx = pages.Context(self.theme, self.clock, self.run_command)
        self.low_manual = themes.load()[2]["low_power"]
        self.low_auto = False
        self.error_until = 0.0
        self.seen_theme = float(state.get("theme_at") or 0)
        self.tray = None
        self.pages = {}
        self.bus = Bus()
        self.bus.line.connect(self.on_event)
        self._listener = lambda kind, text: self.bus.line.emit(kind, text)
        events.listeners.append(self._listener)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._sidebar())
        main = QVBoxLayout()
        main.setContentsMargins(14, 10, 14, 10)
        main.setSpacing(10)
        main.addLayout(self._topbar())
        self.confirm = pages.ConfirmBar(self.ctx)
        main.addWidget(self.confirm)
        self.stack = QStackedWidget()
        for name, cls in NAV:
            page = cls(self.ctx, self) if cls is pages.Settings else cls(self.ctx)
            self.pages[name] = page
            self.stack.addWidget(page)
        main.addWidget(self.stack, 1)
        main.addLayout(self._bottombar())
        root.addLayout(main, 1)

        self.theme.changed.connect(self.restyle)
        self.restyle()
        QShortcut(QKeySequence("Ctrl+."), self).activated.connect(self.stop_all)
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(self.quit_all)
        QShortcut(QKeySequence("F11"), self).activated.connect(self.toggle_full)
        self.poll = QTimer(self)
        self.poll.timeout.connect(self.tick)
        self.poll.start(POLL_MS)
        self.page_timer = QTimer(self)
        self.page_timer.timeout.connect(self.refresh_page)
        self.page_timer.start(PAGE_MS)
        self._ticks = 0
        self.apply_low_power()
        self.go("Home")
        self.make_tray()
        self.check_ollama()

    # ---------- building ----------
    def _sidebar(self):
        side = QWidget()
        side.setFixedWidth(176)
        box = QVBoxLayout(side)
        box.setContentsMargins(0, 14, 0, 14)
        title = QLabel("J.A.R.V.I.S")
        title.setObjectName("brand")
        title.setContentsMargins(16, 4, 8, 16)
        title.setMinimumHeight(40)
        box.addWidget(title)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.nav = {}
        for name, _ in NAV:
            b = QPushButton("  " + name.upper())
            b.setObjectName("nav")
            b.setIconSize(QSize(20, 20))
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, n=name: self.go(n))
            self.group.addButton(b)
            self.nav[name] = b
            box.addWidget(b)
        box.addStretch(1)
        return side

    def _topbar(self):
        row = QHBoxLayout()
        self.clock_label = QLabel("")
        self.clock_label.setObjectName("clock")
        self.ram_chip = QLabel("LOW RAM")
        self.ram_chip.setObjectName("cap")
        self.ram_chip.setContentsMargins(10, 2, 10, 2)
        self.ram_chip.setVisible(False)
        self.search = QLineEdit()
        self.search.setPlaceholderText("search notes")
        self.search.setMaximumWidth(280)
        self.search.returnPressed.connect(self.global_search)
        self.chip = QLabel("")
        self.chip.setObjectName("cap")
        self.chip.setContentsMargins(10, 2, 10, 2)
        self.theme_btn = QPushButton("THEME")
        self.theme_btn.clicked.connect(lambda: self.set_theme(themes.pick("next", self.theme.name if self.theme.name != "custom" else "")))
        row.addWidget(self.clock_label)
        row.addStretch(1)
        row.addWidget(self.search)
        row.addWidget(self.ram_chip)
        row.addWidget(self.chip)
        row.addWidget(self.theme_btn)
        return row

    def _bottombar(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        self.wave = Waveform(self.theme, self.clock)
        self.talk_btn = QPushButton("Talk to Jarvis")
        self.talk_btn.setObjectName("talk")
        self.talk_btn.clicked.connect(self.talk)
        self.cmd = QLineEdit()
        self.cmd.setPlaceholderText("type a command, or say " + config.wake_label().title() + " ...")
        self.cmd.returnPressed.connect(self.send)
        self.quick = QToolButton()
        self.quick.setText("Quick commands")
        self.quick.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.quick)
        for text in pages.QUICK:
            act = QAction(text, menu)
            act.triggered.connect(lambda _=False, c=text: self.run_command(c))
            menu.addAction(act)
        self.quick.setMenu(menu)
        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setObjectName("stop")
        self.stop_btn.clicked.connect(self.stop_all)
        for w in (self.wave, self.talk_btn):
            row.addWidget(w)
        row.addWidget(self.cmd, 1)
        row.addWidget(self.quick)
        row.addWidget(self.stop_btn)
        return row

    # ---------- theme ----------
    def restyle(self):
        self.setStyleSheet(self.theme.qss())
        for name, button in self.nav.items():
            button.setIcon(icons.make(name, self.theme.accent if button.isChecked() else self.theme.text))
        self.update()

    def set_theme(self, name):
        if name:
            self.theme.set_name(name)
            themes.save(name)

    def set_hue(self, hue):
        self.theme.set_hue(hue)

    def set_ui_flag(self, key, on):
        themes.save(**{key: bool(on)})
        self.theme.set_flags(**{key: bool(on)})

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), self.theme.bg)

    # ---------- low power, visibility ----------
    def apply_low_power(self):
        low = self.low_manual or self.low_auto
        self.clock.set_low(low)
        home = self.pages.get("Home")
        if home:
            home.orb.set_low(low)

    def set_low_power(self, on):
        self.low_manual = bool(on)
        themes.save(low_power=bool(on))
        self.apply_low_power()

    def sync_visibility(self):
        self.clock.set_visible(self.isVisible() and not self.isMinimized() and self.windowState() != Qt.WindowState.WindowMinimized)

    def showEvent(self, ev):
        super().showEvent(ev)
        self.sync_visibility()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.sync_visibility()

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type().name == "WindowStateChange":
            self.sync_visibility()

    # ---------- navigation and refresh ----------
    def go(self, name):
        self.nav[name].setChecked(True)
        self.restyle()
        self.stack.setCurrentWidget(self.pages[name])
        self.refresh_page()

    def refresh_page(self):
        if not self.isVisible() and not os.environ.get("JARVIS_DASH_TEST"):
            return
        page = self.stack.currentWidget()
        try:
            page.refresh()
        except Exception as e:
            events.emit("sys", f"error: page refresh failed ({type(e).__name__})")
            traceback.print_exc()
        self.confirm.refresh() if page is not self.pages["Web"] else None

    def global_search(self):
        q = self.search.text().strip()
        notes = self.pages["Notes"]
        notes.search.setText(q)
        self.go("Notes")
        notes.do_search()

    def tick(self):
        self._ticks += 1
        mode = current_mode()
        self.ctx.mode = mode
        orb_mode = mode if mode in ("listening", "thinking", "speaking") else "idle"
        self.pages["Home"].orb.set_mode(orb_mode)
        err = time.time() < self.error_until
        self.theme.set_state("error" if err else orb_mode if orb_mode != "speaking" else "idle")
        colour = self.theme.bad if err else self.theme.accent
        self.chip.setText(("ERROR" if err else mode.upper()))
        self.chip.setStyleSheet(f"color: {colour.name()}; border: 1px solid {colour.name()}; border-radius: 9px;")
        self.clock_label.setText(datetime.now().strftime("%a %d %b  %H:%M:%S").upper())
        at = float(state.get("theme_at") or 0)
        if at > self.seen_theme:
            self.seen_theme = at
            self.theme.reload_saved()
        if self._ticks % 10 == 0:
            free = psutil.virtual_memory().available / 2 ** 30
            self.ram_chip.setVisible(free < CHIP_RAM_GB)
            self.ram_chip.setStyleSheet(f"color: {self.theme.bad.name()}; border: 1px solid {self.theme.bad.name()}; border-radius: 9px;")
            if free < LOW_RAM_GB and not self.low_auto:
                self.low_auto = True
                self.apply_low_power()
            elif free > OK_RAM_GB and self.low_auto:
                self.low_auto = False
                self.apply_low_power()
        if self._ticks % 40 == 0:
            self.check_ollama()

    def check_ollama(self):
        def go():
            try:
                from ...brain import brain
                self.ctx.ollama = bool(brain._ollama_up())
            except Exception:
                self.ctx.ollama = False
        threading.Thread(target=go, daemon=True).start()

    # ---------- events from the voice loop ----------
    def on_event(self, kind, text):
        stamp = datetime.now().strftime("%H:%M")
        feed = self.ctx.feed
        if kind == "you":
            feed.append(dict(time=stamp, heard=text, route="", provider=""))
            del feed[:-30]
        elif kind == "route" and feed:
            feed[-1]["route"] = text
        elif kind == "provider" and feed:
            feed[-1]["provider"] = text
        elif kind in ("sys", "jarvis"):
            self.ctx.log.append(f"{stamp} {'JARVIS' if kind == 'jarvis' else 'SYS'}  {text[:300]}")
            del self.ctx.log[:-200]
            if kind == "sys" and any(w in text.lower() for w in ("error", "stopped", "failed")):
                self.error_until = time.time() + ERROR_SECONDS

    # ---------- commands ----------
    def run_command(self, text):
        text = str(text).strip()
        if not text:
            return
        events.emit("you", text)
        threading.Thread(target=self._run, args=(text,), daemon=True).start()

    def _run(self, text):
        from ...core import main as core
        try:
            core.handle(text)
        except Exception as e:
            events.emit("sys", f"error: {type(e).__name__}")
            traceback.print_exc()

    def send(self):
        text = self.cmd.text().strip()
        self.cmd.clear()
        self.run_command(text)

    def talk(self):
        state.update(talk_request=time.time(), paused=False)

    def stop_all(self):
        state.update(stop_at=time.time())
        mpvctl.stop()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._size_timer.start(800)

    def toggle_full(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    # ---------- tray, close, quit ----------
    def make_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon_file = config.ROOT / "assets" / "jarvis.png"
        if icon_file.exists():
            icon = QIcon(str(icon_file))
        else:
            icon = QIcon(self.theme.glow(64).copy())
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        menu = QMenu()
        for text, fn in (("Show", self.bring_up), ("Talk to Jarvis", self.talk), ("Stop", self.stop_all), ("Quit", self.quit_all)):
            act = QAction(text, menu)
            act.triggered.connect(lambda _=False, f=fn: f())
            menu.addAction(act)
        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.bring_up() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def bring_up(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, ev):
        """Close goes to the tray. Without a tray there is nowhere to hide, so close quits."""
        if getattr(self, "quitting", False):
            ev.accept()
        elif self.tray is not None and self.tray.isVisible():
            ev.ignore()
            self.hide()
        else:
            self.quit_all()

    def quit_all(self, exit_process=True):
        """Kill mpv, the browser and every child process, then leave."""
        from .. import ui
        self.quitting = True
        themes.save_window(self.width(), self.height())
        state.update(activity="idle")
        ui.shutdown_all()
        if self._listener in events.listeners:
            events.listeners.remove(self._listener)
        if self.tray is not None:
            self.tray.hide()
        if exit_process:
            os._exit(0)
        self.close()


def run(with_core=True):
    from PyQt6.QtCore import QLockFile
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    lock = QLockFile(os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "jarvis_ui.lock"))
    if not lock.tryLock(100):
        print("Jarvis is already running.")
        return
    app = QApplication(sys.argv)
    app.setApplicationName("Jarvis")
    app.setQuitOnLastWindowClosed(False)
    win = Dashboard()
    win.show()
    events.emit("sys", "Say " + config.wake_label().title() + ", or type below. Close hides to the tray; Quit stops everything.")
    if with_core:
        from .. import ui
        ui.start_core()
    import signal
    signal.signal(signal.SIGTERM, lambda *a: win.quit_all())
    signal.signal(signal.SIGINT, lambda *a: win.quit_all())
    ticker = QTimer()
    ticker.timeout.connect(lambda: None)
    ticker.start(500)
    code = app.exec()
    win.quit_all(exit_process=False)
    os._exit(code)
