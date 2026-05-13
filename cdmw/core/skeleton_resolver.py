from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable, Mapping, Optional, Sequence, Tuple

from cdmw.models import ArchiveEntry
from cdmw.modding.skeleton_parser import Skeleton, iter_pab_candidate_basenames, parse_pab


@dataclass(frozen=True)
class SkeletonResolveCandidate:
    path: str
    score: int
    reason: str = ""
    bone_count: int = 0
    palette_hits: int = 0


@dataclass(frozen=True)
class SkeletonResolveReport:
    model_path: str
    selected_path: str = ""
    confidence: str = "unresolved"
    reason: str = ""
    candidates: Tuple[SkeletonResolveCandidate, ...] = ()
    attempted_paths: Tuple[str, ...] = ()
    blocking_errors: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SkinBindingMap:
    skeleton_bones: Tuple[str, ...] = ()
    pab_to_slot: Tuple[int, ...] = ()
    source_path: str = ""
    blocking_errors: Tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        return bool(self.skeleton_bones) and len(self.pab_to_slot) == len(self.skeleton_bones) and not self.blocking_errors

    def to_dict(self) -> dict:
        return {
            "schema": "cdmw_skin_binding_map_v1",
            "source_path": self.source_path,
            "skeleton_bones": list(self.skeleton_bones),
            "pab_to_slot": list(self.pab_to_slot),
            "blocking_errors": list(self.blocking_errors),
        }


def build_skin_binding_map(
    skeleton: Skeleton,
    pab_to_slot: Sequence[int],
    *,
    source_path: str = "",
    strict: bool = True,
) -> SkinBindingMap:
    bones = tuple(str(getattr(bone, "name", "") or f"bone_{index}") for index, bone in enumerate(getattr(skeleton, "bones", ()) or ()))
    slots = tuple(int(value) for value in pab_to_slot)
    errors: list[str] = []
    if not bones:
        errors.append("No PAB-ordered skeleton bones were available.")
    if len(slots) != len(bones):
        errors.append(
            f"PAB-to-slot mapping length {len(slots):,} does not match skeleton bone count {len(bones):,}."
        )
    if strict and any(value < 0 for value in slots):
        errors.append("PAB-to-slot mapping contains unresolved negative slot indexes.")
    if len(set(slots)) != len(slots):
        errors.append("PAB-to-slot mapping contains duplicate raw vertex-byte slots.")
    return SkinBindingMap(
        skeleton_bones=bones,
        pab_to_slot=slots,
        source_path=str(source_path or getattr(skeleton, "path", "") or ""),
        blocking_errors=tuple(errors),
    )


def _normalize_virtual_path(path: object) -> str:
    return PurePosixPath(str(path or "").replace("\\", "/").strip().strip("/")).as_posix().lower()


def _shared_prefix_len(left: str, right: str) -> int:
    left_parts = PurePosixPath(left).parts
    right_parts = PurePosixPath(right).parts
    count = 0
    for left_part, right_part in zip(left_parts, right_parts):
        if left_part != right_part:
            break
        count += 1
    return count


def _skeleton_palette_hits(skeleton: Skeleton, pac_data: bytes) -> int:
    if not pac_data:
        return 0
    skeleton_hashes = {
        int(getattr(bone, "name_hash", 0) or 0)
        for bone in tuple(getattr(skeleton, "bones", ()) or ())
        if int(getattr(bone, "name_hash", 0) or 0) > 0
    }
    if not skeleton_hashes:
        return 0
    best_sequence: set[int] = set()
    data_length = len(pac_data)
    for offset in range(0, max(0, data_length - 3)):
        value = int.from_bytes(pac_data[offset:offset + 4], "little", signed=False)
        if value not in skeleton_hashes:
            continue
        sequence: set[int] = set()
        cursor = offset
        while cursor + 4 <= data_length:
            candidate = int.from_bytes(pac_data[cursor:cursor + 4], "little", signed=False)
            if candidate not in skeleton_hashes:
                break
            sequence.add(candidate)
            cursor += 4
        if len(sequence) > len(best_sequence):
            best_sequence = sequence
    return len(best_sequence)


def _candidate_entry_for_path(candidates: Sequence[ArchiveEntry], path: str) -> Optional[ArchiveEntry]:
    normalized_path = _normalize_virtual_path(path)
    for entry in candidates:
        if _normalize_virtual_path(getattr(entry, "path", "")) == normalized_path:
            return entry
    return None


def _candidate_confidence(candidate: SkeletonResolveCandidate) -> str:
    if candidate.palette_hits:
        return "palette"
    if "exact sibling path" in candidate.reason:
        return "exact"
    return "heuristic"


def _candidate_is_ambiguous(
    best: SkeletonResolveCandidate,
    other: SkeletonResolveCandidate,
    *,
    palette_mode: bool,
) -> bool:
    if palette_mode:
        return best.palette_hits == other.palette_hits and best.score == other.score
    return best.score == other.score and _candidate_confidence(best) == _candidate_confidence(other)


def _all_indexed_pab_candidates(
    *,
    archive_entries: Sequence[ArchiveEntry],
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]],
) -> Tuple[ArchiveEntry, ...]:
    result: list[ArchiveEntry] = []
    seen: set[str] = set()

    def add(entry: ArchiveEntry) -> None:
        normalized = _normalize_virtual_path(getattr(entry, "path", ""))
        if normalized and normalized.endswith(".pab") and normalized not in seen:
            seen.add(normalized)
            result.append(entry)

    for entry in archive_entries:
        add(entry)
    if archive_entries_by_basename is not None:
        for entries in archive_entries_by_basename.values():
            for entry in tuple(entries or ()):
                add(entry)
    return tuple(result)


