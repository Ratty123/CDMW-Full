"""``coverage.json``: what covers each command and capability (P13 stage C, design record 2.7).

Every registry command and every capability of every panel has a row, with
the tool that covers it or an accepted gap:

* ``not_built``: its tool comes later; the row names the milestone;
* ``needs_pointer``: the action needs a hand on a pointer or pen; the row
  names the tool that takes points instead;
* ``writes_into_game``: no tool ever covers it, under any setting;
* ``user_only``: only the user may do it, because it could change the AI
  connection settings, the approvals or the game folder (section 7, answer 8).

``tests/test_mcp_coverage.py`` fails when a command appears without a row,
when a row names a tool or a command that does not exist, and when a built
tool covers nothing.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

COVERAGE_FILE = Path(__file__).with_name("coverage.json")
GAPS = ("not_built", "needs_pointer", "writes_into_game", "user_only")


@lru_cache(maxsize=1)
def load_coverage() -> dict[str, object]:
    return json.loads(COVERAGE_FILE.read_text(encoding="utf-8"))


def command_row(command_id: str) -> dict[str, object] | None:
    document = load_coverage()
    row = document["commands"].get(command_id)
    if row is not None:
        return row
    for pattern in document["command_patterns"]:
        if command_id.startswith(pattern["prefix"]):
            return pattern
    return None
