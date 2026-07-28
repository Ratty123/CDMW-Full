"""Group the prefab walk failures by cause, with how far each one got.

45.6% of shipped prefabs do not walk to completion. Quoted as one number that
looks like a single unsolved problem; it is five, none of them a majority, and
they are not equally close to solved. A cause that consistently stops at 95% of
the data section is a different proposition from one that stops at 20%.

This exists so the next attempt targets the largest real cause rather than the
whole percentage, and so the figures in
``docs/features/prefab-structural-decoding.md`` can be re-derived rather than
trusted.

Usage:
    python scripts/prefab_walk_failure_census.py --corpus <dir>

Game archives are read-only inputs and are never committed, so the corpus
directory is supplied rather than assumed.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from cdmw.core.prefab_binary import PrefabBinaryError, decode_prefab_binary  # noqa: E402

_HEX = re.compile(r"0x[0-9a-f]+")
_NUM = re.compile(r"\b\d+\b")


def cause_of(note: str) -> str:
    """The message with its offsets and counts removed, so cases group."""
    return _NUM.sub("N", _HEX.sub("0x_", str(note or "")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=pathlib.Path)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    files = sorted(args.corpus.glob("*.prefab"))
    if args.limit:
        files = files[: args.limit]

    counts: collections.Counter[str] = collections.Counter()
    progress: dict[str, list[float]] = collections.defaultdict(list)
    objects: dict[str, list[int]] = collections.defaultdict(list)
    header_failures = 0
    total = complete = 0

    for path in files:
        total += 1
        try:
            document = decode_prefab_binary(path.read_bytes())
        except PrefabBinaryError:
            header_failures += 1
            continue
        if document.walk_complete:
            complete += 1
            continue
        cause = cause_of(document.walk_note)
        counts[cause] += 1
        progress[cause].append(document.walk_progress)
        objects[cause].append(len(document.objects))

    partial = sum(counts.values())
    print(f"prefabs                 : {total:,}")
    print(f"  header would not parse: {header_failures:,}")
    print(f"  walked to completion  : {complete:,} ({100 * complete / max(1, total):.1f}%)")
    print(f"  stopped part way      : {partial:,} ({100 * partial / max(1, total):.1f}%)")
    print("\nby cause, with how far through the data section it got:")
    print(f"  {'files':>6}  {'share':>6}  {'median':>7}  {'p90':>6}  {'objs':>5}  cause")
    for cause, count in counts.most_common():
        runs = sorted(progress[cause])
        median = runs[len(runs) // 2]
        p90 = runs[int(len(runs) * 0.9)]
        print(
            f"  {count:>6,}  {100 * count / partial:>5.1f}%  {median:>6.0%}  "
            f"{p90:>5.0%}  {statistics.median(objects[cause]):>5.0f}  {cause[:58]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
