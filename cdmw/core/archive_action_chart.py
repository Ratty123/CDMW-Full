"""Resource paths an action chart (`.paac`) names, read from its string table.

Chart strings are framed as `<strlen + 1><ASCII><NUL>` (see
`tools/placement_studio/paac.py`). Requiring that frame, rather than scanning for
anything path-like, keeps the length byte out of the name and rejects matches
inside compressed or numeric runs. Node and event structure around the strings
is not decoded here; a named path is a reference, not proof of when it plays.
"""

from __future__ import annotations

import re

MAX_ACTION_CHART_RESOURCE_NAMES = 256
_PATH_TOKEN = re.compile(rb"[A-Za-z0-9_()./\\-]{3,254}")


def action_chart_resource_names(data: bytes, *, max_names: int = MAX_ACTION_CHART_RESOURCE_NAMES) -> tuple[str, ...]:
    """Framed strings that look like paths, in first-seen order.

    Extensionless names are kept: sub-charts and sequences are stored without
    their extension, and the caller resolves them against its index.
    """

    names: dict[str, None] = {}
    for match in _PATH_TOKEN.finditer(data):
        end = match.end()
        if end >= len(data) or data[end] != 0:
            continue
        for start in range(match.start(), end - 2):
            if start and data[start - 1] == end - start + 1:
                text = data[start:end].decode("ascii").replace("\\", "/")
                if "/" in text.strip("/"):
                    names.setdefault(text, None)
                break
        if len(names) >= max_names:
            break
    return tuple(names)


__all__ = ["MAX_ACTION_CHART_RESOURCE_NAMES", "action_chart_resource_names"]
