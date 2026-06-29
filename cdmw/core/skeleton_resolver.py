from __future__ import annotations

import html
import xml.etree.ElementTree as ET
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
    descriptor_path: str = ""
    skeleton_variation_path: str = ""
    animation_constraint_path: str = ""
    socket_path: str = ""
    candidates: Tuple[SkeletonResolveCandidate, ...] = ()
    attempted_paths: Tuple[str, ...] = ()
    blocking_errors: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SkeletonDescriptorResolution:
    descriptor_entry: Optional[ArchiveEntry] = None
    skeleton_entry: Optional[ArchiveEntry] = None
    skeleton_variation_entry: Optional[ArchiveEntry] = None
    animation_constraint_entry: Optional[ArchiveEntry] = None
    socket_entry: Optional[ArchiveEntry] = None
    score: int = 0
    reason: str = ""
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


def _prefabdata_xml_refs(text: str) -> Tuple[Tuple[str, str], ...]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return ()
    refs: list[tuple[str, str]] = []
    for element in root.iter():
        tag_lower = str(element.tag).rsplit("}", 1)[-1].lower()
        for key, raw_value in element.attrib.items():
            value = html.unescape(str(raw_value or "")).strip()
            if not value:
                continue
            key_lower = str(key or "").lower()
            ref_key = tag_lower if key_lower == "filename" and tag_lower in {
                "skeletonname",
                "skeletonvariationname",
                "animationconstraintname",
                "socketfilename",
            } else str(key)
            if (
                key_lower in {"filename", "skeletonname", "skeletonvariationname", "animationconstraintname", "socketfilename"}
                or key_lower.endswith("name")
                or key_lower.endswith("file")
                or key_lower.endswith("path")
            ):
                refs.append((ref_key, value))
    return tuple(dict.fromkeys(refs))


def _model_descriptor_tokens(model_path: str) -> Tuple[str, ...]:
    normalized = _normalize_virtual_path(model_path)
    stem = PurePosixPath(normalized).stem
    tokens: list[str] = []
    for part in PurePosixPath(normalized).parts:
        part_lower = part.lower()
        if part_lower in {"1_pc", "2_mon"}:
            continue
        if part and any(ch.isdigit() for ch in part) and "_" in part:
            tokens.append(part.lower())
    stem_parts = [part for part in stem.split("_") if part]
    if len(stem_parts) >= 2 and stem_parts[0] == "cd":
        tokens.append(stem_parts[1].lower())
    return tuple(dict.fromkeys(token for token in tokens if token))


def _iter_index_entries(index: Mapping[str, Sequence[ArchiveEntry]] | None) -> Tuple[ArchiveEntry, ...]:
    if not index:
        return ()
    result: list[ArchiveEntry] = []
    seen: set[str] = set()
    for entries in index.values():
        for entry in tuple(entries or ()):
            normalized = _normalize_virtual_path(getattr(entry, "path", ""))
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(entry)
    return tuple(result)


def _descriptor_candidates_for_model(
    model_entry: ArchiveEntry,
    *,
    archive_entries: Sequence[ArchiveEntry],
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]],
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]],
) -> Tuple[ArchiveEntry, ...]:
    model_path = _normalize_virtual_path(getattr(model_entry, "path", ""))
    model_pure = PurePosixPath(model_path)
    stem = model_pure.stem
    tokens = set(_model_descriptor_tokens(model_path))
    candidates: dict[str, ArchiveEntry] = {}

    def add(entry: ArchiveEntry) -> None:
        normalized = _normalize_virtual_path(getattr(entry, "path", ""))
        basename = PurePosixPath(normalized).name
        if not normalized or (entry.extension != ".prefabdata_xml" and "prefabdata" not in basename):
            return
        candidates.setdefault(normalized, entry)

    for suffix in (".prefabdata_xml", ".prefabdata.xml"):
        for raw_path in (
            model_pure.with_suffix(suffix).as_posix(),
            model_pure.with_name(f"{stem}{suffix}").as_posix(),
            model_path.replace("/model/", "/prefab/").rsplit(".", 1)[0] + suffix,
        ):
            normalized = _normalize_virtual_path(raw_path)
            for entry in tuple((archive_entries_by_normalized_path or {}).get(normalized, ()) or ()):
                add(entry)
        for entry in tuple((archive_entries_by_basename or {}).get(f"{stem}{suffix}".lower(), ()) or ()):
            add(entry)

    for entry in tuple(archive_entries or ()) + _iter_index_entries(archive_entries_by_basename):
        normalized = _normalize_virtual_path(getattr(entry, "path", ""))
        if not normalized or "prefabdata" not in PurePosixPath(normalized).name:
            continue
        if tokens and not any(token in normalized for token in tokens):
            continue
        add(entry)
    return tuple(candidates.values())


