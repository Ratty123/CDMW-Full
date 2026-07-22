"""Settings-owned persistence for procedural mesh morph definitions and values."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Iterable, Mapping

from cdmw.core.atomic_file import atomic_write_text
from cdmw.domain.mesh import (
    MESH_MORPH_PRESET_FORMAT,
    MESH_MORPH_PROFILE_FORMAT,
    MeshMorphDefinition,
    MeshMorphProfile,
    MeshMorphRule,
    MeshMorphValuePreset,
    MeshMorphVertexWeight,
    build_weighted_morph_selection,
    mesh_morph_driver_topology_fingerprint,
    procedural_morph_pivot,
)


_LEGACY_PROFILE_FORMAT = "cdmw.mesh_morph_slider_profile.v1"
_SAFE_ID = re.compile(r"[^a-z0-9_-]+")


def mesh_morph_profile_root(settings: object | None) -> Path:
    """Return the existing settings-owned mesh_slider_profiles directory."""

    if settings is None:
        raise RuntimeError("Mesh morph profiles require application settings.")
    file_name = getattr(settings, "fileName", None)
    raw_path = file_name() if callable(file_name) else file_name
    if not raw_path:
        raise RuntimeError("Mesh morph profiles require a settings file path.")
    return Path(str(raw_path)).expanduser().resolve().parent / "mesh_slider_profiles"


def list_mesh_morph_profiles(
    root: str | Path,
    mesh: object,
) -> tuple[tuple[MeshMorphProfile, ...], tuple[str, ...]]:
    """Load exact-topology v2 profiles plus compatible in-memory v1 regions."""

    profile_root = Path(root).expanduser()
    if not profile_root.is_dir():
        return (), ()
    profiles: list[MeshMorphProfile] = []
    diagnostics: list[str] = []
    for path in sorted((profile_root / "definitions").glob("*.json")):
        try:
            profile = mesh_morph_profile_from_payload(_read_object(path))
            current_fingerprint = mesh_morph_driver_topology_fingerprint(mesh, profile.definitions)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            diagnostics.append(f"Skipped invalid procedural morph profile {path.name}: {exc}")
            continue
        if profile.topology_fingerprint == current_fingerprint:
            profiles.append(profile)
        else:
            diagnostics.append(
                f"Procedural morph profile {profile.name} was omitted because its driver topology does not match."
            )
    migrated_ids = {profile.profile_id for profile in profiles}
    for legacy_path in sorted(profile_root.glob("*/profile.json")):
        try:
            migrated, migration_diagnostics = _migrate_legacy_profile(legacy_path, mesh)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            diagnostics.append(f"Skipped invalid legacy slider profile {legacy_path.parent.name}: {exc}")
            continue
        diagnostics.extend(migration_diagnostics)
        if migrated is not None and migrated.profile_id not in migrated_ids:
            migrated_ids.add(migrated.profile_id)
            profiles.append(migrated)
    profiles.sort(key=lambda item: (item.name.casefold(), item.profile_id))
    return tuple(profiles), tuple(diagnostics)


def save_mesh_morph_profile(root: str | Path, profile: MeshMorphProfile) -> Path:
    """Atomically save a v2 definition profile without touching legacy files."""

    profile_root = Path(root).expanduser() / "definitions"
    profile_root.mkdir(parents=True, exist_ok=True)
    destination = profile_root / f"{_safe_id(profile.profile_id)}.json"
    normalized = MeshMorphProfile(
        profile_id=profile.profile_id,
        name=profile.name,
        topology_fingerprint=profile.topology_fingerprint,
        definitions=profile.definitions,
    )
    atomic_write_text(destination, json.dumps(mesh_morph_profile_payload(normalized), indent=2, sort_keys=True))
    return destination


def delete_mesh_morph_profile(root: str | Path, profile_id: object) -> bool:
    """Delete only a v2 definition file; legacy v1 directories remain intact."""

    destination = Path(root).expanduser() / "definitions" / f"{_safe_id(profile_id)}.json"
    if not destination.is_file():
        return False
    destination.unlink()
    return True


def list_mesh_morph_presets(
    root: str | Path,
    profile: MeshMorphProfile,
) -> tuple[tuple[MeshMorphValuePreset, ...], tuple[str, ...]]:
    preset_root = Path(root).expanduser() / "presets" / _safe_id(profile.profile_id)
    if not preset_root.is_dir():
        return (), ()
    presets: list[MeshMorphValuePreset] = []
    diagnostics: list[str] = []
    definition_ids = {definition.definition_id for definition in profile.definitions}
    for path in sorted(preset_root.glob("*.json")):
        try:
            preset = mesh_morph_preset_from_payload(_read_object(path))
            if preset.profile_id != profile.profile_id or preset.topology_fingerprint != profile.topology_fingerprint:
                raise ValueError("preset driver identity does not match the active definition profile")
            if any(definition_id not in definition_ids for definition_id, _value in preset.values):
                raise ValueError("preset references a missing procedural definition")
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            diagnostics.append(f"Skipped invalid morph preset {path.name}: {exc}")
            continue
        presets.append(preset)
    presets.sort(key=lambda item: (item.name.casefold(), item.preset_id))
    return tuple(presets), tuple(diagnostics)


def save_mesh_morph_preset(root: str | Path, preset: MeshMorphValuePreset) -> Path:
    preset_root = Path(root).expanduser() / "presets" / _safe_id(preset.profile_id)
    preset_root.mkdir(parents=True, exist_ok=True)
    destination = preset_root / f"{_safe_id(preset.preset_id)}.json"
    atomic_write_text(destination, json.dumps(mesh_morph_preset_payload(preset), indent=2, sort_keys=True))
    return destination


def delete_mesh_morph_preset(root: str | Path, profile_id: object, preset_id: object) -> bool:
    destination = Path(root).expanduser() / "presets" / _safe_id(profile_id) / f"{_safe_id(preset_id)}.json"
    if not destination.is_file():
        return False
    destination.unlink()
    return True


def mesh_morph_profile_payload(profile: MeshMorphProfile) -> dict[str, object]:
    return {
        "format": MESH_MORPH_PROFILE_FORMAT,
        "profile_id": profile.profile_id,
        "name": profile.name,
        "topology_fingerprint": profile.topology_fingerprint,
        "definitions": [_definition_payload(definition) for definition in profile.definitions],
    }


def mesh_morph_profile_from_payload(payload: Mapping[str, object]) -> MeshMorphProfile:
    if str(payload.get("format") or "") != MESH_MORPH_PROFILE_FORMAT:
        raise ValueError("unsupported procedural morph profile format")
    definitions = tuple(
        _definition_from_payload(item)
        for item in _mapping_items(payload.get("definitions"))
    )
    return MeshMorphProfile(
        profile_id=str(payload.get("profile_id") or ""),
        name=str(payload.get("name") or ""),
        topology_fingerprint=str(payload.get("topology_fingerprint") or ""),
        definitions=definitions,
    )


def mesh_morph_preset_payload(preset: MeshMorphValuePreset) -> dict[str, object]:
    return {
        "format": MESH_MORPH_PRESET_FORMAT,
        "preset_id": preset.preset_id,
        "name": preset.name,
        "profile_id": preset.profile_id,
        "topology_fingerprint": preset.topology_fingerprint,
        "values": {definition_id: value for definition_id, value in preset.values},
    }


def mesh_morph_preset_from_payload(payload: Mapping[str, object]) -> MeshMorphValuePreset:
    if str(payload.get("format") or "") != MESH_MORPH_PRESET_FORMAT:
        raise ValueError("unsupported procedural morph preset format")
    raw_values = payload.get("values")
    values = tuple((str(key), _finite(value, "preset value")) for key, value in raw_values.items()) if isinstance(raw_values, Mapping) else ()
    return MeshMorphValuePreset(
        preset_id=str(payload.get("preset_id") or ""),
        name=str(payload.get("name") or ""),
        profile_id=str(payload.get("profile_id") or ""),
        topology_fingerprint=str(payload.get("topology_fingerprint") or ""),
        values=values,
    )


def _definition_payload(definition: MeshMorphDefinition) -> dict[str, object]:
    return {
        "definition_id": definition.definition_id,
        "label": definition.label,
        "category": definition.category,
        "vertices": [
            {"submesh_index": item.submesh_index, "vertex_index": item.vertex_index, "weight": item.weight}
            for item in definition.vertices
        ],
        "pivot": list(definition.pivot),
        "local_basis": [list(axis) for axis in definition.local_basis],
        "rule": {
            "kind": definition.rule.kind,
            "axis": definition.rule.axis,
            "amount": definition.rule.amount,
            "falloff": definition.rule.falloff,
            "feather": definition.rule.feather,
            "parameters": {key: value for key, value in definition.rule.parameters},
        },
        "mirror_mode": definition.mirror_mode,
        "min_percent": definition.min_percent,
        "max_percent": definition.max_percent,
        "default_percent": definition.default_percent,
    }


def _definition_from_payload(payload: Mapping[str, object]) -> MeshMorphDefinition:
    raw_rule = payload.get("rule")
    if not isinstance(raw_rule, Mapping):
        raise ValueError("procedural morph definition is missing its rule")
    raw_parameters = raw_rule.get("parameters")
    parameters = tuple((str(key), _finite(value, "rule parameter")) for key, value in raw_parameters.items()) if isinstance(raw_parameters, Mapping) else ()
    raw_basis = tuple(payload.get("local_basis") or ())
    if len(raw_basis) != 3:
        raise ValueError("procedural morph definition local_basis is invalid")
    return MeshMorphDefinition(
        definition_id=str(payload.get("definition_id") or ""),
        label=str(payload.get("label") or ""),
        category=str(payload.get("category") or "General"),
        vertices=tuple(
            MeshMorphVertexWeight(
                int(item.get("submesh_index", -1)),
                int(item.get("vertex_index", -1)),
                _finite(item.get("weight", 1.0), "vertex weight"),
            )
            for item in _mapping_items(payload.get("vertices"))
        ),
        pivot=_vec3(payload.get("pivot")),
        local_basis=tuple(_vec3(axis) for axis in raw_basis),  # type: ignore[arg-type]
        rule=MeshMorphRule(
            kind=str(raw_rule.get("kind") or ""),
            axis=str(raw_rule.get("axis") or "y"),
            amount=_finite(raw_rule.get("amount", 0.1), "rule amount"),
            falloff=str(raw_rule.get("falloff") or "smooth"),
            feather=int(raw_rule.get("feather", 2) or 0),
            parameters=parameters,
        ),
        mirror_mode=str(payload.get("mirror_mode") or "off"),
        min_percent=_finite(payload.get("min_percent", -100.0), "minimum percent"),
        max_percent=_finite(payload.get("max_percent", 100.0), "maximum percent"),
        default_percent=_finite(payload.get("default_percent", 0.0), "default percent"),
    )


def _migrate_legacy_profile(
    profile_path: Path,
    mesh: object,
) -> tuple[MeshMorphProfile | None, tuple[str, ...]]:
    payload = _read_object(profile_path)
    if str(payload.get("format") or "") != _LEGACY_PROFILE_FORMAT:
        return None, ()
    if not _legacy_topology_matches(payload.get("topology_signature"), mesh):
        return None, ()
    definitions: list[MeshMorphDefinition] = []
    diagnostics: list[str] = []
    for raw_slider in _mapping_items(payload.get("sliders")):
        slider_type = str(raw_slider.get("type") or raw_slider.get("slider_type") or "morph_target").strip().lower()
        slider_id = _safe_id(raw_slider.get("id") or raw_slider.get("slider_id") or "slider")
        if slider_type != "region_volume":
            diagnostics.append(f"Legacy target slider {slider_id} was omitted; target-based v1 sliders are unsupported.")
            continue
        raw_region_path = str(raw_slider.get("region_path") or "").strip()
        if not raw_region_path:
            diagnostics.append(f"Legacy region slider {slider_id} was omitted because its region file is missing.")
            continue
        region_path = Path(raw_region_path)
        if not region_path.is_absolute():
            region_path = profile_path.parent / region_path
        region = _read_object(region_path)
        selection = {
            int(key): tuple(int(index) for index in values or ())
            for key, values in (region.get("selected_vertices_by_submesh") or {}).items()
        }
        feather = max(0, int(region.get("feather", 2) or 0))
        vertices = build_weighted_morph_selection(mesh, selection, feather=feather, falloff="smooth")
        definitions.append(
            MeshMorphDefinition(
                definition_id=slider_id,
                label=str(raw_slider.get("label") or slider_id),
                category="Migrated",
                vertices=vertices,
                pivot=procedural_morph_pivot(mesh, vertices),
                local_basis=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
                rule=MeshMorphRule(kind="volume", amount=_finite(region.get("amount", 0.1), "legacy amount"), feather=feather),
                min_percent=_finite(raw_slider.get("min_percent", -100.0), "legacy minimum"),
                max_percent=_finite(raw_slider.get("max_percent", 100.0), "legacy maximum"),
                default_percent=_finite(raw_slider.get("default_percent", 0.0), "legacy default"),
            )
        )
    if not definitions:
        return None, tuple(diagnostics)
    legacy_key = profile_path.parent.name or str(payload.get("name") or "legacy")
    profile_id = f"migrated-{_safe_id(legacy_key)}-{hashlib.sha1(str(profile_path).encode('utf-8')).hexdigest()[:8]}"
    diagnostics.append(f"Loaded compatible v1 region profile {payload.get('name') or legacy_key} in memory; Save Profile writes v2 and leaves v1 intact.")
    return MeshMorphProfile(
        profile_id=profile_id,
        name=str(payload.get("name") or legacy_key),
        topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, definitions),
        definitions=tuple(definitions),
        migrated_from_version=1,
        requires_v2_save=True,
    ), tuple(diagnostics)


def _legacy_topology_matches(raw_signature: object, mesh: object) -> bool:
    if not isinstance(raw_signature, Mapping):
        return False
    current_submeshes = []
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        faces = [list(map(int, face[:3])) for face in tuple(getattr(submesh, "faces", ()) or ()) if len(face) >= 3]
        current_submeshes.append(
            {
                "name": str(getattr(submesh, "name", "") or ""),
                "material": str(getattr(submesh, "material", "") or ""),
                "vertex_count": len(tuple(getattr(submesh, "vertices", ()) or ())),
                "face_count": len(faces),
                "faces": faces,
            }
        )
    current = {"submesh_count": len(current_submeshes), "submeshes": current_submeshes}
    return json.dumps(dict(raw_signature), sort_keys=True, separators=(",", ":")) == json.dumps(current, sort_keys=True, separators=(",", ":"))


def _mapping_items(value: object) -> Iterable[Mapping[str, object]]:
    return (item for item in tuple(value or ()) if isinstance(item, Mapping))


def _read_object(path: Path) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("JSON root must be an object")
    return payload


def _safe_id(value: object) -> str:
    candidate = _SAFE_ID.sub("-", str(value or "").strip().lower()).strip("-_")
    if not candidate:
        raise ValueError("Morph profile and preset ids require at least one alphanumeric character.")
    return candidate[:80]


def _finite(value: object, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _vec3(value: object) -> tuple[float, float, float]:
    raw = tuple(value or ())  # type: ignore[arg-type]
    if len(raw) != 3:
        raise ValueError("expected a three-component vector")
    return _finite(raw[0], "vector"), _finite(raw[1], "vector"), _finite(raw[2], "vector")


__all__ = [
    "delete_mesh_morph_preset",
    "delete_mesh_morph_profile",
    "list_mesh_morph_presets",
    "list_mesh_morph_profiles",
    "mesh_morph_preset_from_payload",
    "mesh_morph_preset_payload",
    "mesh_morph_profile_from_payload",
    "mesh_morph_profile_payload",
    "mesh_morph_profile_root",
    "save_mesh_morph_preset",
    "save_mesh_morph_profile",
]
