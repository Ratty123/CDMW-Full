"""Read and decode immutable Studio requests without accessing Qt widgets."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DecodedGeometry:
    data: bytes
    mesh: object
    nbytes: int


def _rig_key(skeleton):
    """Bind results belong to bone content, not a newly allocated session object."""
    if skeleton is None:
        return None
    bones = getattr(skeleton, 'bones', None)
    if bones is None:
        return skeleton  # Nonstandard callers retain identity-based isolation.
    return tuple((getattr(bone, 'index', index), bone.name, bone.name_hash, bone.parent_index,
                  tuple(bone.bind_matrix), tuple(bone.inv_bind_matrix),
                  tuple(bone.scale), tuple(bone.rotation), tuple(bone.position))
                 for index, bone in enumerate(bones))


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


def prepare_model_baseline(baseline, model, source, cancelled):
    """Complete a character's loose baseline only when that character is selected."""
    from .cli_support import discover_body_meshes
    from .corpus import extract_baseline
    from .meshes import weapon_mesh_path
    from .resolver import model_of, weapon_id_of
    from .session import skeleton_paths_for

    paths = baseline.paths()
    prefix = f'/{model}/'
    if (any(prefix in path and path.endswith('.pab') for path in paths)
            and any(prefix in path and '/armor/' in path and path.endswith('.pac') for path in paths)):
        return baseline
    catalogue = source.open(cancelled)
    sockets = [path for path in paths if path.endswith('.sockets.xml') and model_of(path) == model]
    wanted = set(skeleton_paths_for(sockets))
    wanted.update(discover_body_meshes([model], resident_catalogue=catalogue))
    wanted.update(weapon_mesh_path(weapon_id_of(path), model) for path in sockets if '/weapon/' in path)
    return extract_baseline(wanted, out_root=baseline.root, resident_catalogue=catalogue,
                            existing=baseline, should_stop=cancelled)


def prepare_meshes(request: MeshRequest, cancelled, progress) -> MeshResult | None:
    from cdmw.modding.mesh_parser import parse_mesh
    from .armour import read_entry
    from .meshes import MIN_BODY_COVERAGE, body_coverage, load_mesh, merge
    from .skinning import load_skinned

    def read(path, entry):
        return request.baseline.read(path) if path in request.baseline else read_entry(entry)

    parsed = getattr(request.hierarchy, "parsed", None)
    rig_key = _rig_key(parsed)
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
            key = ('bound-v1', path, rig_key, number < len(request.body))
            decoded_key = ('decoded-v1', path)
            previous = cached.get(key)
            proxy = None
            if stamp is not None and previous is not None and previous[0] == stamp:
                _, mesh, proxy = previous
            else:
                decoded = cached.get(decoded_key)
                if stamp is not None and decoded is not None and decoded[0] == stamp:
                    geometry = decoded[1]
                else:
                    data = read(path, entry)
                    if cancelled():
                        return None
                    mesh_data = parse_mesh(data, path.rsplit('/', 1)[-1])
                    # Conservative Python row storage estimate, computed off Qt.
                    size = len(data) + sum(2048 * len(part.vertices) + 160 * len(part.faces)
                                           for part in mesh_data.submeshes)
                    geometry = DecodedGeometry(data, mesh_data, size)
                if cancelled():
                    return None
                mesh = load_skinned(geometry.data, path, parsed, parsed_mesh=geometry.mesh) if parsed is not None else None
                if mesh is None and number < len(request.body):
                    proxy = load_mesh(geometry.data, source_path=path, parsed_mesh=geometry.mesh)
                if stamp is not None and _source_stamp(request.baseline, path, entry) != stamp:
                    raise ValueError('Source files changed while preparing geometry; refresh and prepare again')
                if stamp is not None:
                    prepared.append((decoded_key, (stamp, geometry, None)))
            if mesh is not None:
                skinned.append(mesh)
            elif proxy is not None and number < len(request.body):
                proxies.append(proxy)
            if stamp is not None:
                prepared.append((key, (stamp, mesh, proxy)))
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


def prepare_clip_index(root, baseline, cancelled, progress, *, resident_source=None):
    """Keep table I/O, cache decompression and fallback directory walks off Qt."""
    from pathlib import Path
    import time
    from .clips import ClipIndex, index_directory, scan_archives

    try:
        if not Path(root).is_dir():
            raise ValueError(f"No game install at {root}")
        for done, total, index in scan_archives(root, should_stop=cancelled, **(
                {"resident_source": resident_source} if resident_source is not None else {})):
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
