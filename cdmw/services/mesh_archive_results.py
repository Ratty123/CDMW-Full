"""Prepare edited archive assets with their source dependency context, read-only."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass, replace
import hashlib
from pathlib import Path
import tempfile
from uuid import uuid4

from cdmw.core.atomic_file import atomic_publish_paths
from cdmw.core.common import raise_if_cancelled
from cdmw.models import ArchiveEntry, ArchiveEntryIdentity
from cdmw.services.archive_read_service import read_archive_entry_data


MAX_RESULT_ENTRIES = 8192
MAX_RESULT_BYTES = 1024 * 1024 * 1024
EDITED_RESULT_NOTE = "Mesh Editor edited result"
ADDED_RESULT_NOTE = "Mesh Editor added result"
# The body a Fit followed. Later passes carry it like an edited result, but
# Build Mod leaves it out unless Include the body is chosen.
BODY_RESULT_NOTE = "Mesh Editor Fit body result"
RESULT_NOTES = (EDITED_RESULT_NOTE, ADDED_RESULT_NOTE, BODY_RESULT_NOTE)


@dataclass(frozen=True, slots=True)
class MeshArchiveMaterialContext:
    """Bounded material metadata with a pin independent of the editing session."""

    source_identity: ArchiveEntryIdentity
    preview_model: object
    package_path: str
    package_lease: object | None = field(repr=False, compare=False)
    resource_leases: tuple = field(default=(), repr=False, compare=False)

    def open_arguments(self) -> dict:
        # Each reopen owns a new pin. Closing it must not unpin the browser's
        # saved result or another editor opened from the same result.
        lease = _material_package_lease(self.package_path)
        return {
            "material_preview_model": self.preview_model,
            "material_package_path": self.package_path,
            "material_package_lease": lease,
            "material_context_verified_for_rust": True,
            "material_source_identity": self.source_identity,
        }


def _material_package_lease(package_path):
    from cdmw.services.preview_rendering_service import acquire_dotnet_preview_package_cache_lease_for_path

    lease = acquire_dotnet_preview_package_cache_lease_for_path(Path(package_path)) if package_path else None
    if package_path and lease is None:
        raise ValueError("The edited mesh's texture package is unavailable. Reopen its source to reload textures.")
    return lease


def capture_mesh_archive_material_context(entry, preview_model, package_path=""):
    """Keep verified source bindings without retaining geometry or decoded images."""
    from cdmw.services.mesh_rust_authoring import _snapshot_rust_preview_model
    from cdmw.services.mesh_dotnet_material_state import count_dotnet_own_material_bindings
    from cdmw.core.temp_cache import acquire_app_temp_cache_lease

    model = _snapshot_rust_preview_model(preview_model)
    if model is None or count_dotnet_own_material_bindings(model) <= 0:
        return None
    if model.path.replace("\\", "/").strip("/").casefold() != entry.identity.normalized_path:
        raise ValueError("The edited mesh's materials belong to a different source.")
    package = str(package_path or "")
    package_lease = _material_package_lease(package)
    # Legacy resolution and Refit sources can also refer to decoded images
    # outside a renderer package. Pin their cache units without reading images.
    pins = tuple(acquire_app_temp_cache_lease(path)
                 for path in dict.fromkeys(_material_resource_paths(model)))
    return MeshArchiveMaterialContext(entry.identity, model, package, package_lease, pins)


def _material_resource_paths(value, name=""):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _material_resource_paths(item, str(key))
    elif is_dataclass(value):
        for attribute in fields(value):
            yield from _material_resource_paths(getattr(value, attribute.name), attribute.name)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _material_resource_paths(item, name)
    elif isinstance(value, str) and value and (
        name in {"texture", "source_dds_path"} or "texture" in name and name.endswith("_path")
    ) and Path(value).is_absolute():
        yield value


@dataclass(frozen=True, slots=True)
class MeshArchiveResult:
    root: Path
    session_id: str
    mesh_revision: int
    material_generation: int
    assets: tuple[ArchiveEntry, ...]
    entries: tuple[ArchiveEntry, ...]
    material_contexts: tuple[MeshArchiveMaterialContext, ...] = ()


def prepare_mesh_archive_result(service, snapshot, entry, dependency_sources, output_root, *,
                                stop_event=None, material_contexts=()):
    """Rebuild exact assets and retain prepared dependencies without touching PAMT/PAZ.

    Legacy unprepared dependencies retain their original read-only archive locations.
    Prepared dependencies are copied so preview-cache eviction cannot break the result.
    """
    if snapshot.hair_state is not None or snapshot.texture_resources or snapshot.material_generation:
        raise ValueError("Finish texture, material or hairstyle authoring through Build Mod before adding an archive result.")
    from cdmw.services.mesh_archive_refit import archive_refit_body_assets, archive_refit_snapshots

    components = (archive_refit_snapshots(snapshot) if snapshot.archive_refit_context is not None
                  else ((entry, snapshot),))
    body = {asset.entry.identity for asset in archive_refit_body_assets(
        snapshot.archive_refit_context, service.cached_morph_state(snapshot.session_id))
    } if snapshot.archive_refit_context is not None else set()
    if components[0][0].identity != entry.identity:
        raise ValueError("The edited result belongs to a different archive source.")
    sources = dict(dependency_sources)
    if any(asset.identity not in sources for asset, _component in components):
        raise ValueError("Reopen every Refit source from Archive Browser to retain its dependencies.")
    entries = {}
    for source_entries in sources.values():
        for candidate in source_entries:
            previous = entries.get(candidate.identity)
            if previous is not None and previous.prepared_sha256 != candidate.prepared_sha256:
                raise ValueError("Archive sources contain conflicting versions of the same dependency.")
            entries[candidate.identity] = replace(candidate)
            if len(entries) > MAX_RESULT_ENTRIES:
                raise ValueError("The edited result exceeds the 8,192-entry dependency limit.")
    outputs = {}
    changed_materials = False
    added = {identity for identity, candidate in entries.items() if candidate.prepared_note == ADDED_RESULT_NOTE}
    for asset, component in components:
        raise_if_cancelled(stop_event)
        if asset.identity not in entries:
            raise ValueError("The source dependency context does not contain its mesh.")
        source_digest = entries[asset.identity].prepared_sha256
        if source_digest and source_digest.casefold() != hashlib.sha256(component.original_data).hexdigest():
            raise ValueError("The dependency context belongs to a different version of the mesh.")
        rebuilt, _report = service.rebuild_result_from_snapshot(component)
        outputs[asset.identity] = (asset, rebuilt.data)
        for companion in getattr(rebuilt, "companion_files", ()):
            from cdmw.services.mesh_replacement_import import archive_entry
            candidate = archive_entry(companion)
            if candidate is None:
                candidate = next((item for item in entries.values()
                    if item.path.replace("\\", "/").casefold() == companion.path.replace("\\", "/").casefold()
                    and item.pamt_path == asset.pamt_path), None)
            if candidate is None:
                candidate = replace(asset, path=companion.path, offset=0, comp_size=0, orig_size=len(companion.data))
                added.add(candidate.identity)
            if companion.path.casefold().endswith((".pac_xml", ".pami")):
                original = entries.get(candidate.identity)
                if original is None or read_archive_entry_data(original, stop_event=stop_event)[0] != companion.data:
                    changed_materials = True
            previous = outputs.get(candidate.identity)
            if previous is not None and previous[1] != companion.data:
                raise ValueError("Edited assets contain conflicting companion files.")
            outputs[candidate.identity] = (candidate, companion.data)
    entries.update({identity: candidate for identity, (candidate, _data) in outputs.items()})
    if len(entries) > MAX_RESULT_ENTRIES:
        raise ValueError("The edited result exceeds the 8,192-entry dependency limit.")
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    final = root / uuid4().hex
    total = 0
    prepared = []
    with tempfile.TemporaryDirectory(prefix=".preparing-", dir=root) as temporary:
        staging = Path(temporary) / "result"
        staging.mkdir()
        for index, (identity, candidate) in enumerate(entries.items()):
            raise_if_cancelled(stop_event)
            output = outputs.get(identity)
            if output is None and candidate.prepared_path is None:
                prepared.append(candidate)
                continue
            size = (len(output[1]) if output is not None else Path(candidate.prepared_path).stat().st_size)
            if size > MAX_RESULT_BYTES - total:
                raise ValueError("The edited result exceeds the 1 GiB prepared-file limit.")
            data = output[1] if output is not None else read_archive_entry_data(candidate, stop_event=stop_event)[0]
            total += len(data)
            if total > MAX_RESULT_BYTES:
                raise ValueError("The edited result exceeds the 1 GiB prepared-file limit.")
            basename = Path(candidate.path.replace("\\", "/")).name
            name = f"{index:05d}-{basename}"
            (staging / name).write_bytes(data)
            prepared.append(replace(candidate, prepared_path=final / name,
                prepared_sha256=hashlib.sha256(data).hexdigest(), prepared_size=len(data),
                content_analysis_json_path=None, content_analysis_text_path=None, content_analysis_version="",
                prepared_note=(ADDED_RESULT_NOTE if identity in added else BODY_RESULT_NOTE if identity in body
                               else EDITED_RESULT_NOTE) if output is not None
                else (candidate.prepared_note if candidate.prepared_note in RESULT_NOTES
                      else "Mesh Editor source dependency")))
        session = service._session(snapshot.session_id)
        with session.export_lock:
            raise_if_cancelled(stop_event)
            if (session.closed or session.revision != snapshot.mesh_revision
                    or session.material_generation != snapshot.material_generation):
                raise RuntimeError("The mesh changed while preparing the archive result; validate it again.")
            atomic_publish_paths(((staging, final),), replace_existing=False)
    by_identity = {candidate.identity: candidate for candidate in prepared}
    return MeshArchiveResult(final, snapshot.session_id, snapshot.mesh_revision, snapshot.material_generation,
        tuple(by_identity[asset.identity] for asset, _component in components), tuple(prepared),
        tuple(context for context in material_contexts
              if not changed_materials and context.source_identity in by_identity))
