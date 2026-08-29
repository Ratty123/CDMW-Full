"""Atomic non-exact OBJ package output for Mesh Editor Free Edit sessions."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from cdmw.core.atomic_file import atomic_write_text
from cdmw.modding.mesh_exporter import export_obj
from cdmw.modding.mesh_obj_importer import import_obj
from cdmw.models import RunCancelled


FREE_EDIT_OUTPUT_FORMAT = "cdmw_mesh_free_edit_output_v1"


@dataclass(frozen=True, slots=True)
class MeshFreeEditOutputResult:
    output_dir: Path
    obj_path: Path
    manifest_path: Path
    mesh_revision: int
    vertex_count: int
    face_count: int
    exact_archive_writeback: bool = False
    output_policy: str = "free_edit_rebuild"


def publish_free_edit_output(
    snapshot: object,
    output_dir: Path | str,
    *,
    source_path: Path | str = "",
    stop_event: threading.Event | None = None,
) -> MeshFreeEditOutputResult:
    """Publish one new directory or nothing; the source asset is read-only."""

    target = Path(output_dir).expanduser().resolve(strict=False)
    if target.exists():
        raise FileExistsError(f"Free Edit output already exists: {target}")
    if not target.parent.is_dir():
        raise FileNotFoundError(f"Free Edit output parent does not exist: {target.parent}")
    source = Path(source_path).expanduser().resolve(strict=False) if str(source_path or "").strip() else None
    if source is not None and target == source:
        raise ValueError("Free Edit output must not overwrite the source asset")
    source_hash_before = _file_sha256(source)
    _raise_cancelled(stop_event)

    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
    try:
        mesh = getattr(snapshot, "mesh")
        stem = _safe_stem(Path(str(getattr(mesh, "path", "") or "mesh")).stem)
        exported = tuple(
            Path(path)
            for path in export_obj(
                mesh,
                str(staging),
                stem,
                extra_payload={
                    "output_policy": "free_edit_rebuild",
                    "exact_archive_writeback": False,
                    "source_preserved": True,
                },
            )
        )
        obj_path = staging / f"{stem}.obj"
        if obj_path not in exported or not obj_path.is_file():
            raise RuntimeError("Free Edit export did not create its OBJ geometry")
        # The ordinary OBJ sidecar is an exact source-lineage round-trip
        # contract. Free Edit intentionally permits new topology, so carrying
        # that sidecar would falsely claim the new vertices still map to the
        # original archive records and can make the package reject itself.
        exact_sidecar = Path(f"{obj_path}.meta.json")
        exact_sidecar.unlink(missing_ok=True)
        exported = tuple(path for path in exported if path != exact_sidecar)
        reparsed = import_obj(str(obj_path))
        expected_vertices = int(getattr(mesh, "total_vertices", 0) or 0)
        expected_faces = int(getattr(mesh, "total_faces", 0) or 0)
        if int(reparsed.total_vertices or 0) != expected_vertices:
            raise RuntimeError("Free Edit OBJ vertex count changed during output validation")
        if int(reparsed.total_faces or 0) != expected_faces:
            raise RuntimeError("Free Edit OBJ face count changed during output validation")
        manifest_path = staging / "free-edit-output.json"
        payload = {
            "format": FREE_EDIT_OUTPUT_FORMAT,
            "output_policy": "free_edit_rebuild",
            "exact_archive_writeback": False,
            "source_preserved": True,
            "source_path": str(source or ""),
            "source_sha256": source_hash_before,
            "mesh_revision": int(getattr(snapshot, "mesh_revision", 0) or 0),
            "native_edit_revision": int(getattr(snapshot, "native_edit_revision", 0) or 0),
            "vertex_count": expected_vertices,
            "face_count": expected_faces,
            "validation": "obj_reparse_passed",
            "artifacts": sorted(path.relative_to(staging).as_posix() for path in exported),
        }
        atomic_write_text(manifest_path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        _raise_cancelled(stop_event)
        if _file_sha256(source) != source_hash_before:
            raise RuntimeError("The Free Edit source asset changed while output was prepared")
        os.replace(staging, target)
        return MeshFreeEditOutputResult(
            output_dir=target,
            obj_path=target / obj_path.relative_to(staging),
            manifest_path=target / manifest_path.relative_to(staging),
            mesh_revision=int(getattr(snapshot, "mesh_revision", 0) or 0),
            vertex_count=expected_vertices,
            face_count=expected_faces,
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _raise_cancelled(stop_event: threading.Event | None) -> None:
    if stop_event is not None and stop_event.is_set():
        raise RunCancelled("Free Edit output cancelled")


def _file_sha256(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_stem(value: str) -> str:
    text = "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in value)
    return text.strip("_-") or "mesh"


__all__ = [
    "FREE_EDIT_OUTPUT_FORMAT",
    "MeshFreeEditOutputResult",
    "publish_free_edit_output",
]
