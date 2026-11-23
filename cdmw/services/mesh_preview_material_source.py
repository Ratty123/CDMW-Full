"""Keep a native layer graph only while its source material bindings are unchanged."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path, PurePosixPath, PureWindowsPath

_LOGGER = logging.getLogger(__name__)


def _canonicalize_signature_numbers(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return 0.0 if value == 0 else float(value)
    if isinstance(value, Mapping):
        return {str(key): _canonicalize_signature_numbers(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize_signature_numbers(item) for item in value]
    return value


def _binding_signature_values(part, *, stat_files: bool = True):
    from cdmw.services.mesh_dotnet_material_bindings import _DOTNET_PREVIEW_MATERIAL_ATTRS

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
    if not stat_files:
        return values
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
    return values


def _binding_signature(part):
    from cdmw.services.mesh_rust_authoring import _canonical_json_bytes, _json_safe

    return hashlib.sha256(
        _canonical_json_bytes(_canonicalize_signature_numbers(_json_safe(_binding_signature_values(part))))
    ).hexdigest()


def _legacy_binding_signature(part):
    from cdmw.services.mesh_rust_authoring import _canonical_json_bytes, _json_safe

    return hashlib.sha256(_canonical_json_bytes(_json_safe(_binding_signature_values(part)))).hexdigest()


def bind_preview_core_material_source(part, package, batch, conservation):
    overrides = dict(getattr(part, "preview_native_material_overrides", {}) or {})
    overrides["preview_core_material_source"] = {
        "package": str(package), "batch": dict(batch), "conservation": dict(conservation),
        "binding_signature": _binding_signature(part),
        "binding_signature_version": 2,
    }
    part.preview_native_material_overrides = overrides


def _parts(mesh):
    levels = [list(getattr(mesh, "submeshes", ()) or ())]
    levels.extend(list(level or ()) for level in (getattr(mesh, "lod_levels", ()) or ()))
    seen, parts = set(), []
    for level in levels:
        for part in level:
            if id(part) not in seen:
                seen.add(id(part))
                parts.append(part)
    return parts


def set_aside_preview_core_sources(mesh):
    """Take each part's bound Preview Core material source out of its overrides.

    A copy of the mesh through the native snapshot encodes every extra attribute
    to JSON in Python; these sources were most of that work. Copies that do not
    need them (an immutable base, a clone that gets them back) set them aside
    first (P4 V4). Returns what ``restore_preview_core_sources`` puts back.
    """

    set_aside = []
    for part in _parts(mesh):
        overrides = getattr(part, "preview_native_material_overrides", None)
        if isinstance(overrides, dict) and "preview_core_material_source" in overrides:
            kept = dict(overrides)
            source = kept.pop("preview_core_material_source")
            part.preview_native_material_overrides = kept
            set_aside.append((part, source))
    return set_aside


def restore_preview_core_sources(set_aside, *, onto=None):
    """Put set-aside sources back; ``onto`` maps an original part to its copy as well."""

    for part, source in set_aside:
        targets = [part]
        if onto is not None and id(part) in onto:
            targets.append(onto[id(part)])
        for target in targets:
            overrides = dict(getattr(target, "preview_native_material_overrides", {}) or {})
            overrides["preview_core_material_source"] = source
            target.preview_native_material_overrides = overrides


def unedited_preview_core_material_source(part):
    source = (getattr(part, "preview_native_material_overrides", {}) or {}).get("preview_core_material_source")
    if (
        not isinstance(source, dict)
        or source.get("batch", {}).get("material_name") != getattr(part, "material", "")
    ):
        return None
    stored_signature = source.get("binding_signature")
    if source.get("binding_signature_version") == 2:
        return source if stored_signature == _binding_signature(part) else None
    if stored_signature in {_binding_signature(part), _legacy_binding_signature(part)}:
        return source
    return None


def _without_cache_locations(value):
    """``value`` with every absolute path reduced to its file name.

    Prepared textures are named by their content, so a rebuilt archive index or
    preview cache keeps the names and changes only the folders they lie in.
    """

    if isinstance(value, str):
        if PureWindowsPath(value).is_absolute() or value.startswith("/"):
            return PureWindowsPath(value).name
        return value
    if isinstance(value, Mapping):
        return {str(key): _without_cache_locations(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_without_cache_locations(item) for item in value]
    return value


def _relocatable_binding_values(part):
    """A part's material inputs, wherever its cache files lie now."""
    from cdmw.services.mesh_rust_authoring import _json_safe

    values = _binding_signature_values(part, stat_files=False)
    return _canonicalize_signature_numbers(_without_cache_locations(_json_safe(values)))


