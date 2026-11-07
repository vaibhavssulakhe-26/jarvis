"""Voice controls for how often Jarvis starts a chat by itself."""
from ..core import state
from ..scheduling import proactive
from .guard_tools import _until
from .tools import tool

LEVELS = proactive.LEVELS


@tool("proactive_level", 'args {"change": "more or less"} - let Jarvis start chats more or less often; for "be chattier", "be quieter"')
def proactive_level(args):
    now = proactive.level()
    i = LEVELS.index(now)
    new = LEVELS[min(i + 1, 2)] if str(args.get("change")).lower() == "more" else LEVELS[max(i - 1, 0)]
    state.update(proactive=new, quiet_until=0.0)
    if new == now:
        return "I am already as chatty as I get." if new == "normal" else "I am already staying quiet."
    return {"off": "Okay, I will stay quiet unless you talk to me.",
            "low": "Okay, I will check in now and then.",
            "normal": "Okay, I will chat a bit more."}[new]


@tool("proactive_quiet", 'args {"for": "two hours"} - stop starting chats for a while; for "stop talking for two hours"')
def proactive_quiet(args):
    state.update(quiet_until=_until(args.get("for"), 120))
    return "Okay, I will keep my thoughts to myself for a while."
