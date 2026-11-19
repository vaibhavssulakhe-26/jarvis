"""The chat: message bubbles with markdown, a copy button, streaming text, a conversation list and file drops.
ChatView is used twice: as the Chat page (with the list) and as the dock on the right of every other page (compact)."""
import threading

from PyQt6.QtCore import QObject, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
                             QTextBrowser, QVBoxLayout, QWidget)

from ...actions import attach, events
from ...memory import threads
from . import privacy

SHOWN = 40
SHOWN_DOCK = 24
CURSOR = " \u258d"
RENDER_MS = 120


class Bridge(QObject):
    """Events arrive on worker threads; the signals carry them to the window thread."""
    thread = pyqtSignal(str, object)
    delta = pyqtSignal(str)
    ended = pyqtSignal()
    chip = pyqtSignal(str)


class Bubble(QFrame):
    def __init__(self, role, text, tier="", via="", theme=None):
        super().__init__()
        self.role, self.raw = role, text
        self.setObjectName("bubble_user" if role == "user" else "bubble_bot")
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 6, 10, 6)
        box.setSpacing(2)
        self.body = QTextBrowser()
        self.body.setFrameShape(QFrame.Shape.NoFrame)
        self.body.setOpenExternalLinks(True)
        self.body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body.setStyleSheet("background: transparent; border: none; font-size: 15px;")
        box.addWidget(self.body)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        self.chips.addStretch(1)
        box.addLayout(self.chips)
        foot = QHBoxLayout()
        self.meta = QLabel("")
        self.meta.setObjectName("cap")
        self.copy = QPushButton("Copy")
        self.copy.setFlat(True)
        self.copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy.clicked.connect(lambda: QApplication.clipboard().setText(privacy.show(self.raw)))
        foot.addWidget(self.meta)
        foot.addStretch(1)
        foot.addWidget(self.copy)
        box.addLayout(foot)
        self.set_text(text)
        self.set_meta(role, tier, via)

    def set_meta(self, role, tier="", via=""):
        bits = ["You" if role == "user" else "Jarvis"]
        if via == "typed" and role == "user":
            bits.append("typed")
        if tier:
            bits.append("ADVANCED" if tier == "advanced" else tier + " tier")
        self.meta.setText("  ".join(bits).upper())

    def set_text(self, text):
        self.raw = text.removesuffix(CURSOR)
        self.body.setMarkdown(privacy.show(text))
        self.fit()

    def add_chip(self, text):
        """A small tag under the reply for one tool call: 'find file: done' or 'play music: failed'."""
        label = QLabel(text)
        label.setObjectName("chip_bad" if text.endswith("failed") else "chip_ok" if text.endswith("done") else "chip")
        self.chips.insertWidget(self.chips.count() - 1, label)

    def fit(self):
        width = max(120, self.body.viewport().width() or self.width() - 24)
        self.body.document().setTextWidth(width)
        self.body.setFixedHeight(int(self.body.document().size().height()) + 6)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.fit()