def adopt_current_material_bindings(restored_mesh, current_mesh) -> int:
    """Give restored parts this session's material bindings where only cache folders differ.

    A saved editor state (unfinished edits picked up again, an Undo step from an earlier
    session) holds each part's material bindings as they were when it was saved: paths
    into the archive index and the preview cache. Those are rebuilt and pruned. The
    stored native layer source then no longer counts as unedited, and the part drew its
    raw textures without dyes and detail layers (Fredric, 2026-11-22).

    ``current_mesh`` is the session's mesh just before the state is installed: its parts
    were bound when this session opened. A restored part takes the bindings of the one
    part with its name and material, when that part's source is valid and both describe
    the same material once file locations are set aside. A part whose material was
    edited differs in more than locations and keeps what it stored. Returns how many
    parts were given bindings.
    """
    import copy

    from cdmw.services.mesh_dotnet_material_bindings import _DOTNET_PREVIEW_MATERIAL_ATTRS

    def identity(part):
        return str(getattr(part, "name", "") or ""), str(getattr(part, "material", "") or "")

    def levels(mesh):
        return [list(getattr(mesh, "submeshes", ()) or ()),
                *(list(level or ()) for level in (getattr(mesh, "lod_levels", ()) or ()))]

    adopted = 0
    current_levels = levels(current_mesh)
    done: set[int] = set()
    for level_index, level in enumerate(levels(restored_mesh)):
        if level_index >= len(current_levels):
            break
        donors: dict[tuple[str, str], list] = {}
        for part in current_levels[level_index]:
            donors.setdefault(identity(part), []).append(part)
        for part in level:
            if id(part) in done:
                continue  # LOD 0 is listed twice when the levels hold it too
            done.add(id(part))
            if unedited_preview_core_material_source(part) is not None:
                continue
            candidates = donors.get(identity(part), ())
            if len(candidates) != 1 or candidates[0] is part:
                continue
            donor = candidates[0]
            source = unedited_preview_core_material_source(donor)
            if source is None or _relocatable_binding_values(part) != _relocatable_binding_values(donor):
                continue
            # Exactly what the binding signature covers: a part's placement role and
            # its own vertex statistics are not its material.
            for name in (*_DOTNET_PREVIEW_MATERIAL_ATTRS, "texture"):
                if (name in {"preview_role", "preview_source_asset_path", "preview_native_material_overrides"}
                        or name.startswith("preview_vertex_") or not hasattr(donor, name)):
                    continue
                value = getattr(donor, name)
                try:
                    value = copy.deepcopy(value)
                except (TypeError, RuntimeError):
                    pass
                setattr(part, name, value)
            # The source itself is read-only and shared, as on every copy of a part.
            overrides = {key: copy.deepcopy(value) for key, value in
                         (getattr(donor, "preview_native_material_overrides", {}) or {}).items()
                         if key != "preview_core_material_source"}
            overrides["preview_core_material_source"] = source
            part.preview_native_material_overrides = overrides
            adopted += 1
    return adopted


def bind_authoring_preview_core_materials(mesh, package_path, *, manifest=None):
    """Match original source file, section and material, never a name-only import."""
    from cdmw.services.mesh_rust_authoring import _mesh_lods
    from cdmw.services.mesh_rust_preview_package import (
        _validated_preview_core_source,
        preview_core_missing_material_source,
    )

    if not package_path:
        return
    package = Path(package_path)
    if package.is_file():
        package = package.parent
    if manifest is None:
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
    if preview_core_missing_material_source(package, manifest):
        # The cached package outlived the texture files it points at (the archive index was
        # rebuilt since): the editor prepares its own materials, as when Browse has no package.
        return
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


_DEFAULT_BIND_AUTHORING_PREVIEW_CORE_MATERIALS = bind_authoring_preview_core_materials


