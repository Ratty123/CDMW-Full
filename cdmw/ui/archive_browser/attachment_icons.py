"""Archive browser attachment-package item icon helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

from cdmw.services.archive_preview_service import ensure_archive_preview_source
from cdmw.domain.archives.mesh_contracts import MeshImportSupplementalFileSpec
from cdmw.domain.library.item_icons import ItemIconOverrideSpec
from cdmw.models import ArchiveEntry, AssetFamilyGraph, AttachmentPlacementEvidence


class ArchiveAttachmentIconMixin:
    """Attachment-package item icon discovery and supplemental build helpers."""

    def _attachment_package_item_icon_entries(
        self,
        entry: ArchiveEntry,
        graph: AssetFamilyGraph,
    ) -> List[ArchiveEntry]:
        icon_entries: List[ArchiveEntry] = []
        seen: set[Tuple[str, str, int]] = set()
        stems: set[str] = set()

        def add_icon(candidate: Optional[ArchiveEntry]) -> None:
            if not isinstance(candidate, ArchiveEntry):
                return
            candidate_path = candidate.path.replace("\\", "/").strip()
            candidate_lower = candidate_path.casefold()
            candidate_name = PurePosixPath(candidate_lower).name
            extension = str(candidate.extension or "").lower()
            if extension not in {".dds", ".png"}:
                return
            if "itemicon" not in candidate_name and "/ui/" not in candidate_lower and "/icon/" not in candidate_lower:
                return
            key = self._attachment_package_entry_key(candidate)
            if key in seen:
                return
            seen.add(key)
            icon_entries.append(candidate)

        def add_stem(raw_path: object) -> None:
            normalized = str(raw_path or "").replace("\\", "/").strip().casefold()
            if not normalized:
                return
            stem = PurePosixPath(normalized).stem.casefold()
            if not stem:
                return
            candidates = {stem, self._attachment_package_strip_side_suffix(normalized)}
            for prefix in ("itemicon_prefab_", "itemicon_", "icon_prefab_", "icon_"):
                if stem.startswith(prefix):
                    stripped = stem[len(prefix):].strip("_")
                    if stripped:
                        candidates.add(stripped)
                        candidates.add(self._attachment_package_strip_side_suffix(stripped))
            for candidate_stem in candidates:
                if candidate_stem:
                    stems.add(candidate_stem)

        graph_entries = self._attachment_package_graph_entries(entry, graph)
        for candidate in graph_entries:
            add_icon(candidate)
            add_stem(getattr(candidate, "path", ""))
        for evidence in tuple(getattr(graph, "attachment_evidence", ()) or ()):
            if not isinstance(evidence, AttachmentPlacementEvidence):
                continue
            for candidate_path in (
                evidence.prefab_path,
                evidence.socket_file_path,
                evidence.model_path,
                evidence.skeleton_path,
            ):
                add_stem(candidate_path)

        entry_path = entry.path.replace("\\", "/").strip().casefold()
        for row in tuple(getattr(self, "archive_item_asset_catalog", ()) or ()):
            if not isinstance(row, Mapping):
                continue
            row_model_paths = {value.replace("\\", "/").strip().casefold() for value in self._archive_asset_catalog_row_values(row, "pac_files")}
            row_model_stems = {PurePosixPath(value.replace("\\", "/").strip()).stem.casefold() for value in self._archive_asset_catalog_row_values(row, "model_stems")}
            row_model_stems = {stem for stem in row_model_stems if stem}
            if entry_path not in row_model_paths and not (stems & row_model_stems):
                continue
            for icon_path in self._archive_asset_catalog_row_values(row, "icon_paths"):
                for icon_entry in self._resolve_archive_asset_catalog_path_candidates(icon_path, fallback_extensions=(".dds", ".png")):
                    add_icon(icon_entry)

        for stem in sorted(stems):
            stem_variants = [stem]
            if not stem.endswith(("_r", "_l")):
                stem_variants.extend([f"{stem}_r", f"{stem}_l"])
            for stem_variant in stem_variants:
                for basename in (
                    f"itemicon_prefab_{stem_variant}.dds",
                    f"itemicon_{stem_variant}.dds",
                    f"icon_prefab_{stem_variant}.dds",
                    f"icon_{stem_variant}.dds",
                ):
                    for candidate in tuple(self.archive_entries_by_basename.get(basename, ()) or ()):
                        add_icon(candidate)

        return icon_entries

    def _archive_item_icon_related_stems(
        self,
        entry: ArchiveEntry,
        graph: Optional[AssetFamilyGraph] = None,
    ) -> Tuple[str, ...]:
        stems: List[str] = []

        def add_path(raw_path: object) -> None:
            normalized = str(raw_path or "").replace("\\", "/").strip()
            if not normalized:
                return
            stem = PurePosixPath(normalized).stem.casefold()
            if stem and stem not in stems:
                stems.append(stem)

        add_path(getattr(entry, "path", ""))
        if isinstance(graph, AssetFamilyGraph):
            for candidate in self._attachment_package_graph_entries(entry, graph):
                add_path(getattr(candidate, "path", ""))
            for evidence in tuple(getattr(graph, "attachment_evidence", ()) or ()):
                if not isinstance(evidence, AttachmentPlacementEvidence):
                    continue
                add_path(evidence.prefab_path)
                add_path(evidence.model_path)
                add_path(evidence.socket_file_path)
        return tuple(stems)

    def _build_custom_item_icon_supplemental_spec(
        self,
        icon_spec: ItemIconOverrideSpec,
        *,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> MeshImportSupplementalFileSpec:
        target_entry = icon_spec.target_entry
        if not isinstance(target_entry, ArchiveEntry):
            raise ValueError("A resolved existing target icon entry is required for custom item icons.")
        target_template_path, _note = ensure_archive_preview_source(target_entry)
        result = self.app_context.services.require_item_icons().build_payload(
            icon_spec,
            target_template_path=target_template_path,
            on_log=on_log,
        )
        if on_log is not None:
            for warning in result.warnings:
                on_log(f"Custom item icon warning: {warning}")
        return MeshImportSupplementalFileSpec(
            source_path=result.source_path,
            target_path=result.target_path,
            kind="item_icon_generated",
            target_entry=target_entry,
            used_for_preview=True,
            payload_data=result.payload_data,
            note=(
                "Generated custom item icon "
                f"from {result.source_path.name} at {result.target_width}x{result.target_height} "
                f"using {result.target_format}."
            ),
        )

    def _attachment_package_source_icon_override_rows(
        self,
        target_entry: ArchiveEntry,
        source_entry: ArchiveEntry,
        target_graph: AssetFamilyGraph,
        source_graph: AssetFamilyGraph,
    ) -> Tuple[List[Tuple[ArchiveEntry, ArchiveEntry, str]], List[str]]:
        target_icons = self._attachment_package_item_icon_entries(target_entry, target_graph)
        source_icons = self._attachment_package_item_icon_entries(source_entry, source_graph)
        if not source_icons:
            return [], ()
        if not target_icons:
            return [], ("Source icon was resolved, but no target icon path was resolved to override.",)

        def icon_prefix(entry: ArchiveEntry) -> str:
            stem = PurePosixPath(entry.path.replace("\\", "/").casefold()).stem
            for prefix in ("itemicon_prefab_", "itemicon_", "icon_prefab_", "icon_"):
                if stem.startswith(prefix):
                    return prefix
            return ""

        def score_source_icon(source_icon: ArchiveEntry, target_icon: ArchiveEntry) -> int:
            score = 0
            if str(source_icon.extension or "").lower() == str(target_icon.extension or "").lower():
                score += 20
            source_side = self._attachment_package_side_suffix(source_icon.path)
            target_side = self._attachment_package_side_suffix(target_icon.path)
            if source_side and source_side == target_side:
                score += 60
            if icon_prefix(source_icon) == icon_prefix(target_icon):
                score += 25
            return score

        rows: List[Tuple[ArchiveEntry, ArchiveEntry, str]] = []
        for target_icon in target_icons[:6]:
            source_icon = max(source_icons, key=lambda candidate: score_source_icon(candidate, target_icon))
            if self._same_archive_entry(source_icon, target_icon):
                continue
            rows.append(
                (
                    source_icon,
                    target_icon,
                    "Copies the placement-source inventory/UI icon onto the target icon path so the in-game swap icon follows the visible source model.",
                )
            )
        return rows, ()
