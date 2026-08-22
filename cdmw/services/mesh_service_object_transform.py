"""Undoable whole-mesh object transforms for resident Mesh Editor sessions."""

from __future__ import annotations

import math
import sys
import threading
from collections.abc import Sequence

from cdmw.domain.mesh import MeshObjectTransformState
from cdmw.modding.mesh_native_core import apply_native_mesh_affine_transform_submeshes
from cdmw.models import RunCancelled
from cdmw.services.mesh_service_state import _MeshEditSession


def _service_call(name: str, *args: object, **kwargs: object) -> object:
    return getattr(sys.modules["cdmw.services.mesh_service"], name)(*args, **kwargs)


def mesh_source_bounds_pivot(mesh: object) -> tuple[float, float, float]:
    vertices = [
        tuple(float(value) for value in vertex[:3])
        for submesh in tuple(getattr(mesh, "submeshes", ()) or ())
        for vertex in tuple(getattr(submesh, "vertices", ()) or ())
        if len(vertex) >= 3 and all(math.isfinite(float(value)) for value in vertex[:3])
    ]
    if not vertices:
        return (0.0, 0.0, 0.0)
    return tuple(
        (min(vertex[axis] for vertex in vertices) + max(vertex[axis] for vertex in vertices)) * 0.5
        for axis in range(3)
    )  # type: ignore[return-value]


def _mat3_multiply(left: Sequence[float], right: Sequence[float]) -> tuple[float, ...]:
    return tuple(
        sum(float(left[row * 3 + inner]) * float(right[inner * 3 + column]) for inner in range(3))
        for row in range(3)
        for column in range(3)
    )


def _mat3_vector(matrix: Sequence[float], vector: Sequence[float]) -> tuple[float, float, float]:
    return tuple(
        sum(float(matrix[row * 3 + column]) * float(vector[column]) for column in range(3))
        for row in range(3)
    )  # type: ignore[return-value]


def _mat3_inverse(matrix: Sequence[float]) -> tuple[float, ...]:
    a, b, c, d, e, f, g, h, i = (float(value) for value in matrix)
    determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if not math.isfinite(determinant) or abs(determinant) <= 1.0e-12:
        raise ValueError("Mesh object transform scale produced a singular matrix")
    inverse = 1.0 / determinant
    return (
        (e * i - f * h) * inverse,
        (c * h - b * i) * inverse,
        (b * f - c * e) * inverse,
        (f * g - d * i) * inverse,
        (a * i - c * g) * inverse,
        (c * d - a * f) * inverse,
        (d * h - e * g) * inverse,
        (b * g - a * h) * inverse,
        (a * e - b * d) * inverse,
    )


def _mat3_transpose(matrix: Sequence[float]) -> tuple[float, ...]:
    return tuple(float(matrix[column * 3 + row]) for row in range(3) for column in range(3))


def _absolute_affine(state: MeshObjectTransformState) -> tuple[tuple[float, ...], tuple[float, float, float]]:
    rx, ry, rz = (math.radians(float(value)) for value in state.rotation_degrees)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    rotation_x = (1.0, 0.0, 0.0, 0.0, cx, -sx, 0.0, sx, cx)
    rotation_y = (cy, 0.0, sy, 0.0, 1.0, 0.0, -sy, 0.0, cy)
    rotation_z = (cz, -sz, 0.0, sz, cz, 0.0, 0.0, 0.0, 1.0)
    rotation = _mat3_multiply(rotation_z, _mat3_multiply(rotation_y, rotation_x))
    scale = (
        float(state.scale[0]), 0.0, 0.0,
        0.0, float(state.scale[1]), 0.0,
        0.0, 0.0, float(state.scale[2]),
    )
    linear = _mat3_multiply(rotation, scale)
    transformed_pivot = _mat3_vector(linear, state.pivot)
    translation = tuple(
        float(state.pivot[axis]) + float(state.location[axis]) - transformed_pivot[axis]
        for axis in range(3)
    )
    return linear, translation  # type: ignore[return-value]


