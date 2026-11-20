"""Speed Tuning (experimental): how fast a character's attacks, jumps and other moves play.

The game reads each move's speed from its action chart (`.paac`). Every animation entry
has speed windows (start, end, rate), and the chart has one rate for all of it
(`ActionSpeedRate`). This module lists a character's charts ("sets"), reads one as moves
grouped by clip, and writes a DMM mod with chosen speed factors through the action chart
edit service. A factor multiplies the shipped rate, so 2 plays that move twice as fast.

The set list, the move kinds and the factor model come from Crimson Live Edit's
Animation speed page (`tools/live_chart_speed.py`). Live Edit also writes speeds into the
running game; that stays in Live Edit. Here the game archives are only read and the
result is always a mod folder.

Factor rule, shared by the Speed Tuning window and the MCP `speed.` tools:

* a speed window's factor is the move's own factor, else the "Moves named" factor when
  the clip's file name contains one of its texts, else its kind's, else 1;
* the set factor scales only the chart's `ActionSpeedRate`, as in Live Edit, so a set
  factor of 2 with an attack factor of 2 plays attacks four times as fast.

No Qt imports.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping, Optional, Sequence

from cdmw.core.action_chart_binary import ANIMATION_TABLE, ActionChart, ActionChartError, ChartValueEdit
from cdmw.models import ArchiveEntry
from cdmw.services.action_chart_edit_service import (
    ACTION_CHART_EXTENSION,
    ActionChartEditRequest,
    ChartArchiveIndex,
    animation_value_rows,
    chart_rate_row,
    chart_scan,
    character_rows_from_index,
    compare_charts,
    apply_action_chart_edits,
    included_charts,
    is_chart_mod,
    is_editable_action_chart_path,
    load_editable_chart,
    mod_destination,
    read_chart_mod,
    string_rows,
    write_action_chart_mod,
    write_action_charts_mod,
)
from cdmw.domain.cancellation import raise_if_cancelled

MIN_FACTOR, MAX_FACTOR = 0.1, 5.0
#: The manifest key the factors of each chart are kept under, so a reopened mod shows them.
MANIFEST_KEY = "speed_tuning"
SPEED_GENERATOR_NOTE = "CDMW Speed Tuning (experimental)"

#: Live Edit's two players, by their chart folder; the fallback when no package description reads.
CHARACTERS = {"Kliff": "1_phm", "Damiane": "2_phw"}
#: First match wins; attacks before movement, because attack clips name their steps.
KINDS = (
    ("attack", re.compile(r"(_att|attack|_skill|combo|swing|smash|stab|thrust|slash|_kick|_punch|charge_shot|_shot_)")),
    ("jump", re.compile(r"jump")),
    ("guard", re.compile(r"(guard|_def_|parry|block)")),
    ("dodge", re.compile(r"(evade|dodge|_roll|avoid|_step_|sidestep|backstep)")),
    ("draw", re.compile(r"(weapon_?in|weapon_?out|_draw|sheath|_equip|unequip)")),
    ("movement", re.compile(r"(_run|_walk|sprint|dash|_move|_turn|_std_to|_stop)")),
    ("idle", re.compile(r"(idle|_stand_|_stance)")),
)
#: A chart keeps a speed window's rate above 0 and at most this.
MAX_RATE = 100.0
#: "Moves named": the user's own group, by parts of the clip file name.
NAMED_KIND, NAMED_LABEL = "named", "Moves named"
NAMED_MIN_LENGTH, NAMED_MAX_LENGTH, NAMED_MAX_TEXTS = 3, 64, 8
KIND_LABELS = {
    "attack": "Attacks", "jump": "Jumps", "guard": "Guard and parry", "dodge": "Dodges",
    "draw": "Draw and sheathe", "movement": "Movement", "idle": "Idle and stance", "other": "Other",
}
NAMES = {
    "twohandsword": "Two-handed sword", "sword": "Sword", "dualsword": "Dual swords", "dualweapon": "Dual weapons",
    "dagger": "Dagger", "fist": "Fists", "battleaxe": "Battle axe", "weapon2h": "Two-handed weapons", "spear": "Spear",
    "subweapon": "Sub-weapon", "sub_bow": "Bow", "bow": "Bow", "tool": "Tools", "torch": "Torch",
}


class SpeedTuningError(ActionChartError):
    """A speed request that cannot be planned or written; the message is for the user."""


# --- data ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpeedSet:
    """One action chart offered as a set of moves."""

    path: str
    label: str
    legs: bool = False


@dataclass(frozen=True, slots=True)
class SpeedCharacter:
    name: str
    sets: tuple[SpeedSet, ...]


@dataclass(frozen=True, slots=True)
class SpeedMove:
    """Every animation entry of a chart that plays one clip."""

    clip: str
    label: str
    kind: str
    entries: int
    windows: int
    seconds: float
    factor: float = 1.0


@dataclass(frozen=True, slots=True)
class SpeedFactors:
    """`set` scales ActionSpeedRate; `kinds`, `named` and `moves` (by clip) scale speed windows.

    `named` holds parts of clip file names; every move whose name contains one of them
    takes `named_factor` instead of its kind's factor.
    """

    set: float = 1.0
    kinds: Mapping[str, float] = field(default_factory=dict)
    moves: Mapping[str, float] = field(default_factory=dict)
    named: tuple[str, ...] = ()
    named_factor: float = 1.0

    def factor_source(self, clip: str, kind: str) -> tuple[str, float]:
        """Where a move's factor comes from ("move", "named" or "kind") and the factor."""

        moves = {key.lower(): value for key, value in self.moves.items()}
        if clip.lower() in moves:
            return "move", float(moves[clip.lower()])
        if self.named and named_match(clip, self.named):
            return NAMED_KIND, float(self.named_factor)
        return "kind", float(self.kinds.get(kind, 1.0))

    def window_factor(self, clip: str, kind: str) -> float:
        return self.factor_source(clip, kind)[1]

    @property
    def names_moves(self) -> bool:
        return bool(self.named) and not _unit(self.named_factor)

    @property
    def is_identity(self) -> bool:
        values = [self.set, *self.kinds.values(), *self.moves.values()]
        return all(_unit(value) for value in values) and not self.names_moves

    def to_data(self) -> dict[str, object]:
        kinds = {k: float(v) for k, v in self.kinds.items() if not _unit(v)}
        # A move held at 1 is a real choice while a kind or Moves named factor would otherwise
        # apply to it, so it is saved then: dropping it made the move take that factor when
        # the mod was reopened.
        moves = {k: float(v) for k, v in self.moves.items() if kinds or self.names_moves or not _unit(v)}
        data: dict[str, object] = {"set": float(self.set), "kinds": kinds, "moves": moves}
        # Moves named at 1x is a real choice too while a kind factor is set: those moves stay at
        # the game's speed.
        if self.names_moves or (self.named and kinds):
            data["named"] = {"texts": list(self.named), "factor": float(self.named_factor)}
        return data

    @classmethod
    def from_data(cls, value: object) -> "SpeedFactors":
        if not isinstance(value, Mapping):
            raise SpeedTuningError("Speed factors must be an object with set, kinds and moves.")
        kinds = dict(value.get("kinds") or {})
        moves = dict(value.get("moves") or {})
        unknown = sorted(set(kinds) - set(KIND_LABELS))
        if unknown:
            raise SpeedTuningError(f"Unknown move kind(s): {', '.join(unknown)}. Kinds are {', '.join(KIND_LABELS)}.")
        named = value.get("named") or {}
        if not isinstance(named, Mapping):
            raise SpeedTuningError("Moves named must be an object with texts and factor.")
        texts = named.get("texts") or ()
        if isinstance(texts, str) or not isinstance(texts, (list, tuple)):
            raise SpeedTuningError("Moves named texts must be a list of texts.")
        factors = cls(float(value.get("set", 1.0)), {str(k): float(v) for k, v in kinds.items()},
                      {str(k): float(v) for k, v in moves.items()},
                      named_texts(texts), float(named.get("factor", 1.0)))
        check_factors(factors)
        return factors


