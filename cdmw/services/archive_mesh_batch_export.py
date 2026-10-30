"""One cancellable batch item, using the ordinary archive mesh exporter."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from cdmw.core.common import raise_if_cancelled
from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.services.archive_preview_service import build_archive_preview_result
from cdmw.services.archive_workflow_service import export_archive_mesh


@dataclass(frozen=True)
class BatchMeshExportRequest:
    request_id: int
    entry: ArchiveEntry
    output_root: Path
    export_format: str
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]]
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]]
    allow_missing_skeleton: bool = False


@dataclass(frozen=True)
class BatchMeshExportResult:
    request_id: int
    status: str
    source_path: str
    output_directory: Path | None = None
    details: tuple[str, ...] = ()


def _reserve_model_directory(root: Path, entry: ArchiveEntry) -> Path:
    # A short leaf name also leaves room for the exporter's referenced_files tree.
    stem = PurePosixPath(entry.path.replace("\\", "/")).stem
    stem = re.sub(r'[^\w. -]', "_", stem, flags=re.UNICODE).strip(" .")[:72] or "model"
    # The prefix avoids Windows device names, including CON, AUX and LPT1.
    for number in range(1, 100_001):
        suffix = "" if number == 1 else f"_{number}"
        target = root / f"model_{stem}{suffix}"
        try:
            target.mkdir()
            return target
        except FileExistsError:
            continue
    raise ValueError("No unused output folder is available for this model.")


def export_batch_mesh_item(request: BatchMeshExportRequest, *, stop_event: object) -> BatchMeshExportResult:
    """Preserve a committed success even if Cancel arrives just after publication."""
    target = None
    try:
        raise_if_cancelled(stop_event)
        if request.export_format not in {"obj", "fbx"} or request.entry.extension not in ARCHIVE_MESH_EXTENSIONS:
            raise ValueError("Select a PAC, PAM or PAMLOD model and OBJ or FBX output.")
        preview = build_archive_preview_result(
            request.entry, (),
            texture_entries_by_normalized_path=dict(request.entries_by_path),
            texture_entries_by_basename=dict(request.entries_by_basename),
            include_loose_preview_assets=False,
            stop_event=stop_event,
        )
        raise_if_cancelled(stop_event)
        references = tuple(preview.model_texture_references or ())
        related = {ref.resolved_entry.identity: ref.resolved_entry for ref in references
                   if ref.resolved_entry is not None and ref.resolved_entry.identity != request.entry.identity}
        request.output_root.mkdir(parents=True, exist_ok=True)
        target = _reserve_model_directory(request.output_root, request.entry)
        result = export_archive_mesh(
            request.entry, target, request.export_format,
            archive_entries_by_normalized_path=request.entries_by_path,
            archive_entries_by_basename=request.entries_by_basename,
            related_entries=tuple(related.values()),
            model_texture_references=references,
            asset_family_graph=preview.asset_family_graph,
            build_preview_context=False,
            allow_missing_skeleton=request.allow_missing_skeleton,
            stop_event=stop_event,
        )
        if result.requires_confirmation:
            raise ValueError("No usable skeleton was found. Mesh-only FBX export was not enabled.")
        elif not result.output_paths:
            raise ValueError("The exporter did not produce any files.")
        else:
            return BatchMeshExportResult(request.request_id, "exported", request.entry.path, target,
                                         tuple(result.summary_lines))
    except RunCancelled:
        status, details = "cancelled", ()
    except Exception as exc:
        status, details = "failed", (str(exc),)
    if target is not None:
        try:
            # Only remove our newly reserved folder if it is empty.
            target.rmdir()
            target = None
        except OSError:
            pass
    return BatchMeshExportResult(request.request_id, status, request.entry.path, target, details)
