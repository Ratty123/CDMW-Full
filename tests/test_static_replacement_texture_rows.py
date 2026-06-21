from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cdmw.modding.static_mesh_replacer import StaticTextureSlotOverride
from cdmw.ui.archive_browser.static_replacement_virtual_texture_contract import (
    alignment_virtual_contract_preview_specs,
    alignment_virtual_contract_rows,
    alignment_virtual_sidecar_contract_state,
    alignment_virtual_texture_contract_defaults,
    copied_source_texture_preview_specs,
    copied_source_texture_slot_overrides,
    virtual_contract_sidecar_text_for_path,
)
from cdmw.ui.archive_browser.static_replacement_texture_rows import (
    TextureRowTableDisplay,
    material_routing_conflict_messages,
    resolve_dds_detail_preview_path,
    routing_source_material_labels,
    source_indices_for_target_contract,
    source_material_group_label,
    source_material_names_for_mapping,
    source_texture_reference_keys,
    source_texture_slot_count,
    selected_material_target_index,
    set_texture_row_assignment,
    source_slot_for_texture_row,
    sync_texture_row_assignment_state,
    target_material_name_for_index,
    target_texture_status_details,
    target_texture_status_text,
    texture_row_contract_status_color,
    texture_row_current_source_indices,
    texture_row_effective_source,
    texture_overrides_dirty_initial_state,
    texture_row_source_color,
    texture_row_source_summary,
    texture_row_table_role_color,
    texture_row_table_display,
    texture_set_for_source_index,
    texture_source_choices_for_row,
    texture_summary_label_html,
    texture_summary_metrics,
)


def test_source_slot_for_texture_row_prefers_compatible_path_slot() -> None:
    material_slot = SimpleNamespace(source_path=Path("material.dds"))
    texture_set = SimpleNamespace(
        slots={
            "material": material_slot,
            "material_mask": SimpleNamespace(source_path="not-a-path"),
        }
    )

    assert source_slot_for_texture_row(texture_set, {"slot_kind": "material_mask"}) is material_slot


def test_alignment_virtual_texture_contract_defaults_mutates_contract_once() -> None:
    contract: dict[str, object] = {"rows": ("row",)}

    returned = alignment_virtual_texture_contract_defaults(contract)

    assert returned is contract
    assert contract["rows"] == ("row",)
    assert contract["preview_specs"] == ()
    assert contract["patched_sidecar_texts"] == {}
    assert contract["sidecar_reports"] == ()


def test_alignment_virtual_contract_rows_routes_replacement_and_mutates_badges() -> None:
    rows = [
        {
            "target_name": "Body",
            "target_path": r"textures\body.dds",
            "slot_kind": "material",
            "parameter_name": "Base",
            "visualized": True,
        }
    ]

    result = alignment_virtual_contract_rows(
        [SimpleNamespace(target_submesh_name="Body", source_submesh_indices=(4,))],
        texture_override_rows=rows,
        texture_override_assignments={("textures/body.dds", "material", "Body"): "mods/body.dds"},
        copied_overrides=(),
        texture_rows_by_target={},
        texture_row_assigned=lambda row: bool(row.get("assigned")),
        texture_row_current_source_indices=lambda row: (),
        virtual_contract_prune_removed_targets_enabled=lambda: False,
        virtual_contract_prune_unmapped_enabled=lambda: False,
        texture_row_effective_source=lambda row: "",
        texture_row_is_shared=lambda row: False,
        texture_role_label_for_slot=lambda slot: slot.title(),
        texture_row_override_key=lambda row: (
            str(row.get("target_path", "")).replace("\\", "/").lower(),
            str(row.get("slot_kind", "")),
            str(row.get("target_name", "")),
        ),
        texture_override_row_sort_key=lambda row, *_args, **_kwargs: str(row.get("target_name", "")),
        texture_slot_contract_key=lambda slot: slot or "material",
    )

    assert result[0]["sidecar_action"] == "replaced"
    assert result[0]["selected_source"] == "mods/body.dds"
    assert result[0]["preview_source"] == "mods/body.dds"
    assert result[0]["source_indices"] == (4,)
    assert rows[0]["_contract_action"] == "replaced"
    assert rows[0]["_contract_selected_source"] == "mods/body.dds"


