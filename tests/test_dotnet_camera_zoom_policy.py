from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DOTNET_ROOT = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET_ROOT / name).read_text(encoding="utf-8")


def _source_family(pattern: str) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(DOTNET_ROOT.glob(pattern))
    )


def _between(source: str, start: str, end: str) -> str:
    """One method's body, or a failure naming the marker that moved.

    `str.split` on an absent separator returns the whole remainder, so a
    delimiter that drifts silently widens the slice to end of file instead of
    failing. That is how this guard spent two days checking the wrong region:
    `IsPanGesture` stopped being `static` on 2026-07-29 and nothing said so
    until unrelated code landed inside the widened slice.
    """
    assert start in source, f"slice start marker is gone: {start!r}"
    tail = source.split(start, maxsplit=1)[1]
    assert end in tail, f"slice end marker is gone or moved above {start!r}: {end!r}"
    return tail.split(end, maxsplit=1)[0]


def test_dotnet_wheel_zoom_is_reversible_and_uses_fit_relative_bounds() -> None:
    host_presentation_source = (
        ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_presentation.py"
    ).read_text(encoding="utf-8")

    expected_steps = (
        0.1,
        0.25,
        0.5,
        0.75,
        1.0,
        1.5,
        2.0,
        3.0,
        4.0,
        6.0,
        8.0,
        12.0,
        16.0,
        24.0,
        32.0,
        48.0,
        64.0,
    )

    assert 'stamped_camera["command_generation"] = generation' in host_presentation_source
    assert 'set(state or {}) == {"camera"}' in host_presentation_source




def test_hidden_runtime_proof_covers_shared_reversible_zoom_policy() -> None:
    real_input = "\n".join(
        (ROOT / "tools" / "mesh_harness" / name).read_text(encoding="utf-8")
        for name in ("real_dotnet_input.py", "real_dotnet_zoom_input.py")
    )

    assert "_camera_preserves_native_zoom_anchor(" in real_input
    assert '"target_panned_anchor_locked"' in real_input
    assert '"models_remained_visible_and_panned_anchor_locked"' in real_input
