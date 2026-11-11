"""List every wearable item of one body with what a bulk body swap would trip over. Read only.

For each item whose owned parts name the body (``phw`` Damiane, ``phm`` Kliff): its
equip type, owned parts and the PACs their prefabs name, whether an owned or borrowed
part is only in a DLC part table, whether an owned prefab has a bone-offset entry, the
tribe/gender selectors its prefabs are shown for (``player_1``/``player_3`` on Kliff's
own gear, ``player_2``/``player_5`` on Damiane's), and whether a PAC of the other body
with the same name (``phw`` <-> ``phm``) exists, which is the game's own version of the
piece for that body when its topology matches.

Example::

    python tools/refit_bulk_inventory.py --game-root "<Crimson Desert>" --body phw --output inventory.json
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BODY_TOKEN = re.compile(r"(?:^|_)(ph[mw]|ptm|ptw)_")
OTHER = {"phw": "phm", "phm": "phw"}


def body_of(stems) -> str:
    match = next((m for m in (BODY_TOKEN.search(s) for s in stems) if m), None)
    return match.group(1) if match else "other"


def twin_path(path: str, body: str) -> str:
    """The same PAC under the other body's folder and prefix (``2_phw``/``cd_phw_`` -> ``1_phm``/``cd_phm_``)."""
    other = OTHER[body]
    folders = {"phw": ("2_phw", "cd_m0001_02_phw"), "phm": ("1_phm", "cd_m0001_01_phm")}
    for mine, theirs in zip(folders[body], folders[other]):
        path = path.replace(f"/{mine}/", f"/{theirs}/")
    return path.replace(f"_{body}_", f"_{other}_")


def main() -> int:
    from cdmw.core.bone_offset_table import BONE_OFFSET_PATH, prefab_entry_names
    from cdmw.core.iteminfo_behavior import read_behavior_fields
    from cdmw.services.independent_item_package import stock_snapshot

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--body", choices=sorted(OTHER), default="phw")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    stock = stock_snapshot(args.game_root, on_log=lambda _m: None)
    snapshot_seconds = time.monotonic() - started
    keyed = {name.lower() for name in prefab_entry_names(stock.payload(BONE_OFFSET_PATH))}
    base, combined = stock.pappt_base.index(), stock.pappt.index()
    items, unresolved, types = [], collections.Counter(), collections.Counter()
    for key, row in sorted(stock.rows.items()):
        equip = stock.equip_type_name(row)
        if not equip:
            continue
        try:
            family = stock.family(key)
        except Exception as error:  # noqa: BLE001 - counted, not fatal
            unresolved[type(error).__name__] += 1
            continue
        owned = [part.stem.lower() for part in family.owned_parts]
        if body_of(owned) != args.body:
            continue
        types[equip] += 1
        pacs = sorted({path for part in family.owned_parts for path in part.pac_paths})
        try:
            selectors = sorted({stock.stringinfo_texts.get(key, str(key)) for prefab in read_behavior_fields(row.raw)["prefabs"]
                                for key in prefab["tribe_genders"]})
        except Exception:  # noqa: BLE001 - an unreadable layout is reported, not fatal
            selectors = None
        items.append({
            "item_key": int(key), "string_key": row.string_key, "equip_type": equip,
            "model_stem": family.model_stem, "owned_parts": owned,
            "borrowed_parts": [part.stem.lower() for part in family.borrowed_parts],
            "pacs": pacs, "tribe_genders": selectors,
            "twins": {path: twin_path(path, args.body) for path in pacs
                      if twin_path(path, args.body) != path and stock.has_entry(twin_path(path, args.body))},
            "owned_dlc_only": [s for s in owned if s in combined and s not in base],
            "borrowed_dlc_only": [p.stem for p in family.borrowed_parts if p.stem in combined and p.stem not in base],
            "bone_offset_entry": [s for s in owned if s in keyed],
        })
    report = {"body": args.body, "snapshot_seconds": snapshot_seconds, "items": len(items),
              "equip_types": dict(types.most_common()), "unresolved_families": dict(unresolved), "rows": items}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=1))
    print(f"elapsed {time.monotonic() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