def test_alignment_virtual_contract_rows_routes_copy_prune_and_review() -> None:
    rows = [
        {"target_name": "CopyTarget", "target_path": "copy.dds", "slot_kind": "base", "part_display": "Copy"},
        {"target_name": "Removed", "target_path": "removed.dds", "slot_kind": "material"},
        {"target_name": "Shared", "target_path": "shared.dds", "slot_kind": "support", "advanced": True},
    ]

    result = alignment_virtual_contract_rows(
        [SimpleNamespace(target_submesh_name="CopyTarget", source_submesh_indices=(2,))],
        texture_override_rows=rows,
        texture_override_assignments={},
        copied_overrides=(
            StaticTextureSlotOverride(
                target_texture_path="copy.dds",
                source_path="copied/copy.dds",
                slot_kind="base",
                target_material_name="CopyTarget",
            ),
        ),
        texture_rows_by_target={},
        texture_row_assigned=lambda row: False,
        texture_row_current_source_indices=lambda row: (7,) if row.get("target_name") == "Shared" else (),
        virtual_contract_prune_removed_targets_enabled=lambda: True,
        virtual_contract_prune_unmapped_enabled=lambda: False,
        texture_row_effective_source=lambda row: "",
        texture_row_is_shared=lambda row: bool(row.get("shared")),
        texture_role_label_for_slot=lambda slot: f"role:{slot}",
        texture_row_override_key=lambda row: ("", "", ""),
        texture_override_row_sort_key=lambda row, *_args, **_kwargs: ("CopyTarget", "Removed", "Shared").index(
            str(row.get("target_name", ""))
        ),
        texture_slot_contract_key=lambda slot: {"material": "material", "base": "base"}.get(slot, slot),
    )

    assert [row["sidecar_action"] for row in result] == ["replaced", "will_prune", "review"]
    assert result[0]["selected_source"] == "copied/copy.dds"
    assert result[1]["reason"] == "Removed target"
    assert result[2]["role_label"] == "role:support"
    assert rows[1]["_contract_action"] == "will_prune"
    assert rows[2]["_contract_action"] == "review"


def test_alignment_virtual_contract_preview_specs_only_visualized_replacements() -> None:
    assert alignment_virtual_contract_preview_specs(
        (
            {
                "sidecar_action": "replaced",
                "preview_source": "mods/body.dds",
                "visualized": True,
                "source_indices": (1, "2"),
                "target_name": "Body",
                "slot_kind": "base",
            },
            {"sidecar_action": "replaced", "preview_source": "mods/hidden.dds", "visualized": False},
            {"sidecar_action": "kept", "preview_source": "mods/kept.dds", "visualized": True},
        ),
        alignment_contract_preview_path=lambda source: source.replace("\\", "/").upper(),
    ) == [
        ("Body", "base", "MODS/BODY.DDS", "body.dds", (1, 2), "mods/body.dds"),
    ]


