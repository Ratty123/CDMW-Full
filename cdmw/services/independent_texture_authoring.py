"""Reviewed standalone texture authoring through the existing package writer."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import os
from pathlib import Path
from uuid import uuid4

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.mod_package import IndependentModPackage
from cdmw.services.independent_item_package import (
    MAX_BLOB, digest, read_package, stock_snapshot, virtual_path, write_package,
)
from cdmw.services.independent_texture_package import (
    from_texture_replacements, lower_texture_operations,
)

MAX_TEXTURE_SEARCH_RESULTS = 200


def _stamp(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _read_replacement(path, stop_event=None):
    path = Path(path)
    if path.suffix.lower() != '.dds':
        raise IndependentItemError('Select a prepared DDS replacement texture.')
    path_before = path.stat()
    with path.open('rb') as source:
        before = os.fstat(source.fileno())
        # Windows exposes different ctime meanings through stat and fstat.
        # Compare full stamps within each API; their common fields bind the path
        # to the open file without mistaking an earlier edit for a racing write.
        if _stamp(before)[:4] != _stamp(path_before)[:4]:
            raise IndependentItemError('The replacement texture changed while it was being read.')
        if before.st_size > MAX_BLOB:
            raise IndependentItemError('The replacement texture exceeds the package size limit.')
        pieces, size = [], 0
        while True:
            raise_if_cancelled(stop_event)
            block = source.read(min(1024 * 1024, MAX_BLOB + 1 - size))
            if not block:
                break
            pieces.append(block)
            size += len(block)
            if size > MAX_BLOB:
                raise IndependentItemError('The replacement texture exceeds the package size limit.')
        if _stamp(os.fstat(source.fileno())) != _stamp(before) or _stamp(path.stat()) != _stamp(path_before):
            raise IndependentItemError('The replacement texture changed while it was being read.')
    return b''.join(pieces)


@dataclass(frozen=True)
class TextureFileRevision:
    path: Path
    size: int
    sha256: str

    def validate(self, stop_event=None):
        data = _read_replacement(self.path, stop_event)
        if len(data) != self.size or digest(data) != self.sha256:
            raise IndependentItemError('The selected replacement texture changed. Review it again.')


@dataclass(frozen=True)
class TextureTargetCatalogue:
    root: Path
    snapshot: object
    paths: tuple[str, ...]
    total_matches: int


@dataclass(frozen=True)
class TexturePackageUpdate:
    path: Path
    identity: str
    digest: str
    artifact_digest: str
    target_path: str
    title: str
    release: str


def _editable_texture_row(package):
    if not isinstance(package, IndependentModPackage):
        raise IndependentItemError('This editor updates v2 standalone texture packages only.')
    manifest = package.manifest
    modules = manifest['modules']
    if (manifest['requires'] != {'texture.replace': 1} or len(modules) != 1
            or modules[0]['type'] != 'texture.replace' or modules[0]['version'] != 1
            or len(modules[0]['data']['replacements']) != 1
            or manifest['provenance'] is not None):
        raise IndependentItemError('This editor updates one texture replacement at a time. Combined packages require their owning editor.')
    row = modules[0]['data']['replacements'][0]
    if set(package.dependencies) != {row['path']}:
        raise IndependentItemError('This texture package has additional dependencies that this editor cannot update.')
    return row


def _update_selection(path, package):
    row = _editable_texture_row(package)
    return TexturePackageUpdate(Path(path).resolve(), package.identity, package.digest,
        package.artifact_digest, row['path'], package.title, package.manifest['release'])


def load_texture_package_update(path, *, stop_event=None):
    path = Path(path).expanduser().resolve()
    return _update_selection(path, read_package(path, stop_event=stop_event))


def _current_update(selection, stop_event):
    package = read_package(selection.path, stop_event=stop_event)
    if _update_selection(selection.path, package) != selection:
        raise IndependentItemError('The package selected for update changed. Load it again before reviewing.')
    return package


def find_existing_texture_targets(root, query='', *, service=None, read_entry=None, stop_event=None, on_log=None):
    """Read a fresh stock catalogue on a worker, then return a bounded selection."""
    root = Path(root).expanduser().resolve()
    snapshot = stock_snapshot(root, service=service, read_entry=read_entry,
                              stop_event=stop_event, on_log=on_log)
    if snapshot.pathc is None:
        raise IndependentItemError('Texture packages require an existing game texture registry.')
    query = str(query).strip().casefold()
    matches = []
    for path, entry in snapshot.entries.items():
        raise_if_cancelled(stop_event)
        if not path.endswith('.dds') or query not in path.casefold():
            continue
        try:
            virtual_path(path)
        except IndependentItemError:
            continue
        archive = Path(entry.pamt_path).resolve()
        group = archive.parent.name
        registered = snapshot.pathc.find(path)
        if (archive.parent.parent != root or len(group) != 4 or not group.isascii()
                or not group.isdigit() or int(group) >= 36
                or registered is None or not registered.is_direct):
            continue
        matches.append(path)
    matches.sort()
    snapshot.provenance.capture().validate(stop_event)
    return TextureTargetCatalogue(root, snapshot, tuple(matches[:MAX_TEXTURE_SEARCH_RESULTS]), len(matches))


@dataclass(frozen=True)
class TexturePackageReview:
    package: IndependentModPackage
    source_revision: object
    replacement: TextureFileRevision
    game_root: Path
    target_path: str
    update: TexturePackageUpdate | None
    lines: tuple[str, ...]

    def validate(self, stop_event=None):
        raise_if_cancelled(stop_event)
        self.source_revision.validate(stop_event)
        self.replacement.validate(stop_event)
        if self.update is not None:
            _current_update(self.update, stop_event)


def prepare_texture_package(catalogue, target_path, replacement_path, *, title='Texture replacements',
                            release='1', identity=None, update=None, stop_event=None):
    """Keep the source/registry, chosen local bytes and selected update pinned."""
    raise_if_cancelled(stop_event)
    if not isinstance(catalogue, TextureTargetCatalogue):
        raise IndependentItemError('Find the existing game texture before reviewing its replacement.')
    target_path = virtual_path(str(target_path))
    snapshot = catalogue.snapshot
    previous = None
    if update is not None:
        previous = _current_update(update, stop_event)
        if target_path != update.target_path:
            raise IndependentItemError('An update must retain its existing texture target. Create a new package for another target.')
        lower_texture_operations(previous, snapshot, {}, stop_event=stop_event)
        identity = previous.identity
    identity = identity or uuid4().hex
    replacement_path = Path(replacement_path).expanduser().resolve()
    replacement = _read_replacement(replacement_path, stop_event)
    package = from_texture_replacements(snapshot, identity, {target_path: replacement},
        title=str(title).strip(), release=str(release).strip(), stop_event=stop_event)
    if previous is not None:
        from cdmw.services.independent_mod_package import read_v2
        manifest = deepcopy(previous.manifest)
        manifest['title'] = package.title
        manifest['release'] = package.manifest['release']
        manifest['dependencies'] = dict(package.dependencies)
        manifest['blobs'] = dict(package.manifest['blobs'])
        manifest['modules'][0]['data'] = deepcopy(package.manifest['modules'][0]['data'])
        package = read_v2(manifest, package.blobs, stop_event=stop_event)
    row = package.manifest['modules'][0]['data']['replacements'][0]
    review = TexturePackageReview(package, snapshot.provenance.capture(),
        TextureFileRevision(replacement_path, len(replacement), digest(replacement)),
        catalogue.root, target_path, update, (
            f"Target texture: {target_path}",
            f"Package: {package.title}",
            f"Package UUID: {package.identity}",
            f"Release: {package.manifest['release']}",
            f"Original source SHA-256: {row['source_sha256']}",
            f"Replacement SHA-256: {row['replacement']}",
            f"Replacement size: {len(replacement)} bytes",
            'The complete DDS descriptor and every mip were validated.',
            'No item IDs or texture registry entries are created.',
            'Install or update this package from Mods. Game appearance requires separate testing.',
        ))
    review.validate(stop_event)
    return review


def write_texture_package(review, destination, *, stop_event=None, on_log=None):
    destination = Path(destination).expanduser().resolve()
    if destination.is_relative_to(review.game_root):
        raise IndependentItemError('Write portable texture packages outside the game archive folder.')
    if review.update is not None and destination != review.update.path:
        raise IndependentItemError('Write an update to the explicitly selected package path.')
    review.validate(stop_event)
    if on_log is not None:
        on_log('Writing the reviewed texture package...')
    result = write_package(review.package, destination,
        expected_digest=review.update.digest if review.update is not None else None,
        stop_event=stop_event, validate_source=review.validate)
    return result
