from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from cdmw.core.atomic_file import atomic_copy_file, atomic_write_bytes
from cdmw.domain.mesh import MeshExportValidationReport, MeshTextureEditTarget
from cdmw.modding.mesh_importer import MeshRebuildReport
from cdmw.models import RunCancelled
from cdmw.services.mesh_service_state import (
    MeshExportSnapshot,
    MeshExportTextureSnapshot,
    _MeshCommittedTextureResource,
    _MeshEditSession,
)


_NATIVE_MESH_FORMATS = frozenset({"pac", "pam", "pamlod"})
_MAX_RESIDENT_TEXTURE_DIMENSION = 32_768
_MAX_RESIDENT_TEXTURE_BYTES = 1 << 30
_BASE_TEXTURE_CHANNELS = frozenset({"base", "base_color", "albedo", "diffuse"})


def _service_call(name: str, *args: object, **kwargs: object) -> object:
    return getattr(sys.modules["cdmw.services.mesh_service"], name)(*args, **kwargs)


def _raise_if_cancelled(stop_event: object | None) -> None:
    if callable(getattr(stop_event, "is_set", None)) and stop_event.is_set():
        raise RunCancelled("Mesh export cancelled.")


def _raise_if_session_closed(session: _MeshEditSession) -> None:
    if session.closed:
        raise KeyError(f"Unknown mesh edit session: {session.session_id}")


def _normalized_resource_key(resource_id: object, channel: object) -> tuple[str, str]:
    resource = str(resource_id or "").strip()
    semantic = str(channel or "base").strip().lower() or "base"
    if not resource:
        raise ValueError("resident texture resource id is required")
    return resource, semantic


