"""The import's account and the package's, compared instead of assumed to match.

MESH-007's finish is one manifest rather than three. That cannot be done from a
desk: the export side resolves against the archive and the import side does not,
so the two can legitimately differ and nobody has measured by how much. What is
testable now is the comparison itself, so a real build produces a list of
differences rather than an argument about whether any exist.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.imported_material_manifest import (
    ImportedMaterialManifest,
    ImportedMaterialSlot,
    MaterialSlotStatus,
)
from cdmw.domain.mesh.material_manifest_agreement import (
    compare_material_manifests,
    manifest_agreement_warnings,
)


def _slot(
    target_path: str = "character/texture/blade_base.dds",
    status: MaterialSlotStatus = MaterialSlotStatus.GENERATED,
) -> ImportedMaterialSlot:
    return ImportedMaterialSlot(
        target_material="Blade",
        target_path=target_path,
        semantic="base",
        source_material="blade_mat",
        source_path="C:/src/blade.png",
        conversion="png->dds",
        status=status,
    )


def _manifest(*slots: ImportedMaterialSlot) -> ImportedMaterialManifest:
    return ImportedMaterialManifest(slots=slots)


def _row(texture_path: str, status: str = "ready") -> SimpleNamespace:
    return SimpleNamespace(texture_path=texture_path, status=status)


def test_nothing_to_compare_is_not_a_disagreement() -> None:
    assert compare_material_manifests(None, ()) == ()
    assert compare_material_manifests(ImportedMaterialManifest(), (_row("a.dds"),)) == ()
    assert manifest_agreement_warnings(None, ()) == ()


def test_two_accounts_that_agree_report_nothing() -> None:
    manifest = _manifest(_slot())
    rows = (_row("character/texture/blade_base.dds"),)

    assert compare_material_manifests(manifest, rows) == ()
    assert manifest_agreement_warnings(manifest, rows) == ()


def test_paths_match_regardless_of_separator_or_case() -> None:
    manifest = _manifest(_slot())
    rows = (_row("Character\\Texture\\Blade_Base.DDS"),)

    assert compare_material_manifests(manifest, rows) == ()


def test_a_written_path_the_package_never_binds_is_reported() -> None:
    manifest = _manifest(_slot())

    disagreements = compare_material_manifests(manifest, (_row("something/else.dds"),))

    assert len(disagreements) == 1
    assert disagreements[0].package_side == "absent"
    assert "no binding for it" in disagreements[0].reason


def test_a_slot_the_import_never_resolved_is_not_chased() -> None:
    # The import already knows it produced nothing here; the package having no
    # binding for it agrees rather than disagrees.
    manifest = _manifest(_slot(status=MaterialSlotStatus.MISSING))

    assert compare_material_manifests(manifest, ()) == ()


def test_disagreeing_about_resolution_is_reported_both_ways() -> None:
    resolved_import = _manifest(_slot())
    unresolved_import = _manifest(_slot(status=MaterialSlotStatus.MISSING))
    path = "character/texture/blade_base.dds"

    import_says_yes = compare_material_manifests(resolved_import, (_row(path, "missing_dds"),))
    import_says_no = compare_material_manifests(unresolved_import, (_row(path, "ready"),))

    for disagreements in (import_says_yes, import_says_no):
        assert len(disagreements) == 1
        assert "whether this path resolved" in disagreements[0].reason


def test_a_package_row_the_import_never_routed_is_left_alone() -> None:
    # The package legitimately carries bindings the target already had. Calling
    # those disagreements would bury the signal this exists to surface.
    manifest = _manifest(_slot())
    rows = (
        _row("character/texture/blade_base.dds"),
        _row("character/texture/an_original_the_import_never_touched.dds"),
    )

    assert compare_material_manifests(manifest, rows) == ()


def test_one_resolved_row_among_several_is_enough_to_agree() -> None:
    manifest = _manifest(_slot())
    path = "character/texture/blade_base.dds"

    assert compare_material_manifests(manifest, (_row(path, "missing_dds"), _row(path, "ready"))) == ()


def test_warnings_are_headed_by_a_count_and_are_bounded() -> None:
    manifest = _manifest(*(_slot(f"character/texture/slot_{index}.dds") for index in range(12)))

    lines = manifest_agreement_warnings(manifest, (), limit=3)

    assert "disagrees with the packaged bindings in 12 place(s)" in lines[0]
    assert len(lines) == 1 + 3 + 1
    assert lines[-1].strip() == "... 9 more"


def test_a_disagreement_line_names_both_sides() -> None:
    manifest = _manifest(_slot())

    line = compare_material_manifests(manifest, ())[0].as_line()

    assert "character/texture/blade_base.dds" in line
    assert "import: generated" in line
    assert "package: absent" in line


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_slot_with_no_target_path_is_skipped(blank: str) -> None:
    assert compare_material_manifests(_manifest(_slot(blank)), ()) == ()


def test_the_package_boundary_reports_the_comparison_as_a_warning() -> None:
    """Warnings, not blockers, until a real build says what normal looks like."""

    import tempfile
    from pathlib import Path

    from cdmw.core.final_package_builder import build_final_package_preview

    from tests.test_final_package_preview import _dds, _preview, _sidecar

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        preview = _preview()
        # The import claims a file the sidecar never references.
        preview.imported_material_manifest = _manifest(
            _slot("character/texture/never_referenced.dds")
        )
        from cdmw.core.archive_modding import MeshImportSupplementalFileSpec

        result = build_final_package_preview(
            preview,
            supplemental_file_specs=(
                MeshImportSupplementalFileSpec(
                    source_path=root / "blade.dds",
                    target_path="character/texture/blade_base.dds",
                    kind="texture_generated",
                    payload_data=_dds(),
                ),
                MeshImportSupplementalFileSpec(
                    source_path=root / "test_weapon.pac_xml",
                    target_path="character/modelproperty/test_weapon.pac_xml",
                    kind="sidecar_generated",
                    payload_data=_sidecar("character/texture/blade_base.dds"),
                ),
            ),
        )

    assert any("disagrees with the packaged bindings" in line for line in result.warnings)
    assert not any(
        "disagrees with the packaged bindings" in line for line in result.preflight_errors
    )