def _reference_extension(attr_name: str, raw_value: str) -> str:
    attr = str(attr_name or "").strip().lower()
    suffix = PurePosixPath(str(raw_value or "").replace("\\", "/").strip()).suffix.lower()
    if suffix:
        return suffix
    if attr == "skeletonname":
        return ".pab"
    if attr == "skeletonvariationname":
        return ".pabc"
    if attr == "animationconstraintname":
        return ".papr"
    return ""


def _descriptor_reference_paths(attr_name: str, raw_value: str) -> Tuple[str, ...]:
    value = str(raw_value or "").replace("\\", "/").strip().strip("/")
    if not value:
        return ()
    extension = _reference_extension(attr_name, value)
    if extension and PurePosixPath(value).suffix.lower() != extension:
        value = f"{value}{extension}"
    paths = [value]
    attr = str(attr_name or "").strip().lower()
    if not value.lower().startswith("character/"):
        if attr == "skeletonvariationname" or value.lower().endswith(".pabc"):
            paths.append(f"character/binary/skeletonvariation/{value}")
        elif attr == "skeletonname" or value.lower().endswith(".pab"):
            paths.append(f"character/model/{value}")
        elif attr == "socketfilename" or value.lower().endswith(".sockets.xml"):
            paths.append(f"character/descriptors/socketbonedata/{value}")
    return tuple(dict.fromkeys(paths))


def _resolve_descriptor_reference(
    attr_name: str,
    raw_value: str,
    *,
    model_entry: ArchiveEntry,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]],
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]],
) -> Tuple[Optional[ArchiveEntry], Tuple[str, ...]]:
    attempted = _descriptor_reference_paths(attr_name, raw_value)
    entries: dict[str, ArchiveEntry] = {}
    expected_extension = _reference_extension(attr_name, raw_value)

    def add(entry: ArchiveEntry) -> None:
        normalized = _normalize_virtual_path(getattr(entry, "path", ""))
        if not normalized:
            return
        if expected_extension and not normalized.endswith(expected_extension):
            return
        entries.setdefault(normalized, entry)

    for path in attempted:
        normalized = _normalize_virtual_path(path)
        for entry in tuple((archive_entries_by_normalized_path or {}).get(normalized, ()) or ()):
            add(entry)
    basename = PurePosixPath(_normalize_virtual_path(attempted[0] if attempted else raw_value)).name
    if basename:
        for entry in tuple((archive_entries_by_basename or {}).get(basename.lower(), ()) or ()):
            add(entry)
    if not entries:
        return None, attempted

    model_path = _normalize_virtual_path(getattr(model_entry, "path", ""))
    target_suffixes = {_normalize_virtual_path(path) for path in attempted}

    def score(entry: ArchiveEntry) -> tuple[int, str]:
        normalized = _normalize_virtual_path(getattr(entry, "path", ""))
        value = 0
        if normalized in target_suffixes:
            value += 100
        if any(normalized.endswith(path) for path in target_suffixes):
            value += 45
        if getattr(entry, "pamt_path", None) == getattr(model_entry, "pamt_path", None):
            value += 12
        value += min(_shared_prefix_len(normalized, model_path) * 3, 24)
        return value, normalized

    return max(entries.values(), key=score), attempted


