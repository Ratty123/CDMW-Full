from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

from cdmw.services.mesh_service_state import _MeshEditSession


_RESIDENT_MATERIAL_PARAMETER_KEYS = frozenset(
    {
        "texture_brightness", "contrast", "post_contrast_brightness", "saturation", "gamma",
        "tint_color", "base_color_lift", "value_max", "auto_balance", "shadow_lift",
        "roughness", "roughness_inverted", "roughness_scale", "roughness_min", "roughness_max",
        "roughness_blend_target", "roughness_blend_strength", "metalness", "metallic",
        "metalness_inverted", "metalness_scale", "metalness_min", "metalness_max",
        "metalness_blend_target", "metalness_blend_strength", "specular", "height_scale",
        "emissive_intensity", "emissive_color", "material_role", "visible",
    }
)


def _material_parameter_value(value: object) -> object:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("resident material parameter must be finite")
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        rows = tuple(value)
        if len(rows) > 16:
            raise ValueError("resident material parameter sequence is too large")
        return [_material_parameter_value(item) for item in rows]
    raise ValueError("resident material parameter has an unsupported value")


def _resident_material_targets(raw: object, submesh_count: int) -> tuple[int, ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)) or not raw:
        return tuple(range(submesh_count))
    targets: set[int] = set()
    for value in raw:
        if isinstance(value, bool):
            continue
        try:
            index = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if 0 <= index < submesh_count:
            targets.add(index)
    return tuple(sorted(targets))


def _resident_material_groups(session: _MeshEditSession) -> tuple[dict[str, object], ...]:
    return tuple(
        {"source_submesh_indices": [index], **copy.deepcopy(session.resident_material_parameters[index])}
        for index in sorted(session.resident_material_parameters)
    )


class MeshResidentMaterialServiceMixin:
    def commit_resident_material_resources(
        self,
        session_id: str,
        bindings: Sequence[Mapping[str, object]],
        *,
        expected_mesh_revision: int | None = None,
    ) -> int:
        session = self._session(session_id)
        with session.export_lock:
            if session.closed:
                raise RuntimeError("mesh edit session is closed")
            if expected_mesh_revision is not None and int(expected_mesh_revision) != int(session.revision):
                raise RuntimeError(
                    f"stale resident material revision: expected {int(expected_mesh_revision)}, current {session.revision}"
                )
            previous = dict(session.committed_texture_resources)
            previous_generation = int(session.material_generation)
            created: list[Path] = []
            applied = False
            try:
                for binding in bindings:
                    if not isinstance(binding, Mapping):
                        continue
                    resource_id = str(binding.get("resource_id", "") or "").strip()
                    channel = str(binding.get("channel", "base") or "base").strip().lower() or "base"
                    if not resource_id:
                        raise ValueError("resident texture resource id is required")
                    key = (resource_id, channel)
                    if bool(binding.get("remove", False)):
                        applied = session.committed_texture_resources.pop(key, None) is not None or applied
                        continue
                    source = Path(str(binding.get("source_dds_path", binding.get("path", "")) or "")).expanduser()
                    if source.suffix.lower() != ".dds":
                        raise ValueError("committed resident material resource must be a DDS file")
                    revision = self.record_committed_texture_assignment(
                        session_id,
                        source,
                        resource_id=resource_id,
                        channel=channel,
                        affected_submeshes=tuple(binding.get("affected_submeshes", ()) or ()),
                        logical_path=str(binding.get("logical_path", "") or source),
                        mesh_texture_assignment=False,
                    )
                    created.append(Path(session.committed_texture_resources[key].source_dds_path))
                    applied = revision > 0
                if not applied:
                    raise ValueError("resident material resource update has no bindings")
            except Exception:
                session.committed_texture_resources = previous
                session.material_generation = previous_generation
                for path in created:
                    path.unlink(missing_ok=True)
                raise
            session.material_generation = previous_generation + 1
            return session.material_generation

    def commit_resident_material_parameters(
        self,
        session_id: str,
        groups: Sequence[Mapping[str, object]],
        *,
        expected_mesh_revision: int | None = None,
    ) -> int:
        session = self._session(session_id)
        with session.export_lock:
            if session.closed:
                raise RuntimeError("mesh edit session is closed")
            if expected_mesh_revision is not None and int(expected_mesh_revision) != int(session.revision):
                raise RuntimeError(
                    f"stale resident material revision: expected {int(expected_mesh_revision)}, current {session.revision}"
                )
            state = copy.deepcopy(session.resident_material_parameters)
            submesh_count = len(tuple(session.working_mesh.submeshes or ()))
            applied = False
            for raw_group in groups:
                if not isinstance(raw_group, Mapping):
                    continue
                values = {
                    key: _material_parameter_value(raw_group[key])
                    for key in sorted(_RESIDENT_MATERIAL_PARAMETER_KEYS)
                    if key in raw_group
                }
                if not values:
                    continue
                for index in _resident_material_targets(raw_group.get("source_submesh_indices"), submesh_count):
                    current = state.setdefault(index, {})
                    for key, value in values.items():
                        if value is None:
                            current.pop(key, None)
                        else:
                            current[key] = value
                    if not current:
                        state.pop(index, None)
                    applied = True
            if not applied:
                raise ValueError("resident material update has no valid targets or parameters")
            session.resident_material_parameters = state
            session.material_generation += 1
            return session.material_generation

    def resident_material_parameter_groups(self, session_id: str) -> tuple[dict[str, object], ...]:
        session = self._session(session_id)
        with session.export_lock:
            return _resident_material_groups(session)


__all__ = ["MeshResidentMaterialServiceMixin"]
