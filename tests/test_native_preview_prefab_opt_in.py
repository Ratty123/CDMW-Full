from __future__ import annotations

from pathlib import Path

from cdmw.models import ArchiveEntry
from cdmw.rendering.native_preview_core import build_native_preview_core_job


def _entry() -> ArchiveEntry:
    return ArchiveEntry(
        path="character/model/body.pac",
        pamt_path=Path("archive.pamt"),
        paz_file=Path("archive.paz"),
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


def test_native_preview_job_defaults_to_no_prefab_components(tmp_path: Path) -> None:
    job = build_native_preview_core_job(
        _entry(),
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "package",
    )

    assert job["enabled_prefab_component_paths"] == []


def test_native_preview_job_captures_deduplicated_prefab_selection(tmp_path: Path) -> None:
    job = build_native_preview_core_job(
        _entry(),
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "package",
        enabled_prefab_component_paths=(
            "character\\underwear.pac",
            "CHARACTER/UNDERWEAR.PAC",
        ),
    )

    assert job["enabled_prefab_component_paths"] == ["character/underwear.pac"]


def test_native_core_prefab_geometry_and_sidecars_are_selection_gated() -> None:
    protocol = Path("native/cdmw_preview_core/src/owners/protocol_json.cpp").read_text(encoding="utf-8")
    lookup = Path("native/cdmw_preview_core/src/owners/material_archive_lookup.cpp").read_text(encoding="utf-8")
    report = Path("native/cdmw_preview_core/src/owners/preview_report.cpp").read_text(encoding="utf-8")

    assert '"enabled_prefab_component_paths"' in protocol
    assert "prefab_component_enabled_for_job(component, job)" in lookup
    assert 'job.extension == ".pac" && !job.enabled_prefab_component_paths.empty()' in lookup
    assert "if (!prefab_component_enabled_for_job(component, job)) continue;" in report
    assert "none loaded until enabled in Archive Browser Parts" in report