@dataclass(frozen=True, slots=True)
class SpeedChart:
    """A set read as moves, with the factors a named mod already applies to it."""

    path: str
    label: str
    rate: float
    moves: tuple[SpeedMove, ...]
    factors: SpeedFactors
    mod: str = ""
    served_by: str = ""

    def kinds(self) -> tuple[tuple[str, str, int], ...]:
        counts: dict[str, int] = {}
        for move in self.moves:
            counts[move.kind] = counts.get(move.kind, 0) + 1
        return tuple((kind, label, counts[kind]) for kind, label in KIND_LABELS.items() if kind in counts)


@dataclass(frozen=True, slots=True)
class KindSummary:
    kind: str
    label: str
    values: int
    before: tuple[float, float]
    after: tuple[float, float]


@dataclass(frozen=True, slots=True)
class SpeedPlan:
    """What a set of factors would change in one chart, read back from the edited bytes."""

    path: str
    request: ActionChartEditRequest
    edited: bytes
    changed_values: int
    kinds: tuple[KindSummary, ...]
    rate_before: float
    rate_after: float
    #: Speed windows the game ships at rate 0: no factor changes them, so they are left alone.
    skipped_windows: int = 0

    @property
    def empty(self) -> bool:
        return self.request.empty


@dataclass(frozen=True, slots=True)
class SpeedProfilePlan:
    """One set of factors checked on many charts."""

    plans: tuple[SpeedPlan, ...]              # charts that change
    unchanged: tuple[str, ...]                # charts these factors change nothing in
    left_out: tuple[tuple[str, str], ...]     # (chart, the reason, for the user)

    @property
    def changed_values(self) -> int:
        return sum(plan.changed_values for plan in self.plans)


@dataclass(frozen=True, slots=True)
class SpeedExportResult:
    folder: Optional[Path]
    title: str
    charts: tuple[str, ...]
    changed_values: int
    removed: tuple[str, ...] = ()
    #: Linked charts the mod holds as sets of their own; their own factors were kept.
    kept: tuple[str, ...] = ()
    #: (chart, reason) for charts a many-set export could not change.
    left_out: tuple[tuple[str, str], ...] = ()


# --- names and kinds ----------------------------------------------------------------


def _unit(value: float) -> bool:
    return abs(float(value) - 1.0) < 1e-6


def _normal(path: object) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/")


def chart_label(path: str) -> str:
    """A set's plain name, such as "Two-handed sword" or "Basic: ride (legs)"."""

    path = _normal(path).lower()
    stem = PurePosixPath(path).name.removesuffix(ACTION_CHART_EXTENSION)
    part = " (legs)" if stem.endswith("_lower") or "/loweraction/" in path else ""
    stem = re.sub(r"_(upper|lower)$", "", stem)
    if stem.startswith("basic_upper_") or stem.startswith("basic_lower_"):
        return "Basic: " + stem.split("_", 2)[2].replace("_", " ") + part
    for key, name in sorted(NAMES.items(), key=lambda item: -len(item[0])):
        if stem == key or stem.startswith(key + "_"):
            rest = stem[len(key):].strip("_").replace("_", " ")
            return name + (" " + rest if rest else "") + part
    return stem.replace("_", " ").capitalize() + part


def kind_of(clip: str) -> str:
    name = PurePosixPath(_normal(clip).lower()).name
    for kind, pattern in KINDS:
        if pattern.search(name):
            return kind
    return "other"


def named_texts(texts: Iterable[object]) -> tuple[str, ...]:
    """Moves named texts as kept: trimmed, lower case, empty ones dropped."""

    return tuple(text for text in (str(item or "").strip().lower() for item in texts) if text)


