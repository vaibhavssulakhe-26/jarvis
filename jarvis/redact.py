"""Masks what should not be stored in traces, notes or logs: email addresses, phone numbers, long digit strings, API keys and passwords."""
import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
KEY = re.compile(r"\b(?:sk|gsk|ghp|gho|xox[abp]|AKIA|AIza|pk|rk)[-_A-Za-z0-9]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----")
SECRET_WORD = re.compile(r"\b(pass(?:word|wd|code|phrase)?|pwd|pin|otp|secret|token|api key)\b(\s*(?:is|was|=|:)?\s*)(\S+)", re.I)
LONG_TOKEN = re.compile(r"\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{32,}\b")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
NUMBER = re.compile(r"(?<![\w.])\+?\(?\d[\d\s().-]{5,}\d(?!\w)")


def _number(m):
    text = m.group(0)
    digits = sum(c.isdigit() for c in text)
    if digits >= 9 or (digits >= 7 and (text.startswith("+") or "(" in text)):
        return "[number]"
    return text


def mask(text):
    """The text with emails, phone numbers, long digit strings, keys and passwords replaced by short tags."""
    t = str(text)
    t = EMAIL.sub("[email]", t)
    t = KEY.sub("[key]", t)
    t = SECRET_WORD.sub(lambda m: f"{m.group(1)}{m.group(2)}[secret]", t)
    t = LONG_TOKEN.sub("[key]", t)
    dates = []
    t = DATE.sub(lambda m: dates.append(m.group(0)) or "\x00", t)
    t = NUMBER.sub(_number, t)
    for d in dates:
        t = t.replace("\x00", d, 1)
    return t