class ChatView(QWidget):
    def __init__(self, ctx, compact=False, header=True):
        super().__init__()
        self.ctx = ctx
        self.compact = compact
        self.bubbles = []
        self.live = None
        self.pending_file = None
        self.setAcceptDrops(True)
        self.bridge = Bridge()
        self.bridge.thread.connect(self.on_thread)
        self.bridge.delta.connect(self.on_delta)
        self.bridge.ended.connect(self.on_end)
        self.bridge.chip.connect(lambda text: self.chips.append(text))
        self.chips = []
        self._tick = QTimer(self)
        self._tick.setSingleShot(True)
        self._tick.timeout.connect(self.render_live)
        self._dirty = False

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        self.convs = QListWidget()
        self.convs.setFixedWidth(190)
        self.convs.itemClicked.connect(self.open_conv)
        side = QWidget()
        sbox = QVBoxLayout(side)
        sbox.setContentsMargins(0, 0, 0, 0)
        new = QPushButton("New chat")
        new.clicked.connect(self.new_chat)
        delete = QPushButton("Delete")
        delete.clicked.connect(self.delete_current)
        sbox.addWidget(new)
        sbox.addWidget(self.convs, 1)
        sbox.addWidget(delete)
        side.setFixedWidth(190)
        self.side = side
        outer.addWidget(side)
        side.setVisible(not compact)

        main = QVBoxLayout()
        main.setSpacing(6)
        if compact and header:
            top = QHBoxLayout()
            self.title = QLabel("CHAT")
            self.title.setObjectName("cap")
            new2 = QPushButton("New")
            new2.clicked.connect(self.new_chat)
            top.addWidget(self.title)
            top.addStretch(1)
            top.addWidget(new2)
            main.addLayout(top)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.scroll.viewport().setStyleSheet("background: transparent;")
        self.holder = QWidget()
        self.holder.setObjectName("chat_holder")
        self.holder.setStyleSheet("QWidget#chat_holder { background: transparent; }")
        self.col = QVBoxLayout(self.holder)
        self.col.setContentsMargins(0, 0, 6, 0)
        self.col.setSpacing(8)
        self.col.addStretch(1)
        self.scroll.setWidget(self.holder)
        main.addWidget(self.scroll, 1)
        self.chip = QLabel("")
        self.chip.setObjectName("cap")
        self.chip.setVisible(False)
        main.addWidget(self.chip)
        row = QHBoxLayout()
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("message, or drop a PDF, text or image file here")
        self.entry.returnPressed.connect(self.send)
        send = QPushButton("Send")
        send.clicked.connect(self.send)
        row.addWidget(self.entry, 1)
        row.addWidget(send)
        main.addLayout(row)
        outer.addLayout(main, 1)

        threads.changed.append(lambda kind, info: self.bridge.thread.emit(kind, info))
        self._listener = self._on_event
        events.listeners.append(self._listener)
        self.load()

    # ---------- events ----------
    def _on_event(self, kind, text):
        if kind == "stream":
            self.bridge.delta.emit(text)
        elif kind == "stream_end":
            self.bridge.ended.emit()
        elif kind == "tool":
            self.bridge.chip.emit(text)

    def stop_listening(self):
        if self._listener in events.listeners:
            events.listeners.remove(self._listener)

    def on_thread(self, kind, info):
        if kind == "message":
            m = info["message"]
            if m["role"] == "assistant" and self.live is not None:
                self.live.set_text(m["text"])
                self.live.set_meta("assistant", m.get("tier", ""))
                bubble, self.live = self.live, None
            else:
                bubble = self.add(m)
            if m["role"] == "assistant":
                for text in self.chips:
                    bubble.add_chip(text)
                self.chips = []
            self.to_end()
        else:
            self.load()
        if kind in ("message", "new", "delete", "switch"):
            self.fill_list()

    def on_delta(self, delta):
        if self.live is None:
            self.live = self.make("assistant", "")
        self.live.raw += delta
        self._dirty = True
        if not self._tick.isActive():
            self._tick.start(RENDER_MS)

    def render_live(self):
        if self.live is not None and self._dirty:
            self._dirty = False
            self.live.set_text(self.live.raw + CURSOR)
            self.to_end()

    def on_end(self):
        self._dirty = False
        if self.live is not None:
            self.live.set_text(self.live.raw)

    # ---------- bubbles ----------
    def make(self, role, text, tier="", via=""):
        b = Bubble(role, text, tier, via, self.ctx.theme)
        self.col.insertWidget(self.col.count() - 1, b)
        self.bubbles.append(b)
        while len(self.bubbles) > (SHOWN_DOCK if self.compact else SHOWN):
            old = self.bubbles.pop(0)
            old.setParent(None)
            old.deleteLater()
        return b

    def add(self, m):
        return self.make(m["role"], m["text"], m.get("tier", ""), m.get("via", ""))

    def to_end(self):
        QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))

    def load(self):
        for b in self.bubbles:
            b.setParent(None)
            b.deleteLater()
        self.bubbles, self.live = [], None
        for m in threads.current()["messages"][-(SHOWN_DOCK if self.compact else SHOWN):]:
            self.add(m)
        self.fill_list()
        self.to_end()

    def fill_list(self):
        if self.compact:
            return
        self.convs.clear()
        cur = threads.current()["id"]
        for r in threads.listing()[:60]:
            item = QListWidgetItem(f"{r['title']}  ({r['count']})")
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.convs.addItem(item)
            if r["id"] == cur:
                self.convs.setCurrentItem(item)

    # ---------- actions ----------
    def open_conv(self, item):
        threads.switch(item.data(Qt.ItemDataRole.UserRole))

    def new_chat(self):
        threads.new_chat()

    def delete_current(self):
        threads.delete(threads.current()["id"])

    def send(self):
        text = self.entry.text().strip()
        self.entry.clear()
        path, self.pending_file = self.pending_file, None
        self.chip.setVisible(False)
        if path:
            self.ask_file(path, text)
        elif text:
            events.via[0] = "typed"
            self.ctx.run(text)

    def ask_file(self, path, question):
        name = path.rsplit("/", 1)[-1]
        events.via[0] = "typed"
        events.emit("you", f"[{name}] {question or 'Summarise this file.'}")

        def go():
            from ...voice import voice
            try:
                voice.say(attach.ask(path, question))
            except Exception as e:
                voice.say(str(e) if str(e) else "I could not read that file.")
        threading.Thread(target=go, daemon=True).start()

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        for url in ev.mimeData().urls():
            path = url.toLocalFile()
            if path and attach.supported(path):
                self.pending_file = path
                self.chip.setText("FILE: " + path.rsplit("/", 1)[-1] + "  (type a question and press Send)")
                self.chip.setVisible(True)
                self.entry.setFocus()
                return
        self.chip.setText("I can read PDF, text and image files.")
        self.chip.setVisible(True)

    def sizeHint(self):
        return QSize(360, 400)
