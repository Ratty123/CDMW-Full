from __future__ import annotations

from array import array
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cdmw.ui.archive_browser.static_replacement_preview_mapping import (
    independent_parts,
    mapped_source_indices,
    preview_model_in_original_frame,
    preview_target_mesh_indices,
    selected_part_preview_indices,
    source_preview_geometry_key,
    unmapped_appended_source_indices,
)


def _write_f64_values(path: object, values: list[float]) -> None:
    data = array("d", values)
    with Path(str(path)).open("wb") as handle:
        data.tofile(handle)


def _write_i32_values(path: object, values: list[int]) -> None:
    data = array("i", values)
    with Path(str(path)).open("wb") as handle:
        data.tofile(handle)


def test_preview_target_mesh_indices_uses_fallback_when_unmapped() -> None:
    preview_model = SimpleNamespace(meshes=[object(), object()])

    assert preview_target_mesh_indices(
        preview_model,
        "Body",
        (0, 2, 1),
        mapped_preview=False,
        current_mappings=(),
        preview_submesh_index_map={},
    ) == (0, 1)


def test_preview_target_mesh_indices_uses_preview_map_then_name_tokens() -> None:
    preview_model = SimpleNamespace(
        meshes=[
            SimpleNamespace(name="Helmet", material_name=""),
            SimpleNamespace(name="", material_name="Body Skin"),
            SimpleNamespace(name="Cape", material_name=""),
        ]
    )
    mappings = (
        SimpleNamespace(target_submesh_index=5, target_submesh_name="Body", source_submesh_indices=(2,)),
    )

    assert preview_target_mesh_indices(
        preview_model,
        "Body",
        (2,),
        mapped_preview=True,
        current_mappings=mappings,
        preview_submesh_index_map={5: 1},
    ) == (1,)
    assert preview_target_mesh_indices(
        preview_model,
        "Body",
        (9,),
        mapped_preview=True,
        current_mappings=mappings,
        preview_submesh_index_map={},
    ) == (1,)


def test_mapped_source_indices_collects_mapping_sources() -> None:
    mappings = (
        SimpleNamespace(source_submesh_indices=(0, "2")),
        SimpleNamespace(source_submesh_indices=(2, 3)),
    )

    assert mapped_source_indices(mappings) == {0, 2, 3}


def test_independent_parts_filters_mapped_disabled_marker_and_bounds() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(material="Body", name="", marker=False),
            SimpleNamespace(material="Cape", name="", marker=False),
            SimpleNamespace(material="Marker", name="", marker=True),
            SimpleNamespace(material="Disabled", name="", marker=False),
        ]
    )
    mappings = (SimpleNamespace(source_submesh_indices=(0,)),)
    adjustments = {3: SimpleNamespace(enabled=False)}

    parts = independent_parts(
        replacement_mesh=mesh,
        independent_output_source_indices={0, 1, 2, 3, 9},
        preview_only_source_indices={0},
        current_mappings=mappings,
        source_part_adjustments=adjustments,
        default_adjustment=lambda _index: SimpleNamespace(enabled=True),
        is_marker_source=lambda source: bool(getattr(source, "marker", False)),
        source_display_name=lambda index: f"{index}: part",
        independent_part_type=SimpleNamespace,
        include_preview_only=True,
    )

    assert [(part.source_submesh_index, part.material_name, part.preview_only) for part in parts] == [
        (0, "Body", True),
        (1, "Cape", False),
    ]


def test_unmapped_appended_source_indices_filters_mapped_disabled_marker_and_bounds() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(marker=False),
            SimpleNamespace(marker=False),
            SimpleNamespace(marker=True),
            SimpleNamespace(marker=False),
        ]
    )
    mappings = (SimpleNamespace(source_submesh_indices=(0,)),)
    adjustments = {3: SimpleNamespace(enabled=False)}

    assert unmapped_appended_source_indices(
        replacement_mesh=mesh,
        appended_source_indices={0, 1, 2, 3, 9},
        current_mappings=mappings,
        source_part_adjustments=adjustments,
        default_adjustment=lambda _index: SimpleNamespace(enabled=True),
        is_marker_source=lambda source: bool(getattr(source, "marker", False)),
    ) == (1,)


