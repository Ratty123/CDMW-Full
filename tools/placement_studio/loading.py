"""Read and decode immutable Studio requests without accessing Qt widgets."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MeshRequest:
    baseline: object
    model: str
    hierarchy: object
    body: tuple
    armour: tuple
    weapon: tuple
    # Already prepared, immutable mesh data may be reused across equipment changes.
    skinned: tuple | None = None
    body_count: int = 0
    cached_parts: tuple = ()


@dataclass(frozen=True)
class MeshResult:
    skinned: tuple
    body_count: int
    weapon_path: str
    weapon: object
    proxy: object
    coverage: float
    problems: tuple
    cached_parts: tuple = ()


def _source_stamp(baseline, path, entry):
    """Worker-only file identities; an unidentifiable source is never reused."""
    from pathlib import Path
    from .corpus import normalize_game_path
    try:
        if path in baseline:
            files = [baseline.root / normalize_game_path(path)]
            location = ()
        else:
            files = [entry.pamt_path, entry.paz_file]
            if getattr(entry, 'prepared_path', None):
                files.append(entry.prepared_path)
            location = tuple(getattr(entry, name, None) for name in
                             ('offset', 'comp_size', 'orig_size', 'flags', 'prepared_sha256'))
        stamps = []
        for file in files:
            file = Path(file)
            stat = file.stat()
            stamps.append((str(file), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        return tuple(stamps), location
    except (OSError, AttributeError, TypeError):
        return None


def prepare_meshes(request: MeshRequest, cancelled, progress) -> MeshResult | None:
    from .armour import read_entry
    from .meshes import MIN_BODY_COVERAGE, body_coverage, load_mesh, merge
    from .skinning import load_skinned

    def read(path, entry):
        return request.baseline.read(path) if path in request.baseline else read_entry(entry)

    parsed = getattr(request.hierarchy, "parsed", None)
    skinned = list(request.skinned or ())
    body_count = request.body_count
    problems, proxies = [], []
    cached, prepared = dict(request.cached_parts), []
    paths = request.body + request.armour if request.skinned is None else ()
    for number, (path, entry) in enumerate(paths):
        if cancelled():
            return None
        try:
            stamp = _source_stamp(request.baseline, path, entry)
            previous = cached.get(path)
            proxy = None
            if stamp is not None and previous is not None and previous[0] == stamp:
                _, mesh, proxy = previous
            else:
                data = read(path, entry)
                if cancelled():
                    return None
                mesh = load_skinned(data, path, parsed) if parsed is not None else None
                if mesh is None and number < len(request.body):
                    proxy = load_mesh(data, source_path=path)
                if stamp is not None and _source_stamp(request.baseline, path, entry) != stamp:
                    raise ValueError('Source files changed while preparing geometry; refresh and prepare again')
            if mesh is not None:
                skinned.append(mesh)
            elif proxy is not None and number < len(request.body):
                proxies.append(proxy)
            if stamp is not None:
                prepared.append((path, (stamp, mesh, proxy)))
        except Exception as exc:
            problems.append(f"{path.rsplit('/', 1)[-1]}: {exc}")
        if number < len(request.body):
            body_count = len(skinned)
        progress(number + 1, len(paths) + 1)
    if cancelled():
        return None
    path, entry = request.weapon
    weapon = None
    if path:
        try:
            weapon = load_mesh(read(path, entry), source_path=path)
        except Exception as exc:
            problems.append(f"{path.rsplit('/', 1)[-1]}: {exc}")
    if cancelled():
        return None
    proxy = merge(proxies, name="body") if proxies and not skinned else None
    coverage = body_coverage(proxy, request.hierarchy) if proxy is not None else 0.0
    if proxy is not None and coverage < MIN_BODY_COVERAGE:
        problems.append(f"proxy spans only {coverage:.0%} of the rig")
    return MeshResult(tuple(skinned), body_count, path, weapon, proxy, coverage,
                      tuple(problems), tuple(prepared))


def prepare_charts(sources, cancelled, progress):
    from .animation import ChartIndex, index_chart
    from .animation_sets import AnimationSetIndex, read_chart

    charts, sets = [], []
    for number, (path, data) in enumerate(sources):
        if cancelled():
            return None
        charts.append(index_chart(path, data))
        if cancelled():
            return None
        if data:
            sets.append(read_chart(path, data))
        progress(number + 1, len(sources))
    if cancelled():
        return None
    return ChartIndex(charts), AnimationSetIndex(sets)


def prepare_clip_index(root, baseline, cancelled, progress):
    """Keep table I/O, cache decompression and fallback directory walks off Qt."""
    from pathlib import Path
    import time
    from .clips import ClipIndex, index_directory, scan_archives

    try:
        if not Path(root).is_dir():
            raise ValueError(f"No game install at {root}")
        for done, total, index in scan_archives(root, should_stop=cancelled):
            if cancelled():
                return None
            progress(done, total)
            if index is not None:
                return index, ''
            time.sleep(0)  # Yield the GIL between decoded batches as well as file reads.
        return None
    except Exception as error:
        if cancelled():
            return None
        reason = str(error)
        if (Path(baseline) / 'character' / 'motion').is_dir():
            index = index_directory(baseline)
            reason = f"{reason} — showing the pinned baseline only"
        else:
            index = ClipIndex()
        return None if cancelled() else (index, reason)
