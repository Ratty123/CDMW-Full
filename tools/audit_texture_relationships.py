from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Iterable, Mapping, Optional, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from cdmw.core.dds_native import inspect_dds_native
except Exception:  # pragma: no cover - exercised only when optional app deps fail
    inspect_dds_native = None  # type: ignore[assignment]


_CUSTOM_EXTENSIONS = (
    ".prefabdata.xml",
    ".prefabdata_xml",
    ".pamlod_xml",
    ".pac_xml",
    ".pam_xml",
    ".app_xml",
    ".sockets.xml",
)
_SIDECAR_EXTENSIONS = {
    ".pac_xml",
    ".pam_xml",
    ".pamlod_xml",
    ".pami",
    ".pamhc",
    ".pappt",
    ".prefab",
    ".prefabdata.xml",
    ".prefabdata_xml",
    ".xml",
    ".seqmt",
}
_HKX_EXTENSIONS = {".hkx", ".hkt"}
_PAB_EXTENSIONS = {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh", ".papr"}
_PREFAB_EXTENSIONS = {".prefab", ".prefabdata.xml", ".prefabdata_xml", ".pappt", ".pamhc"}
_DDS_SUFFIXES = tuple(
    sorted(
        {
            "_basecolor",
            "_diffuse",
            "_albedo",
            "_normalmap",
            "_normal",
            "_nrm",
            "_nm",
            "_mask_amg",
            "_specular",
            "_roughness",
            "_metallic",
            "_displacement",
            "_position",
            "_pivotpos",
            "_emissive",
            "_height",
            "_rough",
            "_metal",
            "_smooth",
            "_gloss",
            "_mask",
            "_dmap",
            "_bump",
            "_parallax",
            "_vector",
            "_velocity",
            "_depth",
            "_disp",
            "_base",
            "_spec",
            "_orm",
            "_rma",
            "_mra",
            "_arm",
            "_ao",
            "_ssdm",
            "_flow",
            "_pivot",
            "_emi",
            "_emc",
            "_ma",
            "_mg",
            "_sp",
            "_op",
            "_wn",
            "_dr",
            "_m",
            "_o",
            "_d",
            "_n",
        },
        key=len,
        reverse=True,
    )
)
_SCAN_BYTE_LIMIT = 16 * 1024 * 1024
_DDS_HEADER_SCAN_BYTES = 4096
_DETAIL_RECORD_LIMIT = 5000
_DEFAULT_MAX_DDS_INSPECT = 20000
_DEFAULT_MAX_SIDECARS_SCAN = 50000
_ATTR_RE = re.compile(r"\b(?P<name>[_A-Za-z][\w:.-]*)\s*=\s*(?P<quote>[\"'])(?P<value>.*?)(?P=quote)", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]*(?:ResourceReferencePath_ITexture|MaterialParameterTexture)[^>]*>", re.IGNORECASE | re.DOTALL)
_DDS_TOKEN_RE = re.compile(r"[A-Za-z0-9_./\\:-]+\.dds\b", re.IGNORECASE)
_PATH_ATTR_NAMES = {"value", "_path", "path", "filename", "texturename", "texture", "file"}
_PARAMETER_ATTR_NAMES = {
    "_name",
    "name",
    "stringitemid",
    "_stringitemid",
    "parameter",
    "_parameter",
    "parametername",
    "_parametername",
}


@dataclass(frozen=True)
class ScannedFile:
    root_name: str
    root_path: Path
    rel_path: str
    abs_path: Path
    extension: str
    basename: str
    stem: str

    @property
    def key(self) -> str:
        return _normalize_rel(self.rel_path)


def _normalize_rel(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    return normalized.casefold()


def _normalized_extension(path: str | PurePosixPath) -> str:
    name = PurePosixPath(str(path).replace("\\", "/")).name.casefold()
    for extension in _CUSTOM_EXTENSIONS:
        if name.endswith(extension):
            return extension
    return PurePosixPath(name).suffix


def _stem_without_custom_extension(path: str | PurePosixPath) -> str:
    name = PurePosixPath(str(path).replace("\\", "/")).name
    lowered = name.casefold()
    for extension in _CUSTOM_EXTENSIONS:
        if lowered.endswith(extension):
            return name[: -len(extension)]
    return PurePosixPath(name).stem


def _iter_root_files(root_name: str, root: Optional[Path], warnings: list[str]) -> tuple[list[ScannedFile], dict[str, object]]:
    if root is None:
        return [], {"path": "", "exists": False, "files": 0}
    resolved = Path(root)
    root_info: dict[str, object] = {"path": str(resolved), "exists": resolved.exists(), "files": 0}
    if not resolved.exists():
        warnings.append(f"{root_name} root does not exist: {resolved}")
        return [], root_info
    if resolved.is_file():
        base_root = resolved.parent
        candidates: Iterable[tuple[Path, str]] = ((resolved, resolved.name),)
    else:
        base_root = resolved
        candidates = (
            (Path(dirpath) / filename, Path(os.path.relpath(Path(dirpath) / filename, base_root)).as_posix())
            for dirpath, _dirnames, filenames in os.walk(resolved)
            for filename in filenames
        )
    files: list[ScannedFile] = []
    for candidate, rel_path in candidates:
        try:
            if resolved.is_file() and not candidate.is_file():
                continue
        except OSError as exc:
            warnings.append(f"Could not stat {candidate}: {exc}")
            continue
        files.append(
            ScannedFile(
                root_name=root_name,
                root_path=base_root,
                rel_path=rel_path,
                abs_path=candidate,
                extension=_normalized_extension(rel_path),
                basename=PurePosixPath(rel_path).name,
                stem=_stem_without_custom_extension(rel_path),
            )
        )
    files.sort(key=lambda item: (item.root_name, item.key))
    root_info["files"] = len(files)
    return files, root_info


def _index_by_path(files: Iterable[ScannedFile], *, extension: Optional[str] = None) -> dict[str, list[ScannedFile]]:
    index: dict[str, list[ScannedFile]] = defaultdict(list)
    for file in files:
        if extension is not None and file.extension != extension:
            continue
        index[file.key].append(file)
    return dict(index)


def _index_by_basename(files: Iterable[ScannedFile], *, extension: Optional[str] = None) -> dict[str, list[ScannedFile]]:
    index: dict[str, list[ScannedFile]] = defaultdict(list)
    for file in files:
        if extension is not None and file.extension != extension:
            continue
        index[file.basename.casefold()].append(file)
    return dict(index)


def _unique_rel_paths(files: Iterable[ScannedFile]) -> list[str]:
    return sorted({file.rel_path for file in files}, key=str.casefold)


def _file_dict(file: ScannedFile) -> dict[str, str]:
    return {
        "root": file.root_name,
        "path": file.rel_path,
        "absolute_path": str(file.abs_path),
    }


def _first_path_component(path: str) -> str:
    normalized = str(path or "").replace("\\", "/").strip("/")
    return normalized.split("/", 1)[0] if normalized else ""


def _family_example_key(file: ScannedFile) -> str:
    if file.root_name != "family":
        return ""
    return _first_path_component(file.rel_path)


def _dds_suffix(path: str) -> str:
    name = PurePosixPath(path).name.casefold()
    for suffix in _DDS_SUFFIXES:
        if name.endswith(f"{suffix}.dds"):
            return suffix
    stem = PurePosixPath(name).stem
    if "_" in stem:
        token = f"_{stem.rsplit('_', 1)[-1]}"
        if 1 < len(token) <= 24:
            return token
        return "_other"
    return "_none"


def _inspect_dds_files(
    dds_files: Sequence[ScannedFile],
    warnings: list[str],
    *,
    max_inspect: int = _DEFAULT_MAX_DDS_INSPECT,
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, int], dict[str, object]]:
    records: list[dict[str, object]] = []
    suffixes: dict[str, Counter[str]] = defaultdict(Counter)
    formats: Counter[str] = Counter()
    inspected_count = 0
    cap = max(0, int(max_inspect or 0))
    for file in dds_files:
        suffix = _dds_suffix(file.rel_path)
        if cap and inspected_count >= cap:
            suffixes[suffix]["not_inspected"] += 1
            formats["not_inspected"] += 1
            continue
        format_name = "not_inspected"
        info_record: dict[str, object] = {
            "root": file.root_name,
            "path": file.rel_path,
            "absolute_path": str(file.abs_path),
            "suffix": suffix,
            "format": format_name,
            "width": 0,
            "height": 0,
            "mip_count": 0,
            "reason": "",
        }
        if inspect_dds_native is None:
            info_record["reason"] = "cdmw.core.dds_native.inspect_dds_native unavailable"
        else:
            try:
                with file.abs_path.open("rb") as handle:
                    header_bytes = handle.read(_DDS_HEADER_SCAN_BYTES)
                info = inspect_dds_native(header_bytes)
                format_name = str(info.format_name or "unknown")
                info_record.update(
                    {
                        "format": format_name,
                        "width": int(info.width),
                        "height": int(info.height),
                        "mip_count": int(info.mip_count),
                        "dxgi_format": int(info.dxgi_format),
                        "fourcc": str(info.fourcc),
                        "compressed_family": str(info.compressed_family),
                        "srgb": bool(info.srgb),
                        "has_alpha": bool(info.has_alpha),
                        "supported_compressed": bool(info.supported_compressed),
                        "supported_uncompressed": bool(info.supported_uncompressed),
                        "reason": str(info.reason),
                    }
                )
            except Exception as exc:  # pragma: no cover - depends on filesystem races
                format_name = "inspect_error"
                info_record["format"] = format_name
                info_record["reason"] = str(exc)
                warnings.append(f"DDS inspect failed for {file.abs_path}: {exc}")
        suffixes[suffix][format_name] += 1
        formats[format_name] += 1
        inspected_count += 1
        if len(records) < _DETAIL_RECORD_LIMIT:
            records.append(info_record)
    suffix_report = {
        suffix: {"count": sum(counter.values()), "formats": dict(sorted(counter.items()))}
        for suffix, counter in sorted(suffixes.items())
    }
    stats = {
        "total": len(dds_files),
        "inspected": inspected_count,
        "capped": bool(cap and inspected_count < len(dds_files)),
        "max_inspect": cap or "all",
    }
    if stats["capped"]:
        warnings.append(
            f"DDS native format inspection capped at {inspected_count:,} of {len(dds_files):,} files; suffix counts still cover all DDS files."
        )
    return records, suffix_report, dict(sorted(formats.items())), stats


def _read_scan_text(file: ScannedFile, warnings: list[str]) -> str:
    try:
        with file.abs_path.open("rb") as handle:
            data = handle.read(_SCAN_BYTE_LIMIT + 1)
    except OSError as exc:
        warnings.append(f"Could not read sidecar {file.abs_path}: {exc}")
        return ""
    if len(data) > _SCAN_BYTE_LIMIT:
        warnings.append(f"Sidecar scan truncated at {_SCAN_BYTE_LIMIT} bytes: {file.rel_path}")
        data = data[:_SCAN_BYTE_LIMIT]
    return data.decode("utf-8", errors="ignore")


def _validate_dds_reference(raw_value: str) -> tuple[Optional[str], Optional[str]]:
    value = str(raw_value or "").strip().strip("\"'")
    if not value:
        return None, "empty texture reference"
    value = value.replace("\x00", "").strip()
    if not value.casefold().endswith(".dds"):
        return None, "texture reference does not end with .dds"
    if any(char.isspace() for char in value):
        return None, "texture reference contains whitespace"
    if re.match(r"^[A-Za-z]:[\\/]", value):
        return None, "texture reference is an absolute Windows path"
    normalized = value.replace("\\", "/").lstrip("/")
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        return None, "texture reference contains an empty or relative path segment"
    basename = PurePosixPath(normalized).name
    if basename.casefold() == ".dds":
        return None, "texture reference is missing a basename"
    return normalized, None


def _parameter_name_from_attrs(attrs: Sequence[re.Match[str]]) -> str:
    for attr in attrs:
        attr_name = attr.group("name").casefold()
        if attr_name in _PARAMETER_ATTR_NAMES:
            return str(attr.group("value") or "").strip()
    return ""


def _extract_sidecar_references(file: ScannedFile, warnings: list[str]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    text = _read_scan_text(file, warnings)
    refs: list[dict[str, str]] = []
    malformed: list[dict[str, str]] = []
    seen_refs: set[str] = set()
    seen_malformed: set[tuple[str, str]] = set()
    attr_value_spans: list[tuple[int, int]] = []
    current_parameter = ""

    def add_ref(raw_value: str, parameter_name: str = "") -> None:
        normalized, reason = _validate_dds_reference(raw_value)
        if reason is not None:
            key = (str(raw_value), reason)
            if key not in seen_malformed:
                seen_malformed.add(key)
                malformed.append(
                    {
                        "sidecar": file.rel_path,
                        "reference": str(raw_value),
                        "parameter_name": str(parameter_name or current_parameter or ""),
                        "reason": reason,
                    }
                )
            return
        assert normalized is not None
        parameter_text = str(parameter_name or current_parameter or "").strip()
        normalized_key = f"{_normalize_rel(normalized)}\0{parameter_text.casefold()}"
        if normalized_key not in seen_refs:
            seen_refs.add(normalized_key)
            refs.append({"reference": normalized, "parameter_name": parameter_text})

    for tag_match in _TAG_RE.finditer(text):
        tag = tag_match.group(0)
        tag_lower = tag.casefold()
        attrs = list(_ATTR_RE.finditer(tag))
        path_attrs = []
        tag_parameter = _parameter_name_from_attrs(attrs) if "materialparametertexture" in tag_lower else ""
        if tag_parameter:
            current_parameter = tag_parameter
        for attr in attrs:
            value_start = tag_match.start() + attr.start("value")
            value_end = tag_match.start() + attr.end("value")
            attr_value_spans.append((value_start, value_end))
            attr_name = attr.group("name").casefold()
            if attr_name in _PATH_ATTR_NAMES:
                path_attrs.append(attr.group("value"))
        if "resourcereferencepath_itexture" in tag_lower and not path_attrs:
            malformed.append(
                {
                    "sidecar": file.rel_path,
                    "reference": "",
                    "parameter_name": current_parameter,
                    "reason": "texture tag has no path attribute",
                }
            )
        for raw_value in path_attrs:
            if ".dds" in raw_value.casefold() or "resourcereferencepath_itexture" in tag_lower:
                add_ref(raw_value, current_parameter)

    if not refs:
        for token_match in _DDS_TOKEN_RE.finditer(text):
            start, end = token_match.span()
            if any(span_start <= start and end <= span_end for span_start, span_end in attr_value_spans):
                continue
            add_ref(token_match.group(0), "")
    return refs, malformed


def _resolve_dds_reference(ref: str, dds_by_path: Mapping[str, list[ScannedFile]], dds_by_basename: Mapping[str, list[ScannedFile]]) -> dict[str, object]:
    key = _normalize_rel(ref)
    exact = dds_by_path.get(key, [])
    if exact:
        return {
            "reference": ref,
            "status": "resolved_exact",
            "resolved_paths": [_file_dict(file) for file in exact],
            "match_count": len(exact),
        }
    basename = PurePosixPath(key).name
    basename_matches = dds_by_basename.get(basename, [])
    distinct_paths = _unique_rel_paths(basename_matches)
    if len(distinct_paths) == 1:
        return {
            "reference": ref,
            "status": "resolved_basename",
            "resolved_paths": [_file_dict(file) for file in basename_matches],
            "match_count": len(basename_matches),
        }
    if len(distinct_paths) > 1:
        return {
            "reference": ref,
            "status": "ambiguous_basename",
            "resolved_paths": [_file_dict(file) for file in basename_matches],
            "match_count": len(basename_matches),
        }
    return {"reference": ref, "status": "missing", "resolved_paths": [], "match_count": 0}


def _suffix_for_reference(ref: str) -> str:
    return _dds_suffix(str(ref or ""))


def _top_risky_parameter_patterns(
    parameter_status: Mapping[str, Counter[str]],
    parameter_suffixes: Mapping[str, Counter[str]],
    *,
    limit: int = 25,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for parameter_name, status_counts in parameter_status.items():
        total = sum(status_counts.values())
        if total <= 0:
            continue
        missing = int(status_counts.get("missing", 0))
        ambiguous = int(status_counts.get("ambiguous_basename", 0))
        malformed = int(status_counts.get("malformed", 0))
        risk_refs = missing + ambiguous + malformed
        if risk_refs <= 0:
            continue
        suffix_counter = parameter_suffixes.get(parameter_name, Counter())
        rows.append(
            {
                "parameter_name": parameter_name or "(unknown)",
                "total_refs": total,
                "resolved_refs": int(status_counts.get("resolved_exact", 0)) + int(status_counts.get("resolved_basename", 0)),
                "missing_refs": missing,
                "ambiguous_basename_refs": ambiguous,
                "malformed_refs": malformed,
                "risk_refs": risk_refs,
                "risk_rate": round(risk_refs / total, 6),
                "common_suffixes": dict(suffix_counter.most_common(8)),
            }
        )
    rows.sort(key=lambda row: (int(row["risk_refs"]), float(row["risk_rate"]), int(row["total_refs"])), reverse=True)
    return rows[:limit]


def _scan_sidecar_refs(
    files: Sequence[ScannedFile],
    dds_by_path: Mapping[str, list[ScannedFile]],
    dds_by_basename: Mapping[str, list[ScannedFile]],
    warnings: list[str],
    *,
    max_sidecars: int = _DEFAULT_MAX_SIDECARS_SCAN,
) -> tuple[list[dict[str, object]], list[dict[str, str]], dict[str, int], dict[str, object], list[dict[str, object]]]:
    records: list[dict[str, object]] = []
    malformed: list[dict[str, str]] = []
    status_counter: Counter[str] = Counter()
    parameter_status: defaultdict[str, Counter[str]] = defaultdict(Counter)
    parameter_suffixes: defaultdict[str, Counter[str]] = defaultdict(Counter)
    sidecars = [file for file in files if file.extension in _SIDECAR_EXTENSIONS or "/modelproperty/" in file.key]
    priority = {
        ".pac_xml": 0,
        ".pam_xml": 1,
        ".pamlod_xml": 2,
        ".pami": 3,
        ".prefab": 4,
        ".prefabdata.xml": 5,
        ".prefabdata_xml": 5,
        ".xml": 6,
    }
    sidecars.sort(key=lambda file: (priority.get(file.extension, 9), file.key))
    cap = max(0, int(max_sidecars or 0))
    scanned_sidecars = sidecars[:cap] if cap else sidecars
    for file in scanned_sidecars:
        refs, bad_refs = _extract_sidecar_references(file, warnings)
        malformed.extend(bad_refs)
        for bad_ref in bad_refs:
            parameter_name = str(bad_ref.get("parameter_name", "") or "")
            parameter_status[parameter_name]["malformed"] += 1
        for ref_record in refs:
            ref = str(ref_record.get("reference", "") or "")
            parameter_name = str(ref_record.get("parameter_name", "") or "")
            resolved = _resolve_dds_reference(ref, dds_by_path, dds_by_basename)
            status = str(resolved["status"])
            status_counter[status] += 1
            parameter_status[parameter_name][status] += 1
            parameter_suffixes[parameter_name][_suffix_for_reference(ref)] += 1
            if len(records) < _DETAIL_RECORD_LIMIT:
                records.append(
                    {
                        "sidecar": file.rel_path,
                        "sidecar_root": file.root_name,
                        "parameter_name": parameter_name,
                        **resolved,
                    }
                )
    stats = {
        "total_candidates": len(sidecars),
        "scanned": len(scanned_sidecars),
        "capped": bool(cap and len(scanned_sidecars) < len(sidecars)),
        "max_sidecars": cap or "all",
    }
    if stats["capped"]:
        warnings.append(
            f"Sidecar DDS reference scan capped at {len(scanned_sidecars):,} of {len(sidecars):,} sidecar candidates; PAC/PAC_XML pairing still covers all files."
        )
    top_risky = _top_risky_parameter_patterns(parameter_status, parameter_suffixes)
    return records, malformed, dict(sorted(status_counter.items())), stats, top_risky


def _candidate_pac_xml_paths(pac: ScannedFile) -> list[str]:
    source = _normalize_rel(pac.rel_path)
    sidecar = f"{str(PurePosixPath(source).with_suffix(''))}.pac_xml"
    candidates = [sidecar]
    if "/model/" in sidecar:
        candidates.append(sidecar.replace("/model/", "/modelproperty/", 1))
    parent = PurePosixPath(source).parent
    if parent.name.casefold() == "model":
        candidates.append((parent.parent / "modelproperty" / f"{pac.stem}.pac_xml").as_posix().casefold())
    return list(dict.fromkeys(candidates))


def _pair_pac_files(files: Sequence[ScannedFile]) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, int]]:
    pac_files = [file for file in files if file.extension == ".pac"]
    pac_xml_files = [file for file in files if file.extension == ".pac_xml"]
    pac_xml_by_path = _index_by_path(pac_xml_files)
    pac_xml_by_basename = _index_by_basename(pac_xml_files)
    pac_by_basename = _index_by_basename(pac_files)
    used_pac_xml: set[str] = set()
    pairs: list[dict[str, object]] = []
    status_counter: Counter[str] = Counter()
    for pac in pac_files:
        matches: list[ScannedFile] = []
        status = "missing"
        for candidate in _candidate_pac_xml_paths(pac):
            exact = pac_xml_by_path.get(candidate, [])
            if exact:
                matches = exact
                status = "exact"
                break
        if not matches:
            basename = f"{pac.stem}.pac_xml".casefold()
            basename_matches = pac_xml_by_basename.get(basename, [])
            distinct_paths = _unique_rel_paths(basename_matches)
            if len(distinct_paths) == 1:
                matches = basename_matches
                status = "basename_unique"
            elif len(distinct_paths) > 1:
                matches = basename_matches
                status = "ambiguous_basename"
        for match in matches:
            used_pac_xml.add(match.key)
        status_counter[status] += 1
        pairs.append(
            {
                "pac": _file_dict(pac),
                "status": status,
                "pac_xml": [_file_dict(match) for match in matches],
            }
        )
    orphan_pac_xml: list[dict[str, object]] = []
    for pac_xml in pac_xml_files:
        if pac_xml.key in used_pac_xml:
            continue
        pac_basename = f"{pac_xml.stem}.pac".casefold()
        if pac_by_basename.get(pac_basename):
            continue
        orphan_pac_xml.append(_file_dict(pac_xml))
    counts = {
        "pac_files": len(pac_files),
        "pac_xml_files": len(pac_xml_files),
        "pac_with_pac_xml": status_counter["exact"] + status_counter["basename_unique"] + status_counter["ambiguous_basename"],
        "pac_without_pac_xml": status_counter["missing"],
        "pac_xml_without_pac": len(orphan_pac_xml),
        "pac_xml_pairs_exact": status_counter["exact"],
        "pac_xml_pairs_basename_unique": status_counter["basename_unique"],
        "pac_xml_pairs_ambiguous_basename": status_counter["ambiguous_basename"],
    }
    return pairs, orphan_pac_xml, counts


def _family_candidate_basenames(stem: str, extensions: Iterable[str]) -> set[str]:
    stems = {stem.casefold()}
    if stem.casefold().endswith(("_l", "_r")):
        stems.add(stem[:-2].casefold())
    stems.update({f"{stem}_l".casefold(), f"{stem}_r".casefold()})
    return {f"{candidate}{extension}" for candidate in stems for extension in extensions}


def _find_companions(stem: str, by_basename: Mapping[str, list[ScannedFile]], extensions: Iterable[str]) -> list[dict[str, str]]:
    matches: list[ScannedFile] = []
    for basename in _family_candidate_basenames(stem, extensions):
        matches.extend(by_basename.get(basename, []))
    unique = {}
    for match in matches:
        unique[(match.root_name, match.rel_path)] = match
    return [_file_dict(file) for file in sorted(unique.values(), key=lambda item: (item.root_name, item.key))]


def _files_in_family_group(
    group_key: str,
    files: Sequence[ScannedFile],
    extensions: Iterable[str],
) -> list[dict[str, str]]:
    wanted = set(extensions)
    matches = [
        file
        for file in files
        if file.root_name == "family" and file.extension in wanted and _family_example_key(file) == group_key
    ]
    return [_file_dict(file) for file in sorted(matches, key=lambda item: item.key)]


def _scan_family_companions(files: Sequence[ScannedFile]) -> tuple[list[dict[str, object]], dict[str, int]]:
    family_pacs = [file for file in files if file.root_name == "family" and file.extension == ".pac"]
    by_basename = _index_by_basename(files)
    records: list[dict[str, object]] = []
    counts: Counter[str] = Counter({"family_pac_files": len(family_pacs)})
    for pac in family_pacs:
        group_key = _family_example_key(pac)
        hkx = _find_companions(pac.stem, by_basename, _HKX_EXTENSIONS)
        pab = _find_companions(pac.stem, by_basename, _PAB_EXTENSIONS)
        prefab = _find_companions(pac.stem, by_basename, _PREFAB_EXTENSIONS)
        pac_xml = _find_companions(pac.stem, by_basename, {".pac_xml"})
        context_hkx = _files_in_family_group(group_key, files, _HKX_EXTENSIONS)
        context_pab = _files_in_family_group(group_key, files, _PAB_EXTENSIONS)
        context_prefab = _files_in_family_group(group_key, files, _PREFAB_EXTENSIONS)
        if not hkx:
            hkx = context_hkx
        if not pab:
            pab = context_pab
        if not prefab:
            prefab = context_prefab
        if hkx:
            counts["family_pacs_with_hkx"] += 1
            counts["family_hkx_companions"] += len(hkx)
        if pab:
            counts["family_pacs_with_pab"] += 1
            counts["family_pab_companions"] += len(pab)
        if prefab:
            counts["family_pacs_with_prefab"] += 1
            counts["family_prefab_companions"] += len(prefab)
        records.append(
            {
                "pac": _file_dict(pac),
                "family_example": group_key,
                "pac_xml": pac_xml,
                "hkx": hkx,
                "pab": pab,
                "prefab": prefab,
                "context_hkx": context_hkx,
                "context_pab": context_pab,
                "context_prefab": context_prefab,
            }
        )
    for key in (
        "family_pacs_with_hkx",
        "family_hkx_companions",
        "family_pacs_with_pab",
        "family_pab_companions",
        "family_pacs_with_prefab",
        "family_prefab_companions",
    ):
        counts.setdefault(key, 0)
    return records, dict(sorted(counts.items()))


def _ambiguous_dds_basenames(dds_by_basename: Mapping[str, list[ScannedFile]]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for basename, files in sorted(dds_by_basename.items()):
        distinct_paths = _unique_rel_paths(files)
        if len(distinct_paths) <= 1:
            continue
        records.append(
            {
                "basename": basename,
                "path_count": len(distinct_paths),
                "paths": [_file_dict(file) for file in sorted(files, key=lambda item: (item.root_name, item.key))],
            }
        )
    return records


def _per_root_extension_counts(files: Sequence[ScannedFile]) -> dict[str, dict[str, int]]:
    by_root: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for file in files:
        by_root[file.root_name][file.extension or "(none)"] += 1
    return {root: dict(sorted(counter.items())) for root, counter in sorted(by_root.items())}


def _family_example_validation(files: Sequence[ScannedFile]) -> tuple[list[dict[str, object]], dict[str, int]]:
    grouped: defaultdict[str, list[ScannedFile]] = defaultdict(list)
    for file in files:
        key = _family_example_key(file)
        if key:
            grouped[key].append(file)
    rows: list[dict[str, object]] = []
    complete_count = 0
    for key, group_files in sorted(grouped.items(), key=lambda item: item[0].casefold()):
        counts = Counter(file.extension or "(none)" for file in group_files)
        complete = all(
            counts.get(extension, 0) > 0
            for extension in (".pac", ".pac_xml", ".dds", ".hkx", ".pab")
        )
        if complete:
            complete_count += 1
        rows.append(
            {
                "family_example": key,
                "pac": counts.get(".pac", 0),
                "pac_xml": counts.get(".pac_xml", 0),
                "dds": counts.get(".dds", 0),
                "hkx": counts.get(".hkx", 0),
                "pab": counts.get(".pab", 0),
                "prefab": counts.get(".prefab", 0),
                "complete": complete,
            }
        )
    counts = {
        "family_example_count": len(rows),
        "family_complete_examples": complete_count,
        "family_dds_files": sum(int(row["dds"]) for row in rows),
        "family_pac_xml_files": sum(int(row["pac_xml"]) for row in rows),
        "family_pab_files": sum(int(row["pab"]) for row in rows),
    }
    return rows, counts


def _build_counts(
    files: Sequence[ScannedFile],
    dds_files: Sequence[ScannedFile],
    pac_counts: Mapping[str, int],
    sidecar_status_counts: Mapping[str, int],
    malformed_refs: Sequence[Mapping[str, str]],
    ambiguous_basenames: Sequence[Mapping[str, object]],
    family_counts: Mapping[str, int],
) -> dict[str, object]:
    extension_counts = Counter(file.extension or "(none)" for file in files)
    valid_sidecar_refs = sum(sidecar_status_counts.values())
    resolved_sidecar_refs = int(sidecar_status_counts.get("resolved_exact", 0)) + int(sidecar_status_counts.get("resolved_basename", 0))
    resolve_rate = (resolved_sidecar_refs / valid_sidecar_refs) if valid_sidecar_refs else 0.0
    counts: dict[str, object] = {
        "files_total": len(files),
        "extensions": dict(sorted(extension_counts.items())),
        "dds_files": len(dds_files),
        "tex_files": int(extension_counts.get(".tex", 0)),
        "ambiguous_dds_basenames": len(ambiguous_basenames),
        "sidecar_dds_refs_total": valid_sidecar_refs,
        "sidecar_dds_refs_resolved": resolved_sidecar_refs,
        "sidecar_dds_refs_missing": int(sidecar_status_counts.get("missing", 0)),
        "sidecar_dds_refs_ambiguous_basename": int(sidecar_status_counts.get("ambiguous_basename", 0)),
        "sidecar_dds_resolve_rate": round(resolve_rate, 6),
        "malformed_refs": len(malformed_refs),
    }
    counts.update(dict(pac_counts))
    counts.update(dict(family_counts))
    return counts


def build_texture_relationship_audit(
    *,
    archive_root: Optional[Path],
    game_root: Optional[Path],
    family_root: Optional[Path],
    max_dds_inspect: int = _DEFAULT_MAX_DDS_INSPECT,
    max_sidecars_scan: int = _DEFAULT_MAX_SIDECARS_SCAN,
) -> dict[str, object]:
    warnings: list[str] = []
    archive_files, archive_info = _iter_root_files("archive", archive_root, warnings)
    game_files, game_info = _iter_root_files("game", game_root, warnings)
    family_files, family_info = _iter_root_files("family", family_root, warnings)
    files = [*archive_files, *game_files, *family_files]
    dds_files = [file for file in files if file.extension == ".dds"]
    dds_by_path = _index_by_path(dds_files)
    dds_by_basename = _index_by_basename(dds_files)
    ambiguous_basenames = _ambiguous_dds_basenames(dds_by_basename)
    dds_records, dds_suffixes, dds_formats, dds_inspection = _inspect_dds_files(
        dds_files,
        warnings,
        max_inspect=max_dds_inspect,
    )
    sidecar_refs, malformed_refs, sidecar_status_counts, sidecar_scan, top_risky_parameter_patterns = _scan_sidecar_refs(
        files,
        dds_by_path,
        dds_by_basename,
        warnings,
        max_sidecars=max_sidecars_scan,
    )
    pac_pairs, orphan_pac_xml, pac_counts = _pair_pac_files(files)
    family_companions, family_counts = _scan_family_companions(files)
    family_examples, family_example_counts = _family_example_validation(files)
    family_counts = {**family_counts, **family_example_counts}
    counts = _build_counts(
        files,
        dds_files,
        pac_counts,
        sidecar_status_counts,
        malformed_refs,
        ambiguous_basenames,
        family_counts,
    )
    return {
        "tool": "audit_texture_relationships",
        "inputs": {
            "archive_root": archive_info,
            "game_root": game_info,
            "family_root": family_info,
        },
        "counts": counts,
        "per_root_extension_counts": _per_root_extension_counts(files),
        "dds_suffixes": dds_suffixes,
        "dds_formats": dds_formats,
        "dds_format_inspection": dds_inspection,
        "dds_files": dds_records,
        "dds_detail_limit": _DETAIL_RECORD_LIMIT,
        "sidecar_dds_refs": sidecar_refs,
        "sidecar_dds_ref_status_counts": sidecar_status_counts,
        "sidecar_scan": sidecar_scan,
        "top_risky_parameter_patterns": top_risky_parameter_patterns,
        "malformed_refs": malformed_refs,
        "ambiguous_basenames": ambiguous_basenames,
        "pac_pac_xml_pairs": pac_pairs,
        "orphan_pac_xml": orphan_pac_xml,
        "family_companions": family_companions,
        "family_examples": family_examples,
        "warnings": warnings,
    }


def _format_count(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.2%}" if 0.0 <= value <= 1.0 else f"{value:.6g}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def render_markdown_report(report: Mapping[str, object]) -> str:
    counts = dict(report.get("counts") or {})
    lines = [
        "# Texture Relationship Audit",
        "",
        "Read-only audit of texture relationships, material sidecars, model sidecars, DDS formats, and family companions.",
        "",
        "## Inputs",
    ]
    inputs = dict(report.get("inputs") or {})
    for name in ("archive_root", "game_root", "family_root"):
        root_info = dict(inputs.get(name) or {})
        exists = "yes" if root_info.get("exists") else "no"
        lines.append(f"- {name}: {root_info.get('path', '')} (exists: {exists}, files: {_format_count(root_info.get('files', 0))})")
    lines.extend(["", "## Counts", "", "| Metric | Value |", "| --- | ---: |"])
    count_order = (
        "files_total",
        "dds_files",
        "pac_files",
        "pac_xml_files",
        "pac_with_pac_xml",
        "pac_without_pac_xml",
        "pac_xml_without_pac",
        "sidecar_dds_refs_total",
        "sidecar_dds_refs_resolved",
        "sidecar_dds_refs_missing",
        "sidecar_dds_refs_ambiguous_basename",
        "sidecar_dds_resolve_rate",
        "malformed_refs",
        "tex_files",
        "ambiguous_dds_basenames",
        "family_pac_files",
        "family_pac_xml_files",
        "family_dds_files",
        "family_example_count",
        "family_complete_examples",
        "family_hkx_companions",
        "family_pab_files",
        "family_pab_companions",
        "family_prefab_companions",
    )
    for key in count_order:
        if key in counts:
            lines.append(f"| {key} | {_format_count(counts[key])} |")
    dds_inspection = dict(report.get("dds_format_inspection") or {})
    sidecar_scan = dict(report.get("sidecar_scan") or {})
    lines.extend(
        [
            "",
            "## Scan Coverage",
            "",
            f"- DDS native headers inspected: {_format_count(dds_inspection.get('inspected', 0))} / {_format_count(dds_inspection.get('total', 0))}",
            f"- Sidecars scanned for DDS refs: {_format_count(sidecar_scan.get('scanned', 0))} / {_format_count(sidecar_scan.get('total_candidates', 0))}",
        ]
    )
    lines.extend(["", "## DDS Suffixes And Formats", "", "| Suffix | Count | Formats |", "| --- | ---: | --- |"])
    suffixes = dict(report.get("dds_suffixes") or {})
    for suffix, payload in suffixes.items():
        payload_map = dict(payload or {})
        formats = ", ".join(f"{name}: {count}" for name, count in dict(payload_map.get("formats") or {}).items())
        lines.append(f"| {suffix} | {_format_count(payload_map.get('count', 0))} | {formats} |")
    lines.extend(["", "## PAC/PAC_XML Pairs", "", "| PAC | Status | PAC_XML |", "| --- | --- | --- |"])
    for pair in list(report.get("pac_pac_xml_pairs") or [])[:50]:
        pair_map = dict(pair or {})
        pac = dict(pair_map.get("pac") or {}).get("path", "")
        pac_xml = ", ".join(dict(match).get("path", "") for match in pair_map.get("pac_xml") or []) or "-"
        lines.append(f"| {pac} | {pair_map.get('status', '')} | {pac_xml} |")
    lines.extend(["", "## Ambiguous DDS Basenames"])
    ambiguous = list(report.get("ambiguous_basenames") or [])
    if not ambiguous:
        lines.append("")
        lines.append("No ambiguous DDS basenames found.")
    else:
        for row in ambiguous[:25]:
            row_map = dict(row or {})
            paths = ", ".join(dict(path).get("path", "") for path in row_map.get("paths") or [])
            lines.append(f"- {row_map.get('basename')}: {paths}")
    lines.extend(["", "## Top Risky Parameter Patterns", "", "| Parameter | Risk Refs | Risk Rate | Missing | Ambiguous | Malformed | Common Suffixes |", "| --- | ---: | ---: | ---: | ---: | ---: | --- |"])
    risky = list(report.get("top_risky_parameter_patterns") or [])
    if not risky:
        lines.append("| none | 0 | 0.00% | 0 | 0 | 0 | - |")
    for row in risky[:25]:
        row_map = dict(row or {})
        suffixes = ", ".join(f"{suffix}: {count}" for suffix, count in dict(row_map.get("common_suffixes") or {}).items())
        lines.append(
            "| "
            f"{row_map.get('parameter_name', '')} | "
            f"{_format_count(row_map.get('risk_refs', 0))} | "
            f"{_format_count(row_map.get('risk_rate', 0.0))} | "
            f"{_format_count(row_map.get('missing_refs', 0))} | "
            f"{_format_count(row_map.get('ambiguous_basename_refs', 0))} | "
            f"{_format_count(row_map.get('malformed_refs', 0))} | "
            f"{suffixes or '-'} |"
        )
    lines.extend(["", "## Family Examples", "", "| Example | PAC | PAC_XML | DDS | HKX | PAB | Prefab | Complete |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"])
    for row in report.get("family_examples") or []:
        row_map = dict(row or {})
        lines.append(
            "| "
            f"{row_map.get('family_example', '')} | "
            f"{_format_count(row_map.get('pac', 0))} | "
            f"{_format_count(row_map.get('pac_xml', 0))} | "
            f"{_format_count(row_map.get('dds', 0))} | "
            f"{_format_count(row_map.get('hkx', 0))} | "
            f"{_format_count(row_map.get('pab', 0))} | "
            f"{_format_count(row_map.get('prefab', 0))} | "
            f"{'yes' if row_map.get('complete') else 'no'} |"
        )
    lines.extend(["", "## Family Companions", "", "| PAC | HKX | PAB | Prefab |", "| --- | ---: | ---: | ---: |"])
    for row in report.get("family_companions") or []:
        row_map = dict(row or {})
        pac = dict(row_map.get("pac") or {}).get("path", "")
        lines.append(f"| {pac} | {len(row_map.get('hkx') or [])} | {len(row_map.get('pab') or [])} | {len(row_map.get('prefab') or [])} |")
    warnings = list(report.get("warnings") or [])
    if warnings:
        lines.extend(["", "## Warnings"])
        for warning in warnings[:50]:
            lines.append(f"- {warning}")
    lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, report: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def _write_markdown(path: Path, report: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown_report(report), encoding="utf-8")


def _is_relative_to_path(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _validate_outputs_outside_inputs(args: argparse.Namespace) -> None:
    outputs = (("--json-out", args.json_out), ("--md-out", args.md_out))
    roots = (
        ("--archive-root", args.archive_root),
        ("--game-root", args.game_root),
        ("--family-root", args.family_root),
    )
    for output_label, output in outputs:
        output_path = Path(output)
        for root_label, root in roots:
            if root is None:
                continue
            root_path = Path(root)
            if not root_path.exists():
                continue
            corpus_root = root_path if root_path.is_dir() else root_path.parent
            if _is_relative_to_path(output_path, corpus_root):
                raise ValueError(f"{output_label} must be outside {root_label} to keep scanned corpus read-only: {output_path}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit texture-sidecar relationships without mutating the scanned corpus.")
    parser.add_argument("--archive-root", required=True, type=Path, help="Extracted archive or archive-like corpus root.")
    parser.add_argument("--game-root", type=Path, default=None, help="Loose game root or extracted game corpus root.")
    parser.add_argument("--family-root", required=True, type=Path, help="Focused model/family root for companion checks.")
    parser.add_argument("--json-out", required=True, type=Path, help="JSON audit output path.")
    parser.add_argument("--md-out", required=True, type=Path, help="Markdown audit output path.")
    parser.add_argument(
        "--max-dds-inspect",
        type=int,
        default=_DEFAULT_MAX_DDS_INSPECT,
        help="Maximum DDS files to open for native header format inspection; 0 means all.",
    )
    parser.add_argument(
        "--max-sidecars-scan",
        type=int,
        default=_DEFAULT_MAX_SIDECARS_SCAN,
        help="Maximum sidecar files to scan for DDS references; 0 means all.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        _validate_outputs_outside_inputs(args)
    except ValueError as exc:
        parser.error(str(exc))
    report = build_texture_relationship_audit(
        archive_root=args.archive_root,
        game_root=args.game_root,
        family_root=args.family_root,
        max_dds_inspect=args.max_dds_inspect,
        max_sidecars_scan=args.max_sidecars_scan,
    )
    _write_json(args.json_out, report)
    _write_markdown(args.md_out, report)
    print(f"Texture relationship audit written: {args.json_out}")
    print(f"Markdown report written: {args.md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
