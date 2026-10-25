"""Theme updates for the embedded Rust Mesh Editor that outgrow one control line.

A ``theme_update`` that fits one line is sent as it is, which every helper
accepts. When its translation catalogue does not fit and the helper advertised
``ui_translation_parts_v1``, the catalogue's compact JSON text is split into
ordered ``theme_translations_part`` lines sent just ahead of the update. The
update then names the transfer instead of carrying the catalogue; the helper
applies it only when every part arrived in order and the joined text matches the
declared UTF-8 length, SHA-256 and entry count.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

THEME_TRANSLATION_PART_EVENT = "theme_translations_part"
# Slices are measured whole, so a part's quoted size is exact without a
# per-character loop on the UI thread.
_SLICE_CHARS = 4096
# Room for a part's event, identity and transfer fields around its text.
_PART_ENVELOPE_BYTES = 1024
_IDENTITY_FIELDS = (
    "protocol",
    "session_id",
    "request_id",
    "base_revision",
    "process_generation",
)


class RustThemeTransportError(ValueError):
    """A theme update cannot be expressed within the control line limit."""


def protocol_line(message: Mapping[str, object]) -> bytes:
    """Encode one control line exactly as the host writes it to the helper."""

    return (
        json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def rust_theme_digest(theme: Mapping[str, object]) -> str:
    """Identify a theme payload, so the one a helper already holds is not resent."""

    encoded = json.dumps(
        theme, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def inline_translation_budget(message: Mapping[str, object], *, line_limit: int) -> int:
    """Bytes a compact translation snapshot may use while the update stays one line."""

    payload = dict(message.get("payload") or {})  # type: ignore[arg-type]
    payload["translations"] = {}
    empty = protocol_line({**message, "payload": payload})
    return line_limit - len(empty) + len(b"{}")


def _fragments(text: str, budget: int) -> list[str]:
    fragments: list[str] = []
    current: list[str] = []
    size = 0
    for start in range(0, len(text), _SLICE_CHARS):
        piece = text[start:start + _SLICE_CHARS]
        cost = len(json.dumps(piece, ensure_ascii=False).encode("utf-8")) - 2
        if current and size + cost > budget:
            fragments.append("".join(current))
            current, size = [], 0
        current.append(piece)
        size += cost
    fragments.append("".join(current))
    return fragments


def rust_theme_update_messages(
    message: Mapping[str, object],
    *,
    line_limit: int,
    parts_supported: bool,
) -> list[dict[str, object]] | None:
    """Return the control messages that deliver one theme update, in send order.

    ``None`` means the update needs translation parts that this helper lacks.
    """

    if len(protocol_line(message)) <= line_limit:
        return [dict(message)]
    if not parts_supported:
        return None
    payload = dict(message["payload"])  # type: ignore[arg-type]
    translations = payload.pop("translations", {})
    # The same compact form translation_snapshot() measures against its limit.
    text = json.dumps(translations, ensure_ascii=False, separators=(",", ":"))
    data = text.encode("utf-8")
    fragments = _fragments(text, line_limit - _PART_ENVELOPE_BYTES)
    transfer = {
        "part_count": len(fragments),
        "byte_length": len(data),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
    }
    identity = {field: message[field] for field in _IDENTITY_FIELDS}
    messages: list[dict[str, object]] = [
        {
            "event": THEME_TRANSLATION_PART_EVENT,
            **identity,
            **transfer,
            "part_index": index,
            "data": fragment,
        }
        for index, fragment in enumerate(fragments)
    ]
    messages.append({
        **message,
        "payload": payload,
        "translations_transfer": {**transfer, "entry_count": len(translations)},
    })
    oversized = max(len(protocol_line(item)) for item in messages)
    if oversized > line_limit:
        raise RustThemeTransportError(
            f"Mesh Editor theme line is {oversized:,} bytes; limit is {line_limit:,}."
        )
    return messages


__all__ = [
    "THEME_TRANSLATION_PART_EVENT",
    "RustThemeTransportError",
    "inline_translation_budget",
    "protocol_line",
    "rust_theme_digest",
    "rust_theme_update_messages",
]
