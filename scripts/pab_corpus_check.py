"""Re-derive the PAB layout figures quoted in the research doc and manifest.

Reads every ``*.pab`` under ``--corpus`` (extracted read-only from the game
archives; game files are never committed) and reports, per file and in total:
the header variant, whether the strict reader explains every byte, whether
the writer reproduces the file byte for byte, whether every stored name hash
is the PA checksum of its name, whether a bone can be appended and read back,
and how the per-bone tail arrays relate to the hierarchy.

Usage:
    python scripts/pab_corpus_check.py --corpus <dir> [--json <out.json>]
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from cdmw.modding.skeleton_writer import (
    PabFormatError,
    _compose_local,
    append_child_bone,
    pab_bone_name_hash,
    read_pab_document,
    write_pab_document,
)


def check(data: bytes, path: str) -> dict:
    row: dict = {"path": path, "size": len(data)}
    try:
        document = read_pab_document(data, path)
    except PabFormatError as exc:
        row["error"] = str(exc)
        return row
    bones = document.bones
    row["variant"] = document.variant
    row["bones"] = len(bones)
    row["round_trip"] = write_pab_document(document) == data
    row["hashes_match"] = all(pab_bone_name_hash(bone.name) == bone.name_hash for bone in bones)
    appended = append_child_bone(document, len(bones) - 1, "CDMW_Corpus_Check_00", position=(0.1, 0.0, 0.0))
    output = write_pab_document(appended)
    reread = read_pab_document(output)
    row["append_rereads"] = reread.bones == appended.bones and write_pab_document(reread) == output
    row["trs_mismatches"] = sum(
        1 for bone in bones
        if max(abs(a - b) for a, b in zip(_compose_local(bone.scale, bone.rotation, bone.position),
                                         bone.local_bind_matrix)) > 1e-3)
    if document.secondary_parents is not None:
        row["secondary_differs"] = sum(1 for bone, other in zip(bones, document.secondary_parents)
                                       if bone.parent_index != other)
        row["secondary_after_self"] = sum(1 for index, other in enumerate(document.secondary_parents)
                                          if other >= index)
    if document.core_flags is not None:
        row["core_bones"] = sum(document.core_flags)
        row["core_under_plain_parent"] = sum(
            1 for bone, flag in zip(bones, document.core_flags)
            if flag and bone.parent_index >= 0 and not document.core_flags[bone.parent_index])
        row["plain_roots"] = sum(1 for bone, flag in zip(bones, document.core_flags)
                                 if bone.parent_index < 0 and not flag)
    row["volumes"] = [len(item.volumes) for item in document.volume_sets]
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", required=True, type=pathlib.Path)
    parser.add_argument("--json", type=pathlib.Path)
    args = parser.parse_args()
    files = sorted(path for path in args.corpus.rglob("*") if path.suffix.lower() == ".pab")
    if not files:
        parser.error(f"no .pab files under {args.corpus}")
    rows = [check(path.read_bytes(), str(path.relative_to(args.corpus))) for path in files]
    totals = collections.Counter()
    for row in rows:
        totals["files"] += 1
        if "error" in row:
            totals["unreadable"] += 1
            continue
        totals[row["variant"]] += 1
        for key in ("round_trip", "hashes_match", "append_rereads"):
            totals[key] += bool(row[key])
        for key in ("bones", "trs_mismatches", "secondary_differs", "secondary_after_self", "core_bones",
                    "core_under_plain_parent", "plain_roots"):
            totals[f"sum {key}"] += row.get(key, 0)
    for key, value in sorted(totals.items()):
        print(f"{key}: {value:,}")
    for row in rows:
        if "error" in row or not row["round_trip"]:
            print("FAIL", row["path"], row.get("error", "round trip differs"))
    if args.json:
        args.json.write_text(json.dumps({"totals": totals, "files": rows}, indent=1), encoding="utf-8")
    return 0 if totals["round_trip"] == totals["files"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
