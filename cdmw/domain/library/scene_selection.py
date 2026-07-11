"""Deterministic scene selection policy for multi-model archives."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence


class ModelArchiveSelectionRequired(ValueError):
    def __init__(self, archive_path: Path | str, members: Sequence[str]) -> None:
        self.archive_path = Path(archive_path)
        self.members = tuple(str(member) for member in members)
        shown = ", ".join(self.members[:20])
        suffix = f" (+{len(self.members) - 20} more)" if len(self.members) > 20 else ""
        super().__init__(
            f"ZIP archive contains multiple importable model members; choose one explicitly: "
            f"{self.archive_path}. Candidates: {shown}{suffix}"
        )


def select_model_archive_member(
    archive_path: Path | str,
    members: Sequence[str],
    *,
    selected_member: str = "",
) -> str | None:
    candidates = tuple(dict.fromkeys(_normalized_member(member) for member in members if _normalized_member(member)))
    requested = _normalized_member(selected_member)
    if not candidates:
        return None
    if requested:
        if requested not in candidates:
            raise ValueError(f"Selected ZIP model member is not available: {requested}")
        return requested
    if len(candidates) > 1:
        raise ModelArchiveSelectionRequired(archive_path, candidates)
    return candidates[0]


def _normalized_member(value: object) -> str:
    return str(value or "").strip().replace("\\", "/")


__all__ = ["ModelArchiveSelectionRequired", "select_model_archive_member"]
