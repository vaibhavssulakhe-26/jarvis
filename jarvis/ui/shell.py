"""The new window. The globe screen opens fullscreen with nothing else on it; the bubbles are one scroll below; each bubble opens one of the existing
dashboard pages with a way back. The classic dashboard still runs underneath as the engine (events, tray, quitting) and as the source of those pages;
`python -m jarvis.main --classic` shows it as it was."""
import os
import traceback

from PyQt6.QtCore import QEvent, QTimer, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from .. import features
from ..actions import events
from ..core import profile, state
from . import design, status
from .bottom import HEIGHT as BOTTOM_HEIGHT, BottomPanel
from .bubbles import NAMES
from .cmdk import CommandPalette
from .dashboard import window as classic
from .settings_hub import SettingsHub
from .stage import Stage

BUBBLE_PAGE = {"Web Search": "Web"}
PAGE_TITLE = {"Web": "Web Search"}
HOST_PAGES = ("Chat", "Activity", "Media", "Code", "Notes", "Study", "Jobs", "Web", "Stats", "Settings")
STATUS_MS = 500
PAGE_MS = 2000
EDGE = design.SPACE["m"]
BOTTOM_ROOM = BOTTOM_HEIGHT + 2 * EDGE + design.SPACE["s"]


class Veil(QWidget):
    """A full-window dark sheet that fades in and out over a change of screen."""

    def __init__(self, parent):
        super().__init__(parent)
        self.level = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, ev):
        p = QPainter(self)
        c = QColor(design.BG)
        c.setAlphaF(self.level)
        p.fillRect(self.rect(), c)


class Destination(QWidget):
    """One existing page inside the new window, under a bar with a clear way back."""

    def __init__(self, dash, parent=None):
        super().__init__(parent)
        self.dash = dash
        box = QVBoxLayout(self)
        box.setContentsMargins(EDGE, EDGE, EDGE, BOTTOM_ROOM)
        box.setSpacing(design.SPACE["s"])
        bar = QHBoxLayout()
        self.back = QPushButton("‹  Back")
        self.back.setToolTip("Back to the bubbles (Esc)")
        self.back.setAccessibleName("Back to the bubbles")
        self.home = QPushButton("Home")
        self.home.setToolTip("Back to the globe (Alt+Home)")
        self.home.setAccessibleName("Back to the globe")
        self.title = QLabel("")
        self.title.setFont(design.font(20))
        bar.addWidget(self.back)
        bar.addWidget(self.title, 1)
        bar.addWidget(self.home)
        box.addLayout(bar)
        self.stack = QStackedWidget()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(self.stack)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        box.addWidget(self.scroll, 1)
        self.pages = {}
        for name in HOST_PAGES:
            page = dash.pages[name]
            self.stack.addWidget(page)
            self.pages[name] = page
        dash.theme.changed.connect(self.restyle)
        self.restyle()

    def restyle(self):
        accent = self.dash.theme.accent.name()
        focus = (f"QPushButton:focus, QToolButton:focus, QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QCheckBox:focus, QSlider:focus, "
                 f"QListWidget:focus, QTableWidget:focus {{ border: 2px solid {design.ACCENT}; }}")
        self.setStyleSheet(self.dash.theme.qss() + focus + design.pages_qss() + design.chat_qss() + f"QLabel#dest_title {{ color: {design.TEXT}; }}")
        self.title.setObjectName("dest_title")

    def show_page(self, name):
        self.stack.setCurrentWidget(self.pages[name])
        self.title.setText(PAGE_TITLE.get(name, name))

    def paintEvent(self, ev):
        QPainter(self).drawPixmap(0, 0, design.backdrop(self.width(), self.height()))


