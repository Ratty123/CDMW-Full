"""Split the test suite into balanced shards that each run sequentially.

CI wall-clock was dominated by one sequential pytest run: 22 minutes of a 24
minute job, against roughly 9 on a developer machine, because a shared runner is
slower per core rather than short of cores.

Running the suite under `pytest-xdist` was measured at 2.25x, but four workers
load the machine on purpose, and the suite contains wall-clock budgets that
cannot survive that. Excluding those to buy the speedup trades verification for
time. Sharding buys the same wall-clock reduction without it: every shard is an
ordinary sequential run, so nothing about how a test executes changes, and the
cost is runner minutes rather than coverage.

Balance is by file size. It is a proxy for runtime rather than a measurement,
but it is stable, needs no stored timings, and a greedy longest-first packing
keeps the shards close enough that no one of them decides the wall clock.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def _test_files() -> list[Path]:
    """Every file pytest would collect, in a stable order."""

    return sorted(TESTS.rglob("test_*.py"))


def shard_files(shard: int, of: int) -> list[Path]:
    """The files belonging to one shard, packed longest-first.

    Sorting by descending size before packing keeps the largest files from
    landing together, which a round-robin over an alphabetical list does not:
    `test_mesh_service_editing.py` alone is larger than most shards' remainder.
    """

    if of < 1:
        raise ValueError("shard count must be at least 1")
    if not 1 <= shard <= of:
        raise ValueError(f"shard {shard} is outside 1..{of}")

    buckets: list[list[Path]] = [[] for _ in range(of)]
    weights = [0] * of
    for path in sorted(_test_files(), key=lambda item: (-item.stat().st_size, item.name)):
        index = weights.index(min(weights))
        buckets[index].append(path)
        weights[index] += path.stat().st_size
    return sorted(buckets[shard - 1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=int, required=True, help="1-based shard to print")
    parser.add_argument("--of", type=int, required=True, help="total number of shards")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="report the balance across every shard instead of printing one",
    )
    arguments = parser.parse_args()

    if arguments.summary:
        for index in range(1, arguments.of + 1):
            files = shard_files(index, arguments.of)
            total = sum(path.stat().st_size for path in files)
            print(f"shard {index}/{arguments.of}: {len(files):4} files, {total / 1024:8.0f} KiB")
        return 0

    for path in shard_files(arguments.shard, arguments.of):
        print(path.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
