"""The small panel that is always visible: what Jarvis is doing, the microphone, the connection, which brain, and the search button."""
from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from . import design, status
from .globe import look_for

HEIGHT = 48
NARROW = 860


class BottomPanel(QWidget):
    search = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(HEIGHT)
        self.setAccessibleName("Status")
        self.state = "idle"
        row = QHBoxLayout(self)
        row.setContentsMargins(34, 0, 8, 0)
        row.setSpacing(design.SPACE["m"])
        self.state_label = self._label("Ready", True)
        widest = max((status.state_label(n) for n in status.STATES), key=len)
        self.state_label.setMinimumWidth(self.state_label.fontMetrics().horizontalAdvance(widest) + 8)
        self.activity = self._label("")
        self.mic = self._label("")
        self.connection = self._label("")
        self.brain = self._label("")
        self.button = QPushButton("Search  Ctrl+K")
        self.button.setToolTip("Search features and settings (Ctrl+K)")
        self.button.setAccessibleName("Search")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setFixedHeight(32)
        self.button.clicked.connect(self.search)
        for w in (self.state_label, self.activity, self.mic, self.connection, self.brain):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(self.button)

    def _label(self, text, strong=False):
        lab = QLabel(text)
        lab.setFont(design.font(13, design.QFont.Weight.Normal if strong else design.QFont.Weight.Light))
        lab.setObjectName("" if strong else "dim")
        return lab

    def set_status(self, snap, state):
        self.state = state
        self.state_label.setText(status.state_label(state))
        self.activity.setText(snap.activity or "")
        self.mic.setText("mic " + status.mic_label(snap))
        self.connection.setText(status.connection_label(snap))
        self.brain.setText("brain: " + status.brain_label(snap))
        self.activity.setVisible(bool(snap.activity) and self.width() >= NARROW)
        self.update()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.activity.setVisible(bool(self.activity.text()) and self.width() >= NARROW)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, design.glass(self.width(), self.height(), design.RADIUS["l"]))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(look_for(self.state).tint))
        p.drawEllipse(QRectF(16, self.height() / 2 - 5, 10, 10))
