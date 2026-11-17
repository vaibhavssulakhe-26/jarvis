class ToolError(Exception):
    """An error with a message that is safe to speak."""


class Ask(ToolError):
    """A question for the user because a detail is missing. It is not a failure and is never reported as one."""
