"""Voice tools for notes. Each note remembers the window it was written from."""
from ..brain import brain
from ..memory import notes
from .tools import ToolError, tool


@tool("take_note", 'args {"topic": "<the subject in one or two words, such as DSA>", "text": "<everything to note, in full>"} - write a note down; for "make a note", "write this down". Leave topic empty if unsure')
def take_note(args):
    text = str(args.get("text", "")).strip()
    if not text:
        raise ToolError("What should I write down?")
    topic = str(args.get("topic") or "").strip() or notes.derive_topic(text, " ".join(brain.RECENT[-2:]))
    notes.save(topic, text)
    return f"Noted under {topic}."


@tool("read_notes", 'args {"topic": "<one or two words>"} - read back what the user noted about a topic; for "what did I note about X"')
def read_notes(args):
    topic = str(args.get("topic") or "").strip()
    if not topic:
        raise ToolError("Which topic should I look up?")
    lines = notes.read(topic) or [t for _, t in notes.search(topic)]
    if not lines:
        return f"I have no notes about {topic}."
    return f"Your notes about {topic}: " + " ".join(lines[-5:])


@tool("list_notes", "args {} - say which note topics exist")
def list_notes(args):
    items = notes.topics()
    if not items:
        return "You have no notes yet."
    return "Your note topics are " + ", ".join(f"{t} with {n}" for t, n in items[:8]) + "."


@tool("search_notes", 'args {"query": "<words to look for>"} - search all notes for words')
def search_notes(args):
    query = str(args.get("query") or "").strip()
    if not query:
        raise ToolError("What should I search your notes for?")
    hits = notes.search(query)
    if not hits:
        return f"I found no notes mentioning {query}."
    return f"I found {len(hits)}. " + " ".join(f"{t}: {x}" for t, x in hits[:3])


@tool("append_to_note", 'args {"topic": "<existing topic>", "text": "<what to add>"} - add a line to an existing note topic')
def append_to_note(args):
    text = str(args.get("text") or "").strip()
    topic = str(args.get("topic") or "").strip()
    if not text or not topic:
        raise ToolError("Which note, and what should I add?")
    existing = notes.topics()
    match = next((t for t, _ in existing if t.lower() == topic.lower()), None) or next(
        (t for t, _ in existing if topic.lower() in t.lower()), topic)
    notes.save(match, text)
    return f"Added to {match}."


def _delete_describe(args):
    topic = str(args.get("topic") or "").strip()
    n = len(notes.read(topic)) if topic else 0
    if not n:
        raise ToolError(f"I have no notes about {topic or 'that'}.")
    return f"I will delete {n} note{'s' if n > 1 else ''} about {topic}."


@tool("delete_note", 'args {"topic": "<topic to delete>"} - delete the notes of a topic', risk="confirm",
      describe=_delete_describe)
def delete_note(args):
    n = notes.delete(str(args.get("topic") or ""))
    return f"Deleted {n} note{'s' if n != 1 else ''}."
