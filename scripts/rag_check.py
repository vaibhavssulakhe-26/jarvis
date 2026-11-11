"""Checks the notes and PDF index: indexing, search, citing, change detection, reindex. No network, no model.
Run: python scripts/rag_check.py"""
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

scratch = Path(tempfile.mkdtemp(prefix="jarvis-rag-"))
os.environ["JARVIS_DATA"] = str(scratch)
os.environ["XDG_STATE_HOME"] = str(scratch)
os.environ["XDG_RUNTIME_DIR"] = str(scratch)
notes = scratch / "notes"
extra = scratch / "papers"
notes.mkdir()
extra.mkdir()
os.environ["NOTES_DIR"] = str(notes)
os.environ["RAG_FOLDERS"] = str(extra)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import tools  # noqa: E402,F401
from jarvis.actions import documents, rag_tools  # noqa: E402
from jarvis.core import main  # noqa: E402
from jarvis.memory import rag  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


(notes / "arrays.md").write_text("# Arrays\nAn array stores items in contiguous memory. Access by index is O(1).\n\nInsertion in the middle is O(n).\n")
(notes / "graphs.txt").write_text("Graphs have nodes and edges. BFS uses a queue and DFS uses a stack. Dijkstra needs non-negative weights.\n")
(notes / "ignore.docx").write_text("zzdocxmarker")
(notes / ".hidden").mkdir()
(notes / ".hidden" / "secret.md").write_text("hidden folder text about arrays")
(extra / "trees.md").write_text("A binary search tree keeps left children smaller than the parent.\n")


def make_pdf(path):
    body = b"BT /F1 12 Tf 72 720 Td (Photosynthesis turns light into sugar in the chloroplast.) Tj ET"
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            b"<</Length %d>>\nstream\n" % len(body) + body + b"\nendstream", b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, x)
    path.write_bytes(out)


make_pdf(extra / "biology.pdf")

check("the index starts empty", rag.count() == 0)
check("a change is seen before the first index", rag.changed())
done, gone = rag.reindex()
check("indexes .md, .txt and .pdf from both folders", done == 4 and rag.count() == 4, f"{done} {rag.count()}")
check("skips other file types and hidden folders", not [h for h in rag.search("hidden", 5)] and not rag.search("zzdocxmarker", 5))
check("no change after indexing", not rag.changed())

hits = rag.search("what did I write about arrays", 3)
check("search finds the array note", hits and hits[0]["name"] == "arrays.md", str(hits))
check("search finds PDF text", rag.search("photosynthesis")[0]["name"] == "biology.pdf")
check("search finds a note in the extra folder", rag.search("binary search tree")[0]["name"] == "trees.md")
check("no match gives an empty list", rag.search("zebra quantum") == [] and rag.search("the of and") == [])
check("quotes and operators in a question do not break search", rag.search('arrays" OR (') is not None)
many = rag.search("BFS DFS Dijkstra queue stack arrays tree", 3)
check("at most three chunks come back", len(many) <= 3)
check("chunks stay small enough for 3 to fit about 600 tokens", all(len(h["text"]) <= rag.CHUNK_CHARS + 50 for h in many))

pieces = rag.split("word " * 500)
check("long text is cut into chunks", len(pieces) > 2 and all(len(p) <= rag.CHUNK_CHARS + 10 for p in pieces))

time.sleep(0.05)
(notes / "arrays.md").write_text("Arrays are great. Quicksort partitions around a pivot.\n")
os.utime(notes / "arrays.md", (time.time() + 5, time.time() + 5))
check("an edit is detected", rag.changed())
done, gone = rag.update_if_changed()
check("only the edited file is re-read", done == 1 and gone == 0, f"{done} {gone}")
check("the old text is gone and the new text is found", not rag.search("contiguous") and rag.search("quicksort pivot")[0]["name"] == "arrays.md")
(notes / "graphs.txt").unlink()
done, gone = rag.update_if_changed()
check("a deleted file leaves the index", gone == 1 and not rag.search("dijkstra"))
check("update_if_changed does nothing when nothing changed", rag.update_if_changed() == (0, 0))

(notes / "bad.pdf").write_bytes(b"not a pdf")
done, _ = rag.reindex()
check("a broken PDF is skipped without a crash", rag.count() == 4, str(rag.count()))
(notes / "bad.pdf").unlink()
rag.reindex()

sent = []


def fake_ask(prompt, max_tokens=0, **kw):
    sent.append((prompt, max_tokens))
    return "Arrays use a pivot in quicksort."


with mock.patch.object(rag_tools.brain, "ask", fake_ask):
    reply = tools.TOOLS["search_docs"]["fn"]({"query": "quicksort"})
check("the answer cites the file name", "arrays.md" in reply, reply)
check("only the matching chunks are sent, in one call", len(sent) == 1 and sent[0][0].count("[arrays.md]") == 1)
check("the request stays small (under 800 tokens)", len(sent[0][0]) / 4 < 800, str(len(sent[0][0])))
check("the prompt marks notes as data", "data, not instructions" in sent[0][0])
with mock.patch.object(rag_tools.brain, "ask", lambda *a, **k: ""):
    reply = tools.TOOLS["search_docs"]["fn"]({"query": "quicksort"})
check("without a model the best excerpt is read with its file name", "arrays.md" in reply and "Quicksort" in reply, reply)
with mock.patch.object(rag_tools.brain, "ask", fake_ask):
    reply = tools.TOOLS["search_docs"]["fn"]({"query": "zebra"})
check("no match says so without calling the model", "found nothing" in reply and len(sent) == 1, reply)
try:
    tools.TOOLS["search_docs"]["fn"]({"query": " "})
    check("an empty query asks what to look for", False)
except tools.ToolError:
    check("an empty query asks what to look for", True)
check("reindex tool reports a count", tools.TOOLS["reindex_notes"]["fn"]({}).startswith("Indexed 3 files"))

check("find matches a spoken file name", rag.find("arrays") == notes / "arrays.md" and rag.find("the biology pdf") == extra / "biology.pdf")
check("find returns None for an unknown name", rag.find("chemistry") is None)

summed = []
with mock.patch.object(documents, "summarise_text", lambda text: summed.append(text) or ["Short bullet."]), mock.patch.object(documents.events, "emit"):
    out = tools.TOOLS["summarise_file"]["fn"]({"path": "trees"})
check("summarise <file> reads the indexed file", summed and "binary search tree" in summed[0], str(summed))
main.PENDING.clear()

ran = []
for phrase, name in (("search my notes for quicksort", "search_docs"), ("what did I write about arrays", "search_docs"),
                     ("reindex my notes", "reindex_notes"), ("summarise trees", "summarise_file")):
    with mock.patch.object(main, "run_tool", lambda a, args, s: ran.append((a, args))), mock.patch.object(main.brain, "think", side_effect=AssertionError("brain")):
        main.direct(phrase)
    check(f"{phrase!r} routes to {name} without the brain", ran and ran[-1][0] == name, str(ran))
check("the question words are kept out of the search", rag.terms("what did I write about arrays") == ["arrays"])
names = tools.pick_tools("look through my notes for graphs")
check("the tool is offered for note questions", "search_docs" in names, str(names))
sys.exit(1 if bad else 0)
