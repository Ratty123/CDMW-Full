from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

from cdmw.models import ArchiveEntry


_TEXT_EXTENSIONS = {".xml", ".pac_xml", ".app_xml", ".material", ".pami", ".prefabdata_xml"}
_DDS_REF_RE = re.compile(r'ResourceReferencePath_ITexture\b[^>]*(?:_path|value)\s*=\s*"([^"]*)"', re.IGNORECASE)


def select_shader_text_entries(entries: Sequence[ArchiveEntry]) -> list[ArchiveEntry]:
    return [entry for entry in entries if str(entry.extension).lower() in _TEXT_EXTENSIONS]


def collect_dds_references(extract_root: Path, sidecar_entries: Sequence[ArchiveEntry]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for entry in sidecar_entries:
        rel_path = str(entry.path).replace("\\", "/")
        candidates = (extract_root / Path(rel_path), extract_root / Path(entry.pamt_path.parent.name) / Path(rel_path))
        source_path = next((path for path in candidates if path.is_file()), None)
        if source_path is None:
            continue
        text = source_path.read_text(encoding="utf-8", errors="replace")
        for ref in _DDS_REF_RE.findall(text):
            normalized = ref.replace("\\", "/").strip()
            if normalized.lower().endswith(".dds"):
                rows.append(
                    {
                        "sidecar_path": rel_path,
                        "dds_reference": normalized,
                        "dds_basename": normalized.rsplit("/", 1)[-1].lower(),
                    }
                )
    return rows


def resolve_dds_entries(
    dds_entries: Sequence[ArchiveEntry],
    refs: Sequence[Mapping[str, str]],
    *,
    limit: int = 0,
) -> tuple[list[ArchiveEntry], list[dict[str, str]], dict[str, int]]:
    by_path = {str(entry.path).replace("\\", "/").lower(): entry for entry in dds_entries}
    by_basename: dict[str, list[ArchiveEntry]] = {}
    for entry in dds_entries:
        by_basename.setdefault(str(entry.basename).lower(), []).append(entry)

    resolved: list[ArchiveEntry] = []
    rows: list[dict[str, str]] = []
    stats: Counter[str] = Counter()
    for ref in refs:
        reference = str(ref.get("dds_reference", "")).replace("\\", "/").lower()
        basename = str(ref.get("dds_basename", "") or reference.rsplit("/", 1)[-1]).lower()
        entry = by_path.get(reference)
        resolution = "exact"
        if entry is None:
            matches = by_basename.get(basename, [])
            if len(matches) == 1:
                entry = matches[0]
                resolution = "basename"
            elif len(matches) > 1:
                resolution = "ambiguous"
            else:
                resolution = "missing"
        stats[resolution] += 1
        row = dict(ref)
        row["resolution"] = resolution
        row["resolved_path"] = str(entry.path) if entry is not None else ""
        rows.append(row)
        if entry is not None and (not limit or len(resolved) < limit):
            resolved.append(entry)
    return resolved, rows, dict(stats)
