"""Import details as short, grouped lines instead of one paragraph per part."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from cdmw.ui.new_item.ui_kit import WARN, note

# Lines written by cdmw.modding.mesh_skinning for each transferred target.
_TRANSFERRED = re.compile(
    r"^Skin weights target \d+ \((?P<label>.*)\): transferred (?P<count>[\d,]+) vertices; "
    r"surface-distance p95 (?P<p95>[\d.eE+-]+) \(limit (?P<limit>[\d.eE+-]+)\)\.$")
_FAR = re.compile(r"^Warning: skin weights for target \d+ \((?P<label>.*)\) were matched from far off")


def _part_lines(report) -> list:
    name = str(report.part_name or f"Part {report.part_index + 1}")
    if report.policy not in {"transfer", "body_transfer"}:
        text = f"• {name}: imported weights kept"
        if report.policy == "reduce" and report.reduced_vertices:
            text += (f"; reduced {report.reduced_vertices:,} vertices, up to {report.maximum_removed_mass:.1%} "
                     "weight removed")
        tone = WARN if report.over_five_percent else None
        return [note(text, tone)]
    lines, transferred, far = [], 0, set()
    others = []
    for detail in report.transfer_details:
        text = str(detail)
        if match := _TRANSFERRED.match(text):
            transferred += int(match["count"].replace(",", ""))
        elif match := _FAR.match(text):
            far.add(match["label"])
        else:
            others.append(text)
    lines.append(note(f"• {name}: {transferred:,} vertices weighted from the template" if transferred
                      else f"• {name}: weighted from the template"))
    if far:
        lines.append(note(f"    Matched far from the template's surface ({len(far)} target(s)); check how it bends.", WARN))
    lines.extend(note(f"    {text}", WARN if "not match" in text or "Warning" in text else None) for text in others)
    return lines


def import_detail_lines(source) -> list:
    """(text, tone) rows for Import details: the file, its weights per part, then file notes."""

    reports = tuple(getattr(source, "skinning_reports", ()) or ())
    summaries = {report.summary() for report in reports}
    lines = []
    if reports:
        donors = sorted({PurePosixPath(str(r.donor_path or r.target_path)).name
                         for r in reports if r.policy in {"transfer", "body_transfer"}})
        if donors:
            lines.append(note("Weights: taken from " + ", ".join(donors)
                              + ". Check rigid pieces, close layers and distant surfaces in the preview."))
        else:
            lines.append(note("Weights: the model's own weights, in the game's bind pose."))
        for report in reports:
            lines.extend(_part_lines(report))
    notes = [str(text) for text in getattr(source, "notes", ()) if str(text) not in summaries]
    if notes:
        lines.append(note("File: what the reader found"))
        lines.extend(note("• " + text.strip(), WARN if text.strip().startswith("Warning") else None) for text in notes)
    return lines


def build_note_lines(notes) -> list:
    """Apply placement's notes as bullets; per-target weight lines already shown above are dropped."""

    lines, far = [], 0
    for text in (str(value).strip() for value in notes or ()):
        if not text or _TRANSFERRED.match(text):
            continue
        if _FAR.match(text):
            far += 1
            continue
        lines.append(note("• " + text, WARN if text.startswith("Warning") else None))
    if far:
        lines.append(note(f"• {far} weight target(s) matched far from the template's surface; check how they bend.", WARN))
    return lines
