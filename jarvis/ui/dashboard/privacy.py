"""What the dashboard shows of private details: phone numbers and email addresses are masked unless the reveal switch is on.
Only the display changes; files, the chat thread and what Jarvis does keep the real text."""
import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w.])\+?\(?\d[\d\s().-]{6,}\d(?![\w])")
state = {"reveal": False}


def _phone(m):
    text = m.group(0)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", text.strip()):
        return text
    return "[number]" if sum(c.isdigit() for c in text) >= 7 else text


def show(text):
    """The text as it may be displayed right now."""
    text = str(text)
    if state["reveal"]:
        return text
    return PHONE.sub(_phone, EMAIL.sub("[email]", text))


def set_reveal(on):
    state["reveal"] = bool(on)