def test_preview_model_in_original_frame_normalizes_meshes_and_records_maps(monkeypatch) -> None:
    monkeypatch.setenv("CDMW_DISABLE_NATIVE_MESH_CORE", "1")
    parsed_mesh = SimpleNamespace(
        path="mesh.pac",
        format="pac",
        submeshes=[
            SimpleNamespace(
                material="Body",
                texture="body.dds",
                vertices=[(2.0, 4.0, 6.0), (4.0, 6.0, 8.0), (6.0, 8.0, 10.0)],
                faces=[(0, 1, 2)],
                uvs=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
                normals=[(0.0, 0.0, 1.0)] * 3,
                preview_double_sided=True,
            ),
            SimpleNamespace(material="Empty", vertices=[], faces=[]),
        ],
    )
    source_index_map: dict[int, int] = {}
    parsed_submesh_index_map: dict[int, int] = {}

    preview = preview_model_in_original_frame(
        parsed_mesh,
        normalization_center=(1.0, 2.0, 3.0),
        normalization_scale=2.0,
        source_indices=(7,),
        source_index_map=source_index_map,
        parsed_submesh_index_map=parsed_submesh_index_map,
    )

    assert preview.path == "mesh.pac"
    assert preview.mesh_count == 1
    assert preview.vertex_count == 3
    assert preview.face_count == 1
    assert preview.normalization_center == (1.0, 2.0, 3.0)
    assert preview.meshes[0].material_name == "Body"
    assert preview.meshes[0].texture_name == "body.dds"
    assert preview.meshes[0].positions == [(2.0, 4.0, 6.0), (6.0, 8.0, 10.0), (10.0, 12.0, 14.0)]
    assert preview.meshes[0].indices == [0, 1, 2]
    assert preview.meshes[0].source_submesh_index == 7
    assert preview.meshes[0].source_vertex_indices == []
    assert preview.meshes[0].source_face_indices == []
    assert preview.meshes[0].source_vertex_range_start == 0
    assert preview.meshes[0].source_vertex_range_count == 3
    assert preview.meshes[0].source_face_range_start == 0
    assert preview.meshes[0].source_face_range_count == 1
    assert preview.meshes[0].preview_double_sided is True
    assert source_index_map == {7: 0}
    assert parsed_submesh_index_map == {0: 0}


def test_preview_model_in_original_frame_uses_native_helper_when_available() -> None:
    parsed_mesh = SimpleNamespace(
        path="mesh.pac",
        format="pac",
        submeshes=[
            SimpleNamespace(
                material="Body",
                texture="body.dds",
                vertices=[(2.0, 4.0, 6.0), (4.0, 6.0, 8.0), (6.0, 8.0, 10.0)],
                faces=[(0, 1, 2)],
                uvs=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
                normals=[(0.0, 0.0, 1.0)] * 3,
                preview_double_sided=True,
            )
        ],
    )

    def _fake_native_preview_model(*args: object, **kwargs: object) -> dict[str, object]:
        assert args[0] is parsed_mesh
        assert kwargs["normalization_center"] == (1.0, 2.0, 3.0)
        assert kwargs["normalization_scale"] == 2.0
        assert kwargs["source_indices"] == (7,)
        return {
            "status": "ok",
            "operation": "preview_model",
            "meshes": [
                {
                    "parsed_submesh_index": 0,
                    "source_submesh_index": 7,
                    "positions": [[99.0, 98.0, 97.0], [1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
                    "texture_coordinates": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]],
                    "normals": [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]],
                    "indices": [0, 1, 2],
                    "source_vertex_start": 0,
                    "source_vertex_count": 3,
                    "source_face_start": 0,
                    "source_face_count": 1,
                }
            ],
        }

    source_index_map: dict[int, int] = {}
    parsed_submesh_index_map: dict[int, int] = {}
    with patch("cdmw.modding.mesh_native_core.build_native_preview_model_in_original_frame", side_effect=_fake_native_preview_model):
        preview = preview_model_in_original_frame(
            parsed_mesh,
            normalization_center=(1.0, 2.0, 3.0),
            normalization_scale=2.0,
            source_indices=(7,),
            source_index_map=source_index_map,
            parsed_submesh_index_map=parsed_submesh_index_map,
        )

    assert preview.meshes[0].positions[0] == (99.0, 98.0, 97.0)
    assert preview.meshes[0].source_submesh_index == 7
    assert preview.meshes[0].source_vertex_indices == []
    assert preview.meshes[0].source_face_indices == []
    assert preview.meshes[0].source_vertex_range_start == 0
    assert preview.meshes[0].source_vertex_range_count == 3
    assert preview.meshes[0].source_face_range_start == 0
    assert preview.meshes[0].source_face_range_count == 1
    assert preview.meshes[0].preview_double_sided is True
    assert source_index_map == {7: 0}
    assert parsed_submesh_index_map == {0: 0}


