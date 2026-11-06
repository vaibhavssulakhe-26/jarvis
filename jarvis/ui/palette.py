"""A small command box. Run it from a keyboard shortcut or say "open palette": what you type goes to the
running Jarvis and is handled like a spoken command. Run: python -m jarvis.ui.palette"""
import sys
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QVBoxLayout, QWidget

from ..core import state

WAIT = 3.0
QSS = ("QWidget { background: #0b0d10; color: #ffd9a0; font-size: 15px; } "
       "QLineEdit { border: 1px solid #ff9a1f; padding: 8px 10px; } QLineEdit:focus { border: 1px solid #2ee6d6; } "
       "QLabel { color: #6f6250; font-size: 12px; }")


def submit(text):
    """Hand a command to the running assistant; True once it has picked it up."""
    state.update(command=text, command_at=time.time())
    end = time.time() + WAIT
    while time.time() < end:
        time.sleep(0.35)
        if not state.get("command"):
            return True
    state.update(command="")
    return False


class Palette(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setStyleSheet(QSS)
        self.setFixedWidth(520)
        box = QVBoxLayout(self)
        self.input = QLineEdit()
        self.input.setPlaceholderText("type a command")
        self.input.returnPressed.connect(self.go)
        self.note = QLabel("Enter to send, Esc to close")
        box.addWidget(self.input)
        box.addWidget(self.note)

    def go(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.setEnabled(False)
        if submit(text):
            self.close()
        else:
            self.note.setText("Jarvis is not running.")
            self.input.setEnabled(True)
            self.input.setFocus()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(ev)


def main():
    app = QApplication(sys.argv)
    win = Palette()
    win.show()
    win.input.setFocus()
    QTimer.singleShot(0, win.activateWindow)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