def named_match(clip: str, texts: Sequence[str]) -> bool:
    """Whether one of `texts` is part of the clip's file name (the name `kind_of` reads)."""

    name = PurePosixPath(_normal(clip).lower()).name
    return any(text and text.lower() in name for text in texts)


def check_named(texts: Sequence[str]) -> None:
    if len(texts) > NAMED_MAX_TEXTS:
        raise SpeedTuningError(f"Moves named takes at most {NAMED_MAX_TEXTS} texts.")
    for text in texts:
        if not NAMED_MIN_LENGTH <= len(str(text).strip()) <= NAMED_MAX_LENGTH:
            raise SpeedTuningError(f"Each Moves named text must have {NAMED_MIN_LENGTH} to {NAMED_MAX_LENGTH} "
                                   f"characters; got {str(text)!r}.")
    if len({str(text).strip().lower() for text in texts}) != len(texts):
        raise SpeedTuningError("A Moves named text is given twice.")


def check_factor(value: object, what: str = "Speed factors") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise SpeedTuningError(f"{what} must be numbers between {MIN_FACTOR:g} and {MAX_FACTOR:g}.")
    if not MIN_FACTOR - 1e-9 <= float(value) <= MAX_FACTOR + 1e-9:
        raise SpeedTuningError(f"{what} must be between {MIN_FACTOR:g} and {MAX_FACTOR:g}; got {float(value):g}.")
    return float(value)


def check_factors(factors: SpeedFactors) -> None:
    check_factor(factors.set, "The set factor")
    for kind, value in factors.kinds.items():
        if kind not in KIND_LABELS:
            raise SpeedTuningError(f"Unknown move kind {kind!r}.")
        check_factor(value, f"The {KIND_LABELS[kind].lower()} factor")
    for clip, value in factors.moves.items():
        check_factor(value, f"The factor for {clip}")
    check_factor(factors.named_factor, "The Moves named factor")
    check_named(factors.named)


# --- sets ---------------------------------------------------------------------------


def _sorted_sets(paths: Iterable[str]) -> tuple[SpeedSet, ...]:
    rows = {_normal(path).lower(): SpeedSet(_normal(path), chart_label(path), "/loweraction/" in _normal(path).lower())
            for path in paths if is_editable_action_chart_path(path) and "sequencer" not in _normal(path).lower()}
    return tuple(sorted(rows.values(), key=lambda row: (row.label.startswith("Basic") or row.label.startswith("Ride"),
                                                        row.legs, row.label.lower())))


def folder_sets(index: ChartArchiveIndex, character: str) -> tuple[SpeedSet, ...]:
    """Live Edit's list: every chart under /1_pc/<folder>/ for Kliff or Damiane."""

    folder = CHARACTERS.get(character)
    if folder is None:
        return ()
    return _sorted_sets(path for path in index.paths_by_extension.get(ACTION_CHART_EXTENSION, ())
                        if f"/1_pc/{folder}/" in path.lower())


def _player_name(package: str) -> str:
    for name in CHARACTERS:
        if name.lower() in package.lower():
            return name
    return package


def list_characters(
    index: ChartArchiveIndex,
    read: Callable[[ArchiveEntry], bytes],
    *,
    includes: Optional[Mapping[str, Sequence[str]]] = None,
) -> tuple[SpeedCharacter, ...]:
    """Every character package with charts, Kliff and Damiane first.

    A package's sets are the charts its slots name and, with `includes`, the charts
    those include. Kliff and Damiane also get every chart in their folder, as in Live
    Edit. Without a readable package description only those two are listed.
    """

    available = {path.lower(): path for path in index.paths_by_extension.get(ACTION_CHART_EXTENSION, ())}
    found: dict[str, list[str]] = {}
    try:
        rows = character_rows_from_index(index, read)
    except (ActionChartError, OSError, ValueError):
        rows = ()
    for row in rows:
        path = available.get(row.archive_path.lower())
        if path is None:
            continue
        paths = found.setdefault(_player_name(row.package), [])
        paths.append(path)
        if includes is not None:
            paths.extend(included_charts(includes, path))
    for name in CHARACTERS:
        found.setdefault(name, []).extend(item.path for item in folder_sets(index, name))
    characters = [SpeedCharacter(name, _sorted_sets(paths)) for name, paths in found.items()]
    order = list(CHARACTERS)
    characters = [item for item in characters if item.sets]
    characters.sort(key=lambda item: (order.index(item.name) if item.name in order else len(order), item.name.lower()))
    return tuple(characters)


# --- reading a set ------------------------------------------------------------------


def _clip_names(chart: ActionChart, data: bytes) -> dict[int, str]:
    return {row.index: row.value for row in string_rows(chart, data, ANIMATION_TABLE)}


def _speed_rows(chart: ActionChart, data: bytes, index: int):
    return [row for row in animation_value_rows(chart, data, index) if row.field == "speed.rate"]


def _moves(chart: ActionChart, data: bytes) -> dict[str, dict]:
    names = _clip_names(chart, data)
    moves: dict[str, dict] = {}
    for animation in chart.animations:
        clip = names.get(animation.clip_index)
        if not clip:
            continue
        rows = _speed_rows(chart, data, animation.index)
        move = moves.setdefault(clip.lower(), {
            "clip": clip, "label": PurePosixPath(clip).name.removesuffix(".paa"), "kind": kind_of(clip),
            "entries": 0, "windows": 0, "seconds": 0.0, "animations": []})
        move["entries"] += 1
        move["windows"] += len(rows)
        move["seconds"] = max(move["seconds"], round(float(animation.end_time) - float(animation.start_time), 3))
        move["animations"].append(animation.index)
    return moves


