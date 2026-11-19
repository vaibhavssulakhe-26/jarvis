"""Decides whether a transcribed utterance was meant for Jarvis.

An utterance is accepted in three cases only: the wake word started it (or is in it), the push-to-talk key or Talk button started it, or it is the
single reply inside a short follow-up window that opened because Jarvis had just asked a question. Everything else is dropped here, before
anything reaches the brain, and the reason is logged for the Activity page."""
import re

from . import stt

FOLLOWUP_SECONDS = 6.0
MIN_WORDS = 3
ANSWERS = {"yes", "yeah", "yep", "yup", "no", "nope", "nah", "sure", "okay", "ok", "please", "cancel", "stop", "first", "second", "third", "fourth",
           "fifth", "last", "newest", "oldest", "latest", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "number",
           "the", "that", "this", "it", "both", "neither", "again", "repeat", "thanks", "thank", "you", "never", "mind", "ya", "haan", "nahi", "illa"}
FILLER_WORDS = {"hmm", "hm", "mm", "mmm", "mhm", "uh", "um", "er", "ah", "oh", "huh", "eh", "ha", "he", "haha", "i", "suppose", "guess", "so", "well",
                "yeah", "okay", "ok", "right", "you", "know", "mean", "the", "and", "a", "da", "la", "na", "ba", "ma", "pa", "doo", "dum", "oh", "wow",
                "like", "just", "maybe", "anyway", "alright", "sure", "yes", "no"}


def words(text):
    return re.findall(r"[\w']+", str(text).lower())


def ambient(text):
    """Why this text looks like room noise or music rather than a request, or an empty string. Repeated syllables ("da da da"), or only filler."""
    w = words(text)
    if not w:
        return "nothing intelligible"
    if len(w) >= 3 and len(set(w)) <= 2:
        return "repeated syllables"
    if all(x in FILLER_WORDS for x in w) and not (len(w) == 1 and w[0] in ANSWERS):
        return "filler only"
    return ""


def judge(text, source, named=False, output=False, closing=False):
    """(accepted, reason) for one transcript. `source` is wake, ptt or followup; `named` is true when the wake word is in the transcript; `output` is true
    when music or Jarvis's own voice was playing while it was recorded; `closing` marks a goodbye, which is let through when it was addressed to Jarvis."""
    text = str(text).strip()
    explicit = named or source in ("wake", "ptt")
    if closing and not output and (explicit or source == "followup"):
        return True, "wake word" if explicit else "follow-up"
    if stt.is_hallucination(text):
        return False, "known hallucination"
    noise = ambient(text) if source != "ptt" else ""
    if noise:
        return False, noise
    if source == "ptt":
        return True, "push-to-talk"
    if output and not explicit:
        return False, "captured while sound was playing"
    if explicit:
        return True, "wake word"
    if source == "followup":
        w = words(text)
        if len(w) < MIN_WORDS and not all(x in ANSWERS for x in w):
            return False, "under 3 words, not an answer"
        return True, "follow-up"
    return False, "no wake word"