def _path_key(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return os.path.normcase(str(Path(raw).expanduser().resolve()))
    except OSError:
        return os.path.normcase(raw)


def _checked_texture_layout(width: object, height: object, row_pitch: object) -> tuple[int, int, int, int]:
    try:
        parsed_width = int(width)
        parsed_height = int(height)
        parsed_pitch = int(row_pitch)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("resident texture dimensions and row pitch must be integers") from exc
    if not (1 <= parsed_width <= _MAX_RESIDENT_TEXTURE_DIMENSION):
        raise ValueError("resident texture width is outside the supported range")
    if not (1 <= parsed_height <= _MAX_RESIDENT_TEXTURE_DIMENSION):
        raise ValueError("resident texture height is outside the supported range")
    tight_pitch = parsed_width * 4
    if parsed_pitch < tight_pitch:
        raise ValueError("resident texture row pitch is smaller than BGRA8 width")
    byte_count = parsed_pitch * parsed_height
    if byte_count > _MAX_RESIDENT_TEXTURE_BYTES:
        raise ValueError("resident texture payload exceeds the resource ceiling")
    return parsed_width, parsed_height, parsed_pitch, tight_pitch


def _payload_bytes(value: bytes | bytearray | memoryview | Path, required: int) -> bytes:
    if isinstance(value, Path):
        data = value.read_bytes()
    elif isinstance(value, (bytes, bytearray, memoryview)):
        data = bytes(value)
    else:
        raise TypeError("resident texture payload must be bytes-like or a Path")
    if len(data) < required:
        raise ValueError(f"resident texture payload is truncated: expected {required}, got {len(data)}")
    return data


def _tight_bgra_bytes(data: bytes, width: int, height: int, row_pitch: int) -> bytes:
    tight_pitch = width * 4
    if row_pitch == tight_pitch:
        return data[: tight_pitch * height]
    return b"".join(data[row * row_pitch : row * row_pitch + tight_pitch] for row in range(height))


def _resource_working_path(session: _MeshEditSession, resource_id: str, channel: str) -> Path:
    if session.texture_resource_root is None:
        session.texture_resource_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_texture_"))
    digest = hashlib.sha256(f"{resource_id}\0{channel}".encode("utf-8", errors="replace")).hexdigest()[:24]
    return session.texture_resource_root / f"{digest}.bgra"


def _resource_assignment_path(
    session: _MeshEditSession,
    resource_id: str,
    channel: str,
    revision: int,
) -> Path:
    if session.texture_resource_root is None:
        session.texture_resource_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_texture_"))
    digest = hashlib.sha256(f"{resource_id}\0{channel}".encode("utf-8", errors="replace")).hexdigest()[:24]
    return session.texture_resource_root / f"{digest}-{int(revision)}.dds"


def _affected_indices(values: Sequence[int]) -> tuple[int, ...]:
    result: set[int] = set()
    for value in values:
        try:
            index = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if index >= 0:
            result.add(index)
    return tuple(sorted(result))


def _native_source_parse_eligible(mesh: object, original_data: bytes) -> bool:
    declared_hash = str(getattr(mesh, "_cdmw_mesh_asset_source_hash", "") or "").strip().lower()
    return bool(
        original_data
        and str(getattr(mesh, "format", "") or "").strip().lower() in _NATIVE_MESH_FORMATS
        and not bool(getattr(mesh, "_cdmw_imported_from_obj", False))
        and not bool(getattr(mesh, "_cdmw_imported_from_glb", False))
        and not bool(getattr(mesh, "_cdmw_imported_from_scene", False))
        and (not declared_hash or declared_hash == hashlib.sha256(original_data).hexdigest())
    )


class MeshRebuildServiceMixin:
    def commit_texture_snapshot(
        self,
        session_id: str,
        resource_id: str,
        *,
        channel: str = "base",
        affected_submeshes: Sequence[int] = (),
        width: int,
        height: int,
        row_pitch: int,
        bgra: bytes | bytearray | memoryview | Path,
        logical_path: str = "",
    ) -> int:
        session = self._session(session_id)
        key = _normalized_resource_key(resource_id, channel)
        parsed_width, parsed_height, parsed_pitch, tight_pitch = _checked_texture_layout(width, height, row_pitch)
        data = _payload_bytes(bgra, parsed_pitch * parsed_height)
        tight = _tight_bgra_bytes(data, parsed_width, parsed_height, parsed_pitch)
        with session.export_lock:
            _raise_if_session_closed(session)
            target = _resource_working_path(session, *key)
            atomic_write_bytes(target, tight)
            previous = session.committed_texture_resources.get(key)
            revision = int(previous.revision if previous is not None else 0) + 1
            session.committed_texture_resources[key] = _MeshCommittedTextureResource(
                resource_id=key[0],
                channel=key[1],
                affected_submeshes=_affected_indices(affected_submeshes),
                revision=revision,
                logical_path=str(logical_path or getattr(previous, "logical_path", "") or ""),
                raw_bgra_path=str(target),
                width=parsed_width,
                height=parsed_height,
                row_pitch=tight_pitch,
            )
            session.material_generation += 1
            return revision

    def commit_texture_region(
        self,
        session_id: str,
        resource_id: str,
        *,
        channel: str = "base",
        affected_submeshes: Sequence[int] = (),
        rect: tuple[int, int, int, int],
        row_pitch: int,
        bgra: bytes | bytearray | memoryview | Path,
        expected_revision: int | None = None,
    ) -> int:
        session = self._session(session_id)
        key = _normalized_resource_key(resource_id, channel)
        with session.export_lock:
            _raise_if_session_closed(session)
            resource = session.committed_texture_resources.get(key)
            if resource is None or not resource.raw_bgra_path:
                raise KeyError(f"Unknown resident texture resource: {resource_id}:{channel}")
            if expected_revision is not None and int(expected_revision) != int(resource.revision):
                raise RuntimeError(
                    f"stale resident texture revision: expected {int(expected_revision)}, current {resource.revision}"
                )
            try:
                x, y, region_width, region_height = (int(value) for value in rect)
                patch_pitch = int(row_pitch)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("resident texture region must contain four integer coordinates") from exc
            if x < 0 or y < 0 or region_width <= 0 or region_height <= 0:
                raise ValueError("resident texture region is empty or outside the texture")
            if x + region_width > resource.width or y + region_height > resource.height:
                raise ValueError("resident texture region exceeds the texture bounds")
            tight_patch_pitch = region_width * 4
            if patch_pitch < tight_patch_pitch:
                raise ValueError("resident texture patch row pitch is smaller than BGRA8 width")
            patch = _payload_bytes(bgra, patch_pitch * region_height)
            target = Path(resource.raw_bgra_path)
            if not target.is_file():
                raise FileNotFoundError(f"resident texture working copy is missing: {target}")
            old_rows: list[bytes] = []
            with target.open("r+b") as handle:
                for row in range(region_height):
                    handle.seek((y + row) * resource.row_pitch + x * 4)
                    old = handle.read(tight_patch_pitch)
                    if len(old) != tight_patch_pitch:
                        raise ValueError("resident texture working copy is truncated")
                    old_rows.append(old)
                try:
                    for row in range(region_height):
                        handle.seek((y + row) * resource.row_pitch + x * 4)
                        start = row * patch_pitch
                        handle.write(patch[start : start + tight_patch_pitch])
                    handle.flush()
                    os.fsync(handle.fileno())
                except Exception:
                    for row, old in enumerate(old_rows):
                        handle.seek((y + row) * resource.row_pitch + x * 4)
                        handle.write(old)
                    handle.flush()
                    os.fsync(handle.fileno())
                    raise
            revision = int(resource.revision) + 1
            session.committed_texture_resources[key] = replace(
                resource,
                affected_submeshes=(
                    _affected_indices(affected_submeshes) or resource.affected_submeshes
                ),
                revision=revision,
            )
            session.material_generation += 1
            return revision

    def record_committed_texture_assignment(
        self,
        session_id: str,
        source_dds_path: Path | str,
        *,
        resource_id: str = "",
        channel: str = "base",
        affected_submeshes: Sequence[int] = (),
        logical_path: str = "",
        mesh_texture_assignment: bool = True,
    ) -> int:
        session = self._session(session_id)
        source = Path(source_dds_path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"committed texture source is missing: {source}")
        if str(resource_id or "").strip():
            normalized_resource = str(resource_id).strip()
        else:
            from cdmw.services.mesh_dotnet_material_state import mesh_dotnet_texture_resource_id

            normalized_resource = mesh_dotnet_texture_resource_id(source)
        key = _normalized_resource_key(normalized_resource, channel)
        with session.export_lock:
            _raise_if_session_closed(session)
            previous = session.committed_texture_resources.get(key)
            revision = int(previous.revision if previous is not None else 0) + 1
            owned_source = _resource_assignment_path(session, *key, revision)
            atomic_copy_file(source, owned_source)
            session.committed_texture_resources[key] = _MeshCommittedTextureResource(
                resource_id=key[0],
                channel=key[1],
                affected_submeshes=_affected_indices(affected_submeshes),
                revision=revision,
                logical_path=str(logical_path or source),
                source_dds_path=str(owned_source),
                assigned_source_path=str(source) if mesh_texture_assignment else "",
            )
            session.material_generation += 1
            return revision

    def mark_material_generation(self, session_id: str) -> int:
        session = self._session(session_id)
        with session.export_lock:
            _raise_if_session_closed(session)
            session.material_generation += 1
            return session.material_generation

    def dispose_export_resources(self, session: _MeshEditSession) -> None:
        with session.export_lock:
            root = session.texture_resource_root
            session.texture_resource_root = None
            session.committed_texture_resources.clear()
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)

    def capture_export_snapshot(
        self,
        session_id: str,
        *,
        stop_event: object | None = None,
        expected_mesh_revision: int | None = None,
    ) -> MeshExportSnapshot:
        session = self._session(session_id)
        _raise_if_cancelled(stop_event)
        with session.export_lock:
            _raise_if_session_closed(session)
            if expected_mesh_revision is not None and int(expected_mesh_revision) != int(session.revision):
                raise RuntimeError(
                    f"mesh export session changed before capture: expected revision {int(expected_mesh_revision)}, "
                    f"current revision {session.revision}"
                )
            captured_revision = int(session.revision)
            native_revision = captured_revision
            if session.native_editor_mesh_dirty:
                summary_before = _service_call(
                    "export_native_mesh_editor_session_snapshot",
                    session.session_id,
                    stop_event=stop_event,
                    timeout_seconds=20.0,
                )
                if not isinstance(summary_before, Mapping):
                    raise RuntimeError("native mesh editor export snapshot failed")
                native_revision = int(summary_before.get("edit_revision", -1) or 0)
                if native_revision != captured_revision:
                    raise RuntimeError(
                        f"native mesh export revision mismatch: service={captured_revision}, native={native_revision}"
                    )
                mesh = _service_call(
                    "_clone_mesh_for_service_native_snapshot",
                    session.working_mesh,
                    "session.export_snapshot_template",
                    "Python export snapshot fallback blocked while native mesh core is available",
                )
                if not _service_call(
                    "export_native_mesh_editor_session_to_mesh",
                    mesh,
                    session.session_id,
                    stop_event=stop_event,
                    timeout_seconds=20.0,
                ):
                    raise RuntimeError("native mesh editor session export failed")
                summary_after = _service_call(
                    "export_native_mesh_editor_session_snapshot",
                    session.session_id,
                    stop_event=stop_event,
                    timeout_seconds=20.0,
                )
                after_revision = int(summary_after.get("edit_revision", -1) or 0) if isinstance(summary_after, Mapping) else -1
                if after_revision != native_revision or int(session.revision) != captured_revision:
                    raise RuntimeError("mesh export session changed during native snapshot capture")
            else:
                mesh = _service_call(
                    "_clone_mesh_for_service_native_snapshot",
                    session.working_mesh,
                    "session.export_snapshot",
                    "Python export snapshot fallback blocked while native mesh core is available",
                )
            if int(session.revision) != captured_revision:
                raise RuntimeError("mesh export session changed during snapshot capture")
            _raise_if_cancelled(stop_event)
            texture_resources = self._capture_texture_resources(session, mesh)
            base_mesh = session.base_mesh if session.base_mesh_is_original_parse else None
            texture_revisions = tuple(
                (resource.resource_id, resource.channel, int(resource.revision))
                for resource in texture_resources
            )
            return MeshExportSnapshot(
                session_id=session.session_id,
                mesh_revision=captured_revision,
                native_edit_revision=native_revision,
                material_generation=int(session.material_generation),
                texture_revisions=texture_revisions,
                mesh=mesh,
                base_mesh=base_mesh,
                original_data=bytes(session.original_data),
                mesh_asset_parse_confidence=session.mesh_asset_parse_confidence,
                mesh_asset_source_hash=session.mesh_asset_source_hash,
                mesh_asset_source_size=session.mesh_asset_source_size,
                mesh_asset_inferred_bone_count=session.mesh_asset_inferred_bone_count,
                skeleton_bone_count=int(_service_call("_session_validation_skeleton_bone_count", session) or 0),
                no_op_roundtrip_report=(
                    dict(session.no_op_roundtrip_report)
                    if isinstance(session.no_op_roundtrip_report, Mapping)
                    else session.no_op_roundtrip_report
                ),
                sidecar_warnings=tuple(session.sidecar_warnings),
                edit_operations=tuple(
                    dict(operation) if isinstance(operation, Mapping) else operation
                    for operation in session.edit_operations
                ),
                requires_edit_operations=bool(session.requires_edit_operations),
                texture_resources=texture_resources,
                material_parameter_groups=self.resident_material_parameter_groups(session.session_id),
            )

    def _capture_texture_resources(
        self,
        session: _MeshEditSession,
        mesh: object,
    ) -> tuple[MeshExportTextureSnapshot, ...]:
        resources: list[MeshExportTextureSnapshot] = []
        submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
        all_indices = tuple(range(len(submeshes)))
        active_assignment_indices: dict[tuple[str, str], tuple[int, ...]] = {}
        assigned_targets_by_channel: dict[str, set[int]] = {}
        for key, resource in session.committed_texture_resources.items():
            if resource.channel not in _BASE_TEXTURE_CHANNELS or not resource.assigned_source_path:
                continue
            assigned_path = _path_key(resource.assigned_source_path)
            candidates = resource.affected_submeshes or all_indices
            active = tuple(
                index
                for index in candidates
                if 0 <= index < len(submeshes)
                and _path_key(getattr(submeshes[index], "texture", "")) == assigned_path
            )
            if active:
                active_assignment_indices[key] = active
                assigned_targets_by_channel.setdefault(resource.channel, set()).update(active)
        for key in sorted(session.committed_texture_resources):
            resource = session.committed_texture_resources[key]
            bound_indices = tuple(
                index
                for index in (resource.affected_submeshes or all_indices)
                if 0 <= index < len(submeshes)
            )
            if resource.channel in _BASE_TEXTURE_CHANNELS:
                if resource.assigned_source_path:
                    bound_indices = active_assignment_indices.get(key, ())
                else:
                    assigned = assigned_targets_by_channel.get(resource.channel, set())
                    bound_indices = tuple(index for index in bound_indices if index not in assigned)
            if not bound_indices:
                continue
            if resource.raw_bgra_path:
                raw_path = Path(resource.raw_bgra_path)
                data = raw_path.read_bytes()
                expected = int(resource.row_pitch) * int(resource.height)
                if len(data) != expected:
                    raise ValueError(f"resident texture working copy is truncated: {raw_path}")
                resources.append(
                    MeshExportTextureSnapshot(
                        resource_id=resource.resource_id,
                        channel=resource.channel,
                        affected_submeshes=bound_indices,
                        revision=resource.revision,
                        logical_path=resource.logical_path,
                        width=resource.width,
                        height=resource.height,
                        row_pitch=resource.row_pitch,
                        bgra_data=data,
                    )
                )
                continue
            if resource.source_dds_path:
                source = Path(resource.source_dds_path)
                if not source.is_file():
                    raise FileNotFoundError(f"committed texture source is missing: {source}")
                resources.append(
                    MeshExportTextureSnapshot(
                        resource_id=resource.resource_id,
                        channel=resource.channel,
                        affected_submeshes=bound_indices,
                        revision=resource.revision,
                        logical_path=resource.logical_path,
                        dds_data=source.read_bytes(),
                    )
                )
        return tuple(resources)

    def texture_edit_target(self, session_id: str) -> MeshTextureEditTarget | None:
        session = self._session(session_id)
        with session.export_lock:
            return self._texture_edit_target_locked(session)

    def _texture_edit_target_locked(self, session: _MeshEditSession) -> MeshTextureEditTarget | None:
        if session.native_editor_mesh_dirty:
            return _service_call("_mesh_texture_edit_target_from_native_summary",
                _service_call("summarize_native_mesh_editor_session", session.session_id),
                session.selection,
            )
        session.selection = _service_call("_prune_selection_to_mesh", session.working_mesh, session.selection)
        return _service_call("selected_mesh_texture_edit_target", session.working_mesh, session.selection)

    def validate_export(
        self,
        session_id: str,
        *,
        available_textures: Iterable[str] | None = None,
        skeleton_bone_count: int | None = None,
    ) -> MeshExportValidationReport:
        session = self._session(session_id)
        with session.export_lock:
            return self._validate_export_locked(
                session,
                available_textures=available_textures,
                skeleton_bone_count=skeleton_bone_count,
            )

    def _validate_export_locked(
        self,
        session: _MeshEditSession,
        *,
        available_textures: Iterable[str] | None,
        skeleton_bone_count: int | None,
    ) -> MeshExportValidationReport:
        if session.native_editor_mesh_dirty and not _service_call("_sync_native_editor_session_to_working_mesh", session):
            raise RuntimeError("native mesh editor session export failed; Python mesh state is stale")
        if skeleton_bone_count is None:
            skeleton_bone_count = _service_call("_session_validation_skeleton_bone_count", session)
        return _service_call("validate_mesh_export",
            session.working_mesh,
            original_mesh=session.base_mesh,
            available_textures=available_textures,
            skeleton_bone_count=skeleton_bone_count,
            parse_confidence=session.mesh_asset_parse_confidence,
            source_asset_hash=session.mesh_asset_source_hash,
            no_op_roundtrip_status=_service_call("_session_roundtrip_status", session),
            no_op_byte_identical=_service_call("_session_roundtrip_byte_identical", session),
            no_op_unexpected_differences=_service_call("_session_roundtrip_unexpected_differences", session),
            sidecar_warnings=session.sidecar_warnings,
            edit_operations=session.edit_operations,
            requires_edit_operations=session.requires_edit_operations,
        )

    def validate_export_snapshot(
        self,
        snapshot: MeshExportSnapshot,
        *,
        available_textures: Iterable[str] | None = None,
        skeleton_bone_count: int | None = None,
    ) -> MeshExportValidationReport:
        no_op = snapshot.no_op_roundtrip_report if isinstance(snapshot.no_op_roundtrip_report, Mapping) else {}
        return _service_call(
            "validate_mesh_export",
            snapshot.mesh,
            original_mesh=snapshot.base_mesh,
            available_textures=available_textures,
            skeleton_bone_count=(
                skeleton_bone_count
                if skeleton_bone_count is not None
                else max(0, int(snapshot.skeleton_bone_count or snapshot.mesh_asset_inferred_bone_count or 0)) or None
            ),
            parse_confidence=snapshot.mesh_asset_parse_confidence,
            source_asset_hash=snapshot.mesh_asset_source_hash,
            no_op_roundtrip_status=str(no_op.get("result", "") or no_op.get("status", "") or ""),
            no_op_byte_identical=(bool(no_op.get("byte_identical")) if "byte_identical" in no_op else None),
            no_op_unexpected_differences=int(no_op.get("unexpected_differences", 0) or 0),
            sidecar_warnings=snapshot.sidecar_warnings,
            edit_operations=snapshot.edit_operations,
            requires_edit_operations=snapshot.requires_edit_operations,
        )

    @staticmethod
    def export_snapshot_report(
        snapshot: MeshExportSnapshot,
        *,
        artifacts: Sequence[Mapping[str, object]] = (),
        output_reparse: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "schema": "cdmw_mesh_export_snapshot_v1",
            "version": 1,
            "session_id": snapshot.session_id,
            "mesh_revision": int(snapshot.mesh_revision),
            "native_edit_revision": int(snapshot.native_edit_revision),
            "source_asset_hash": snapshot.mesh_asset_source_hash,
            "source_asset_size": int(snapshot.mesh_asset_source_size),
            "material_generation": int(snapshot.material_generation),
            "texture_revisions": [
                {"resource_id": resource_id, "channel": channel, "revision": int(revision)}
                for resource_id, channel, revision in snapshot.texture_revisions
            ],
            "texture_resources": [
                {
                    "resource_id": resource.resource_id,
                    "channel": resource.channel,
                    "revision": int(resource.revision),
                    "affected_submeshes": list(resource.affected_submeshes),
                    "logical_path": resource.logical_path,
                    "width": int(resource.width),
                    "height": int(resource.height),
                    "source_kind": "raw_bgra" if resource.bgra_data else "dds",
                }
                for resource in snapshot.texture_resources
            ],
            "material_parameter_groups": [dict(group) for group in snapshot.material_parameter_groups],
            "artifacts": [dict(artifact) for artifact in artifacts],
            "output_reparse": dict(output_reparse or {"status": "not_run"}),
        }

    def rebuild_report(
        self,
        session_id: str,
        *,
        available_textures: Iterable[str] | None = None,
        skeleton_bone_count: int | None = None,
        output_path: str = "",
        developer_override: bool = False,
        developer_override_reason: str = "",
    ) -> MeshRebuildReport:
        snapshot = self.capture_export_snapshot(session_id)
        _result, report = self.rebuild_result_from_snapshot(
            snapshot,
            available_textures=available_textures,
            skeleton_bone_count=skeleton_bone_count,
            output_path=output_path,
            developer_override=developer_override,
            developer_override_reason=developer_override_reason,
        )
        return report

    def rebuild_asset(
        self,
        session_id: str,
        output_path: Path | str,
        *,
        available_textures: Iterable[str] | None = None,
        skeleton_bone_count: int | None = None,
        developer_override: bool = False,
        developer_override_reason: str = "",
    ) -> MeshRebuildReport:
        target = Path(output_path)
        if not str(target).strip():
            raise RuntimeError("mesh rebuild output path is required")
        session = self._session(session_id)
        source_text = str(getattr(session.base_mesh, "path", "") or getattr(session.working_mesh, "path", "") or "").strip()
        if source_text and target.resolve(strict=False) == Path(source_text).resolve(strict=False):
            raise RuntimeError("mesh rebuild output must not overwrite the original source asset")
        snapshot = self.capture_export_snapshot(session_id)
        result, report = self.rebuild_result_from_snapshot(
            snapshot,
            available_textures=available_textures,
            skeleton_bone_count=skeleton_bone_count,
            output_path=str(target),
            developer_override=developer_override,
            developer_override_reason=developer_override_reason,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        _service_call("atomic_write_bytes", target, result.data)
        return report

    def rebuild_result_from_snapshot(
        self,
        snapshot: MeshExportSnapshot,
        *,
        available_textures: Iterable[str] | None = None,
        skeleton_bone_count: int | None = None,
        output_path: str = "",
        developer_override: bool = False,
        developer_override_reason: str = "",
    ):
        if not snapshot.original_data:
            raise RuntimeError("mesh rebuild report requires original source bytes")
        validation = self.validate_export_snapshot(
            snapshot,
            available_textures=available_textures,
            skeleton_bone_count=skeleton_bone_count,
        )
        overridden_blockers: tuple[str, ...] = ()
        if not validation.ok:
            overridden_blockers = _service_call("_developer_override_blocker_codes",
                validation,
                enabled=developer_override,
                output_path=output_path,
            )
            if not overridden_blockers:
                codes = ", ".join(issue.code for issue in validation.blockers[:6]) or "validation blocked rebuild"
                raise RuntimeError(f"mesh rebuild blocked: {codes}")
        if snapshot.edit_operations:
            setattr(snapshot.mesh, "_cdmw_edit_operations", tuple(snapshot.edit_operations))
        result = _service_call("rebuild_mesh_with_report",
            snapshot.mesh,
            snapshot.original_data,
            validation_status="developer_override" if overridden_blockers else "passed",
            output_path=output_path,
            original_mesh=snapshot.base_mesh,
        )
        override_entries = _service_call("_developer_override_report_entries",
            developer_override_reason,
            overridden_blockers,
        )
        report = replace(
            result.report,
            validation_status="developer_override" if overridden_blockers else "passed",
            warnings=tuple(issue.code for issue in validation.warnings)
            + tuple(f"developer_override_blocker:{code}" for code in overridden_blockers),
            developer_overrides=tuple(getattr(result.report, "developer_overrides", ()) or ()) + override_entries,
            edit_operations=tuple(
                dict(operation) if isinstance(operation, Mapping) else operation
                for operation in snapshot.edit_operations
            ),
            output_path=str(output_path or result.report.output_path or ""),
            export_snapshot=self.export_snapshot_report(snapshot),
        )
        return result, report

    def _rebuild_result(self, session_id: str, **kwargs: object):
        return self.rebuild_result_from_snapshot(self.capture_export_snapshot(session_id), **kwargs)