def test_alignment_virtual_sidecar_contract_state_builds_patch_plans() -> None:
    patch_calls: list[tuple[str, object]] = []

    def _patcher(source_text: str, plan: object) -> tuple[str, object]:
        patch_calls.append((source_text, plan))
        return f"patched:{getattr(plan, 'sidecar_path')}", {"sidecar": getattr(plan, "sidecar_path")}

    state = alignment_virtual_sidecar_contract_state(
        (
            {
                "target_name": "Body",
                "parameter_name": "Base",
                "sidecar_path": "body.sidecar",
                "sidecar_action": "replaced",
                "original_dds": "body_old.dds",
                "final_output_dds": "body_new.dds",
            },
            {
                "target_name": "Boot",
                "parameter_name": "Base",
                "sidecar_path": "body.sidecar",
                "sidecar_action": "will_prune",
                "original_dds": "boot.dds",
                "final_output_dds": "boot.dds",
            },
            {
                "target_name": "Empty",
                "parameter_name": "Base",
                "sidecar_path": "missing.sidecar",
                "sidecar_action": "kept",
            },
        ),
        (("Body", "base"),),
        sidecar_text_for_path=lambda key: "" if key == "missing.sidecar" else f"source:{key}",
        prune_removed_targets_enabled=True,
        prune_unmapped_enabled=False,
        patch_sidecar_text=_patcher,
    )

    assert state["preview_specs"] == (("Body", "base"),)
    assert state["patched_sidecar_texts"] == {"body.sidecar": "patched:body.sidecar"}
    assert state["sidecar_reports"] == ({"sidecar": "body.sidecar"},)
    assert len(patch_calls) == 1
    source_text, plan = patch_calls[0]
    assert source_text == "source:body.sidecar"
    assert getattr(plan, "texture_path_replacements") == {"body_old.dds": "body_new.dds"}
    assert getattr(plan, "texture_parameter_keep_rules") == [("Body", "Base")]
    assert getattr(plan, "prune_material_names") == ["Boot"]
    assert getattr(plan, "prune_unmapped_texture_parameters") is True


def test_source_texture_reference_keys_normalizes_path_name_and_stem() -> None:
    keys = source_texture_reference_keys(r"Textures\Body\Base.dds")

    assert "textures/body/base.dds" in keys
    assert "base.dds" in keys
    assert "base" in keys
    assert source_texture_reference_keys("") == set()


def test_texture_set_for_source_index_prefers_material_key_then_texture_slot_match() -> None:
    direct_set = SimpleNamespace(material_name="skin", slots={})
    base_set = SimpleNamespace(
        material_name="body",
        slots={"base": SimpleNamespace(source_path=Path("textures/body/base.dds"))},
    )
    normal_set = SimpleNamespace(
        material_name="normal",
        slots={"normal": SimpleNamespace(source_path=Path("textures/body/base.dds"))},
    )
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="", material="Skin", texture="unused.dds"),
            SimpleNamespace(name="", material="", texture=r"textures\body\base.dds"),
        ]
    )

    texture_sets = {"skin": direct_set, "body": base_set, "normal": normal_set}

    assert texture_set_for_source_index(0, mesh, texture_sets) is direct_set
    assert texture_set_for_source_index(1, mesh, texture_sets) is base_set
    assert texture_set_for_source_index(5, mesh, texture_sets) is None
    assert texture_set_for_source_index(0, None, texture_sets) is None


def test_source_material_group_label_uses_explicit_texture_key_and_texture_set_name() -> None:
    texture_set = SimpleNamespace(material_name="BodyMaterial", slots={})
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="", material="Skin", texture="", cdmw_source_texture_set_key="explicit"),
            SimpleNamespace(name="", material="Body", texture=""),
        ]
    )

    assert source_material_group_label(0, mesh, {"body": texture_set}, {}) == "explicit"
    assert source_material_group_label(1, mesh, {"body": texture_set}, {}) == "BodyMaterial"


def test_source_material_group_label_marks_duplicate_adjusted_sources_as_unique_group() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="", material="Skin", texture=""),
            SimpleNamespace(name="", material="Skin", texture=""),
        ]
    )
    adjustments = {1: SimpleNamespace(material_role="emissive", emissive_color_rgb=())}

    assert source_material_group_label(1, mesh, {}, adjustments) == "__source_part_1_skin"
    assert source_material_group_label(5, mesh, {}, {}) == "source 5"


