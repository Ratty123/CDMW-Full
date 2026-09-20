"""Capture exact, read-only PAC physics sources on the archive session worker.

These documents are authored data, not the heuristic settings used by the
render-cloth preview. Keep all variants and explicit empty bindings until the
caller has established which part and variant it is editing.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path, PurePosixPath
import re
import threading
from collections.abc import Mapping, Sequence

from cdmw.core.common import RunCancelled, raise_if_cancelled
from cdmw.core.pbd_cloth import (
    _parse_xml, collect_pbd_config_materials, parse_pbd_sidecar_hints,
)
from cdmw.models import (
    ArchiveEntry, PbdProfileBinding, PbdProfileContext, PbdProfileDocument,
)
from cdmw.services.archive_read_service import read_archive_entry_data


_PBD_ROOT = "character/descriptors/pbd/"
_MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
_MAX_CONTEXT_BYTES = 16 * 1024 * 1024
_MAX_BINDINGS = 4096
_MAX_PROFILES = 256


def _exact_entry(path: str, entries: Mapping[str, Sequence[ArchiveEntry]]) -> ArchiveEntry:
    normalized = path.replace("\\", "/").strip().strip("/").casefold()
    candidates = entries.get(PurePosixPath(normalized).name, ())
    if not isinstance(candidates, Sequence) or len(candidates) > 256:
        raise ValueError("Physics source lookup exceeds its candidate limit.")
    matches = {}
    for entry in candidates:
        if isinstance(entry, ArchiveEntry) and entry.identity.normalized_path == normalized:
            key = (entry.identity, entry.prepared_sha256, entry.prepared_size)
            matches[key] = entry
    if len(matches) != 1:
        raise ValueError(
            "Physics source path is ambiguous." if matches else "Exact physics source path is unavailable."
        )
    return next(iter(matches.values()))


def _xml_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    if data.startswith(b"<\x00"):
        return data.decode("utf-16-le")
    if data.startswith(b"\x00<"):
        return data.decode("utf-16-be")
    return data.decode("utf-8-sig")


def _read_document(entry: ArchiveEntry, budget: list[int], stop_event: threading.Event | None):
    raise_if_cancelled(stop_event)
    size = (
        Path(entry.prepared_path).stat().st_size
        if entry.prepared_path is not None else max(entry.orig_size, entry.comp_size)
    )
    if not 0 < size <= min(_MAX_DOCUMENT_BYTES, budget[0]):
        raise ValueError("Physics source exceeds the document size limit.")
    data, _, _ = read_archive_entry_data(entry, stop_event=stop_event)
    if not 0 < len(data) <= min(_MAX_DOCUMENT_BYTES, budget[0]):
        raise ValueError("Decoded physics source exceeds the document size limit.")
    budget[0] -= len(data)
    # Decode strictly. The original bytes, including BOM and unknown settings,
    # remain the source for future export; no XML reserialization occurs here.
    text = _xml_text(data)
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
        raise ValueError("Physics source contains an unsupported XML declaration.")
    root = _parse_xml(text)
    if root is None:
        raise ValueError("Physics source XML is malformed.")
    pending = [(root, 0)]
    count = 0
    while pending:
        element, depth = pending.pop()
        count += 1
        if depth > 64 or count > 32768:
            raise ValueError("Physics source XML exceeds the structural limit.")
        if any(len(str(value)) > 4096 for value in element.attrib.values()):
            raise ValueError("Physics source XML has an oversized attribute.")
        pending.extend((child, depth + 1) for child in element)
    raise_if_cancelled(stop_event)
    return PbdProfileDocument(entry.path, entry.identity, bytes(data), hashlib.sha256(data).hexdigest()), text


def _profile_path(filename: str) -> str:
    path = filename.replace("\\", "/").strip()
    if (not path or path.startswith("/") or ":" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))):
        raise ValueError("Physics profile declares an invalid archive path.")
    path = path if path.casefold().startswith("character/") else _PBD_ROOT + path
    if not path.casefold().endswith(".xml"):
        raise ValueError("Physics profile does not reference an XML document.")
    return path


def resolve_mesh_physics_profiles(
    source: ArchiveEntry,
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]],
    *,
    stop_event: threading.Event | None = None,
) -> PbdProfileContext:
    """Resolve one exact PAC sidecar and its declared profiles, never a basename guess."""
    raise_if_cancelled(stop_event)
    context = PbdProfileContext(source.identity)
    if source.extension != ".pac":
        return context
    budget = [_MAX_CONTEXT_BYTES]
    try:
        sidecar_path = source.identity.normalized_path.replace("/model/", "/modelproperty/", 1) + "_xml"
        sidecar, text = _read_document(_exact_entry(sidecar_path, entries_by_basename), budget, stop_event)
        context = replace(context, sidecar=sidecar)
        hints = parse_pbd_sidecar_hints(text, sidecar_path=sidecar.path, retain_empty_bindings=True)
        if len(hints) > _MAX_BINDINGS:
            raise ValueError("Physics sidecar contains too many part bindings.")
        bindings = tuple(PbdProfileBinding(
            hint.simulation_material_name, hint.submesh_name, hint.material_name, hint.variant_index,
        ) for hint in hints)
        context = replace(context, bindings=bindings)
        if not any(binding.profile_name for binding in bindings):
            return context
        catalogue, text = _read_document(
            _exact_entry(_PBD_ROOT + "pbdconfig.xml", entries_by_basename), budget, stop_event,
        )
        context = replace(context, catalogue=catalogue)
        materials = collect_pbd_config_materials(text)
        if len(materials) > _MAX_BINDINGS:
            raise ValueError("Physics catalogue contains too many profile declarations.")
        by_name = {}
        for material in materials:
            by_name.setdefault(material.name.casefold(), []).append(material)
        profiles = {}
        failures = {}
        resolved = []
        for binding in bindings:
            raise_if_cancelled(stop_event)
            if not binding.profile_name:
                resolved.append(binding)
                continue
            try:
                matches = by_name.get(binding.profile_name.casefold(), ())
                if len(matches) != 1:
                    raise ValueError("Physics profile name is ambiguous or absent from the catalogue.")
                path = _profile_path(matches[0].filename)
                key = path.casefold()
                if key in failures:
                    raise ValueError(failures[key])
                if key not in profiles:
                    try:
                        if len(profiles) + len(failures) >= _MAX_PROFILES:
                            raise ValueError("Physics context contains too many profiles.")
                        document, _ = _read_document(_exact_entry(path, entries_by_basename), budget, stop_event)
                        profiles[key] = document
                    except (OSError, ValueError) as exc:
                        failures[key] = str(exc)
                        raise
                resolved.append(replace(binding, profile_path=profiles[key].path))
            except (OSError, ValueError) as exc:
                resolved.append(replace(binding, problem=str(exc)))
        return replace(context, profiles=tuple(profiles.values()), bindings=tuple(resolved))
    except RunCancelled:
        raise
    except (OSError, ValueError) as exc:
        return replace(context, problem=str(exc))