def test_native_preview_model_bridge_uses_resident_session_when_available() -> None:
    from cdmw.modding import mesh_native_core

    parsed_mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(
                vertices=[(2.0, 4.0, 6.0), (4.0, 6.0, 8.0), (6.0, 8.0, 10.0)],
                faces=[(0, 1, 2)],
                uvs=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
                normals=[(0.0, 0.0, 1.0)] * 3,
            )
        ]
    )

    def _native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "preview-model-json"
        assert payload["operation"] == "preview_model"  # type: ignore[index]
        submesh_payload = payload["submeshes"][0]  # type: ignore[index]
        assert submesh_payload["session_id"] == "preview-session-0"
        for key in ("vertices_binary", "faces_binary", "uvs_binary", "normals_binary"):
            assert key not in submesh_payload
        positions_path = submesh_payload["positions_output_path"]
        uvs_path = submesh_payload["texture_coordinates_output_path"]
        normals_path = submesh_payload["normals_output_path"]
        indices_path = submesh_payload["indices_output_path"]
        source_vertices_path = submesh_payload["source_vertex_indices_output_path"]
        source_faces_path = submesh_payload["source_face_indices_output_path"]
        for path in (positions_path, uvs_path, normals_path, indices_path, source_vertices_path, source_faces_path):
            assert str(path)
        _write_f64_values(positions_path, [2.0, 4.0, 6.0, 4.0, 6.0, 8.0, 6.0, 8.0, 10.0])
        _write_f64_values(uvs_path, [0.0, 0.0, 1.0, 0.0, 1.0, 1.0])
        _write_f64_values(normals_path, [0.0, 0.0, 1.0] * 3)
        _write_i32_values(indices_path, [0, 1, 2])
        _write_i32_values(source_vertices_path, [0, 1, 2])
        _write_i32_values(source_faces_path, [0])
        assert timeout_seconds == 20.0
        return {
            "status": "ok",
            "operation": "preview_model",
            "mesh_count": 1,
            "vertex_count": 3,
            "face_count": 1,
            "meshes": [
                {
                    "parsed_submesh_index": 0,
                    "source_submesh_index": 7,
                    "vertex_count": 3,
                    "face_count": 1,
                    "positions_binary": {"path": str(positions_path), "count": 3, "components": 3, "type": "f64"},
                    "texture_coordinates_binary": {"path": str(uvs_path), "count": 3, "components": 2, "type": "f64"},
                    "normals_binary": {"path": str(normals_path), "count": 3, "components": 3, "type": "f64"},
                    "indices_binary": {"path": str(indices_path), "count": 3, "components": 1, "type": "i32"},
                    "source_vertex_indices_binary": {"path": str(source_vertices_path), "count": 3, "components": 1, "type": "i32"},
                    "source_face_indices_binary": {"path": str(source_faces_path), "count": 1, "components": 1, "type": "i32"},
                }
            ],
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="preview-session-0"),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=_native_job),
    ):
        report = mesh_native_core.build_native_preview_model_in_original_frame(
            parsed_mesh,
            normalization_center=(1.0, 2.0, 3.0),
            normalization_scale=2.0,
            source_indices=(7,),
        )

    assert report is not None
    assert report["mesh_count"] == 1
    assert report["meshes"][0]["source_submesh_index"] == 7
    assert "positions" not in report["meshes"][0]
    assert "indices" not in report["meshes"][0]
    assert Path(report["meshes"][0]["positions_binary"]["path"]).is_file()
    assert Path(report["meshes"][0]["indices_binary"]["path"]).is_file()
    assert Path(report["meshes"][0]["source_face_indices_binary"]["path"]).is_file()


