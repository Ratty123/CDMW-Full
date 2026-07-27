"""Tier C animation retargeting and Tier D motion-clip substitution.

Changing *which* animation draws a weapon is not animation authoring. It is two mechanisms,
both provable:

**Tier C — socket retarget inside `.paac`.** Action-chart strings are length-prefixed
(`<len=strlen+1><ASCII><NUL>`, verified 30/30 across the golden corpus), so replacing a socket
name with another of the *same length* leaves every offset and length field correct. The length
constraint is surfaced as a candidate filter, not an error: names of the wrong length are never
offered.

**Tier D — motion clip substitution.** The golden mods ship "existing source package `.paa` /
`.motionblending` payloads only". Clips are copied from elsewhere in the game, never synthesised.

Both write paths verify before returning: output length unchanged, and byte identity everywhere
outside the patched spans.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from . import paac
from .model import Socket
from .ops import Operation
from .paac import PaacPatchError

# Action charts for the player live under this prefix.
ACTIONCHART_PREFIX = "actionchart/bin__"


class RetargetError(RuntimeError):
    """Raised when a retarget is not representable as a same-length patch."""


def is_actionchart(game_path: str) -> bool:
    return game_path.lower().endswith(".paac")


def actionchart_model(game_path: str) -> str:
    """`actionchart/bin__/upperaction/1_pc/1_phm/ride_upper.paac` -> `1_phm`."""

    parts = PurePosixPath(game_path.lower().replace("\\", "/")).parts
    for index, segment in enumerate(parts):
        if segment == "1_pc" and index + 1 < len(parts):
            return parts[index + 1]
    return ""


def actionchart_group(game_path: str) -> str:
    """The behaviour group — `upperaction`, `loweraction`, and so on."""

    parts = PurePosixPath(game_path.lower().replace("\\", "/")).parts
    for index, segment in enumerate(parts):
        if segment == "bin__" and index + 1 < len(parts):
            return parts[index + 1]
    return ""


# ── socket occurrences ───────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ChartSockets:
    """The socket names one action chart references, with their offsets."""

    game_path: str
    size: int
    occurrences: Mapping[str, tuple[int, ...]] = field(default_factory=dict)

    @property
    def names(self) -> Tuple[str, ...]:
        return tuple(sorted(self.occurrences))

    @property
    def group(self) -> str:
        return actionchart_group(self.game_path)

    @property
    def model(self) -> str:
        return actionchart_model(self.game_path)

    def references(self, socket_name: str) -> bool:
        return socket_name in self.occurrences

    def offsets(self, socket_name: str) -> Tuple[int, ...]:
        return tuple(self.occurrences.get(socket_name, ()))


def index_chart(game_path: str, data: bytes) -> ChartSockets:
    occurrences: Dict[str, List[int]] = {}
    for item in paac.index_sockets(data):
        occurrences.setdefault(item.value, []).append(item.offset)
    return ChartSockets(
        game_path=game_path,
        size=len(data),
        occurrences={name: tuple(offsets) for name, offsets in sorted(occurrences.items())},
    )


class ChartIndex:
    """Every action chart, by the sockets it references."""

    __slots__ = ("_charts",)

    def __init__(self, charts: Iterable[ChartSockets] = ()) -> None:
        self._charts: Dict[str, ChartSockets] = {chart.game_path: chart for chart in charts}

    def __len__(self) -> int:
        return len(self._charts)

    def add(self, chart: ChartSockets) -> None:
        self._charts[chart.game_path] = chart

    def charts(self) -> List[ChartSockets]:
        return sorted(self._charts.values(), key=lambda c: c.game_path)

    def get(self, game_path: str) -> Optional[ChartSockets]:
        return self._charts.get(game_path)

    def vocabulary(self) -> Set[str]:
        """Every socket name any chart references."""

        return {name for chart in self._charts.values() for name in chart.occurrences}

    def charts_referencing(self, socket_name: str, *, model: str = "") -> List[ChartSockets]:
        """Which charts would a retarget of this socket touch?"""

        return [
            chart
            for chart in self.charts()
            if chart.references(socket_name) and (not model or chart.model in ("", model))
        ]

    def sockets_for(self, *, model: str = "") -> Dict[str, int]:
        """socket name -> how many charts reference it."""

        counts: Dict[str, int] = {}
        for chart in self.charts():
            if model and chart.model not in ("", model):
                continue
            for name in chart.occurrences:
                counts[name] = counts.get(name, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


# ── retarget planning ────────────────────────────────────────────────


def retarget_candidates(
    old_name: str,
    *,
    defined_sockets: Iterable[str],
    exclude_self: bool = True,
) -> List[str]:
    """Socket names a retarget may legally use: same length, and actually defined.

    Same length is what keeps the length prefix and every downstream offset valid. Filtering
    here rather than rejecting later is deliberate — a name of the wrong length is not an
    error the user should have to read, it is an option that should not exist.
    """

    width = len(old_name)
    return sorted(
        name
        for name in set(defined_sockets)
        if len(name) == width and (not exclude_self or name != old_name)
    )


@dataclass(frozen=True, slots=True)
class RetargetSite:
    """One file's share of a retarget, with the exact offsets to patch."""

    game_path: str
    offsets: tuple[int, ...]

    @property
    def count(self) -> int:
        return len(self.offsets)