def resolve_skeleton_for_model(
    model_entry: ArchiveEntry,
    archive_entries: Sequence[ArchiveEntry] = (),
    *,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    pac_data: bytes = b"",
    read_entry_data: Optional[Callable[[ArchiveEntry], bytes]] = None,
) -> Tuple[Optional[ArchiveEntry], SkeletonResolveReport]:
    model_path = _normalize_virtual_path(getattr(model_entry, "path", ""))
    expected_path = PurePosixPath(model_path).with_suffix(".pab").as_posix()
    expected_normalized = _normalize_virtual_path(expected_path)
    candidate_basenames = iter_pab_candidate_basenames(model_path)
    attempted: list[str] = []
    seen_attempted: set[str] = set()
    candidates: list[ArchiveEntry] = []
    seen_candidates: set[str] = set()

    def remember(raw_path: object) -> None:
        normalized = _normalize_virtual_path(raw_path)
        if normalized and normalized not in seen_attempted:
            seen_attempted.add(normalized)
            attempted.append(str(raw_path or "").replace("\\", "/"))

    def add_candidate(entry: ArchiveEntry) -> None:
        normalized = _normalize_virtual_path(getattr(entry, "path", ""))
        if not normalized or normalized in seen_candidates or not normalized.endswith(".pab"):
            return
        seen_candidates.add(normalized)
        candidates.append(entry)

    remember(expected_path)
    if archive_entries_by_normalized_path is not None:
        for entry in tuple(archive_entries_by_normalized_path.get(expected_normalized, ()) or ()):
            add_candidate(entry)
    if archive_entries_by_basename is not None:
        for basename in candidate_basenames:
            remember(basename)
            for entry in tuple(archive_entries_by_basename.get(str(basename).lower(), ()) or ()):
                add_candidate(entry)
    if not candidates and archive_entries:
        wanted_basenames = {str(value).lower() for value in candidate_basenames}
        for entry in archive_entries:
            normalized = _normalize_virtual_path(getattr(entry, "path", ""))
            if normalized.endswith(".pab") and PurePosixPath(normalized).name in wanted_basenames:
                add_candidate(entry)
    if pac_data and read_entry_data is not None:
        for entry in _all_indexed_pab_candidates(
            archive_entries=archive_entries,
            archive_entries_by_basename=archive_entries_by_basename,
        ):
            add_candidate(entry)

    scored: list[SkeletonResolveCandidate] = []
    for entry in candidates:
        candidate_path = _normalize_virtual_path(entry.path)
        score = 0
        reasons: list[str] = []
        if candidate_path == expected_normalized:
            score += 100
            reasons.append("exact sibling path")
        if PurePosixPath(candidate_path).name in {str(value).lower() for value in candidate_basenames}:
            score += 32
            reasons.append("candidate basename")
        if getattr(entry, "pamt_path", None) == getattr(model_entry, "pamt_path", None):
            score += 10
            reasons.append("same package")
        shared_prefix = _shared_prefix_len(candidate_path, model_path)
        if shared_prefix:
            score += min(shared_prefix * 3, 24)
            reasons.append("shared path prefix")
        if "skeleton" in PurePosixPath(candidate_path).parts:
            score += 8
            reasons.append("skeleton folder")

        bone_count = 0
        palette_hits = 0
        if read_entry_data is not None:
            try:
                skeleton = parse_pab(read_entry_data(entry), entry.path)
                bone_count = len(getattr(skeleton, "bones", ()) or ())
                palette_hits = _skeleton_palette_hits(skeleton, pac_data)
                if palette_hits:
                    score += 200 + min(120, palette_hits * 6)
                    reasons.append(f"{palette_hits} contiguous palette bone hash hit(s)")
            except Exception as exc:
                score -= 20
                reasons.append(f"parse failed: {exc}")
        scored.append(
            SkeletonResolveCandidate(
                path=entry.path.replace("\\", "/"),
                score=score,
                reason=", ".join(reasons) or "candidate",
                bone_count=bone_count,
                palette_hits=palette_hits,
            )
        )

    if not scored:
        return None, SkeletonResolveReport(
            model_path=model_entry.path.replace("\\", "/"),
            attempted_paths=tuple(attempted),
            blocking_errors=(f"No PAB skeleton candidate could be resolved for {model_entry.path}.",),
        )

    palette_scored = [candidate for candidate in scored if candidate.palette_hits > 0]
    ranked = palette_scored or scored
    ranked.sort(key=lambda candidate: (candidate.palette_hits, candidate.score, candidate.bone_count, -len(candidate.path)), reverse=True)
    scored.sort(key=lambda candidate: (candidate.score, candidate.palette_hits, candidate.bone_count, -len(candidate.path)), reverse=True)
    if len(ranked) > 1 and _candidate_is_ambiguous(ranked[0], ranked[1], palette_mode=bool(palette_scored)):
        confidence = "ambiguous_palette" if palette_scored else "ambiguous"
        return None, SkeletonResolveReport(
            model_path=model_entry.path.replace("\\", "/"),
            selected_path="",
            confidence=confidence,
            reason="Ambiguous skeleton candidates; no deterministic selection was made.",
            candidates=tuple(scored),
            attempted_paths=tuple(attempted),
            blocking_errors=("Multiple skeleton candidates scored equally; select a skeleton explicitly.",),
        )
    selected_path = ranked[0].path
    selected_entry = _candidate_entry_for_path(candidates, selected_path)
    confidence = _candidate_confidence(ranked[0])
    return selected_entry, SkeletonResolveReport(
        model_path=model_entry.path.replace("\\", "/"),
        selected_path=selected_path,
        confidence=confidence,
        reason=ranked[0].reason,
        candidates=tuple(scored),
        attempted_paths=tuple(attempted),
    )
