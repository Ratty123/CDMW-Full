"""Find the body a fitted garment was authored on, from the session's archive assets.

Fit to body uses the reference body when the garments came from a game PAC
whose skeleton has a nude body, and that body is not the driver itself. The
garment's skeleton comes from ``resolve_skeleton_for_model``, its rig folder
holds the nude body (the same choice as character preview), and the driver's
skeleton is resolved the same way. Archive reads go through the dependency
context retained with the loaded Refit assets. Every refusal comes back as a
reason so the caller can fit to the driver alone and say why.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import PurePosixPath
import threading
from typing import Callable, Sequence

from cdmw.modding.mesh_parser import parse_pac, resolve_pac_bone_palette
from cdmw.modding.mesh_refit_reference import RefitReferenceBody, retarget_reference_body
from cdmw.modding.skeleton_parser import parse_pab


@dataclass(frozen=True)
class RefitReferenceLookup:
    reference: RefitReferenceBody | None
    reason: str = ""


@dataclass(frozen=True)
class _ResolvedSkeleton:
    path: str
    skeleton: object


_CACHE_LIMIT = 4
_CACHE: OrderedDict[tuple, RefitReferenceLookup] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _normalized(path: object) -> str:
    return str(path or "").replace("\\", "/").strip("/").casefold()


def _assets_for(context, indices: Sequence[int]) -> tuple[object, ...]:
    wanted = set(indices)
    return tuple(asset for asset in context.assets if wanted.intersection(asset.part_indices))


def _dependencies(context):
    for asset in context.assets:
        lease = getattr(asset, "preview_lease", None)
        dependencies = getattr(lease, "archive_dependencies", None)
        if dependencies is not None:
            return dependencies
    return None


def _reader(read_entry: Callable[[object], bytes] | None) -> Callable[[object], bytes]:
    if read_entry is None:
        from cdmw.services.archive_read_service import read_archive_entry_data

        def read_entry(entry):
            return read_archive_entry_data(entry)[0]
    payloads: dict[tuple, bytes] = {}

    def read(entry) -> bytes:
        key = (str(entry.path), str(getattr(entry, "paz_file", "")), int(getattr(entry, "offset", 0)))
        if key not in payloads:
            payloads[key] = read_entry(entry)
        return payloads[key]
    return read


def _skeleton(asset, dependencies, read) -> _ResolvedSkeleton | str:
    from cdmw.core.skeleton_resolver import resolve_skeleton_for_model

    name = PurePosixPath(_normalized(asset.entry.path)).name
    entry, report = resolve_skeleton_for_model(
        asset.entry,
        archive_entries_by_normalized_path=dependencies.entries_by_normalized_path,
        archive_entries_by_basename=dependencies.entries_by_basename,
        pac_data=asset.source.original_data,
        read_entry_data=read,
    )
    if entry is None:
        detail = str(getattr(report, "reason", "") or "").strip()
        return f"no skeleton was found for {name}" + (f" ({detail})" if detail else "")
    skeleton = parse_pab(read(entry), entry.path)
    if skeleton.parser_mode != "fixed" or skeleton.parse_warning or not skeleton.bones:
        return f"the skeleton of {name} could not be read exactly"
    return _ResolvedSkeleton(_normalized(entry.path), skeleton)


def _nude_body_path(skeleton_path: str, dependencies) -> str:
    from cdmw.services.effect_character_reference import _body_mesh_paths

    rig_folder = PurePosixPath(skeleton_path).parent
    prefix = str(rig_folder) + "/nude/"
    paths = _body_mesh_paths(
        (path for path in dependencies.entries_by_normalized_path if _normalized(path).startswith(prefix)),
        {}, rig_model=rig_folder.name,
    )
    return next((path for path in paths if "/nude/" in path), "")


def _appearance(asset, skeleton) -> tuple[tuple[float, ...], ...] | None:
    appearance = getattr(asset, "neutral_appearance", None)
    return None if appearance is None else tuple(appearance.skin_matrices)


def _appearance_matches(asset, skeleton) -> bool:
    appearance = getattr(asset, "neutral_appearance", None)
    return appearance is None or len(appearance.skin_matrices) == len(skeleton.bones)


def find_refit_reference_body(
    context,
    garment_indices: Sequence[int],
    driver_indices: Sequence[int],
    *,
    read_entry: Callable[[object], bytes] | None = None,
) -> RefitReferenceLookup:
    """The retargeted body the bound garments were authored on, or why there is none."""
    from cdmw.services.mesh_archive_refit import ArchiveRefitContext

    if not isinstance(context, ArchiveRefitContext):
        return RefitReferenceLookup(None, "the garments were not loaded from the game archive")
    garments = _assets_for(context, garment_indices)
    drivers = _assets_for(context, driver_indices)
    if not garments or len(drivers) != 1:
        return RefitReferenceLookup(None, "the body and garments must each come from loaded game PACs")
    if drivers[0] in garments:
        return RefitReferenceLookup(None, "the body and garments come from the same PAC")
    dependencies = _dependencies(context)
    if dependencies is None:
        return RefitReferenceLookup(None, "the game archive index is not available")
    key = (context.context_id, tuple(_normalized(asset.entry.path) for asset in garments),
           _normalized(drivers[0].entry.path), tuple(garment_indices), tuple(driver_indices))
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    lookup = _find(garments, drivers[0], dependencies, _reader(read_entry))
    with _CACHE_LOCK:
        _CACHE[key] = lookup
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
    return lookup


def _find(garments, driver, dependencies, read) -> RefitReferenceLookup:
    sources = [_skeleton(asset, dependencies, read) for asset in garments]
    failure = next((item for item in sources if isinstance(item, str)), None)
    if failure:
        return RefitReferenceLookup(None, failure)
    if len({item.path for item in sources}) != 1:
        return RefitReferenceLookup(None, "the garments use different skeletons")
    appearances = {None if getattr(asset, "neutral_appearance", None) is None
                   else tuple(map(tuple, asset.neutral_appearance.skin_matrices)) for asset in garments}
    if len(appearances) != 1:
        return RefitReferenceLookup(None, "the garments are shown in different character appearances")
    source = sources[0]
    target = _skeleton(driver, dependencies, read)
    if isinstance(target, str):
        return RefitReferenceLookup(None, target)
    body_path = _nude_body_path(source.path, dependencies)
    if not body_path:
        return RefitReferenceLookup(None, f"no nude body was found for {source.path}")
    if body_path == _normalized(driver.entry.path) and source.path == target.path:
        return RefitReferenceLookup(None, "the garments were authored on this body")
    entry = dependencies.entry_for_path(body_path)
    if entry is None:
        return RefitReferenceLookup(None, f"{body_path} is not in the loaded game archive")
    if not _appearance_matches(garments[0], source.skeleton) or not _appearance_matches(driver, target.skeleton):
        return RefitReferenceLookup(None, "a character appearance does not match its skeleton")
    data = read(entry)
    palette = resolve_pac_bone_palette(data, source.skeleton)
    if not palette:
        return RefitReferenceLookup(None, f"the bones of {body_path} do not match {source.path}")
    try:
        reference = retarget_reference_body(
            parse_pac(data, body_path).submeshes, palette, source.skeleton, target.skeleton, label=body_path,
            source_appearance=_appearance(garments[0], source.skeleton),
            target_appearance=_appearance(driver, target.skeleton),
        )
    except ValueError as exc:
        return RefitReferenceLookup(None, f"{body_path}: {exc}")
    return RefitReferenceLookup(reference)


def clear_refit_reference_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = ["RefitReferenceLookup", "clear_refit_reference_cache", "find_refit_reference_body"]
