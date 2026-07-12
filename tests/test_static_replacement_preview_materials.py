from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_preview_materials import (
    apply_original_material_preview,
    copy_exact_clone_original_preview_materials,
    copy_original_preview_material,
    copy_preview_material_bindings_to_mesh,
    preview_mesh_surface_matches,
)
from cdmw.ui.archive_browser.static_replacement_mesh_edit_session import (
    _mesh_editor_ensure_static_replacement_session,
)


def _mesh(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "positions": [(1.0, 1.0, 1.0), (2.0, 2.0, 2.0), (3.0, 3.0, 3.0)],
        "indices": [0, 1, 2],
        "texture_coordinates": [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
        "normals": [(0.0, 0.0, 1.0)] * 3,
        "material_name": "",
        "preview_material_texture_inputs": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_preview_mesh_surface_matches_translated_clone_only() -> None:
    src = _mesh()
    translated = _mesh(positions=[(3.0, 4.0, 5.0), (4.0, 5.0, 6.0), (5.0, 6.0, 7.0)])
    distorted = _mesh(positions=[(3.0, 4.0, 5.0), (4.0, 5.0, 7.0), (5.0, 6.0, 7.0)])

    assert preview_mesh_surface_matches(translated, src)
    assert not preview_mesh_surface_matches(distorted, src)
    assert not preview_mesh_surface_matches(_mesh(indices=[0, 2, 1]), src)


def test_copy_original_preview_material_clones_preview_attrs_and_surface_attrs() -> None:
    src = _mesh(
        material_name="Original",
        preview_material_texture_inputs={"base": ["diffuse.dds"]},
        texture_coordinates=[(0.25, 0.5), (0.75, 0.5), (0.75, 1.0)],
        normals=[(1.0, 0.0, 0.0)] * 3,
    )
    dst = _mesh(positions=[(11.0, 11.0, 11.0), (12.0, 12.0, 12.0), (13.0, 13.0, 13.0)])

    copy_original_preview_material(dst, src, copy_matching_surface=True)
    src.preview_material_texture_inputs["base"].append("mutated.dds")

    assert dst.material_name == "Original"
    assert dst.preview_material_texture_inputs == {"base": ["diffuse.dds"]}
    assert dst.texture_coordinates == [(0.25, 0.5), (0.75, 0.5), (0.75, 1.0)]
    assert dst.normals == [(1.0, 0.0, 0.0)] * 3


def test_copy_preview_material_bindings_to_mesh_keeps_paths_without_images() -> None:
    bindings = {"base": ["body.dds"]}
    preview_model = SimpleNamespace(
        meshes=[
            _mesh(
                preview_texture_path="C:/cache/body.dds",
                preview_texture_dds_path="C:/cache/body.dds",
                preview_texture_image=object(),
                preview_material_texture_inputs=bindings,
            )
        ]
    )
    submesh = SimpleNamespace()

    assert copy_preview_material_bindings_to_mesh(
        SimpleNamespace(submeshes=[submesh]),
        preview_model,
    ) == 1
    bindings["base"].append("mutated.dds")

    assert submesh.preview_texture_path == "C:/cache/body.dds"
    assert submesh.preview_texture_dds_path == "C:/cache/body.dds"
    assert submesh.preview_material_texture_inputs == {"base": ["body.dds"]}
    assert not hasattr(submesh, "preview_texture_image")


def test_modify_original_session_uses_live_resolved_preview_model() -> None:
    stale_model = SimpleNamespace(meshes=[_mesh(preview_texture_path="")])
    resolved_model = SimpleNamespace(
        meshes=[_mesh(preview_texture_path="C:/cache/body.dds")]
    )
    source_mesh = SimpleNamespace(submeshes=[SimpleNamespace()])

    class FakeSession:
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            self.controller = SimpleNamespace()

        def open(self, mesh: object) -> None:
            self.controller.working_mesh = lambda *, clone=False: mesh

        def close(self) -> None:
            pass

    session_state: dict[str, object] = {}
    state = SimpleNamespace(
        _mesh_edit_state=SimpleNamespace(replacement_mesh_for_mapping=source_mesh),
        mesh_editor_static_replacement_session_state=session_state,
        original_reference_preview_model=stale_model,
        modify_original_clone_mode=True,
        context={"_get_original_reference_preview_model": lambda: resolved_model},
        StaticReplacementMeshEditSession=FakeSession,
        source_skeleton=None,
        mesh_edit_native_result_submesh_counts={},
    )
    callbacks = SimpleNamespace(
        _mesh_editor_current_edit_revision=lambda: 0,
        _mesh_editor_clear_static_replacement_session=session_state.clear,
    )

    session = _mesh_editor_ensure_static_replacement_session(state, callbacks)

    assert isinstance(session, FakeSession)
    assert source_mesh.submeshes[0].preview_texture_path == "C:/cache/body.dds"
    assert session_state["material_source"] is resolved_model


def test_copy_exact_clone_original_preview_materials_requires_clone_preview_state() -> None:
    original_model = SimpleNamespace(meshes=[_mesh(material_name="A"), _mesh(material_name="B")])
    preview_model = SimpleNamespace(meshes=[_mesh(), _mesh()])

    assert not copy_exact_clone_original_preview_materials(
        preview_model,
        modify_original_clone_mode=False,
        original_texture_preview_enabled=True,
        original_reference_preview_model=original_model,
    )
    assert copy_exact_clone_original_preview_materials(
        preview_model,
        modify_original_clone_mode=True,
        original_texture_preview_enabled=True,
        original_reference_preview_model=original_model,
    )
    assert [mesh.material_name for mesh in preview_model.meshes] == ["A", "B"]


def test_apply_original_material_preview_uses_direct_source_preview_map() -> None:
    original_model = SimpleNamespace(
        meshes=[_mesh(material_name="Source 0"), _mesh(material_name="Source 1")]
    )
    preview_model = SimpleNamespace(meshes=[_mesh(), _mesh()])

    apply_original_material_preview(
        preview_model,
        original_texture_preview_enabled=True,
        original_reference_preview_model=original_model,
        modify_original_clone_mode=False,
        mapped_preview=False,
        current_mappings=(),
        direct_source_preview_index_map={1: 0},
        preview_target_mesh_indices=lambda *_args: (),
    )

    assert [mesh.material_name for mesh in preview_model.meshes] == ["Source 1", ""]


def test_apply_original_material_preview_uses_mapping_targets_for_mapped_preview() -> None:
    original_model = SimpleNamespace(
        meshes=[_mesh(material_name="Original Target"), _mesh(material_name="Other")]
    )
    preview_model = SimpleNamespace(meshes=[_mesh(), _mesh()])
    mappings = (
        SimpleNamespace(
            target_submesh_index=0,
            target_submesh_name="Body",
            source_submesh_indices=(5,),
        ),
    )

    apply_original_material_preview(
        preview_model,
        original_texture_preview_enabled=True,
        original_reference_preview_model=original_model,
        modify_original_clone_mode=False,
        mapped_preview=True,
        current_mappings=mappings,
        direct_source_preview_index_map={},
        preview_target_mesh_indices=lambda _model, _target, _sources, _mapped, _mappings: (1,),
    )

    assert [mesh.material_name for mesh in preview_model.meshes] == ["", "Original Target"]