def test_preview_model_in_original_frame_carries_native_binary_descriptors() -> None:
    parsed_mesh = SimpleNamespace(
        path="mesh.pac",
        format="pac",
        submeshes=[
            SimpleNamespace(
                material="Body",
                texture="body.dds",
                vertices=[(2.0, 4.0, 6.0), (4.0, 6.0, 8.0), (6.0, 8.0, 10.0)],
                faces=[(0, 1, 2)],
                uvs=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
                normals=[(0.0, 0.0, 1.0)] * 3,
            )
        ],
    )

    with tempfile.TemporaryDirectory(prefix="cdmw-preview-model-descriptor-") as temp_dir:
        positions_path = Path(temp_dir) / "positions.bin"
        uvs_path = Path(temp_dir) / "uvs.bin"
        normals_path = Path(temp_dir) / "normals.bin"
        indices_path = Path(temp_dir) / "indices.bin"
        source_vertices_path = Path(temp_dir) / "source_vertices.bin"
        source_faces_path = Path(temp_dir) / "source_faces.bin"
        _write_f64_values(positions_path, [2.0, 4.0, 6.0, 4.0, 6.0, 8.0, 6.0, 8.0, 10.0])
        _write_f64_values(uvs_path, [0.0, 0.0, 1.0, 0.0, 1.0, 1.0])
        _write_f64_values(normals_path, [0.0, 0.0, 1.0] * 3)
        _write_i32_values(indices_path, [0, 1, 2])
        _write_i32_values(source_vertices_path, [0, 1, 2])
        _write_i32_values(source_faces_path, [0])

        def _fake_native_preview_model(*args: object, **kwargs: object) -> dict[str, object]:
            return {
                "status": "ok",
                "operation": "preview_model",
                "mesh_count": 1,
                "vertex_count": 3,
                "face_count": 1,
                "meshes": [
                    {
                        "parsed_submesh_index": 0,
                        "source_submesh_index": 7,
                        "vertex_count": 3,
                        "face_count": 1,
                        "positions_binary": {"path": str(positions_path), "count": 3, "components": 3, "type": "f64"},
                        "texture_coordinates_binary": {"path": str(uvs_path), "count": 3, "components": 2, "type": "f64"},
                        "normals_binary": {"path": str(normals_path), "count": 3, "components": 3, "type": "f64"},
                        "indices_binary": {"path": str(indices_path), "count": 3, "components": 1, "type": "i32"},
                        "source_vertex_indices_binary": {"path": str(source_vertices_path), "count": 3, "components": 1, "type": "i32"},
                        "source_face_indices_binary": {"path": str(source_faces_path), "count": 1, "components": 1, "type": "i32"},
                    }
                ],
            }

        with patch("cdmw.modding.mesh_native_core.build_native_preview_model_in_original_frame", side_effect=_fake_native_preview_model):
            preview = preview_model_in_original_frame(
                parsed_mesh,
                normalization_center=(1.0, 2.0, 3.0),
                normalization_scale=2.0,
                source_indices=(7,),
            )

        assert preview.vertex_count == 3
        assert preview.face_count == 1
        assert preview.meshes[0].positions == []
        assert preview.meshes[0].indices == []
        assert preview.meshes[0].positions_binary["path"] == str(positions_path)
        assert preview.meshes[0].indices_binary["path"] == str(indices_path)


def test_native_preview_model_bridge_keeps_binary_sidecar_fallback() -> None:
    from cdmw.modding import mesh_native_core

    parsed_mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(
                vertices=[(2.0, 4.0, 6.0), (4.0, 6.0, 8.0), (6.0, 8.0, 10.0)],
                faces=[(0, 1, 2)],
                uvs=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
                normals=[(0.0, 0.0, 1.0)] * 3,
            )
        ]
    )

    def _native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "preview-model-json"
        assert payload["operation"] == "preview_model"  # type: ignore[index]
        submesh_payload = payload["submeshes"][0]  # type: ignore[index]
        assert "session_id" not in submesh_payload
        for key in ("vertices_binary", "faces_binary", "uvs_binary", "normals_binary"):
            assert key in submesh_payload
            assert Path(submesh_payload[key]["path"]).is_file()
        for key in ("vertices", "faces", "uvs", "normals"):
            assert key not in submesh_payload
        assert submesh_payload["vertices_binary"]["count"] == 3
        assert submesh_payload["faces_binary"]["count"] == 1
        assert timeout_seconds == 20.0
        return {
            "status": "ok",
            "operation": "preview_model",
            "mesh_count": 1,
            "vertex_count": 3,
            "face_count": 1,
            "meshes": [
                {
                    "parsed_submesh_index": 0,
                    "source_submesh_index": 7,
                    "positions": [[2.0, 4.0, 6.0], [4.0, 6.0, 8.0], [6.0, 8.0, 10.0]],
                    "texture_coordinates": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]],
                    "normals": [[0.0, 0.0, 1.0]] * 3,
                    "indices": [0, 1, 2],
                    "source_vertex_indices": [0, 1, 2],
                    "source_face_indices": [0],
                }
            ],
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value=None),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=_native_job),
    ):
        report = mesh_native_core.build_native_preview_model_in_original_frame(
            parsed_mesh,
            normalization_center=(1.0, 2.0, 3.0),
            normalization_scale=2.0,
            source_indices=(7,),
        )

    assert report is not None
    assert report["mesh_count"] == 1
    assert report["meshes"][0]["source_submesh_index"] == 7


