from __future__ import annotations

from pathlib import Path

from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser import binary_sidecar_actions
from cdmw.ui.archive_browser.binary_sidecar_actions import ArchiveBinarySidecarActionsMixin
from cdmw.ui.archive_browser.hkx_document_actions import ArchiveHkxDocumentActionsMixin
from cdmw.ui.archive_browser.material_sidecar_actions import ArchiveMaterialSidecarActionsMixin
from cdmw.ui.archive_browser.remote_preview_dependencies import ArchivePreviewDependencySet


def _entry(path: str, offset: int, *, prepared_path: Path | None = None) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("C:/Game/0009/0.pamt"),
        paz_file=Path("C:/Game/0009/0.paz"),
        offset=offset,
        comp_size=20,
        orig_size=40,
        flags=0,
        paz_index=0,
        prepared_path=prepared_path,
        prepared_sha256=f"sha-{offset}" if prepared_path is not None else "",
    )


def _snapshot(selected: ArchiveEntry, *dependencies: ArchiveEntry) -> ArchivePreviewDependencySet:
    entries = (selected, *dependencies)
    return ArchivePreviewDependencySet(
        session_id="session-a",
        entry_id=7,
        entries=entries,
        entries_by_normalized_path={entry.path.casefold(): (entry,) for entry in entries},
        entries_by_basename={entry.basename.casefold(): (entry,) for entry in entries},
        total_candidates=len(dependencies),
        truncated=False,
    )


class _Bridge:
    displays_v2 = True

    def __init__(self, snapshot: ArchivePreviewDependencySet) -> None:
        self.snapshot = snapshot

    def prepared_dependencies_for(self, _entry: ArchiveEntry) -> ArchivePreviewDependencySet:
        return self.snapshot


def test_material_sidecar_resolution_uses_bounded_remote_maps(tmp_path: Path) -> None:
    prepared_mesh = _entry("character/model/hero.pac", 100, prepared_path=tmp_path / "hero.pac")
    prepared_sidecar = _entry(
        "character/model/hero.pac_xml",
        200,
        prepared_path=tmp_path / "hero.pac_xml",
    )
    snapshot = _snapshot(prepared_mesh, prepared_sidecar)

    class _Owner:
        archive_remote_bridge = _Bridge(snapshot)

        @property
        def archive_entries_by_basename(self) -> object:
            raise AssertionError("material sidecar lookup touched the legacy basename map")

    selected = _entry("character/model/hero.pac", 100)
    resolved = ArchiveMaterialSidecarActionsMixin._related_material_sidecar_entry_for_archive_entry(
        _Owner(),
        selected,
    )

    assert resolved is prepared_sidecar


def test_binary_sidecar_decode_uses_prepared_source_and_bounded_maps(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepared_path = tmp_path / "hero.meshinfo"
    prepared_path.write_bytes(b"meshinfo")
    prepared = _entry("character/model/hero.meshinfo", 300, prepared_path=prepared_path)
    snapshot = _snapshot(prepared)
    captured: dict[str, object] = {}

    class _Owner:
        archive_remote_bridge = _Bridge(snapshot)

        @property
        def archive_entries_by_normalized_path(self) -> object:
            raise AssertionError("binary sidecar decode touched the legacy path map")

        @property
        def archive_entries_by_basename(self) -> object:
            raise AssertionError("binary sidecar decode touched the legacy basename map")

    monkeypatch.setattr(
        binary_sidecar_actions,
        "ensure_archive_preview_source",
        lambda entry: (entry.prepared_path, "prepared"),
    )

    def _build(data: bytes, path: str, **kwargs: object) -> str:
        captured.update(data=data, path=path, **kwargs)
        return "bounded-sidecar-json"

    monkeypatch.setattr(binary_sidecar_actions, "build_binary_sidecar_analysis_json", _build)
    selected = _entry("character/model/hero.meshinfo", 300)

    result = ArchiveBinarySidecarActionsMixin._build_archive_binary_sidecar_json_document(
        _Owner(),
        selected,
    )

    assert result == "bounded-sidecar-json"
    assert captured["data"] == b"meshinfo"
    assert captured["source_entry"] is prepared
    assert captured["archive_entries_by_normalized_path"] is snapshot.entries_by_normalized_path
    assert captured["archive_entries_by_basename"] is snapshot.entries_by_basename


def test_hkx_companion_lookup_uses_bounded_remote_maps(tmp_path: Path) -> None:
    prepared_hkx = _entry(
        "character/physics/hero.hkx",
        400,
        prepared_path=tmp_path / "hero.hkx",
    )
    prepared_xml = _entry(
        "character/physics/hero.xml",
        500,
        prepared_path=tmp_path / "hero.xml",
    )
    snapshot = _snapshot(prepared_hkx, prepared_xml)

    class _Owner(ArchiveHkxDocumentActionsMixin):
        archive_remote_bridge = _Bridge(snapshot)

        @staticmethod
        def _normalize_archive_entry_path(path: str) -> str:
            return path.replace("\\", "/").strip("/").casefold()

        @staticmethod
        def _current_archive_related_references_for_entry(_entry: ArchiveEntry) -> tuple[object, ...]:
            return ()

        @staticmethod
        def set_status_message(_message: str, *, error: bool = False) -> None:
            raise AssertionError(f"unexpected HKX lookup failure: error={error}")

        @property
        def archive_entries_by_normalized_path(self) -> object:
            raise AssertionError("HKX companion lookup touched the legacy path map")

        @property
        def archive_entries_by_basename(self) -> object:
            raise AssertionError("HKX companion lookup touched the legacy basename map")

    selected = _entry("character/physics/hero.hkx", 400)
    resolved = ArchiveHkxDocumentActionsMixin._archive_hkx_companion_descriptor_entries(
        _Owner(),
        selected,
    )

    assert resolved == (prepared_xml,)
