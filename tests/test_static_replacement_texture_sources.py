from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from cdmw.models import ArchiveEntry
from cdmw.models import RunCancelled
from cdmw.ui.archive_browser.static_replacement_texture_sources import (
    add_archive_texture_lookup_entry,
    archive_texture_lookup_indexes_for_alignment,
    register_allowed_texture_source_file,
    register_dialog_supplemental_file,
    register_texture_source_file,
    register_texture_source_files,
    scan_texture_source_folder,
    texture_source_files_in_folder,
)


def _archive_entry(path: str) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("test.pamt"),
        paz_file=Path("test.paz"),
        offset=0,
        comp_size=0,
        orig_size=0,
        flags=0,
        paz_index=0,
    )


def test_register_texture_source_files_adds_allowed_unique_resolved_paths(tmp_path: Path) -> None:
    body = tmp_path / "body.dds"
    body.write_bytes(b"DDS ")
    ignored = tmp_path / "notes.txt"
    ignored.write_text("skip", encoding="utf-8")
    texture_files: list[Path] = []
    seen: set[str] = set()

    assert register_texture_source_files(
        (body, ignored, tmp_path / "missing.dds", body),
        texture_files_for_mapping=texture_files,
        seen_texture_file_keys=seen,
        allowed_extensions=(".dds", ".png"),
    )

    assert texture_files == [body.resolve()]
    assert seen == {str(body.resolve()).lower()}
    assert not register_texture_source_files(
        (body,),
        texture_files_for_mapping=texture_files,
        seen_texture_file_keys=seen,
        allowed_extensions=(".dds", ".png"),
    )


def test_register_texture_source_file_adds_unique_existing_path_without_extension_filter(tmp_path: Path) -> None:
    texture = tmp_path / "manual.custom"
    texture.write_text("data", encoding="utf-8")
    texture_files: list[Path] = []
    seen: set[str] = set()

    assert register_texture_source_file(
        texture,
        texture_files_for_mapping=texture_files,
        seen_texture_file_keys=seen,
    )

    assert texture_files == [texture.resolve()]
    assert seen == {str(texture.resolve()).lower()}
    assert not register_texture_source_file(
        texture,
        texture_files_for_mapping=texture_files,
        seen_texture_file_keys=seen,
    )
    assert not register_texture_source_file(
        tmp_path / "missing.dds",
        texture_files_for_mapping=texture_files,
        seen_texture_file_keys=seen,
    )


def test_register_allowed_texture_source_file_returns_resolved_path_and_filters_extension(tmp_path: Path) -> None:
    texture = tmp_path / "body.dds"
    ignored = tmp_path / "body.txt"
    texture.write_bytes(b"DDS ")
    ignored.write_text("skip", encoding="utf-8")
    texture_files: list[Path] = []
    seen: set[str] = set()

    assert register_allowed_texture_source_file(
        texture,
        texture_files_for_mapping=texture_files,
        seen_texture_file_keys=seen,
        allowed_extensions=(".dds",),
    ) == texture.resolve()

    assert texture_files == [texture.resolve()]
    assert seen == {str(texture.resolve()).lower()}
    assert register_allowed_texture_source_file(
        texture,
        texture_files_for_mapping=texture_files,
        seen_texture_file_keys=seen,
        allowed_extensions=(".dds",),
    ) == texture.resolve()
    assert texture_files == [texture.resolve()]
    assert register_allowed_texture_source_file(
        ignored,
        texture_files_for_mapping=texture_files,
        seen_texture_file_keys=seen,
        allowed_extensions=(".dds",),
    ) is None


def test_register_dialog_supplemental_file_updates_supplemental_and_texture_lists(tmp_path: Path) -> None:
    texture = tmp_path / "body.dds"
    mesh = tmp_path / "body.obj"
    texture.write_bytes(b"DDS ")
    mesh.write_text("obj", encoding="utf-8")
    dialog_added: list[Path] = []
    texture_files: list[Path] = []

    assert register_dialog_supplemental_file(
        texture,
        dialog_added_supplemental_files=dialog_added,
        supplemental_files=(),
        texture_files_for_mapping=texture_files,
        allowed_texture_extensions=(".dds",),
    ) == texture.resolve()

    assert dialog_added == [texture.resolve()]
    assert texture_files == [texture.resolve()]

    register_dialog_supplemental_file(
        texture,
        dialog_added_supplemental_files=dialog_added,
        supplemental_files=(),
        texture_files_for_mapping=texture_files,
        allowed_texture_extensions=(".dds",),
    )
    assert dialog_added == [texture.resolve()]
    assert texture_files == [texture.resolve()]

    register_dialog_supplemental_file(
        mesh,
        dialog_added_supplemental_files=dialog_added,
        supplemental_files=(),
        texture_files_for_mapping=texture_files,
        allowed_texture_extensions=(".dds",),
    )
    assert dialog_added == [texture.resolve(), mesh.resolve()]
    assert texture_files == [texture.resolve()]