def test_routing_source_material_labels_preserves_order_and_dedupes_case_insensitive() -> None:
    texture_set = SimpleNamespace(material_name="Skin", slots={})
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="", material="skin", texture=""),
            SimpleNamespace(name="HairName", material="", texture=""),
            SimpleNamespace(name="", material="Skin", texture=""),
        ]
    )

    assert routing_source_material_labels((0, 1, 2, 9), mesh, {"skin": texture_set}) == ("Skin", "HairName")
    assert routing_source_material_labels((0,), None, {"skin": texture_set}) == ()


def test_source_material_names_for_mapping_uses_texture_sets_and_dedupes() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="", material="Skin", texture=""),
            SimpleNamespace(name="", material="skin", texture=""),
            SimpleNamespace(name="", material="Cloth", texture=""),
        ]
    )
    texture_sets = {
        "skin": SimpleNamespace(material_name="SkinMat", slots={}),
        "cloth": SimpleNamespace(material_name="ClothMat", slots={}),
    }
    mapping = SimpleNamespace(source_submesh_indices=(0, "1", 2, -1, "bad", 9))

    assert source_material_names_for_mapping(mapping, mesh, texture_sets) == ("SkinMat", "ClothMat")
    assert source_material_names_for_mapping(mapping, None, texture_sets) == ()


def test_material_routing_conflict_messages_reports_multiple_materials() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="", material="Skin", texture=""),
            SimpleNamespace(name="", material="Cloth", texture=""),
        ]
    )
    texture_sets = {
        "skin": SimpleNamespace(material_name="SkinMat", slots={}),
        "cloth": SimpleNamespace(material_name="ClothMat", slots={}),
    }

    messages = material_routing_conflict_messages(
        (SimpleNamespace(target_submesh_name="Body", source_submesh_indices=(0, 1)),),
        mesh,
        texture_sets,
    )

    assert len(messages) == 1
    assert "Body receives multiple replacement materials (SkinMat, ClothMat)." in messages[0]
    assert material_routing_conflict_messages(
        (SimpleNamespace(target_submesh_name="Body", source_submesh_indices=(0,)),),
        mesh,
        texture_sets,
    ) == ()


def test_target_material_name_for_index_uses_material_name_and_bounds() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(material="BodyMat", name="Body"),
            SimpleNamespace(material="", name="Cape"),
            SimpleNamespace(material="", name=""),
        ]
    )

    assert target_material_name_for_index(0, mesh) == "BodyMat"
    assert target_material_name_for_index(1, mesh) == "Cape"
    assert target_material_name_for_index(2, mesh) == "target 2"
    assert target_material_name_for_index(-1, mesh) == ""
    assert target_material_name_for_index(9, mesh) == ""
    assert target_material_name_for_index(0, None) == ""


def test_selected_material_target_index_prefers_selected_target_then_combo_fallback() -> None:
    assert selected_material_target_index(lambda: 3, lambda: "7") == 3
    assert selected_material_target_index(lambda: -1, lambda: "7") == 7
    assert selected_material_target_index(lambda: -1, lambda: None) == -1
    assert selected_material_target_index(lambda: -1, lambda: "bad") == -1


def test_resolve_dds_detail_preview_path_handles_empty_missing_and_images(tmp_path: Path) -> None:
    image_path = tmp_path / "preview.png"
    image_path.write_bytes(b"png")

    assert resolve_dds_detail_preview_path(
        "",
        texconv_path=None,
        parse_dds_file=lambda _path: object(),
        ensure_dds_display_preview=lambda *_args, **_kwargs: image_path,
    ) == (None, "No local preview source is available for this row.")
    missing_path, missing_status = resolve_dds_detail_preview_path(
        tmp_path / "missing.dds",
        texconv_path=None,
        parse_dds_file=lambda _path: object(),
        ensure_dds_display_preview=lambda *_args, **_kwargs: image_path,
    )
    assert missing_path is None
    assert "Preview source is not a local file:" in missing_status
    assert resolve_dds_detail_preview_path(
        image_path,
        texconv_path=None,
        parse_dds_file=lambda _path: object(),
        ensure_dds_display_preview=lambda *_args, **_kwargs: image_path,
    ) == (image_path, "Visible thumbnail from the source image.")


