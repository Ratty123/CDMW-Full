"""Every mesh edit action must reach the native core, or be listed as not doing so.

The native mesh core is a required release binary, and
``_allow_python_mesh_edit_fallback`` blocks the Python geometry implementation
whenever that core is present. So in any shipped build the Python bodies in
``mesh_edit_ops`` do not run: a native call that returns ``None`` falls through
to ``return set(), {}``, and the edit becomes a silent no-op.

That makes "does this action have a native entry point?" a correctness question,
not a performance one. A new action wired up without one lands in code that only
executes when the native core is absent entirely -- which no supported
configuration produces. These tests pin the current answer so that gap has to be
declared rather than discovered.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "cdmw/modding/mesh_edit_ops.py"
SPEC = ROOT / "CrimsonDesertModWorkbench.spec"
DISPATCHER = "apply_mesh_edit_geometry_action"
NATIVE_PREFIX = "apply_native_mesh_"
FALLBACK_GATE = "_allow_python_mesh_edit_fallback"

#: Actions that legitimately have no native entry point, with the reason.
#: Adding to this list is a decision, not a formality -- the Python body only
#: runs where the native core is missing.
PYTHON_ONLY_ACTIONS = {
    "material_assign": "reassigns material indices; no geometry is touched",
    "material_copy": "copies material indices; no geometry is touched",
    "quadrangulate_display": "display-only no-op that returns an empty change set",
}


def _ops_tree() -> ast.Module:
    return ast.parse(OPS.read_text(encoding="utf-8"))


def _dispatch_table() -> dict[str, str]:
    """Action string -> the function the dispatcher returns for it."""
    tree = _ops_tree()
    table: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == DISPATCHER):
            continue
        for branch in ast.walk(node):
            if not isinstance(branch, ast.If):
                continue
            actions = [
                constant.value
                for constant in ast.walk(branch.test)
                if isinstance(constant, ast.Constant)
                and isinstance(constant.value, str)
            ]
            implementation = ""
            for statement in ast.walk(branch):
                if isinstance(statement, ast.Return) and isinstance(
                    statement.value, ast.Call
                ):
                    function = statement.value.func
                    if isinstance(function, ast.Name):
                        implementation = function.id
            for action in actions:
                table.setdefault(action, implementation)
    assert table, f"{DISPATCHER} no longer parses as a dispatch table"
    return table


def _native_calls_by_function() -> dict[str, set[str]]:
    calls: dict[str, set[str]] = {}
    for node in ast.walk(_ops_tree()):
        if not isinstance(node, ast.FunctionDef):
            continue
        found = {
            sub.func.id
            for sub in ast.walk(node)
            if isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Name)
            and sub.func.id.startswith(NATIVE_PREFIX)
        }
        calls[node.name] = found
    return calls


def _functions_using_the_fallback_gate() -> set[str]:
    return {
        node.name
        for node in ast.walk(_ops_tree())
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Name)
            and sub.func.id == FALLBACK_GATE
            for sub in ast.walk(node)
        )
    }


DISPATCH = _dispatch_table()
NATIVE_BACKED_ACTIONS = sorted(set(DISPATCH) - set(PYTHON_ONLY_ACTIONS))


@pytest.mark.parametrize("action", NATIVE_BACKED_ACTIONS)
def test_action_reaches_the_native_core(action: str) -> None:
    implementation = DISPATCH[action]
    native = _native_calls_by_function().get(implementation, set())

    assert native, (
        f"{action!r} dispatches to {implementation}, which calls no "
        f"{NATIVE_PREFIX}* entry point. In a shipped build its Python body is "
        "unreachable, so the edit would silently do nothing. Give it a native "
        "path, or add it to PYTHON_ONLY_ACTIONS with a reason."
    )


@pytest.mark.parametrize("action", NATIVE_BACKED_ACTIONS)
def test_native_backed_action_guards_its_python_fallback(action: str) -> None:
    implementation = DISPATCH[action]

    assert implementation in _functions_using_the_fallback_gate(), (
        f"{action!r} dispatches to {implementation}, which attempts a native "
        f"edit but never consults {FALLBACK_GATE}. Its Python body would run "
        "alongside a working native core and could diverge from it."
    )


def test_python_only_actions_are_still_dispatched() -> None:
    # Keeps the allowlist from outliving the actions it excuses.
    stale = sorted(set(PYTHON_ONLY_ACTIONS) - set(DISPATCH))

    assert not stale, f"PYTHON_ONLY_ACTIONS lists actions nothing dispatches: {stale}"


def test_python_only_actions_really_have_no_native_path() -> None:
    native_calls = _native_calls_by_function()
    promoted = sorted(
        action
        for action in PYTHON_ONLY_ACTIONS
        if native_calls.get(DISPATCH[action], set())
    )

    assert not promoted, (
        f"{promoted} now have native entry points; remove them from "
        "PYTHON_ONLY_ACTIONS so the coverage gate starts holding them"
    )


def test_the_native_mesh_core_is_a_required_release_binary() -> None:
    # This is what makes the Python fallback unreachable in shipped builds. If
    # it stops being required, the fallback becomes live code again and needs
    # test coverage of its own.
    spec = SPEC.read_text(encoding="utf-8")
    entry = next(
        (line for line in spec.splitlines() if "cdmw-mesh-core.exe" in line),
        "",
    )

    assert entry, "the packaging spec no longer bundles cdmw-mesh-core.exe"
    assert "required_release=True" in entry, (
        "cdmw-mesh-core.exe is bundled but no longer required for release; the "
        "Python geometry fallback would become reachable and is untested"
    )
