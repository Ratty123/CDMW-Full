"""Archive mesh swap support helpers."""
from __future__ import annotations

import re
import threading
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from cdmw.services.archive_query_service import (
    extract_archive_model_sidecar_texture_references as _extract_archive_model_sidecar_texture_references,
    find_archive_model_related_entries as _find_archive_model_related_entries,
    find_archive_model_sidecar_entries as _find_archive_model_sidecar_entries,
    build_archive_model_texture_references,
)
from cdmw.services.archive_workflow_service import _extract_archive_sidecar_texture_lookup_paths
from cdmw.domain.archives.format import is_material_sidecar_extension as _is_material_sidecar_extension
from cdmw.services.archive_preview_service import ensure_archive_preview_source
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.preview_workflow_service import try_decode_text_like_archive_data
from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.archives.filters import archive_entry_identity_key
from cdmw.services.archive_workflow_service import build_archive_relationship_plan, resolve_material_texture_graph
from cdmw.services.texture_workflow_service import normalize_texture_reference_for_sidecar_lookup, parse_material_sidecar_profile
from cdmw.models import ArchiveEntry, ArchiveEntryIdentity
from cdmw.services.mesh_workflow_service import classify_texture_binding
from cdmw.services.mesh_workflow_service import parse_mesh
from cdmw.services.mesh_workflow_service import SceneImportResult
from cdmw.services.mesh_workflow_service import _semantic_tokens
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependencyContext,
    archive_workflow_dependency_context,
)


