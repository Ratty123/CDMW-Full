"""Read-only character appearance resolution for PAC preview and FBX export."""

from __future__ import annotations

import html
import hashlib
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping, Optional, Sequence

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_relationships import build_archive_relationship_plan
from cdmw.core.character_appearance_bundle import (
    CHARACTER_APPEARANCE_BUNDLE_FILENAME,
    CHARACTER_APPEARANCE_BUNDLE_FORMAT,
    load_character_appearance_bundle_index as _manifest_appearance_index,
    write_character_appearance_bundle_manifest,
)
from cdmw.core.common import RunCancelled, raise_if_cancelled
from cdmw.core.skeleton_resolver import resolve_skeleton_descriptor_for_model, resolve_skeleton_for_model
from cdmw.models import ArchiveEntry, ModelPreviewData
from cdmw.modding.mesh_parser import ParsedMesh, resolve_pac_bone_palette
from cdmw.modding.skeleton_parser import iter_pab_candidate_basenames, parse_pab
from cdmw.modding.skeleton_variation_parser import (
    apply_skeleton_variation_to_mesh,
    parse_pabc_skeleton_variation,
    parse_pamt_morph_target_set,
)


_LOOSE_APPEARANCE_EXTENSIONS = {".app_xml", ".pab", ".pabc", ".pamt", ".prefabdata_xml"}
_LOOSE_APPEARANCE_SCAN_LIMIT = 20_000
_LOOSE_APPEARANCE_PAYLOAD_LIMIT = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class LooseCharacterAppearanceSources:
    package_root: Path
    model_virtual_path: str
    descriptor_path: Path | None = None
    skeleton_descriptor_path: Path | None = None
    morph_descriptor_path: Path | None = None
    skeleton_path: Path | None = None
    skeleton_variation_path: Path | None = None
    morph_target_path: Path | None = None
    manifest_path: Path | None = None
    expected_hashes: tuple[tuple[str, str], ...] = ()