def test_register_dialog_supplemental_file_skips_original_supplemental(tmp_path: Path) -> None:
    original = tmp_path / "existing.dds"
    original.write_bytes(b"DDS ")
    dialog_added: list[Path] = []
    texture_files: list[Path] = []

    register_dialog_supplemental_file(
        original,
        dialog_added_supplemental_files=dialog_added,
        supplemental_files=(original,),
        texture_files_for_mapping=texture_files,
        allowed_texture_extensions=(".dds",),
    )

    assert dialog_added == []
    assert texture_files == [original.resolve()]


def test_texture_source_files_in_folder_returns_sorted_allowed_files(tmp_path: Path) -> None:
    first = tmp_path / "a.dds"
    second = tmp_path / "nested" / "b.png"
    ignored = tmp_path / "c.txt"
    second.parent.mkdir()
    second.write_bytes(b"png")
    first.write_bytes(b"DDS ")
    ignored.write_text("skip", encoding="utf-8")

    assert texture_source_files_in_folder(tmp_path, allowed_extensions=(".dds", ".png")) == (
        first,
        second,
    )
    assert texture_source_files_in_folder(tmp_path / "missing", allowed_extensions=(".dds",)) == ()


def test_texture_folder_scan_is_bounded_and_cancellable(tmp_path: Path) -> None:
    for index in range(5):
        (tmp_path / f"texture_{index}.dds").write_bytes(b"DDS ")

    result = scan_texture_source_folder(
        tmp_path,
        allowed_extensions=(".dds",),
        max_files=2,
    )

    assert len(result.files) == 2
    assert result.truncated
    assert result.scanned_entries <= 100_000

    exact_limit_root = tmp_path / "exact"
    exact_limit_root.mkdir()
    for index in range(2):
        (exact_limit_root / f"texture_{index}.dds").write_bytes(b"DDS ")
    exact_limit = scan_texture_source_folder(
        exact_limit_root,
        allowed_extensions=(".dds",),
        max_files=2,
    )
    assert len(exact_limit.files) == 2
    assert not exact_limit.truncated

    stop_event = threading.Event()
    stop_event.set()
    try:
        scan_texture_source_folder(
            tmp_path,
            allowed_extensions=(".dds",),
            stop_event=stop_event,
        )
    except RunCancelled:
        pass
    else:
        raise AssertionError("pre-cancelled texture folder scan must stop before traversal")


def test_add_archive_texture_lookup_entry_normalizes_and_deduplicates_archive_entries() -> None:
    path_index: dict[str, list[ArchiveEntry]] = {}
    basename_index: dict[str, list[ArchiveEntry]] = {}
    entry = _archive_entry("Textures\\Body\\TORSO_D.DDS")

    add_archive_texture_lookup_entry(path_index, basename_index, entry)
    add_archive_texture_lookup_entry(path_index, basename_index, entry)
    add_archive_texture_lookup_entry(path_index, basename_index, object())

    assert path_index == {"textures/body/torso_d.dds": [entry]}
    assert basename_index == {"torso_d.dds": [entry]}


def test_archive_texture_lookup_indexes_include_graph_references_dds_and_related_sidecars() -> None:
    target = _archive_entry("Characters/Hero/BODY.PAC")
    graph_entry = _archive_entry("Textures/Graph_D.DDS")
    resolved_reference = _archive_entry("Textures/Reference_N.DDS")
    archive_dds = _archive_entry("Textures/Body_D.DDS")
    target_sidecar = _archive_entry("Sidecars\\Body.PAC")
    related_sidecar = _archive_entry("Sidecars/ARM.PAC")
    unrelated_sidecar = _archive_entry("Sidecars/Leg.PAC")

    indexes = archive_texture_lookup_indexes_for_alignment(
        target_entry=target,
        graph_entries=(graph_entry,),
        graph_references=(
            SimpleNamespace(resolved_entry=resolved_reference),
            SimpleNamespace(resolved_entry=object()),
        ),
        related_target_basenames=("arm.pac",),
        extension_index={
            ".dds": (archive_dds, object()),
            ".xml": (target_sidecar, related_sidecar, unrelated_sidecar),
        },
    )

    assert indexes.graph_reference_count == 2
    assert indexes.dds_count == 1
    assert indexes.sidecar_count == 2
    assert set(indexes.path_index) == {
        "textures/graph_d.dds",
        "textures/reference_n.dds",
        "textures/body_d.dds",
        "sidecars/body.pac",
        "sidecars/arm.pac",
    }
    assert indexes.basename_index["body.pac"] == [target_sidecar]
    assert indexes.basename_index["arm.pac"] == [related_sidecar]
    assert "leg.pac" not in indexes.basename_index
