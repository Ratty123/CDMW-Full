"""Cancellable archive reads for Studio browsing, published separately from live edits."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ArchiveRequest:
    root: object
    model: str
    baseline_paths: frozenset
    sockets: tuple
    prefabs: tuple
    charts: tuple
    mesh_paths: frozenset
    weapons: bool


@dataclass(frozen=True)
class ArchiveResult:
    sockets: tuple
    models: tuple
    charts: tuple
    errors: tuple


def prepare_archive_content(request, cancelled, progress):
    from .armour import cached_content, read_entry, store_content
    from .corpus import package_signature
    from .equipment_assets import prefab_models

    signature = package_signature(request.root)
    errors, caches, models = [], [], []

    def read_kind(kind, entries):
        if cancelled():
            return {}
        cached = cached_content(request.model, kind, request.root)
        payloads = {}
        failed = False
        for number, (path, entry) in enumerate(entries):
            if cancelled():
                return {}
            try:
                payloads[path] = (cached[path] if cached is not None and path in cached
                                  else read_entry(entry))
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                failed = True
                errors.append(f'{path}: {exc}')
            progress(number + 1, len(entries))
        if payloads and not failed and cached is None:
            caches.append((kind, payloads))
        return payloads

    sockets = read_kind('sockets', request.sockets) if request.weapons else {}
    prefabs = read_kind('weapon-prefabs', request.prefabs) if request.weapons else {}
    for path, data in prefabs.items():
        if cancelled():
            return None
        try:
            models.extend(model for model in prefab_models(data, path)
                          if model.mesh in request.mesh_paths)
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            errors.append(f'{path}: {exc}')
    charts = read_kind('charts', request.charts)
    if cancelled():
        return None
    if package_signature(request.root) != signature:
        raise ValueError('Equipment relationships changed; refresh required')
    for kind, payloads in caches:
        if cancelled():
            return None
        store_content(request.model, kind, payloads, request.root, signature=signature)
    return ArchiveResult(tuple(sockets.items()), tuple(models), tuple(charts.items()), tuple(errors))
