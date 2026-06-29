from __future__ import annotations

import dataclasses
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping, Optional, Sequence

from cdmw.core.archive import parse_archive_pamt, read_archive_entry_data
from cdmw.core.mod_package import is_mod_package_payload_path, normalize_mod_package_payload_path
from cdmw.models import ArchiveEntry


SourceMixLayerKind = str
SourceMixStrategy = str


@dataclasses.dataclass(frozen=True, slots=True)
class SourceMixLayer:
    source_id: str
    label: str
    kind: SourceMixLayerKind
    root: Path | None = None
    source_path: Path | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class SourceMixCandidate:
    virtual_path: str
    display_path: str
    layer: SourceMixLayer
    extension: str
    size: int
    target_archive_entry: ArchiveEntry | None = None
    source_path: Path | None = None
    source_archive_entry: ArchiveEntry | None = None
    role: str = ""
    family_id: str = ""
    match_status: str = ""
    confidence: str = ""
    conflict_status: str = ""
    default_action: str = "skip"
    _payload_reader: Callable[[], bytes] | None = dataclasses.field(default=None, repr=False, compare=False)

    @property
    def normalized_virtual_path(self) -> str:
        return normalize_source_mix_virtual_path(self.virtual_path)

    def read_payload(self) -> bytes:
        if self._payload_reader is not None:
            return self._payload_reader()
        if self.source_archive_entry is not None:
            data, _decompressed, _note = read_archive_entry_data(self.source_archive_entry)
            return data
        if self.source_path is not None:
            return self.source_path.read_bytes()
        raise ValueError(f"Source mix candidate has no readable payload: {self.display_path}")


@dataclasses.dataclass(frozen=True, slots=True)
class SourceMixSelection:
    virtual_path: str
    chosen_candidate: SourceMixCandidate | None = None
    strategy: SourceMixStrategy = "keep_target"

    @property
    def normalized_virtual_path(self) -> str:
        return normalize_source_mix_virtual_path(self.virtual_path)


@dataclasses.dataclass(frozen=True, slots=True)
class SourceMixValidationResult:
    blocking_errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.blocking_errors


def normalize_source_mix_virtual_path(path_value: str | Path) -> str:
    return normalize_mod_package_payload_path(path_value).as_posix().strip("/").lower()


def _display_virtual_path(path_value: str | Path) -> str:
    normalized = normalize_mod_package_payload_path(path_value).as_posix().strip("/")
    return normalized or str(path_value or "").replace("\\", "/").strip().strip("/")


def _extension_for_virtual_path(path_value: str | Path) -> str:
    return PurePosixPath(str(path_value or "").replace("\\", "/")).suffix.lower()


def _normalized_parts(path_value: str | Path) -> tuple[str, ...]:
    normalized = normalize_source_mix_virtual_path(path_value)
    return tuple(part for part in normalized.split("/") if part)


def _strip_known_texture_suffix(stem: str) -> str:
    lowered = stem.casefold()
    for suffix in (
        "_base",
        "_diff",
        "_diffuse",
        "_color",
        "_albedo",
        "_n",
        "_normal",
        "_ma",
        "_mg",
        "_m",
        "_sp",
        "_mask",
        "_h",
        "_height",
        "_disp",
        "_d",
        "_ao",
    ):
        if lowered.endswith(suffix) and len(lowered) > len(suffix) + 2:
            return lowered[: -len(suffix)]
    return lowered


