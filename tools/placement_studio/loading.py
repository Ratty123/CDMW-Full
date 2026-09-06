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


@dataclass(frozen=True)
class MeshResult:
    skinned: tuple
    body_count: int
    weapon_path: str
    weapon: object
    proxy: object
    coverage: float
    problems: tuple


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
    paths = request.body + request.armour if request.skinned is None else ()
    for number, (path, entry) in enumerate(paths):
        if cancelled():
            return None
        try:
            data = read(path, entry)
            mesh = load_skinned(data, path, parsed) if parsed is not None else None
            if mesh is not None:
                skinned.append(mesh)
            elif number < len(request.body):
                proxies.append(load_mesh(data, source_path=path))
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
    return MeshResult(tuple(skinned), body_count, path, weapon, proxy, coverage, tuple(problems))


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