def test_resolve_dds_detail_preview_path_decodes_dds_with_texconv_and_slot(tmp_path: Path) -> None:
    dds_path = tmp_path / "body.dds"
    dds_path.write_bytes(b"DDS ")
    texconv_path = tmp_path / "texconv.exe"
    texconv_path.write_bytes(b"tool")
    preview_path = tmp_path / "body.png"
    calls: list[tuple[object, Path, object, int, str]] = []

    def ensure_preview(texconv: object, candidate: Path, **kwargs: object) -> Path:
        calls.append(
            (
                texconv,
                candidate,
                kwargs.get("dds_info"),
                int(kwargs.get("max_dimension", 0)),
                str(kwargs.get("slot_kind", "")),
            )
        )
        return preview_path

    assert resolve_dds_detail_preview_path(
        dds_path,
        " Normal ",
        texconv_path=texconv_path,
        parse_dds_file=lambda path: {"path": path.name},
        ensure_dds_display_preview=ensure_preview,
    ) == (preview_path, "Visible thumbnail from decoded DDS preview.")
    assert calls == [(texconv_path, dds_path, {"path": "body.dds"}, 512, "normal")]


def test_resolve_dds_detail_preview_path_reports_decode_failures(tmp_path: Path) -> None:
    dds_path = tmp_path / "body.dds"
    dds_path.write_bytes(b"DDS ")

    preview_path, status = resolve_dds_detail_preview_path(
        dds_path,
        texconv_path=None,
        parse_dds_file=lambda _path: object(),
        ensure_dds_display_preview=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("decode failed")),
    )

    assert preview_path is None
    assert status == "DDS is not previewable here: decode failed"


def test_copied_source_texture_slot_overrides_are_target_scoped_and_skip_disabled() -> None:
    mappings = (
        SimpleNamespace(target_submesh_index=0, target_submesh_name="Body", source_submesh_indices=(1, 2)),
        SimpleNamespace(target_submesh_index=1, target_submesh_name="Cape", source_submesh_indices=(3,)),
    )
    target_rows = {
        0: ({"slot_kind": "material", "texture_path": "target/body_mask.dds"},),
        1: ({"slot_kind": "base", "texture_path": "target/cape_base.dds"},),
    }
    copied_rows = {
        1: ({"slot_kind": "base", "source_path": "source/body_base.dds"},),
        2: ({"slot_kind": "base", "source_path": "source/disabled.dds"},),
        3: ({"slot_kind": "base", "source_path": "source/cape_base.dds"},),
    }

    overrides = copied_source_texture_slot_overrides(
        mappings,
        original_part_texture_intent_rows=lambda index: target_rows.get(index, ()),
        copied_original_texture_intents_by_source=copied_rows,
        copied_original_texture_disabled_sources={2},
        source_display_name=lambda index: f"source {index}",
        texture_slot_contract_key=lambda value: value.strip().lower() or "material",
    )

    assert overrides == (
        StaticTextureSlotOverride(
            target_texture_path="target/body_mask.dds",
            source_path="source/body_base.dds",
            slot_kind="material",
            target_material_name="Body",
            enabled=True,
            source_material_name="source 1",
        ),
        StaticTextureSlotOverride(
            target_texture_path="target/cape_base.dds",
            source_path="source/cape_base.dds",
            slot_kind="base",
            target_material_name="Cape",
            enabled=True,
            source_material_name="source 3",
        ),
    )


