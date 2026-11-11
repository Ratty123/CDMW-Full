"""When the automation bridge may start, and with what."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

AUTOMATION_ENV = "CDMW_AUTOMATION"
TOKEN_ENV = "CDMW_AUTOMATION_TOKEN"
PIPE_ENV = "CDMW_AUTOMATION_PIPE"
# Test harnesses run the real window hidden, as the P0 harness did.
HIDDEN_ENV = "CDMW_AUTOMATION_HIDDEN"
PIPE_PREFIX = "\\\\.\\pipe\\cdmw-automation-"
_MIN_TOKEN_BYTES = 16


class AutomationRefused(RuntimeError):
    """The bridge will not start; the message names the reason."""


@dataclass(frozen=True)
class AutomationSettings:
    token: bytes
    address: str
    hidden: bool


def automation_requested() -> bool:
    return os.environ.get(AUTOMATION_ENV, "").strip() == "1"


def pipe_address(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name or ""))[:64]
    if not clean:
        raise AutomationRefused("The automation pipe needs a name.")
    return PIPE_PREFIX + clean


def automation_settings() -> AutomationSettings:
    """Check every rule before anything listens; raise with the reason."""

    from cdmw.app.app_folder import default_app_folder, profile_override, profile_scope

    profile = profile_override()
    if profile is None:
        raise AutomationRefused(
            "Automation needs a private profile: set CDMW_PROFILE_DIR to a folder of its own.")
    if profile == default_app_folder().resolve():
        raise AutomationRefused("Automation refuses the app's own folder as its profile.")
    text = os.environ.get(TOKEN_ENV, "").strip()
    try:
        token = bytes.fromhex(text)
    except ValueError:
        token = b""
    if len(token) < _MIN_TOKEN_BYTES:
        raise AutomationRefused(
            f"Automation needs a token of at least {_MIN_TOKEN_BYTES} bytes, as hex, in {TOKEN_ENV}.")
    name = os.environ.get(PIPE_ENV, "").strip() or profile_scope()
    return AutomationSettings(token=token, address=pipe_address(name),
                              hidden=os.environ.get(HIDDEN_ENV, "").strip() == "1")
