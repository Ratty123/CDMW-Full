"""Validate the prefab rewriter against the game's own authoring tool.

Every other check on this rewriter is internal -- "does the result decode
again" -- which a systematically wrong assumption would also pass. This is the
one oracle that sits outside our own decoder.

The archives ship thousands of prefabs that are the same asset with one path
changed: armour variants, object presets, weapon indexes. Those pairs are
ground truth produced by whatever wrote the game's data. So: take vanilla A,
use the rewriter to point it at B's path, and demand the result is byte
identical to vanilla B.

Selecting genuine pairs is most of the work, and getting it wrong manufactures
false failures. A pair qualifies only when both files agree on

* the full type table, members included -- sharing type *names* is not enough,
  since different members move everything after the schema;
* every decoded object: name, component type, member list, parent, provenance;
* every inline numeric value, and the pointer count;
* every string but one;
* the file-size difference equals that string's byte delta. A pair whose sizes
  differ by anything else carries a second change -- an extra record, a flag --
  and cannot serve as ground truth for this edit;
* every byte before the edited string is identical, once the data header's
  file-size and blob-length fields are masked out. Some pairs differ in a bool
  the decoder does not surface as a value, and that byte sits ahead of the
  paths. Those two header fields must be excluded or the check rejects every
  length-changing pair -- they are precisely the fields a length change moves;
* and, when the replacement is the same length, every byte after the string is
  identical too. A same-length variant that still differs later -- an index
  stored past the path, say -- carries a second change. This is decided from
  the two vanilla files alone, never from our output, so it cannot mask a bug.
  Length-changing pairs get the same check with the fields a shift legitimately
  moves -- pointer values and every candidate length field -- masked out first.
  Without it, ``_index01`` versus ``_index02`` variants qualify: they differ in
  the path *and* in an index byte stored after it, and the rewrite then
  faithfully preserves A's index while B holds its own.

There is deliberately no "is this residual difference really ours?" classifier.
An earlier version excused any byte where our output still matched A, reasoning
that the two vanilla files must differ there. That is exactly what a *missing*
update looks like: mutating the data-header patch into a no-op dropped 280
exact matches and the classifier reported zero faults. Non-exact is a failure.

The version-4 header holds a per-file identifier that is deliberately preserved
(see docs/features/prefab-structural-decoding.md), so a rewritten A keeps A's
id where B has B's. Both sides are compared with that field zeroed. Everything
else must match exactly, the data header's file size included.

Usage:
    python scripts/prefab_vanilla_pair_oracle.py --corpus <dir> [--limit N]

The corpus is a directory of ``.prefab`` files extracted from the archives,
named with ``__`` for path separators. Game archives are read-only inputs and
are never committed, so the directory is supplied rather than assumed.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from cdmw.core.prefab_binary import (  # noqa: E402
    PrefabBinaryError,
    decode_prefab_binary,
    pointer_sites,
)
from cdmw.core.prefab_binary_edit import (  # noqa: E402
    _POINTEE_SCAN,
    _length_field_candidates,
    _string_byte_mask,
    PrefabEditError,
    PrefabPathEdit,
    rewrite_prefab_paths,
)

ID_AT, ID_LEN = 6, 8


def header_masked(data: bytes, blob_at: int) -> bytes:
    """``data`` with the data header's file-size and blob-length zeroed.

    Both legitimately differ between two vanilla files whose paths are
    different lengths, and both sit *before* the strings, so comparing raw
    prefixes would reject every length-changing pair.
    """
    out = bytearray(data)
    for at in (blob_at - 24, blob_at - 4):
        if 0 <= at and at + 4 <= len(out):
            out[at : at + 4] = bytes(4)
    return bytes(out)


def neutral(data: bytes) -> bytes:
    """The file with its per-file version-4 header identifier zeroed."""
    if len(data) < ID_AT + ID_LEN or struct.unpack_from("<H", data, 2)[0] != 4:
        return data
    return data[:ID_AT] + b"\x00" * ID_LEN + data[ID_AT + ID_LEN :]


def layout_masked(data: bytes, document) -> bytes:
    """``data`` with pointer values and candidate length fields zeroed.

    These encode absolute positions, so they differ between two vanilla files
    whose paths are different lengths even when nothing else does. Masking them
    leaves the actual content comparable.
    """
    out = bytearray(data)
    strings = _string_byte_mask(data, document)
    for site in pointer_sites(data, document.blob_offset, document.blob_length):
        out[site : site + 4] = bytes(4)
        for candidate in _length_field_candidates(data, site + 4, _POINTEE_SCAN, strings):
            out[candidate : candidate + 4] = bytes(4)
    return bytes(out)


class Summary:
    """Everything the decoder can see about a file, for pair matching."""

    __slots__ = (
        "data", "types", "strings", "numbers", "pointers", "root", "shape",
        "blob_at", "masked",
    )

    def __init__(self, data: bytes, document) -> None:
        self.data = data
        self.blob_at = document.blob_offset
        self.masked = layout_masked(data, document)
        self.root = document.root_type
        self.types = tuple(
            (
                item.type_name,
                tuple(
                    (m.name, m.type_name, m.flags, m.value_size, m.attr_flags, m.extra)
                    for m in item.members
                ),
            )
            for item in document.types
        )
        self.strings = tuple((s.offset, s.text) for s in document.all_strings())
        numbers = list(document.root_numbers)
        for obj in document.objects:
            numbers.extend(obj.numbers)
        self.numbers = tuple(n.raw for n in numbers)
        self.pointers = len(document.pointers)
        # Object names never appear in all_strings(), so without them a pair
        # differing in a name *and* a path looks like a pure variant.
        self.shape = (
            document.root_members,
            tuple(
                (o.name, o.component_type, o.member_names, o.parent, o.type_source)
                for o in document.objects
            ),
        )


def differing_string(left: Summary, right: Summary) -> int | None:
    """Index of the single differing string, or ``None`` if not a clean pair."""
    if left.types != right.types or left.root != right.root or left.blob_at != right.blob_at:
        return None
    if left.shape != right.shape or left.numbers != right.numbers:
        return None
    if len(left.strings) != len(right.strings) or left.pointers != right.pointers:
        return None
    differing = [
        index
        for index, (a, b) in enumerate(zip(left.strings, right.strings))
        if a[1] != b[1]
    ]
    return differing[0] if len(differing) == 1 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=pathlib.Path)
    parser.add_argument("--limit", type=int, default=0, help="stop after N files")
    parser.add_argument("--bucket-max", type=int, default=60)
    args = parser.parse_args()

    files = sorted(args.corpus.glob("*.prefab"))
    if args.limit:
        files = files[: args.limit]
    buckets: dict[str, list[pathlib.Path]] = collections.defaultdict(list)
    for path in files:
        buckets[path.name.rsplit("__", 1)[0]].append(path)

    cache: dict[pathlib.Path, Summary | None] = {}

    def summarise(path: pathlib.Path) -> Summary | None:
        if path not in cache:
            data = neutral(path.read_bytes())
            try:
                document = decode_prefab_binary(data)
            except PrefabBinaryError:
                cache[path] = None
            else:
                cache[path] = Summary(data, document) if document.walk_complete else None
        return cache[path]

    pairs = same = changing = exact = changing_exact = refused = impure = 0
    faults: list[str] = []

    for group in buckets.values():
        if not 2 <= len(group) <= args.bucket_max:
            continue
        for left_path in group:
            for right_path in group:
                if left_path is right_path:
                    continue
                left, right = summarise(left_path), summarise(right_path)
                if left is None or right is None:
                    continue
                index = differing_string(left, right)
                if index is None:
                    continue
                offset, old = left.strings[index]
                _, new = right.strings[index]
                delta = len(new.encode("utf-8")) - len(old.encode("utf-8"))
                if len(right.data) - len(left.data) != delta:
                    impure += 1
                    continue
                if (
                    header_masked(left.data, left.blob_at)[:offset]
                    != header_masked(right.data, right.blob_at)[:offset]
                ):
                    impure += 1
                    continue
                past = offset + 4 + len(old.encode("utf-8"))
                if left.masked[past:] != right.masked[past + delta :]:
                    impure += 1
                    continue
                pairs += 1
                grew = delta != 0
                changing += grew
                same += not grew
                try:
                    result = rewrite_prefab_paths(
                        left.data,
                        [PrefabPathEdit(offset=offset, old_text=old, new_text=new)],
                    )
                except PrefabEditError:
                    refused += 1
                    continue
                got = neutral(result.data)
                if got == right.data:
                    exact += 1
                    changing_exact += grew
                else:
                    faults.append(f"{left_path.name} -> {right_path.name}: {old} => {new}")

    print(f"vanilla pairs differing in exactly one path : {pairs}")
    print(f"   same length                              : {same}")
    print(f"   length-changing (tests relocation)       : {changing}")
    print(f"\nreproduced vanilla byte-for-byte           : {exact}/{pairs}")
    print(f"   of which length-changing                 : {changing_exact}/{changing}")
    print(f"   refused as undecidable                   : {refused}")
    print(f"   NOT REPRODUCED (counted as failures)     : {len(faults)}")
    print(f"\npairs rejected as impure before testing    : {impure}")
    for line in faults[:10]:
        print(f"      {line}")
    return 1 if faults else 0


if __name__ == "__main__":
    raise SystemExit(main())
