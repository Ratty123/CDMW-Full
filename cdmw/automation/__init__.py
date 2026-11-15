"""Automation bridge for tests and timing harnesses (P13 stage A).

Off in every normal launch. It starts only when asked (``--automation`` or
``CDMW_AUTOMATION=1``), only under a private profile (``CDMW_PROFILE_DIR``),
and only with a per-run token from the launcher's environment. It drives the
app through the same calls a user's clicks make and never writes archives.
"""

from cdmw.automation.policy import (
    AUTOMATION_ENV,
    HIDDEN_ENV,
    PIPE_ENV,
    TOKEN_ENV,
    AutomationRefused,
    AutomationSettings,
    automation_requested,
    automation_settings,
)

__all__ = [
    "AUTOMATION_ENV",
    "HIDDEN_ENV",
    "PIPE_ENV",
    "TOKEN_ENV",
    "AutomationRefused",
    "AutomationSettings",
    "automation_requested",
    "automation_settings",
]