def source_mix_role_for_virtual_path(path_value: str | Path) -> str:
    """Classify loose/source-mix rows into user-facing asset roles."""
    normalized = normalize_source_mix_virtual_path(path_value)
    suffix = PurePosixPath(normalized).suffix.lower()
    basename = PurePosixPath(normalized).name.casefold()
    if basename.endswith(".sockets.xml") or "socket" in basename and suffix == ".xml":
        return "Socket XML"
    if suffix in {".pac", ".pam", ".pamlod"}:
        return "Model"
    if suffix in {".pac_xml", ".pam_xml", ".pamlod_xml", ".pami", ".pamhc", ".material"}:
        return "Material"
    if suffix in {".dds", ".seqmt", ".png", ".tga"}:
        return "Texture"
    if suffix in {".hkx", ".hkt"}:
        return "Physics HKX"
    if suffix == ".meshinfo":
        return "MeshInfo"
    if suffix in {".prefab", ".prefabdata_xml", ".app_xml", ".pappt"}:
        return "Prefab / Metadata"
    if suffix in {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh", ".papr"}:
        return "Skeleton / Rig"
    if suffix in {
        ".paa",
        ".paa_metabin",
        ".pae",
        ".paem",
        ".motionblending",
        ".paseq",
        ".paseqc",
        ".paschedule",
        ".paschedulepath",
        ".pastage",
    }:
        return "Animation / Motion"
    return "Other"


def source_mix_family_id_for_virtual_path(path_value: str | Path) -> str:
    """Return a stable loose-mod family key for grouping companion files."""
    normalized = normalize_source_mix_virtual_path(path_value)
    if not normalized:
        return ""
    parts = _normalized_parts(normalized)
    path = PurePosixPath(normalized)
    name = path.name.casefold()
    parent_parts = list(parts[:-1])
    if "modelproperty" in parent_parts:
        parent_parts[parent_parts.index("modelproperty")] = "model"
    if "bin__" in parent_parts and "meshphysics" in parent_parts:
        parent_parts[parent_parts.index("bin__")] = "model"
        parent_parts.remove("meshphysics")
    if name.endswith(".sockets.xml"):
        stem = name[: -len(".sockets.xml")]
    elif name.endswith(".pac_xml"):
        stem = name[: -len(".pac_xml")]
    elif name.endswith(".pam_xml"):
        stem = name[: -len(".pam_xml")]
    elif name.endswith(".pamlod_xml"):
        stem = name[: -len(".pamlod_xml")]
    else:
        stem = PurePosixPath(name).stem.casefold()
    if PurePosixPath(name).suffix.lower() in {".dds", ".png", ".tga", ".seqmt"}:
        stem = _strip_known_texture_suffix(stem)
    parent = "/".join(parent_parts)
    return f"{parent}/{stem}".strip("/")


def _layer_id(kind: str, label: str, source_path: Path | None = None) -> str:
    base = f"{kind}:{label}".strip(":")
    if source_path is not None:
        base = f"{kind}:{source_path.expanduser().resolve()}"
    return base.replace("\\", "/").lower()


def source_mix_layer_for_archive(label: str = "Loaded archive") -> SourceMixLayer:
    return SourceMixLayer(
        source_id=_layer_id("archive", label),
        label=label,
        kind="archive",
    )


def source_mix_layer_for_loose_folder(root: Path, label: str = "") -> SourceMixLayer:
    resolved = root.expanduser().resolve()
    return SourceMixLayer(
        source_id=_layer_id("loose_folder", label or resolved.name, resolved),
        label=label.strip() or resolved.name or resolved.as_posix(),
        kind="loose_folder",
        root=resolved,
        source_path=resolved,
    )


def source_mix_layer_for_mod_archive(source_path: Path, label: str = "") -> SourceMixLayer:
    resolved = source_path.expanduser().resolve()
    return SourceMixLayer(
        source_id=_layer_id("mod_archive", label or resolved.name, resolved),
        label=label.strip() or resolved.name or resolved.as_posix(),
        kind="mod_archive",
        root=resolved if resolved.is_dir() else resolved.parent,
        source_path=resolved,
    )


def _archive_candidate(
    entry: ArchiveEntry,
    layer: SourceMixLayer,
    *,
    target_archive_entry: ArchiveEntry | None = None,
) -> SourceMixCandidate:
    display_path = _display_virtual_path(entry.path)
    return SourceMixCandidate(
        virtual_path=display_path,
        display_path=display_path,
        layer=layer,
        extension=entry.extension,
        size=int(entry.orig_size or entry.comp_size or 0),
        target_archive_entry=target_archive_entry,
        source_archive_entry=entry,
        _payload_reader=lambda current_entry=entry: read_archive_entry_data(current_entry)[0],
    )


def _source_mix_candidate_conflict_status(
    candidate: SourceMixCandidate,
    grouped_by_path: Mapping[str, Sequence[SourceMixCandidate]],
) -> str:
    siblings = tuple(grouped_by_path.get(candidate.normalized_virtual_path, ()) or ())
    if len(siblings) <= 1:
        return "none"
    sizes = {int(getattr(sibling, "size", 0) or 0) for sibling in siblings}
    return "duplicate" if len(sizes) <= 1 else "conflict"


def enrich_source_mix_candidates(
    candidates: Sequence[SourceMixCandidate],
    *,
    target_entries_by_virtual_path: Mapping[str, ArchiveEntry] | None = None,
) -> tuple[SourceMixCandidate, ...]:
    """Add role/family/match metadata used by overlay review and asset-family flows."""
    target_map = target_entries_by_virtual_path or {}
    target_entries_by_basename: dict[tuple[str, str], list[ArchiveEntry]] = {}
    for target_entry in target_map.values():
        if not isinstance(target_entry, ArchiveEntry):
            continue
        target_name = PurePosixPath(str(target_entry.path or "").replace("\\", "/")).name.lower()
        target_extension = str(getattr(target_entry, "extension", "") or "").lower()
        if target_name:
            target_entries_by_basename.setdefault((target_name, target_extension), []).append(target_entry)
    grouped_by_path = group_source_mix_candidates_by_virtual_path(candidates)
    enriched: list[SourceMixCandidate] = []
    for candidate in candidates:
        normalized = candidate.normalized_virtual_path
        target_entry = candidate.target_archive_entry or target_map.get(normalized)
        match_status = "exact" if target_entry is not None else "extra"
        confidence = "Exact virtual path" if target_entry is not None else "Extra source file"
        if target_entry is None:
            candidate_name = PurePosixPath(candidate.display_path.replace("\\", "/")).name.lower()
            candidate_extension = _extension_for_virtual_path(candidate.display_path)
            basename_matches = target_entries_by_basename.get((candidate_name, candidate_extension), ())
            if len(basename_matches) == 1:
                target_entry = basename_matches[0]
                match_status = "basename"
                confidence = "Matched archive target by filename; common for compact or CrimsonForge-style loose packages."
            elif len(basename_matches) > 1:
                confidence = "Extra source file; filename matched multiple archive targets, so no target was chosen automatically."
        default_action = "replace" if target_entry is not None else "skip"
        conflict_status = _source_mix_candidate_conflict_status(candidate, grouped_by_path)
        if conflict_status == "conflict":
            default_action = "resolve"
        enriched.append(
            dataclasses.replace(
                candidate,
                target_archive_entry=target_entry,
                role=source_mix_role_for_virtual_path(candidate.virtual_path),
                family_id=source_mix_family_id_for_virtual_path(candidate.virtual_path),
                match_status=match_status,
                confidence=confidence,
                conflict_status=conflict_status,
                default_action=default_action,
            )
        )
    return tuple(enriched)


def scan_archive_entries_source(
    entries: Sequence[ArchiveEntry],
    *,
    label: str = "Loaded archive",
    target_entries_by_virtual_path: Mapping[str, ArchiveEntry] | None = None,
) -> tuple[SourceMixCandidate, ...]:
    layer = source_mix_layer_for_archive(label)
    candidates = tuple(
        _archive_candidate(
            entry,
            layer,
            target_archive_entry=(
                target_entries_by_virtual_path or {}
            ).get(normalize_source_mix_virtual_path(entry.path), entry),
        )
        for entry in entries
        if isinstance(entry, ArchiveEntry) and normalize_source_mix_virtual_path(entry.path)
    )
    return enrich_source_mix_candidates(
        candidates,
        target_entries_by_virtual_path=target_entries_by_virtual_path,
    )


def _iter_loose_payload_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and not any(part.startswith(".") for part in path.relative_to(root).parts):
            yield path


def _loose_virtual_path(root: Path, path: Path) -> str:
    resolved_root = root.expanduser().resolve()
    resolved_path = path.expanduser().resolve()
    try:
        relative = resolved_path.relative_to(resolved_root)
    except ValueError:
        relative = Path(resolved_path.name)
    return _display_virtual_path(relative)


def scan_loose_folder_source(
    root: Path,
    *,
    label: str = "",
    target_entries_by_virtual_path: Mapping[str, ArchiveEntry] | None = None,
) -> tuple[SourceMixCandidate, ...]:
    resolved_root = root.expanduser().resolve()
    if not resolved_root.exists():
        raise FileNotFoundError(f"Loose source folder does not exist: {resolved_root}")
    layer = source_mix_layer_for_loose_folder(resolved_root, label=label)
    candidates: list[SourceMixCandidate] = []
    for path in _iter_loose_payload_files(resolved_root):
        display_path = _loose_virtual_path(resolved_root if resolved_root.is_dir() else resolved_root.parent, path)
        normalized = normalize_source_mix_virtual_path(display_path)
        if not normalized or not is_mod_package_payload_path(display_path):
            continue
        candidates.append(
            SourceMixCandidate(
                virtual_path=display_path,
                display_path=_display_virtual_path(display_path),
                layer=layer,
                extension=_extension_for_virtual_path(display_path),
                size=path.stat().st_size,
                target_archive_entry=(target_entries_by_virtual_path or {}).get(normalized),
                source_path=path,
                _payload_reader=lambda current_path=path: current_path.read_bytes(),
            )
        )
    return enrich_source_mix_candidates(
        candidates,
        target_entries_by_virtual_path=target_entries_by_virtual_path,
    )


def _mod_archive_pamt_files(source_path: Path) -> tuple[Path, ...]:
    resolved = source_path.expanduser().resolve()
    if resolved.is_dir():
        return tuple(sorted(resolved.rglob("*.pamt")))
    if resolved.suffix.lower() == ".pamt":
        return (resolved,)
    if resolved.suffix.lower() == ".paz":
        candidates = [
            resolved.with_suffix(".pamt"),
            resolved.parent / "0.pamt",
        ]
        return tuple(path for path in candidates if path.is_file())
    return ()


def scan_mod_archive_source(
    source_path: Path,
    *,
    label: str = "",
    target_entries_by_virtual_path: Mapping[str, ArchiveEntry] | None = None,
) -> tuple[SourceMixCandidate, ...]:
    pamt_files = _mod_archive_pamt_files(source_path)
    if not pamt_files:
        raise FileNotFoundError(f"No .pamt files were found for source mod archive: {source_path}")
    layer = source_mix_layer_for_mod_archive(source_path, label=label)
    candidates: list[SourceMixCandidate] = []
    for pamt_path in pamt_files:
        for entry in parse_archive_pamt(pamt_path):
            normalized = normalize_source_mix_virtual_path(entry.path)
            if not normalized:
                continue
            candidates.append(
                _archive_candidate(
                    entry,
                    layer,
                    target_archive_entry=(target_entries_by_virtual_path or {}).get(normalized),
                )
            )
    return enrich_source_mix_candidates(
        candidates,
        target_entries_by_virtual_path=target_entries_by_virtual_path,
    )


def group_source_mix_candidates_by_virtual_path(
    candidates: Sequence[SourceMixCandidate],
) -> dict[str, list[SourceMixCandidate]]:
    grouped: dict[str, list[SourceMixCandidate]] = {}
    for candidate in candidates:
        normalized = candidate.normalized_virtual_path
        if normalized:
            grouped.setdefault(normalized, []).append(candidate)
    return grouped


def group_source_mix_candidates_by_family(
    candidates: Sequence[SourceMixCandidate],
) -> dict[str, list[SourceMixCandidate]]:
    grouped: dict[str, list[SourceMixCandidate]] = {}
    for candidate in candidates:
        family_id = candidate.family_id or source_mix_family_id_for_virtual_path(candidate.virtual_path)
        if family_id:
            grouped.setdefault(family_id, []).append(candidate)
    return grouped


_PAIRED_EXTENSION_COUNTERPARTS = {
    ".pabgb": ".pabgh",
    ".pabgh": ".pabgb",
}


def paired_counterpart_virtual_path(path_value: str | Path) -> str:
    display_path = _display_virtual_path(path_value)
    suffix = PurePosixPath(display_path).suffix.lower()
    counterpart_suffix = _PAIRED_EXTENSION_COUNTERPARTS.get(suffix)
    if not counterpart_suffix:
        return ""
    return normalize_source_mix_virtual_path(PurePosixPath(display_path).with_suffix(counterpart_suffix).as_posix())


def validate_source_mix_selections(
    selections: Sequence[SourceMixSelection],
) -> SourceMixValidationResult:
    selected_paths: set[str] = set()
    errors: list[str] = []
    warnings: list[str] = []
    for selection in selections:
        strategy = str(selection.strategy or "").strip().lower()
        if strategy not in {"replace", "include_extra"}:
            continue
        normalized = selection.normalized_virtual_path
        if not normalized:
            errors.append("A selected source row has an empty virtual path.")
            continue
        if selection.chosen_candidate is None:
            errors.append(f"No replacement source was selected for {normalized}.")
            continue
        selected_paths.add(normalized)
        if selection.chosen_candidate.target_archive_entry is None and strategy == "replace":
            errors.append(f"Replacement target is not present in the loaded archive: {selection.chosen_candidate.display_path}")

    for normalized in sorted(selected_paths):
        suffix = PurePosixPath(normalized).suffix.lower()
        if suffix not in _PAIRED_EXTENSION_COUNTERPARTS:
            continue
        counterpart = paired_counterpart_virtual_path(normalized)
        if counterpart and counterpart not in selected_paths:
            errors.append(
                f"Paired file selection is incomplete: {normalized} requires {counterpart}."
            )

    return SourceMixValidationResult(
        blocking_errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
    )
