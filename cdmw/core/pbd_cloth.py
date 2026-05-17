"""Tool-side PBD cloth preview helpers.

The game runtime is not available here, so this module builds a small,
deterministic preview payload from resolved model sidecars and recovered mesh
data.  The native D3D11 host consumes the result as an approximate cloth
simulation, not as Havok/Pearl Abyss exact runtime behavior.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
import re
import xml.etree.ElementTree as ET
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from cdmw.models import (
    ClothPreviewBatch,
    ClothPreviewConstraint,
    ClothPreviewData,
    ModelPreviewData,
    ModelPreviewMesh,
    PbdMaterialSettings,
)


_CLOTH_TOKENS = ("cloth", "cloak", "cape", "skirt", "dress", "mantle", "robe", "flap")
_HAIR_TOKENS = ("hair", "fur")
_BODY_JIGGLE_TOKENS = ("breast", "belly", "body_soft", "jiggle")
_NON_CLOTH_PBD_TOKENS = ("weapon", "spline", "blade", "guard", "handle", "hilt", "sword", "metal", "rigid")


@dataclass(frozen=True, slots=True)
class PbdConfigMaterial:
    name: str = ""
    filename: str = ""
    mode: str = ""
    pbd_part: str = ""


@dataclass(frozen=True, slots=True)
class PbdSidecarHint:
    simulation_material_name: str = ""
    material_name: str = ""
    submesh_name: str = ""
    parameter_name: str = ""
    sidecar_path: str = ""
    simulation_kind: str = "unknown"


def _local_name(value: object) -> str:
    text = str(value or "")
    if "}" in text:
        text = text.rsplit("}", 1)[-1]
    return text.strip()


def _normalize_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _normalize_name(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\\", "/").strip().lower())


def _contains_any_token(value: object, tokens: Sequence[str]) -> bool:
    text = _normalize_name(value)
    return any(token in text for token in tokens)


def _safe_float(value: object, fallback: float = 0.0) -> float:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if math.isfinite(result) else fallback


def _safe_int(value: object, fallback: int = 0) -> int:
    try:
        return int(round(float(str(value).strip())))
    except (TypeError, ValueError, OverflowError):
        return fallback


def _safe_bool(value: object, fallback: bool = False) -> bool:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return fallback


def _parse_xml(text: str) -> Optional[ET.Element]:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        return None


def classify_pbd_simulation_kind(*values: object) -> str:
    joined = " ".join(str(value or "") for value in values).lower()
    if any(token in joined for token in _HAIR_TOKENS):
        return "hair"
    if any(token in joined for token in _BODY_JIGGLE_TOKENS):
        return "body_soft"
    if any(token in joined for token in _CLOTH_TOKENS):
        return "cloth"
    if any(token in joined for token in _NON_CLOTH_PBD_TOKENS):
        return "spline"
    return "unknown"


def parse_pbd_config_materials(text: str) -> Dict[str, PbdConfigMaterial]:
    root = _parse_xml(text)
    if root is None:
        return {}
    materials: Dict[str, PbdConfigMaterial] = {}
    for element in root.iter():
        attrs = {str(key): str(value or "").strip() for key, value in element.attrib.items()}
        name = attrs.get("Name") or attrs.get("_name") or attrs.get("name") or ""
        filename = attrs.get("Filename") or attrs.get("_filename") or attrs.get("filename") or ""
        if not name or not filename:
            continue
        material = PbdConfigMaterial(
            name=name,
            filename=filename.replace("\\", "/"),
            mode=attrs.get("Mode") or attrs.get("_mode") or attrs.get("mode") or "",
            pbd_part=attrs.get("PbdPart") or attrs.get("_pbdPart") or attrs.get("pbdPart") or "",
        )
        materials[_normalize_key(name)] = material
    return materials


def parse_pbd_sidecar_hints(sidecar_text: str, *, sidecar_path: str = "") -> Tuple[PbdSidecarHint, ...]:
    root = _parse_xml(sidecar_text)
    if root is None:
        return ()
    hints: List[PbdSidecarHint] = []
    seen: set[Tuple[str, str, str, str]] = set()
    for element in root.iter():
        attrs = element.attrib
        pbd_name = str(attrs.get("_pbdSimulationMaterialName") or attrs.get("pbdSimulationMaterialName") or "").strip()
        if not pbd_name:
            continue
        material_name = str(attrs.get("_materialName") or attrs.get("materialName") or attrs.get("MaterialName") or "").strip()
        submesh_name = str(attrs.get("_subMeshName") or attrs.get("subMeshName") or attrs.get("SubMeshName") or "").strip()
        parameter_name = str(attrs.get("_name") or attrs.get("Name") or _local_name(element.tag)).strip()
        kind = classify_pbd_simulation_kind(pbd_name, material_name, submesh_name, parameter_name, _local_name(element.tag))
        key = (
            _normalize_key(pbd_name),
            _normalize_name(material_name),
            _normalize_name(submesh_name),
            _normalize_name(parameter_name),
        )
        if key in seen:
            continue
        seen.add(key)
        hints.append(
            PbdSidecarHint(
                simulation_material_name=pbd_name,
                material_name=material_name,
                submesh_name=submesh_name,
                parameter_name=parameter_name,
                sidecar_path=str(sidecar_path or ""),
                simulation_kind=kind,
            )
        )
    return tuple(hints)


def collect_pbd_sidecar_hints(
    sidecar_texts: Sequence[Tuple[str, str] | str],
) -> Tuple[PbdSidecarHint, ...]:
    hints: List[PbdSidecarHint] = []
    seen: set[Tuple[str, str, str, str, str]] = set()
    for item in sidecar_texts:
        if isinstance(item, tuple):
            sidecar_path = str(item[0] or "")
            text = str(item[1] or "")
        else:
            sidecar_path = ""
            text = str(item or "")
        for hint in parse_pbd_sidecar_hints(text, sidecar_path=sidecar_path):
            key = (
                _normalize_key(hint.simulation_material_name),
                _normalize_name(hint.material_name),
                _normalize_name(hint.submesh_name),
                _normalize_name(hint.parameter_name),
                _normalize_name(hint.sidecar_path),
            )
            if key in seen:
                continue
            seen.add(key)
            hints.append(hint)
    return tuple(hints)


def _material_scalar_values(root: ET.Element) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for element in root.iter():
        attrs = {str(key): str(value or "").strip() for key, value in element.attrib.items()}
        name_attr = attrs.get("Name") or attrs.get("_name") or attrs.get("name") or ""
        value_attr = attrs.get("Value") or attrs.get("_value") or attrs.get("value") or ""
        if name_attr and value_attr:
            values[_normalize_key(name_attr)] = value_attr
        for key, value in attrs.items():
            if value:
                values[_normalize_key(key)] = value
        text = str(element.text or "").strip()
        if text and len(text) < 80:
            values[_normalize_key(_local_name(element.tag))] = text
    return values


def _first_scalar(values: Mapping[str, str], *names: str) -> str:
    for name in names:
        key = _normalize_key(name)
        if key in values:
            return values[key]
    return ""


def parse_pbd_material_settings(
    text: str,
    *,
    material_name: str = "",
    material_path: str = "",
    config_material: Optional[PbdConfigMaterial] = None,
) -> PbdMaterialSettings:
    settings = PbdMaterialSettings(
        material_name=str(material_name or getattr(config_material, "name", "") or ""),
        material_path=str(material_path or getattr(config_material, "filename", "") or ""),
        simulation_kind=classify_pbd_simulation_kind(
            material_name,
            material_path,
            getattr(config_material, "mode", ""),
            getattr(config_material, "pbd_part", ""),
        ),
    )
    root = _parse_xml(text)
    if root is None:
        return settings
    values = _material_scalar_values(root)
    mode = _first_scalar(values, "SimulationMode", "Mode")
    if mode:
        settings.simulation_kind = classify_pbd_simulation_kind(mode, settings.material_name, settings.material_path)
    settings.stretching_stiffness = max(
        0.0,
        min(1.0, _safe_float(_first_scalar(values, "StretchingStiffness", "StretchStiffness"), settings.stretching_stiffness)),
    )
    settings.bending_stiffness = max(
        0.0,
        min(1.0, _safe_float(_first_scalar(values, "BendingStiffness", "BendStiffness"), settings.bending_stiffness)),
    )
    settings.damping = max(0.0, min(4.0, _safe_float(_first_scalar(values, "Damping"), settings.damping)))
    settings.gravity = max(-50.0, min(50.0, _safe_float(_first_scalar(values, "Gravity"), settings.gravity)))
    settings.air_resistance = max(0.0, min(8.0, _safe_float(_first_scalar(values, "AirResistance"), settings.air_resistance)))
    settings.wind_response = max(0.0, min(4.0, _safe_float(_first_scalar(values, "WindResponse"), settings.wind_response)))
    settings.solver_iterations = max(
        1,
        min(64, _safe_int(_first_scalar(values, "SolverIterationCount", "IterationCount"), settings.solver_iterations)),
    )
    settings.collision_enabled = _safe_bool(
        _first_scalar(values, "CollisionCheck", "CollisionEnabled"),
        settings.collision_enabled,
    )
    settings.is_cloak = _safe_bool(_first_scalar(values, "IsCloak"), _contains_any_token(settings.material_name, ("cloak",)))
    return settings


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    dx = float(a[0]) - float(b[0])
    dy = float(a[1]) - float(b[1])
    dz = float(a[2]) - float(b[2])
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _valid_triangles(indices: Sequence[int], vertex_count: int) -> Tuple[Tuple[int, int, int], ...]:
    triangles: List[Tuple[int, int, int]] = []
    for offset in range(0, len(indices) - 2, 3):
        tri = (int(indices[offset]), int(indices[offset + 1]), int(indices[offset + 2]))
        if any(index < 0 or index >= vertex_count for index in tri):
            continue
        if len(set(tri)) < 3:
            continue
        triangles.append(tri)
    return tuple(triangles)


def _safe_index(value: object, fallback: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def build_cloth_constraints(
    positions: Sequence[Tuple[float, float, float]],
    triangles: Sequence[Tuple[int, int, int]],
    settings: PbdMaterialSettings,
    *,
    max_constraints: int = 60000,
) -> Tuple[ClothPreviewConstraint, ...]:
    edge_faces: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    structural_edges: set[Tuple[int, int]] = set()
    for face_index, (a, b, c) in enumerate(triangles):
        for left, right in ((a, b), (b, c), (c, a)):
            edge = (left, right) if left < right else (right, left)
            structural_edges.add(edge)
            edge_faces[edge].append(face_index)

    constraints: List[ClothPreviewConstraint] = []
    for a, b in sorted(structural_edges):
        constraints.append(
            ClothPreviewConstraint(
                kind="structural",
                a=a,
                b=b,
                rest_length=_distance(positions[a], positions[b]),
                stiffness=float(settings.stretching_stiffness),
            )
        )
        if len(constraints) >= max_constraints:
            return tuple(constraints)

    bend_seen: set[Tuple[int, int]] = set()
    for edge, face_indices in edge_faces.items():
        if len(face_indices) < 2:
            continue
        first = triangles[face_indices[0]]
        second = triangles[face_indices[1]]
        opposite = [index for index in first if index not in edge] + [index for index in second if index not in edge]
        if len(opposite) < 2:
            continue
        a, b = opposite[0], opposite[1]
        if a == b:
            continue
        bend = (a, b) if a < b else (b, a)
        if bend in bend_seen:
            continue
        bend_seen.add(bend)
        constraints.append(
            ClothPreviewConstraint(
                kind="bend",
                a=bend[0],
                b=bend[1],
                rest_length=_distance(positions[bend[0]], positions[bend[1]]),
                stiffness=float(settings.bending_stiffness),
            )
        )
        if len(constraints) >= max_constraints:
            break
    return tuple(constraints)


def build_cloth_pin_weights(
    positions: Sequence[Tuple[float, float, float]],
    *,
    cloak_bias: bool = False,
) -> Tuple[float, ...]:
    if not positions:
        return ()
    ys = [float(position[1]) for position in positions]
    y_min = min(ys)
    y_max = max(ys)
    span = max(1e-6, y_max - y_min)
    hard_height = 0.16 if cloak_bias else 0.12
    fade_height = 0.36 if cloak_bias else 0.28
    hard_line = y_max - span * hard_height
    fade_line = y_max - span * fade_height
    weights: List[float] = []
    for y in ys:
        if y >= hard_line:
            weights.append(1.0)
        elif y >= fade_line:
            weights.append(max(0.0, min(1.0, (y - fade_line) / max(1e-6, hard_line - fade_line))))
        else:
            weights.append(0.0)
    if max(weights, default=0.0) <= 0.0:
        top_indices = sorted(range(len(ys)), key=lambda index: ys[index], reverse=True)[: max(3, min(8, len(ys)))]
        for index in top_indices:
            weights[index] = 1.0
    return tuple(weights)


def _match_hint_score(
    hint: PbdSidecarHint,
    mesh: ModelPreviewMesh,
    submesh: object,
) -> int:
    label = " ".join(
        str(value or "")
        for value in (
            getattr(mesh, "material_name", ""),
            getattr(mesh, "texture_name", ""),
            getattr(submesh, "name", ""),
            getattr(submesh, "material", ""),
            getattr(submesh, "texture", ""),
        )
    )
    score = 0
    if hint.submesh_name and _normalize_name(hint.submesh_name) in {
        _normalize_name(getattr(submesh, "name", "")),
        _normalize_name(getattr(mesh, "material_name", "")),
        _normalize_name(getattr(mesh, "texture_name", "")),
    }:
        score += 5
    if hint.material_name and _normalize_name(hint.material_name) in {
        _normalize_name(getattr(submesh, "material", "")),
        _normalize_name(getattr(mesh, "material_name", "")),
    }:
        score += 4
    if hint.simulation_material_name and _contains_any_token(label, (_normalize_name(hint.simulation_material_name),)):
        score += 2
    if _contains_any_token(label, _CLOTH_TOKENS):
        score += 1
    return score


def build_cloth_preview_data(
    model_preview: ModelPreviewData,
    parsed_mesh: object,
    sidecar_hints: Sequence[PbdSidecarHint],
    material_settings_by_name: Mapping[str, PbdMaterialSettings],
) -> Optional[ClothPreviewData]:
    if not isinstance(model_preview, ModelPreviewData) or not model_preview.meshes:
        return None
    hints = tuple(hint for hint in sidecar_hints if hint.simulation_kind == "cloth")
    if not hints:
        return None
    submeshes = list(getattr(parsed_mesh, "submeshes", ()) or [])
    batches: List[ClothPreviewBatch] = []
    for mesh_index, mesh in enumerate(model_preview.meshes):
        if not isinstance(mesh, ModelPreviewMesh):
            continue
        source_submesh_index = _safe_index(getattr(mesh, "source_submesh_index", -1), -1)
        if source_submesh_index < 0 or source_submesh_index >= len(submeshes):
            continue
        submesh = submeshes[source_submesh_index]
        mesh_label = " ".join(
            str(value or "")
            for value in (
                getattr(mesh, "material_name", ""),
                getattr(mesh, "texture_name", ""),
            )
        )
        if not _contains_any_token(mesh_label, _CLOTH_TOKENS):
            continue
        scored = sorted(
            ((_match_hint_score(hint, mesh, submesh), hint) for hint in hints),
            key=lambda item: item[0],
            reverse=True,
        )
        if not scored or scored[0][0] <= 0:
            continue
        hint = scored[0][1]
        settings = material_settings_by_name.get(_normalize_key(hint.simulation_material_name)) or PbdMaterialSettings(
            material_name=hint.simulation_material_name,
            simulation_kind="cloth",
        )
        if settings.simulation_kind != "cloth":
            continue
        positions = tuple(tuple(float(component) for component in position[:3]) for position in (mesh.positions or ()))
        triangles = _valid_triangles(tuple(int(index) for index in (mesh.indices or ())), len(positions))
        if len(positions) < 3 or not triangles:
            continue
        constraints = build_cloth_constraints(positions, triangles, settings)
        pin_weights = build_cloth_pin_weights(positions, cloak_bias=bool(settings.is_cloak))
        bone_indices: Tuple[Tuple[int, ...], ...] = ()
        bone_weights: Tuple[Tuple[float, ...], ...] = ()
        raw_bone_indices = tuple(getattr(submesh, "bone_indices", ()) or ())
        raw_bone_weights = tuple(getattr(submesh, "bone_weights", ()) or ())
        if len(raw_bone_indices) == len(positions) and len(raw_bone_weights) == len(positions):
            bone_indices = tuple(tuple(int(value) for value in tuple(row or ())) for row in raw_bone_indices)
            bone_weights = tuple(tuple(float(value) for value in tuple(row or ())) for row in raw_bone_weights)
        batches.append(
            ClothPreviewBatch(
                mesh_index=mesh_index,
                source_submesh_index=source_submesh_index,
                mesh_name=str(getattr(submesh, "name", "") or getattr(mesh, "material_name", "") or ""),
                material_name=str(getattr(mesh, "material_name", "") or getattr(submesh, "material", "") or ""),
                simulation_material_name=hint.simulation_material_name,
                simulation_kind="cloth",
                material_settings=settings,
                positions=positions,
                triangles=triangles,
                pin_weights=pin_weights,
                constraints=constraints,
                bone_indices=bone_indices,
                bone_weights=bone_weights,
                notes=(
                    "Tool-side PBD cloth approximation; not game/Havok exact.",
                    f"Resolved from {hint.sidecar_path}" if hint.sidecar_path else "Resolved from model sidecar PBD metadata.",
                ),
            )
        )
    if not batches:
        return None
    particle_count = sum(len(batch.positions) for batch in batches)
    constraint_count = sum(len(batch.constraints) for batch in batches)
    return ClothPreviewData(
        source_path=str(getattr(model_preview, "path", "") or ""),
        summary=(
            f"Tool-side PBD cloth preview ready for {len(batches):,} batch(es), "
            f"{particle_count:,} particles, {constraint_count:,} constraints."
        ),
        batches=tuple(batches),
        limitations=(
            "Approximate CPU PBD preview only; it does not run the proprietary game cloth solver.",
            "Hair and body jiggle descriptors are intentionally deferred.",
        ),
    )


def build_cloth_preview_from_sidecars(
    model_preview: ModelPreviewData,
    parsed_mesh: object,
    sidecar_texts: Sequence[Tuple[str, str] | str],
    pbd_config_text: str,
    material_text_resolver: Callable[[PbdConfigMaterial], Tuple[str, str]],
) -> Optional[ClothPreviewData]:
    hints = collect_pbd_sidecar_hints(sidecar_texts)
    if not hints:
        return None
    config_materials = parse_pbd_config_materials(pbd_config_text)
    material_settings_by_name: Dict[str, PbdMaterialSettings] = {}
    for hint in hints:
        config_material = config_materials.get(_normalize_key(hint.simulation_material_name))
        if config_material is None:
            material_settings_by_name[_normalize_key(hint.simulation_material_name)] = PbdMaterialSettings(
                material_name=hint.simulation_material_name,
                simulation_kind=hint.simulation_kind,
            )
            continue
        material_path, material_text = material_text_resolver(config_material)
        material_settings_by_name[_normalize_key(hint.simulation_material_name)] = parse_pbd_material_settings(
            material_text,
            material_name=config_material.name,
            material_path=material_path or config_material.filename,
            config_material=config_material,
        )
    return build_cloth_preview_data(model_preview, parsed_mesh, hints, material_settings_by_name)


__all__ = [
    "PbdConfigMaterial",
    "PbdSidecarHint",
    "build_cloth_constraints",
    "build_cloth_pin_weights",
    "build_cloth_preview_data",
    "build_cloth_preview_from_sidecars",
    "classify_pbd_simulation_kind",
    "collect_pbd_sidecar_hints",
    "parse_pbd_config_materials",
    "parse_pbd_material_settings",
    "parse_pbd_sidecar_hints",
]
