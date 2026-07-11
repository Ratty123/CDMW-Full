"""Archive browser attachment-package selection helpers."""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import List, Optional, Tuple

from cdmw.services.archive_query_service import (
    find_archive_model_related_entries as _find_archive_model_related_entries,
    build_archive_relationship_references,
)
from cdmw.domain.archives.format import is_material_sidecar_extension as _is_material_sidecar_extension
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ArchiveEntry, AssetFamilyGraph, AssetFamilyMember, AttachmentPlacementEvidence


class ArchiveAttachmentPackageMixin:
    """Attachment package graph, matching, and compatibility helpers."""

    @staticmethod
    def _attachment_package_entry_key(entry: Optional[ArchiveEntry]) -> Tuple[str, str, int]:
        if not isinstance(entry, ArchiveEntry):
            return ("", "", 0)
        return (
            entry.path.replace("\\", "/").strip().casefold(),
            str(entry.pamt_path).strip().casefold(),
            int(entry.offset),
        )

    @staticmethod
    def _attachment_package_path_stem(path: str) -> str:
        return PurePosixPath(str(path or "").replace("\\", "/")).stem.casefold()

    @staticmethod
    def _attachment_package_side_suffix(path: str) -> str:
        stem = PurePosixPath(str(path or "").replace("\\", "/")).stem.casefold()
        for suffix in ("_r", "_l", "_in", "_out"):
            if stem.endswith(suffix):
                return suffix
        return ""

    @staticmethod
    def _attachment_package_strip_side_suffix(path: str) -> str:
        stem = PurePosixPath(str(path or "").replace("\\", "/")).stem.casefold()
        for suffix in ("_r", "_l", "_in", "_out"):
            if stem.endswith(suffix):
                return stem[: -len(suffix)]
        return stem

    def _attachment_package_graph_entries(
        self,
        entry: ArchiveEntry,
        graph: AssetFamilyGraph,
    ) -> List[ArchiveEntry]:
        entries: List[ArchiveEntry] = []
        seen: set[Tuple[str, str, int]] = set()

        def add(candidate: Optional[ArchiveEntry]) -> None:
            if not isinstance(candidate, ArchiveEntry):
                return
            key = self._attachment_package_entry_key(candidate)
            if key in seen:
                return
            seen.add(key)
            entries.append(candidate)

        add(entry)
        for member in tuple(getattr(graph, "member_rows", ()) or ()):
            if isinstance(member, AssetFamilyMember):
                add(getattr(member, "resolved_entry", None))
        for evidence in tuple(getattr(graph, "attachment_evidence", ()) or ()):
            if not isinstance(evidence, AttachmentPlacementEvidence):
                continue
            for candidate_path in (
                evidence.prefab_path,
                evidence.socket_file_path,
                evidence.model_path,
                evidence.skeleton_path,
            ):
                if candidate_path:
                    add(self._find_archive_entry_by_virtual_path(candidate_path))
        try:
            related_entries = _find_archive_model_related_entries(entry, self.archive_entries_by_basename)
        except Exception:
            related_entries = ()
        for candidate in tuple(related_entries or ()):
            add(candidate)
        return entries

    def _attachment_package_entries_with_extension(
        self,
        entry: ArchiveEntry,
        graph: AssetFamilyGraph,
        extensions: set[str],
    ) -> List[ArchiveEntry]:
        return [
            candidate
            for candidate in self._attachment_package_graph_entries(entry, graph)
            if isinstance(candidate, ArchiveEntry) and str(candidate.extension or "").lower() in extensions
        ]

    def _score_attachment_package_target_entry(
        self,
        candidate: ArchiveEntry,
        donor: ArchiveEntry,
        selected_target: ArchiveEntry,
    ) -> int:
        candidate_path = candidate.path.replace("\\", "/").casefold()
        donor_path = donor.path.replace("\\", "/").casefold()
        selected_path = selected_target.path.replace("\\", "/").casefold()
        candidate_stem = self._attachment_package_path_stem(candidate_path)
        donor_stem = self._attachment_package_path_stem(donor_path)
        selected_stem = self._attachment_package_path_stem(selected_path)
        candidate_base_stem = self._attachment_package_strip_side_suffix(candidate_path)
        selected_base_stem = self._attachment_package_strip_side_suffix(selected_path)
        donor_side = self._attachment_package_side_suffix(donor_path)
        candidate_side = self._attachment_package_side_suffix(candidate_path)
        score = 0
        if candidate_stem == selected_stem:
            score += 140
        if candidate_base_stem and candidate_base_stem == selected_base_stem:
            score += 80
        if selected_stem and candidate_stem.startswith(selected_stem):
            score += 30
        if donor_side and candidate_side == donor_side:
            score += 20
        if candidate.extension == donor.extension:
            score += 20
        if candidate.pamt_path == selected_target.pamt_path:
            score += 8
        if candidate.extension == ".prefab" and "/prefab/" in candidate_path:
            score += 35
        if candidate.extension in {".hkx", ".hkt"} and "/meshphysics/" in candidate_path:
            score += 35
        if candidate.extension in {".paa", ".paa_metabin", ".motionblending"} and (
            "/animation/" in candidate_path or "motion" in candidate_path
        ):
            score += 25
        return score

    def _choose_attachment_package_target_entry(
        self,
        donor: ArchiveEntry,
        selected_target: ArchiveEntry,
        target_graph: AssetFamilyGraph,
        extensions: set[str],
    ) -> Optional[ArchiveEntry]:
        candidates = self._attachment_package_entries_with_extension(selected_target, target_graph, extensions)
        donor_extension = str(donor.extension or "").lower()
        candidates = [
            candidate
            for candidate in candidates
            if not self._same_archive_entry(candidate, donor)
            and (donor_extension not in extensions or str(candidate.extension or "").lower() == donor_extension)
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda candidate: self._score_attachment_package_target_entry(candidate, donor, selected_target),
        )

    def _choose_attachment_package_donor_prefab(
        self,
        donor_entry: ArchiveEntry,
        donor_graph: AssetFamilyGraph,
        target_prefab: Optional[ArchiveEntry],
    ) -> Optional[ArchiveEntry]:
        donor_prefabs = self._attachment_package_entries_with_extension(donor_entry, donor_graph, {".prefab"})
        if not donor_prefabs:
            return None
        target_side = self._attachment_package_side_suffix(target_prefab.path if isinstance(target_prefab, ArchiveEntry) else "")

        def score(candidate: ArchiveEntry) -> int:
            candidate_side = self._attachment_package_side_suffix(candidate.path)
            value = 0
            if self._same_archive_entry(candidate, donor_entry):
                value += 300
            if target_side and candidate_side == target_side:
                value += 90
            if not target_side and candidate_side == "_r":
                value += 70
            if not target_side and not candidate_side:
                value += 45
            if candidate_side == "_l":
                value += 20
            if "/prefab/" in candidate.path.replace("\\", "/").casefold():
                value += 15
            return value

        return max(donor_prefabs, key=score)

    def _attachment_package_target_prefab_entries_for_donor(
        self,
        selected_target: ArchiveEntry,
        target_graph: AssetFamilyGraph,
        donor_prefab: ArchiveEntry,
        selected_target_prefab: Optional[ArchiveEntry],
    ) -> List[ArchiveEntry]:
        target_prefabs = self._attachment_package_entries_with_extension(selected_target, target_graph, {".prefab"})
        if selected_target_prefab is None:
            selected_target_prefab = self._choose_attachment_package_target_entry(
                donor_prefab,
                selected_target,
                target_graph,
                {".prefab"},
            )
        if not isinstance(selected_target_prefab, ArchiveEntry):
            return []
        selected_path = selected_target_prefab.path.replace("\\", "/").strip()
        selected_base_stem = self._attachment_package_strip_side_suffix(selected_path)
        selected_folder = PurePosixPath(selected_path).parent.as_posix().casefold()
        donor_side = self._attachment_package_side_suffix(donor_prefab.path)
        targets: List[ArchiveEntry] = []
        seen: set[Tuple[str, str, int]] = set()

        def add(candidate: ArchiveEntry) -> None:
            key = self._attachment_package_entry_key(candidate)
            if key in seen:
                return
            seen.add(key)
            targets.append(candidate)

        add(selected_target_prefab)
        if not selected_base_stem:
            return targets

        for candidate in target_prefabs:
            candidate_path = candidate.path.replace("\\", "/").strip()
            if PurePosixPath(candidate_path).parent.as_posix().casefold() != selected_folder:
                continue
            if self._attachment_package_strip_side_suffix(candidate_path) != selected_base_stem:
                continue
            candidate_side = self._attachment_package_side_suffix(candidate_path)
            if candidate_side in {"_l", "_r"}:
                add(candidate)
            elif donor_side and candidate_side == donor_side:
                add(candidate)

        targets.sort(
            key=lambda entry: (
                0 if self._same_archive_entry(entry, selected_target_prefab) else 1,
                self._attachment_package_side_suffix(entry.path) or "_",
                entry.path.casefold(),
            )
        )
        return targets

    def _attachment_package_socket_entries_for_prefab(
        self,
        donor_graph: AssetFamilyGraph,
        donor_prefab: ArchiveEntry,
    ) -> List[ArchiveEntry]:
        socket_entries: List[ArchiveEntry] = []
        seen_paths: set[str] = set()
        donor_prefab_path = donor_prefab.path.replace("\\", "/").casefold()
        fallback_paths: List[str] = []
        for evidence in tuple(getattr(donor_graph, "attachment_evidence", ()) or ()):
            if not isinstance(evidence, AttachmentPlacementEvidence):
                continue
            socket_path = str(evidence.socket_file_path or "").replace("\\", "/").strip()
            if not socket_path:
                continue
            if str(evidence.prefab_path or "").replace("\\", "/").casefold() == donor_prefab_path:
                fallback_paths.insert(0, socket_path)
            else:
                fallback_paths.append(socket_path)
        for socket_path in fallback_paths:
            normalized = socket_path.casefold()
            if normalized in seen_paths:
                continue
            seen_paths.add(normalized)
            socket_entry = self._find_archive_entry_by_virtual_path(socket_path)
            if isinstance(socket_entry, ArchiveEntry) and str(socket_entry.extension or "").lower() == ".xml":
                socket_entries.append(socket_entry)
        return socket_entries

    def _attachment_package_weapon_class_tokens(
        self,
        entry: ArchiveEntry,
        graph: AssetFamilyGraph,
    ) -> set[str]:
        tokens: set[str] = set()

        def add_from_path(raw_path: object) -> None:
            normalized = str(raw_path or "").replace("\\", "/").casefold()
            if not normalized:
                return
            if any(token in normalized for token in ("/1_onehandweapon/", "/01_onehandweapon/", "onehandweapon", "cd_phm_01_sword")):
                tokens.add("1H")
            if any(token in normalized for token in ("/2_twohandweapon/", "/02_twohandweapon/", "twohandweapon", "longsword", "cd_phm_02_sword")):
                tokens.add("2H")

        add_from_path(getattr(entry, "path", ""))
        for candidate in self._attachment_package_graph_entries(entry, graph):
            add_from_path(getattr(candidate, "path", ""))
        for evidence in tuple(getattr(graph, "attachment_evidence", ()) or ()):
            if not isinstance(evidence, AttachmentPlacementEvidence):
                continue
            add_from_path(evidence.prefab_path)
            add_from_path(evidence.socket_file_path)
            add_from_path(evidence.model_path)
            add_from_path(evidence.skeleton_path)
        return tokens

    def _attachment_package_weapon_subclass_tokens(
        self,
        entry: ArchiveEntry,
        graph: AssetFamilyGraph,
        *,
        allow_archive_reads: bool = False,
        stop_event: threading.Event | None = None,
    ) -> set[str]:
        cache_key = self._attachment_package_entry_key(entry)
        token_cache = getattr(self, "_attachment_weapon_subclass_token_cache", {})
        cached_tokens = token_cache.get(cache_key) if isinstance(token_cache, Mapping) else None
        if cached_tokens is not None and not allow_archive_reads:
            return set(cached_tokens)
        tokens: set[str] = set()

        def add_from_text(raw_text: object) -> None:
            normalized = str(raw_text or "").replace("\\", "/").casefold()
            if not normalized:
                return
            compact = re.sub(r"[^a-z0-9]+", "", normalized)
            split_tokens = {token for token in re.split(r"[^a-z0-9]+", normalized) if token}
            if "warhammer" in compact or ("war" in split_tokens and "hammer" in split_tokens):
                tokens.add("warhammer")
            elif "hammer" in split_tokens or "hammer" in compact:
                tokens.add("hammer")
            if "mace" in split_tokens or "mace" in compact:
                tokens.add("mace")
            if "battleaxe" in compact or "waraxe" in compact or "axe" in split_tokens:
                tokens.add("axe")
            if (
                "longsword" in compact
                or "sword" in split_tokens
                or "sword" in compact
                or "dagger" in split_tokens
                or "dagger" in compact
                or "blade" in split_tokens
                or "blade" in compact
                or "lswd" in split_tokens
            ):
                tokens.add("sword")
            if "shield" in split_tokens or "shield" in compact:
                tokens.add("shield")
            if "bow" in split_tokens or "bow" in compact or "crossbow" in compact:
                tokens.add("bow")
            if "spear" in split_tokens or "spear" in compact or "lance" in split_tokens:
                tokens.add("spear")
            if "staff" in split_tokens or "staff" in compact:
                tokens.add("staff")
            if "rifle" in split_tokens or "musket" in split_tokens or "gun" in split_tokens:
                tokens.add("firearm")

        add_from_text(getattr(entry, "path", ""))
        graph_entries = self._attachment_package_graph_entries(entry, graph)
        for candidate in graph_entries:
            add_from_text(getattr(candidate, "path", ""))
        for evidence in tuple(getattr(graph, "attachment_evidence", ()) or ()):
            if not isinstance(evidence, AttachmentPlacementEvidence):
                continue
            add_from_text(evidence.prefab_path)
            add_from_text(evidence.socket_file_path)
            add_from_text(evidence.model_path)
            add_from_text(evidence.skeleton_path)

        entry_paths = {
            str(getattr(candidate, "path", "") or "").replace("\\", "/").strip().casefold()
            for candidate in (entry, *tuple(graph_entries))
            if isinstance(candidate, ArchiveEntry)
        }
        entry_stems = {
            PurePosixPath(path).stem.casefold()
            for path in entry_paths
            if path
        }
        for row in tuple(getattr(self, "archive_item_asset_catalog", ()) or ()):
            if not isinstance(row, Mapping):
                continue
            row_paths = set()
            row_stems = set()
            for key in ("pac_files", "prefab_files", "hkx_files", "socket_files", "icon_paths"):
                for value in self._archive_asset_catalog_row_values(row, key):
                    normalized_value = value.replace("\\", "/").strip().casefold()
                    if normalized_value:
                        row_paths.add(normalized_value)
                        row_stems.add(PurePosixPath(normalized_value).stem.casefold())
            if not (entry_paths & row_paths or entry_stems & row_stems):
                continue
            for key in (
                "name",
                "display_name",
                "item_name",
                "category",
                "subcategory",
                "item_type",
                "pac_files",
                "prefab_files",
                "hkx_files",
                "socket_files",
            ):
                raw_value = row.get(key)
                if isinstance(raw_value, str):
                    add_from_text(raw_value)
                else:
                    for value in self._archive_asset_catalog_row_values(row, key):
                        add_from_text(value)

        if allow_archive_reads:
            for candidate in graph_entries:
                raise_if_cancelled(stop_event, "Attachment prefab classification cancelled.")
                if str(getattr(candidate, "extension", "") or "").lower() != ".prefab":
                    continue
                try:
                    payload, _decompressed, _note = read_archive_entry_data(candidate)
                except Exception:
                    continue
                add_from_text(bytes(payload[:65536]).decode("latin-1", errors="ignore"))

        return tokens

    @staticmethod
    def _attachment_package_weapon_class_label(
        handedness_tokens: set[str],
        subclass_tokens: set[str],
    ) -> str:
        handed = "/".join(sorted(handedness_tokens)) if handedness_tokens else "unknown hand"
        subclass = "/".join(sorted(subclass_tokens)) if subclass_tokens else "unknown weapon"
        return f"{handed} {subclass}"

    def _attachment_package_placement_compatibility(
        self,
        target_entry: ArchiveEntry,
        donor_entry: ArchiveEntry,
        target_graph: AssetFamilyGraph,
        donor_graph: AssetFamilyGraph,
    ) -> dict:
        target_handedness = self._attachment_package_weapon_class_tokens(target_entry, target_graph)
        donor_handedness = self._attachment_package_weapon_class_tokens(donor_entry, donor_graph)
        target_subclasses = self._attachment_package_weapon_subclass_tokens(target_entry, target_graph)
        donor_subclasses = self._attachment_package_weapon_subclass_tokens(donor_entry, donor_graph)
        cross_handedness = bool(
            target_handedness
            and donor_handedness
            and target_handedness.isdisjoint(donor_handedness)
        )
        shared_subclass = target_subclasses & donor_subclasses
        if "sword" in target_subclasses and "sword" in donor_subclasses:
            status = "Known compatible"
            risky = False
        elif target_subclasses and donor_subclasses and not shared_subclass:
            status = "Cross-category risky"
            risky = True
        elif target_subclasses and donor_subclasses:
            status = "Unknown"
            risky = False
        else:
            status = "Unknown"
            risky = False
        return {
            "status": status,
            "risky": risky,
            "cross_handedness": cross_handedness,
            "target_handedness": target_handedness,
            "donor_handedness": donor_handedness,
            "target_subclasses": target_subclasses,
            "donor_subclasses": donor_subclasses,
            "target_label": self._attachment_package_weapon_class_label(target_handedness, target_subclasses),
            "donor_label": self._attachment_package_weapon_class_label(donor_handedness, donor_subclasses),
        }

    def _attachment_package_target_support_entries(
        self,
        target_entry: ArchiveEntry,
        target_graph: AssetFamilyGraph,
    ) -> List[Tuple[str, ArchiveEntry, str]]:
        support_rows: List[Tuple[str, ArchiveEntry, str]] = []
        seen: set[Tuple[str, str, int, str]] = set()
        target_stems: set[str] = set()
        model_extensions = {".pac", ".pam", ".pamlod"}
        material_extensions = {".pac_xml", ".pam_xml", ".pamlod_xml", ".pami"}
        motion_extensions = {".paa", ".paa_metabin", ".motionblending"}

        def add_stem_from_path(raw_path: object) -> None:
            normalized = str(raw_path or "").replace("\\", "/").strip().casefold()
            if not normalized:
                return
            stem = PurePosixPath(normalized).stem.casefold()
            if stem:
                target_stems.add(stem)
                stripped_stem = self._attachment_package_strip_side_suffix(normalized)
                if stripped_stem:
                    target_stems.add(stripped_stem)

        def action_for_entry(candidate: ArchiveEntry) -> Optional[Tuple[str, str]]:
            candidate_path = candidate.path.replace("\\", "/").casefold()
            candidate_name = PurePosixPath(candidate_path).name.casefold()
            extension = str(candidate.extension or "").lower()
            if extension in model_extensions:
                return (
                    "Preserve target PAC/model bytes",
                    "Keeps the visible target model in the package instead of relying on a placement-source file to imply it.",
                )
            if extension in material_extensions or _is_material_sidecar_extension(extension, candidate_name):
                return (
                    "Preserve target material sidecar bytes",
                    "Keeps target material and texture binding context with the model.",
                )
            if extension == ".prefab" and "/prefab/" in candidate_path:
                return (
                    "Preserve target prefab bytes",
                    "Keeps target-owned prefab/socket reference context with the placement package.",
                )
            if extension in {".hkx", ".hkt"} and (
                "/meshphysics/" in candidate_path
                or "/havokphysics/" in candidate_path
                or "physics" in candidate_path
            ):
                return (
                    "Preserve target HKX/HKT physics bytes",
                    "Keeps target-owned physics/collision data with the placement package.",
                )
            if extension == ".dds" and ("itemicon" in candidate_name or "/ui/" in candidate_path):
                return (
                    "Preserve target item icon bytes",
                    "Keeps the target inventory/UI icon with the placement package.",
                )
            if extension in motion_extensions:
                return (
                    "Preserve target PAA/motion bytes",
                    "Keeps target draw/sheath motion context with the weapon class.",
                )
            if extension == ".xml" and candidate_name.endswith(".sockets.xml"):
                return (
                    "Preserve target socket context XML",
                    "Keeps character or target socket context used by the placement chain.",
                )
            return None

        def add_candidate(candidate: Optional[ArchiveEntry]) -> None:
            if not isinstance(candidate, ArchiveEntry):
                return
            decision = action_for_entry(candidate)
            if decision is None:
                return
            action, note = decision
            key = (
                candidate.path.replace("\\", "/").casefold(),
                str(candidate.pamt_path).casefold(),
                int(candidate.offset),
                action.casefold(),
            )
            if key in seen:
                return
            seen.add(key)
            support_rows.append((action, candidate, note))

        graph_entries = self._attachment_package_graph_entries(target_entry, target_graph)
        for candidate in graph_entries:
            add_stem_from_path(getattr(candidate, "path", ""))
            add_candidate(candidate)

        for evidence in tuple(getattr(target_graph, "attachment_evidence", ()) or ()):
            if not isinstance(evidence, AttachmentPlacementEvidence):
                continue
            for candidate_path in (
                evidence.prefab_path,
                evidence.socket_file_path,
                evidence.model_path,
                evidence.skeleton_path,
            ):
                add_stem_from_path(candidate_path)
                add_candidate(self._find_archive_entry_by_virtual_path(str(candidate_path or "")))

        for related_source in graph_entries[:24]:
            try:
                references = build_archive_relationship_references(
                    related_source,
                    archive_entries_by_normalized_path=self.archive_entries_by_normalized_path,
                    archive_entries_by_basename=self.archive_entries_by_basename,
                )
            except Exception:
                references = ()
            for reference in tuple(references or ()):
                add_candidate(getattr(reference, "resolved_entry", None))

        for stem in sorted(target_stems):
            if not stem:
                continue
            for basename in (
                f"{stem}.pac",
                f"{stem}.pam",
                f"{stem}.pamlod",
                f"{stem}.pac_xml",
                f"{stem}.pam_xml",
                f"{stem}.pamlod_xml",
                f"{stem}.pami",
                f"itemicon_prefab_{stem}.dds",
                f"itemicon_{stem}.dds",
                f"icon_prefab_{stem}.dds",
                f"icon_{stem}.dds",
            ):
                for candidate in tuple(self.archive_entries_by_basename.get(basename, ()) or ()):
                    add_candidate(candidate)

        for basename in ("phm_01.pab.sockets.xml", "identityskeleton.pab.sockets.xml"):
            for candidate in tuple(self.archive_entries_by_basename.get(basename, ()) or ()):
                add_candidate(candidate)

        target_class_tokens = self._attachment_package_weapon_class_tokens(target_entry, target_graph)
        if "2H" in target_class_tokens:
            motion_count = 0
            for basename, entries in self.archive_entries_by_basename.items():
                if motion_count >= 32:
                    break
                normalized_basename = str(basename or "").casefold()
                if not normalized_basename.endswith((".paa", ".paa_metabin", ".motionblending")):
                    continue
                if not any(token in normalized_basename for token in ("longsword", "lswd")):
                    continue
                if "weapon_in" not in normalized_basename and "weapon_out" not in normalized_basename:
                    continue
                for candidate in tuple(entries or ()):
                    before_count = len(support_rows)
                    add_candidate(candidate)
                    if len(support_rows) > before_count:
                        motion_count += 1
                        if motion_count >= 32:
                            break

        return support_rows