def test_copied_source_texture_slot_overrides_respects_occupied_keys() -> None:
    occupied = {("target/body.dds", "base")}

    overrides = copied_source_texture_slot_overrides(
        (SimpleNamespace(target_submesh_index=0, target_submesh_name="Body", source_submesh_indices=(1,)),),
        original_part_texture_intent_rows=lambda _index: ({"slot_kind": "base", "texture_path": "target/body.dds"},),
        copied_original_texture_intents_by_source={1: ({"slot_kind": "base", "source_path": "source/body.dds"},)},
        copied_original_texture_disabled_sources=(),
        source_display_name=lambda index: f"source {index}",
        texture_slot_contract_key=lambda value: value.strip().lower() or "material",
        occupied_keys=occupied,
    )

    assert overrides == ()
    assert occupied == {("target/body.dds", "base")}


def test_copied_source_texture_preview_specs_follow_matching_target_sources() -> None:
    mappings = (
        SimpleNamespace(target_submesh_name="Body", source_submesh_indices=("1", "2")),
        SimpleNamespace(target_submesh_name="Cape", source_submesh_indices=(3,)),
    )
    overrides = (
        StaticTextureSlotOverride(
            target_texture_path="target/body.dds",
            source_path="C:/source/body.dds",
            slot_kind="base",
            target_material_name="Body",
        ),
    )

    assert copied_source_texture_preview_specs(
        mappings,
        overrides,
        source_preview_path=lambda path: f"preview:{path}",
    ) == (("Body", "base", "preview:C:/source/body.dds", "body.dds", (1, 2), "C:/source/body.dds"),)


def test_virtual_contract_sidecar_text_for_path_prefers_normalized_then_basename_and_fallback() -> None:
    assert (
        virtual_contract_sidecar_text_for_path(
            "textures/body.dds",
            sidecar_texts_by_normalized_path={"norm:textures/body.dds": ("normalized",)},
            sidecar_texts_by_basename={"body.dds": ("basename",)},
            sidecar_text_values=("fallback",),
            normalize_texture_reference=lambda value: f"norm:{value}",
        )
        == "normalized"
    )
    assert (
        virtual_contract_sidecar_text_for_path(
            "textures/body.dds",
            sidecar_texts_by_normalized_path={},
            sidecar_texts_by_basename={"body.dds": ("basename",)},
            sidecar_text_values=("fallback",),
            normalize_texture_reference=lambda value: f"norm:{value}",
        )
        == "basename"
    )
    assert (
        virtual_contract_sidecar_text_for_path(
            "missing.dds",
            sidecar_texts_by_normalized_path={"other": ("first map value",)},
            sidecar_texts_by_basename={},
            sidecar_text_values=("fallback",),
            normalize_texture_reference=lambda value: f"norm:{value}",
        )
        == "first map value"
    )
    assert (
        virtual_contract_sidecar_text_for_path(
            "missing.dds",
            sidecar_texts_by_normalized_path={},
            sidecar_texts_by_basename={},
            sidecar_text_values=("fallback",),
            normalize_texture_reference=lambda value: f"norm:{value}",
        )
        == "fallback"
    )


def test_source_texture_slot_count_counts_slots_for_valid_source_materials() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="", material="Skin"),
            SimpleNamespace(name="Hair", material=""),
        ]
    )
    texture_sets = {
        "skin": SimpleNamespace(slots={"base": object(), "normal": object()}),
        "hair": SimpleNamespace(slots={"base": object()}),
    }

    assert source_texture_slot_count((0, "1", "bad", 9), mesh, texture_sets) == 3
    assert source_texture_slot_count((0,), None, texture_sets) == 0
    assert source_texture_slot_count((0,), mesh, {}) == 0


def test_target_texture_status_details_collects_original_and_routed_dds_rows() -> None:
    bindings = [
        SimpleNamespace(part_name="Body", texture_path="orig.dds", parameter_name="Base"),
        SimpleNamespace(part_name="Body", texture_path="skip.png", parameter_name="Skip"),
        SimpleNamespace(part_name="Other", texture_path="other.dds", parameter_name="Other"),
    ]
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(name="", material="Skin")])
    texture_sets = {"skin": SimpleNamespace(slots={"base": SimpleNamespace(source_path="src.dds")})}

    text = target_texture_status_details("Body", bindings, (0,), mesh, texture_sets)

    assert "Base: orig.dds" in text
    assert "Skin / base: src.dds" in text
    assert "Other: other.dds" not in text
    assert "skip.png" not in text


