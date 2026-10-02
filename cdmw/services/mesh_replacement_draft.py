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
from cdmw.domain.mesh.cloth_guides import PacClothGuideRule
from cdmw.domain.mesh.jiggle import PacJiggleRule
from cdmw.domain.mesh.physics_profile import PacPhysicsProfileRule
from cdmw.domain.mesh.translucency import translucency_values, translucency_surface_values
from cdmw.domain.mesh.emission import EmissionChoice
from cdmw.domain.mesh.shader_controls import ShaderControls


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

    relative_jiggle = any(part.jiggle is not None and part.jiggle.retained for part in state.parts)
    regional_jiggle = any(part.jiggle is not None and part.jiggle.bone_retained for part in state.parts)
    physics_profiles = any(part.physics_profiles for part in state.parts)
    translucent = any(part.translucency is not None for part in state.parts)
    guides = any(part.cloth_guides is not None for part in state.parts)
    islands = any(part.excluded_island_faces for part in state.parts)
    if sum(len(part.excluded_island_faces) for part in state.parts) > 4_000_000:
        raise ValueError("Replacement draft island masks exceed the face limit.")
    return {
        "version": (15 if regional_jiggle else 14 if state.weapon_collisions else 13 if islands else 12 if any(part.shader_controls is not None for part in state.parts) else 11 if any(part.emission is not None for part in state.parts) else 10 if any(part.translucency_surface is not None for part in state.parts) else 9 if guides else 8 if translucent else
                    7 if physics_profiles else 6 if relative_jiggle else
                    5 if any(part.jiggle is not None for part in state.parts) else
                    4 if any(part.cloth is not None for part in state.parts) else
                    3 if state.neutral_appearance is not None else 2),
        **({"neutral_appearance": {"version": 1, **asdict(state.neutral_appearance)},
            "neutral_coordinates": state.neutral_coordinates} if state.neutral_appearance is not None else {}),
        "target_path": state.target_path, "target_sha256": state.target_sha256,
        "target_location": state.target_location, "revision": state.revision,
        **({"weapon_collisions": True} if state.weapon_collisions else {}),
        "parts": [{"part_id": part.part_id, "target_index": part.target_index,
                   "source_part_ids": list(part.source_part_ids), "included": part.included,
                   "material_choice": part.material_choice, "source_label": part.source_label,
                   "import_positions": blob(b"".join(struct.pack("<3d", *point) for point in part.import_positions)),
                   "import_normals": (blob(b"".join(struct.pack("<3d", *normal) for normal in part.import_normals))
                                      if part.import_normals is not None else None),
                   **({"cloth": part.cloth.to_dict()} if part.cloth is not None else {}),
                   **({"cloth_guides": part.cloth_guides.to_dict()} if part.cloth_guides is not None else {}),
                   **({"physics_profiles": [rule.to_dict() for rule in part.physics_profiles]} if part.physics_profiles else {}),
                   **({"translucency": list(part.translucency)} if part.translucency is not None else {}),
                   **({"emission": part.emission.to_dict()} if part.emission is not None else {}),
                   **({"shader_controls": part.shader_controls.to_dict()} if part.shader_controls is not None else {}),
                   **({"excluded_island_faces": list(part.excluded_island_faces)} if part.excluded_island_faces else {}),
                   **({"translucency_surface": list(part.translucency_surface)} if part.translucency_surface is not None else {}),
                   **({"jiggle": {**part.jiggle.to_dict(),
                                  **({"retained": part.jiggle.retained} if regional_jiggle or state.weapon_collisions or islands or relative_jiggle or physics_profiles or translucent or guides or any(p.emission is not None or p.shader_controls is not None for p in state.parts) else {})}}
                      if part.jiggle is not None else {})}
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
    if (not isinstance(payload, dict) or payload.get("version") not in {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15}
            or (payload["version"] < 3 and ("neutral_appearance" in payload or "neutral_coordinates" in payload))):
        raise ValueError("Unsupported replacement draft state.")
    weapon_collisions = payload.get("weapon_collisions", False)
    if (type(weapon_collisions) is not bool
            or (payload["version"] == 14 and not weapon_collisions)
            or (payload["version"] < 14 and "weapon_collisions" in payload)):
        raise ValueError("Invalid weapon collision draft settings.")
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
    island_face_count = 0
    physics_rule_count = 0
    if not isinstance(payload.get("parts"), list) or not 1 <= len(payload["parts"]) <= 4096:
        raise ValueError("Invalid replacement draft parts.")
    for value in payload["parts"]:
        if payload["version"] < 4 and "cloth" in value:
            raise ValueError("Cloth influence settings require replacement draft version 4.")
        cloth = PacClothRule.from_dict(value["cloth"]) if "cloth" in value else None
        if payload["version"] < 9 and "cloth_guides" in value:
            raise ValueError("Cloth guide settings require replacement draft version 9.")
        guides = PacClothGuideRule.from_dict(value["cloth_guides"]) if "cloth_guides" in value else None
        if payload["version"] < 5 and "jiggle" in value:
            raise ValueError("Jiggle settings require replacement draft version 5.")
        if payload["version"] < 8 and "translucency" in value:
            raise ValueError("Translucency settings require replacement draft version 8.")
        translucency = translucency_values(value["translucency"]) if "translucency" in value else None
        if payload["version"] < 10 and "translucency_surface" in value:
            raise ValueError("Translucent surface settings require replacement draft version 10.")
        surface = translucency_surface_values(value.get("translucency_surface"))
        if payload["version"] < 11 and "emission" in value:
            raise ValueError("Glow settings require replacement draft version 11.")
        emission = EmissionChoice.from_dict(value["emission"]) if "emission" in value else None
        if emission is not None and (emission.animation.active or emission.rgb is not None) and translucency is not None:
            raise ValueError("Animated glow cannot share a part with translucency.")
        if payload["version"] < 12 and "shader_controls" in value:
            raise ValueError("Shader controls require replacement draft version 12.")
        controls = ShaderControls.from_dict(value["shader_controls"]) if "shader_controls" in value else None
        if controls is not None and (emission is not None or translucency is not None):
            raise ValueError("Shader experiments cannot share a part with Glow or Translucency overrides.")
        if surface is not None and translucency is None:
            raise ValueError("Surface overrides require translucency on the same part.")
        jiggle = PacJiggleRule.from_dict(value["jiggle"]) if "jiggle" in value else None
        if payload["version"] < 15 and jiggle is not None and jiggle.bone_retained:
            raise ValueError("Regional jiggle settings require replacement draft version 15.")
        profiles = value.get("physics_profiles", [])
        if (not isinstance(profiles, list) or len(profiles) > 256
                or ("physics_profiles" in value and payload["version"] < 7)):
            raise ValueError("Invalid physics profile settings.")
        physics_rule_count += len(profiles)
        if physics_rule_count > 4096:
            raise ValueError("Invalid physics profile settings.")
        profiles = tuple(PacPhysicsProfileRule.from_dict(rule) for rule in profiles)
        if len({rule.variant for rule in profiles}) != len(profiles):
            raise ValueError("Physics profile assignment is ambiguous or does not match the PAC.")
        if payload["version"] >= 6 and jiggle is not None and "retained" not in value["jiggle"]:
            raise ValueError("Relative jiggle draft is missing the retained contribution.")
        if payload["version"] < 6 and jiggle is not None and jiggle.retained:
            raise ValueError("Relative jiggle settings require replacement draft version 6.")
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
        excluded_faces = value.get("excluded_island_faces", [])
        if (not isinstance(excluded_faces, list) or len(excluded_faces) > 4_000_000
                or any(type(face) is not int or not 0 <= face < 4_000_000 for face in excluded_faces)
                or excluded_faces != sorted(set(excluded_faces))
                or ("excluded_island_faces" in value and payload["version"] < 13)):
            raise ValueError("Invalid mesh island exclusion mapping.")
        island_face_count += len(excluded_faces)
        if island_face_count > 4_000_000:
            raise ValueError("Replacement draft island masks exceed the face limit.")
        parts.append(ReplacementPart(str(value["part_id"]), int(value["target_index"]),
            tuple(str(v) for v in value["source_part_ids"]), value["included"],
            value["material_choice"], str(value["source_label"]), positions, normals, cloth, jiggle, profiles, translucency, guides, surface, emission, controls, tuple(excluded_faces)))
    if payload["version"] == 15 and not any(part.jiggle is not None and part.jiggle.bone_retained for part in parts):
        raise ValueError("Regional jiggle draft has no regional contribution settings.")
    if payload["version"] == 13 and not any(part.excluded_island_faces for part in parts):
        raise ValueError("Island draft has no excluded faces.")
    if payload["version"] == 12 and not any(part.shader_controls is not None for part in parts):
        raise ValueError("Shader draft has no experimental controls.")
    if payload["version"] == 11 and not any(part.emission is not None for part in parts):
        raise ValueError("Glow draft has no emission settings.")
    if payload["version"] == 10 and not any(part.translucency_surface is not None for part in parts):
        raise ValueError("Translucent surface draft has no surface settings.")
    if payload["version"] == 9 and not any(part.cloth_guides is not None for part in parts):
        raise ValueError("Guide draft has no guide creation settings.")
    if payload["version"] == 8 and not any(part.translucency is not None for part in parts):
        raise ValueError("Translucency draft has no absorption settings.")
    if payload["version"] == 6 and not any(part.jiggle is not None and part.jiggle.retained for part in parts):
        raise ValueError("Relative jiggle draft has no retained contribution settings.")
    if payload["version"] == 7 and not any(part.physics_profiles for part in parts):
        raise ValueError("Invalid physics profile settings.")
    if any(not part.part_id for part in parts) or len({part.part_id for part in parts}) != len(parts):
        raise ValueError("Replacement draft part identities are missing or duplicated.")
    if {part.target_index for part in parts} != set(range(len(parts))):
        raise ValueError("Replacement draft target mappings are invalid or incomplete.")
    appearance, neutral = None, False
    if payload["version"] == 3 or (payload["version"] >= 4 and "neutral_appearance" in payload):
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
        tuple(file(v) for v in payload.get("companion_files", [])), appearance, neutral, weapon_collisions)
