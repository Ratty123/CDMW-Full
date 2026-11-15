"""Names shared by the command registry and the MCP tool table (P13 stage C).

Standard library only, so the registry, the bridge process and tests can all
import it without Qt.
"""

from __future__ import annotations

import re

#: What a tool or command can change (P13 stage C, "Effect classes and approvals").
READ = "read"  # changes nothing
EDIT = "edit"  # changes a session or document, undoable
DESTRUCTIVE = "destructive"  # deletes something the user made inside the CDMW folder
OUTPUT = "output"  # writes a file outside the session: a mod, an export, a draft folder
EFFECT_CLASSES = (READ, EDIT, DESTRUCTIVE, OUTPUT)
#: A registry command that does not say otherwise is an edit.
DEFAULT_EFFECT = EDIT

#: The typed tool families. A registry command id never starts with one, so a
#: command and a typed tool can never take the same name (section 7, answer 2).
RESERVED_PREFIXES = (
    "search.", "files.", "view.", "mesh.", "textures.", "materials.", "saved.", "app.",
    "commands.", "new_item.", "mods.", "tables.", "strings.",
)

#: Tool names as clients see them. Claude's and OpenAI's tool names allow
#: letters, digits, "_" and "-" only, so dots become underscores, as CDMW
#: Next does; 64 characters is the shorter of the two limits.
WIRE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def reserved_prefix(name: str) -> str:
    """The reserved family prefix ``name`` starts with, or ""."""

    text = str(name or "")
    return next((prefix for prefix in RESERVED_PREFIXES if text.startswith(prefix)), "")


def wire_name(name: str) -> str:
    """The name a client calls: ``search.archive`` is ``search_archive``."""

    return str(name or "").replace(".", "_")
