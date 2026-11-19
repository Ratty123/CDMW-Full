"""Suggest where a game patch changed the compact ItemInfo row layout.

Developer diagnostic, read-only. When no known ItemInfo generation decodes a
patched table, this tries one added field at a time (1, 2, 4 or 8 bytes, or a
UTF-8 string) after every ItemInfo field and inside every nested record reader,
keeps the change that decodes the most sampled rows, and repeats for up to
three changes.

The answer is a lead, not a layout. An added byte between fixed-width fields
decodes identically at every position in that run, so the report lists the
whole run; place the new field from the executable's field labels (they sit in
reverse field order beside the owner name), then add a named generation to
`cdmw/core/compact_static.py` with tests. The app never applies a probed layout.

    python tools/probe_iteminfo_layout.py --game "C:/games/Steam/steamapps/common/Crimson Desert"
    python tools/probe_iteminfo_layout.py --body iteminfo.staticinfobody --header iteminfo.staticinfoheader
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core import compact_static as cs  # noqa: E402
from cdmw.core.new_item_record import RecordError  # noqa: E402

_INSERTS = (("raw", 1), ("raw", 2), ("raw", 4), ("raw", 8), ("text",))
_NESTED_INSERTS = (("raw", 1), ("raw", 4))


@dataclass(frozen=True)
class Change:
    reader: tuple | None  # (reader id, path to its field sequence); None: the ItemInfo row
    after: str  # field the new one follows; "" for the first position
    op: tuple

    def describe(self) -> str:
        where = "ItemInfo" if self.reader is None else f"reader {self.reader[0]}"
        size = "string" if self.op[0] == "text" else f"{self.op[1]}-byte"
        return f"{size} field in {where} after {self.after or '(start)'}"


def _decodes(raw, program, readers) -> bool:
    saved = cs.READERS
    cs.READERS = readers
    try:
        cs._read_compact_layout(raw, "iteminfo", program)
        return True
    except (RecordError, UnicodeError):
        return False
    finally:
        cs.READERS = saved


def _fields(seq):
    return [i for i, op in enumerate(seq) if isinstance(op, tuple) and op[0] == "field"]


def _record_seqs(program, readers):
    """(reader id, path) of every field sequence inside readers reachable from `program`."""
    found, stack, seen = [], [program], set()

    def visit(reader, op, path):
        if not isinstance(op, tuple):
            return
        if op and op[0] == "seq" and _fields(op[1:]):
            found.append((reader, path))
        for index, child in enumerate(op):
            if isinstance(child, tuple):
                visit(reader, child, path + (index,))

    while stack:
        text = repr(stack.pop())
        for number in map(int, re.findall(r"\('(?:call|optional)', (\d+)\)", text)):
            if number in seen:
                continue
            seen.add(number)
            visit(number, readers[number], ())
            stack.append(readers[number])
    return found


def _at(op, path):
    for index in path:
        op = op[index]
    return op


def _replace(op, path, value):
    if not path:
        return value
    head = path[0]
    return (*op[:head], _replace(op[head], path[1:], value), *op[head + 1:])


def _apply(program, readers, change):
    new = ("field", "Probe", "_probed", change.op)

    def insert(seq):
        at = 1 if not change.after else next(i + 1 for i in _fields(seq) if seq[i][2] == change.after)
        return (*seq[:at], new, *seq[at:])

    if change.reader is None:
        return insert(program), readers
    reader, path = change.reader
    patched = list(readers)
    patched[reader] = _replace(readers[reader], path, insert(_at(readers[reader], path)))
    return program, tuple(patched)


def _candidates(program, readers, nested):
    names = [""] + [program[i][2] for i in _fields(program)]
    for name in names:
        for op in _INSERTS:
            yield Change(None, name, op)
    if nested:
        for reader, path in _record_seqs(program, readers):
            body = _at(readers[reader], path)
            for name in [""] + [body[i][2] for i in _fields(body)]:
                for op in _NESTED_INSERTS:
                    yield Change((reader, path), name, op)


def probe(rows, *, sample=200, rounds=3, seed=0):
    """Return (known generation scores, [(changes so far, decoded, ties)], sampled row count)."""
    rows = list(rows)
    picked = random.Random(seed).sample(rows, min(sample, len(rows)))
    known = {label: sum(_decodes(raw, program, cs.READERS) for raw in picked)
             for label, program in cs.ITEMINFO_GENERATIONS}
    program, readers = cs.ITEMINFO_GENERATIONS[-1][1], cs.READERS
    best_score = known[cs.ITEMINFO_GENERATIONS[-1][0]]
    steps = []
    for _round in range(rounds):
        if best_score == len(picked):
            break
        scored = []
        for nested in (False, True):
            for change in _candidates(program, readers, nested):
                trial = _apply(program, readers, change)
                score = sum(_decodes(raw, *trial) for raw in picked)
                if score > best_score:
                    scored.append((score, change))
            if scored and max(s for s, _ in scored) == len(picked):
                break
        if not scored:
            break
        top = max(s for s, _ in scored)
        ties = [c for s, c in scored if s == top]
        program, readers = _apply(program, readers, ties[0])
        best_score = top
        steps.append((ties[0], top, ties))
    return known, steps, len(picked)


def _game_rows(args):
    from cdmw.core.structured_binary_editor import parse_pabgh_table

    if args.game:
        from cdmw.core.archive_extraction import read_archive_entry_data
        from cdmw.core.item_sources import resolve_item_data_sources
        from tools.placement_studio import corpus

        entries = [entry for _package, entry in corpus._iter_archive_entries(Path(args.game))
                   if corpus.normalize_game_path(entry.path).startswith("gamedata/")]
        read = lambda entry: bytes(read_archive_entry_data(entry)[0])  # noqa: E731
        pair = resolve_item_data_sources(entries, read_entry=read).tables["iteminfo"]
        body = next(read(e) for e in pair if e.path.endswith("body"))
        header = next(read(e) for e in pair if e.path.endswith("header"))
    else:
        body, header = Path(args.body).read_bytes(), Path(args.header).read_bytes()
    spans = parse_pabgh_table(header, payload=body).row_spans(len(body))
    return [body[start:end] for _row, start, end in spans]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--game", help="installed game folder (read-only)")
    source.add_argument("--body", help="an extracted iteminfo.staticinfobody")
    parser.add_argument("--header", help="the matching iteminfo.staticinfoheader (with --body)")
    parser.add_argument("--sample", type=int, default=200, help="rows to test each guess on")
    args = parser.parse_args(argv)
    if args.body and not args.header:
        parser.error("--body needs --header")
    known, steps, sampled = probe(_game_rows(args), sample=args.sample)
    print(f"Sampled {sampled} rows.")
    for label, score in known.items():
        print(f"  known layout {label}: {score} decode")
    if any(score == sampled for score in known.values()):
        print("A known layout already decodes every sampled row.")
        return 0
    for number, (change, score, ties) in enumerate(steps, 1):
        print(f"Change {number}: {score}/{sampled} rows decode with a {change.describe()}.")
        if len(ties) > 1:
            print(f"  {len(ties)} positions decode the same; any of:")
            for tie in ties:
                print(f"    {tie.describe()}")
    if not steps or steps[-1][1] != sampled:
        print("No combination of up to three added fields decodes every sampled row.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