def resolve_skeleton_descriptor_for_model(
    model_entry: ArchiveEntry,
    archive_entries: Sequence[ArchiveEntry] = (),
    *,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    read_entry_data: Optional[Callable[[ArchiveEntry], bytes]] = None,
) -> SkeletonDescriptorResolution:
    if read_entry_data is None:
        return SkeletonDescriptorResolution()
    model_path = _normalize_virtual_path(getattr(model_entry, "path", ""))
    candidate_basenames = set(iter_pab_candidate_basenames(model_path))
    best: SkeletonDescriptorResolution | None = None
    attempted_all: list[str] = []
    errors: list[str] = []
    for descriptor_entry in _descriptor_candidates_for_model(
        model_entry,
        archive_entries=archive_entries,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    ):
        try:
            text = read_entry_data(descriptor_entry).decode("utf-8", "ignore")
        except Exception as exc:
            errors.append(f"{descriptor_entry.path}: {exc}")
            continue
        refs = _prefabdata_xml_refs(text)
        if not refs:
            continue
        resolved: dict[str, ArchiveEntry] = {}
        attempted: list[str] = []
        score = min(_shared_prefix_len(_normalize_virtual_path(descriptor_entry.path), model_path) * 4, 32)
        for attr_name, raw_value in refs:
            attr = str(attr_name or "").strip().lower()
            value_path = _normalize_virtual_path(raw_value)
            if attr == "filename" and (
                value_path == model_path
                or PurePosixPath(value_path).name == PurePosixPath(model_path).name
            ):
                score += 120
            if attr == "skeletonname" and PurePosixPath(value_path).name.lower() in candidate_basenames:
                score += 80
            if attr in {"skeletonname", "skeletonvariationname", "animationconstraintname", "socketfilename"}:
                entry, paths = _resolve_descriptor_reference(
                    attr_name,
                    raw_value,
                    model_entry=model_entry,
                    archive_entries_by_normalized_path=archive_entries_by_normalized_path,
                    archive_entries_by_basename=archive_entries_by_basename,
                )
                attempted.extend(paths)
                if entry is not None:
                    resolved[attr] = entry
                    score += 40
        attempted_all.extend(attempted)
        if not any(key in resolved for key in ("skeletonname", "skeletonvariationname")):
            continue
        resolution = SkeletonDescriptorResolution(
            descriptor_entry=descriptor_entry,
            skeleton_entry=resolved.get("skeletonname"),
            skeleton_variation_entry=resolved.get("skeletonvariationname"),
            animation_constraint_entry=resolved.get("animationconstraintname"),
            socket_entry=resolved.get("socketfilename"),
            score=score,
            reason=f"prefabdata descriptor {descriptor_entry.path}",
            attempted_paths=tuple(dict.fromkeys(attempted)),
        )
        if best is None or (resolution.score, bool(resolution.skeleton_entry)) > (best.score, bool(best.skeleton_entry)):
            best = resolution
    if best is not None:
        return best
    return SkeletonDescriptorResolution(
        attempted_paths=tuple(dict.fromkeys(attempted_all)),
        blocking_errors=tuple(errors),
    )


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
    descriptor_resolution = resolve_skeleton_descriptor_for_model(
        model_entry,
        archive_entries,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
        read_entry_data=read_entry_data,
    )
    if descriptor_resolution.skeleton_entry is not None:
        selected = descriptor_resolution.skeleton_entry
        return selected, SkeletonResolveReport(
            model_path=model_entry.path.replace("\\", "/"),
            selected_path=selected.path.replace("\\", "/"),
            confidence="descriptor",
            reason=descriptor_resolution.reason,
            descriptor_path=str(getattr(descriptor_resolution.descriptor_entry, "path", "") or "").replace("\\", "/"),
            skeleton_variation_path=str(getattr(descriptor_resolution.skeleton_variation_entry, "path", "") or "").replace("\\", "/"),
            animation_constraint_path=str(getattr(descriptor_resolution.animation_constraint_entry, "path", "") or "").replace("\\", "/"),
            socket_path=str(getattr(descriptor_resolution.socket_entry, "path", "") or "").replace("\\", "/"),
            candidates=(
                SkeletonResolveCandidate(
                    path=selected.path.replace("\\", "/"),
                    score=descriptor_resolution.score,
                    reason=descriptor_resolution.reason,
                ),
            ),
            attempted_paths=descriptor_resolution.attempted_paths,
        )
    descriptor_attempted = tuple(descriptor_resolution.attempted_paths)
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
            attempted_paths=tuple(dict.fromkeys((*descriptor_attempted, *attempted))),
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
            descriptor_path=str(getattr(descriptor_resolution.descriptor_entry, "path", "") or "").replace("\\", "/"),
            skeleton_variation_path=str(getattr(descriptor_resolution.skeleton_variation_entry, "path", "") or "").replace("\\", "/"),
            attempted_paths=tuple(dict.fromkeys((*descriptor_attempted, *attempted))),
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
        descriptor_path=str(getattr(descriptor_resolution.descriptor_entry, "path", "") or "").replace("\\", "/"),
        skeleton_variation_path=str(getattr(descriptor_resolution.skeleton_variation_entry, "path", "") or "").replace("\\", "/"),
        candidates=tuple(scored),
        attempted_paths=tuple(dict.fromkeys((*descriptor_attempted, *attempted))),
    )