def test_target_texture_status_text_counts_original_and_source_slots() -> None:
    bindings = [
        SimpleNamespace(part_name="Body", texture_path="orig.dds"),
        SimpleNamespace(submesh_name="Body", reference_name="normal.dds"),
        SimpleNamespace(material_name="Body", texture_path="skip.png"),
    ]

    assert target_texture_status_text("", bindings, 0) == "No target"
    assert target_texture_status_text("Body", bindings, 3) == "Orig 2 | Src 3"
    assert target_texture_status_text("Body", [], 0) == "Sidecar unknown"
    assert target_texture_status_text("Missing", bindings, 0) == "Orig 0 | Src 0"


def test_source_indices_for_target_contract_uses_mapping_then_material_fallback() -> None:
    mappings = (
        SimpleNamespace(
            target_submesh_index=4,
            target_submesh_name="Body",
            source_submesh_indices=("2", "bad", -1, 7),
        ),
    )
    target_indices = {"body": 4, "body_mat": -1}

    def target_index_for_name(name: str) -> int:
        return target_indices.get(name.lower(), -1)

    assert source_indices_for_target_contract(
        "Body",
        "Body_Mat",
        target_index_for_name=target_index_for_name,
        mappings=mappings,
        source_indices_for_material_name=lambda _name: (9,),
    ) == (2, 7)

    assert source_indices_for_target_contract(
        "Cape",
        "Cape_Mat",
        target_index_for_name=target_index_for_name,
        mappings=mappings,
        source_indices_for_material_name=lambda name: (11,) if name == "Cape_Mat" else (),
    ) == (11,)


def test_texture_row_current_source_indices_uses_target_lookup_then_row_fallback() -> None:
    row = {"target_name": "helmet", "source_indices": ("2", "bad", 2, "3")}

    assert texture_row_current_source_indices(row, source_indices_for_target_name=lambda _name: (7,)) == (7,)
    assert texture_row_current_source_indices(row, source_indices_for_target_name=lambda _name: ()) == (2, 3)


def test_texture_row_summary_and_assignment_state_follow_effective_source() -> None:
    row = {
        "target_name": "helmet",
        "parameter_name": "base",
        "target_path": "textures/base.dds",
        "checked": True,
        "source_path": "detected.dds",
    }
    assignments = {("helmet", "base", "textures/base.dds"): "manual.dds"}

    assert texture_row_effective_source(row, assignments) == "manual.dds"
    assert sync_texture_row_assignment_state(row, assignments)["source_path"] == "manual.dds"
    assert texture_row_source_summary((1, 2, 3, 4), source_display_name=lambda index: f"src {index}") == "src 1, src 2, src 3, +1 more"


def test_set_texture_row_assignment_updates_assignment_map_and_dirty_flag() -> None:
    row = {"target_name": "helmet", "parameter_name": "base", "target_path": "textures/base.dds"}
    assignments: dict[tuple[str, str, str], str] = {}
    dirty = {"dirty": False}

    set_texture_row_assignment(row, assignments, dirty, source_path=" manual.dds ", checked=True)

    assert assignments == {("helmet", "base", "textures/base.dds"): "manual.dds"}
    assert row["source_path"] == "manual.dds"
    assert row["checked"] is True
    assert dirty["dirty"] is True


def test_texture_overrides_dirty_initial_state_preserves_dirty_flag() -> None:
    assert texture_overrides_dirty_initial_state() == {"dirty": True}