def object_transform_delta_matrices(
    previous: MeshObjectTransformState,
    current: MeshObjectTransformState,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    old_linear, old_translation = _absolute_affine(previous)
    new_linear, new_translation = _absolute_affine(current)
    inverse_old = _mat3_inverse(old_linear)
    delta_linear = _mat3_multiply(new_linear, inverse_old)
    inverse_old_translation = _mat3_vector(inverse_old, old_translation)
    delta_translation = tuple(
        float(new_translation[axis]) - value
        for axis, value in enumerate(_mat3_vector(new_linear, inverse_old_translation))
    )
    position_matrix = (
        delta_linear[0], delta_linear[1], delta_linear[2], delta_translation[0],
        delta_linear[3], delta_linear[4], delta_linear[5], delta_translation[1],
        delta_linear[6], delta_linear[7], delta_linear[8], delta_translation[2],
    )
    normal_matrix = _mat3_transpose(_mat3_inverse(delta_linear))
    return position_matrix, normal_matrix


class MeshObjectTransformServiceMixin:
    def set_object_transform(
        self,
        session_id: str,
        *,
        location: Sequence[float] | None = None,
        rotation_degrees: Sequence[float] | None = None,
        scale: Sequence[float] | None = None,
        label: str = "Object Transform",
        stop_event: threading.Event | None = None,
    ):
        session: _MeshEditSession = self._session(session_id)
        with session.export_lock:
            previous = session.object_transform
            current = MeshObjectTransformState(
                location=tuple(location) if location is not None else previous.location,
                rotation_degrees=(
                    tuple(rotation_degrees) if rotation_degrees is not None else previous.rotation_degrees
                ),
                scale=tuple(scale) if scale is not None else previous.scale,
                pivot=previous.pivot,
            )
            if current == previous:
                return self._result(session, "object_transform", status="noop")
            if stop_event is not None and stop_event.is_set():
                raise RunCancelled("Mesh object transform cancelled")

            # Export any resident stroke before cloning; the Python copy must be
            # the authoritative revision the reader can currently see.
            self._working_mesh_locked(session, clone=False)
            candidate = _service_call(
                "_clone_mesh_for_service_native_snapshot",
                session.working_mesh,
                "session.object_transform_candidate",
                "Python object-transform clone fallback blocked while native mesh core is available",
            )
            position_matrix, normal_matrix = object_transform_delta_matrices(previous, current)
            target_indices = tuple(range(len(candidate.submeshes)))
            changed = apply_native_mesh_affine_transform_submeshes(
                candidate.submeshes,
                position_matrices_by_index={index: position_matrix for index in target_indices},
                normal_matrices_by_index={index: normal_matrix for index in target_indices},
                timeout_seconds=20.0,
            )
            if changed is None or set(changed) != set(target_indices):
                raise RuntimeError("Native whole-mesh object transform did not update every mesh part")
            if stop_event is not None and stop_event.is_set():
                raise RunCancelled("Mesh object transform cancelled")

            snapshot = _service_call("_snapshot", session, prefer_native=True)
            snapshot.history_action = "object_transform"
            snapshot.history_label = str(label or "Object Transform")
            snapshot.object_transform = previous
            snapshot.retained_bytes = _service_call("_history_snapshot_retained_bytes", snapshot)
            _service_call("_close_native_editor_session", session)
            reopened_for_autosave = False
            if session.mesh_layer_project_path is not None:
                opened = _service_call(
                    "open_native_mesh_editor_session",
                    candidate,
                    session.session_id,
                    stop_event=stop_event,
                    timeout_seconds=20.0,
                )
                if opened is None:
                    raise RuntimeError("Mesh object transform could not establish its draft autosave session")
                reopened_for_autosave = True
            self._push_history_snapshot(session, snapshot)
            _service_call("_clear_history_stack", session.redo_stack)
            session.working_mesh = candidate
            session.object_transform = current
            session.revision += 1
            if reopened_for_autosave:
                session.native_editor_session_ready = True
                session.native_editor_mesh_signature = _service_call(
                    "_native_editor_mesh_storage_signature", candidate
                )
            _service_call("refresh_mesh_totals", candidate)
            self._trim_session_history(session)
            self._schedule_mesh_layer_autosave(session)
            changed_vertices = {
                index: range(len(tuple(getattr(submesh, "vertices", ()) or ())))
                for index, submesh in enumerate(candidate.submeshes)
            }
            return self._result(
                session,
                "object_transform",
                affected=set(target_indices),
                changed=changed_vertices,
            )


__all__ = [
    "MeshObjectTransformServiceMixin",
    "mesh_source_bounds_pivot",
    "object_transform_delta_matrices",
]
