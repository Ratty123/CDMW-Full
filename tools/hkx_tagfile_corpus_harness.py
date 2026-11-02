"""Read-only corpus harness for the relocating HKX tagfile codec.

For every `.hkx` entry in the installed archives (latest copy of each path):

1. parse it into ``HkxTagfileModel`` (or record the refusal code);
2. serialize the model and require byte identity with the source;
3. relocation check: serialize with a 16-byte gap before every item, parse the
   shifted file again, require the same reference graph and masked payloads,
   and require that serializing the shifted model gives back the source bytes.

Optionally (``--string-probe``) every replaceable string item is lengthened in
one edit, the file is rebuilt and parsed again, the strings must read back, and
restoring them must give the source bytes; this exercises the structural string
edit on real layouts.

Nothing is written to the archives; the report goes to ``--out``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Dict, List, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import discover_pamt_files, parse_archive_pamt
from cdmw.core.archive_hkx_structural_edits import (
    hkx_string_items,
    replace_hkx_string_items,
)
from cdmw.core.archive_hkx_tagfile_model import (
    HkxTagfileRefused,
    hkx_tagfile_masked_payloads,
    hkx_tagfile_reference_graph,
    parse_hkx_tagfile_model,
    serialize_hkx_tagfile_model,
)

_REPORT_FORMAT = "cdmw_hkx_tagfile_corpus_v1"
_SAMPLES_PER_CODE = 12


def discover_hkx_entries(game_root: Path, path_contains: Sequence[str] = ()) -> List[object]:
    latest: Dict[str, object] = {}
    for pamt_path in discover_pamt_files(game_root):
        is_dlc = pamt_path.relative_to(game_root).as_posix().casefold().startswith("dlc/")
        for entry in parse_archive_pamt(pamt_path):
            if str(getattr(entry, "extension", "") or "").casefold() != ".hkx":
                continue
            key = str(entry.path).replace("\\", "/").casefold()
            if path_contains and not all(text.casefold() in key for text in path_contains):
                continue
            if key not in latest or is_dlc:
                latest[key] = entry
    return [latest[key] for key in sorted(latest)]


def check_hkx_bytes(data: bytes, *, string_probe: bool = False) -> Dict[str, object]:
    try:
        model = parse_hkx_tagfile_model(data)
    except HkxTagfileRefused as exc:
        return {"status": "refused", "code": exc.code, "message": str(exc)}
    row: Dict[str, object] = {"items": len(model.items) - 1, "references": len(model.references)}
    if serialize_hkx_tagfile_model(model) != data:
        row.update(status="rebuild_mismatch")
        return row
    shifted = parse_hkx_tagfile_model(serialize_hkx_tagfile_model(model, extra_gap=16), canonical_layout=False)
    if (
        hkx_tagfile_reference_graph(shifted) != hkx_tagfile_reference_graph(model)
        or hkx_tagfile_masked_payloads(shifted) != hkx_tagfile_masked_payloads(model)
        or serialize_hkx_tagfile_model(shifted) != data
    ):
        row.update(status="relocation_mismatch")
        return row
    if string_probe:
        strings = hkx_string_items(model)
        row["strings"] = len(strings)
        if strings:
            lengthened = parse_hkx_tagfile_model(
                serialize_hkx_tagfile_model(
                    replace_hkx_string_items(model, {index: text + "_cdmw_probe" for index, text in strings})
                )
            )
            if hkx_string_items(lengthened) != [(index, text + "_cdmw_probe") for index, text in strings]:
                row.update(status="string_edit_mismatch")
                return row
            restored = replace_hkx_string_items(lengthened, dict(strings))
            if serialize_hkx_tagfile_model(restored) != data:
                row.update(status="string_edit_mismatch")
                return row
    row["types"] = dict(Counter(model.type_name(index) for index in range(1, len(model.items))))
    row["status"] = "exact"
    return row


def _check_batch(batch: Sequence[object], string_probe: bool) -> List[Dict[str, object]]:
    rows = []
    for entry in batch:
        path = str(entry.path).replace("\\", "/")
        try:
            data, _, _ = read_archive_entry_data(entry)
            row = check_hkx_bytes(data, string_probe=string_probe)
        except Exception as exc:  # noqa: BLE001 - the harness records every failure
            row = {"status": "error", "message": repr(exc)[:300]}
        row["path"] = path
        rows.append(row)
    return rows


def summarize(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    status = Counter(str(row["status"]) for row in rows)
    codes = Counter(str(row.get("code")) for row in rows if row["status"] == "refused")
    samples: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    exact_types: Counter[str] = Counter()
    exact_files_by_type: Counter[str] = Counter()
    folders: Dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        key = str(row.get("code") or row["status"])
        if row["status"] != "exact" and len(samples[key]) < _SAMPLES_PER_CODE:
            samples[key].append({name: row[name] for name in ("path", "message") if name in row})
        folders["/".join(str(row["path"]).split("/")[:3])][str(row["status"])] += 1
        for type_name, count in dict(row.get("types") or {}).items():
            exact_types[type_name] += int(count)
            exact_files_by_type[type_name] += 1
    return {
        "format": _REPORT_FORMAT,
        "files": len(rows),
        "status_counts": dict(status),
        "refusal_codes": dict(codes),
        "string_probe_files": sum(1 for row in rows if int(row.get("strings") or 0) > 0 and row["status"] == "exact"),
        "string_probe_items": sum(int(row.get("strings") or 0) for row in rows if row["status"] == "exact"),
        "samples": dict(samples),
        "exact_items_by_type": dict(exact_types.most_common()),
        "exact_files_by_type": dict(exact_files_by_type.most_common()),
        "folders": {folder: dict(counts) for folder, counts in sorted(folders.items())},
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game-root", type=Path, required=True, help="Crimson Desert package root containing .pamt files.")
    parser.add_argument("--out", type=Path, required=True, help="Path of the JSON summary to write.")
    parser.add_argument("--path-contains", action="append", default=[], help="Only check paths containing this text. Repeatable.")
    parser.add_argument("--limit", type=int, default=0, help="Check only the first N matching paths.")
    parser.add_argument("--jobs", type=int, default=1, help="Worker processes (read-only work).")
    parser.add_argument("--string-probe", action="store_true", help="Also lengthen and restore every PTCH string item.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    started = time.time()
    entries = discover_hkx_entries(args.game_root, args.path_contains)
    if args.limit:
        entries = entries[: args.limit]
    batches = [entries[start : start + 250] for start in range(0, len(entries), 250)]
    rows: List[Dict[str, object]] = []
    if args.jobs > 1:
        with ProcessPoolExecutor(args.jobs) as pool:
            for batch_rows in pool.map(_check_batch, batches, [args.string_probe] * len(batches)):
                rows.extend(batch_rows)
    else:
        for batch in batches:
            rows.extend(_check_batch(batch, args.string_probe))
    summary = summarize(rows)
    summary["elapsed_seconds"] = round(time.time() - started, 1)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    keys = ("files", "status_counts", "refusal_codes", "string_probe_files", "string_probe_items", "elapsed_seconds")
    print(json.dumps({key: summary[key] for key in keys}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
