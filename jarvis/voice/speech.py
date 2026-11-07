"""What is safe to say out loud: strips markup and symbols, and decides when a reply is too long to read."""
import re

URL = re.compile(r"(?:https?://|www\.)\S+")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
EMOJI = re.compile("[\U0001F000-\U0001FAFF←-⇿⌀-⏿☀-➿⬀-⯿️‍]")
SENTENCE = re.compile(r"(?<=[.!?])\s+")
STRUCTURED = re.compile(r"```|^\s*(?:[-*•]|\d+[.)])\s+\S|^\s*#{1,6}\s|^\s*\|.*\|\s*$|^\s*-{3,}\s*$", re.M)
SHORT_SENTENCES = 3
MAX_SENTENCES = 5
MAX_CHARS = 450
DONE = "Done, it's on your screen and copied."


class Full(str):
    """A line the user asked to hear in full, such as a file read aloud. It is cleaned but never shortened."""


def sentences(text):
    return [s for s in SENTENCE.split(text.strip()) if s.strip()]


def clean(text):
    """Plain words only: no markdown, symbols, links, addresses or emoji."""
    t = str(text)
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    links = []
    t = URL.sub(lambda m: links.append(1) or " \0 ", t)
    t = t.replace("\0", "link on screen", 1).replace("\0", " ")
    t = EMAIL.sub(" ", t)
    t = EMOJI.sub("", t)
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.replace("&", " and ").replace("%", " percent")
    t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", t, flags=re.M)
    t = re.sub(r"(?<=\w)-(?=\w)", "\1", t)
    t = re.sub(r"[^\w\s.,!?;:'\"()\1ऀ-ॿಀ-೿]", " ", t).replace("\1", "-")
    t = t.replace("_", " ")
    t = re.sub(r"\s+([.,!?;:])", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def too_long(text):
    """True for code, lists, tables and anything past about five sentences: show those instead of speaking them."""
    t = str(text)
    return bool(STRUCTURED.search(t)) or "\n\n" in t.strip() or len(sentences(t)) > MAX_SENTENCES or len(t) > MAX_CHARS


def shorten(spoken):
    """At most three sentences are spoken."""
    parts = sentences(spoken)
    return " ".join(parts[:SHORT_SENTENCES]) if len(parts) > SHORT_SENTENCES else spoken
