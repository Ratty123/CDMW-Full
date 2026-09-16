"""Versioned replacement draft payloads with contained, checksummed resources."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
import math
from pathlib import Path
import struct

from cdmw.core.common import raise_if_cancelled
from cdmw.domain.mesh.replacement import MeshReplacementState, ReplacementFile, ReplacementPart
from cdmw.domain.mesh.cloth import PacClothRule


MAX_REPLACEMENT_BYTES = 512 * 1024 * 1024


def save_replacement_state(state, project_root, generation_dir, stop_event=None):
    if state is None:
        return None
    root = Path(project_root).resolve()
    directory = Path(generation_dir) / "replacement"
    directory.mkdir(exist_ok=True)
    total = 0

    def blob(data):
        nonlocal total
        raise_if_cancelled(stop_event, "Replacement draft save cancelled.")
        total += len(data)
        if total > MAX_REPLACEMENT_BYTES:
            raise ValueError("Replacement draft resources exceed the 512 MiB limit.")
        digest = hashlib.sha256(data).hexdigest()
        path = directory / digest
        if not path.exists():
            path.write_bytes(data)
        return {"path": path.relative_to(root).as_posix(), "sha256": digest, "size": len(data)}

    def file_payload(file):
        return {"path": file.path, "data": blob(file.data), "archive_location": file.archive_location}

    return {
        "version": 4 if any(part.cloth is not None for part in state.parts) else (3 if state.neutral_appearance is not None else 2),
        **({"neutral_appearance": {"version": 1, **asdict(state.neutral_appearance)},
            "neutral_coordinates": state.neutral_coordinates} if state.neutral_appearance is not None else {}),
        "target_path": state.target_path, "target_sha256": state.target_sha256,
        "target_location": state.target_location, "revision": state.revision,
        "parts": [{"part_id": part.part_id, "target_index": part.target_index,
                   "source_part_ids": list(part.source_part_ids), "included": part.included,
                   "material_choice": part.material_choice, "source_label": part.source_label,
                   "import_positions": blob(b"".join(struct.pack("<3d", *point) for point in part.import_positions)),
                   "import_normals": (blob(b"".join(struct.pack("<3d", *normal) for normal in part.import_normals))
                                      if part.import_normals is not None else None),
                   **({"cloth": part.cloth.to_dict()} if part.cloth is not None else {})}
                  for part in state.parts],
        "dependencies": [file_payload(file) for file in state.dependencies],
        "companion_files": [file_payload(file) for file in state.companion_files],
    }


def load_replacement_state(payload, project_root):
    """Decode persisted input with one recoverable validation error boundary."""
    try:
        return _load_replacement_state(payload, project_root)
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("Malformed replacement draft state.") from exc


def _load_replacement_state(payload, project_root):
    if payload is None:
        return None
    if (not isinstance(payload, dict) or payload.get("version") not in {1, 2, 3, 4}
            or (payload["version"] < 3 and ("neutral_appearance" in payload or "neutral_coordinates" in payload))):
        raise ValueError("Unsupported replacement draft state.")
    root = Path(project_root).resolve()
    total = 0

    def blob(descriptor):
        nonlocal total
        path = (root / descriptor["path"]).resolve()
        size = int(descriptor["size"])
        total += size
        if size < 0 or total > MAX_REPLACEMENT_BYTES or root not in path.parents:
            raise ValueError("Invalid replacement draft resource path or size.")
        if path.stat().st_size != size:
            raise ValueError("Replacement draft resource size changed.")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != descriptor["sha256"]:
            raise ValueError("Replacement draft resource checksum changed.")
        return data

    def location(value):
        if value is None:
            return None
        if not isinstance(value, (tuple, list)) or len(value) != 7:
            raise ValueError("Invalid replacement archive identity.")
        return (str(value[0]), str(value[1]), *(int(v) for v in value[2:]))

    def file(value):
        return ReplacementFile(str(value["path"]), blob(value["data"]), location(value.get("archive_location")))

    parts = []
    if not isinstance(payload.get("parts"), list) or not 1 <= len(payload["parts"]) <= 4096:
        raise ValueError("Invalid replacement draft parts.")
    for value in payload["parts"]:
        if payload["version"] < 4 and "cloth" in value:
            raise ValueError("Cloth influence settings require replacement draft version 4.")
        cloth = PacClothRule.from_dict(value["cloth"]) if "cloth" in value else None
        data = blob(value["import_positions"])
        if len(data) % 24:
            raise ValueError("Invalid replacement import placement data.")
        positions = tuple(struct.iter_unpack("<3d", data))
        if any(not math.isfinite(coordinate) for point in positions for coordinate in point):
            raise ValueError("Non-finite replacement import placement.")
        normals = None
        if payload["version"] >= 2 and "import_normals" not in value:
            raise ValueError("Replacement draft is missing saved import normals.")
        if payload["version"] >= 2 and value["import_normals"] is not None:
            normal_data = blob(value["import_normals"])
            if len(normal_data) not in {0, len(data)}:
                raise ValueError("Saved import normals do not match the replacement geometry.")
            normals = tuple(struct.iter_unpack("<3d", normal_data))
            if any(not math.isfinite(coordinate) for normal in normals for coordinate in normal):
                raise ValueError("Non-finite replacement import normals.")
        if type(value["included"]) is not bool or value["material_choice"] not in {"original", "imported"}:
            raise ValueError("Invalid replacement output intent.")
        parts.append(ReplacementPart(str(value["part_id"]), int(value["target_index"]),
            tuple(str(v) for v in value["source_part_ids"]), value["included"],
            value["material_choice"], str(value["source_label"]), positions, normals, cloth))
    if any(not part.part_id for part in parts) or len({part.part_id for part in parts}) != len(parts):
        raise ValueError("Replacement draft part identities are missing or duplicated.")
    if {part.target_index for part in parts} != set(range(len(parts))):
        raise ValueError("Replacement draft target mappings are invalid or incomplete.")
    appearance, neutral = None, False
    if payload["version"] == 3 or (payload["version"] == 4 and "neutral_appearance" in payload):
        from cdmw.modding.mesh_importer import _load_obj_neutral_appearance
        appearance = _load_obj_neutral_appearance(payload.get("neutral_appearance"))
        neutral = payload.get("neutral_coordinates")
        if type(neutral) is not bool:
            raise ValueError("Invalid experimental replacement coordinate frame.")
    elif "neutral_coordinates" in payload:
        raise ValueError("Replacement coordinates require a saved appearance transform.")
    return MeshReplacementState(str(payload["target_path"]), str(payload["target_sha256"]),
        tuple(parts), int(payload["revision"]), location(payload.get("target_location")),
        tuple(file(v) for v in payload.get("dependencies", [])),
        tuple(file(v) for v in payload.get("companion_files", [])), appearance, neutral)
