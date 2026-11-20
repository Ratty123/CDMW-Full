"""Which prefab speed values the prefab walk reaches, per (component type, member).

Speed Tuning (experimental) offers only catalogue members the walk actually reaches
(`cdmw/domain/archives/prefab_speed.py`). This re-derives that list from a folder of
extracted prefabs, so the catalogue's figures can be checked rather than trusted.

Run on 2026-11-20 against all 51,178 prefabs of the installed game (CDMW at b14d1ce):
speed-named members appear in 519 files, none failed to decode and 411 walks completed.
Reached: CameraComponent._speed (4 files, 6 values), VelocityComponent._angularVelocity
(70 files, 141 values), WindComponent._windSpeedAccelerationScale (7, 7) and three
CloudDensityVolumeComponent flow and swirl speeds (2 to 3 files each). Not reached in any
file: every emitter speed and velocity (68 files declare them; 61 walks stop early and
the other 7 never reach an emitter), VelocityComponent._linearVelocity,
NPCScheduleSplineDataAttribute._speedLimit, WeatherConstant._windSpeed and
ScenePostProcessing's exposure speeds.

Usage:
    python scripts/prefab_speed_census.py --corpus <dir of .prefab files> [--limit N]

Game archives are read-only inputs and are never committed, so the corpus folder is
supplied rather than assumed.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from cdmw.core.prefab_binary import PrefabBinaryError, decode_prefab_binary  # noqa: E402
from cdmw.domain.archives.prefab_speed import SPEED_MEMBERS  # noqa: E402

_SPEEDY = re.compile(r"speed|velocity|acceleration", re.IGNORECASE)


def census(files):
    declared = collections.Counter()
    reached_files = collections.Counter()
    reached_values = collections.Counter()
    walked = failed = 0
    for path in files:
        data = path.read_bytes()
        if not _SPEEDY.search(data.decode("latin-1")):
            continue
        try:
            document = decode_prefab_binary(data)
        except PrefabBinaryError:
            failed += 1
            continue
        walked += document.walk_complete
        for prefab_type in document.types:
            for member in prefab_type.members:
                if _SPEEDY.search(member.name):
                    declared[(prefab_type.type_name, member.name)] += 1
        seen = set()
        for obj in document.objects:
            for number in obj.numbers:
                if _SPEEDY.search(number.name):
                    key = (obj.component_type, number.name)
                    reached_values[key] += 1
                    seen.add(key)
        for key in seen:
            reached_files[key] += 1
    return declared, reached_files, reached_values, walked, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=pathlib.Path)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    files = sorted(args.corpus.rglob("*.prefab"))
    if args.limit:
        files = files[:args.limit]
    declared, files_reached, values, walked, failed = census(files)
    print(f"{len(files)} prefabs; {walked} complete walks among speed-named files; {failed} failed to decode")
    print("type\tmember\tdeclared_in\treached_in\tvalues\tin_catalogue")
    for key in sorted(set(declared) | set(files_reached)):
        print(f"{key[0]}\t{key[1]}\t{declared.get(key, 0)}\t{files_reached.get(key, 0)}\t{values.get(key, 0)}"
              f"\t{'yes' if key in SPEED_MEMBERS else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
