"""What an import resolved per slot, and the log that now reads it rather than retelling it.

ME-MAT-004's complaint is that imported material resolution had no stable,
inspectable form owned by the import transaction. It had one form: a run of log
lines assembled at the end of `append_texture_replacement_report`, truncated at
sixteen rows, with no status and no counts. These tests pin the structure and
pin that the log is now rendered from it, because a summary that retells the
same rows in its own words is exactly how the two come to disagree.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.imported_material_manifest import (
    ImportedMaterialManifest,
    MaterialSlotStatus,
    build_imported_material_manifest,
)


def _mapping(
    *,
    slot_kind: str = "base",
    source_path: str = "C:/src/blade.png",
    output_texture_path: str = "character/texture/blade_base.dds",
    target_material_name: str = "Blade",
    source_material_name: str = "blade_mat",
    normal_space: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        target_material_name=target_material_name,
        target_texture_path=output_texture_path,
        slot_kind=slot_kind,
        source_material_name=source_material_name,
        source_path=Path(source_path),
        output_texture_path=output_texture_path,
        normal_space=normal_space,
    )


def _report(*mappings, warnings=(), errors=(), generated=()) -> SimpleNamespace:
    return SimpleNamespace(
        slot_mappings=list(mappings),
        warnings=list(warnings),
        errors=list(errors),
        generated_payloads=[SimpleNamespace(target_path=path) for path in generated],
    )


def test_an_empty_report_is_an_empty_manifest() -> None:
    manifest = build_imported_material_manifest(_report())

    assert manifest.slots == ()
    assert manifest.summary_lines() == ()
    assert manifest.as_payload()["schema"] == "cdmw_imported_material_manifest_v1"


def test_a_slot_the_package_writes_is_generated() -> None:
    manifest = build_imported_material_manifest(
        _report(_mapping()), packaged_target_paths=("character/texture/blade_base.dds",)
    )

    slot = manifest.slots[0]
    assert slot.status is MaterialSlotStatus.GENERATED
    assert slot.resolved
    assert slot.target_path == "character/texture/blade_base.dds"
    assert slot.source_material == "blade_mat"
    assert slot.semantic == "base"


def test_packaged_paths_match_regardless_of_separator_or_case() -> None:
    manifest = build_imported_material_manifest(
        _report(_mapping()),
        packaged_target_paths=("Character\\Texture\\Blade_Base.DDS",),
    )

    assert manifest.slots[0].status is MaterialSlotStatus.GENERATED


def test_a_slot_with_a_source_but_no_packaged_payload_is_copied() -> None:
    manifest = build_imported_material_manifest(_report(_mapping()))

    assert manifest.slots[0].status is MaterialSlotStatus.COPIED
    assert manifest.slots[0].resolved


def test_a_slot_routed_nowhere_is_missing() -> None:
    manifest = build_imported_material_manifest(
        _report(_mapping(output_texture_path=""))
    )

    assert manifest.slots[0].status is MaterialSlotStatus.MISSING
    assert not manifest.slots[0].resolved
    assert manifest.missing_slots() == manifest.slots


def test_a_missing_base_slot_is_a_missing_required_slot() -> None:
    manifest = build_imported_material_manifest(
        _report(
            _mapping(slot_kind="base", output_texture_path=""),
            _mapping(slot_kind="normal", output_texture_path=""),
        )
    )

    assert len(manifest.missing_slots()) == 2
    required = manifest.missing_required_slots()
    assert len(required) == 1
    assert required[0].semantic == "base"


def test_conversion_names_the_format_change_and_the_normal_space() -> None:
    converted = build_imported_material_manifest(_report(_mapping())).slots[0]
    assert converted.conversion == "png->dds"

    unchanged = build_imported_material_manifest(
        _report(_mapping(source_path="C:/src/blade.dds"))
    ).slots[0]
    assert unchanged.conversion == "none"

    flipped = build_imported_material_manifest(
        _report(_mapping(slot_kind="normal", normal_space="opengl"))
    ).slots[0]
    assert flipped.conversion == "png->dds normal_space=opengl"


def test_counts_are_reported_per_semantic() -> None:
    manifest = build_imported_material_manifest(
        _report(
            _mapping(slot_kind="base"),
            _mapping(slot_kind="base", output_texture_path="b.dds"),
            _mapping(slot_kind="normal", output_texture_path="n.dds"),
        )
    )

    assert manifest.counts_by_semantic() == {"base": 2, "normal": 1}


def test_summary_lines_report_counts_and_what_is_missing() -> None:
    manifest = build_imported_material_manifest(
        _report(
            _mapping(slot_kind="base"),
            _mapping(slot_kind="normal", output_texture_path=""),
        )
    )

    lines = manifest.summary_lines()
    assert "Imported material slots resolved: 2 (base: 1, normal: 1)" in lines[0]
    assert any("no packaged file: 1" in line for line in lines)
    # The normal map is optional, so nothing is reported as required-missing.
    assert not any("Missing required" in line for line in lines)


def test_warnings_and_errors_are_carried_rather_than_re_derived() -> None:
    manifest = build_imported_material_manifest(
        _report(_mapping(), warnings=["a warning"], errors=["an error"])
    )

    assert manifest.warnings == ("a warning",)
    assert manifest.errors == ("an error",)
    payload = manifest.as_payload()
    assert payload["warnings"] == ["a warning"]
    assert payload["errors"] == ["an error"]


def test_an_unnamed_semantic_does_not_vanish_from_the_counts() -> None:
    manifest = build_imported_material_manifest(_report(_mapping(slot_kind="")))

    assert manifest.counts_by_semantic() == {"unknown": 1}


def test_the_default_manifest_is_empty_rather_than_absent() -> None:
    assert ImportedMaterialManifest().summary_lines() == ()
    assert ImportedMaterialManifest().as_payload()["missing"] == 0


@pytest.mark.parametrize("required", ["base", "color", "basecolor", "base_color", "diffuse"])
def test_every_visible_colour_name_counts_as_required(required: str) -> None:
    manifest = build_imported_material_manifest(
        _report(_mapping(slot_kind=required, output_texture_path=""))
    )

    assert manifest.missing_required_slots() == manifest.slots


def test_the_build_log_is_rendered_from_the_manifest() -> None:
    """The import's summary reads the manifest instead of retelling its rows."""

    from cdmw.core.archive_mesh_import_materials import append_texture_replacement_report

    state = SimpleNamespace(summary_lines=[], material_authority_settings={})
    report = _report(
        _mapping(slot_kind="base"),
        _mapping(slot_kind="normal", output_texture_path="character/texture/blade_n.dds"),
        generated=("character/texture/blade_base.dds",),
    )

    append_texture_replacement_report(state, report)

    assert state.imported_material_manifest.slots
    joined = "\n".join(state.summary_lines)
    assert "Imported material slots resolved: 2 (base: 1, normal: 1)" in joined
    # Status and conversion reach the log, which they never did before.
    assert "[generated; png->dds]" in joined
    assert "[copied; png->dds]" in joined