def factors_from_charts(shipped: bytes, edited: bytes, path: str) -> SpeedFactors:
    """The per-move factors and set factor an edited chart holds against the shipped one."""

    chart = load_editable_chart(shipped, path)
    after = load_editable_chart(edited, path)
    if len(chart.animations) != len(after.animations):
        raise SpeedTuningError(f"The modded copy of {path} has a different layout than the game's.")
    moves: dict[str, float] = {}
    for clip, move in _moves(chart, shipped).items():
        for index in move["animations"]:
            before = _speed_rows(chart, shipped, index)
            now = _speed_rows(after, edited, index)
            if before and now and before[0].value:
                ratio = round(float(now[0].value) / float(before[0].value), 3)
                if not _unit(ratio):
                    moves[move["clip"]] = ratio
                break
    rate = float(chart_rate_row(chart).value)
    rate_now = float(chart_rate_row(after).value)
    return SpeedFactors(round(rate_now / rate, 3) if rate else 1.0, {}, moves)


def _own_factors(value: object) -> bool:
    """Whether a saved manifest entry holds a set's own factors (not just `linked_to`)."""

    return isinstance(value, Mapping) and any(key in value for key in ("set", "kinds", "moves", "named"))


def _mod_factors(folder: Path, path: str, shipped: bytes) -> Optional[SpeedFactors]:
    """The factors the mod in `folder` holds for `path`: as saved by Speed Tuning, else from its values."""

    if not folder.is_dir() or not is_chart_mod(folder):
        return None
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    saved = (manifest.get(MANIFEST_KEY) or {}) if isinstance(manifest, dict) else {}
    for chart_path, value in (saved.get("charts") or {}).items() if isinstance(saved, dict) else ():
        if chart_path.lower() == path.lower():
            # A chart saved only as linked to another set has no factors of its own here; what it
            # holds is read from its values below, so it does not show 1x and lose them on export.
            if not _own_factors(value):
                break
            try:
                return SpeedFactors.from_data(value)
            except (SpeedTuningError, TypeError, ValueError):
                break
    for chart_path, data in read_chart_mod(folder).charts.items():
        if chart_path.lower() == path.lower():
            return factors_from_charts(shipped, data, path)
    return None


def read_speed_set(
    index: ChartArchiveIndex,
    read: Callable[[ArchiveEntry], bytes],
    path: str,
    *,
    mod_folder: Optional[Path | str] = None,
) -> SpeedChart:
    """One set as moves, with the factors the mod at `mod_folder` applies to it, if any."""

    entry = index.entry_for_path(path)
    if entry is None:
        raise SpeedTuningError(f"{path} is not in the game archives.")
    path = _normal(entry.path)
    if not is_editable_action_chart_path(path):
        raise SpeedTuningError(f"{path} is not an editable action chart.")
    data = read(entry)
    chart = load_editable_chart(data, path)
    factors = SpeedFactors()
    mod = ""
    if mod_folder:
        found = _mod_factors(Path(mod_folder), path, data)
        if found is not None:
            factors, mod = found, Path(mod_folder).name
    moves = tuple(sorted(
        (SpeedMove(m["clip"], m["label"], m["kind"], m["entries"], m["windows"], m["seconds"],
                   factors.window_factor(m["clip"], m["kind"])) for m in _moves(chart, data).values()),
        key=lambda move: (list(KIND_LABELS).index(move.kind), move.label.lower())))
    root = getattr(index, "root", None)
    return SpeedChart(path, chart_label(path), float(chart_rate_row(chart).value), moves, factors, mod,
                      served_by(root, path) if root else "")


def served_by(game_root: Optional[Path | str], path: str) -> str:
    """The mounted DMM mod that serves this chart instead of the game's copy, if any.

    Read from DMM's runtime list, bin64/dmm/manifest.tsv ("file<TAB>path<TAB>source").
    """

    if not game_root:
        return ""
    manifest = Path(game_root) / "bin64" / "dmm" / "manifest.tsv"
    wanted = _normal(path).lower()
    try:
        lines = manifest.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in lines:
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] == "file" and _normal(parts[1]).lower() == wanted:
            source = parts[2].replace("\\", "/")
            marker = source.lower().find("/mods/")
            if marker < 0:
                return "a DMM mod"
            rest = source[marker + 6:].split("/")
            # "Mod/Option/actionchart/..." -> "Mod / Option" (DMM's option folders)
            if len(rest) < 3 or rest[1].lower() == "actionchart":
                return rest[0]
            return rest[0] + " / " + rest[1]
    return ""


# --- linked charts ------------------------------------------------------------------


def linked_sets(
    index: ChartArchiveIndex,
    read: Callable[[ArchiveEntry], bytes],
    path: str,
    *,
    stop_event: Optional[threading.Event] = None,
) -> tuple[tuple[str, bool], ...]:
    """Other charts that play this set's clips: (path, included by this set).

    A move can play from another chart, such as dual swords' idle from
    dualweapon_upper, so a change to one chart alone can show nothing in game.
    """

    entry = index.entry_for_path(path)
    if entry is None:
        return ()
    path = _normal(entry.path)
    data = read(entry)
    chart = load_editable_chart(data, path)
    scan = chart_scan(index, read, stop_event=stop_event)
    included = {item.lower() for item in included_charts(scan.includes, path)}
    found: dict[str, str] = {}
    for clip in _clip_names(chart, data).values():
        for use in scan.clip_uses.get(clip.lower(), ()):
            if use.chart.lower() != path.lower():
                found.setdefault(use.chart.lower(), use.chart)
    return tuple(sorted(((other, key in included) for key, other in found.items()),
                        key=lambda item: (not item[1], item[0].lower())))


# --- planning -----------------------------------------------------------------------


def _clip_factors(chart: ActionChart, data: bytes, factors: SpeedFactors) -> dict[str, float]:
    """clip (lower case) -> window factor, for every clip of the chosen set that changes."""

    resolved = {}
    for key, move in _moves(chart, data).items():
        value = factors.window_factor(move["clip"], move["kind"])
        if not _unit(value):
            resolved[key] = value
    return resolved


