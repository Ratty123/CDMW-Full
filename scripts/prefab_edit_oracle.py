"""Randomised edits over the shipped prefabs, judged by an oracle that shares no code
with the writers.

Why another check: the existing checks are round trips (rewrite and back,
duplicate and remove) plus the writers' own read-back. A round trip cannot see a
length field that both directions leave stale -- the two misses cancel -- and the
read-back only validates the length fields the walk itself records, about half of
them. This checks every byte of the result against the original instead.

For each operation the harness works out, independently of the writer:

* where every surviving byte of the original lands (copy segments);
* every pointer site's image, each of which must hold its own position + 4, and the
  set of pointer sites in the result must be exactly those images;
* every pointee's candidate length fields (any u32 equal to its distance from the
  pointee start, outside decoded strings, anywhere in the blob -- not the writer's
  8 KiB window). A pointee that encloses a change must have an enclosing candidate
  that holds its new length afterwards.

Any byte that differs from its original, other than a pointer, a length field
explained as above, the header sizes or a resized collection's count, is reported.

The corpus is a flat directory of ``.prefab`` files extracted read-only from the
installed game; game files are never committed, so it is supplied rather than
assumed. Failures and crashes go to ``--out`` as JSON lines with the edit that
produced them, so each one can be replayed.

Usage:
    python scripts/prefab_edit_oracle.py --corpus <dir> [--limit N] [--seed S] [--out failures.jsonl]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import sys
import time
import traceback
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cdmw.core.prefab_array_edit import (
    duplicate_prefab_element,
    remove_prefab_element,
)
from cdmw.core.prefab_binary import (
    PrefabBinaryError,
    decode_prefab_binary,
    walk_is_determined,
)
from cdmw.core.prefab_binary_edit import (
    PrefabEditError,
    PrefabPathEdit,
    rewrite_prefab_paths,
    rewrite_prefab_paths_any_length,
)

_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789_/"
# Reports where a nearer candidate ends before the change and a farther one
# encloses it. "resolved" ones were settled by the field the walk itself read and
# validated; "unresolved" ones the file does not settle.
AMBIGUOUS = {"resolved": 0, "unresolved": 0}


# --------------------------------------------------------------------------- oracle


def u32_array(data: bytes) -> np.ndarray:
    raw = np.frombuffer(data + b"\0\0\0", dtype=np.uint8).astype(np.int64)
    n = len(data)
    return raw[:n] | (raw[1 : n + 1] << 8) | (raw[2 : n + 2] << 16) | (raw[3 : n + 3] << 24)


def oracle_pointer_sites(data: bytes, blob_offset: int, blob_length: int) -> list[int]:
    values = u32_array(data)
    positions = np.arange(len(data), dtype=np.int64)
    end = min(len(data) - 3, blob_offset + blob_length - 3)
    window = slice(blob_offset, max(blob_offset, end))
    hits = np.nonzero(values[window] == positions[window] + 4)[0] + blob_offset
    return hits.tolist()


def string_mask(data: bytes, document) -> np.ndarray:
    mask = np.zeros(len(data) + 4, dtype=bool)
    for item in document.all_strings():
        start = item.offset
        stop = min(len(data), start + 4 + len(item.text.encode("utf-8")))
        if 0 <= start < stop:
            mask[start:stop] = True
    return mask


def candidates_by_target(data: bytes, document, targets: list[int]) -> dict[int, list[int]]:
    """Every position q in the blob whose u32 equals q - target, for each target."""
    if not targets:
        return {}
    values = u32_array(data)
    lo = document.blob_offset
    hi = min(len(data) - 3, document.blob_offset + document.blob_length - 3)
    q = np.arange(lo, max(lo, hi), dtype=np.int64)
    vals = values[lo : max(lo, hi)]
    keys = q - vals
    mask = string_mask(data, document)[lo : max(lo, hi)]
    usable = (vals >= 4) & ~mask
    wanted = np.isin(keys, np.asarray(targets, dtype=np.int64)) & usable
    found: dict[int, list[int]] = collections.defaultdict(list)
    for position, key in zip(q[wanted].tolist(), keys[wanted].tolist()):
        found[key].append(position)
    return found


class Mapping:
    """Where each surviving byte of the original lands, as copy segments."""

    def __init__(self, segments: list[tuple[int, int, int]]) -> None:
        # (p_start, p_end, r_start), may overlap in p (a duplicated block)
        self.segments = segments

    def images(self, p: int) -> list[int]:
        return [r + (p - a) for a, b, r in self.segments if a <= p < b]

    def images_span(self, p: int, width: int) -> list[int]:
        """Images of a whole span; a span split by a change has none."""
        return [r + (p - a) for a, b, r in self.segments if a <= p and p + width <= b]


def judge(
    original: bytes,
    before,
    result: bytes,
    mapping: Mapping,
    encloses,  # (target, field) -> bool, in original coordinates
    *,
    extra_allowed: set[int] = frozenset(),
    survives_pointee=lambda target: True,
) -> list[str]:
    """Problems with ``result``, or [] if every byte is explained."""
    problems: list[str] = []
    try:
        after = decode_prefab_binary(result)
    except PrefabBinaryError as exc:
        return [f"result does not decode: {exc}"]
    if not after.walk_complete:
        problems.append(f"result walk incomplete: {after.walk_note}")

    sites = oracle_pointer_sites(original, before.blob_offset, before.blob_length)
    expected_sites = sorted(image for site in sites for image in mapping.images_span(site, 4))
    actual_sites = oracle_pointer_sites(result, after.blob_offset, after.blob_length)
    if expected_sites != actual_sites:
        missing = sorted(set(expected_sites) - set(actual_sites))[:5]
        extra = sorted(set(actual_sites) - set(expected_sites))[:5]
        problems.append(f"pointer sites differ: missing {missing} extra {extra}")

    allowed: set[int] = set(extra_allowed)
    for site in expected_sites:
        allowed.update(range(site, site + 4))
    header = after.blob_offset - 28
    allowed.update(range(header + 4, header + 8))
    allowed.update(range(header + 24, header + 28))

    targets = [site + 4 for site in sites]
    candidates = candidates_by_target(original, before, targets)
    recorded_fields = dict(before.pointee_length_fields)
    result_values = u32_array(result)
    for site in sites:
        target = site + 4
        if not survives_pointee(target):
            continue
        fields = candidates.get(target, [])
        if not fields:
            continue
        enclosing = [q for q in fields if encloses(target, q)]
        if not enclosing:
            continue
        for t_image in mapping.images(target):
            holds = []
            for q in enclosing:
                for q_image in mapping.images_span(q, 4):
                    # Only the image belonging to the same copy of the pointee.
                    if q_image - t_image < 0 or q_image - t_image > len(result):
                        continue
                    if int(result_values[q_image]) == q_image - t_image:
                        holds.append(q_image)
                        allowed.update(range(q_image, q_image + 4))
            if holds:
                continue
            outside = [q for q in fields if q not in enclosing]
            kind = "ambiguous" if outside else "definite"
            recorded = recorded_fields.get(site)
            if outside and recorded is not None:
                if recorded in outside:
                    # The walk read this pointee's field before the change, so the
                    # farther candidates are coincidences.
                    AMBIGUOUS["resolved"] += 1
                    continue
                kind = "definite (recorded field)"
            elif outside:
                # A nearer candidate ends before the change, so the genuine field is
                # most likely that one and this is a coincidental far match.
                AMBIGUOUS["unresolved"] += 1
                continue
            problems.append(
                f"stale length ({kind}): pointee 0x{target:x} encloses a change; "
                f"candidates {[hex(q) for q in fields][:6]}"
            )

    out = np.frombuffer(result, dtype=np.uint8)
    src = np.frombuffer(original, dtype=np.uint8)
    for a, b, r in mapping.segments:
        n = b - a
        if r + n > len(out):
            problems.append(f"segment 0x{a:x}..0x{b:x} runs past the result")
            continue
        differing = np.nonzero(out[r : r + n] != src[a:b])[0]
        unexplained = [int(r + d) for d in differing.tolist() if int(r + d) not in allowed]
        if unexplained:
            problems.append(
                f"{len(unexplained)} unexplained byte change(s), first at result 0x{unexplained[0]:x}"
            )
    return problems


# ------------------------------------------------------------------- path edits


def random_text(rng: random.Random, old: str) -> str:
    old_len = len(old.encode("utf-8"))
    mode = rng.random()
    if mode < 0.2:
        length = rng.randint(1, 4)
    elif mode < 0.4:
        length = old_len + rng.randint(1, 300)
    elif mode < 0.55:
        length = max(1, old_len - rng.randint(1, max(1, old_len - 1)))
    elif mode < 0.65:
        length = old_len  # same length, different text
    elif mode < 0.75:
        length = max(1, old_len + rng.choice((-4, 4, -8, 8, 1, -1)))
    else:
        length = rng.randint(1, 120)
    text = "".join(rng.choices(_ALPHABET, k=length))
    if rng.random() < 0.1:
        text = text[:-1] + "åö"
    if text == old:
        text = "x" + text[1:] if text[0] != "x" else "y" + text[1:]
    return text


def path_mapping(original: bytes, edits) -> Mapping:
    segments = []
    cursor = shift = 0
    for edit in sorted(edits, key=lambda e: e.offset):
        old = len(edit.old_text.encode("utf-8"))
        new = len(edit.new_text.encode("utf-8"))
        segments.append((cursor, edit.offset, cursor + shift))
        cursor = edit.offset + 4 + old
        shift += new - old
    segments.append((cursor, len(original), cursor + shift))
    return Mapping([s for s in segments if s[1] > s[0]])


def path_encloses(edits):
    points = [edit.offset for edit in edits]
    return lambda target, field: any(target <= c < field + 4 for c in points)


def sequential(original: bytes, edits) -> bytes:
    """Apply the batch one edit at a time, each addressed in the current file."""
    current = original
    applied = []
    for edit in sorted(edits, key=lambda e: e.offset):
        shift = sum(
            len(e.new_text.encode("utf-8")) - len(e.old_text.encode("utf-8")) for e in applied
        )
        step = PrefabPathEdit(offset=edit.offset + shift, old_text=edit.old_text, new_text=edit.new_text)
        current = rewrite_prefab_paths(current, [step]).data
        applied.append(edit)
    return current


def fuzz_paths(rng, name, data, document, record) -> None:
    strings = list(document.all_strings())
    resources = {item.offset for item in document.resource_strings()}
    if not strings:
        return
    if rng.random() < 0.15:
        chosen = strings
    else:
        pool = [s for s in strings if s.offset in resources] if rng.random() < 0.7 else strings
        pool = pool or strings
        chosen = rng.sample(pool, rng.randint(1, min(len(pool), 6)))
    edits = [PrefabPathEdit(offset=s.offset, old_text=s.text, new_text=random_text(rng, s.text)) for s in chosen]
    try:
        result = rewrite_prefab_paths(data, edits)
    except PrefabEditError as exc:
        record["path"] = "refused"
        record["path_reason"] = refusal_class(str(exc))
        return
    problems = judge(data, document, result.data, path_mapping(data, edits), path_encloses(edits))
    # Undo: every edit reversed must restore the original exactly.
    after = decode_prefab_binary(result.data)
    moved = {item.offset: item for item in after.all_strings()}
    mapping = path_mapping(data, edits)
    back = []
    shift = 0
    for edit in sorted(edits, key=lambda e: e.offset):
        at = edit.offset + shift
        back.append(PrefabPathEdit(offset=at, old_text=edit.new_text, new_text=edit.old_text))
        shift += len(edit.new_text.encode("utf-8")) - len(edit.old_text.encode("utf-8"))
        if at not in moved or moved[at].text != edit.new_text:
            problems.append(f"edited string not found at 0x{at:x} in the result")
    if any(not edit.old_text for edit in edits):
        # An empty replacement means "leave it" to the rewriter, so a string that
        # started empty cannot be written back empty; skip the undo, not the edit.
        record["undo_skipped"] = "empty original"
    elif not problems:
        try:
            restored = rewrite_prefab_paths(result.data, back).data
            if restored != data:
                problems.append("undo did not restore the original bytes")
        except PrefabEditError as exc:
            record["undo_refused"] = refusal_class(str(exc))
    if len(edits) > 1 and not problems:
        try:
            if sequential(data, edits) != result.data:
                problems.append("one-at-a-time result differs from the batch")
        except PrefabEditError as exc:
            record["sequential_refused"] = refusal_class(str(exc))
    record["path"] = "fail" if problems else "ok"
    record["path_edits"] = len(edits)
    record["path_delta"] = result.byte_delta
    if problems:
        record["path_problems"] = problems[:8]
        record["path_edit_list"] = [(e.offset, e.old_text, e.new_text) for e in edits]
    del mapping


# ---------------------------------------------------------------------- resizes


def fuzz_resize(rng, name, data, document, record) -> None:
    usable = [
        (index, item) for index, item in enumerate(document.collections)
        if item.elements and len(item.elements) == item.count
    ]
    if not usable:
        return
    index, collection = rng.choice(usable)
    element = rng.randrange(len(collection.elements))
    from cdmw.core.prefab_array_edit import _element_span
    start, end = _element_span(data, document, index, element)
    insert = rng.random() < 0.6 or collection.count <= 1
    try:
        if insert:
            result = duplicate_prefab_element(data, index, element)
        else:
            result = remove_prefab_element(data, index, element)
    except PrefabEditError as exc:
        record["resize"] = "refused"
        record["resize_reason"] = refusal_class(str(exc))
        return
    length = end - start
    count_at = collection.count_offset
    if insert:
        mapping = Mapping([(0, end, 0), (start, end, end), (end, len(data), end + length)])
        def encloses(target, field):
            return target < end < field + 4
        survives = lambda target: True
    else:
        mapping = Mapping([s for s in [(0, start, 0), (end, len(data), start)] if s[1] > s[0]])
        def encloses(target, field):
            return target < start < field + 4
        survives = lambda target: not (start <= target < end)
    allowed = set(range(count_at, count_at + 4))
    problems = judge(
        data, document, result.data, mapping, encloses,
        extra_allowed=allowed, survives_pointee=survives,
    )
    if insert and not problems:
        try:
            back = remove_prefab_element(result.data, index, element + 1).data
            if back != data:
                problems.append("removing the duplicate did not restore the original")
        except PrefabEditError as exc:
            record["resize_undo_refused"] = refusal_class(str(exc))
        # Commutation with a path edit outside the block.
        outside = [s for s in document.resource_strings() if not (start <= s.offset < end)]
        if outside and not problems:
            target = rng.choice(outside)
            edit = PrefabPathEdit(target.offset, target.text, random_text(rng, target.text))
            try:
                one = duplicate_prefab_element(rewrite_prefab_paths(data, [edit]).data, index, element).data
            except PrefabEditError:
                one = None
            if one is not None:
                shifted = edit.offset + (length if edit.offset >= end else 0)
                try:
                    two = rewrite_prefab_paths(
                        result.data, [PrefabPathEdit(shifted, edit.old_text, edit.new_text)]
                    ).data
                except PrefabEditError:
                    two = None
                if two is not None and one != two:
                    problems.append("duplicate and path edit do not commute")
    record["resize"] = ("fail" if problems else "ok")
    record["resize_op"] = "duplicate" if insert else "remove"
    if problems:
        record["resize_problems"] = problems[:8]
        record["resize_target"] = (index, element, collection.member_name)


# ------------------------------------------------------------- same-length only


def fuzz_same_length(rng, name, data, document, record) -> None:
    """Partial walks: a same-length swap must change exactly the text bytes."""
    from cdmw.core.prefab_recovery import recover_pointee_strings

    strings = {s.offset: s.text for s in recover_pointee_strings(data, document.blob_offset, document.blob_length)}
    strings.update({s.offset: s.text for s in document.all_strings()})
    paths = sorted({text for text in strings.values() if "/" in text and text.isascii()})
    if not paths:
        return
    chosen = rng.sample(paths, rng.randint(1, min(3, len(paths))))
    wanted = {}
    for text in chosen:
        new = "".join(rng.choices(_ALPHABET, k=len(text)))
        wanted[text] = new if new != text else "q" + new[1:]
    try:
        result = rewrite_prefab_paths_any_length(data, wanted)
    except PrefabEditError as exc:
        record["same"] = "refused"
        record["same_reason"] = refusal_class(str(exc))
        return
    # The rewriter matches with backslashes read as slashes, so the expectation must too.
    normalised = {old.replace("\\", "/").strip(): new for old, new in wanted.items()}
    expected = bytearray(data)
    for offset, text in strings.items():
        replacement = normalised.get(text.replace("\\", "/").strip())
        if replacement:
            expected[offset + 4 : offset + 4 + len(text)] = replacement.encode()
    problems = []
    if result.data != bytes(expected):
        diff = np.nonzero(np.frombuffer(result.data, np.uint8) != np.frombuffer(bytes(expected), np.uint8))[0]
        problems.append(f"same-length swap changed other bytes, first at 0x{int(diff[0]):x}" if len(diff) else "length changed")
    record["same"] = "fail" if problems else "ok"
    if problems:
        record["same_problems"] = problems


# ------------------------------------------------------------------------ main


def refusal_class(message: str) -> str:
    import re

    return re.sub(r"0x[0-9a-f]+|\b\d+\b|'[^']*'", "_", message)[:140]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("prefab-edit-oracle-failures.jsonl"))
    parser.add_argument("--rounds", type=int, default=1)
    args = parser.parse_args()

    files = sorted(args.corpus.glob("*.prefab"))
    if args.limit and args.limit < len(files):
        files = sorted(random.Random(args.seed).sample(files, args.limit))
    totals: collections.Counter[str] = collections.Counter()
    started = time.time()
    with args.out.open("w", encoding="utf-8") as sink:
        for number, path in enumerate(files, 1):
            data = path.read_bytes()
            try:
                document = decode_prefab_binary(data)
            except PrefabBinaryError:
                totals["header_error"] += 1
                continue
            for round_index in range(args.rounds):
                digest = hashlib.sha256(f"{args.seed}:{round_index}:{path.name}".encode()).digest()
                rng = random.Random(int.from_bytes(digest[:8], "little"))
                record = {"file": path.name, "round": round_index, "complete": document.walk_complete}
                try:
                    if document.walk_complete and walk_is_determined(data):
                        fuzz_paths(rng, path.name, data, document, record)
                        fuzz_resize(rng, path.name, data, document, record)
                    elif document.walk_complete:
                        record["undetermined"] = True
                        fuzz_same_length(rng, path.name, data, document, record)
                    else:
                        fuzz_same_length(rng, path.name, data, document, record)
                except Exception as exc:  # noqa: BLE001
                    record["crash"] = f"{type(exc).__name__}: {exc}"
                    record["trace"] = traceback.format_exc()[-1500:]
                for key in ("path", "resize", "same"):
                    if key in record:
                        totals[f"{key}:{record[key]}"] += 1
                if "crash" in record:
                    totals["crash"] += 1
                if any(record.get(k) == "fail" for k in ("path", "resize", "same")) or "crash" in record:
                    sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                    sink.flush()
            if number % 500 == 0:
                rate = number / (time.time() - started)
                print(f"{number}/{len(files)} {rate:.1f}/s {dict(totals)}", flush=True)
    print("ambiguous stale reports (not failures):", AMBIGUOUS)
    print("done", dict(totals), f"{time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
