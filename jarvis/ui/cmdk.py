"""The command palette (Ctrl+K): one line to type in, fuzzy results from the feature registry, Enter jumps straight there."""
from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from .. import features
from . import design

WIDTH = 640
LIMIT = 8
TAG = {features.SECTION: "section", features.SETTING: "setting", features.TOOL: "tool"}


class CommandPalette(QWidget):
    chosen = pyqtSignal(object)
    closed = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setAccessibleName("Command palette")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.items = []
        box = QVBoxLayout(self)
        box.setContentsMargins(design.SPACE["m"], design.SPACE["m"], design.SPACE["m"], design.SPACE["m"])
        box.setSpacing(design.SPACE["s"])
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Search features, settings and tools")
        self.entry.setAccessibleName("Search")
        self.entry.setFont(design.font(16))
        self.entry.textChanged.connect(self.refresh)
        self.entry.installEventFilter(self)
        self.list = QListWidget()
        self.list.setAccessibleName("Results")
        self.list.setFont(design.font(14))
        self.list.itemActivated.connect(lambda _: self.activate())
        self.list.itemClicked.connect(lambda _: self.activate())
        self.hint = QLabel("Enter to open, Up and Down to choose, Esc to close")
        self.hint.setObjectName("dim")
        self.hint.setFont(design.font(12))
        box.addWidget(self.entry)
        box.addWidget(self.list, 1)
        box.addWidget(self.hint)
        self.hide()

    def open(self):
        self.entry.clear()
        self.refresh()
        self.place()
        self.show()
        self.raise_()
        self.entry.setFocus(Qt.FocusReason.PopupFocusReason)

    def place(self):
        parent = self.parentWidget()
        w = min(WIDTH, max(320, parent.width() - 2 * design.SPACE["m"]))
        h = min(parent.height() - 2 * design.SPACE["l"], 120 + LIMIT * 40)
        self.setGeometry((parent.width() - w) // 2, max(design.SPACE["l"], parent.height() // 6), w, h)

    def close_palette(self):
        if self.isVisible():
            self.hide()
            self.closed.emit()

    def refresh(self):
        self.items = features.search(self.entry.text(), LIMIT)
        self.list.clear()
        first = None
        for i, f in enumerate(self.items):
            text = f"{f.title}     {TAG[f.group]}" if f.available else f"{f.title}     not built yet: {f.why}"
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, i)
            if not f.available:
                it.setFlags(Qt.ItemFlag.NoItemFlags)
                it.setForeground(QColor(design.DIM))
            elif first is None:
                first = i
            self.list.addItem(it)
        if first is not None:
            self.list.setCurrentRow(first)

    def current(self):
        it = self.list.currentItem()
        return self.items[it.data(Qt.ItemDataRole.UserRole)] if it is not None else None

    def activate(self):
        f = self.current()
        if f is None or not f.available:
            return
        self.hide()
        self.chosen.emit(f)

    def _step(self, delta):
        rows = [i for i in range(self.list.count()) if self.list.item(i).flags() & Qt.ItemFlag.ItemIsEnabled]
        if not rows:
            return
        cur = self.list.currentRow()
        nxt = [r for r in rows if (r > cur if delta > 0 else r < cur)]
        self.list.setCurrentRow((nxt[0] if delta > 0 else nxt[-1]) if nxt else (rows[0] if delta > 0 else rows[-1]))

    def eventFilter(self, obj, ev):
        if obj is self.entry and ev.type() == QEvent.Type.KeyPress:
            k = ev.key()
            if k == Qt.Key.Key_Down:
                self._step(1)
                return True
            if k == Qt.Key.Key_Up:
                self._step(-1)
                return True
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.activate()
                return True
            if k == Qt.Key.Key_Escape:
                self.close_palette()
                return True
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.close_palette()
        else:
            super().keyPressEvent(ev)

    def paintEvent(self, ev):
        from PyQt6.QtGui import QPainter
        p = QPainter(self)
        p.drawPixmap(0, 0, design.glass(self.width(), self.height(), design.RADIUS["l"], hot=True))