def plan_speed_edits(
    data: bytes,
    path: str,
    factors: SpeedFactors,
    *,
    clip_factors: Optional[Mapping[str, float]] = None,
    scale_rate: bool = True,
) -> SpeedPlan:
    """The value edits `factors` make to one chart, applied and read back.

    `clip_factors` (clip, lower case -> factor) replaces the move and kind rule: a
    linked chart takes the chosen set's resolved factors by clip, so only the set's own
    moves change there, and its ActionSpeedRate stays (`scale_rate` False).
    """

    check_factors(factors)
    path = _normal(path)
    chart = load_editable_chart(data, path)
    names = _clip_names(chart, data)
    per_clip = dict(clip_factors) if clip_factors is not None else _clip_factors(chart, data, factors)
    edits: list[ChartValueEdit] = []
    summary: dict[str, list[tuple[float, float]]] = {}
    skipped = 0
    for animation in chart.animations:
        clip = names.get(animation.clip_index, "")
        factor = per_clip.get(clip.lower())
        if factor is None or _unit(factor):
            continue
        kind = kind_of(clip)
        group = NAMED_KIND if factors.factor_source(clip, kind)[0] == NAMED_KIND else kind
        for row in _speed_rows(chart, data, animation.index):
            if not float(row.value) > 0:
                skipped += 1  # shipped at 0: any factor leaves it at 0, and a chart refuses a rate of 0
                continue
            new = float(row.value) * float(factor)
            if new > MAX_RATE:
                raise SpeedTuningError(
                    f"{path}: {PurePosixPath(clip).name} would get a speed rate of {new:g}; a chart holds at "
                    f"most {MAX_RATE:g}. Use a smaller factor.")
            edits.append(ChartValueEdit("speed.rate", new, animation.index, row.item))
            summary.setdefault(group, []).append((float(row.value), new))
    rate = float(chart_rate_row(chart).value)
    rate_after = rate
    if scale_rate and not _unit(factors.set):
        rate_after = rate * float(factors.set)
        edits.append(ChartValueEdit("chart.action_speed_rate", rate_after))
    request = ActionChartEditRequest(values=tuple(edits))
    if request.empty:
        return SpeedPlan(path, request, bytes(data), 0, (), rate, rate, skipped)
    try:
        result = apply_action_chart_edits(data, request, virtual_path=path)
    except ActionChartError as exc:
        raise SpeedTuningError(f"{path}: {exc}") from exc
    kinds = tuple(
        KindSummary(kind, label, len(values), (min(v[0] for v in values), max(v[0] for v in values)),
                    (min(v[1] for v in values), max(v[1] for v in values)))
        for kind, label in (*KIND_LABELS.items(), (NAMED_KIND, NAMED_LABEL)) if (values := summary.get(kind)))
    return SpeedPlan(path, request, result.data, result.changes.count, kinds, rate, rate_after, skipped)


def plan_speed_set(
    index: ChartArchiveIndex,
    read: Callable[[ArchiveEntry], bytes],
    path: str,
    factors: SpeedFactors,
    *,
    linked: Iterable[str] = (),
) -> tuple[SpeedPlan, ...]:
    """Plans for the set and for each linked chart, which takes the set's moves' factors."""

    entry = index.entry_for_path(path)
    if entry is None:
        raise SpeedTuningError(f"{path} is not in the game archives.")
    path = _normal(entry.path)
    data = read(entry)
    plans = [plan_speed_edits(data, path, factors)]
    clips = _clip_factors(load_editable_chart(data, path), data, factors)
    for other in dict.fromkeys(_normal(item) for item in linked):
        if other.lower() == path.lower():
            continue
        other_entry = index.entry_for_path(other)
        if other_entry is None:
            raise SpeedTuningError(f"{other} is not in the game archives.")
        plans.append(plan_speed_edits(read(other_entry), _normal(other_entry.path), factors,
                                      clip_factors=clips, scale_rate=False))
    return tuple(plans)


# --- export -------------------------------------------------------------------------


def _read_manifest(folder: Path) -> dict:
    try:
        value = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _saved_factors(folder: Path) -> dict[str, dict]:
    saved = _read_manifest(folder).get(MANIFEST_KEY) or {}
    charts = saved.get("charts") if isinstance(saved, dict) else None
    return dict(charts) if isinstance(charts, dict) else {}