def test_source_preview_geometry_key_serializes_stable_geometry_payload() -> None:
    key = source_preview_geometry_key(
        (SimpleNamespace(target_submesh_index=2, source_submesh_indices=("5", 6)),),
        (
            SimpleNamespace(
                source_submesh_index=5,
                enabled=True,
                offset_xyz=(1, 2, 3),
                rotate_xyz_degrees=(4, 5, 6),
                scale_xyz=(1.0, 1.5, 2.0),
                uniform_scale=0.75,
                material_role="emissive",
                emissive_color_rgb=(1, 2, 3),
            ),
        ),
        (SimpleNamespace(original_submesh_index=1, label="copy", keep_original_placement=True),),
        alignment_mode="grid_flat",
        scale_to_length=True,
        flip=False,
        rotate_xyz=(10, 20, 30),
        scale_xyz=(1, 2, 3),
        offset_xyz=(4, 5, 6),
        texture_uv_payload={"Body": {"u": 1}},
        mesh_edit_revision=7,
        source_geometry_revision=8,
        independent_output_source_indices={9, 3},
        preview_only_source_indices={4},
    )

    payload = json.loads(key)

    assert payload["mode"] == "grid_flat"
    assert payload["mappings"] == [[2, [5, 6]]]
    assert payload["adjustments"][0][0] == 5
    assert payload["copies"] == [[1, "copy", True]]
    assert payload["texture_uv"] == {"Body": {"u": 1}}
    assert payload["mesh_edit_revision"] == 7
    assert payload["source_geometry_revision"] == 8
    assert payload["independent_sources"] == [3, 9]
    assert payload["preview_only_sources"] == [4]
    assert "source_material_textures" not in payload
    assert "donor_material_plans" not in payload


def test_selected_part_preview_indices_uses_direct_map_or_source_indices() -> None:
    preview_model = SimpleNamespace(meshes=[object(), object(), object()])

    assert selected_part_preview_indices(
        preview_model,
        source_index=-1,
        highlighted_source_indices={0, 2},
        mapped_preview=False,
        current_mappings=(),
        direct_source_preview_index_map={0: 1, 2: 9},
        source_overlay_preview_index_map={},
        preview_target_mesh_indices=lambda *_args: (),
    ) == (1,)
    assert selected_part_preview_indices(
        preview_model,
        source_index=-1,
        highlighted_source_indices={0, 2},
        mapped_preview=False,
        current_mappings=(),
        direct_source_preview_index_map={},
        source_overlay_preview_index_map={},
        preview_target_mesh_indices=lambda *_args: (),
    ) == (0, 2)
    assert selected_part_preview_indices(
        preview_model,
        source_index=-1,
        highlighted_source_indices=set(),
        mapped_preview=False,
        current_mappings=(),
        direct_source_preview_index_map={},
        source_overlay_preview_index_map={},
        preview_target_mesh_indices=lambda *_args: (),
    ) is None


def test_selected_part_preview_indices_uses_overlay_then_mapping_targets() -> None:
    preview_model = SimpleNamespace(meshes=[object(), object(), object(), object()])
    mappings = (SimpleNamespace(target_submesh_name="Body", source_submesh_indices=(1,)),)

    assert selected_part_preview_indices(
        preview_model,
        source_index=-1,
        highlighted_source_indices={1, 3},
        mapped_preview=True,
        current_mappings=mappings,
        direct_source_preview_index_map={},
        source_overlay_preview_index_map={3: 2},
        preview_target_mesh_indices=lambda _model, _target, _fallback, _mapped, _mappings: (1,),
    ) == (1, 2)
