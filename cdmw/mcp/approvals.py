"""Who may run what without asking (P13 stage C, design record 2.5).

* Read tools run without asking. Edit, destructive and output tools ask in the
  app by default; the user may set each of those classes to allow.
* **Full access** allows all three, is shown while it is on, and ends when
  the app closes unless the user ticks "Keep".
* The prompt offers Allow once, Allow this tool for this session (until the
  app disconnects) and Deny. Deny, or no answer within five minutes as in
  CDMW Next, returns ``refused``.
* No tool can change the AI connection setting, the approval classes, Full
  access or the game folder (section 7, answer 8): :func:`refuse_protected_setting`.

The settings are read from the app's settings object each time, so a change
in Settings applies to the next call. No Qt here.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass, field

from cdmw.mcp.errors import DECLINED_MESSAGE, REFUSED, ToolError
from cdmw.mcp.names import DESTRUCTIVE, EDIT, OUTPUT, READ

ENABLED_KEY = "ai_connections/enabled"
FULL_ACCESS_KEY = "ai_connections/full_access"
FULL_ACCESS_KEEP_KEY = "ai_connections/full_access_keep"
APPROVAL_KEY = "ai_connections/approval/{effect}"
#: The configured game folder (Settings > Paths).
GAME_FOLDER_KEY = "archive/package_root"

ASK = "ask"
ALLOW = "allow"
#: Classes the user can set; read always runs.
CONFIGURABLE = (EDIT, DESTRUCTIVE, OUTPUT)
DEFAULTS = {READ: ALLOW, EDIT: ASK, DESTRUCTIVE: ASK, OUTPUT: ASK}

ALLOW_ONCE = "allow_once"
ALLOW_SESSION = "allow_session"
DENY = "deny"
PROMPT_TIMEOUT_S = 300.0

#: Settings no tool may change, whatever its approval: only the user can.
PROTECTED_PREFIXES = ("ai_connections/",)
PROTECTED_KEYS = frozenset({GAME_FOLDER_KEY})


def _bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in ("1", "true", "yes", "on")
    return bool(value)


def is_protected_setting(key: str) -> bool:
    text = str(key or "").replace("\\", "/").strip("/").casefold()
    return text in {k.casefold() for k in PROTECTED_KEYS} or text.startswith(PROTECTED_PREFIXES)


def refuse_protected_setting(key: str) -> None:
    """Every settings tool calls this before it writes a key."""

    if is_protected_setting(key):
        raise ToolError(REFUSED, "Only you can change this setting in CDMW: AI connections, their approvals, "
                                 "Full access and the game folder are never changed by a tool.")


def connections_enabled(settings) -> bool:
    return settings is not None and _bool(settings.value(ENABLED_KEY, False))


def approval_mode(settings, effect: str) -> str:
    if effect == READ:
        return ALLOW
    value = str(settings.value(APPROVAL_KEY.format(effect=effect), DEFAULTS[effect]) if settings is not None
                else DEFAULTS[effect]).strip().casefold()
    return ALLOW if value == ALLOW else ASK


def full_access(settings) -> bool:
    return settings is not None and _bool(settings.value(FULL_ACCESS_KEY, False))


def end_full_access_unless_kept(settings) -> bool:
    """Called once when the app starts: Full access ends with the session unless kept. True if it ended."""

    if settings is None or not full_access(settings) or _bool(settings.value(FULL_ACCESS_KEEP_KEY, False)):
        return False
    settings.setValue(FULL_ACCESS_KEY, False)
    return True


@dataclass
class ApprovalRequest:
    """One question in the app: may ``client`` run ``tool`` with these arguments?"""

    client: str
    tool: str
    title: str
    effect: str
    arguments: Mapping[str, object]
    change: str
    answer: str = ""
    #: Called with the answer once it is known, on whichever thread decided it.
    on_decided: list = field(default_factory=list, repr=False)
    _answered: threading.Event = field(default_factory=threading.Event, repr=False)

    def decide(self, answer: str) -> None:
        if answer not in (ALLOW_ONCE, ALLOW_SESSION, DENY) or self._answered.is_set():
            return
        self.answer = answer
        self._answered.set()
        for listener in list(self.on_decided):
            try:
                listener(answer)
            except Exception:
                pass

    @property
    def decided(self) -> bool:
        return self._answered.is_set()

    def wait(self, timeout: float, cancel: threading.Event | None = None) -> str:
        """The answer; DENY after ``timeout`` or when ``cancel`` is set."""

        import time

        deadline = time.monotonic() + max(0.0, timeout)
        while not self._answered.wait(0.05):
            if time.monotonic() >= deadline or (cancel is not None and cancel.is_set()):
                self.decide(DENY)
        return self.answer


CHANGE_TEXT = {
    EDIT: "It changes the open session or document. You can undo it.",
    DESTRUCTIVE: "It deletes something you made in the CDMW folder. Undo cannot bring it back.",
    OUTPUT: "It writes files outside the session (a mod, an export or a draft folder). Nothing is written "
            "into the game.",
}


class ApprovalPolicy:
    """Decides each call by its class; asks through ``ask(request)`` when it must."""

    def __init__(self, settings, ask=None, *, timeout: float = PROMPT_TIMEOUT_S) -> None:
        self.settings = settings
        self._ask = ask
        self.timeout = timeout

    def needs_prompt(self, effect: str, tool: str, session_allowed: set[str]) -> bool:
        if effect == READ or tool in session_allowed:
            return False
        if full_access(self.settings):
            return False
        return approval_mode(self.settings, effect) != ALLOW

    def approve(self, *, client: str, tool: str, title: str, effect: str, arguments: Mapping[str, object],
                session_allowed: set[str], cancel: threading.Event | None = None) -> str:
        """``"no_prompt"``, ``"session"``, ALLOW_ONCE or ALLOW_SESSION; raises ``refused`` when declined."""

        if effect == READ or full_access(self.settings) or approval_mode(self.settings, effect) == ALLOW:
            return "no_prompt"
        if tool in session_allowed:
            return "session"
        if self._ask is None:
            raise ToolError(REFUSED, "CDMW cannot ask you now, so the call was declined.")
        request = ApprovalRequest(client=client, tool=tool, title=title, effect=effect,
                                  arguments=dict(arguments), change=CHANGE_TEXT.get(effect, ""))
        self._ask(request)
        answer = request.wait(self.timeout, cancel)
        if answer == ALLOW_SESSION:
            session_allowed.add(tool)
        if answer not in (ALLOW_ONCE, ALLOW_SESSION):
            raise ToolError(REFUSED, DECLINED_MESSAGE)
        return answer
