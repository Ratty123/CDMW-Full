"""Archive browser attachment visual socket-context helpers."""

from __future__ import annotations

import dataclasses
import math
import os
import re
import threading
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.services.archive_workflow_service import parse_socket_bone_data_xml
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.cancellable_file_service import read_file_bytes_cancellable
from cdmw.domain.xml_text import decode_xml_text_payload
from cdmw.services.mesh_workflow_service import parse_pab
from cdmw.models import (
    ArchiveEntry,
    AssetFamilyGraph,
    AttachmentPlacementEvidence,
    AttachmentSocketDocument,
    AttachmentSocketInfo,
)
from cdmw.ui.archive_browser.attachment_visual_core import ArchiveAttachmentVisualCoreMixin


class ArchiveAttachmentVisualContextMixin(ArchiveAttachmentVisualCoreMixin):
    @staticmethod
    def _attachment_visual_lookup_named_vector(
        values: Optional[Mapping[str, Tuple[float, float, float]]],
        name: str,
    ) -> Optional[Tuple[float, float, float]]:
        if not isinstance(values, Mapping):
            return None
        key = str(name or "").strip().casefold()
        if not key:
            return None
        value = values.get(key)
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return __class__._attachment_visual_finite_vector3(value)
        return None

    @staticmethod
    def _attachment_visual_lookup_named_matrix(
        values: Optional[Mapping[str, Tuple[float, ...]]],
        name: str,
    ) -> Optional[Tuple[float, ...]]:
        if not isinstance(values, Mapping):
            return None
        key = str(name or "").strip().casefold()
        if not key:
            return None
        value = values.get(key)
        if isinstance(value, (list, tuple)) and len(value) >= 16:
            try:
                matrix = tuple(float(component) for component in tuple(value)[:16])
            except (TypeError, ValueError, OverflowError):
                return None
            if all(math.isfinite(component) for component in matrix):
                return matrix
        return None

    @staticmethod
    def _attachment_visual_transform_bone_vector(
        matrix: Optional[Sequence[float]],
        vector: Sequence[object],
    ) -> Tuple[float, float, float]:
        x, y, z = __class__._attachment_visual_finite_vector3(vector)
        if not isinstance(matrix, (list, tuple)) or len(matrix) < 16:
            return (x, y, z)
        try:
            values = tuple(float(component) for component in tuple(matrix)[:16])
        except (TypeError, ValueError, OverflowError):
            return (x, y, z)
        if not all(math.isfinite(component) for component in values):
            return (x, y, z)
        return (
            (x * values[0]) + (y * values[4]) + (z * values[8]),
            (x * values[1]) + (y * values[5]) + (z * values[9]),
            (x * values[2]) + (y * values[6]) + (z * values[10]),
        )

    @staticmethod
    def _attachment_visual_socket_world_position(
        socket: Optional[AttachmentSocketInfo],
        context: Optional[Mapping[str, object]],
    ) -> Optional[Tuple[float, float, float]]:
        if not isinstance(socket, AttachmentSocketInfo) or not isinstance(context, Mapping):
            return None
        bone_positions = context.get("bone_positions")
        bone_matrices = context.get("bone_matrices")
        parent_name = str(socket.parent or "").strip()
        parent_position = __class__._attachment_visual_lookup_named_vector(bone_positions, parent_name)
        if parent_position is None:
            return None
        matrix = __class__._attachment_visual_lookup_named_matrix(bone_matrices, parent_name)
        translated = __class__._attachment_visual_transform_bone_vector(matrix, socket.translation)
        return (
            parent_position[0] + translated[0],
            parent_position[1] + translated[1],
            parent_position[2] + translated[2],
        )

    def _attachment_visual_socket_evidence_roots(
        self,
        extra_roots: Sequence[object] = (),
    ) -> List[Path]:
        roots: List[Path] = []
        seen: set[str] = set()

        def add_root(raw: object) -> None:
            if raw is None:
                return
            try:
                path = Path(str(raw)).expanduser().resolve()
            except OSError:
                return
            key = str(path).casefold()
            if key in seen or not path.exists():
                return
            seen.add(key)
            roots.append(path)

        for root in self._collect_archive_preview_loose_roots():
            add_root(root)
        for raw_root in tuple(extra_roots or ()):
            add_root(raw_root)
        env_roots = os.environ.get("CDMW_SOCKET_EVIDENCE_ROOTS", "")
        for raw_root in re.split(r"[;|]", env_roots):
            if raw_root.strip():
                add_root(raw_root.strip())
        return roots

    def _attachment_visual_find_loose_evidence_path(
        self,
        virtual_path: str,
        *,
        extra_roots: Sequence[object] = (),
    ) -> Optional[Path]:
        normalized = str(virtual_path or "").replace("\\", "/").strip().lstrip("/")
        if not normalized:
            return None
        basename = PurePosixPath(normalized).name
        relative_candidates = []
        for candidate in (
            normalized,
            f"files/{normalized}",
            basename,
            f"files/{basename}",
            f"character/{basename}",
            f"files/character/{basename}",
        ):
            candidate = candidate.replace("\\", "/").strip().lstrip("/")
            if candidate and candidate not in relative_candidates:
                relative_candidates.append(candidate)
        for root in self._attachment_visual_socket_evidence_roots(extra_roots):
            for relative in relative_candidates:
                path = root.joinpath(*PurePosixPath(relative).parts)
                if path.is_file():
                    return path
            try:
                package_dirs = [
                    child
                    for child in root.iterdir()
                    if child.is_dir() and re.match(r"^\d{3,5}$", child.name)
                ]
            except OSError:
                package_dirs = []
            for package_dir in package_dirs:
                for relative in relative_candidates:
                    path = package_dir.joinpath(*PurePosixPath(relative).parts)
                    if path.is_file():
                        return path
        return None

    def _attachment_visual_find_archive_entry_by_path_or_basename(self, virtual_path: str) -> Optional[ArchiveEntry]:
        normalized = str(virtual_path or "").replace("\\", "/").strip().lower()
        if not normalized:
            return None
        direct = self._find_archive_entry_by_virtual_path(normalized)
        if isinstance(direct, ArchiveEntry):
            return direct
        basename = PurePosixPath(normalized).name.lower()
        for candidate in tuple(self.archive_entries_by_basename.get(basename, ()) or ()):
            if isinstance(candidate, ArchiveEntry):
                return candidate
        return None

    def _attachment_visual_socket_document_from_path(
        self,
        virtual_path: str,
        *,
        preferred_entry: Optional[ArchiveEntry] = None,
        extra_roots: Sequence[object] = (),
        stop_event: threading.Event | None = None,
    ) -> Optional[AttachmentSocketDocument]:
        raise_if_cancelled(stop_event, "Attachment socket resolution cancelled.")
        entry = preferred_entry if isinstance(preferred_entry, ArchiveEntry) else None
        if entry is None:
            entry = self._attachment_visual_find_archive_entry_by_path_or_basename(virtual_path)
        if isinstance(entry, ArchiveEntry):
            try:
                data, _decompressed, _note = read_archive_entry_data(entry)
                raise_if_cancelled(stop_event, "Attachment socket resolution cancelled.")
                document = parse_socket_bone_data_xml(decode_xml_text_payload(data).text, source_path=entry.path)
            except Exception:
                document = None
            raise_if_cancelled(stop_event, "Attachment socket resolution cancelled.")
            if isinstance(document, AttachmentSocketDocument) and (document.sockets or document.stack_equip_infos):
                return document
        loose_path = self._attachment_visual_find_loose_evidence_path(virtual_path, extra_roots=extra_roots)
        if loose_path is None:
            return None
        try:
            document = parse_socket_bone_data_xml(
                decode_xml_text_payload(
                    read_file_bytes_cancellable(loose_path, stop_event=stop_event)
                ).text,
                source_path=str(loose_path),
            )
            raise_if_cancelled(stop_event, "Attachment socket resolution cancelled.")
        except Exception:
            raise_if_cancelled(stop_event, "Attachment socket resolution cancelled.")
            return None
        return document if document.sockets or document.stack_equip_infos else None

    @staticmethod
    def _attachment_visual_model_skeleton_path_candidates(path_text: str) -> Tuple[str, ...]:
        normalized = str(path_text or "").replace("\\", "/").strip()
        if not normalized:
            return ()
        parts = PurePosixPath(normalized).parts
        candidates: List[str] = []
        for index, part in enumerate(parts):
            match = re.match(r"^(\d+)_([a-z0-9]+)$", part, re.IGNORECASE)
            if not match:
                continue
            number_text, token = match.groups()
            try:
                number = int(number_text)
            except ValueError:
                number = 1
            if index + 1 > len(parts):
                continue
            skeleton_name = f"{token.lower()}_{number:02d}.pab"
            candidate = "/".join((*parts[: index + 1], skeleton_name))
            if candidate not in candidates:
                candidates.append(candidate)
        return tuple(candidates)

    def _attachment_visual_candidate_skeleton_paths(
        self,
        graph: Optional[AssetFamilyGraph],
        evidence: Optional[AttachmentPlacementEvidence],
        model_entry: Optional[ArchiveEntry],
    ) -> Tuple[str, ...]:
        candidates: List[str] = []

        def add(path_text: object) -> None:
            normalized = str(path_text or "").replace("\\", "/").strip()
            if normalized and normalized.lower() not in {candidate.lower() for candidate in candidates}:
                candidates.append(normalized)

        if isinstance(evidence, AttachmentPlacementEvidence):
            add(evidence.skeleton_path)
            for candidate in self._attachment_visual_model_skeleton_path_candidates(evidence.model_path):
                add(candidate)
        if isinstance(model_entry, ArchiveEntry):
            for candidate in self._attachment_visual_model_skeleton_path_candidates(model_entry.path):
                add(candidate)
        if isinstance(graph, AssetFamilyGraph):
            for member in tuple(getattr(graph, "member_rows", ()) or ()):
                entry = getattr(member, "resolved_entry", None)
                if isinstance(entry, ArchiveEntry) and str(entry.extension or "").lower() == ".pab":
                    add(entry.path)
        add("character/model/1_pc/1_phm/phm_01.pab")
        add("character/identityskeleton.pab")
        return tuple(candidates)

    @staticmethod
    def _attachment_visual_bone_position_from_matrix_or_local(bone: object) -> Tuple[float, float, float]:
        fallback = __class__._attachment_visual_finite_vector3(getattr(bone, "position", ()))
        matrix = tuple(getattr(bone, "bind_matrix", ()) or ())
        if len(matrix) < 16:
            return fallback
        row = __class__._attachment_visual_finite_vector3((matrix[12], matrix[13], matrix[14]))
        column = __class__._attachment_visual_finite_vector3((matrix[3], matrix[7], matrix[11]))
        row_score = sum(abs(component) for component in row)
        column_score = sum(abs(component) for component in column)
        chosen = row if row_score >= column_score else column
        if any(abs(component) > 50.0 for component in chosen):
            return fallback
        return chosen

    @staticmethod
    def _attachment_visual_build_skeleton_context(skeleton: object, source_path: str) -> Optional[Dict[str, object]]:
        bones = tuple(getattr(skeleton, "bones", ()) or ())
        if len(bones) <= 1:
            return None
        bone_positions: Dict[str, Tuple[float, float, float]] = {}
        bone_matrices: Dict[str, Tuple[float, ...]] = {}
        parent_names: Dict[str, str] = {}
        for bone in bones:
            name = str(getattr(bone, "name", "") or "").strip()
            if not name:
                continue
            key = name.casefold()
            bone_positions[key] = __class__._attachment_visual_bone_position_from_matrix_or_local(bone)
            matrix = tuple(getattr(bone, "bind_matrix", ()) or ())
            if len(matrix) >= 16:
                try:
                    bone_matrices[key] = tuple(float(component) for component in matrix[:16])
                except (TypeError, ValueError, OverflowError):
                    pass
            parent_index = int(getattr(bone, "parent_index", -1) or -1)
            if 0 <= parent_index < len(bones):
                parent_name = str(getattr(bones[parent_index], "name", "") or "").strip()
                if parent_name:
                    parent_names[key] = parent_name
        if len(bone_positions) <= 1:
            return None
        return {
            "bone_positions": bone_positions,
            "bone_matrices": bone_matrices,
            "bone_parent_names": parent_names,
            "skeleton_source_path": source_path,
            "skeleton_bone_count": len(bone_positions),
        }

    def _attachment_visual_skeleton_context(
        self,
        graph: Optional[AssetFamilyGraph],
        evidence: Optional[AttachmentPlacementEvidence],
        model_entry: Optional[ArchiveEntry],
        *,
        extra_roots: Sequence[object] = (),
        stop_event: threading.Event | None = None,
    ) -> Dict[str, object]:
        best_context: Dict[str, object] = {}
        best_count = 0
        for candidate_path in self._attachment_visual_candidate_skeleton_paths(graph, evidence, model_entry):
            raise_if_cancelled(stop_event, "Attachment skeleton resolution cancelled.")
            payload: Optional[bytes] = None
            source_path = candidate_path
            entry = self._attachment_visual_find_archive_entry_by_path_or_basename(candidate_path)
            if isinstance(entry, ArchiveEntry):
                try:
                    payload, _decompressed, _note = read_archive_entry_data(entry)
                    source_path = entry.path
                except Exception:
                    payload = None
                raise_if_cancelled(stop_event, "Attachment skeleton resolution cancelled.")
            if payload is None:
                loose_path = self._attachment_visual_find_loose_evidence_path(candidate_path, extra_roots=extra_roots)
                if loose_path is not None:
                    try:
                        payload = read_file_bytes_cancellable(loose_path, stop_event=stop_event)
                        source_path = str(loose_path)
                    except Exception:
                        payload = None
                    raise_if_cancelled(stop_event, "Attachment skeleton resolution cancelled.")
            if not payload:
                continue
            try:
                skeleton = parse_pab(payload, source_path)
                context = self._attachment_visual_build_skeleton_context(skeleton, source_path)
            except Exception:
                context = None
            raise_if_cancelled(stop_event, "Attachment skeleton resolution cancelled.")
            count = int(context.get("skeleton_bone_count", 0) or 0) if isinstance(context, Mapping) else 0
            if isinstance(context, dict) and count > best_count:
                best_context = context
                best_count = count
        return best_context

    def _attachment_visual_character_socket_document(
        self,
        graph: Optional[AssetFamilyGraph],
        evidence: Optional[AttachmentPlacementEvidence],
        model_entry: Optional[ArchiveEntry],
        skeleton_context: Optional[Mapping[str, object]],
        *,
        extra_roots: Sequence[object] = (),
        stop_event: threading.Event | None = None,
    ) -> Optional[AttachmentSocketDocument]:
        candidates: List[str] = []

        def add(path_text: object) -> None:
            normalized = str(path_text or "").replace("\\", "/").strip()
            if normalized and normalized.lower() not in {candidate.lower() for candidate in candidates}:
                candidates.append(normalized)

        skeleton_source = str((skeleton_context or {}).get("skeleton_source_path", "") or "")
        for path_text in (
            skeleton_source,
            getattr(evidence, "skeleton_path", "") if isinstance(evidence, AttachmentPlacementEvidence) else "",
        ):
            normalized = str(path_text or "").replace("\\", "/").strip()
            if not normalized:
                continue
            basename = PurePosixPath(normalized).name
            add(f"{normalized}.sockets.xml")
            add(f"{basename}.sockets.xml")
            add(f"character/{basename}.sockets.xml")
        if isinstance(evidence, AttachmentPlacementEvidence):
            for candidate in self._attachment_visual_model_skeleton_path_candidates(evidence.model_path):
                basename = PurePosixPath(candidate).name
                add(f"{candidate}.sockets.xml")
                add(f"{basename}.sockets.xml")
                add(f"character/{basename}.sockets.xml")
        if isinstance(model_entry, ArchiveEntry):
            for candidate in self._attachment_visual_model_skeleton_path_candidates(model_entry.path):
                basename = PurePosixPath(candidate).name
                add(f"{candidate}.sockets.xml")
                add(f"{basename}.sockets.xml")
                add(f"character/{basename}.sockets.xml")
        add("phm_01.pab.sockets.xml")
        add("character/phm_01.pab.sockets.xml")
        for candidate in candidates:
            raise_if_cancelled(stop_event, "Attachment socket resolution cancelled.")
            document = self._attachment_visual_socket_document_from_path(
                candidate,
                extra_roots=extra_roots,
                stop_event=stop_event,
            )
            if isinstance(document, AttachmentSocketDocument):
                return document
        return None

    def _attachment_visual_resolve_context(
        self,
        graph: Optional[AssetFamilyGraph],
        evidence: Optional[AttachmentPlacementEvidence],
        model_entry: Optional[ArchiveEntry],
        *,
        socket_entry: Optional[ArchiveEntry] = None,
        extra_roots: Sequence[object] = (),
        stop_event: threading.Event | None = None,
    ) -> Dict[str, object]:
        context = self._attachment_visual_skeleton_context(
            graph,
            evidence,
            model_entry,
            extra_roots=extra_roots,
            stop_event=stop_event,
        )
        character_document = self._attachment_visual_character_socket_document(
            graph,
            evidence,
            model_entry,
            context,
            extra_roots=extra_roots,
            stop_event=stop_event,
        )
        weapon_document = None
        if isinstance(evidence, AttachmentPlacementEvidence):
            weapon_document = self._attachment_visual_socket_document_from_path(
                evidence.socket_file_path,
                preferred_entry=socket_entry,
                extra_roots=extra_roots,
                stop_event=stop_event,
            )
        character_socket = self._attachment_visual_find_socket_info(
            character_document,
            getattr(evidence, "character_socket_name", "") if isinstance(evidence, AttachmentPlacementEvidence) else "",
        )
        weapon_socket = self._attachment_visual_find_socket_info(
            weapon_document,
            getattr(evidence, "weapon_socket_name", "") if isinstance(evidence, AttachmentPlacementEvidence) else "",
        )
        if isinstance(character_document, AttachmentSocketDocument):
            context["character_socket_document"] = character_document
        if isinstance(weapon_document, AttachmentSocketDocument):
            context["weapon_socket_document"] = weapon_document
        if isinstance(character_socket, AttachmentSocketInfo):
            context["character_socket_info"] = character_socket
            anchor = self._attachment_visual_socket_world_position(character_socket, context)
            if anchor is not None:
                context["character_anchor"] = anchor
        if isinstance(weapon_socket, AttachmentSocketInfo):
            context["weapon_socket_info"] = weapon_socket
        sources: List[str] = []
        if context.get("skeleton_source_path"):
            sources.append(f"PAB skeleton: {context.get('skeleton_source_path')}")
        if isinstance(character_document, AttachmentSocketDocument):
            sources.append(f"character sockets: {character_document.source_path}")
        if isinstance(weapon_document, AttachmentSocketDocument):
            sources.append(f"weapon sockets: {weapon_document.source_path}")
        context["placement_source_summary"] = "; ".join(sources) if sources else "socket-name proxy fallback"
        return context

    @staticmethod
    def _attachment_visual_character_socket_choices(
        context: Optional[Mapping[str, object]],
    ) -> Tuple[Tuple[str, str], ...]:
        document = context.get("character_socket_document") if isinstance(context, Mapping) else None
        if not isinstance(document, AttachmentSocketDocument):
            return ()
        socket_by_name = {
            str(socket.name or "").strip().casefold(): socket
            for socket in tuple(getattr(document, "sockets", ()) or ())
            if isinstance(socket, AttachmentSocketInfo) and str(socket.name or "").strip()
        }
        choices: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for stack in tuple(getattr(document, "stack_equip_infos", ()) or ()):
            equip_type = str(getattr(stack, "equip_type_name", "") or "").strip()
            for socket_name in tuple(getattr(stack, "socket_names", ()) or ()):
                normalized = str(socket_name or "").strip().casefold()
                if not normalized or normalized in seen or normalized not in socket_by_name:
                    continue
                seen.add(normalized)
                label = f"{equip_type}: {socket_name}" if equip_type else str(socket_name)
                choices.append((label, str(socket_name)))
        for socket in tuple(getattr(document, "sockets", ()) or ()):
            if not isinstance(socket, AttachmentSocketInfo):
                continue
            socket_name = str(socket.name or "").strip()
            normalized = socket_name.casefold()
            if not socket_name or normalized in seen:
                continue
            seen.add(normalized)
            choices.append((socket_name, socket_name))
        return tuple(choices)

    def _attachment_visual_context_for_character_socket(
        self,
        context: Optional[Mapping[str, object]],
        socket_name: str,
    ) -> Dict[str, object]:
        updated: Dict[str, object] = dict(context or {})
        socket = self._attachment_visual_find_socket_info(
            updated.get("character_socket_document") if isinstance(updated.get("character_socket_document"), AttachmentSocketDocument) else None,
            socket_name,
        )
        if isinstance(socket, AttachmentSocketInfo):
            updated["character_socket_info"] = socket
            anchor = self._attachment_visual_socket_world_position(socket, updated)
            if anchor is not None:
                updated["character_anchor"] = anchor
            elif "character_anchor" in updated:
                updated.pop("character_anchor", None)
            source_summary = str(updated.get("placement_source_summary", "") or "").strip()
            if source_summary:
                updated["placement_source_summary"] = f"{source_summary}; selected character socket: {socket.name}"
            else:
                updated["placement_source_summary"] = f"selected character socket: {socket.name}"
            current_pivot = updated.get("weapon_socket_info")
            fallback_pivot_name = str(getattr(current_pivot, "name", "") or "")
            pivot_name = self._attachment_visual_pivot_socket_for_character_socket(updated, socket.name, fallback_pivot_name)
            pivot_socket = self._attachment_visual_find_socket_info(
                updated.get("weapon_socket_document") if isinstance(updated.get("weapon_socket_document"), AttachmentSocketDocument) else None,
                pivot_name,
            )
            if isinstance(pivot_socket, AttachmentSocketInfo):
                updated["weapon_socket_info"] = pivot_socket
        return updated

    def _attachment_visual_pivot_socket_for_character_socket(
        self,
        context: Optional[Mapping[str, object]],
        character_socket_name: str,
        fallback_pivot_socket_name: str,
    ) -> str:
        document = context.get("weapon_socket_document") if isinstance(context, Mapping) else None
        if not isinstance(document, AttachmentSocketDocument):
            return str(fallback_pivot_socket_name or "")
        socket_name = str(character_socket_name or "").strip()
        candidates: List[str] = []
        if socket_name.endswith("_Socket"):
            candidates.append(f"{socket_name[:-7]}_ChildSocket")
        lowered = socket_name.casefold()
        if "pelvis_l" in lowered:
            candidates.append("Pelvis_L_ChildSocket")
        if "pelvis_r" in lowered:
            candidates.append("Pelvis_R_ChildSocket")
        if "hand" in lowered:
            candidates.append("Basic_ChildSocket")
        candidates.append(str(fallback_pivot_socket_name or ""))
        for candidate in candidates:
            if self._attachment_visual_find_socket_info(document, candidate) is not None:
                return candidate
        return str(fallback_pivot_socket_name or "")

    def _attachment_visual_evidence_for_character_socket(
        self,
        evidence: Optional[AttachmentPlacementEvidence],
        context: Optional[Mapping[str, object]],
        socket_name: str,
    ) -> Optional[AttachmentPlacementEvidence]:
        if not isinstance(evidence, AttachmentPlacementEvidence):
            return evidence
        socket = self._attachment_visual_find_socket_info(
            context.get("character_socket_document") if isinstance(context, Mapping) else None,
            socket_name,
        )
        pivot_socket_name = self._attachment_visual_pivot_socket_for_character_socket(
            context,
            str(socket_name or ""),
            evidence.weapon_socket_name,
        )
        pivot_socket = self._attachment_visual_find_socket_info(
            context.get("weapon_socket_document") if isinstance(context, Mapping) else None,
            pivot_socket_name,
        )
        if not isinstance(socket, AttachmentSocketInfo):
            return dataclasses.replace(
                evidence,
                character_socket_name=str(socket_name or ""),
                weapon_socket_name=pivot_socket_name,
                weapon_socket_parent=pivot_socket.parent if isinstance(pivot_socket, AttachmentSocketInfo) else evidence.weapon_socket_parent,
                weapon_socket_translation=pivot_socket.translation if isinstance(pivot_socket, AttachmentSocketInfo) else evidence.weapon_socket_translation,
                weapon_socket_rotation=pivot_socket.rotation if isinstance(pivot_socket, AttachmentSocketInfo) else evidence.weapon_socket_rotation,
            )
        return dataclasses.replace(
            evidence,
            character_socket_name=socket.name,
            character_socket_parent=socket.parent,
            character_socket_translation=socket.translation,
            character_socket_rotation=socket.rotation,
            weapon_socket_name=pivot_socket_name,
            weapon_socket_parent=pivot_socket.parent if isinstance(pivot_socket, AttachmentSocketInfo) else evidence.weapon_socket_parent,
            weapon_socket_translation=pivot_socket.translation if isinstance(pivot_socket, AttachmentSocketInfo) else evidence.weapon_socket_translation,
            weapon_socket_rotation=pivot_socket.rotation if isinstance(pivot_socket, AttachmentSocketInfo) else evidence.weapon_socket_rotation,
        )