class Shell(QWidget):
    def __init__(self, dash=None):
        super().__init__()
        self.setWindowTitle("JARVIS")
        self.setMinimumSize(design.MIN_WIDTH, design.MIN_HEIGHT)
        self.resize(1280, 800)
        self.setStyleSheet(design.qss())
        self.dash = dash or classic.Dashboard()
        self.dash.bring_up = self.bring_up
        self.dash.on_power = self.apply_power
        self.hub = SettingsHub(self.dash.ctx, self.dash, self.dash.pages["Settings"])
        self.dash.pages["Settings"] = self.hub
        self.tracker = status.Tracker()
        self.snap = status.Snapshot()
        self.state = "idle"
        self.levels = {}
        self.quitting = False
        self.where = "globe"
        self.last_bubble = None
        self._veil_anim = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.stage = Stage()
        self.destination = Destination(self.dash)
        self.stack.addWidget(self.stage)
        self.stack.addWidget(self.destination)
        root.addWidget(self.stack)

        self.bottom = BottomPanel(self)
        self.confirm = self.dash.confirm
        self.confirm.setParent(self)
        self.palette = CommandPalette(self)
        self.veil = Veil(self)
        self.confirm.raise_()
        self.bottom.raise_()

        self.stage.opened.connect(self.open_bubble)
        self.stage.went_home.connect(self.go_globe)
        self.destination.back.clicked.connect(self.back)
        self.destination.home.clicked.connect(self.go_globe)
        self.bottom.search.connect(self.open_palette)
        self.palette.chosen.connect(self.run_feature)
        self.palette.closed.connect(self._restore_focus)
        self.dash.clock.tick.connect(self._frame)
        events.listeners.append(self.tracker.on_event)
        design.listeners.append(self.on_look)
        profile.listeners.append(self.on_profile)

        for keys, fn in (("Ctrl+K", self.open_palette), ("Ctrl+.", self.dash.stop_all), ("Ctrl+Q", self.quit_all), ("F11", self.toggle_full),
                         ("Esc", self.escape), ("Alt+Left", self.back), ("Alt+Home", self.go_globe)):
            QShortcut(QKeySequence(keys), self).activated.connect(fn)
        order = [self.stage] + [self.stage.bubbles[n] for n in NAMES] + [self.bottom.button]
        for a, b in zip(order, order[1:]):
            QWidget.setTabOrder(a, b)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(STATUS_MS)
        self.page_timer = QTimer(self)
        self.page_timer.timeout.connect(self.refresh_page)
        self.page_timer.start(PAGE_MS)
        self.track(self)
        self.apply_power()
        self.poll()
        self._place_overlays()

    @staticmethod
    def track(widget):
        """Mouse tracking on the window and every child, so move events arrive without a button held. The stage also polls the cursor itself."""
        widget.setMouseTracking(True)
        for child in widget.findChildren(QWidget):
            child.setMouseTracking(True)

    # ---------- showing ----------
    def present(self):
        self.showFullScreen()
        self.stage.setFocus()

    def toggle_full(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def bring_up(self):
        self.showNormal() if self.isMinimized() else self.show()
        self.raise_()
        self.activateWindow()

    def sync_visibility(self):
        self.dash.clock.set_visible(self.isVisible() and not self.isMinimized())

    def showEvent(self, ev):
        super().showEvent(ev)
        self.sync_visibility()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.sync_visibility()

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() == QEvent.Type.WindowStateChange:
            self.sync_visibility()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place_overlays()

    def _place_overlays(self):
        w, h = self.width(), self.height()
        bw = min(980, w - 2 * EDGE)
        x = (w - bw) // 2
        self.bottom.setGeometry(x, h - BOTTOM_HEIGHT - EDGE, bw, BOTTOM_HEIGHT)
        ch = self.confirm.sizeHint().height()
        self.confirm.setGeometry(x, h - BOTTOM_HEIGHT - EDGE - ch - design.SPACE["s"], bw, ch)
        self.veil.setGeometry(0, 0, w, h)
        if self.palette.isVisible():
            self.palette.place()

    # ---------- look and profile ----------
    def on_look(self):
        """The saved look changed: restyle the chrome and the pages, rebuild the motion budget, repaint."""
        self.setStyleSheet(design.qss())
        self.destination.restyle()
        self.apply_power()
        self.stage.update()
        self.bottom.update()
        self.palette.update()

    def on_profile(self, _profile=None):
        self.stage.update()

    # ---------- power and motion ----------
    def apply_power(self):
        self.stage.apply_budget(design.current_budget())

    # ---------- live state ----------
    def poll(self):
        """Twice a second: read the real state, tell the globe and the bottom panel. Provider levels are read here, never per frame."""
        try:
            self.levels = status.cloud_levels()
            self.snap = status.snapshot(self.tracker, self.levels)
        except Exception:
            traceback.print_exc()
            return
        self.state = status.resolve_state(self.snap)
        self.stage.set_state(self.state)
        self.bottom.set_status(self.snap, self.state)
        self.confirm.refresh()
        self._place_overlays()

    def _frame(self):
        if self.stack.currentWidget() is self.stage:
            self.stage.tick()

    def refresh_page(self):
        if self.where in self.destination.pages and (self.isVisible() or os.environ.get("JARVIS_DASH_TEST")):
            try:
                self.destination.pages[self.where].refresh()
            except Exception as e:
                events.emit("sys", f"error: page refresh failed ({type(e).__name__})")
                traceback.print_exc()

    # ---------- navigation ----------
    def _swap(self, change):
        """Run `change` under a short fade, or at once when reduced motion is on."""
        if self._veil_anim is not None:
            self._veil_anim.stop()
        if not self.stage.budget.transitions:
            self.veil.hide()
            change()
            return
        anim = QVariantAnimation(self)
        self._veil_anim = anim
        self.veil.show()
        self.veil.raise_()
        phase = {"in": True}

        def step(v):
            self.veil.level = float(v) if phase["in"] else 1 - float(v)
            self.veil.update()

        def finish():
            if phase["in"]:
                phase["in"] = False
                change()
                anim.setDuration(design.MOTION["base"])
                anim.start()
            else:
                self.veil.hide()
                self.bottom.raise_()
                self.confirm.raise_()

        anim.valueChanged.connect(step)
        anim.finished.connect(finish)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(design.MOTION["fast"])
        anim.start()

    def open_bubble(self, name):
        self.last_bubble = name
        self.open_page(BUBBLE_PAGE.get(name, name))

    def open_page(self, key):
        if key not in self.destination.pages:
            return

        def change():
            self.where = key
            self.destination.show_page(key)
            self.stack.setCurrentWidget(self.destination)
            self.refresh_page()
            self.destination.back.setFocus(Qt.FocusReason.OtherFocusReason)
            self.bottom.raise_()
            self.confirm.raise_()

        self._swap(change)

    def go_bubbles(self):
        self._show_stage("bubbles")

    def go_globe(self):
        self._show_stage("globe")

    def back(self):
        if self.where in self.destination.pages:
            self._show_stage("bubbles")

    def _show_stage(self, section):
        def change():
            self.where = section
            self.stack.setCurrentWidget(self.stage)
            self.stage.scroll_to(section, instant=True)
            target = self.stage.bubbles.get(self.last_bubble) if section == "bubbles" else None
            (target or self.stage).setFocus(Qt.FocusReason.OtherFocusReason)
            self.bottom.raise_()
            self.confirm.raise_()

        if self.stack.currentWidget() is self.stage:
            self.where = section
            self.stage.scroll_to(section)
            if section == "globe":
                self.stage.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self._swap(change)

    def escape(self):
        if self.palette.isVisible():
            self.palette.close_palette()
        elif self.stack.currentWidget() is self.destination:
            self.back()
        elif self.stage.section == "bubbles":
            self.go_globe()

    # ---------- palette ----------
    def open_palette(self):
        self.palette.open()

    def _restore_focus(self):
        if self.stack.currentWidget() is self.stage:
            self.stage.setFocus(Qt.FocusReason.OtherFocusReason)

    def run_feature(self, f):
        """Where Enter goes for a registry entry."""
        kind = f.action[0]
        if kind == "globe":
            self.go_globe()
        elif kind == "page":
            self.open_page(f.action[1])
            if len(f.action) > 2 and f.action[1] == "Settings":
                self.hub.show_section(f.action[2])
        elif kind == "toggle":
            if f.action[1] == "low_power":
                self.dash.set_low_power(not self.dash.low_manual)
            else:
                self.dash.set_reduced_motion(not self.dash.reduced)
            self.apply_power()
        elif kind == "window":
            self.toggle_full()
        elif kind == "tool":
            self.open_page("Chat")
            entry = self.dash.pages["Chat"].view.entry
            entry.setText(f.action[2])
            entry.setFocus()
            entry.setCursorPosition(len(entry.text()))

    # ---------- closing ----------
    def closeEvent(self, ev):
        """Close hides to the tray when there is one; with no tray there is nowhere to hide, so close quits."""
        tray = self.dash.tray
        if self.quitting:
            ev.accept()
        elif tray is not None and tray.isVisible():
            ev.ignore()
            self.hide()
        else:
            self.quit_all()

    def quit_all(self, exit_process=True):
        self.quitting = True
        if self.tracker.on_event in events.listeners:
            events.listeners.remove(self.tracker.on_event)
        for hooks, fn in ((design.listeners, self.on_look), (profile.listeners, self.on_profile)):
            if fn in hooks:
                hooks.remove(fn)
        state.update(activity="idle")
        self.dash.quit_all(exit_process=exit_process)
        if not exit_process:
            self.close()


def run(with_core=True):
    classic.run(with_core=with_core, make=Shell)
