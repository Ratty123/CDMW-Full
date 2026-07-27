"""Validate and report format decode progress from the capability manifest.

`schemas/archive_content_capabilities.v1.json` is the single source of truth for
what CDMW can read and write per file format. Each entry carries a `decode` and
`write` status, where that claim is evidenced, and what is left to do.

This tool owns two derived artefacts and nothing else:

* the manifest's own `progress` block, recomputed from the entries, and
* `docs/features/format-decode-progress.md`, regenerated from the same data.

Run `--check` (the default) to fail on drift, `--write` to regenerate both.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "schemas" / "archive_content_capabilities.v1.json"
REPORT_PATH = REPO_ROOT / "docs" / "features" / "format-decode-progress.md"

DECODE_WEIGHTS = {"full": 1.0, "partial": 0.6, "surface": 0.3, "none": 0.0}
WRITE_WEIGHTS = {"full": 1.0, "constrained": 0.5, "none": 0.0}
ORIGINS = ("proprietary", "third_party", "open", "unknown")
PRIORITIES = ("high", "medium", "low", "none")

REQUIRED_FIELDS = ("origin", "decode", "write", "priority", "evidence", "remaining")

RUBRIC = {
    "decode": {
        "full": "Record layout is known and checked against the shipped corpus. No unexplained spans in the supported path.",
        "partial": "The primary payload is decoded, but variants, later LODs, or regions of the file remain unmodelled.",
        "surface": "Strings, references, and headers are recovered. The record layout is not parsed.",
        "none": "Raw bytes only.",
    },
    "write": {
        "full": "CDMW can produce game-loadable bytes for this format.",
        "constrained": "Only edits proven safe are permitted; the rest are gated off deliberately.",
        "none": "No writer exists.",
    },
    "origin": {
        "proprietary": "Pearl Abyss format. Everything known about it was reverse engineered here.",
        "third_party": "Licensed middleware format (Havok, Wwise). Documented externally, not by the game.",
        "open": "Public format with a published specification.",
        "unknown": "Provenance unconfirmed; may not be engine content.",
    },
    "priority": {
        "high": "Closing this gap unlocks a modding category that is currently at zero.",
        "medium": "Real value, but a workaround or an adjacent format covers part of it.",
        "low": "Rare, cosmetic, or already served by another route.",
        "none": "Nothing meaningful left to do.",
    },
    "weights": {
        "note": "Coverage percentages are the weighted mean of these per-entry scores, so they move only when a status moves.",
        "decode": DECODE_WEIGHTS,
        "write": WRITE_WEIGHTS,
    },
}


class ManifestError(RuntimeError):
    """Raised when the manifest is internally inconsistent."""


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(entries: Sequence[Mapping[str, object]]) -> None:
    seen: set[str] = set()
    for entry in entries:
        extension = str(entry.get("extension") or "")
        if not extension.startswith(".") or len(extension) < 2:
            raise ManifestError(f"invalid extension: {extension!r}")
        if extension in seen:
            raise ManifestError(f"duplicate extension: {extension}")
        seen.add(extension)
        for field in REQUIRED_FIELDS:
            if field not in entry:
                raise ManifestError(f"{extension}: missing {field!r}")
        if entry["origin"] not in ORIGINS:
            raise ManifestError(f"{extension}: unknown origin {entry['origin']!r}")
        if entry["decode"] not in DECODE_WEIGHTS:
            raise ManifestError(f"{extension}: unknown decode {entry['decode']!r}")
        if entry["write"] not in WRITE_WEIGHTS:
            raise ManifestError(f"{extension}: unknown write {entry['write']!r}")
        if entry["priority"] not in PRIORITIES:
            raise ManifestError(f"{extension}: unknown priority {entry['priority']!r}")
        if not str(entry["evidence"]).strip():
            raise ManifestError(f"{extension}: evidence must say where the claim is backed")
        if entry["decode"] == "full" and entry["write"] == "full" and str(entry["remaining"]).strip():
            continue
        if entry["priority"] == "none" and entry["decode"] in {"surface", "none"} and entry["origin"] == "proprietary":
            raise ManifestError(f"{extension}: undecoded proprietary format cannot be priority 'none'")
        if entry["write"] != "full" and entry["priority"] != "none" and not str(entry["remaining"]).strip():
            raise ManifestError(f"{extension}: must say what is remaining")


def _percent(values: Iterable[float]) -> float:
    scores = list(values)
    if not scores:
        return 0.0
    return round(100.0 * sum(scores) / len(scores), 1)


def _bucket(entries: Sequence[Mapping[str, object]]) -> dict:
    return {
        "extensions": len(entries),
        "decode_percent": _percent(DECODE_WEIGHTS[str(e["decode"])] for e in entries),
        "write_percent": _percent(WRITE_WEIGHTS[str(e["write"])] for e in entries),
        "decode": {k: v for k, v in sorted(Counter(str(e["decode"]) for e in entries).items())},
        "write": {k: v for k, v in sorted(Counter(str(e["write"]) for e in entries).items())},
    }


def summarize(entries: Sequence[Mapping[str, object]]) -> dict:
    proprietary = [e for e in entries if e["origin"] == "proprietary"]
    engine = [e for e in entries if e["origin"] in {"proprietary", "third_party"}]
    by_origin = {
        origin: _bucket([e for e in entries if e["origin"] == origin])
        for origin in ORIGINS
        if any(e["origin"] == origin for e in entries)
    }
    by_group = {
        group: _bucket([e for e in entries if e["group"] == group])
        for group in sorted({str(e["group"]) for e in entries})
    }
    open_gaps = [
        {
            "extension": str(e["extension"]),
            "decode": str(e["decode"]),
            "write": str(e["write"]),
            "remaining": str(e["remaining"]),
        }
        for e in sorted(entries, key=lambda e: str(e["extension"]))
        if e["priority"] == "high"
    ]
    return {
        "generated_by": "tools/report_format_decode_progress.py --write",
        "rubric": RUBRIC,
        "headline": {
            "note": "Engine formats are the ones CDMW had to reverse engineer. Open formats are counted separately because decoding them is not the project's work.",
            "engine_formats": _bucket(engine),
            "proprietary_formats": _bucket(proprietary),
            "all_formats": _bucket(list(entries)),
        },
        "by_origin": by_origin,
        "by_group": by_group,
        "priority": {p: sum(1 for e in entries if e["priority"] == p) for p in PRIORITIES},
        "open_high_priority_gaps": open_gaps,
    }


def _render_progress_block(progress: Mapping[str, object]) -> str:
    body = json.dumps(progress, indent=2, ensure_ascii=False)
    return "\n".join("  " + line for line in body.splitlines())


def write_manifest_progress(progress: Mapping[str, object], path: Path = MANIFEST_PATH) -> None:
    text = path.read_text(encoding="utf-8")
    block = f'  "progress": {_render_progress_block(progress).lstrip()},\n'
    pattern = re.compile(r'^  "progress": .*?\n(?=  "extensions": \[)', re.DOTALL | re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(block, text)
    else:
        text = text.replace('  "extensions": [', block + '  "extensions": [', 1)
    path.write_text(text, encoding="utf-8")


def _bar(percent: float, width: int = 20) -> str:
    filled = int(round(percent / 100.0 * width))
    return "#" * filled + "." * (width - filled)


def _table(rows: Sequence[Sequence[str]], header: Sequence[str]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def render_report(manifest: Mapping[str, object]) -> str:
    entries = list(manifest["extensions"])  # type: ignore[index]
    progress = summarize(entries)
    engine = progress["headline"]["engine_formats"]
    proprietary = progress["headline"]["proprietary_formats"]

    out: list[str] = []
    out.append("# Format decode progress")
    out.append("")
    out.append(
        "Generated by `tools/report_format_decode_progress.py --write` from "
        "`schemas/archive_content_capabilities.v1.json`. Do not edit by hand: change the "
        "manifest entry and regenerate, so the status a modder reads and the status the "
        "Archive Browser reports can never disagree."
    )
    out.append("")
    out.append("## Where we are")
    out.append("")
    out.append(
        f"Of {len(entries)} known file formats, {engine['extensions']} are engine formats "
        f"(Pearl Abyss or licensed middleware) that had to be reverse engineered. Those are the "
        f"real measure of progress; the rest are public formats that arrive already understood."
    )
    out.append("")
    out.append(
        _table(
            [
                [
                    "Engine formats (proprietary + middleware)",
                    str(engine["extensions"]),
                    f"{engine['decode_percent']}%",
                    f"{engine['write_percent']}%",
                ],
                [
                    "Pearl Abyss formats only",
                    str(proprietary["extensions"]),
                    f"{proprietary['decode_percent']}%",
                    f"{proprietary['write_percent']}%",
                ],
                [
                    "All formats",
                    str(progress["headline"]["all_formats"]["extensions"]),
                    f"{progress['headline']['all_formats']['decode_percent']}%",
                    f"{progress['headline']['all_formats']['write_percent']}%",
                ],
            ],
            ["Scope", "Formats", "Read coverage", "Write coverage"],
        )
    )
    out.append("")
    out.append(
        "Coverage is a weighted mean, not a file count: "
        + ", ".join(f"decode `{k}` = {v}" for k, v in DECODE_WEIGHTS.items())
        + "; "
        + ", ".join(f"write `{k}` = {v}" for k, v in WRITE_WEIGHTS.items())
        + "."
    )
    out.append("")
    out.append("## By area")
    out.append("")
    rows = []
    for group, bucket in progress["by_group"].items():
        rows.append(
            [
                f"`{group}`",
                str(bucket["extensions"]),
                f"`{_bar(bucket['decode_percent'])}` {bucket['decode_percent']}%",
                f"`{_bar(bucket['write_percent'])}` {bucket['write_percent']}%",
            ]
        )
    out.append(_table(rows, ["Area", "Formats", "Read", "Write"]))
    out.append("")
    out.append("## What works, and what is left")
    out.append("")
    out.append("Engine formats only, worst first. Open formats are listed at the end for completeness.")
    out.append("")

    order = {"high": 0, "medium": 1, "low": 2, "none": 3}
    engine_entries = [e for e in entries if e["origin"] in {"proprietary", "third_party"}]
    engine_entries.sort(key=lambda e: (order[str(e["priority"])], str(e["extension"])))
    rows = []
    for entry in engine_entries:
        remaining = str(entry["remaining"]).strip() or "Nothing outstanding."
        rows.append(
            [
                f"`{entry['extension']}`",
                str(entry["decode"]),
                str(entry["write"]),
                str(entry["priority"]),
                remaining,
            ]
        )
    out.append(_table(rows, ["Format", "Read", "Write", "Priority", "What is left"]))
    out.append("")
    out.append("### Open formats")
    out.append("")
    open_entries = [e for e in entries if e["origin"] not in {"proprietary", "third_party"}]
    open_entries.sort(key=lambda e: str(e["extension"]))
    out.append(
        ", ".join(
            f"`{e['extension']}` ({e['decode']}/{e['write']})" for e in open_entries
        )
        + "."
    )
    out.append("")
    out.append("## Highest-value gaps")
    out.append("")
    out.append("Every format marked `high`: closing it opens a modding category that is currently at zero.")
    out.append("")
    for gap in progress["open_high_priority_gaps"]:
        out.append(f"- **`{gap['extension']}`** (read {gap['decode']}, write {gap['write']}) — {gap['remaining']}")
    out.append("")
    out.append("## Rubric")
    out.append("")
    for axis in ("decode", "write", "origin", "priority"):
        out.append(f"**{axis}**")
        out.append("")
        for key, description in RUBRIC[axis].items():  # type: ignore[index]
            out.append(f"- `{key}` — {description}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate the progress block and the report")
    args = parser.parse_args(argv)

    manifest = load_manifest()
    entries = list(manifest["extensions"])
    validate(entries)
    progress = summarize(entries)

    if args.write:
        write_manifest_progress(progress)
        REPORT_PATH.write_text(render_report(manifest), encoding="utf-8")
        headline = progress["headline"]["engine_formats"]
        print(
            f"wrote {MANIFEST_PATH.name} progress and {REPORT_PATH.name}: "
            f"{headline['extensions']} engine formats, "
            f"read {headline['decode_percent']}%, write {headline['write_percent']}%"
        )
        return 0

    stored = manifest.get("progress")
    if stored != progress:
        print("manifest progress block is stale; run: python tools/report_format_decode_progress.py --write")
        return 1
    expected = render_report(manifest)
    if not REPORT_PATH.exists() or REPORT_PATH.read_text(encoding="utf-8") != expected:
        print(f"{REPORT_PATH} is stale; run: python tools/report_format_decode_progress.py --write")
        return 1
    print("format decode progress is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
