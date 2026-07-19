"""Archive browser attachment visual model and transform helpers."""

from __future__ import annotations

import math
import re
from pathlib import PurePosixPath
from typing import List, Mapping, Optional, Sequence, Tuple

from cdmw.models import (
    ArchiveEntry,
    AssetFamilyGraph,
    AssetFamilyMember,
    AttachmentPlacementEvidence,
    AttachmentSocketDocument,
    AttachmentSocketInfo,
)
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependenciesUnavailable,
    archive_workflow_dependency_context,
)


class ArchiveAttachmentVisualCoreMixin:
    def _attachment_visual_model_entry(
        self,
        source_entry: ArchiveEntry,
        graph: AssetFamilyGraph,
    ) -> Optional[ArchiveEntry]:
        try:
            dependencies = archive_workflow_dependency_context(self, source_entry)
        except ArchiveWorkflowDependenciesUnavailable:
            return None
        source_entry = dependencies.selected_entry
        prepared_by_identity = (
            {candidate.identity: candidate for candidate in dependencies.entries}
            if dependencies.remote
            else None
        )
        model_extensions = {".pac", ".pam", ".pamlod"}
        if str(source_entry.extension or "").lower() in model_extensions:
            return source_entry

        source_path = str(source_entry.path or "").replace("\\", "/").strip()
        source_lower = source_path.casefold()
        source_stem = PurePosixPath(source_path).stem.casefold()
        source_family_stem = re.sub(r"(?:_(?:r|l|in|out|[0-9]{1,2}))+$", "", source_stem)
        source_tokens = {token for token in re.split(r"[^a-z0-9]+", source_stem) if token}

        def path_score(path_text: object) -> int:
            candidate_path = str(path_text or "").replace("\\", "/").strip()
            candidate_lower = candidate_path.casefold()
            candidate_stem = PurePosixPath(candidate_path).stem.casefold()
            candidate_family_stem = re.sub(r"(?:_(?:r|l|in|out|[0-9]{1,2}))+$", "", candidate_stem)
            candidate_tokens = {token for token in re.split(r"[^a-z0-9]+", candidate_stem) if token}
            score = 0
            if source_stem and candidate_stem == source_stem:
                score += 180
            elif source_family_stem and candidate_family_stem == source_family_stem:
                score += 130
            elif source_stem and (candidate_stem.startswith(source_stem) or source_stem.startswith(candidate_stem)):
                score += 90
            shared_tokens = source_tokens & candidate_tokens
            if shared_tokens:
                score += min(70, len(shared_tokens) * 14)
            for token in ("weapon", "sword", "shield", "bow", "dagger", "axe", "spear", "onehandweapon", "twohandweapon"):
                if token in source_lower and token in candidate_lower:
                    score += 16
            if "/weapon/" in source_lower and "/weapon/" in candidate_lower:
                score += 46
            if "/character/" in source_lower and "/character/" in candidate_lower:
                score += 18
            if "/object/" in source_lower and "/object/" not in candidate_lower:
                score -= 20
            if "/object/" not in source_lower and "/object/" in candidate_lower:
                score -= 72
            return score

        candidates: List[Tuple[int, int, ArchiveEntry]] = []
        seen: set[Tuple[str, str, int]] = set()

        def add_candidate(candidate: Optional[ArchiveEntry], base_score: int) -> None:
            if not isinstance(candidate, ArchiveEntry):
                return
            if prepared_by_identity is not None:
                candidate = prepared_by_identity.get(candidate.identity)
                if not isinstance(candidate, ArchiveEntry):
                    return
            if str(candidate.extension or "").lower() not in model_extensions:
                return
            key = (
                str(candidate.path or "").replace("\\", "/").casefold(),
                str(candidate.pamt_path).casefold(),
                int(candidate.offset),
            )
            if key in seen:
                return
            score = int(base_score) + path_score(candidate.path)
            if score < 45 and base_score < 100:
                return
            seen.add(key)
            candidates.append((score, len(candidates), candidate))

        for evidence in tuple(getattr(graph, "attachment_evidence", ()) or ()):
            if isinstance(evidence, AttachmentPlacementEvidence) and evidence.model_path:
                model_entry = dependencies.entry_for_path(evidence.model_path)
                add_candidate(model_entry, 115)
        for member in tuple(getattr(graph, "member_rows", ()) or ()):
            if not isinstance(member, AssetFamilyMember):
                continue
            model_entry = getattr(member, "resolved_entry", None)
            base_score = 22
            if member.group == "Selected Model":
                base_score += 120
            if str(member.include_policy or "").casefold() in {"required", "recommended"}:
                base_score += 20
            if str(member.source_evidence or member.confidence or "").casefold() in {"exact", "exact path", "same stem"}:
                base_score += 22
            add_candidate(model_entry, base_score)
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item[0], item[1]))
        best_score, _order, best_entry = candidates[0]
        return best_entry if best_score >= 45 else None

    def _attachment_visual_body_context_model_entry(
        self,
        target_entry: ArchiveEntry,
        donor_entry: Optional[ArchiveEntry] = None,
    ) -> Optional[ArchiveEntry]:
        try:
            dependencies = archive_workflow_dependency_context(self, target_entry)
        except ArchiveWorkflowDependenciesUnavailable:
            return None
        target_entry = dependencies.selected_entry
        evidence_text = " ".join(
            str(value or "").replace("\\", "/").casefold()
            for value in (
                getattr(target_entry, "path", ""),
                getattr(target_entry, "basename", ""),
                getattr(donor_entry, "path", "") if isinstance(donor_entry, ArchiveEntry) else "",
                getattr(donor_entry, "basename", "") if isinstance(donor_entry, ArchiveEntry) else "",
            )
        )
        family = "phw" if "phw" in evidence_text or "/2_phw/" in evidence_text else "phm"
        preferred = (
            (
                "cd_phw_00_nude_00_0001.pac",
                "cd_phw_00_nude_00_0001_damian.pac",
            )
            if family == "phw"
            else (
                "cd_phm_00_nude_10_0001.pac",
                "cd_phm_00_nude_00_0001.pac",
                "cd_phm_00_nude_00_4001.pac",
            )
        )
        for basename in preferred:
            for entry in tuple(dependencies.entries_by_basename.get(basename, ()) or ()):
                if isinstance(entry, ArchiveEntry) and str(entry.extension or "").lower() == ".pac":
                    return entry

        prefix = f"cd_{family}_00_nude"
        candidates: List[Tuple[int, str, ArchiveEntry]] = []
        for entry in dependencies.entries:
            if not isinstance(entry, ArchiveEntry) or str(entry.extension or "").lower() != ".pac":
                continue
            basename = str(entry.basename or PurePosixPath(entry.path.replace("\\", "/")).name).casefold()
            path = str(entry.path or "").replace("\\", "/").casefold()
            if not basename.startswith(prefix):
                continue
            score = 0
            if "/nude/" in path:
                score += 60
            if "_hand_hair" in basename or "_lod_" in basename:
                score -= 80
            if "damian" in basename:
                score += 20 if family == "phw" else -10
            if "_10_0001" in basename:
                score += 28
            if "_00_0001" in basename:
                score += 20
            candidates.append((score, path, entry))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item[0], item[1]))
        return candidates[0][2]

    @staticmethod
    def _attachment_visual_best_evidence(graph: AssetFamilyGraph) -> Optional[AttachmentPlacementEvidence]:
        rows = [
            evidence
            for evidence in tuple(getattr(graph, "attachment_evidence", ()) or ())
            if isinstance(evidence, AttachmentPlacementEvidence)
        ]
        if not rows:
            return None

        def score(evidence: AttachmentPlacementEvidence) -> int:
            value = 0
            if evidence.character_socket_name:
                value += 40
            if evidence.weapon_socket_name:
                value += 40
            if evidence.socket_file_path:
                value += 20
            if evidence.character_socket_translation:
                value += 12
            if evidence.weapon_socket_translation:
                value += 12
            if str(evidence.confidence or "").casefold().startswith("exact"):
                value += 25
            return value

        return max(rows, key=score)

    def _attachment_visual_evidence_for_prefab(
        self,
        graph: Optional[AssetFamilyGraph],
        prefab_entry: Optional[ArchiveEntry],
    ) -> Optional[AttachmentPlacementEvidence]:
        if not isinstance(graph, AssetFamilyGraph):
            return None
        if isinstance(prefab_entry, ArchiveEntry):
            prefab_path = prefab_entry.path.replace("\\", "/").casefold()
            for evidence in tuple(getattr(graph, "attachment_evidence", ()) or ()):
                if not isinstance(evidence, AttachmentPlacementEvidence):
                    continue
                if str(evidence.prefab_path or "").replace("\\", "/").casefold() == prefab_path:
                    return evidence
        return self._attachment_visual_best_evidence(graph)

    @staticmethod
    def _attachment_visual_finite_vector3(value: Sequence[object], fallback: Tuple[float, float, float] = (0.0, 0.0, 0.0)) -> Tuple[float, float, float]:
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            return fallback
        try:
            parsed = (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError, OverflowError):
            return fallback
        if not all(math.isfinite(component) for component in parsed):
            return fallback
        return parsed

    @staticmethod
    def _attachment_visual_finite_quat(value: Sequence[object]) -> Tuple[float, float, float, float]:
        if not isinstance(value, (list, tuple)) or len(value) < 4:
            return (0.0, 0.0, 0.0, 1.0)
        try:
            quat = (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
        except (TypeError, ValueError, OverflowError):
            return (0.0, 0.0, 0.0, 1.0)
        if not all(math.isfinite(component) for component in quat):
            return (0.0, 0.0, 0.0, 1.0)
        length = math.sqrt(sum(component * component for component in quat))
        if length <= 1e-8:
            return (0.0, 0.0, 0.0, 1.0)
        return tuple(component / length for component in quat)  # type: ignore[return-value]

    @staticmethod
    def _attachment_visual_quat_inverse(quat: Sequence[float]) -> Tuple[float, float, float, float]:
        x, y, z, w = __class__._attachment_visual_finite_quat(quat)
        return (-x, -y, -z, w)

    @staticmethod
    def _attachment_visual_quat_multiply(
        first: Sequence[float],
        second: Sequence[float],
    ) -> Tuple[float, float, float, float]:
        ax, ay, az, aw = __class__._attachment_visual_finite_quat(first)
        bx, by, bz, bw = __class__._attachment_visual_finite_quat(second)
        return __class__._attachment_visual_finite_quat(
            (
                (aw * bx) + (ax * bw) + (ay * bz) - (az * by),
                (aw * by) - (ax * bz) + (ay * bw) + (az * bx),
                (aw * bz) + (ax * by) - (ay * bx) + (az * bw),
                (aw * bw) - (ax * bx) - (ay * by) - (az * bz),
            )
        )

    @staticmethod
    def _attachment_visual_quat_rotate(
        quat: Sequence[float],
        point: Sequence[float],
    ) -> Tuple[float, float, float]:
        x, y, z = __class__._attachment_visual_finite_vector3(point)
        rotation = __class__._attachment_visual_finite_quat(quat)
        rotated = __class__._attachment_visual_quat_multiply(
            __class__._attachment_visual_quat_multiply(rotation, (x, y, z, 0.0)),
            __class__._attachment_visual_quat_inverse(rotation),
        )
        return (rotated[0], rotated[1], rotated[2])

    @staticmethod
    def _attachment_visual_euler_quat(rx_degrees: float, ry_degrees: float, rz_degrees: float) -> Tuple[float, float, float, float]:
        def axis_quat(axis: str, degrees: float) -> Tuple[float, float, float, float]:
            radians = math.radians(float(degrees)) * 0.5
            sine = math.sin(radians)
            cosine = math.cos(radians)
            if axis == "x":
                return (sine, 0.0, 0.0, cosine)
            if axis == "y":
                return (0.0, sine, 0.0, cosine)
            return (0.0, 0.0, sine, cosine)

        return __class__._attachment_visual_quat_multiply(
            axis_quat("z", rz_degrees),
            __class__._attachment_visual_quat_multiply(axis_quat("y", ry_degrees), axis_quat("x", rx_degrees)),
        )

    @staticmethod
    def _attachment_visual_socket_proxy_position(socket_name: str, parent_name: str = "") -> Tuple[float, float, float]:
        text = f"{socket_name} {parent_name}".casefold()
        if "pelvis_l" in text or "weaponin_r" in text:
            return (-0.26, -0.18, -0.08)
        if "pelvis_r" in text or "weaponin_l" in text:
            return (0.26, -0.18, -0.08)
        if "spine2_b" in text or "back" in text:
            return (0.0, 0.36, -0.24)
        if "spine" in text:
            return (0.0, 0.26, -0.16)
        if "hand_l" in text or "weapon_l" in text:
            return (-0.42, 0.16, 0.10)
        if "hand_r" in text or "weapon_r" in text:
            return (0.42, 0.16, 0.10)
        if "head" in text:
            return (0.0, 0.72, 0.0)
        return (0.0, 0.0, 0.0)

    @staticmethod
    def _attachment_visual_find_socket_info(
        document: Optional[AttachmentSocketDocument],
        socket_name: str,
    ) -> Optional[AttachmentSocketInfo]:
        normalized = str(socket_name or "").strip().casefold()
        if not normalized or not isinstance(document, AttachmentSocketDocument):
            return None
        for socket in tuple(getattr(document, "sockets", ()) or ()):
            if isinstance(socket, AttachmentSocketInfo) and str(socket.name or "").strip().casefold() == normalized:
                return socket
        return None

    @staticmethod
    def _attachment_visual_context_has_real_anchor(context: Optional[Mapping[str, object]]) -> bool:
        if not isinstance(context, Mapping):
            return False
        if bool(context.get("force_visual_proxy_anchor")):
            return False
        anchor = context.get("character_anchor")
        if not isinstance(anchor, (list, tuple)) or len(anchor) < 3:
            return False
        try:
            return all(math.isfinite(float(component)) for component in tuple(anchor)[:3])
        except (TypeError, ValueError, OverflowError):
            return False

    @staticmethod
    def _attachment_visual_context_transform_scale(context: Optional[Mapping[str, object]]) -> float:
        # Model previews are normalized display geometry; only socket anchors may come from real skeleton data.
        # Keep weapon mesh/socket edit scale stable so decoded PAC bounds cannot turn placement preview into a blob.
        return 0.10
