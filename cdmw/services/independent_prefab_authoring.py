"""Reviewed standalone prefab authoring through the existing package writer."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.mod_package import IndependentModPackage
from cdmw.services.independent_item_package import (
    stock_snapshot,
    virtual_path,
    write_package,
)
from cdmw.services.independent_prefab_package import from_prefab_replacements


@dataclass(frozen=True)
class PrefabPackageReview:
    package: IndependentModPackage
    source_revision: object
    game_root: Path
    target_path: str
    lines: tuple[str, ...]

    def validate(self, stop_event=None):
        raise_if_cancelled(stop_event)
        self.source_revision.validate(stop_event)


def prepare_prefab_package(root, target_path, replacement, *, edited_from=None, title='Prefab edit', release='1',
                           identity=None, service=None, read_entry=None, stop_event=None, on_log=None):
    """Pin the shipped prefab and the game catalogue the edit was checked against.

    `edited_from` is the copy the editor opened. The package replaces the game's
    own copy, so an edit made on another mod's version of the file is refused
    rather than silently carrying that mod's changes along.
    """
    root = Path(root).expanduser().resolve()
    target_path = virtual_path(str(target_path).replace('\\', '/').lower())
    snapshot = stock_snapshot(root, service=service, read_entry=read_entry, stop_event=stop_event, on_log=on_log)
    if edited_from is not None and snapshot.has_entry(target_path) and snapshot.payload(target_path) != bytes(edited_from):
        raise IndependentItemError(f'The prefab you edited differs from the game\'s own copy of {target_path}, '
                                   'probably because another mod changes it. Disable that mod and edit the prefab again.')
    package = from_prefab_replacements(snapshot, identity or uuid4().hex, {target_path: bytes(replacement)},
        title=str(title).strip() or 'Prefab edit', release=str(release).strip() or '1', stop_event=stop_event)
    row = package.manifest['modules'][0]['data']['replacements'][0]
    review = PrefabPackageReview(package, snapshot.provenance.capture(), root, target_path, (
        f'Target prefab: {target_path}',
        f'Package: {package.title}',
        f'Package UUID: {package.identity}',
        f'Original source SHA-256: {row["source_sha256"]}',
        f'Replacement SHA-256: {row["replacement"]}',
        'The edited prefab decodes as completely as the game copy, and every file it newly points at exists in this game.',
        'No item IDs, new files or registry entries are created.',
        'Add this package on the Mods page. Game behavior requires separate testing.',
    ))
    review.validate(stop_event)
    return review


def write_prefab_package(review, destination, *, stop_event=None, on_log=None):
    destination = Path(destination).expanduser().resolve()
    if destination.is_relative_to(review.game_root):
        raise IndependentItemError('Write portable prefab packages outside the game archive folder.')
    review.validate(stop_event)
    if on_log is not None:
        on_log('Writing the reviewed prefab package...')
    return write_package(review.package, destination, stop_event=stop_event, validate_source=review.validate)
