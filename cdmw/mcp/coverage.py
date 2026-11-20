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


# ----- Surfaces: what the app offers that the command registry does not see ------------------
#
# ``coverage.json``'s ``surfaces`` section has one row per menu entry, dialog class, Mesh Editor
# host command, Mesh Editor helper control and rail page, found by reading the source. Each row
# names the tool or registry command that reaches it, or a gap. ``generic_only`` is a gap the
# generic tools (app.ui, app.ui_act, app.run_command) already reach; it names the plan item that
# will give it a typed tool. ``tests/test_mcp_coverage.py`` fails when the scan finds something
# without a row, so a new menu entry or dialog cannot ship without a decision.

SURFACE_GAPS = (*GAPS, "generic_only")
SURFACE_KINDS = ("menu", "dialog", "host_command", "helper_control", "rail_page")

_REPO = Path(__file__).resolve().parents[2]
_MENU_ROOTS = ("cdmw/ui", "tools")
_DIALOG_BASES = {"QDialog", "QWizard"}
_HOST_COMMAND_FILES = ("cdmw/services/mesh_rust_authoring.py", "cdmw/services/mesh_rust_replacement.py")
_CONTROL_CONTRACT = "tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/control_contract.rs"
_TRANSLATORS = {"tr", "_translate", "translate_active_ui_text", "as_label", "QCoreApplication.translate"}


def _python_sources(roots):
    for root in roots:
        folder = _REPO / root
        if folder.is_dir():
            yield from sorted(path for path in folder.rglob("*.py") if "__pycache__" not in path.parts)


def _relative(path: Path) -> str:
    return path.relative_to(_REPO).as_posix()


def _literal_text(node) -> str | None:
    import ast

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call) and node.args:
        name = ast.unparse(node.func).split(".")[-1]
        if name in {part.split(".")[-1] for part in _TRANSLATORS}:
            return _literal_text(node.args[-1] if name == "translate" else node.args[0])
    return None


def _menu_entry(call) -> str:
    """An ``addAction`` call's entry text, or its source when the text is worked out at run time."""

    import ast

    for argument in call.args[:2]:
        text = _literal_text(argument)
        if text is not None:
            return text
    return "<" + ast.unparse(call.args[0]) + ">"


def scan_menus() -> list[tuple[str, str]]:
    """``(module, entry)`` for every ``addAction`` in the interface code, sorted and unique."""

    import ast

    found = set()
    for path in _python_sources(_MENU_ROOTS):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "addAction" and node.args):
                found.add((_relative(path), _menu_entry(node)))
    return sorted(found)


def scan_dialogs() -> list[tuple[str, str]]:
    """``(module, class)`` for every dialog class in the interface code, through subclasses too."""

    import ast

    classes = {}
    for path in _python_sources(_MENU_ROOTS):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = {ast.unparse(base).split(".")[-1] for base in node.bases}
                classes.setdefault(node.name, []).append((_relative(path), bases))
    dialogs = set(_DIALOG_BASES)
    changed = True
    while changed:
        changed = False
        for name, places in classes.items():
            if name not in dialogs and any(bases & dialogs for _, bases in places):
                dialogs.add(name)
                changed = True
    return sorted((module, name) for name, places in classes.items() if name in dialogs - _DIALOG_BASES
                  for module, bases in places if bases & dialogs)


def scan_host_commands() -> list[str]:
    """The Mesh Editor command names CDMW's host side handles: every string ``command`` is compared
    with, and every prefix it is dispatched by (``morph_*``)."""

    import ast

    names = set()
    for relative in _HOST_COMMAND_FILES:
        tree = ast.parse((_REPO / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "command":
                for comparator in node.comparators:
                    if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                        names.add(comparator.value)
                    elif isinstance(comparator, (ast.Set, ast.Tuple, ast.List)):
                        names.update(element.value for element in comparator.elts
                                     if isinstance(element, ast.Constant) and isinstance(element.value, str))
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "startswith" and isinstance(node.func.value, ast.Name)
                  and node.func.value.id == "command"):
                for argument in node.args:
                    values = argument.elts if isinstance(argument, ast.Tuple) else [argument]
                    names.update(value.value + "*" for value in values
                                 if isinstance(value, ast.Constant) and isinstance(value.value, str))
    names.discard("")
    return sorted(names)


def scan_helper_controls() -> list[str]:
    """The control keys of the Mesh Editor helper's own interface (``PRODUCT_CORE_ROWS``)."""

    source = (_REPO / _CONTROL_CONTRACT).read_text(encoding="utf-8")
    block = source.split('const PRODUCT_CORE_ROWS: &str = r#"', 1)[1].split('"#', 1)[0]
    return sorted({line.split("|", 1)[0] for line in block.splitlines() if line.strip()})


def scan_rail_pages() -> list[str]:
    from cdmw.ui.shell.compact.registry import COMPACT_TOOL_SPECS

    return sorted(spec.key for spec in COMPACT_TOOL_SPECS)


def surface_key(kind: str, *parts: str) -> str:
    return kind + ":" + "|".join(parts)


def scan_surfaces() -> dict[str, tuple[str, ...]]:
    """Every surface the source offers, by its row key."""

    found: dict[str, tuple[str, ...]] = {}
    for module, entry in scan_menus():
        found[surface_key("menu", module, entry)] = ("menu", module, entry)
    for module, name in scan_dialogs():
        found[surface_key("dialog", module, name)] = ("dialog", module, name)
    for name in scan_host_commands():
        found[surface_key("host_command", name)] = ("host_command", name)
    for name in scan_helper_controls():
        found[surface_key("helper_control", name)] = ("helper_control", name)
    for name in scan_rail_pages():
        found[surface_key("rail_page", name)] = ("rail_page", name)
    return found


def surface_rows() -> dict[str, dict[str, object]]:
    return {row["key"]: row for row in load_coverage().get("surfaces", ())}
