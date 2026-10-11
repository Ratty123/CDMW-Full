"""Compare PALOC lookup and validation in frozen baseline and trial source trees.

This measures parsing on identical in-memory inputs, not archive IO or time to a
visible New Item window. Inputs are owned synthetic tables by default. --input
and --keys-json, or --corpus-manifest, identify an already isolated local corpus.
Selection and discarded-table validation are separate phases and percentages
must not be added. English selection is not used by the New Item snapshot.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import struct
import sys
import time

import lz4.block


def _load(root, label, relative="cdmw/core/paloc_format.py"):
    path = Path(root) / relative
    spec = importlib.util.spec_from_file_location("_paloc_benchmark_" + label, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _rows(entries):
    return tuple((e.category, e.key, e.text, e.reserved) for e in entries)


def _digest(entries):
    data = json.dumps(_rows(entries), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _wrapped(payload):
    compressed = lz4.block.compress(payload, store_size=False)
    header = bytearray(512)
    header[:5] = b"paloc"
    struct.pack_into("<III", header, 5, 0, len(compressed), len(payload))
    header[200:206] = b"opaque"
    return bytes(header) + compressed


def _synthetic(module, count, every, multilingual):
    rows, keys = [], set()
    for index in range(count):
        selected = index % every == 0
        key = str((index << 32) | 0x70) if selected else f"questdialog_owned_{index:06}"
        if selected:
            keys.add(key)
        text = (f"Item {index}" if selected else f"Owned dialogue line {index}. " * 3)
        if multilingual:
            text += " 日本語 Grüße سيف"
        rows.append(module.LocalizationEntry(7 if selected else 38, key, text, index % 3))
    return module.encode_paloc(rows), frozenset(keys)


def _summary(values):
    return {"median_ms": statistics.median(values), "min_ms": min(values), "max_ms": max(values),
            "samples_ms": values}


def _paired(baseline, trial, rounds):
    timings = {"baseline": [], "trial": []}
    functions = {"baseline": baseline, "trial": trial}
    # A full field-by-field comparison is separate from timing and warms both paths.
    left, right = baseline(), trial()
    if _rows(left) != _rows(right):
        raise AssertionError("Baseline and trial returned different localization records.")
    expected_digest = _digest(left)
    expected_count = len(left)
    del left, right
    for index in range(rounds):
        order = ("baseline", "trial") if index % 2 == 0 else ("trial", "baseline")
        for label in order:
            gc.collect()
            started = time.perf_counter()
            entries = functions[label]()
            elapsed = (time.perf_counter() - started) * 1000
            timings[label].append(elapsed)
            if len(entries) != expected_count or _digest(entries) != expected_digest:
                raise AssertionError(f"{label} produced unstable records in round {index}.")
            del entries
    a, b = _summary(timings["baseline"]), _summary(timings["trial"])
    return {"baseline": a, "trial": b, "median_saved_ms": a["median_ms"] - b["median_ms"],
            "median_reduction_percent": 100 * (a["median_ms"] - b["median_ms"]) / a["median_ms"],
            "speedup": a["median_ms"] / b["median_ms"], "equal_records": True,
            "record_count": expected_count, "records_sha256": expected_digest}


def _record(key, text):
    return struct.pack("<III", 7, 9, len(key)) + key + struct.pack("<I", len(text)) + text


def _validation_inputs():
    good = _record(b"wanted", b"Name")
    records = [
        _record(b"unwanted", b"Other"), _record(b"\xff", b"Other"),
        _record(b"unwanted", b"\xff"), _record(b"unwanted", b"\xed\xa0\x80"),
        struct.pack("<III", 7, 0, 9999) + b"k",
        struct.pack("<III", 7, 0, 1) + b"k" + struct.pack("<I", 9999) + b"x",
        b"\x01",
    ]
    cases = [b"", b"\x00", struct.pack("<I", 0),
             good + _record(b"wanted", "日本語 Grüße سيف".encode()) + struct.pack("<I", 2)]
    cases += [good + record + struct.pack("<I", count) for record in records for count in (1, 2, 3)]
    cases += [_wrapped(data) for data in cases if len(data) >= 4]
    container = _wrapped(good + struct.pack("<I", 1))
    cases.append(container[:100])
    for offset, value in ((5, 1), (9, len(container)), (13, 0), (13, 0xFFFFFFFF)):
        damaged = bytearray(container)
        struct.pack_into("<I", damaged, offset, value)
        cases.append(bytes(damaged))
    cases.append(container[:512] + bytes(len(container) - 512))
    return cases


def _validation_parity(baseline, trial):
    count = 0
    for case_number, data in enumerate(_validation_inputs()):
        for keys in (frozenset({"wanted"}), frozenset()):
            outcomes = []
            for reader in (
                lambda: tuple(e for e in baseline.parse_paloc(data, name="parity").entries if e.key in keys),
                lambda: trial.select_paloc_entries(data, keys, name="parity"),
            ):
                try:
                    outcomes.append(("records", _rows(reader())))
                except ValueError as exc:
                    outcomes.append(("error", str(exc)))
            if outcomes[0] != outcomes[1]:
                raise AssertionError(f"Validation mismatch in owned differential case {case_number}: {outcomes}")
            count += 1
    return {"cases": count, "exact_output_or_error_match": True}


@contextmanager
def _paloc_alias(module):
    name = "cdmw.core.paloc_format"
    missing = object()
    before = sys.modules.get(name, missing)
    sys.modules[name] = module
    try:
        yield
    finally:
        if before is missing:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = before


def _encrypted_parity(root_a, root_b, baseline, trial):
    # Common dependencies use the frozen baseline. The two changed modules are
    # loaded explicitly and each decryptor imports its own PALOC implementation.
    sys.path.insert(0, str(root_a))
    archive_a, source_a = _load(root_a, "archive_baseline", "cdmw/core/archive_format.py")
    archive_b, source_b = _load(root_b, "archive_trial", "cdmw/core/archive_format.py")
    from cdmw.models import ArchiveEntry

    count = 0
    successes = 0
    rejections = 0
    for case_number, data in enumerate(_validation_inputs()):
        for compressed in (False, True):
            stored = lz4.block.compress(data, store_size=False) if compressed else data
            entry = ArchiveEntry(
                path="gamedata/stringtable/binary__/eng/item.paloc",
                pamt_path=Path("owned/0.pamt"), paz_file=Path("owned/0.paz"),
                offset=0, comp_size=len(stored), orig_size=len(data), paz_index=0,
                flags=(3 << 4) | (2 if compressed else 0),
            )
            encrypted = archive_a.crypt_chacha20_filename(stored, entry.basename)
            outcomes = []
            for archive, paloc in ((archive_a, baseline), (archive_b, trial)):
                with _paloc_alias(paloc):
                    try:
                        decoded, note = archive.try_decrypt_archive_entry_data(entry, encrypted)
                        if decoded != stored or note != "ChaCha20":
                            raise AssertionError("Encrypted input bytes or decode note changed.")
                        outcomes.append(("bytes", decoded, note))
                    except ValueError as exc:
                        outcomes.append(("error", str(exc)))
            if outcomes[0] != outcomes[1]:
                raise AssertionError(f"Encrypted validation mismatch in owned case {case_number}.")
            if outcomes[0][0] == "bytes":
                successes += 1
            else:
                rejections += 1
            count += 1
    return {"cases": count, "successful_decodes": successes, "matching_rejections": rejections,
            "exact_bytes_note_or_error_match": True,
            "baseline_archive_source": source_a, "trial_archive_source": source_b}


def _keys(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(key, str) for key in value):
        raise ValueError("keys JSON must be a list of strings")
    return frozenset(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--records", type=int, default=187521)
    parser.add_argument("--every", type=int, default=64)
    parser.add_argument("--input", type=Path, action="append", default=[])
    parser.add_argument("--keys-json", type=Path)
    parser.add_argument("--corpus-manifest", type=Path)
    parser.add_argument("--selection-only", action="store_true",
                        help="Skip complete-parser timing when using a larger corpus.")
    args = parser.parse_args()
    if min(args.rounds, args.records, args.every) < 1:
        parser.error("rounds, records and every must be positive")
    if args.input and args.keys_json is None:
        parser.error("--keys-json is required with --input")
    if args.corpus_manifest and (args.input or args.keys_json):
        parser.error("--corpus-manifest is separate from --input/--keys-json")
    baseline, source_a = _load(args.baseline, "baseline")
    trial, source_b = _load(args.trial, "trial")
    validation = _validation_parity(baseline, trial)
    encrypted_validation = _encrypted_parity(args.baseline, args.trial, baseline, trial)
    cases = []
    if args.corpus_manifest:
        manifest = json.loads(args.corpus_manifest.read_text(encoding="utf-8"))
        if manifest.get("schema") != "cdmw_paloc_capture_v1":
            parser.error("unrecognized isolated corpus manifest")
        root = args.corpus_manifest.parent.resolve()
        keys = _keys(root / manifest["keys_file"])
        if len(keys) != manifest["wanted_key_count"]:
            parser.error("isolated wanted-key count changed")
        for record in manifest["files"]:
            if not record["role"].startswith("localization:"):
                continue
            path = (root / record["file"]).resolve()
            if not path.is_relative_to(root):
                parser.error("corpus input is outside the isolated capture")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != record["decoded_sha256"]:
                parser.error("isolated input checksum changed")
            language = record["role"].split(":", 1)[1]
            extra = {"language": language, "source_game_path": record["game_path"],
                     "archive_flags": record["flags"], "decode_note": record["decode_note"],
                     "selection_used_by_new_item": language != "eng",
                     "validation_used_by_archive": (record["flags"] >> 4) == 3}
            cases.append((path.name, data, keys, "isolated installed corpus", extra))
    elif args.input:
        keys = _keys(args.keys_json)
        for path in args.input:
            cases.append((path.name, path.read_bytes(), keys, "isolated supplied corpus", {}))
    else:
        plain, keys = _synthetic(baseline, args.records, args.every, False)
        cases.append(("owned_ascii_plain", plain, keys, "synthetic", {}))
        multilingual, keys = _synthetic(baseline, args.records, args.every, True)
        cases.append(("owned_multilingual_wrapped", _wrapped(multilingual), keys, "synthetic", {}))
    results = []
    for name, data, keys, kind, extra in cases:
        def old_selection():
            return tuple(e for e in baseline.parse_paloc(data, name=name).entries if e.key in keys)

        def new_selection():
            return trial.select_paloc_entries(data, keys, name=name)

        def old_validation():
            baseline.parse_paloc(data, name=name)
            return ()

        def new_validation():
            return trial.select_paloc_entries(data, (), name=name)

        result = {"name": name, "kind": kind, "input_bytes": len(data), **extra,
                  "input_sha256": hashlib.sha256(data).hexdigest(), "wanted_key_count": len(keys),
                  "wanted_keys_sha256": hashlib.sha256(json.dumps(sorted(keys)).encode()).hexdigest(),
                  "selected_names": _paired(old_selection, new_selection, args.rounds),
                  "validation_only": _paired(old_validation, new_validation, args.rounds)}
        # Original full-table editing/export behavior is also compared, including
        # preserving the exact bytes of a compressed source container.
        full_a = baseline.parse_paloc(data, name=name)
        full_b = trial.parse_paloc(data, name=name)
        result["full_table_parity"] = (_rows(full_a.entries) == _rows(full_b.entries)
                                      and baseline.encode_paloc(full_a) == data
                                      and trial.encode_paloc(full_b) == data)
        if not result["full_table_parity"]:
            raise AssertionError("Complete PALOC parsing or re-encoding changed.")
        result["full_record_count"] = len(full_a.entries)
        del full_a, full_b
        if not args.selection_only:
            result["complete_parser"] = _paired(
                lambda: baseline.parse_paloc(data, name=name).entries,
                lambda: trial.parse_paloc(data, name=name).entries, args.rounds)
        results.append(result)
    report = {"schema": "cdmw_paloc_selection_ab_v2", "python": sys.version,
              "baseline_source": source_a, "trial_source": source_b,
              "scope": "In-memory parsing and selected record retention; excludes archive IO and UI startup.",
              "method": "One untimed exact comparison, alternating A/B then B/A; GC before each timed call; output checks outside timing.",
              "phase_note": "Selected names, validation-only and complete-parser timings are separate operations. Do not add percentages or count English selection as a New Item saving.",
              "rounds": args.rounds, "validation_parity": validation,
              "encrypted_validation_parity": encrypted_validation, "cases": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "validation_parity": validation,
                      "encrypted_validation_parity": encrypted_validation,
                      "cases": [{"name": r["name"], "input_bytes": r["input_bytes"],
                                  "full_record_count": r["full_record_count"],
                                  "selected_record_count": r["selected_names"]["record_count"],
                                  "baseline_ms": r["selected_names"]["baseline"]["median_ms"],
                                  "trial_ms": r["selected_names"]["trial"]["median_ms"],
                                  "reduction_percent": r["selected_names"]["median_reduction_percent"],
                                  "validation_only_reduction_percent": r["validation_only"]["median_reduction_percent"],
                                  "validation_only_saved_ms": r["validation_only"]["median_saved_ms"],
                                  "exact_parity": r["full_table_parity"],
                                  "complete_parser_reduction_percent": r.get("complete_parser", {}).get("median_reduction_percent")}
                                 for r in results]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
