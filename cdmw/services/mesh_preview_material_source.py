"""Keep a native layer graph only while its source material bindings are unchanged."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _binding_signature(part):
    from cdmw.services.mesh_dotnet_material_bindings import _DOTNET_PREVIEW_MATERIAL_ATTRS
    from cdmw.services.mesh_rust_authoring import _canonical_json_bytes, _json_safe

    # Geometry edits and scene placement do not edit a material. All material
    # inputs, parameters, factors and direct texture assignments do.
    excluded = {"preview_role", "preview_source_asset_path", "preview_native_material_overrides"}
    values = {name: getattr(part, name, None) for name in _DOTNET_PREVIEW_MATERIAL_ATTRS
              if name not in excluded and not name.startswith("preview_vertex_")}
    values.update(material=getattr(part, "material", ""), texture=getattr(part, "texture", ""))
    overrides = getattr(part, "preview_native_material_overrides", {}) or {}
    ignored = {"preview_core_material_source"}
    if overrides.get("painted_texture_channels"):
        # Painted masks use renderer controls after composition. Their retained
        # graph must still be checked against every texture/parameter edit.
        ignored.update(("shader_controls", "translucency", "translucency_surface"))
    values["overrides"] = {key: value for key, value in overrides.items() if key not in ignored}
    # An editor may replace a file in place without changing its binding path.
    # Package resources are immutable; a changed source file must be baked again.
    paths = {str(value) for name, value in values.items() if "path" in name and value}
    for row in getattr(part, "preview_material_texture_inputs", ()) or ():
        for name in ("source_dds_path", "preview_texture_path", "source_texture_path"):
            value = row.get(name) if isinstance(row, dict) else getattr(row, name, None)
            if value:
                paths.add(str(value))
    files = {}
    for text in sorted(paths):
        path = Path(text)
        if path.is_absolute():
            try:
                stat = path.stat()
                files[text] = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                files[text] = None
    values["source_files"] = files
    return hashlib.sha256(_canonical_json_bytes(_json_safe(values))).hexdigest()


def bind_preview_core_material_source(part, package, batch, conservation):
    overrides = dict(getattr(part, "preview_native_material_overrides", {}) or {})
    overrides["preview_core_material_source"] = {
        "package": str(package), "batch": dict(batch), "conservation": dict(conservation),
        "binding_signature": _binding_signature(part),
    }
    part.preview_native_material_overrides = overrides


def unedited_preview_core_material_source(part):
    source = (getattr(part, "preview_native_material_overrides", {}) or {}).get("preview_core_material_source")
    if (isinstance(source, dict) and source.get("binding_signature") == _binding_signature(part)
            and source.get("batch", {}).get("material_name") == getattr(part, "material", "")):
        return source
    return None


def bind_authoring_preview_core_materials(mesh, package_path):
    """Match original source file, section and material, never a name-only import."""
    from cdmw.services.mesh_rust_authoring import _mesh_lods
    from cdmw.services.mesh_rust_preview_package import _validated_preview_core_source

    if not package_path:
        return
    package = Path(package_path)
    if package.is_file():
        package = package.parent
    path = package / "manifest.json"
    if not path.is_file():
        return
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Preview Core manifest exceeds the 16 MiB limit")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version", 0) < 8:
        return
    normalize = lambda value: str(value or "").replace("\\", "/").casefold()
    source_path = normalize(manifest.get("source_path"))
    if not source_path or source_path != normalize(getattr(mesh, "path", "")):
        return
    _validated_preview_core_source(package, manifest)
    batches = {}
    for batch in manifest["batches"]:
        identity = batch.get("editor_identity", {})
        if (identity.get("prefab_component") or identity.get("context_component")
                or normalize(identity.get("source_model_path", source_path)) != source_path):
            continue
        index = identity.get("source_submesh_index", -1)
        if index >= 0:
            batches.setdefault(index, []).append(batch)
    for level in _mesh_lods(mesh):
        for index, part in enumerate(level):
            original_index = getattr(part, "cdmw_mesh_edit_topology_source_submesh_index", index)
            rows = batches.get(original_index, ())
            if len(rows) == 1 and rows[0].get("material_name") == getattr(part, "material", ""):
                bind_preview_core_material_source(part, package, rows[0], manifest["material_conservation"])


def native_companion_reference_mesh(mesh, package_path, cancelled=lambda: False):
    """The editable PAC's prefab and context companions (eyes, teeth, a
    scabbard) as read-only parts, each bound to its own native material batch.

    They come from the same Preview Core package Browse Archives shows, so the
    Mesh Editor draws them with the same material layers. Returns None when the
    package has no companions or does not belong to this mesh.
    """
    from cdmw.modding.mesh_parser import ParsedMesh
    from cdmw.modding.mesh_totals import refresh_mesh_totals
    from cdmw.services.mesh_dotnet_reference_composite import append_dotnet_native_reference_composite
    from cdmw.services.mesh_rust_preview_package import _validated_preview_core_source

    if not package_path:
        return None
    package = Path(package_path)
    if package.is_file():
        package = package.parent
    path = package / "manifest.json"
    if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version", 0) < 8:
        return None
    normalize = lambda value: str(value or "").replace("\\", "/").casefold()
    if not normalize(manifest.get("source_path")) or normalize(manifest.get("source_path")) != normalize(getattr(mesh, "path", "")):
        return None
    _validated_preview_core_source(package, manifest)
    reference = ParsedMesh(path=str(getattr(mesh, "path", "")), format="pac",
                           bbox_min=getattr(mesh, "bbox_min", (0, 0, 0)), bbox_max=getattr(mesh, "bbox_max", (0, 0, 0)),
                           has_uvs=True)
    if not append_dotnet_native_reference_composite(reference, package, cancelled=cancelled):
        return None
    batches = {int(batch.get("index", -1)): batch for batch in manifest.get("batches", ()) if isinstance(batch, dict)}
    for part in reference.submeshes:
        batch = batches.get(int(getattr(part, "cdmw_mesh_edit_topology_source_submesh_index", -1)))
        if batch is not None and batch.get("material_name") == getattr(part, "material", ""):
            bind_preview_core_material_source(part, package, batch, manifest["material_conservation"])
    refresh_mesh_totals(reference)
    return reference


def prepare_item_set_material_source(mesh, context, cache_root, stop_event):
    """Resolve one original PAC's graph on the existing set preparation worker."""
    from types import SimpleNamespace
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.models import ModelPreviewRenderSettings
    from cdmw.rendering.native_preview_core import run_native_preview_core_preview_job
    from cdmw.rendering.native_preview_package_cache import acquire_native_preview_package_cache_lease_for_path
    from cdmw.services.mesh_archive_refit import ArchiveRefitPreviewLease
    from cdmw.services.mesh_dotnet_material_bindings import apply_dotnet_native_material_batch_bindings
    from cdmw.services.mesh_rust_authoring import _rebase_rust_preview_texture_paths, _submesh_has_material_synthesis_inputs
    from cdmw.services.mesh_rust_preview_package import _validated_preview_core_source
    from cdmw.workers.archive_preview_native import native_preview_core_timeout_seconds

    raise_if_cancelled(stop_event, "Item set loading cancelled")
    if not any(_submesh_has_material_synthesis_inputs(part) for part in mesh.submeshes):
        return None
    entry = context.selected_entry
    normalize = lambda value: str(value or "").replace("\\", "/").casefold()
    if normalize(mesh.path) != normalize(entry.path) or context.entry_matching(entry) is None:
        raise ValueError("Item set dependencies do not match the selected mesh")
    settings = ModelPreviewRenderSettings(use_textures_by_default=True)
    result = run_native_preview_core_preview_job(
        entry, cache_root=Path(cache_root), render_settings=settings,
        dependency_entries=tuple(context.entries), dependency_entries_complete=bool(context.remote),
        timeout_seconds=native_preview_core_timeout_seconds(settings), stop_event=stop_event,
    )
    raise_if_cancelled(stop_event, "Item set loading cancelled")
    if not result.succeeded:
        # Unsupported native inputs retain the existing bounded CPU compositor.
        return None
    package = Path(result.package_path)
    lease = acquire_native_preview_package_cache_lease_for_path(package)
    if lease is None:
        raise ValueError("The resolved Archive Browser texture package could not be leased.")
    try:
        path = package / "manifest.json"
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("Preview Core manifest exceeds the 16 MiB limit")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if normalize(manifest.get("source_path")) != normalize(entry.path):
            raise ValueError("Item set dependencies do not match the selected mesh")
        _validated_preview_core_source(package, manifest)
        raise_if_cancelled(stop_event, "Item set loading cancelled")
        apply_dotnet_native_material_batch_bindings(mesh, manifest["batches"])
        # Discard old CPU-preview paths outside this graph's declared resources.
        # The native DDS sources themselves were validated above.
        # The job's temporary package references DDS files in this set's own
        # native cache, which the package location alone does not reveal.
        _rebase_rust_preview_texture_paths(
            mesh, package, stop_event=stop_event, extra_texture_roots=(Path(cache_root) / "dds",))
        bind_authoring_preview_core_materials(mesh, package)
        raise_if_cancelled(stop_event, "Item set loading cancelled")
        return ArchiveRefitPreviewLease(SimpleNamespace(material_package_lease=lease), context)
    except BaseException:
        lease.release()
        raise


def preview_core_material_contract(mesh):
    from cdmw.services.mesh_rust_authoring import _mesh_lods
    from cdmw.services.mesh_rust_preview_package import (
        _PREVIEW_CORE_MATERIAL_GRAPH_VERSION, _PREVIEW_CORE_MATERIAL_SEMANTICS_VERSION,
    )
    reports = {}
    for level in _mesh_lods(mesh):
        for part in level:
            if source := unedited_preview_core_material_source(part):
                reports[source["package"]] = source["conservation"]
    return {
        "graph_version": _PREVIEW_CORE_MATERIAL_GRAPH_VERSION,
        "semantics_version": _PREVIEW_CORE_MATERIAL_SEMANTICS_VERSION,
        "conservation": {
            "conserved": all(report.get("conserved") is True for report in reports.values()),
            "declared_parameter_count": sum(report["declared_parameter_count"] for report in reports.values()),
            "transported_parameter_count": sum(report["transported_parameter_count"] for report in reports.values()),
        },
    }