def _normalized_path(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/").casefold()


def _shared_prefix_length(left: str, right: str) -> int:
    count = 0
    for left_part, right_part in zip(PurePosixPath(_normalized_path(left)).parts, PurePosixPath(_normalized_path(right)).parts):
        if left_part != right_part:
            break
        count += 1
    return count


def _sorted_candidates(source_path: str, entries: Sequence[ArchiveEntry]) -> tuple[ArchiveEntry, ...]:
    deduped: dict[tuple[str, str, int, int], ArchiveEntry] = {}
    for entry in entries:
        key = (
            _normalized_path(entry.path),
            str(entry.pamt_path or "").casefold(),
            int(entry.paz_index or 0),
            int(entry.offset or 0),
        )
        deduped.setdefault(key, entry)
    return tuple(
        sorted(
            deduped.values(),
            key=lambda entry: (
                _shared_prefix_length(source_path, entry.path),
                -len(str(entry.path or "")),
                _normalized_path(entry.path),
            ),
            reverse=True,
        )
    )


def _loose_character_package_root(source_path: Path) -> Path:
    resolved = source_path.expanduser().resolve()
    for parent in resolved.parents:
        if parent.name.casefold() == "character":
            return parent.parent
    return resolved.parent


def _loose_virtual_path(package_root: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to(package_root.resolve())
    except (OSError, ValueError):
        relative = Path(path.name)
    return _normalized_path(relative.as_posix())


def _loose_appearance_index(
    package_root: Path,
    *,
    stop_event: Optional[threading.Event],
) -> tuple[dict[str, Path], dict[str, tuple[Path, ...]]]:
    by_virtual: dict[str, Path] = {}
    by_basename_lists: dict[str, list[Path]] = {}
    scanned = 0
    try:
        iterator = package_root.rglob("*")
        for candidate in iterator:
            raise_if_cancelled(stop_event)
            scanned += 1
            if scanned > _LOOSE_APPEARANCE_SCAN_LIMIT:
                raise ValueError(
                    f"Loose character package exceeds the {_LOOSE_APPEARANCE_SCAN_LIMIT:,}-entry scan limit"
                )
            name = candidate.name.casefold()
            if not candidate.is_file() or (
                candidate.suffix.casefold() not in _LOOSE_APPEARANCE_EXTENSIONS
                and not name.endswith(".prefabdata.xml")
            ):
                continue
            virtual_path = _loose_virtual_path(package_root, candidate)
            by_virtual.setdefault(virtual_path, candidate.resolve())
            by_basename_lists.setdefault(name, []).append(candidate.resolve())
    except OSError as exc:
        raise ValueError(f"Could not scan loose character package {package_root}: {exc}") from exc
    return by_virtual, {key: tuple(value) for key, value in by_basename_lists.items()}


def _loose_candidate_score(model_virtual_path: str, package_root: Path, candidate: Path) -> tuple[int, int, str]:
    candidate_virtual_path = _loose_virtual_path(package_root, candidate)
    descriptor_model_path = candidate_virtual_path.replace("/prefab/", "/model/")
    for suffix in (".prefabdata_xml", ".prefabdata.xml"):
        if descriptor_model_path.endswith(suffix):
            descriptor_model_path = descriptor_model_path[: -len(suffix)] + ".pac"
            break
    return (
        int(descriptor_model_path == _normalized_path(model_virtual_path)),
        _shared_prefix_length(model_virtual_path, candidate_virtual_path),
        candidate_virtual_path,
    )


def _loose_descriptor_family_rank(source_stem: str, candidate_stem: str) -> tuple[int, int] | None:
    source_tokens = tuple(token for token in str(source_stem or "").casefold().split("_") if token)
    candidate_tokens = tuple(token for token in str(candidate_stem or "").casefold().split("_") if token)
    shared_tokens = 0
    for left, right in zip(source_tokens, candidate_tokens):
        if left != right:
            break
        shared_tokens += 1
    component_tokens = {"body", "face", "hair", "head", "nude"}
    has_named_family_token = (
        source_tokens[:1] == ("cd",)
        and len(source_tokens) > 3
        and source_tokens[3] not in component_tokens
    )
    family_token_count = 4 if has_named_family_token else 3
    if shared_tokens < family_token_count:
        return None
    if has_named_family_token:
        source_component = source_tokens[family_token_count] if len(source_tokens) > family_token_count else ""
        if source_component and not (source_component.isdigit() or source_component in {"body", "nude"}):
            return None
    if not has_named_family_token:
        source_tail = tuple(
            token for token in source_tokens[family_token_count:] if token not in component_tokens and token != "00"
        )
        candidate_tail = tuple(
            token for token in candidate_tokens[family_token_count:] if token not in component_tokens and token != "00"
        )
        if source_tail != candidate_tail:
            return None
    shared_characters = 0
    for left, right in zip(str(source_stem or "").casefold(), str(candidate_stem or "").casefold()):
        if left != right:
            break
        shared_characters += 1
    return shared_tokens, shared_characters


def _read_loose_appearance_payload(
    path: Path,
    stop_event: Optional[threading.Event] = None,
) -> bytes:
    raise_if_cancelled(stop_event)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"Could not inspect loose appearance file {path}: {exc}") from exc
    if size > _LOOSE_APPEARANCE_PAYLOAD_LIMIT:
        raise ValueError(
            f"Loose appearance file is too large: {path} ({size:,} bytes; limit {_LOOSE_APPEARANCE_PAYLOAD_LIMIT:,})"
        )
    chunks: list[bytes] = []
    try:
        with path.open("rb") as handle:
            while True:
                raise_if_cancelled(stop_event)
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
    except OSError as exc:
        raise ValueError(f"Could not read loose appearance file {path}: {exc}") from exc
    raise_if_cancelled(stop_event)
    return b"".join(chunks)


def _loose_prefabdata_references(text: str) -> tuple[tuple[str, str], ...]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return ()
    role_names = {
        "skeletonname",
        "skeletonvariationname",
        "morphtargetset",
        "morphtargetsetname",
    }
    references: list[tuple[str, str]] = []
    for element in root.iter():
        tag = str(element.tag).rsplit("}", 1)[-1].casefold()
        for key, raw_value in element.attrib.items():
            value = html.unescape(str(raw_value or "")).replace("\\", "/").strip()
            key_name = str(key or "").casefold()
            if not value:
                continue
            role = tag if key_name == "filename" and tag in role_names else key_name
            if role in role_names:
                references.append((role, value))
            elif key_name == "filename" and PurePosixPath(value).suffix.casefold() in {".pac", ".pam", ".pamlod"}:
                references.append(("model", value))
    return tuple(dict.fromkeys(references))


def _loose_app_prefab_names(text: str) -> tuple[str, ...]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return ()
    names: list[str] = []
    for element in root.iter():
        if str(element.tag).rsplit("}", 1)[-1].casefold() != "prefab":
            continue
        name = str(element.attrib.get("Name") or element.attrib.get("name") or "").strip()
        if name:
            names.append(name.casefold())
    return tuple(dict.fromkeys(names))


def _loose_app_sibling_descriptors(
    descriptor_path: Path,
    *,
    model_virtual_path: str,
    package_root: Path,
    by_virtual: Mapping[str, Path],
    by_basename: Mapping[str, Sequence[Path]],
    stop_event: Optional[threading.Event],
) -> tuple[Path, ...]:
    descriptor_virtual = _loose_virtual_path(package_root, descriptor_path)
    descriptor_stem = PurePosixPath(descriptor_virtual).name.split(".prefabdata", 1)[0]
    siblings: dict[str, Path] = {}
    for app_virtual, app_path in sorted(by_virtual.items()):
        raise_if_cancelled(stop_event)
        if not app_virtual.endswith(".app_xml"):
            continue
        prefab_names = _loose_app_prefab_names(
            _read_loose_appearance_payload(app_path, stop_event).decode("utf-8-sig", "replace")
        )
        if descriptor_stem not in prefab_names:
            continue
        for prefab_name in prefab_names:
            for suffix in (".prefabdata_xml", ".prefabdata.xml"):
                for candidate in tuple(by_basename.get(f"{prefab_name}{suffix}", ()) or ()):
                    if candidate != descriptor_path:
                        siblings.setdefault(str(candidate).casefold(), candidate)
    return tuple(
        sorted(
            siblings.values(),
            key=lambda candidate: _loose_candidate_score(model_virtual_path, package_root, candidate),
            reverse=True,
        )
    )


def _resolve_loose_reference(
    raw_value: str,
    role: str,
    *,
    model_virtual_path: str,
    package_root: Path,
    by_virtual: Mapping[str, Path],
    by_basename: Mapping[str, Sequence[Path]],
) -> Path | None:
    value = _normalized_path(raw_value)
    role_name = str(role or "").casefold()
    expected_extension = {
        "skeletonname": ".pab",
        "skeletonvariationname": ".pabc",
        "morphtargetset": ".pamt",
        "morphtargetsetname": ".pamt",
    }.get(role_name, PurePosixPath(value).suffix.casefold())
    if expected_extension and not PurePosixPath(value).suffix:
        value += expected_extension
    attempted = [value]
    if value and not value.startswith("character/"):
        if expected_extension == ".pabc":
            attempted.append(f"character/binary/skeletonvariation/{value}")
        elif expected_extension in {".pab", ".pamt"}:
            attempted.append(f"character/model/{value}")
    candidates: dict[str, Path] = {}
    for attempted_path in attempted:
        direct = by_virtual.get(_normalized_path(attempted_path))
        if direct is not None:
            candidates.setdefault(str(direct).casefold(), direct)
    basename = PurePosixPath(value).name.casefold()
    for candidate in tuple(by_basename.get(basename, ()) or ()):
        if expected_extension and candidate.suffix.casefold() != expected_extension:
            continue
        candidates.setdefault(str(candidate).casefold(), candidate)
    if not candidates:
        return None
    attempted_set = {_normalized_path(path) for path in attempted}
    return max(
        candidates.values(),
        key=lambda candidate: (
            int(_loose_virtual_path(package_root, candidate) in attempted_set),
            int(any(_loose_virtual_path(package_root, candidate).endswith(path) for path in attempted_set)),
            _shared_prefix_length(model_virtual_path, _loose_virtual_path(package_root, candidate)),
            _loose_virtual_path(package_root, candidate),
        ),
    )


def _resolve_loose_sibling_morph_context(
    descriptor_path: Path,
    *,
    model_virtual_path: str,
    package_root: Path,
    by_virtual: Mapping[str, Path],
    by_basename: Mapping[str, Sequence[Path]],
    stop_event: Optional[threading.Event],
) -> tuple[Path, Path] | None:
    descriptor_virtual = _loose_virtual_path(package_root, descriptor_path)
    descriptor_parent = PurePosixPath(descriptor_virtual).parent
    descriptor_namespace = PurePosixPath(descriptor_virtual).parts[:4]
    descriptor_stem = PurePosixPath(descriptor_virtual).name.split(".prefabdata", 1)[0]
    candidates: list[tuple[tuple[int, int, int, str], Path, Path]] = []
    for virtual_path, candidate in by_virtual.items():
        raise_if_cancelled(stop_event)
        if candidate == descriptor_path:
            continue
        if not (virtual_path.endswith(".prefabdata_xml") or virtual_path.endswith(".prefabdata.xml")):
            continue
        if PurePosixPath(virtual_path).parts[:4] != descriptor_namespace:
            continue
        references = dict(
            _loose_prefabdata_references(
                _read_loose_appearance_payload(candidate, stop_event).decode("utf-8-sig", "replace")
            )
        )
        morph_reference = references.get("morphtargetset") or references.get("morphtargetsetname") or ""
        if not morph_reference:
            continue
        morph_path = _resolve_loose_reference(
            morph_reference,
            "morphtargetset",
            model_virtual_path=model_virtual_path,
            package_root=package_root,
            by_virtual=by_virtual,
            by_basename=by_basename,
        )
        if morph_path is None:
            continue
        candidate_stem = PurePosixPath(virtual_path).name.split(".prefabdata", 1)[0]
        family_rank = _loose_descriptor_family_rank(descriptor_stem, candidate_stem)
        if family_rank is None:
            continue
        rank = (
            *family_rank,
            int(PurePosixPath(virtual_path).parent == descriptor_parent),
            virtual_path,
        )
        candidates.append((rank, candidate, morph_path))
    if not candidates:
        return None
    _rank, selected_descriptor, selected_morph = max(candidates, key=lambda item: item[0])
    return selected_descriptor, selected_morph


def _select_loose_character_descriptor(
    stem: str,
    *,
    model_virtual_path: str,
    package_root: Path,
    by_virtual: Mapping[str, Path],
    by_basename: Mapping[str, Sequence[Path]],
    stop_event: Optional[threading.Event],
) -> tuple[Path | None, tuple[tuple[str, str], ...]]:
    exact = tuple(dict.fromkeys((
        *tuple(by_basename.get(f"{stem}.prefabdata_xml", ()) or ()),
        *tuple(by_basename.get(f"{stem}.prefabdata.xml", ()) or ()),
    )))
    if exact:
        selected = max(
            exact,
            key=lambda candidate: _loose_candidate_score(model_virtual_path, package_root, candidate),
        )
        text = _read_loose_appearance_payload(selected, stop_event).decode("utf-8-sig", "replace")
        return selected, _loose_prefabdata_references(text)
    ranked: list[tuple[tuple[object, ...], Path, tuple[tuple[str, str], ...]]] = []
    for virtual_path, candidate in by_virtual.items():
        raise_if_cancelled(stop_event)
        if not (virtual_path.endswith(".prefabdata_xml") or virtual_path.endswith(".prefabdata.xml")):
            continue
        text = _read_loose_appearance_payload(candidate, stop_event).decode("utf-8-sig", "replace")
        candidate_references = _loose_prefabdata_references(text)
        candidate_stem = PurePosixPath(virtual_path).name.split(".prefabdata", 1)[0]
        family_rank = _loose_descriptor_family_rank(stem, candidate_stem)
        references_model = any(
            role == "model" and (
                _normalized_path(value) == model_virtual_path
                or model_virtual_path.endswith(_normalized_path(value))
                or PurePosixPath(_normalized_path(value)).name == PurePosixPath(model_virtual_path).name
            )
            for role, value in candidate_references
        )
        if references_model or family_rank is not None:
            rank = (
                int(references_model),
                family_rank or (0, 0),
                _loose_candidate_score(model_virtual_path, package_root, candidate),
            )
            ranked.append((rank, candidate, candidate_references))
    if not ranked:
        return None, ()
    _rank, selected, references = max(ranked, key=lambda item: item[0])
    return selected, references


def resolve_loose_character_appearance_sources(
    source_path: Path | str,
    *,
    stop_event: Optional[threading.Event] = None,
) -> LooseCharacterAppearanceSources | None:
    """Resolve a preserved ``character/`` dependency tree around a loose PAC."""

    model_path = Path(source_path).expanduser().resolve()
    if model_path.suffix.casefold() != ".pac" or not model_path.is_file():
        return None
    package_root = _loose_character_package_root(model_path)
    manifest_index = _manifest_appearance_index(package_root, stop_event=stop_event)
    if manifest_index is None:
        by_virtual, by_basename = _loose_appearance_index(package_root, stop_event=stop_event)
        expected_hashes: dict[str, str] = {}
        manifest_path = None
    else:
        by_virtual, by_basename, expected_hashes, manifest_path = manifest_index
    model_virtual_path = _loose_virtual_path(package_root, model_path)
    if manifest_path is not None and model_virtual_path not in by_virtual:
        raise ValueError(f"Loose PAC is not listed by {manifest_path.name}: {model_virtual_path}")
    stem = model_path.stem.casefold()
    descriptor_path, descriptor_references = _select_loose_character_descriptor(
        stem,
        model_virtual_path=model_virtual_path,
        package_root=package_root,
        by_virtual=by_virtual,
        by_basename=by_basename,
        stop_event=stop_event,
    )
    references: dict[str, str] = {}
    for role, value in descriptor_references:
        references.setdefault(role, value)

    skeleton_path = _resolve_loose_reference(
        references.get("skeletonname", ""),
        "skeletonname",
        model_virtual_path=model_virtual_path,
        package_root=package_root,
        by_virtual=by_virtual,
        by_basename=by_basename,
    ) if references.get("skeletonname") else None
    skeleton_descriptor_path = descriptor_path if skeleton_path is not None else None
    variation_path = _resolve_loose_reference(
        references.get("skeletonvariationname", ""),
        "skeletonvariationname",
        model_virtual_path=model_virtual_path,
        package_root=package_root,
        by_virtual=by_virtual,
        by_basename=by_basename,
    ) if references.get("skeletonvariationname") else None
    morph_reference = references.get("morphtargetset") or references.get("morphtargetsetname") or ""
    morph_target_path = _resolve_loose_reference(
        morph_reference,
        "morphtargetset",
        model_virtual_path=model_virtual_path,
        package_root=package_root,
        by_virtual=by_virtual,
        by_basename=by_basename,
    ) if morph_reference else None
    morph_descriptor_path = descriptor_path if morph_target_path is not None else None
    if morph_target_path is None and descriptor_path is not None:
        sibling_morph = _resolve_loose_sibling_morph_context(
            descriptor_path,
            model_virtual_path=model_virtual_path,
            package_root=package_root,
            by_virtual=by_virtual,
            by_basename=by_basename,
            stop_event=stop_event,
        )
        if sibling_morph is not None:
            morph_descriptor_path, morph_target_path = sibling_morph

    if variation_path is None:
        pabc_candidates = tuple(by_basename.get(f"{stem}.pabc", ()) or ())
        if pabc_candidates:
            variation_path = max(
                pabc_candidates,
                key=lambda candidate: _loose_candidate_score(model_virtual_path, package_root, candidate),
            )
    if skeleton_path is None and descriptor_path is not None:
        for sibling_descriptor in _loose_app_sibling_descriptors(
            descriptor_path,
            model_virtual_path=model_virtual_path,
            package_root=package_root,
            by_virtual=by_virtual,
            by_basename=by_basename,
            stop_event=stop_event,
        ):
            sibling_references = dict(
                _loose_prefabdata_references(
                    _read_loose_appearance_payload(sibling_descriptor, stop_event).decode("utf-8-sig", "replace")
                )
            )
            sibling_skeleton_reference = sibling_references.get("skeletonname", "")
            if not sibling_skeleton_reference:
                continue
            skeleton_path = _resolve_loose_reference(
                sibling_skeleton_reference,
                "skeletonname",
                model_virtual_path=model_virtual_path,
                package_root=package_root,
                by_virtual=by_virtual,
                by_basename=by_basename,
            )
            if skeleton_path is not None:
                skeleton_descriptor_path = sibling_descriptor
                break
    if skeleton_path is None:
        for basename in iter_pab_candidate_basenames(model_virtual_path):
            candidates = tuple(by_basename.get(basename.casefold(), ()) or ())
            if candidates:
                skeleton_path = max(
                    candidates,
                    key=lambda candidate: _loose_candidate_score(model_virtual_path, package_root, candidate),
                )
                break
    if variation_path is None and morph_target_path is None:
        return None
    return LooseCharacterAppearanceSources(
        package_root=package_root,
        model_virtual_path=model_virtual_path,
        descriptor_path=descriptor_path,
        skeleton_descriptor_path=skeleton_descriptor_path,
        morph_descriptor_path=morph_descriptor_path,
        skeleton_path=skeleton_path,
        skeleton_variation_path=variation_path,
        morph_target_path=morph_target_path,
        manifest_path=manifest_path,
        expected_hashes=tuple(sorted(expected_hashes.items())),
    )


def apply_loose_character_appearance(
    source_path: Path | str,
    parsed_mesh: ParsedMesh,
    pac_data: bytes,
    *,
    include_morph_targets: bool = False,
    stop_event: Optional[threading.Event] = None,
) -> tuple[ParsedMesh, tuple[str, ...]]:
    """Apply companions from an extracted dependency tree to a presentation clone."""

    if str(getattr(parsed_mesh, "format", "") or "").casefold() != "pac":
        return parsed_mesh, ()
    sources = resolve_loose_character_appearance_sources(source_path, stop_event=stop_event)
    if sources is None:
        return parsed_mesh, ()
    if sources.skeleton_path is None:
        raise ValueError("Loose character appearance package does not contain its referenced PAB skeleton")
    expected_hashes = dict(sources.expected_hashes)

    def read_verified(path: Path) -> bytes:
        payload = _read_loose_appearance_payload(path, stop_event)
        virtual_path = _loose_virtual_path(sources.package_root, path)
        expected_hash = expected_hashes.get(virtual_path, "")
        if expected_hash and hashlib.sha256(payload).hexdigest().casefold() != expected_hash:
            raise ValueError(f"Character appearance bundle hash mismatch: {virtual_path}")
        return payload

    model_expected_hash = expected_hashes.get(sources.model_virtual_path, "")
    if model_expected_hash and hashlib.sha256(pac_data).hexdigest().casefold() != model_expected_hash:
        raise ValueError(f"Character appearance bundle hash mismatch: {sources.model_virtual_path}")
    skeleton = parse_pab(
        read_verified(sources.skeleton_path),
        sources.skeleton_path.as_posix(),
    )
    palette = tuple(resolve_pac_bone_palette(pac_data, skeleton))
    if not palette:
        raise ValueError("Loose PAC bone palette was not resolved against the bundled PAB skeleton")
    variation = None
    if sources.skeleton_variation_path is not None:
        variation = parse_pabc_skeleton_variation(
            read_verified(sources.skeleton_variation_path),
            sources.skeleton_variation_path.as_posix(),
            skeleton=skeleton,
        )
    morph_target_set = None
    if include_morph_targets and sources.morph_target_path is not None:
        morph_target_set = parse_pamt_morph_target_set(
            read_verified(sources.morph_target_path),
            sources.morph_target_path.as_posix(),
        )
    deformed = apply_skeleton_variation_to_mesh(
        parsed_mesh,
        skeleton,
        palette,
        variation,
        morph_target_set=morph_target_set,
    )
    notes: list[str] = []
    if variation is not None and sources.skeleton_variation_path is not None:
        notes.append(
            f"Applied bundled character skeleton variation {sources.skeleton_variation_path.as_posix()} "
            f"({variation.matched_record_count:,}/{variation.record_count:,} records matched the PAB)."
        )
    if morph_target_set is not None and sources.morph_target_path is not None:
        notes.append(
            f"Recovered {max(0, morph_target_set.target_count - 1):,} appearance shape target(s) "
            f"from bundled {sources.morph_target_path.as_posix()}."
        )
    return deformed, tuple(notes)


def apply_loose_character_appearance_for_preview(
    source_path: Path | str,
    parsed_mesh: ParsedMesh,
    pac_data: bytes,
    *,
    stop_event: Optional[threading.Event] = None,
) -> tuple[ParsedMesh, tuple[str, ...]]:
    try:
        return apply_loose_character_appearance(
            source_path,
            parsed_mesh,
            pac_data,
            stop_event=stop_event,
        )
    except RunCancelled:
        raise
    except Exception as exc:
        return parsed_mesh, (f"Bundled character appearance was not applied for {source_path}: {exc}",)


def _related_appearance_entries(
    model_entry: ArchiveEntry,
    *,
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
    context_entries: Sequence[ArchiveEntry],
) -> tuple[ArchiveEntry, ...]:
    if context_entries:
        return _sorted_candidates(model_entry.path, context_entries)
    related: list[ArchiveEntry] = []
    relationship_plan = build_archive_relationship_plan(
        model_entry,
        (),
        path_index=path_index,
        basename_index=basename_index,
    )
    related.extend(
        edge.related_entry
        for edge in relationship_plan.edges
        if isinstance(getattr(edge, "related_entry", None), ArchiveEntry)
    )
    model_stem = PurePosixPath(str(model_entry.path or "").replace("\\", "/")).stem.casefold()
    descriptors: list[ArchiveEntry] = []
    for suffix in (".prefabdata_xml", ".prefabdata.xml"):
        descriptors.extend(tuple(basename_index.get(f"{model_stem}{suffix}", ()) or ()))
    for descriptor in _sorted_candidates(model_entry.path, descriptors):
        related.append(descriptor)
        descriptor_plan = build_archive_relationship_plan(
            descriptor,
            (),
            path_index=path_index,
            basename_index=basename_index,
        )
        related.extend(
            edge.related_entry
            for edge in descriptor_plan.edges
            if isinstance(getattr(edge, "related_entry", None), ArchiveEntry)
        )
    return _sorted_candidates(model_entry.path, related)


def _indexed_skeleton_for_variation(
    model_entry: ArchiveEntry,
    pac_data: bytes,
    pabc_data: bytes | None,
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
    read_payload,
) -> tuple[object, tuple[int, ...]] | None:
    """Resolve the small exact PAB candidate set without scanning every descriptor."""

    best: tuple[tuple[int, int, int], object, tuple[int, ...]] | None = None
    for priority, basename in enumerate(iter_pab_candidate_basenames(model_entry.path)):
        for entry in _sorted_candidates(model_entry.path, tuple(basename_index.get(basename.casefold(), ()) or ())):
            try:
                candidate = parse_pab(read_payload(entry), entry.path)
                palette = tuple(resolve_pac_bone_palette(pac_data, candidate))
                variation = (
                    parse_pabc_skeleton_variation(pabc_data, skeleton=candidate)
                    if pabc_data is not None
                    else None
                )
            except Exception:
                continue
            score = (
                variation.matched_record_count if variation is not None else 0,
                len(palette),
                -priority,
            )
            if palette and (best is None or score > best[0]):
                best = score, candidate, palette
    if best is None:
        return None
    if pabc_data is not None and best[0][0] <= 0:
        return None
    return best[1], best[2]


def apply_archive_mesh_appearance(
    model_entry: ArchiveEntry,
    parsed_mesh: ParsedMesh,
    pac_data: bytes,
    *,
    archive_entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]],
    archive_entries_by_basename: Mapping[str, Sequence[ArchiveEntry]],
    context_entries: Sequence[ArchiveEntry] = (),
    include_morph_targets: bool = False,
    skeleton: object | None = None,
    bone_palette: Sequence[int] | None = None,
    stop_event: Optional[threading.Event] = None,
) -> tuple[ParsedMesh, tuple[str, ...]]:
    """Return a presentation clone with its linked PABC/PAMT appearance."""

    if str(getattr(parsed_mesh, "format", "") or "").lower() != "pac":
        return parsed_mesh, ()
    raise_if_cancelled(stop_event)
    related = _related_appearance_entries(
        model_entry,
        path_index=archive_entries_by_normalized_path,
        basename_index=archive_entries_by_basename,
        context_entries=context_entries,
    )
    def read_payload(entry: ArchiveEntry) -> bytes:
        raise_if_cancelled(stop_event)
        payload, _decompressed, _note = read_archive_entry_data(entry, stop_event=stop_event)
        return payload

    descriptor_resolution = resolve_skeleton_descriptor_for_model(
        model_entry,
        (),
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
        read_entry_data=read_payload,
    )
    pabc_candidates = tuple(entry for entry in related if str(entry.extension or "").lower() == ".pabc")
    pamt_candidates = tuple(entry for entry in related if str(entry.extension or "").lower() == ".pamt")
    pabc_entry = descriptor_resolution.skeleton_variation_entry or (pabc_candidates[0] if pabc_candidates else None)
    pamt_entry = descriptor_resolution.morph_target_entry or (pamt_candidates[0] if pamt_candidates else None)
    if pabc_entry is None and not (include_morph_targets and pamt_entry is not None):
        return parsed_mesh, ()
    pabc_data = read_payload(pabc_entry) if pabc_entry is not None else None
    resolved_skeleton = skeleton
    palette = tuple(int(value) for value in (bone_palette or ()))
    if resolved_skeleton is None:
        if descriptor_resolution.skeleton_entry is not None:
            resolved_skeleton = parse_pab(
                read_payload(descriptor_resolution.skeleton_entry),
                descriptor_resolution.skeleton_entry.path,
            )
            palette = tuple(resolve_pac_bone_palette(pac_data, resolved_skeleton))
        else:
            indexed = _indexed_skeleton_for_variation(
                model_entry, pac_data, pabc_data, archive_entries_by_basename, read_payload
            )
            if indexed is not None:
                resolved_skeleton, palette = indexed
            else:
                skeleton_entry, report = resolve_skeleton_for_model(
                    model_entry,
                    (),
                    archive_entries_by_normalized_path=archive_entries_by_normalized_path,
                    archive_entries_by_basename=archive_entries_by_basename,
                    pac_data=pac_data,
                    read_entry_data=read_payload,
                )
                if skeleton_entry is None:
                    detail = report.blocking_errors[0] if report.blocking_errors else "matching PAB skeleton was not resolved"
                    raise ValueError(detail)
                resolved_skeleton = parse_pab(read_payload(skeleton_entry), skeleton_entry.path)
    if not palette:
        palette = tuple(resolve_pac_bone_palette(pac_data, resolved_skeleton))
    if not palette:
        raise ValueError("PAC bone palette was not resolved against the character skeleton")

    variation = (
        parse_pabc_skeleton_variation(pabc_data, pabc_entry.path, skeleton=resolved_skeleton)
        if pabc_entry is not None and pabc_data is not None
        else None
    )
    morph_target_set = None
    if include_morph_targets:
        if pamt_entry is not None:
            morph_target_set = parse_pamt_morph_target_set(read_payload(pamt_entry), pamt_entry.path)
    deformed = apply_skeleton_variation_to_mesh(
        parsed_mesh,
        resolved_skeleton,
        palette,
        variation,
        morph_target_set=morph_target_set,
    )
    notes = []
    if variation is not None and pabc_entry is not None:
        notes.append(
            f"Applied character skeleton variation {pabc_entry.path} "
            f"({variation.matched_record_count:,}/{variation.record_count:,} records matched the PAB)."
        )
    if morph_target_set is not None and pamt_entry is not None:
        notes.append(
            f"Recovered {max(0, morph_target_set.target_count - 1):,} appearance shape target(s) from {pamt_entry.path}."
        )
    return deformed, tuple(notes)


