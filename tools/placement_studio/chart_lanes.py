"""Where an animation is actually used, read from the action charts.

The alternative was reading the clip's own file name, and that is guesswork dressed as fact.
It put `cd_prh_swd_01_01_nor_std_weapon_out_00` under "standing still" because the name
contains `nor_std` — while the charts say plainly that the clip belongs to
`ride_weapon_upper.paac`, which is the mounted set. It also called `sit_std` clips horseback
when `sword_upper.paac` names them, an ordinary on-foot chart.

A chart is the game's own statement of when a clip plays, and its file name says which
situation it covers: `basic_lower_crouch`, `basic_lower_swim`, `ride_weapon_upper`. So the
lane is looked up rather than inferred, and where no chart names a clip the filename remains
the fallback — labelled as such rather than presented as if it were known.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Tuple

#: Chart-name fragment -> the situation it covers, most specific first.
#:
#: Deliberately few. One lane per thing a modder would recognise; charts that describe a
#: *weapon* rather than a situation (`sword_upper`, `twohandsword_upper`) are absent on
#: purpose, because the weapon is already the row and repeating it would only add lanes.
SITUATIONS: Tuple[Tuple[str, str], ...] = (
    ("ride_weapon", "On horseback"),
    ("ride_bow", "On horseback"),
    ("ride_crossbow", "On horseback"),
    ("basic_lower_riding", "On horseback"),
    ("ride_carriage", "Driving a vehicle"),
    ("ride_canoe", "In a boat"),
    ("ride_cannon", "Operating a weapon"),
    ("ride_ballista", "Operating a weapon"),
    ("ride_giantcannon", "Operating a weapon"),
    ("ride_singijeon", "Operating a weapon"),
    ("ride_tank", "Operating a weapon"),
    ("ride_airballoon", "In the air"),
    ("ride_elephant", "Riding an animal"),
    ("crouch", "Crouching"),
    ("wallhide", "Crouching"),
    ("swim", "Swimming"),
    ("crawl", "Crawling"),
    ("ladder", "Climbing"),
    ("climb", "Climbing"),
    ("wallup", "Climbing"),
    ("thornyvine", "Climbing"),
    ("glide", "In the air"),
    ("slide", "Sliding"),
    ("slope", "Sliding"),
    ("camp", "At camp"),
    ("assassinate", "Assassinating"),
    ("hitaction", "Taking a hit"),
    ("torch", "Holding a torch"),
    ("pickup", "Picking something up"),
    ("interactive", "Interacting"),
)

_CACHE_VERSION = 1


def situation_of_chart(chart_name: str) -> str:
    """The lane one chart covers, or "" when it describes a weapon rather than a situation."""

    lowered = chart_name.lower()
    for fragment, lane in SITUATIONS:
        if fragment in lowered:
            return lane
    return ""


def _cache_file(model: str) -> Path:
    from .corpus import work_root

    return Path(work_root()) / f"chart-lanes-{model}.json"


def build(game_root, model: str, *, should_stop=None) -> Dict[str, str]:
    """clip stem -> the situation a chart puts it in.

    Scanning the package tables and reading the rig's ~100 charts takes a few seconds, so the
    result is cached exactly as the wearables index is.
    """

    from .animation_sets import chart_clips
    from .armour import read_entry
    from .corpus import _iter_archive_entries, normalize_game_path

    out: Dict[str, str] = {}
    for _package, entry in _iter_archive_entries(Path(game_root)):
        if should_stop is not None and should_stop():
            return {}
        path = normalize_game_path(entry.path)
        if not path.endswith(".paac") or model not in path:
            continue
        lane = situation_of_chart(path.rsplit("/", 1)[-1])
        if not lane:
            continue
        try:
            data = read_entry(entry)
        except Exception:  # noqa: BLE001 - a chart that will not read simply says nothing
            continue
        for stem in chart_clips(data):
            # First chart to claim a clip wins, and the table is ordered most specific first,
            # so a crouching draw is not relabelled by a chart that merely also mentions it.
            out.setdefault(stem, lane)
    return out


def load(game_root, model: str, *, should_stop=None) -> Dict[str, str]:
    """The cached index, building it once if there is none."""

    path = _cache_file(model)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("version") == _CACHE_VERSION and raw.get("lanes"):
            return dict(raw["lanes"])
    except (OSError, ValueError):
        pass
    lanes = build(game_root, model, should_stop=should_stop)
    if lanes:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"version": _CACHE_VERSION, "lanes": lanes}), encoding="utf-8"
            )
        except OSError:
            pass
    return lanes
