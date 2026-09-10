"""Keep archive Refit assets separate while editing their geometry together."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import copy
import hashlib
from pathlib import Path
from uuid import uuid4

from cdmw.domain.mesh.export_validation import MeshExportValidationReport
from cdmw.modding.mesh_edit_ops import refresh_mesh_totals
from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
from cdmw.services.mesh_service_state import MeshExportSnapshot


@dataclass(frozen=True, slots=True)
class ArchiveRefitAsset:
    entry: object
    source: MeshExportSnapshot
    part_indices: tuple[int, ...]
    role: str
    preview_lease: object | None = None
    neutral_appearance: NeutralMeshAppearance | None = None


class ArchiveRefitPreviewLease:
    """Share one cache lease across shadow, authoritative and history snapshots."""

    def __init__(self, context):
        self.lease = context.material_package_lease

    def __deepcopy__(self, _memo):
        return self

    def __del__(self):
        try:
            if self.lease is not None:
                self.lease.release()
        except Exception:
            pass


@dataclass(frozen=True, slots=True)
class ArchiveRefitContext:
    assets: tuple[ArchiveRefitAsset, ...]
    context_id: str = field(default_factory=lambda: uuid4().hex)
    neutral_coordinates: bool = False


def _clone(mesh):
    from cdmw.services.mesh_service import _clone_mesh_for_service_native_snapshot

    return _clone_mesh_for_service_native_snapshot(
        mesh, "session.archive_refit", "Archive Refit native mesh snapshot failed"
    )


def transform_archive_refit_mesh(mesh, context, *, to_neutral):
    """Convert each asset with its own palette; retain combined Part/LOD aliases."""
    indices = [index for asset in context.assets for index in asset.part_indices]
    if sorted(indices) != list(range(len(mesh.submeshes))):
        raise ValueError("Archive Refit Part identities changed; undo the Part addition or removal")
    result = _clone(mesh)
    for asset_index, asset in enumerate(context.assets):
        appearance = asset.neutral_appearance
        if appearance is None:
            continue
        subset = copy.copy(result)
        subset.submeshes = [result.submeshes[index] for index in asset.part_indices]
        # The combined document retains the primary asset's additional LODs.
        # Incoming assets contribute only their editable Parts.
        subset.lod_levels = [subset.submeshes, *(result.lod_levels[1:] if asset_index == 0 else ())]
        converted = (appearance.to_neutral(subset) if to_neutral
                     else appearance.to_source(subset, asset.source.mesh))
        for original_level, converted_level in zip(subset.lod_levels, converted.lod_levels, strict=True):
            for original, part in zip(original_level, converted_level, strict=True):
                for channel in ("vertices", "normals", "tangents", "tangent_signs"):
                    if hasattr(part, channel):
                        setattr(original, channel, getattr(part, channel))
    refresh_mesh_totals(result)
    return result


def append_archive_refit(current, primary_entry, incoming, entry, role, preview_lease=None,
                         *, primary_source=None, primary_appearance=None, incoming_appearance=None):
    if role not in {"body", "armor"}:
        raise ValueError("Archive Refit role must be body or armor")
    if current.texture_resources or incoming.texture_resources:
        raise ValueError("Finish texture edits before loading an archive Refit mesh")
    context = current.archive_refit_context
    assets = context.assets if isinstance(context, ArchiveRefitContext) else (
        ArchiveRefitAsset(copy.copy(primary_entry), replace(primary_source or current, archive_refit_context=None),
                          tuple(range(len(current.mesh.submeshes))), "loaded",
                          neutral_appearance=primary_appearance),
    )
    source_paths = {str(asset.entry.path).replace("\\", "/").casefold() for asset in assets}
    if str(entry.path).replace("\\", "/").casefold() in source_paths:
        raise ValueError("This archive mesh is already loaded; select its Parts instead")
    if not incoming.original_data or not incoming.mesh.submeshes:
        raise ValueError("Archive Refit needs a parsed game asset with original source bytes")
    if Path(primary_entry.pamt_path).resolve().parent.parent != Path(entry.pamt_path).resolve().parent.parent:
        raise ValueError("Archive Refit assets must belong to the same loaded game archive root")
    for source in (primary_source or current, incoming) if context is None else (incoming,):
        base = source.base_mesh
        if base is None or len(base.submeshes) != len(source.mesh.submeshes) or any(
            len(original.vertices) != len(edited.vertices) or original.faces != edited.faces
            for original, edited in zip(base.submeshes, source.mesh.submeshes, strict=True)
        ):
            raise ValueError("Archive Refit requires the original mesh topology; undo topology changes before loading")
    combined = _clone(current.mesh)
    imported = (incoming_appearance.to_neutral(incoming.mesh) if incoming_appearance is not None
                else _clone(incoming.mesh))
    first = len(combined.submeshes)
    combined.submeshes.extend(imported.submeshes)
    combined.has_bones = combined.has_bones or imported.has_bones
    combined.has_uvs = combined.has_uvs or imported.has_uvs
    refresh_mesh_totals(combined)
    indices = tuple(range(first, len(combined.submeshes)))
    return combined, ArchiveRefitContext((*assets, ArchiveRefitAsset(
        copy.copy(entry), replace(incoming, archive_refit_context=None), indices, role, preview_lease,
        incoming_appearance,
    )), neutral_coordinates=bool(
        (context is not None and context.neutral_coordinates)
        or primary_appearance is not None or incoming_appearance is not None
    )), indices


def archive_refit_snapshots(snapshot):
    context = snapshot.archive_refit_context
    if not isinstance(context, ArchiveRefitContext):
        raise ValueError("Archive Refit asset identities are unavailable")
    all_indices = [index for asset in context.assets for index in asset.part_indices]
    if sorted(all_indices) != list(range(len(snapshot.mesh.submeshes))):
        raise ValueError("Archive Refit Part identities changed; undo the Part addition or removal")
    result = []
    edited = (transform_archive_refit_mesh(snapshot.mesh, context, to_neutral=False)
              if context.neutral_coordinates else _clone(snapshot.mesh))
    for asset in context.assets:
        mesh = _clone(asset.source.mesh)
        parts = [edited.submeshes[index] for index in asset.part_indices]
        if len(parts) != len(mesh.submeshes):
            raise ValueError("Archive Refit Part table no longer matches its source")
        for original, part in zip(mesh.submeshes, parts, strict=True):
            if len(original.vertices) != len(part.vertices) or original.faces != part.faces:
                raise ValueError("Archive Refit preserves each source topology; undo topology edits")
            # The archive parse owns offsets, descriptors, palettes and material identity.
            # Native history/drafts own only the edited channels, never that provenance.
            for channel in ("vertices", "normals", "uvs", "tangents", "tangent_signs", "bone_indices", "bone_weights"):
                if hasattr(part, channel):
                    setattr(original, channel, getattr(part, channel))
        refresh_mesh_totals(mesh)
        result.append((asset.entry, replace(
            asset.source, mesh=mesh, mesh_revision=snapshot.mesh_revision,
            native_edit_revision=snapshot.native_edit_revision, archive_refit_context=None,
        )))
    return tuple(result)


def validate_archive_refit(service, snapshot):
    reports = []
    issues = []
    for asset, (entry, component) in zip(snapshot.archive_refit_context.assets,
                                       archive_refit_snapshots(snapshot), strict=True):
        report = service.validate_export_snapshot(component)
        reports.append(report)
        issues.extend(replace(
            issue, message=f"{entry.path}: {issue.message}",
            submesh_index=(asset.part_indices[issue.submesh_index]
                           if 0 <= issue.submesh_index < len(asset.part_indices) else -1),
        ) for issue in report.issues)
    return MeshExportValidationReport(
        mesh_format=snapshot.mesh.format,
        submesh_count=sum(report.submesh_count for report in reports),
        vertex_count=sum(report.vertex_count for report in reports),
        face_count=sum(report.face_count for report in reports),
        issues=tuple(issues),
        parse_confidence=(reports[0].parse_confidence if len({report.parse_confidence for report in reports}) == 1 else "mixed"),
        no_op_roundtrip_status=("passed" if all(report.no_op_roundtrip_status.casefold() in {"pass", "passed"} for report in reports) else "blocked"),
        no_op_byte_identical=all(report.no_op_byte_identical for report in reports),
    )


def archive_refit_candidate_snapshot(session, mesh, context):
    """Only the combined geometry and identities are consumed by the splitter."""
    return MeshExportSnapshot(
        session_id=session.session_id, mesh_revision=session.revision,
        native_edit_revision=session.revision, material_generation=0,
        texture_revisions=(), mesh=mesh, base_mesh=None, original_data=b"",
        archive_refit_context=context,
    )


def save_archive_refit_context(context, project_root, stop_event):
    """Persist immutable source bytes once; the layer generation owns the mapping."""
    if context is None:
        return None
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.services.atomic_file_service import atomic_write_bytes

    assets = []
    for asset in context.assets:
        raise_if_cancelled(stop_event, "Archive Refit draft save cancelled")
        digest = hashlib.sha256(asset.source.original_data).hexdigest()
        relative = f"archive-refit-sources/{digest}.bin"
        path = project_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            atomic_write_bytes(path, asset.source.original_data)
        elif path.stat().st_size != len(asset.source.original_data) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Archive Refit draft source checksum failed")
        entry = asset.entry
        assets.append({
            "entry": {"path": entry.path, "pamt_path": str(entry.pamt_path), "paz_file": str(entry.paz_file),
                      "offset": entry.offset, "comp_size": entry.comp_size, "orig_size": entry.orig_size,
                      "flags": entry.flags, "paz_index": entry.paz_index},
            "source": relative, "sha256": digest, "size": len(asset.source.original_data),
            "parts": list(asset.part_indices), "role": asset.role,
            "skeleton_bone_count": asset.source.skeleton_bone_count,
            **({"neutral_appearance": {"version": 1, **asdict(asset.neutral_appearance)}}
               if asset.neutral_appearance is not None else {}),
        })
    return {"format": "cdmw_archive_refit_v2", "assets": assets,
            "coordinates": "neutral" if context.neutral_coordinates else "source"}


def load_archive_refit_context(payload, project_root):
    if payload is None:
        return None
    from cdmw.models import ArchiveEntry
    from cdmw.services.mesh_service import MeshService

    if not isinstance(payload, dict) or payload.get("format") not in {"cdmw_archive_refit_v1", "cdmw_archive_refit_v2"}:
        raise ValueError("Unsupported archive Refit draft format")
    coordinates = payload.get("coordinates", "source")
    if coordinates not in {"source", "neutral"}:
        raise ValueError("Unsupported archive Refit coordinate space")
    assets = []
    service = MeshService()
    for item in payload["assets"]:
        path = (project_root / str(item["source"])).resolve(strict=True)
        if not path.is_relative_to(project_root.resolve()) or path.stat().st_size != int(item["size"]):
            raise ValueError("Archive Refit draft source is unavailable or outside the project")
        if not 0 < path.stat().st_size <= 256 * 1024 * 1024:
            raise ValueError("Archive Refit draft source size is invalid")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("Archive Refit draft source checksum failed")
        raw_entry = dict(item["entry"])
        raw_entry["pamt_path"] = Path(raw_entry["pamt_path"])
        raw_entry["paz_file"] = Path(raw_entry["paz_file"])
        entry = ArchiveEntry(**raw_entry)
        mesh = service.load_mesh_bytes(data, entry.path, run_roundtrip=True)
        session_id = service.open_edit_session(mesh, load_layer_project=False).session_id
        try:
            source = service.capture_export_snapshot(session_id)
            source = replace(source, skeleton_bone_count=max(0, int(item["skeleton_bone_count"])))
        finally:
            service.close_edit_session(session_id, force_without_saving=True)
        appearance = None
        if "neutral_appearance" in item:
            from cdmw.modding.mesh_importer import _load_obj_neutral_appearance
            try:
                appearance = _load_obj_neutral_appearance(item["neutral_appearance"])
            except ValueError as exc:
                raise ValueError(f"Archive Refit draft neutral appearance is invalid: {exc}") from exc
        assets.append(ArchiveRefitAsset(entry, source, tuple(int(i) for i in item["parts"]), str(item["role"]),
                                       neutral_appearance=appearance))
    if not assets:
        raise ValueError("Archive Refit draft contains no asset identities")
    return ArchiveRefitContext(tuple(assets), neutral_coordinates=coordinates == "neutral")