def test_texture_source_choices_dedupe_assigned_suggested_and_mapping_files() -> None:
    choices = texture_source_choices_for_row(
        {"source_path": "assigned.dds", "checked": True, "suggested_source": "suggested.dds"},
        [Path("suggested.dds"), Path("extra.dds")],
        effective_source=lambda row: str(row.get("source_path", "")),
        source_key=lambda value: Path(value).name.lower(),
    )

    assert choices == [
        ("Keep original", ""),
        ("Assigned: assigned.dds", "assigned.dds"),
        ("Use suggested: suggested.dds", "suggested.dds"),
        ("extra.dds", "extra.dds"),
    ]


def test_texture_summary_metrics_and_html_are_stable() -> None:
    rows = [
        {"advanced": False, "assigned": True},
        {"advanced": True, "assigned": False},
        {"advanced": True, "assigned": True},
    ]

    visible, assigned, advanced_hidden, total = texture_summary_metrics(
        rows,
        visible_count=None,
        visible_predicate=lambda row: not bool(row.get("advanced")),
        assigned_predicate=lambda row: bool(row.get("assigned")),
        show_advanced=False,
    )

    assert (visible, assigned, advanced_hidden, total) == (1, 2, 2, 3)
    html = texture_summary_label_html(
        visible_count=visible,
        assigned_count=assigned,
        total_count=total,
        advanced_hidden=advanced_hidden,
    )
    assert "Visible rows" in html
    assert "2/3" in html


def test_texture_row_table_colors_follow_contract_and_assignment_state() -> None:
    assert texture_row_contract_status_color("will_prune", "#000000") == "#fb923c"
    assert texture_row_contract_status_color("kept", "#000000") == "#8b949e"
    assert texture_row_contract_status_color("replaced", "#000000") == "#3fb950"
    assert texture_row_contract_status_color("review", "#000000") == "#d29922"
    assert texture_row_contract_status_color("", "#123456") == "#123456"

    assert texture_row_table_role_color({"slot_kind": "normal"}) == "#79c0ff"
    assert texture_row_table_role_color({"slot_kind": "unknown"}) == "#c9d1d9"
    assert texture_row_source_color({}, contract_action="replaced", assigned=False) == "#7ee787"
    assert texture_row_source_color({}, contract_action="", assigned=True) == "#7ee787"
    assert texture_row_source_color({"suggested_source": "suggested.dds"}, contract_action="", assigned=False) == "#f2cc60"
    assert texture_row_source_color({}, contract_action="", assigned=False) == "#8b949e"


def test_texture_row_table_display_collects_values_tooltips_and_colors() -> None:
    status = SimpleNamespace(label="Ready", detail="ready detail")
    table_row = SimpleNamespace(
        part_label="Body",
        part_material="Body / target",
        full_part_material="Full body material",
        role="Base / Color",
        original_slot="_base: body.dds",
        override_source="Suggested: source.dds",
        controls="control text",
        target_dds="character/texture/body.dds",
        status=status,
    )
    row = {
        "slot_kind": "base",
        "_contract_action": "replaced",
        "_contract_reason": "Manual target-slot override",
        "_contract_selected_source": "C:/mods/source.dds",
    }

    display = texture_row_table_display(
        row,
        table_row,
        source_summary="Source body",
        source_summary_tooltip="Source body full",
        effective_source="manual.dds",
        assigned=True,
        status_color_for_label=lambda _label: "#000000",
        dark_foreground_statuses=("Replaced",),
    )

    assert isinstance(display, TextureRowTableDisplay)
    assert display.values == (
        "Body",
        "Source body",
        "Base / Color",
        "_base: body.dds",
        "source.dds",
        "Replaced",
        "Manual target-slot override",
    )
    assert display.tooltips[0] == "Full body material"
    assert display.tooltips[1] == "Source body full"
    assert display.tooltips[4] == "C:/mods/source.dds"
    assert display.role_color == "#7ee787"
    assert display.source_color == "#7ee787"
    assert display.status_color == "#3fb950"
    assert display.status_foreground == "#0d1117"
