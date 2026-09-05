from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_native_core import find_native_mesh_core_binary
from cdmw.ui.mesh_editor.native_topology_updates import _material_source_index
from cdmw.ui.mesh_editor.static_replacement_adapter import StaticReplacementMeshEditSession
from tools.mesh_editor_dev_harness import _build_two_part_synthetic_mesh


ROOT = Path(__file__).resolve().parents[1]
DOTNET = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET / name).read_text(encoding="utf-8")






def test_whole_part_delete_sends_affected_only_shrink() -> None:
    # `delete` is a native mesh-edit command and the Python fallback is disabled
    # by design, so without the core built there is no topology update to assert.
    if find_native_mesh_core_binary() is None:
        pytest.skip("cdmw_mesh_core is not built")
    session = StaticReplacementMeshEditSession(session_id="dotnet-partial-delete")
    session.open(_build_two_part_synthetic_mesh())
    try:
        deleted = session.apply("delete", source_indices=(0,), delete_parts=True)
        update = deleted.native_update

        assert not update.replace_all_triangles
        assert update.final_submesh_count == 1
        assert update.triangle_source_submesh_indices == (0, 1)
        assert len(update.triangle_groups) == 1
        group = update.triangle_groups[0]
        assert group["source_submesh_index"] == 0
        assert not (group.get("positions") or group.get("positions_binary"))
        assert not (group.get("indices") or group.get("indices_binary"))
    finally:
        session.close()


def test_dotnet_packet_forwards_explicit_final_submesh_count() -> None:
    sender = (ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_payloads.py").read_text(encoding="utf-8")
    update = (ROOT / "cdmw" / "ui" / "mesh_editor" / "controller.py").read_text(encoding="utf-8")
    topology = (ROOT / "cdmw" / "ui" / "mesh_editor" / "controller_topology.py").read_text(encoding="utf-8")

    assert "final_submesh_count: int | None = None" in update
    assert '"final_submesh_count": update.final_submesh_count' in sender
    assert "final_submesh_count(self, result)" in update
    assert "shrink_source_indices(result, requested, final_count)" in update
    assert "return tuple(range(first_affected, last_affected))" in topology


def test_material_lineage_beats_ambiguous_duplicate_labels() -> None:
    duplicate = SimpleNamespace(name="same", material="same", texture="same.dds")
    current = SimpleNamespace(
        name="same",
        material="same",
        texture="same.dds",
        cdmw_mesh_edit_material_source_submesh_index=1,
    )

    assert _material_source_index(current, 0, (duplicate, duplicate)) == 1
