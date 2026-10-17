"""Separate catalogue freshness from the content required by a virtual profile."""
from pathlib import Path

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.services.new_item_provenance import SourceRevision, _stamp


def profile_revision(resolved):
    """Keep explicit reads and runtime dependencies authoritative.

    The v1 compiler reruns audit_references while lowering every recipe, including
    borrowed PAC companions, prefabs, materials, DDS and effect references. A
    completed traversal records whether every borrowed reference boundary was
    parsed or known to be terminal. Each declared package dependency is also
    read and checked before that lowering.
    Unknown external contributions and other module combinations retain the full
    carrier guards until their runtime closure has an equivalent proof.
    """
    revisions = (resolved.baseline.provenance.capture(), *resolved.revisions)
    payloads, pinned, indexes, required = {}, {}, {}, set()
    for source in revisions:
        required.update(path for path, _ in source.content_files)
        for payload in source.payloads:
            prior = payloads.setdefault(payload.entry.identity, payload)
            if prior.sha256 != payload.sha256:
                raise VirtualLoaderError(f'Source payload has conflicting revisions: {payload.entry.path}.')
        for path, stamp in source.files:
            if path in pinned and pinned[path] != stamp:
                raise VirtualLoaderError(f'Source changed during preparation: {path}.')
            pinned[path] = stamp
        for path, checksum in source.indexes:
            if indexes.setdefault(path, checksum) != checksum:
                raise VirtualLoaderError(f'Source index has conflicting parsed revisions: {path}.')
    from cdmw.domain.new_item.independent import IndependentItemPackage
    bounded = (not resolved.external.providers
               and not any(layer['active'] for layer in resolved.state['layers'])
               and all(isinstance(package, IndependentItemPackage) for package, _ in resolved.contributions)
               and all(source.reference_closure_complete for source in resolved.revisions))
    catalogue = tuple(sorted(path for path in pinned if bounded and path not in required
                             and path.suffix.lower() == '.paz'))
    return SourceRevision(tuple(payloads.values()), tuple(pinned.items()), revisions[0].reader,
                          tuple(indexes.items()), catalogue)


def catalogue_records(revision):
    pinned = dict(revision.files)
    return [(str(path), pinned[path]) for path in revision.catalogue_files]


def verify_catalogue(records, stop_event=None):
    for path, expected in records:
        raise_if_cancelled(stop_event)
        stamp = tuple(expected) if expected is not None else None
        if _stamp(Path(path)) != stamp:
            raise VirtualLoaderError(f'Archive catalogue source changed: {path}. Apply changes again.')
