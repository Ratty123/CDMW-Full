"""Find the body a fitted garment was authored on, from the session's archive assets.

Fit to body uses the reference body when the garments came from a game PAC
whose skeleton has a nude body, and that body is not the driver itself. The
garment's skeleton comes from ``resolve_skeleton_for_model`` (a bone-palette tie
between humanoid skeletons is settled by the character's nude prefab), its rig folder
holds the nude body (the same choice as character preview), and the driver's
skeleton is resolved the same way. Archive reads go through the dependency
context retained with the loaded Refit assets, or through ``dependencies``
when the caller supplies one: the editor's archive sets are bounded per opened
PAC and hold no nude bodies, so it prepares a merged set with them first
(:class:`PreparedRefitReferenceArchive`). Every refusal comes back as a
reason so the caller can fit to the driver alone and say why. With a reference
it also returns the driver's skin weights for the garments
(:mod:`cdmw.services.mesh_refit_weights`), or why they keep their own.
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
import threading
import time
from typing import Callable, Sequence

from cdmw.modding.mesh_parser import parse_pac, resolve_pac_bone_palette
from cdmw.modding.mesh_refit_reference import RefitReferenceBody, retarget_reference_body
from cdmw.modding.skeleton_parser import parse_pab
from cdmw.services.mesh_refit_weights import RefitWeightTransfer, build_refit_weight_transfer


@dataclass(frozen=True)
class RefitReferenceLookup:
    reference: RefitReferenceBody | None
    reason: str = ""
    # With a reference: the body's skin weights for the garments, or why they keep their own.
    weights: RefitWeightTransfer | None = None
    weights_reason: str = ""


@dataclass(frozen=True)
class RefitReferenceArchive:
    """The archive files a Fit reads, or why they could not be prepared.

    ``dependencies`` None with no ``reason`` means the Refit assets' own
    dependency contexts already index the whole archive.
    """

    dependencies: object | None = None
    reason: str = ""


@dataclass
class PreparedRefitReferenceArchive:
    """Filled on the GUI thread; only the Fit worker waits for it."""

    done: threading.Event = field(default_factory=threading.Event)
    archive: RefitReferenceArchive = RefitReferenceArchive()

    def settle(self, dependencies: object | None = None, reason: str = "") -> None:
        if not self.done.is_set():
            self.archive = RefitReferenceArchive(dependencies, reason)
            self.done.set()

    def wait(
        self, check_cancelled: Callable[[], None] | None = None, *, timeout_seconds: float = 60.0,
    ) -> RefitReferenceArchive:
        # A lost archive reply must not hold the Fit; it then fits to the current body.
        deadline = time.monotonic() + timeout_seconds
        while not self.done.wait(0.05):
            if check_cancelled is not None:
                check_cancelled()
            if time.monotonic() >= deadline:
                return RefitReferenceArchive(reason="the archive worker did not list the authored bodies in time")
        return self.archive


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
    if entry is None and str(getattr(report, "confidence", "")).startswith("ambiguous"):
        entry = _authored_rig(asset, report, dependencies, read)
    if entry is None:
        detail = str(getattr(report, "reason", "") or "").strip()
        return f"no skeleton was found for {name}" + (f" ({detail})" if detail else "")
    skeleton = parse_pab(read(entry), entry.path)
    if skeleton.parser_mode != "fixed" or skeleton.parse_warning or not skeleton.bones:
        return f"the skeleton of {name} could not be read exactly"
    return _ResolvedSkeleton(_normalized(entry.path), skeleton)


def character_prefab_folders(model_path: str) -> tuple[str, str]:
    """The prefab folders of the character a model belongs to and of its family.

    ``character/model/2_mon/<family>/<character>/...`` pairs with
    ``character/prefab/2_mon/<family>/<character>`` and ``.../<family>``;
    both are "" for a path too short to name them.
    """
    parts = PurePosixPath(_normalized(model_path)).parts
    if len(parts) < 6 or parts[:2] != ("character", "model"):
        return "", ""
    return "/".join(("character", "prefab", *parts[2:5])), "/".join(("character", "prefab", *parts[2:4]))


def _named_skeletons(folder, tied, dependencies, read) -> str:
    """The tied skeleton most nude prefabs under ``folder`` name, or "" without one clear answer."""
    from cdmw.core.skeleton_resolver import (
        _descriptor_reference_paths,
        _prefabdata_xml_refs,
    )

    named: Counter[str] = Counter()
    for path in dependencies.entries_by_normalized_path:
        name = PurePosixPath(_normalized(path)).name
        if not _normalized(path).startswith(folder + "/") or "_nude_" not in name or not name.endswith(".prefabdata_xml"):
            continue
        text = read(dependencies.entry_for_path(path)).decode("utf-8", "ignore")
        found = set()
        for attribute, value in _prefabdata_xml_refs(text):
            if attribute.strip().lower() == "skeletonname":
                found.update(_normalized(item) for item in _descriptor_reference_paths(attribute, value))
        named.update(found & tied)
    ranked = named.most_common(2)
    return "" if not ranked or (len(ranked) == 2 and ranked[0][1] == ranked[1][1]) else ranked[0][0]


def _authored_rig(asset, report, dependencies, read):
    """Of the skeletons that tie on the bone palette, the one the garment's character is built on.

    Humanoid characters share bone names, so a boss outfit's palette matches the
    player rigs and its family's boss skeletons equally (the resolver refuses).
    The character's nude prefab names the skeleton the game builds it on; every
    humanoid boss outfit checked names ``phm_01.pab``, which also fitted their
    hand-made female versions best. Characters without one (a quarter of the
    humanoid family) take a tied player rig their path names (``cd_m0001_02_phw``),
    else the skeleton most of the family's nude prefabs name. Nearest-body guesses
    picked the bulkier PTM rig and fitted worse. Without one clear answer the tie
    stays refused.
    """
    top = max((candidate.palette_hits for candidate in report.candidates), default=0)
    tied = {_normalized(candidate.path) for candidate in report.candidates if top > 0 and candidate.palette_hits == top}
    character, family = character_prefab_folders(asset.entry.path)
    if not tied or not character:
        return None
    chosen = _named_skeletons(character, tied, dependencies, read)
    if not chosen:
        tokens = set(_normalized(asset.entry.path).replace("/", "_").split("_"))
        player = [path for path in tied if path.startswith("character/model/1_pc/")
                  and PurePosixPath(path).parent.name.split("_", 1)[-1] in tokens]
        chosen = player[0] if len(player) == 1 else _named_skeletons(family, tied, dependencies, read)
    return dependencies.entry_for_path(chosen) if chosen else None


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
    dependencies: object | None = None,
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
    if dependencies is None:
        dependencies = _dependencies(context)
    if dependencies is None:
        return RefitReferenceLookup(None, "the game archive index is not available")
    # A refusal from a smaller archive set must not outlive it.
    key = (context.context_id, id(dependencies), tuple(_normalized(asset.entry.path) for asset in garments),
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
    nude = parse_pac(data, body_path).submeshes
    try:
        reference = retarget_reference_body(
            nude, palette, source.skeleton, target.skeleton, label=body_path,
            source_appearance=_appearance(garments[0], source.skeleton),
            target_appearance=_appearance(driver, target.skeleton),
        )
    except ValueError as exc:
        return RefitReferenceLookup(None, f"{body_path}: {exc}")
    weights, weights_reason = build_refit_weight_transfer(
        target.skeleton, source.skeleton, driver, garments, read, reference=(nude, palette))
    return RefitReferenceLookup(reference, weights=weights, weights_reason=weights_reason)


def clear_refit_reference_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = [
    "PreparedRefitReferenceArchive", "RefitReferenceArchive", "RefitReferenceLookup",
    "clear_refit_reference_cache", "find_refit_reference_body",
]