def _mark(folder: Path, factors_by_chart: Mapping[str, dict]) -> None:
    manifest = _read_manifest(folder)
    if not manifest:
        return
    manifest[MANIFEST_KEY] = {"note": SPEED_GENERATOR_NOTE, "charts": dict(sorted(factors_by_chart.items()))}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def export_speed_mod(
    index: ChartArchiveIndex,
    read: Callable[[ArchiveEntry], bytes],
    path: str,
    factors: SpeedFactors,
    *,
    parent: Path | str,
    title: str,
    author: str = "",
    version: str = "1.0",
    description: str = "",
    linked: Iterable[str] = (),
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> SpeedExportResult:
    """Write or update the DMM mod `title` under `parent` with this set at `factors`.

    Other charts the mod already holds stay, so one mod can carry several sets. A set
    whose factors are all 1 leaves the mod (with its linked charts); when nothing is left
    the mod folder CDMW wrote is removed. The game archives are only read.
    """

    title = str(title or "").strip()
    if not title or len(title) > 120:
        raise SpeedTuningError("Name the mod (at most 120 characters).")
    parent = Path(parent)
    folder, replaced = mod_destination(parent, title)
    saved = _saved_factors(folder) if replaced else {}
    own_entry = index.entry_for_path(path)
    own_key = _normal(own_entry.path if own_entry is not None else path).lower()
    # A linked chart the mod already holds as a set of its own keeps its own factors: a plan
    # starts from the game's chart, so writing it as a linked chart would undo them.
    sets_of_their_own = {chart.lower() for chart, value in saved.items() if _own_factors(value)} - {own_key}
    kept = tuple(dict.fromkeys(_normal(item) for item in linked if _normal(item).lower() in sets_of_their_own))
    plans = plan_speed_set(index, read, path, factors,
                           linked=[item for item in linked if _normal(item).lower() not in sets_of_their_own])
    own = plans[0].path
    if factors.is_identity:
        # Only this set: `_remove_charts` adds the charts saved as linked to it.
        return _remove_charts(index, read, folder, title, {own}, saved,
                              author=author, version=version, description=description, on_log=on_log)
    description = str(description or "").strip() or (
        f"Speed Tuning (experimental) for {chart_label(own)}: " + _describe(factors))
    result = None
    changed = 0
    written = [plan for plan in plans if not plan.empty]
    if not written:
        raise SpeedTuningError("These factors change no speed value in this set.")
    for plan in written:
        entry = index.entry_for_path(plan.path)
        result = write_action_chart_mod(
            entry, read(entry), plan.edited, parent=parent, title=title, description=description, author=author,
            version=version, keep_existing=True, shipped_entries=index.entry_for_path, read_shipped=read,
            on_log=on_log, stop_event=stop_event)
        changed += plan.changed_values
    saved[own] = factors.to_data()
    for plan in written[1:]:
        saved[plan.path] = {"linked_to": own}
    _mark(result.folder, saved)
    return SpeedExportResult(result.folder, title, tuple(result.charts), changed, kept=kept)


def _describe(factors: SpeedFactors) -> str:
    parts = []
    if not _unit(factors.set):
        parts.append(f"whole set x{factors.set:g}")
    parts += [f"{KIND_LABELS[k].lower()} x{v:g}" for k, v in factors.kinds.items() if not _unit(v)]
    if factors.names_moves:
        parts.append(f"moves named {', '.join(factors.named)} x{factors.named_factor:g}")
    if any(not _unit(v) for v in factors.moves.values()):
        parts.append(f"{sum(1 for v in factors.moves.values() if not _unit(v))} move(s) set one by one")
    return ", ".join(parts) or "no change"


def _remove_charts(index, read, folder: Path, title: str, paths: set[str], saved: dict, *,
                   author: str, version: str, description: str, on_log) -> SpeedExportResult:
    if not folder.is_dir() or not is_chart_mod(folder):
        return SpeedExportResult(None, title, (), 0)
    mod = read_chart_mod(folder)
    drop = {path.lower() for path in paths}
    drop |= {chart.lower() for chart, value in saved.items()
             if isinstance(value, dict) and str(value.get("linked_to", "")).lower() in drop}
    others = {chart: data for chart, data in mod.charts.items() if chart.lower() not in drop}
    removed = tuple(sorted(chart for chart in mod.charts if chart.lower() in drop))
    if not removed:
        return SpeedExportResult(folder, title, tuple(sorted(mod.charts)), 0)
    if not others:
        # Only Speed Tuning's own charts were in this CDMW mod; nothing is left to ship.
        shutil.rmtree(folder)
        return SpeedExportResult(None, title, (), 0, removed)
    result = None
    for number, (chart, data) in enumerate(sorted(others.items())):
        entry = index.entry_for_path(chart)
        if entry is None:
            raise SpeedTuningError(f"{chart} is not in the game archives.")
        result = write_action_chart_mod(
            entry, read(entry), data, parent=folder.parent, title=title,
            description=description or mod.description, author=author or mod.author, version=version or mod.version,
            keep_existing=number > 0, shipped_entries=index.entry_for_path, read_shipped=read, on_log=on_log)
    _mark(result.folder, {chart: value for chart, value in saved.items() if chart.lower() not in drop})
    return SpeedExportResult(result.folder, title, tuple(result.charts), 0, removed)


# --- many sets at once --------------------------------------------------------------

WHOLE_SET_ONE_AT_A_TIME = ("The whole-set factor works on one set at a time. Put it back to 1x to change "
                           "several sets.")
EDITED_OUTSIDE = "It is in this mod with changes made outside Speed & Prefabs, so it was left as it is."


def plan_speed_profile(
    index: ChartArchiveIndex,
    read: Callable[[ArchiveEntry], bytes],
    paths: Iterable[str],
    factors: SpeedFactors,
    *,
    includes: Optional[Mapping[str, Sequence[str]]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> SpeedProfilePlan:
    """Check one set of factors on many charts: which change, which do not, which cannot.

    Each chart is read once and planned on its own with the kind, Moves named and move
    factors; its ActionSpeedRate stays, so the whole-set factor is refused here (a set
    and a chart it includes would both scale it, and whether that compounds in game is
    not known). With `includes`, the charts each path includes are checked too. A chart
    that cannot be planned is left out with its reason instead of failing the rest.
    """

    check_factors(factors)
    if not _unit(factors.set):
        raise SpeedTuningError(WHOLE_SET_ONE_AT_A_TIME)
    wanted: dict[str, str] = {}
    for path in paths:
        path = _normal(path)
        if not path:
            continue
        wanted.setdefault(path.lower(), path)
        if includes is not None:
            for other in included_charts(includes, path):
                wanted.setdefault(_normal(other).lower(), _normal(other))
    plans: list[SpeedPlan] = []
    unchanged: list[str] = []
    left_out: list[tuple[str, str]] = []
    for number, path in enumerate(wanted.values()):
        raise_if_cancelled(stop_event, "Checking the sets was cancelled.")
        if on_progress is not None:
            on_progress(number, len(wanted), path)
        entry = index.entry_for_path(path)
        if entry is None:
            left_out.append((path, "It is not in the game archives."))
            continue
        path = _normal(entry.path)
        if not is_editable_action_chart_path(path):
            left_out.append((path, "It is not an editable action chart."))
            continue
        try:
            plan = plan_speed_edits(read(entry), path, factors, scale_rate=False)
        except (ActionChartError, OSError, ValueError) as exc:
            reason = str(exc)
            left_out.append((path, reason[len(path) + 2:] if reason.startswith(path + ": ") else reason))
            continue
        if plan.empty:
            unchanged.append(path)
        else:
            plans.append(plan)
    if on_progress is not None:
        on_progress(len(wanted), len(wanted), "")
    return SpeedProfilePlan(tuple(plans), tuple(unchanged), tuple(left_out))


@dataclass(frozen=True, slots=True)
class SpeedProfileOutcome:
    """What a many-set export would do to the mod it is written into; nothing is written."""

    written: tuple[str, ...]                  # charts that get these factors
    removed: tuple[str, ...]                  # charts that leave the mod
    left_out: tuple[tuple[str, str], ...]     # (chart, the reason, for the user)
    stays: tuple[str, ...]                    # charts the mod holds that stay as they are


def _profile_layout(folder: Path, replaced: bool, plan: SpeedProfilePlan):
    """Which charts the mod holds after `plan` is written into it, and the saved factors that stay."""

    saved = {chart.lower(): (chart, value) for chart, value in (_saved_factors(folder) if replaced else {}).items()}
    held = dict(read_chart_mod(folder).charts) if replaced and is_chart_mod(folder) else {}
    changed = {item.path.lower(): item for item in plan.plans}
    scope = set(changed) | {path.lower() for path in plan.unchanged}
    left_out = list(plan.left_out)
    final: dict[str, tuple[str, bytes]] = {}
    marks: dict[str, object] = {}
    for chart, data in held.items():
        key = chart.lower()
        mark = saved.get(key, (chart, None))[1]
        if key in scope and mark is None:
            # Planning starts from the game's chart, so writing it would drop those other changes.
            changed.pop(key, None)
            left_out.append((chart, EDITED_OUTSIDE))
            final[key] = (chart, data)
        elif key in scope:
            continue  # replaced below when it changes, otherwise it leaves the mod
        elif isinstance(mark, Mapping) and str(mark.get("linked_to", "")).lower() in scope:
            continue  # changed together with a set that is now at these factors
        else:
            final[key] = (chart, data)
            if mark is not None:
                marks[chart] = mark
    for key, item in changed.items():
        final[key] = (item.path, item.edited)
    return final, marks, changed, held, left_out


def speed_profile_outcome(plan: SpeedProfilePlan, *, parent: Path | str, title: str) -> SpeedProfileOutcome:
    """What `export_speed_profile` would do with `plan` in the mod `title` under `parent`."""

    title = str(title or "").strip()
    if not title or len(title) > 120:
        raise SpeedTuningError("Name the mod (at most 120 characters).")
    folder, replaced = mod_destination(Path(parent), title)
    final, _marks, changed, held, left_out = _profile_layout(folder, replaced, plan)
    return SpeedProfileOutcome(
        tuple(item.path for item in changed.values()),
        tuple(sorted(chart for chart in held if chart.lower() not in final)),
        tuple(left_out),
        tuple(sorted(chart for chart in held if chart.lower() in final and chart.lower() not in changed)))


def export_speed_profile(
    index: ChartArchiveIndex,
    read: Callable[[ArchiveEntry], bytes],
    paths: Iterable[str],
    factors: SpeedFactors,
    *,
    parent: Path | str,
    title: str,
    author: str = "",
    version: str = "1.0",
    description: str = "",
    includes: Optional[Mapping[str, Sequence[str]]] = None,
    plan: Optional[SpeedProfilePlan] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> SpeedExportResult:
    """Write or update the DMM mod `title` so that every chart of `paths` is at `factors`.

    One build for all of them. A chart these factors change replaces its earlier version;
    a chart they change nothing in leaves the mod, as do the charts saved as linked to it;
    a chart that could not be planned, or that the mod holds with changes Speed & Prefabs
    did not make, stays as it is and is named in `left_out`. Charts outside `paths` stay.
    When nothing is left, the folder CDMW wrote is removed. `plan` hands over the plan the
    caller already showed. The game archives are only read.
    """

    title = str(title or "").strip()
    if not title or len(title) > 120:
        raise SpeedTuningError("Name the mod (at most 120 characters).")
    parent = Path(parent)
    folder, replaced = mod_destination(parent, title)
    paths = [_normal(path) for path in paths if _normal(path)]
    if plan is None:
        plan = plan_speed_profile(index, read, paths, factors, includes=includes, on_progress=on_progress,
                                  stop_event=stop_event)
    elif not _unit(factors.set):
        raise SpeedTuningError(WHOLE_SET_ONE_AT_A_TIME)
    final, marks, changed, held, left_out = _profile_layout(folder, replaced, plan)
    scope = {item.path.lower() for item in plan.plans} | {path.lower() for path in plan.unchanged}
    for item in changed.values():
        marks[item.path] = factors.to_data()
    removed = tuple(sorted(chart for chart in held if chart.lower() not in final))
    left = tuple(left_out)
    if not changed and not removed:
        # Nothing to write: the mod (if any) already is what these factors give.
        return SpeedExportResult(folder if replaced else None, title, tuple(sorted(held)), 0, left_out=left)
    if not final:
        shutil.rmtree(folder)
        return SpeedExportResult(None, title, (), 0, removed, left_out=left)
    charts = []
    for chart, data in sorted(final.values(), key=lambda item: item[0].lower()):
        entry = index.entry_for_path(chart)
        if entry is None:
            raise SpeedTuningError(f"{chart} is not in the game archives.")
        charts.append((entry, data))
    block: dict[str, object] = {"note": SPEED_GENERATOR_NOTE, "charts": dict(sorted(marks.items()))}
    if len(paths) > 1:
        block["profile"] = {"factors": factors.to_data(), "sets": sorted(dict.fromkeys(paths), key=str.lower)}
    if not str(description or "").strip():
        if len(changed) == 1 and len(scope) == 1:
            description = (f"Speed Tuning (experimental) for {chart_label(next(iter(changed.values())).path)}: "
                           + _describe(factors))
        else:
            description = f"Speed Tuning (experimental) for {len(changed)} sets: " + _describe(factors)
    result = write_action_charts_mod(charts, parent=parent, title=title, description=str(description).strip(),
                                     author=author, version=version, extra_manifest={MANIFEST_KEY: block},
                                     on_log=on_log, stop_event=stop_event)
    return SpeedExportResult(result.folder, title, tuple(result.charts),
                             sum(item.changed_values for item in changed.values()), removed, left_out=left)


def mod_speed_charts(folder: Path | str) -> dict[str, dict]:
    """The factors Speed Tuning saved in a mod, by chart path (empty for other mods)."""

    return _saved_factors(Path(folder))


# --- starting points and reopening a mod ----------------------------------------------


@dataclass(frozen=True, slots=True)
class SpeedPreset:
    """A starting point: kind and Moves named factors only, so it fits any set and many sets."""

    key: str
    label: str
    factors: Mapping[str, object]


#: Starting points, not tested values. The finisher name parts come from a scan of the
#: player charts (docs/crimson-desert-research.md, finisher animations).
SPEED_PRESETS: tuple[SpeedPreset, ...] = (
    SpeedPreset("faster_attacks", "Faster attacks (1.25x)", {"kinds": {"attack": 1.25}}),
    SpeedPreset("quick_draw", "Quicker draw and sheathe (1.5x)", {"kinds": {"draw": 1.5}}),
    SpeedPreset("snappier_dodges", "Snappier dodges (1.2x)", {"kinds": {"dodge": 1.2}}),
    SpeedPreset("slow_finishers", "Slow-motion finishers (0.5x)",
                {"named": {"texts": ["att_finish_link", "execute_lk", "takedown"], "factor": 0.5}}),
)


def speed_preset(key: str) -> SpeedFactors:
    for preset in SPEED_PRESETS:
        if preset.key == str(key):
            return SpeedFactors.from_data(preset.factors)
    raise SpeedTuningError(f"Unknown starting point {key!r}. Starting points are "
                           f"{', '.join(preset.key for preset in SPEED_PRESETS)}.")


@dataclass(frozen=True, slots=True)
class SpeedModSummary:
    """What a speed mod holds, for showing it again: one line and the saved factors per chart."""

    folder: Path
    title: str
    author: str
    version: str
    charts: Mapping[str, str]
    factors: Mapping[str, Optional[dict]]
    #: The block a many-set export saved (factors and sets), if any.
    profile: Optional[Mapping[str, object]]
    #: Some chart has no saved factors; they are worked out from its values when it is opened.
    derived: bool

    def to_data(self) -> dict[str, object]:
        return {"folder": str(self.folder), "title": self.title, "author": self.author, "version": self.version,
                "charts": [{"path": path, "summary": line, "factors": self.factors.get(path)}
                           for path, line in self.charts.items()],
                "profile": dict(self.profile) if self.profile else None, "derived": self.derived}


def speed_mod_summary(folder: Path | str, charts: Optional[Iterable[str]] = None) -> SpeedModSummary:
    """Read an action chart mod CDMW wrote as a speed mod; needs no game files.

    With `charts` (the paths an export just wrote) the mod's charts are not decoded again.
    """

    folder = Path(folder)
    manifest = _read_manifest(folder)
    if charts is None:
        mod = read_chart_mod(folder)
        paths, title, author, version = list(mod.charts), mod.title, mod.author, mod.version
    else:
        if not is_chart_mod(folder):
            raise SpeedTuningError(f"{folder.name} is not an action chart mod CDMW wrote.")
        paths = [_normal(chart) for chart in charts]
        title = str(manifest.get("title") or manifest.get("name") or folder.name)
        author, version = str(manifest.get("author") or ""), str(manifest.get("version") or "1.0")
    block = manifest.get(MANIFEST_KEY)
    block = block if isinstance(block, dict) else {}
    saved = {chart.lower(): value for chart, value in _saved_factors(folder).items()}
    lines: dict[str, str] = {}
    factors: dict[str, Optional[dict]] = {}
    derived = False
    for chart in sorted(paths, key=str.lower):
        value = saved.get(chart.lower())
        line, data = "", None
        if _own_factors(value):
            try:
                found = SpeedFactors.from_data(value)
                line, data = _describe(found), found.to_data()
            except (SpeedTuningError, TypeError, ValueError):
                pass
        elif isinstance(value, Mapping) and value.get("linked_to"):
            line = f"changed together with {chart_label(str(value['linked_to']))}"
        if not line:
            derived = True
            line = "factors not saved"
        lines[chart] = line
        factors[chart] = data
    profile = block.get("profile")
    return SpeedModSummary(folder, title, author, version, lines, factors,
                           profile if isinstance(profile, dict) else None, derived)


__all__ = [
    "CHARACTERS",
    "KINDS",
    "KIND_LABELS",
    "MANIFEST_KEY",
    "MAX_FACTOR",
    "MIN_FACTOR",
    "NAMED_KIND",
    "NAMED_LABEL",
    "KindSummary",
    "SpeedChart",
    "SpeedCharacter",
    "SPEED_PRESETS",
    "SpeedExportResult",
    "SpeedFactors",
    "SpeedModSummary",
    "SpeedMove",
    "SpeedPlan",
    "SpeedPreset",
    "SpeedProfileOutcome",
    "SpeedProfilePlan",
    "SpeedSet",
    "SpeedTuningError",
    "chart_label",
    "check_factor",
    "check_factors",
    "export_speed_mod",
    "export_speed_profile",
    "named_match",
    "named_texts",
    "plan_speed_profile",
    "speed_mod_summary",
    "speed_profile_outcome",
    "speed_preset",
    "factors_from_charts",
    "folder_sets",
    "kind_of",
    "linked_sets",
    "list_characters",
    "mod_speed_charts",
    "plan_speed_edits",
    "plan_speed_set",
    "read_speed_set",
    "served_by",
]
