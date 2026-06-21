from __future__ import annotations

"""Guide text parsing helpers for the standalone Texture Editor UI."""

from typing import List, Sequence, Tuple


def parse_texture_editor_guides_text(text: str) -> Tuple[int, ...]:
    values: List[int] = []
    for raw in (text or "").replace(";", ",").split(","):
        token = raw.strip()
        if not token:
            continue
        try:
            values.append(max(0, int(round(float(token)))))
        except Exception:
            continue
    return tuple(sorted(dict.fromkeys(values)))


def format_texture_editor_guides_text(values: Sequence[int]) -> str:
    return ", ".join(str(max(0, int(value))) for value in values)


def texture_editor_guides_cleared_status_text() -> str:
    return "Texture Editor guides cleared."


__all__ = [
    "format_texture_editor_guides_text",
    "parse_texture_editor_guides_text",
    "texture_editor_guides_cleared_status_text",
]