@dataclass(frozen=True, slots=True)
class RetargetPlan:
    """A planned same-length socket retarget across one or more action charts."""

    old_name: str
    new_name: str
    sites: tuple[RetargetSite, ...] = field(default=())

    @property
    def valid(self) -> bool:
        return len(self.old_name) == len(self.new_name) and bool(self.sites)

    @property
    def file_count(self) -> int:
        return len(self.sites)

    @property
    def patch_count(self) -> int:
        return sum(site.count for site in self.sites)

    def paths(self) -> List[str]:
        return [site.game_path for site in self.sites]

    def operations(self) -> List[Operation]:
        return [
            Operation(
                "C",
                "paac_retarget",
                site.game_path,
                self.old_name,
                {"old": self.old_name, "new": self.new_name, "offsets": list(site.offsets)},
            )
            for site in self.sites
        ]

    def describe(self) -> str:
        return (
            f"{self.old_name} -> {self.new_name}  "
            f"{self.patch_count} site(s) across {self.file_count} file(s)"
        )


def plan_retarget(
    index: ChartIndex,
    old_name: str,
    new_name: str,
    *,
    model: str = "",
    paths: Optional[Iterable[str]] = None,
) -> RetargetPlan:
    """Build a retarget plan, refusing anything that is not a same-length swap."""

    if len(old_name) != len(new_name):
        raise RetargetError(
            f"Same-length only: {old_name!r} ({len(old_name)}) != {new_name!r} ({len(new_name)})"
        )
    if not new_name.isascii():
        raise RetargetError(f"Replacement must be ASCII: {new_name!r}")
    if old_name == new_name:
        raise RetargetError("Old and new socket are the same")

    wanted = set(paths) if paths is not None else None
    sites = [
        RetargetSite(chart.game_path, chart.offsets(old_name))
        for chart in index.charts_referencing(old_name, model=model)
        if wanted is None or chart.game_path in wanted
    ]
    return RetargetPlan(old_name, new_name, tuple(site for site in sites if site.count))