class ArchiveMeshSwapSupportMixin:
    @staticmethod
    def _archive_entry_identity_key(entry: Optional[ArchiveEntry]) -> ArchiveEntryIdentity | tuple[()]:
        if entry is None:
            return ()
        return archive_entry_identity_key(entry)

    def _same_archive_entry(self, first: Optional[ArchiveEntry], second: Optional[ArchiveEntry]) -> bool:
        return bool(first is not None and second is not None and self._archive_entry_identity_key(first) == self._archive_entry_identity_key(second))

    def _archive_swap_dependencies(
        self,
        entry: ArchiveEntry,
        dependencies: ArchiveWorkflowDependencyContext | None,
    ) -> ArchiveWorkflowDependencyContext:
        if isinstance(dependencies, ArchiveWorkflowDependencyContext):
            return dependencies
        remote_bridge = getattr(self, "archive_remote_bridge", None)
        if remote_bridge is not None and bool(getattr(remote_bridge, "displays_v2", False)):
            return archive_workflow_dependency_context(self, entry)
        return ArchiveWorkflowDependencyContext(
            selected_entry=entry,
            entries=getattr(self, "archive_entries", ()) or (),
            entries_by_normalized_path=getattr(self, "archive_entries_by_normalized_path", {}) or {},
            entries_by_basename=getattr(self, "archive_entries_by_basename", {}) or {},
            remote=False,
        )

    @staticmethod
    def _archive_mesh_source_label(entry: ArchiveEntry) -> str:
        normalized_path = entry.path.replace("\\", "/")
        return f"archive://{normalized_path}"

    @staticmethod
    def _archive_mesh_source_scene_path(entry: ArchiveEntry) -> Path:
        parts = PurePosixPath(entry.path.replace("\\", "/")).parts
        if parts:
            return Path("_in_game_mesh_sources").joinpath(*parts)
        return Path("_in_game_mesh_sources") / entry.basename

    def _load_archive_mesh_scene_import_result(
        self,
        source_entry: ArchiveEntry,
        *,
        stop_event: Optional[threading.Event] = None,
    ) -> SceneImportResult:
        raise_if_cancelled(stop_event, "In-game mesh swap preparation cancelled.")
        data, _decompressed, _note = read_archive_entry_data(source_entry)
        raise_if_cancelled(stop_event, "In-game mesh swap preparation cancelled.")
        source_mesh = parse_mesh(data, source_entry.path)
        raise_if_cancelled(stop_event, "In-game mesh swap preparation cancelled.")
        return SceneImportResult(
            mesh=source_mesh,
            diagnostics=(f"Using in-game archive mesh source: {source_entry.path}",),
        )

    @staticmethod
    def _archive_entry_is_material_sidecar(entry: ArchiveEntry) -> bool:
        extension = str(entry.extension or "").strip().lower()
        basename = PurePosixPath(entry.path.replace("\\", "/")).name.lower()
        return _is_material_sidecar_extension(extension, basename)

    @staticmethod
    def _archive_entry_is_appearance_descriptor(entry: ArchiveEntry) -> bool:
        extension = str(entry.extension or "").strip().lower()
        basename = PurePosixPath(entry.path.replace("\\", "/")).name.lower()
        return extension == ".app_xml" or basename.endswith((".app.xml", ".app_xml"))

    @staticmethod
    def _archive_entry_is_prefab_descriptor(entry: ArchiveEntry) -> bool:
        extension = str(entry.extension or "").strip().lower()
        basename = PurePosixPath(entry.path.replace("\\", "/")).name.lower()
        return extension == ".prefabdata_xml" or basename.endswith((".prefabdata.xml", ".prefabdata_xml"))

    @staticmethod
    def _archive_entry_is_equipment_model_for_swap(entry: ArchiveEntry) -> bool:
        normalized_path = str(getattr(entry, "path", "") or "").replace("\\", "/").strip().lower()
        extension = str(getattr(entry, "extension", "") or "").strip().lower()
        if extension not in ARCHIVE_MESH_EXTENSIONS:
            return False
        return any(
            marker in normalized_path
            for marker in (
                "/weapon/",
                "/shield/",
                "/subweapon/",
                "/onehandweapon/",
                "/twohandweapon/",
                "/bow/",
                "/musket/",
                "/instrument/",
            )
        )

    @staticmethod
    def _archive_entry_is_character_appearance_swap_candidate(entry: ArchiveEntry) -> bool:
        normalized_path = str(getattr(entry, "path", "") or "").replace("\\", "/").strip().lower()
        extension = str(getattr(entry, "extension", "") or "").strip().lower()
        if extension not in ARCHIVE_MESH_EXTENSIONS:
            return False
        if any(marker in normalized_path for marker in ("/weapon/", "/shield/", "/subweapon/", "/object/", "/vehicle/")):
            return False
        if "/character/model/" not in normalized_path:
            return False
        part_markers = {
            "nude",
            "head",
            "hair",
            "beard",
            "armor",
            "underwear",
            "body",
            "face",
        }
        if any(f"/{marker}/" in normalized_path for marker in part_markers):
            return True
        candidate_tokens = _semantic_tokens(PurePosixPath(normalized_path).stem)
        return bool(candidate_tokens & part_markers)

    def _archive_entries_allow_character_swap_scope(self, target_entry: ArchiveEntry, source_entry: ArchiveEntry) -> bool:
        return bool(
            self._archive_entry_is_character_appearance_swap_candidate(target_entry)
            and self._archive_entry_is_character_appearance_swap_candidate(source_entry)
        )

    @staticmethod
    def _archive_entry_swap_companion_group(entry: ArchiveEntry) -> str:
        extension = str(entry.extension or "").strip().lower()
        basename = PurePosixPath(entry.path.replace("\\", "/")).name.lower()
        if _is_material_sidecar_extension(extension, basename):
            return "Material sidecar"
        if extension == ".app_xml" or basename.endswith((".app.xml", ".app_xml")):
            return "Appearance descriptor"
        if extension == ".prefabdata_xml" or basename.endswith((".prefabdata.xml", ".prefabdata_xml")):
            return "Prefab data"
        if extension == ".dds":
            return "Texture"
        if extension in {".pab", ".pabc", ".pabv"}:
            return "Skeleton"
        if extension in {".hkx", ".hkt"}:
            return "Physics"
        if extension in {".paa", ".paa_metabin", ".papr", ".motionblending"}:
            return "Animation"
        if extension == ".paccd":
            return "Customization"
        if extension in ARCHIVE_MESH_EXTENSIONS:
            return "Mesh companion"
        return "Other"

    def _archive_model_related_entries_for_swap(
        self,
        entry: ArchiveEntry,
        *,
        dependencies: ArchiveWorkflowDependencyContext | None = None,
    ) -> Tuple[ArchiveEntry, ...]:
        from cdmw.services.archive_query_service import find_archive_model_related_entries as _find_archive_model_related_entries

        context = self._archive_swap_dependencies(entry, dependencies)
        return _find_archive_model_related_entries(entry, context.entries_by_basename)

    def _archive_model_sidecar_entries_for_swap(
        self,
        entry: ArchiveEntry,
        *,
        dependencies: ArchiveWorkflowDependencyContext | None = None,
    ) -> Tuple[ArchiveEntry, ...]:
        from cdmw.services.archive_query_service import find_archive_model_sidecar_entries as _find_archive_model_sidecar_entries

        context = self._archive_swap_dependencies(entry, dependencies)
        return _find_archive_model_sidecar_entries(entry, context.entries_by_basename)

    def _archive_character_appearance_entries_for_swap(
        self,
        entry: ArchiveEntry,
        *,
        dependencies: ArchiveWorkflowDependencyContext | None = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Tuple[ArchiveEntry, ...]:
        raise_if_cancelled(stop_event, "Character appearance scan cancelled.")
        context = self._archive_swap_dependencies(entry, dependencies)
        normalized_entry_path = str(getattr(entry, "path", "") or "").replace("\\", "/").strip().lower()
        if "/character/" not in normalized_entry_path:
            return ()
        entry_key = self._archive_entry_identity_key(entry)
        result_cache = getattr(self, "archive_character_appearance_swap_cache", {})
        if not context.remote and entry_key in result_cache:
            return tuple(result_cache[entry_key])
        appearance_candidates: List[ArchiveEntry] = []
        seen_candidates: set[ArchiveEntryIdentity] = set()
        if context.remote:
            candidate_groups = (
                tuple(
                    candidate
                    for candidate in context.entries
                    if str(candidate.extension or "").strip().casefold() in {".app_xml", ".xml"}
                ),
            )
        else:
            extension_index = getattr(self, "archive_entries_by_extension", {}) or {}
            if not extension_index and getattr(self, "archive_entries", ()):
                if stop_event is None:
                    self._ensure_archive_basic_index_worker_started()
                return ()
            candidate_groups = tuple(extension_index.get(extension, ()) for extension in (".app_xml", ".xml"))
        for candidates in candidate_groups:
            for candidate in candidates:
                raise_if_cancelled(stop_event, "Character appearance scan cancelled.")
                if not isinstance(candidate, ArchiveEntry) or not self._archive_entry_is_appearance_descriptor(candidate):
                    continue
                candidate_key = self._archive_entry_identity_key(candidate)
                if candidate_key in seen_candidates:
                    continue
                seen_candidates.add(candidate_key)
                appearance_candidates.append(candidate)
        source_stem = PurePosixPath(normalized_entry_path).stem.lower()
        source_tokens = {
            token
            for token in _semantic_tokens(source_stem)
            if token not in {"cd", "pc", "phm", "phw", "ptm", "head", "nude", "armor", "weapon"}
            and not token.isdigit()
        }
        class_tokens = tuple(
            token
            for token in re.findall(r"/1_pc/[^/]+|/2_mon/[^/]+|/3_npc/[^/]+|/4_riding/[^/]+", normalized_entry_path)
            if token
        )
        scored: List[Tuple[int, ArchiveEntry]] = []
        for candidate in appearance_candidates:
            raise_if_cancelled(stop_event, "Character appearance scan cancelled.")
            candidate_path = candidate.path.replace("\\", "/").strip().lower()
            if "/character/appearance/" not in candidate_path:
                continue
            score = 0
            if source_stem and source_stem in candidate_path:
                score += 60
            for token in source_tokens:
                if token and token in candidate_path:
                    score += 20
            for class_token in class_tokens:
                if class_token and class_token in candidate_path:
                    score += 8
            try:
                data, _decompressed, _note = read_archive_entry_data(candidate)
                text = (try_decode_text_like_archive_data(data) or "").lower()
            except Exception:
                raise_if_cancelled(stop_event, "Character appearance scan cancelled.")
                text = ""
            if source_stem and source_stem in text:
                score += 120
            for token in source_tokens:
                if token and token in text:
                    score += 12
            if score > 0:
                scored.append((score, candidate))
        scored.sort(key=lambda item: (item[0], -len(item[1].path)), reverse=True)
        result: List[ArchiveEntry] = []
        seen: set[str] = set()
        for _score, candidate in scored:
            key = self._archive_entry_identity_key(candidate)
            if key and key not in seen:
                result.append(candidate)
                seen.add(key)
            if len(result) >= 8:
                break
        resolved = tuple(result)
        if not context.remote:
            result_cache[entry_key] = resolved
            self.archive_character_appearance_swap_cache = result_cache
        return resolved

    def _archive_character_app_graph_entries_for_swap(
        self,
        entry: ArchiveEntry,
        *,
        dependencies: ArchiveWorkflowDependencyContext | None = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Tuple[ArchiveEntry, ...]:
        context = self._archive_swap_dependencies(entry, dependencies)
        appearance_entries = self._archive_character_appearance_entries_for_swap(
            entry,
            dependencies=context,
            stop_event=stop_event,
        )
        if not appearance_entries:
            return ()
        result: List[ArchiveEntry] = []
        seen: set[str] = set()

        def _add_entry(candidate: Optional[ArchiveEntry]) -> None:
            if not isinstance(candidate, ArchiveEntry):
                return
            key = self._archive_entry_identity_key(candidate)
            if key and key not in seen:
                result.append(candidate)
                seen.add(key)

        for appearance_entry in appearance_entries:
            raise_if_cancelled(stop_event, "Character appearance graph scan cancelled.")
            _add_entry(appearance_entry)
            try:
                relationship_plan = build_archive_relationship_plan(
                    appearance_entry,
                    context.entries,
                    mode="swap_source",
                )
            except Exception:
                raise_if_cancelled(stop_event, "Character appearance graph scan cancelled.")
                continue
            for edge in relationship_plan.edges:
                _add_entry(edge.related_entry)
        return tuple(result[:96])

    def _archive_character_app_graph_texture_entries_for_swap(
        self,
        entry: ArchiveEntry,
        *,
        dependencies: ArchiveWorkflowDependencyContext | None = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Tuple[ArchiveEntry, ...]:
        context = self._archive_swap_dependencies(entry, dependencies)
        graph_entries = self._archive_character_app_graph_entries_for_swap(
            entry,
            dependencies=context,
            stop_event=stop_event,
        )
        if not graph_entries:
            return ()
        texture_entries_by_key: Dict[str, ArchiveEntry] = {}

        def _add_texture(texture_entry: Optional[ArchiveEntry]) -> None:
            if not isinstance(texture_entry, ArchiveEntry):
                return
            if str(getattr(texture_entry, "extension", "") or "").strip().lower() != ".dds":
                return
            key = self._archive_entry_identity_key(texture_entry)
            if key and key not in texture_entries_by_key:
                texture_entries_by_key[key] = texture_entry

        for graph_entry in graph_entries:
            raise_if_cancelled(stop_event, "Character appearance texture graph scan cancelled.")
            try:
                relationship_plan = resolve_material_texture_graph(graph_entry, context.entries)
            except Exception:
                raise_if_cancelled(stop_event, "Character appearance texture graph scan cancelled.")
                relationship_plan = None
            for edge in tuple(getattr(relationship_plan, "edges", ()) or ()):
                _add_texture(edge.related_entry)
        return tuple(texture_entries_by_key.values())

    def _archive_model_source_texture_entries_for_swap(
        self,
        entry: ArchiveEntry,
        *,
        dependencies: ArchiveWorkflowDependencyContext | None = None, stop_event: Optional[threading.Event] = None,
    ) -> Tuple[ArchiveEntry, ...]:
        from cdmw.services.archive_workflow_service import _extract_archive_sidecar_texture_lookup_paths
        raise_if_cancelled(stop_event, "In-game mesh texture scan cancelled.")
        context = self._archive_swap_dependencies(entry, dependencies)
        texture_entries_by_key: "OrderedDict[str, ArchiveEntry]" = OrderedDict()
        texture_entry_scores_by_key: Dict[str, int] = {}
        source_path_text = entry.path.replace("\\", "/").strip().lower()
        source_root = PurePosixPath(source_path_text).parts[0] if PurePosixPath(source_path_text).parts else ""
        source_stem_tokens = _semantic_tokens(PurePosixPath(source_path_text).stem)

        def _source_texture_relevance_score(candidate: ArchiveEntry, referenced_path: str = "") -> int:
            candidate_path = candidate.path.replace("\\", "/").strip().lower()
            candidate_basename = PurePosixPath(candidate_path).name.lower()
            referenced_normalized = normalize_texture_reference_for_sidecar_lookup(referenced_path)
            candidate_normalized = normalize_texture_reference_for_sidecar_lookup(candidate_path)
            score = 0
            if referenced_normalized and candidate_normalized == referenced_normalized:
                score += 100
            candidate_parts = PurePosixPath(candidate_path).parts
            if source_root and candidate_parts and candidate_parts[0] == source_root:
                score += 30
            elif source_root == "character" and candidate_path.startswith("object/"):
                score -= 25
            if "/texture/" in candidate_path:
                score += 6
            candidate_tokens = _semantic_tokens(PurePosixPath(candidate_basename).stem)
            if source_stem_tokens and candidate_tokens:
                score += len(source_stem_tokens & candidate_tokens) * 4
            return score

        def _add_texture(candidate: Optional[ArchiveEntry], *, referenced_path: str = "") -> None:
            if not isinstance(candidate, ArchiveEntry):
                return
            if str(candidate.extension or "").strip().lower() != ".dds":
                return
            key = self._archive_entry_identity_key(candidate)
            if not key:
                return
            score = _source_texture_relevance_score(candidate, referenced_path)
            previous = texture_entries_by_key.get(key)
            if previous is None or score > texture_entry_scores_by_key.get(key, -9999):
                texture_entries_by_key[key] = candidate
                texture_entry_scores_by_key[key] = score

        try:
            relationship_plan = resolve_material_texture_graph(entry, context.entries)
            for edge in relationship_plan.edges:
                raise_if_cancelled(stop_event, "In-game mesh texture scan cancelled.")
                _add_texture(edge.related_entry, referenced_path=edge.related_path)
        except Exception:
            raise_if_cancelled(stop_event, "In-game mesh texture scan cancelled.")
            pass

        try:
            (
                source_sidecar_bindings,
                _source_sidecar_reference_paths,
                source_sidecar_texts_by_path,
                source_sidecar_texts_by_basename,
            ) = _extract_archive_model_sidecar_texture_references(
                entry,
                archive_entries_by_basename=context.entries_by_basename,
            )
            source_texture_references = build_archive_model_texture_references(
                entry,
                None,
                sidecar_texture_references=source_sidecar_bindings,
                texture_entries_by_normalized_path=context.entries_by_normalized_path,
                texture_entries_by_basename=context.entries_by_basename,
                sidecar_texts_by_normalized_path=source_sidecar_texts_by_path,
                sidecar_texts_by_basename=source_sidecar_texts_by_basename,
            )
            for reference in source_texture_references:
                raise_if_cancelled(stop_event, "In-game mesh texture scan cancelled.")
                _add_texture(
                    getattr(reference, "resolved_entry", None),
                    referenced_path=str(getattr(reference, "source_path", "") or getattr(reference, "texture_path", "") or ""),
                )
        except Exception:
            raise_if_cancelled(stop_event, "In-game mesh texture scan cancelled.")
            pass

        # Some sidecars carry plain texture attributes that are not recognized by
        # the material-binding parser yet. Resolve those raw paths directly so the
        # swap scope still exposes the DDS files for manual inclusion.
        for sidecar_entry in self._archive_model_sidecar_entries_for_swap(entry, dependencies=context):
            raise_if_cancelled(stop_event, "In-game mesh texture scan cancelled.")
            try:
                sidecar_data, _decompressed, _note = read_archive_entry_data(sidecar_entry)
                sidecar_text = try_decode_text_like_archive_data(sidecar_data) or ""
            except Exception:
                continue
            for raw_texture_path in _extract_archive_sidecar_texture_lookup_paths(sidecar_text):
                normalized_path = normalize_texture_reference_for_sidecar_lookup(raw_texture_path)
                if normalized_path:
                    for candidate in context.entries_by_normalized_path.get(normalized_path, ()):
                        _add_texture(candidate, referenced_path=raw_texture_path)
                basename = PurePosixPath(str(raw_texture_path or "").replace("\\", "/")).name.lower()
                if basename:
                    for candidate in context.entries_by_basename.get(basename, ()):
                        _add_texture(candidate, referenced_path=raw_texture_path)

        return tuple(texture_entries_by_key.values())

    def _build_archive_swap_source_texture_evidence(
        self,
        source_entry: ArchiveEntry,
        *,
        dependencies: ArchiveWorkflowDependencyContext | None = None, stop_event: Optional[threading.Event] = None,
    ) -> Tuple[Tuple[Path, ...], Tuple[Mapping[str, object], ...]]:
        """Expose source-side DDS/sidecar evidence to Mesh Replacement Alignment suggestions."""

        raise_if_cancelled(stop_event, "In-game mesh texture evidence cancelled.")
        context = self._archive_swap_dependencies(source_entry, dependencies)
        texture_entries = self._archive_model_source_texture_entries_for_swap(source_entry, dependencies=context, stop_event=stop_event)
        if not texture_entries:
            return (), ()
        bindings: Tuple[object, ...] = ()
        try:
            bindings, _paths, _texts_by_path, _texts_by_basename = _extract_archive_model_sidecar_texture_references(
                source_entry,
                archive_entries_by_basename=context.entries_by_basename,
            )
        except Exception:
            bindings = ()
        bindings_by_normalized_path: Dict[str, List[object]] = {}
        bindings_by_basename: Dict[str, List[object]] = {}
        for binding in bindings:
            raise_if_cancelled(stop_event, "In-game mesh texture evidence cancelled.")
            texture_path = str(getattr(binding, "texture_path", "") or "").replace("\\", "/").strip()
            normalized = normalize_texture_reference_for_sidecar_lookup(texture_path)
            if normalized:
                bindings_by_normalized_path.setdefault(normalized, []).append(binding)
            basename = PurePosixPath(texture_path).name.lower()
            if basename:
                bindings_by_basename.setdefault(basename, []).append(binding)
        profile_records_by_normalized_path: Dict[str, List[Tuple[object, object, object]]] = {}
        profile_records_by_basename: Dict[str, List[Tuple[object, object, object]]] = {}
        source_sidecar_entries = tuple(self._archive_model_sidecar_entries_for_swap(source_entry, dependencies=context))
        for sidecar_entry in source_sidecar_entries:
            raise_if_cancelled(stop_event, "In-game mesh texture evidence cancelled.")
            try:
                sidecar_data, _decompressed, _note = read_archive_entry_data(sidecar_entry)
                sidecar_text = try_decode_text_like_archive_data(sidecar_data) or ""
                profile = parse_material_sidecar_profile(sidecar_text, sidecar_path=sidecar_entry.path)
            except Exception:
                continue
            for material in tuple(getattr(profile, "materials", ()) or ()):
                for parameter in tuple(getattr(material, "texture_parameters", ()) or ()):
                    texture_path = str(getattr(parameter, "texture_path", "") or "").replace("\\", "/").strip()
                    normalized = normalize_texture_reference_for_sidecar_lookup(texture_path)
                    if normalized:
                        profile_records_by_normalized_path.setdefault(normalized, []).append((profile, material, parameter))
                    basename = PurePosixPath(texture_path).name.lower()
                    if basename:
                        profile_records_by_basename.setdefault(basename, []).append((profile, material, parameter))

        def _profile_records_for(archive_path: str, binding: Optional[object] = None) -> Tuple[Tuple[object, object, object], ...]:
            candidates: List[Tuple[object, object, object]] = []
            for value in (
                str(getattr(binding, "texture_path", "") or "") if binding is not None else "",
                archive_path,
            ):
                normalized = normalize_texture_reference_for_sidecar_lookup(value)
                if normalized:
                    candidates.extend(profile_records_by_normalized_path.get(normalized, ()))
                basename = PurePosixPath(str(value or "").replace("\\", "/")).name.lower()
                if basename:
                    candidates.extend(profile_records_by_basename.get(basename, ()))
            if not candidates:
                return ()
            parameter_name = str(getattr(binding, "parameter_name", "") or "").strip().lower() if binding is not None else ""
            part_name = str(getattr(binding, "part_name", "") or getattr(binding, "submesh_name", "") or "").strip().lower() if binding is not None else ""
            seen: set[Tuple[str, str, str]] = set()
            scored: List[Tuple[int, Tuple[object, object, object]]] = []
            for record in candidates:
                _profile, material, parameter = record
                key = (
                    str(getattr(material, "part_name", "") or "").lower(),
                    str(getattr(parameter, "parameter_name", "") or "").lower(),
                    str(getattr(parameter, "texture_path", "") or "").lower(),
                )
                if key in seen:
                    continue
                seen.add(key)
                score = 0
                if parameter_name and str(getattr(parameter, "parameter_name", "") or "").strip().lower() == parameter_name:
                    score += 10
                material_part = str(getattr(material, "part_name", "") or "").strip().lower()
                if part_name and material_part and (part_name in material_part or material_part in part_name):
                    score += 6
                scored.append((score, record))
            scored.sort(key=lambda item: item[0], reverse=True)
            return tuple(record for _score, record in scored[:4])

        def _material_profile_evidence_fields(records: Sequence[Tuple[object, object, object]]) -> Dict[str, object]:
            if not records:
                return {}
            _profile, material, parameter = records[0]
            render_flag = str(getattr(material, "parameter_value", lambda _name: "")("_renderSettingFlag") or "")
            color_flag = str(getattr(material, "parameter_value", lambda _name: "")("_colorBlendingFlag") or "")
            color_names = tuple(
                str(getattr(color, "parameter_name", "") or "")
                for color in tuple(getattr(material, "color_parameters", ()) or ())[:8]
                if str(getattr(color, "parameter_name", "") or "")
            )
            float_names = tuple(
                str(getattr(value, "parameter_name", "") or "")
                for value in tuple(getattr(material, "float_parameters", ()) or ())[:8]
                if str(getattr(value, "parameter_name", "") or "")
            )
            flag_parts = []
            if render_flag:
                flag_parts.append(f"render={render_flag}")
            if color_flag:
                flag_parts.append(f"colorBlend={color_flag}")
            shader_family = str(getattr(material, "shader_family", "") or "")
            part_name = str(getattr(material, "part_name", "") or "")
            parameter_name = str(getattr(parameter, "parameter_name", "") or "")
            profile_label = " | ".join(value for value in (part_name, shader_family, parameter_name) if value)
            return {
                "material_profile_label": profile_label,
                "material_profile_part": part_name,
                "material_profile_shader": shader_family,
                "material_profile_parameter": parameter_name,
                "material_profile_index": int(getattr(parameter, "index", -1) or -1),
                "material_profile_flags": "; ".join(flag_parts),
                "material_profile_colors": ", ".join(color_names),
                "material_profile_floats": ", ".join(float_names),
                "material_profile_emissive": bool(getattr(material, "is_emissive", False)),
                "material_profile_visible_textures": int(getattr(material, "visible_texture_count", 0) or 0),
            }

        supplemental_paths: List[Path] = []
        evidence_rows: List[Mapping[str, object]] = []
        seen_local_paths: set[str] = set()
        for texture_entry in texture_entries:
            raise_if_cancelled(stop_event, "In-game mesh texture evidence cancelled.")
            try:
                local_path, _note = ensure_archive_preview_source(texture_entry)
                local_path = local_path.expanduser().resolve()
            except Exception:
                continue
            local_key = str(local_path).lower()
            if local_key in seen_local_paths:
                continue
            seen_local_paths.add(local_key)
            supplemental_paths.append(local_path)
            archive_path = texture_entry.path.replace("\\", "/").strip()
            matched_bindings: List[object] = []
            normalized_archive_path = normalize_texture_reference_for_sidecar_lookup(archive_path)
            if normalized_archive_path:
                matched_bindings.extend(bindings_by_normalized_path.get(normalized_archive_path, ()))
            matched_bindings.extend(bindings_by_basename.get(PurePosixPath(archive_path).name.lower(), ()))
            if matched_bindings:
                for binding in matched_bindings:
                    profile_records = _profile_records_for(archive_path, binding)
                    classification = classify_texture_binding(
                        str(getattr(binding, "parameter_name", "") or ""),
                        str(getattr(binding, "texture_path", "") or "") or archive_path,
                    )
                    row = {
                            "local_path": str(local_path),
                            "archive_path": archive_path,
                            "parameter_name": str(getattr(binding, "parameter_name", "") or ""),
                            "texture_path": str(getattr(binding, "texture_path", "") or archive_path),
                            "part_name": str(getattr(binding, "part_name", "") or ""),
                            "submesh_name": str(getattr(binding, "submesh_name", "") or ""),
                            "shader_family": str(getattr(binding, "shader_family", "") or ""),
                            "slot_kind": str(getattr(classification, "slot_kind", "") or ""),
                            "semantic_subtype": str(getattr(classification, "semantic_subtype", "") or ""),
                    }
                    row.update(_material_profile_evidence_fields(profile_records))
                    evidence_rows.append(row)
            else:
                profile_records = _profile_records_for(archive_path)
                classification = classify_texture_binding("", archive_path)
                row = {
                        "local_path": str(local_path),
                        "archive_path": archive_path,
                        "parameter_name": "",
                        "texture_path": archive_path,
                        "part_name": "",
                        "submesh_name": "",
                        "shader_family": "",
                        "slot_kind": str(getattr(classification, "slot_kind", "") or ""),
                        "semantic_subtype": str(getattr(classification, "semantic_subtype", "") or ""),
                }
                row.update(_material_profile_evidence_fields(profile_records))
                evidence_rows.append(row)
        return tuple(supplemental_paths), tuple(evidence_rows)

    def _target_sidecar_path_for_source_sidecar(
        self,
        target_entry: ArchiveEntry,
        source_sidecar_entry: ArchiveEntry,
        *,
        dependencies: ArchiveWorkflowDependencyContext | None = None,
    ) -> Tuple[str, Optional[ArchiveEntry]]:
        target_sidecars = list(
            self._archive_model_sidecar_entries_for_swap(
                target_entry,
                dependencies=dependencies,
            )
        )
        source_extension = str(source_sidecar_entry.extension or "").strip().lower()
        for target_sidecar in target_sidecars:
            if str(target_sidecar.extension or "").strip().lower() == source_extension:
                return target_sidecar.path, target_sidecar
        if target_sidecars:
            return target_sidecars[0].path, target_sidecars[0]
        target_path = target_entry.path.replace("\\", "/").strip()
        target_stem = PurePosixPath(target_path).with_suffix("").as_posix()
        if target_entry.extension == ".pac":
            return f"{target_stem}.pac_xml", None
        if target_entry.extension == ".pam":
            return f"{target_stem}.pami", None
        if target_entry.extension == ".pamlod":
            return f"{target_stem}.pamlod_xml", None
        return f"{target_stem}.xml", None

    def _target_appearance_path_for_source_appearance(
        self,
        target_entry: ArchiveEntry,
        source_appearance_entry: ArchiveEntry,
        *,
        dependencies: ArchiveWorkflowDependencyContext | None = None,
    ) -> Tuple[str, Optional[ArchiveEntry]]:
        target_appearances = list(
            self._archive_character_appearance_entries_for_swap(
                target_entry,
                dependencies=dependencies,
            )
        )
        if not target_appearances:
            return "", None
        source_basename = PurePosixPath(source_appearance_entry.path.replace("\\", "/")).name.lower()
        source_variant_match = re.search(r"_(\d{5})\.app", source_basename)
        source_variant = source_variant_match.group(1) if source_variant_match else ""
        if source_variant:
            for target_appearance in target_appearances:
                target_basename = PurePosixPath(target_appearance.path.replace("\\", "/")).name.lower()
                if f"_{source_variant}.app" in target_basename:
                    return target_appearance.path, target_appearance
        return target_appearances[0].path, target_appearances[0]

    def _target_family_path_for_source_companion(
        self,
        target_entry: ArchiveEntry,
        source_entry: ArchiveEntry,
        source_companion: ArchiveEntry,
        *,
        dependencies: ArchiveWorkflowDependencyContext | None = None,
    ) -> Tuple[str, Optional[ArchiveEntry]]:
        if self._same_archive_entry(source_entry, source_companion):
            return target_entry.path.replace("\\", "/"), target_entry
        if self._archive_entry_is_material_sidecar(source_companion):
            return self._target_sidecar_path_for_source_sidecar(
                target_entry,
                source_companion,
                dependencies=dependencies,
            )
        if self._archive_entry_is_appearance_descriptor(source_companion):
            return self._target_appearance_path_for_source_appearance(
                target_entry,
                source_companion,
                dependencies=dependencies,
            )
        if str(source_companion.extension or "").strip().lower() == ".dds":
            # Source sidecars still point at source texture archive paths, so DDS files stay at source paths.
            return source_companion.path.replace("\\", "/"), source_companion

        source_path = source_companion.path.replace("\\", "/").strip()
        source_entry_path = source_entry.path.replace("\\", "/").strip()
        target_entry_path = target_entry.path.replace("\\", "/").strip()
        source_stem = PurePosixPath(source_entry_path).stem
        target_stem = PurePosixPath(target_entry_path).stem
        source_suffix = PurePosixPath(source_path).suffix
        source_companion_stem = PurePosixPath(source_path).stem
        target_related_entries = tuple(
            self._archive_model_related_entries_for_swap(
                target_entry,
                dependencies=dependencies,
            )
        )
        target_group = self._archive_entry_swap_companion_group(source_companion)
        source_tail = ""
        if source_stem and source_companion_stem.lower().startswith(source_stem.lower()):
            source_tail = source_companion_stem[len(source_stem):]
        expected_names: set[str] = set()
        if target_stem:
            expected_names.add(f"{target_stem}{source_tail}{source_suffix}".lower())
            if source_suffix.lower() == ".xml":
                expected_names.add(f"{target_stem}{source_tail}.xml".lower())
        for candidate in target_related_entries:
            if self._archive_entry_swap_companion_group(candidate) != target_group:
                continue
            candidate_name = PurePosixPath(candidate.path.replace("\\", "/")).name.lower()
            if candidate_name in expected_names:
                return candidate.path.replace("\\", "/"), candidate
        source_parts = list(PurePosixPath(source_path).parts)
        source_entry_parts = list(PurePosixPath(source_entry_path).parts)
        target_entry_parts = list(PurePosixPath(target_entry_path).parts)
        source_family_segment = ""
        target_family_segment = ""
        if source_entry_parts and target_entry_parts:
            for index, part in enumerate(source_parts):
                if index < len(source_entry_parts) and index < len(target_entry_parts) and part == source_entry_parts[index]:
                    source_parts[index] = target_entry_parts[index]
            try:
                source_weapon_index = [part.lower() for part in source_entry_parts].index("weapon")
                target_weapon_index = [part.lower() for part in target_entry_parts].index("weapon")
                source_family_segment = source_entry_parts[source_weapon_index + 1]
                target_family_segment = target_entry_parts[target_weapon_index + 1]
            except (ValueError, IndexError):
                source_family_segment = ""
                target_family_segment = ""
            if source_family_segment and target_family_segment:
                def _retarget_family_segment(part: str) -> str:
                    part_text = str(part or "")
                    part_key = part_text.lower()
                    source_key = source_family_segment.lower()
                    if part_key == source_key:
                        return target_family_segment
                    stripped_part_key = part_key.lstrip("0")
                    stripped_source_key = source_key.lstrip("0")
                    if stripped_part_key == stripped_source_key and stripped_source_key:
                        leading_zero_count = len(part_text) - len(part_text.lstrip("0"))
                        if leading_zero_count > 0 and target_family_segment[:1].isdigit():
                            return ("0" * leading_zero_count) + target_family_segment
                        return target_family_segment
                    return part_text

                source_parts = [_retarget_family_segment(part) for part in source_parts]
        filename = source_parts[-1] if source_parts else PurePosixPath(source_path).name
        if source_stem and target_stem:
            filename = re.sub(re.escape(source_stem), target_stem, filename, count=1, flags=re.IGNORECASE)
            if source_parts:
                source_parts[-1] = filename
        guessed_path = PurePosixPath(*source_parts).as_posix() if source_parts else filename
        target_candidate = self._find_archive_entry_by_virtual_path(guessed_path)
        return guessed_path, target_candidate
