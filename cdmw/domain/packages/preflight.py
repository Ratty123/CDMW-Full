"""Pure package preflight result types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PreflightIssue:
    code: str
    message: str
    severity: str = "warning"


@dataclass(frozen=True, slots=True)
class PreflightResult:
    issues: tuple[PreflightIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(issue.severity.lower() == "error" for issue in self.issues)


__all__ = ["PreflightIssue", "PreflightResult"]
