"""Short, safe summaries of tool arguments, for the approval prompt and the audit log.

No secrets and no file contents: a value whose name mentions a key, token,
secret, password, credential or authorization is ``[removed]``; text longer
than 300 characters is cut with its length noted; lists keep their first 32
items; data that looks like image or file bytes is counted, not kept. Paths
inside the user's folder are shortened to ``%USERPROFILE%``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

TEXT_LIMIT = 300
LIST_LIMIT = 32
DEPTH_LIMIT = 4
_SECRET_WORDS = ("key", "token", "secret", "password", "credential", "authorization")
_DATA_WORDS = ("data", "bytes", "image", "pixels", "content", "base64")


def _secret(name: str) -> bool:
    text = name.casefold()
    return any(word in text for word in _SECRET_WORDS) and text not in ("page_token",)


def _payload(name: str) -> bool:
    text = name.casefold()
    return any(text == word or text.endswith("_" + word) for word in _DATA_WORDS)


def shorten_path(text: str) -> str:
    home = os.path.expanduser("~")
    if home and home != "~" and os.path.normcase(text).startswith(os.path.normcase(home)):
        return "%USERPROFILE%" + text[len(home):]
    return text


def summarize(value: object, name: str = "", depth: int = 0) -> object:
    if name and _secret(name):
        return "[removed]"
    if name and _payload(name) and isinstance(value, (str, bytes, list)):
        return f"[{len(value)} {'characters' if isinstance(value, str) else 'items' if isinstance(value, list) else 'bytes'} not logged]"
    if isinstance(value, bytes):
        return f"[{len(value)} bytes not logged]"
    if isinstance(value, str):
        text = shorten_path(value)
        return text if len(text) <= TEXT_LIMIT else f"{text[:TEXT_LIMIT]}... ({len(text)} characters)"
    if isinstance(value, Mapping):
        if depth >= DEPTH_LIMIT:
            return f"[object with {len(value)} fields]"
        return {str(k): summarize(v, str(k), depth + 1) for k, v in list(value.items())[:LIST_LIMIT]}
    if isinstance(value, (list, tuple)):
        if depth >= DEPTH_LIMIT:
            return f"[{len(value)} items]"
        items = [summarize(v, "", depth + 1) for v in list(value)[:LIST_LIMIT]]
        if len(value) > LIST_LIMIT:
            items.append(f"... {len(value) - LIST_LIMIT} more")
        return items
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return summarize(str(value), name, depth)


def summarize_arguments(arguments: Mapping[str, object] | None) -> dict[str, object]:
    return summarize(dict(arguments or {})) if arguments else {}
