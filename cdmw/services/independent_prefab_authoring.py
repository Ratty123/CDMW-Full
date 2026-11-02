"""Reviewed prefab authoring through the existing package writer.

A prefab edit becomes either a standalone package or a new release of an
existing item package, so it can point an existing prefab at that item's mesh.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.mod_package import IndependentModPackage
from cdmw.services.independent_item_package import (
    package_bytes,
    read_package,
    stock_snapshot,
    virtual_path,
    write_package,
)
from cdmw.services.independent_prefab_package import (
    from_prefab_replacements,
    next_release,
    prefab_modules,
    with_prefab_replacements,
)


@dataclass(frozen=True)
class PrefabPackageUpdate:
    """The item package an edit is added to, pinned to the bytes that were read."""

    path: Path
    identity: str
    digest: str

    def validate(self, stop_event=None):
        current = read_package(self.path, stop_event=stop_event)
        if (current.identity, current.digest) != (self.identity, self.digest):
            raise IndependentItemError('The item package changed while the prefab edit was prepared. Add the edit again.')


@dataclass(frozen=True)
class PrefabPackageReview:
    package: IndependentModPackage
    source_revision: object
    game_root: Path
    target_path: str
    lines: tuple[str, ...]
    update: PrefabPackageUpdate | None = None

    def validate(self, stop_event=None):
        raise_if_cancelled(stop_event)
        self.source_revision.validate(stop_event)
        if self.update is not None:
            self.update.validate(stop_event)


def prepare_prefab_package(root, target_path, replacement, *, edited_from=None, title='Prefab edit', release='1',
                           identity=None, add_to=None, service=None, read_entry=None, stop_event=None, on_log=None):
    """Pin the shipped prefab and the game catalogue the edit was checked against.

    `edited_from` is the copy the editor opened. The package replaces the game's
    own copy, so an edit made on another mod's version of the file is refused
    rather than silently carrying that mod's changes along.

    `add_to` names an existing `.cditem`. The edit then becomes that package's
    next release, checked the way an install would check it, so a new mesh path
    may name a file the package's own item adds.
    """
    root = Path(root).expanduser().resolve()
    target_path = virtual_path(str(target_path).replace('\\', '/').lower())
    snapshot = stock_snapshot(root, service=service, read_entry=read_entry, stop_event=stop_event, on_log=on_log)
    if edited_from is not None and snapshot.has_entry(target_path) and snapshot.payload(target_path) != bytes(edited_from):
        raise IndependentItemError(f'The prefab you edited differs from the game\'s own copy of {target_path}, '
                                   'probably because another mod changes it. Disable that mod and edit the prefab again.')
    update = None
    replaces_earlier = False
    if add_to is not None:
        add_to = Path(add_to).expanduser().resolve()
        existing = read_package(add_to, stop_event=stop_event)
        update = PrefabPackageUpdate(add_to, existing.identity, existing.digest)
        # A package holds one version of each prefab, and the editor opened the
        # game's copy, so an earlier edit of this prefab is not in what was edited.
        replaces_earlier = any(row['path'] == target_path for module in prefab_modules(existing)
                               for row in module['data']['replacements'])
        release = existing.manifest['release'] if isinstance(existing, IndependentModPackage) else '1'
        package = with_prefab_replacements(existing, snapshot, {target_path: bytes(replacement)},
                                           release=next_release(release), stop_event=stop_event)
        # The new release must resolve exactly as an install would; this writes nothing.
        from cdmw.services.independent_item_install import resolve_items
        if on_log is not None:
            on_log(f'Checking {package.title} with the prefab edit against the installed game...')
        resolve_items([package_bytes(package)], root, target='virtual', stop_event=stop_event, read_entry=read_entry)
    else:
        package = from_prefab_replacements(snapshot, identity or uuid4().hex, {target_path: bytes(replacement)},
            title=str(title).strip() or 'Prefab edit', release=str(release).strip() or '1', stop_event=stop_event)
    row = next(row for module in prefab_modules(package) for row in module['data']['replacements']
               if row['path'] == target_path)
    replaced_line = (
        (f"This replaces the package's earlier edit of {target_path}. That edit was made on the game's "
         "own copy too, so it is not part of this one; redo it here if you still want it."),
    ) if replaces_earlier else ()
    review = PrefabPackageReview(package, snapshot.provenance.capture(), root, target_path, (
        *replaced_line,
        f'Target prefab: {target_path}',
        f'Package: {package.title}',
        f'Package UUID: {package.identity}',
        f'Release: {package.manifest["release"]}',
        f'Original source SHA-256: {row["source_sha256"]}',
        f'Replacement SHA-256: {row["replacement"]}',
        'The edited prefab decodes as completely as the game copy, and every file it newly points at exists '
        'in this game or is added by the package.',
        'Add this package on the Mods page (or Apply changes again if it is already there). '
        'Game behavior requires separate testing.',
    ), update)
    review.validate(stop_event)
    return review


def write_prefab_package(review, destination=None, *, stop_event=None, on_log=None):
    """Write a new package, or replace the item package the edit was added to."""
    if review.update is not None:
        if destination is not None and Path(destination).expanduser().resolve() != review.update.path:
            raise IndependentItemError('Write an update to the item package it was prepared from.')
        destination = review.update.path
    if destination is None:
        raise IndependentItemError('Choose where to write the prefab package.')
    destination = Path(destination).expanduser().resolve()
    if destination.is_relative_to(review.game_root):
        raise IndependentItemError('Write portable prefab packages outside the game archive folder.')
    review.validate(stop_event)
    if on_log is not None:
        on_log('Writing the reviewed prefab package...')
    return write_package(review.package, destination,
                         expected_digest=review.update.digest if review.update is not None else None,
                         stop_event=stop_event, validate_source=review.validate)