def apply_archive_mesh_appearance_for_preview(
    model_entry: ArchiveEntry,
    parsed_mesh: ParsedMesh,
    pac_data: bytes,
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
    context_entries: Sequence[ArchiveEntry],
    stop_event: Optional[threading.Event],
) -> tuple[ParsedMesh, tuple[str, ...]]:
    """Preview-safe wrapper that reports a fallback instead of hiding the mesh."""

    try:
        return apply_archive_mesh_appearance(
            model_entry,
            parsed_mesh,
            pac_data,
            archive_entries_by_normalized_path=path_index,
            archive_entries_by_basename=basename_index,
            context_entries=context_entries,
            stop_event=stop_event,
        )
    except RunCancelled:
        raise
    except Exception as exc:
        return parsed_mesh, (f"Character appearance deformation was not applied for {model_entry.path}: {exc}",)


def apply_archive_mesh_appearance_to_preview_model(
    entry: ArchiveEntry,
    data: bytes,
    model_preview: ModelPreviewData,
    parsed_mesh: ParsedMesh,
    *,
    path_index: Optional[Mapping[str, Sequence[ArchiveEntry]]],
    basename_index: Optional[Mapping[str, Sequence[ArchiveEntry]]],
    stop_event: Optional[threading.Event],
) -> tuple[ModelPreviewData, ParsedMesh, tuple[str, ...]]:
    """Apply appearance when archive indexes are available, preserving fallback."""

    if path_index is None or basename_index is None:
        return model_preview, parsed_mesh, ()
    appearance_mesh, notes = apply_archive_mesh_appearance_for_preview(
        entry,
        parsed_mesh,
        data,
        path_index,
        basename_index,
        (),
        stop_event,
    )
    if appearance_mesh is parsed_mesh:
        return model_preview, parsed_mesh, notes
    from cdmw.core.archive_mesh_import_scene_preview import parsed_mesh_to_preview_model

    return parsed_mesh_to_preview_model(appearance_mesh), appearance_mesh, notes


__all__ = [
    "CHARACTER_APPEARANCE_BUNDLE_FILENAME",
    "CHARACTER_APPEARANCE_BUNDLE_FORMAT",
    "LooseCharacterAppearanceSources",
    "apply_archive_mesh_appearance",
    "apply_archive_mesh_appearance_for_preview",
    "apply_archive_mesh_appearance_to_preview_model",
    "apply_loose_character_appearance",
    "apply_loose_character_appearance_for_preview",
    "resolve_loose_character_appearance_sources",
    "write_character_appearance_bundle_manifest",
]