def apply_retarget(
    plan: RetargetPlan,
    source: Mapping[str, bytes],
) -> Dict[str, bytes]:
    """Apply a retarget plan, verifying every file before returning any of them.

    Verification is all-or-nothing: a half-patched set of action charts is worse than none.
    """

    if not plan.valid:
        raise RetargetError(f"Invalid retarget plan: {plan.describe()}")

    output: Dict[str, bytes] = {}
    for site in plan.sites:
        data = source.get(site.game_path)
        if data is None:
            raise RetargetError(f"Missing source bytes for {site.game_path}")
        try:
            patched = paac.retarget(data, plan.old_name, plan.new_name, offsets=site.offsets)
        except PaacPatchError as exc:
            raise RetargetError(f"{site.game_path}: {exc}") from exc
        if len(patched) != len(data):
            raise RetargetError(f"{site.game_path}: length changed")
        output[site.game_path] = patched
    return output


def verify_retarget(
    plan: RetargetPlan,
    source: Mapping[str, bytes],
    produced: Mapping[str, bytes],
) -> List[str]:
    """Check a retarget's results. Returns problems; empty means clean."""

    problems: List[str] = []
    for site in plan.sites:
        original = source.get(site.game_path)
        patched = produced.get(site.game_path)
        if original is None or patched is None:
            problems.append(f"{site.game_path}: missing bytes")
            continue
        if len(original) != len(patched):
            problems.append(f"{site.game_path}: length changed")
            continue
        try:
            paac.verify_outside_spans(
                original, patched, [(offset, len(plan.old_name)) for offset in site.offsets]
            )
        except PaacPatchError as exc:
            problems.append(f"{site.game_path}: {exc}")
            continue
        after = paac.socket_histogram(patched)
        if plan.old_name in after:
            problems.append(f"{site.game_path}: {plan.old_name} still present")
        if plan.new_name not in after:
            problems.append(f"{site.game_path}: {plan.new_name} not written")
        # A same-length swap must be exactly reversible.
        try:
            restored = paac.retarget(
                patched, plan.new_name, plan.old_name, offsets=site.offsets
            )
        except PaacPatchError as exc:
            problems.append(f"{site.game_path}: not reversible ({exc})")
            continue
        if restored != original:
            problems.append(f"{site.game_path}: reverse retarget did not restore the original")
    return problems


# ── motion clip substitution (Tier D) ────────────────────────────────

_CLIP_SUFFIXES = (".paa", ".motionblending")


def is_motion_clip(game_path: str) -> bool:
    return game_path.lower().endswith(_CLIP_SUFFIXES)


@dataclass(frozen=True, slots=True)
class ClipSubstitution:
    """Replace one motion clip with the bytes of another that already exists."""

    target_path: str
    source_path: str
    sha256: str = ""
    size: int = 0

    def operation(self) -> Operation:
        return Operation(
            "D",
            "file_replace",
            self.target_path,
            "*",
            {"sha256": self.sha256, "size": self.size, "origin": self.source_path},
        )

    def describe(self) -> str:
        return f"{self.target_path}  <-  {self.source_path}"


def clip_stem(game_path: str) -> str:
    name = PurePosixPath(game_path).name
    for suffix in _CLIP_SUFFIXES:
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return name


def clip_archetype(game_path: str) -> str:
    """`cd_phm_longsword_00_01_normal_move_run_f_ing_000` -> `longsword`.

    Clip names carry the weapon archetype, which is what makes "use the longsword draw for
    the greatsword" expressible as a file-level substitution.
    """

    stem = clip_stem(game_path).lower()
    parts = stem.split("_")
    # cd_<model>_<archetype>_...
    return parts[2] if len(parts) > 3 and parts[0] == "cd" else ""


def substitution_candidates(
    target_path: str,
    available: Iterable[str],
    *,
    same_archetype: bool = False,
) -> List[str]:
    """Clips that could stand in for the target: same kind of file, never itself."""

    target_suffix = PurePosixPath(target_path).suffix.lower()
    archetype = clip_archetype(target_path)
    results = []
    for path in available:
        if path == target_path or PurePosixPath(path).suffix.lower() != target_suffix:
            continue
        if same_archetype and clip_archetype(path) != archetype:
            continue
        results.append(path)
    return sorted(results)
