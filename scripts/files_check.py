"""Checks file finding, summaries and notes against a scratch folder. Run: python scripts/files_check.py"""
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
tmp = Path(tempfile.mkdtemp(prefix="jarvis-files-"))
os.environ["JARVIS_DATA"] = str(tmp / "data")
os.environ["USER_PET_NAME"] = "Testy"

from jarvis.actions import documents, files, notes, tools, windows  # noqa: E402,F401
from jarvis.brain import brain  # noqa: E402
from jarvis.core import main as core  # noqa: E402
from jarvis.memory import notes as note_store  # noqa: E402
from jarvis.memory import store  # noqa: E402

results = []


def check(name, ok):
    ok = bool(ok)
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name)


def make_pdf(path, text):
    """A tiny valid PDF with one line of text per 90 characters, enough for text extraction."""
    lines = [text[i:i + 90] for i in range(0, len(text), 90)] or [""]
    content = "BT /F1 10 Tf 40 780 Td 12 TL " + " ".join(
        "(" + ln.replace("(", "[").replace(")", "]").replace("\\", "/") + ") Tj T*" for ln in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)


home = tmp / "home"
files.HOME = home
for folder in ("Downloads", "Documents", "Desktop", "Pictures"):
    (home / folder).mkdir(parents=True)
first = home / "Downloads" / "Legal_Aid_Rights_Awareness_Portal_Synopsis.pdf"
second = home / "Downloads" / "VTU_Synopsis_Legal_Aid_Rights_Awareness_Portal.pdf"
body = ("The portal gives citizens simple access to legal aid. It lists rights, lawyers and forms. "
        "Volunteers verify every entry. ") * 4
make_pdf(first, body)
make_pdf(second, body + " The VTU version adds a review section about budget and timeline.")
os.utime(first, (time.time() - 5000, time.time() - 5000))
chart = home / "Documents" / "weekly family food chart.txt"
chart.write_text("Monday rice and dal. Tuesday chapati. Wednesday idli. " * 3)
(home / "Documents" / "deep" / "er").mkdir(parents=True)
(home / "Documents" / "deep" / "er" / "Aegis Phase 2 Judging Prep.pdf").write_bytes(b"x")
(home / ".venv-1").mkdir()
(home / ".venv-1" / "Legal_Aid_hidden.pdf").write_bytes(b"x")

def ask_again():
    try:
        files.locate("Legal Aid Rights Awareness Portal", ("summarise_file", {}))
    except files.FileChoice:
        pass


found = files.find_files("Legal Aid Rights Awareness Portal")
check("two candidates for the Legal Aid query", len(files.close_ones(found)) == 2 and not files.clear_winner(found))
check("hidden folders are skipped", all(".venv" not in str(r["path"]) for r in found))
try:
    files.locate("Legal Aid Rights Awareness Portal", ("summarise_file", {}))
    asked = None
except files.FileChoice as e:
    asked = str(e)
check("the question names both options", bool(asked) and asked.count(";") == 1 and "Which one" in asked)
options = list(files.PENDING["options"])
act = files.take_choice("the second one")
check("'the second one' picks the second listed file", act and act[1]["path"] == str(options[1]["path"]))
ask_again()
act = files.take_choice("the newest")
check("'the newest' picks the newest file", act and Path(act[1]["path"]) == second)
ask_again()
act = files.take_choice("the first")
check("'the first' picks the first listed file", act and act[1]["path"] == str(options[0]["path"]))

check("clear winner for the food chart", files.locate("weekly family food chart") == chart)
check("the last file is remembered", files.locate("it") == chart)
check("spoken number matches digit in name", files.find_files("aegis phase two")[0]["path"].name.startswith("Aegis Phase 2"))
check("folder hint works", files.find_files("synopsis in downloads")[0]["path"].parent.name == "Downloads")
try:
    files.locate("quantum zebra invoice")
    msg = ""
except LookupError as e:
    msg = str(e)
check("a miss names the folders searched", "Downloads" in msg and "Documents" in msg)

calls = []


def fake_ask(prompt, max_tokens=300, **kw):
    calls.append(prompt)
    return "- first point\n- second point\n- third point\n- fourth point\n- fifth point"


with mock.patch.object(brain, "ask", fake_ask):
    result = tools.TOOLS["summarise_file"]["fn"]({"path": "Legal Aid Rights Awareness Portal Synopsis pdf"})
check("pdf text is extracted and summarised", "first point" in result and len(calls) == 1)
check("summary offers a note", result.endswith("save this as a note?") and core.PENDING.get("action") == "take_note")
core.PENDING.clear()

long_text = ("Section about budgets and timelines for the portal. " * 400)
long_file = home / "Documents" / "long_report.txt"
long_file.write_text(long_text)
calls.clear()
with mock.patch.object(brain, "ask", fake_ask):
    tools.TOOLS["summarise_file"]["fn"]({"path": "long report"})
check("long file: at most 8 small calls", 2 <= len(calls) <= 8 and all(len(c) < 3200 for c in calls))
core.PENDING.clear()

calls.clear()
with mock.patch.object(brain, "ask", fake_ask):
    answer = tools.TOOLS["ask_about_file"]["fn"]({"question": "what does it say about budgets", "path": ""})
check("ask about the last file uses two chunks at most", len(calls) == 1 and calls[0].count("---") <= 3 and answer)

# notes
store.PATH = tmp / "data" / "memory.db"
with mock.patch.object(windows, "active_window", return_value=("org.kde.okular", "Syllabus - Okular")):
    check("topic from an acronym", note_store.derive_topic("study DSA chapter 3 tonight") == "DSA")
    check("topic from the active window", note_store.derive_topic("buy milk") == "Syllabus")
    tools.TOOLS["take_note"]["fn"]({"topic": "DSA", "text": "study DSA chapter 3 tonight"})
with store.db() as con:
    row = con.execute("SELECT * FROM notes WHERE topic='DSA'").fetchone()
check("note stores app and window title", row["app"] == "org.kde.okular" and row["window_title"] == "Syllabus - Okular")
check("readable copy is written", "chapter 3" in (tmp / "data" / "notes" / "dsa.txt").read_text())
check("read back by topic", "chapter 3" in tools.TOOLS["read_notes"]["fn"]({"topic": "DSA"}))
check("search finds it", "DSA" in tools.TOOLS["search_notes"]["fn"]({"query": "chapter"}))
tools.TOOLS["append_to_note"]["fn"]({"topic": "dsa", "text": "revise trees"})
check("append adds to the same topic", len(note_store.read("DSA")) == 2)
check("list names the topic", "DSA" in tools.TOOLS["list_notes"]["fn"]({}))
check("delete needs a confirmation", tools.TOOLS["delete_note"]["risk"] == "confirm")
tools.TOOLS["delete_note"]["fn"]({"topic": "DSA"})
check("delete removes notes and copy", not note_store.read("DSA") and not (tmp / "data" / "notes" / "dsa.txt").exists())
with mock.patch.object(windows, "active_window", return_value=None):
    check("no window falls back to general", note_store.derive_topic("buy milk") == "general")

print(f"\n{sum(results)} of {len(results)} passed")
sys.exit(0 if all(results) else 1)