def _normalize_preview_model_path(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/").casefold()


def _safe_batch_int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


@dataclass(frozen=True, slots=True)
class PreviewCoreSetPackage:
    """Validated, leased Preview Core set package shared read-only across set pieces."""

    package: Path
    manifest: Mapping[str, object]
    lease: object
    extra_texture_roots: tuple[Path, ...]
    batches_by_path: Mapping[str, tuple[Mapping[str, object], ...]]
    batches_by_basename: Mapping[str, tuple[str, ...]]


def _preview_core_extra_texture_roots(package: Path, cache_root: Path | str | None = None) -> tuple[Path, ...]:
    candidates: list[Path] = []
    if package.name == "package" and package.parent.parent.name == "packages":
        candidates.append(package.parent.parent.parent / "dds")
    if cache_root is not None:
        candidates.append(Path(cache_root) / "dds")
    seen: set[str] = set()
    roots: list[Path] = []
    for candidate in candidates:
        key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        roots.append(candidate)
    return tuple(roots)


def load_preview_core_set_package(
    package_path: Path | str | None,
    *,
    cache_root: Path | str | None = None,
    stop_event: object = None,
) -> PreviewCoreSetPackage | None:
    """Lease and validate Browse's conserved Preview Core set package once for all pieces.

    Caller owns ``result.lease`` and must release it once every piece has either
    acquired its own piece lease or fallen back.
    """
    from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled
    from cdmw.rendering.native_preview_package_cache import acquire_native_preview_package_cache_lease_for_path
    from cdmw.services.mesh_rust_preview_cache import native_material_package_for_rust_preview
    from cdmw.services.mesh_rust_preview_package import (
        _validated_preview_core_source,
        preview_core_missing_material_source,
    )

    raise_if_cancelled(stop_event, "Item set loading cancelled")
    if not package_path:
        return None
    try:
        package = Path(package_path)
        if package.is_file():
            package = package.parent
        package = native_material_package_for_rust_preview(package) or package
        package = package.resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    lease = acquire_native_preview_package_cache_lease_for_path(package)
    if lease is None:
        return None
    try:
        raise_if_cancelled(stop_event, "Item set loading cancelled")
        manifest_path = package / "manifest.json"
        if not manifest_path.is_file() or manifest_path.stat().st_size > 16 * 1024 * 1024:
            lease.release()
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if not isinstance(manifest, Mapping) or _safe_batch_int(manifest.get("schema_version"), 0) < 8:
            lease.release()
            return None
        _validated_preview_core_source(package, manifest)
        if preview_core_missing_material_source(package, manifest):
            # Stale: its textures belonged to an archive index that has been replaced.
            lease.release()
            return None
        raise_if_cancelled(stop_event, "Item set loading cancelled")
        source_path = _normalize_preview_model_path(manifest.get("source_path"))
        by_path: dict[str, list[Mapping[str, object]]] = {}
        by_basename: dict[str, list[str]] = {}
        for batch in manifest.get("batches", ()):
            if not isinstance(batch, Mapping):
                continue
            identity = batch.get("editor_identity")
            if not isinstance(identity, Mapping):
                continue
            batch_path = _normalize_preview_model_path(
                identity.get("source_model_path") or identity.get("source_asset_path") or ""
            )
            if (
                not batch_path
                and not bool(identity.get("prefab_component", False))
                and not bool(identity.get("context_component", False))
                and _safe_batch_int(identity.get("source_component_index", 0), 0) == 0
            ):
                batch_path = source_path
            if not batch_path:
                continue
            if batch_path not in by_path:
                basename = PurePosixPath(batch_path).name
                if basename:
                    by_basename.setdefault(basename, []).append(batch_path)
            by_path.setdefault(batch_path, []).append(batch)
        if not by_path:
            lease.release()
            return None
        return PreviewCoreSetPackage(
            package=package,
            manifest=manifest,
            lease=lease,
            extra_texture_roots=_preview_core_extra_texture_roots(package, cache_root),
            batches_by_path={key: tuple(value) for key, value in by_path.items()},
            batches_by_basename={key: tuple(value) for key, value in by_basename.items()},
        )
    except RunCancelled:
        lease.release()
        raise
    except Exception:
        lease.release()
        return None


def bind_item_set_piece_from_preview_core_package(
    mesh: object,
    context: object,
    set_package: PreviewCoreSetPackage | None,
    stop_event: object,
) -> object | None:
    """Bind one item-set piece directly from Browse's already-built set package.

    Matches piece ``entry.path`` (or unambiguous basename) against each batch's
    ``editor_identity`` and local/source submesh index plus exact material name.
    Returns an ``ArchiveRefitPreviewLease`` holding a fresh lease on the package,
    or ``None`` when any submesh is missing or ambiguous so the caller falls back
    to ``prepare_item_set_material_source`` for this piece only.
    """
    from types import SimpleNamespace
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.rendering.native_preview_package_cache import acquire_native_preview_package_cache_lease_for_path
    from cdmw.services.mesh_archive_refit import ArchiveRefitPreviewLease
    from cdmw.services.mesh_dotnet_material_bindings import (
        _DOTNET_PREVIEW_MATERIAL_ATTRS,
        apply_dotnet_native_material_batch_binding,
    )
    from cdmw.services.mesh_rust_authoring import _mesh_lods, _rebase_rust_preview_texture_paths

    raise_if_cancelled(stop_event, "Item set loading cancelled")
    if set_package is None:
        return None
    entry = context.selected_entry
    entry_path = _normalize_preview_model_path(getattr(entry, "path", ""))
    mesh_path = _normalize_preview_model_path(getattr(mesh, "path", ""))
    if not entry_path or mesh_path != entry_path:
        return None
    piece_batches = set_package.batches_by_path.get(entry_path, ())
    if not piece_batches:
        basename = PurePosixPath(entry_path).name
        matching_paths = set_package.batches_by_basename.get(basename, ())
        if len(matching_paths) == 1:
            piece_batches = set_package.batches_by_path.get(matching_paths[0], ())
    if not piece_batches:
        return None
    by_component: dict[int, list[Mapping[str, object]]] = {}
    for batch in piece_batches:
        identity = batch.get("editor_identity")
        component_index = (
            _safe_batch_int(identity.get("source_component_index", 0), 0)
            if isinstance(identity, Mapping)
            else 0
        )
        by_component.setdefault(component_index, []).append(batch)
    if len(by_component) > 1:
        if 0 in by_component:
            piece_batches = tuple(by_component[0])
        else:
            return None
    batches_by_local: dict[int, list[Mapping[str, object]]] = {}
    for batch in piece_batches:
        identity = batch.get("editor_identity")
        if not isinstance(identity, Mapping):
            continue
        if "source_local_submesh_index" in identity:
            local_index = _safe_batch_int(identity.get("source_local_submesh_index"), -1)
        else:
            local_index = _safe_batch_int(identity.get("source_submesh_index"), -1)
        if local_index >= 0:
            batches_by_local.setdefault(local_index, []).append(batch)
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    if not submeshes:
        return None
    matched_pairs: list[tuple[object, Mapping[str, object]]] = []
    for index, part in enumerate(submeshes):
        original_index = getattr(part, "cdmw_mesh_edit_topology_source_submesh_index", index)
        rows = batches_by_local.get(original_index, ())
        if len(rows) != 1:
            return None
        batch = rows[0]
        if str(batch.get("material_name", "") or "") != str(getattr(part, "material", "") or ""):
            return None
        matched_pairs.append((part, batch))

    lease = acquire_native_preview_package_cache_lease_for_path(set_package.package)
    if lease is None:
        return None

    sentinel = object()
    saved_attrs: list[tuple[object, dict[str, object]]] = []

    def restore_parts() -> None:
        for target_part, previous in saved_attrs:
            for attr, value in previous.items():
                if value is sentinel:
                    if hasattr(target_part, attr):
                        try:
                            delattr(target_part, attr)
                        except AttributeError:
                            pass
                else:
                    setattr(target_part, attr, value)

    try:
        raise_if_cancelled(stop_event, "Item set loading cancelled")
        for part, batch in matched_pairs:
            saved_attrs.append((
                part,
                {attr: getattr(part, attr, sentinel) for attr in _DOTNET_PREVIEW_MATERIAL_ATTRS},
            ))
            if not apply_dotnet_native_material_batch_binding(part, batch):
                restore_parts()
                lease.release()
                return None
        # Browse's set package draws the archive worker's prepared files, which are
        # outside its lease. The piece is bound to the package's Preview Core
        # materials below, which carry those textures, as a single-file open is;
        # only a texture file that is gone refuses the piece.
        _rebased, unavailable_reason = _rebase_rust_preview_texture_paths(
            mesh,
            set_package.package,
            stop_event=stop_event,
            extra_texture_roots=set_package.extra_texture_roots,
            tolerate_external_files=True,
        )
        if unavailable_reason:
            restore_parts()
            lease.release()
            return None
        conservation = set_package.manifest["material_conservation"]
        for level in _mesh_lods(mesh):
            for index, part in enumerate(level):
                original_index = getattr(part, "cdmw_mesh_edit_topology_source_submesh_index", index)
                rows = batches_by_local.get(original_index, ())
                if len(rows) == 1 and str(rows[0].get("material_name", "") or "") == str(getattr(part, "material", "") or ""):
                    bind_preview_core_material_source(part, set_package.package, rows[0], conservation)
        raise_if_cancelled(stop_event, "Item set loading cancelled")
        return ArchiveRefitPreviewLease(SimpleNamespace(material_package_lease=lease), context)
    except BaseException:
        restore_parts()
        lease.release()
        raise


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
    from cdmw.services.mesh_rust_preview_package import (
        _validated_preview_core_source,
        preview_core_missing_material_source,
    )

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
    if preview_core_missing_material_source(package, manifest):
        return None
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


def _item_set_piece_package_root(entry, context) -> Path | None:
    """The game folder Browse gives Preview Core, found from the piece's own archive files.

    The native core reads the shader definitions from it. Without them a texture a
    material declares but the game lacks gets no technique default (Demenissian
    Council Robes' upper body declares a missing normal map), and the piece's graph
    is not conserved although Browse's own job resolves it.
    """
    from cdmw.domain.archives.filters import archive_entry_game_root
    from cdmw.services.archive_environment_service import looks_like_archive_package_root

    seen: set[str] = set()
    for candidate in (entry, *tuple(getattr(context, "entries", ()) or ())):
        pamt_path = getattr(candidate, "pamt_path", None)
        if not pamt_path:
            continue
        folder = str(Path(str(pamt_path)).parent)
        if folder in seen:
            continue
        seen.add(folder)
        try:
            root = archive_entry_game_root(candidate)
            if root.is_dir() and looks_like_archive_package_root(root):
                return root
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
    return None


def prepare_item_set_material_source(mesh, context, cache_root, stop_event, *, require_existing_inputs: bool = True):
    """Resolve one original PAC's graph on the existing set preparation worker.

    Returns None when Preview Core cannot give the piece a complete graph; the
    caller then prepares that piece's materials the bounded CPU way, so one
    incomplete piece never stops the whole set from opening.
    """
    from types import SimpleNamespace
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.models import ModelPreviewRenderSettings
    from cdmw.rendering.native_preview_core import run_native_preview_core_preview_job
    from cdmw.rendering.native_preview_package_cache import acquire_native_preview_package_cache_lease_for_path
    from cdmw.services.mesh_archive_refit import ArchiveRefitPreviewLease
    from cdmw.services.mesh_dotnet_material_bindings import apply_dotnet_native_material_batch_bindings
    from cdmw.services.mesh_rust_authoring import _rebase_rust_preview_texture_paths, _submesh_has_material_synthesis_inputs
    from cdmw.services.mesh_rust_preview_package import _validated_preview_core_source
    from cdmw.workers.archive_preview_native import (
        native_preview_core_timeout_seconds, native_preview_model_property_indices,
    )

    raise_if_cancelled(stop_event, "Item set loading cancelled")
    direct_native = bool(getattr(mesh, "_cdmw_item_set_direct_native_materials", False))
    if require_existing_inputs and not direct_native and not any(_submesh_has_material_synthesis_inputs(part) for part in mesh.submeshes):
        return None
    entry = context.selected_entry
    normalize = lambda value: str(value or "").replace("\\", "/").casefold()
    if normalize(mesh.path) != normalize(entry.path) or context.entry_matching(entry) is None:
        raise ValueError("Item set dependencies do not match the selected mesh")
    settings = ModelPreviewRenderSettings(use_textures_by_default=True)
    # The item's prefab picks the file's material variant, as Browse's preview
    # of the same context does; without it the core falls back to variant 0.
    dependencies = tuple(context.entries)
    result = run_native_preview_core_preview_job(
        entry, cache_root=Path(cache_root), render_settings=settings,
        dependency_entries=dependencies, dependency_entries_complete=bool(context.remote),
        model_property_indices=native_preview_model_property_indices(
            dependencies, stop_event, model_paths=(entry.path,)),
        package_root=_item_set_piece_package_root(entry, context),
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
        conservation = manifest.get("material_conservation")
        if not isinstance(conservation, Mapping) or conservation.get("conserved") is not True:
            # As with unsupported native inputs above: this piece keeps the bounded
            # CPU compositor instead of failing every other piece's open.
            findings = tuple(conservation.get("findings", ()) or ()) if isinstance(conservation, Mapping) else ()
            _LOGGER.warning("Item set piece %s has an incomplete Preview Core material graph (%s); "
                            "its materials are prepared without it.", entry.path,
                            findings[0] if findings else "no finding reported")
            lease.release()
            return None
        _validated_preview_core_source(package, manifest)
        raise_if_cancelled(stop_event, "Item set loading cancelled")
        apply_dotnet_native_material_batch_bindings(mesh, manifest["batches"])
        # Discard old CPU-preview paths outside this graph's declared resources.
        # The native DDS sources themselves were validated above.
        # The job's temporary package references DDS files in this set's own
        # native cache, which the package location alone does not reveal.
        _rebase_rust_preview_texture_paths(
            mesh, package, stop_event=stop_event, extra_texture_roots=(Path(cache_root) / "dds",))
        if bind_authoring_preview_core_materials is _DEFAULT_BIND_AUTHORING_PREVIEW_CORE_MATERIALS:
            bind_authoring_preview_core_materials(mesh, package, manifest=manifest)
        else:
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
