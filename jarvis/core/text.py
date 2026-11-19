"""Small text helpers shared by more than one module."""
import re


def fence(text):
    """The code inside the first ``` block of a model reply, or the whole reply, ending in one newline."""
    m = re.search(r"```[\w+-]*\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip("\n") + "\n"
