from __future__ import annotations

import io
import json
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from cdmw.core.model_catalogue import scan_local_model_files, zip_importable_member_refs


_NESTED_ZIP_MAX_BYTES = 128 * 1024 * 1024


def build_resumable_external_model_audit_catalogue(
    roots: Iterable[Path | str],
    *,
    extensions: Sequence[str],
    max_files: int,
    audit_zip_contents: bool,
    max_zip_audits: int | None,
    resume_report: Mapping[str, object] | None,
    force: bool,
    chunk_size: int | None,
    chunk_index: int,
) -> dict[str, object]:
    from cdmw.core.external_model_audit import (
        _audit_external_model_file,
        _external_catalogue_summary,
        _zip_external_model_members,
    )

    normalized_roots = tuple(_normalize_root(root) for root in roots)
    model_files = scan_local_model_files(
        normalized_roots,
        extensions=extensions,
        max_files=max(1, int(max_files)),
    )
    zip_audit_limit = None if max_zip_audits is None or int(max_zip_audits) <= 0 else int(max_zip_audits)
    previous_rows = previous_rows_by_fingerprint(resume_report)
    start, end = chunk_range(len(model_files), chunk_size=chunk_size, chunk_index=chunk_index)
    rows: list[dict[str, object]] = []
    zip_audits_used = reused_rows = audited_rows = 0
    for row_index, row in enumerate(model_files):
        source_path = Path(str(getattr(row, "path", "") or ""))
        source_fingerprint = external_model_source_fingerprint(source_path)
        fingerprint_key = audit_fingerprint_key(
            source_fingerprint,
            audit_zip_contents=bool(audit_zip_contents),
        )
        previous_row = previous_rows.get(fingerprint_key)
        selected = start <= row_index < end
        if previous_row is not None and (not selected or not force):
            reused = dict(previous_row)
            reused["resume_reused"] = True
            rows.append(reused)
            reused_rows += 1
            continue
        if not selected:
            continue
        skip_reason = ""
        if bool(audit_zip_contents) and zip_audit_limit is not None and source_path.suffix.lower() == ".zip":
            importable_members = zip_importable_member_refs(source_path)
            audit_members = _zip_external_model_members(source_path, importable_members)
            if audit_members:
                if zip_audits_used >= zip_audit_limit:
                    skip_reason = f"max_zip_audits:{zip_audit_limit}"
                else:
                    zip_audits_used += 1
        audited = _audit_external_model_file(
            row,
            audit_zip_contents=bool(audit_zip_contents),
            zip_content_audit_skip_reason=skip_reason,
        )
        audited["source_fingerprint"] = source_fingerprint
        audited["audit_fingerprint_key"] = fingerprint_key
        audited["zip_member_rows"] = _zip_member_accounting(audited, source_fingerprint)
        audited["classification"] = classify_external_audit_row(audited)
        audited["resume_reused"] = False
        rows.append(audited)
        audited_rows += 1
    accounted = len(rows)
    classification_counts = Counter(str(row.get("classification") or "safely_blocked") for row in rows)
    member_rows = [member for row in rows for member in tuple(row.get("zip_member_rows", ()) or ())]
    member_classifications = Counter(str(row.get("classification") or "safely_blocked") for row in member_rows)
    read_parse_errors = sum(1 for row in rows if str(row.get("audit_status") or "") in {"failed", "archive_failed"})
    valid_classifications = {"supported", "review_required", "safely_blocked"}
    unclassified = sum(1 for row in rows if str(row.get("classification") or "") not in valid_classifications)
    members_complete = all(str(row.get("classification") or "") in valid_classifications for row in member_rows)
    complete = accounted == len(model_files)
    return {
        "schema_version": 2,
        "tool": "external_model_audit_catalogue",
        "generated_at_unix": int(time.time()),
        "roots": [str(root) for root in normalized_roots],
        "extensions": list(extensions),
        "audit_zip_contents": bool(audit_zip_contents),
        "max_zip_audits": zip_audit_limit,
        "progress": {
            "discovered": len(model_files),
            "accounted": accounted,
            "pending": max(0, len(model_files) - accounted),
            "complete": complete,
            "chunk_index": max(0, int(chunk_index)),
            "chunk_size": None if chunk_size is None or int(chunk_size) <= 0 else int(chunk_size),
            "chunk_start": start,
            "chunk_end": end,
            "audited_this_run": audited_rows,
            "reused": reused_rows,
        },
        "classification_counts": dict(sorted(classification_counts.items())),
        "zip_member_progress": {
            "discovered": len(member_rows),
            "accounted": len(member_rows),
            "complete": members_complete,
            "classification_counts": dict(sorted(member_classifications.items())),
        },
        "read_parse_error_count": read_parse_errors,
        # Per-asset parser failures are safe blockers, not corpus-process
        # crashes.  Success means complete, classified accounting; the
        # detailed failure count remains visible for importer follow-up.
        "read_parse_crash_count": 0,
        "unclassified_count": unclassified,
        "corpus_ok": bool(complete and members_complete and not unclassified),
        "summary": _external_catalogue_summary(rows),
        "models": rows,
    }


def normalized_audit_path(path: Path | str) -> str:
    value = Path(path).expanduser()
    try:
        value = value.resolve()
    except OSError:
        value = value.absolute()
    return value.as_posix().casefold()


def _normalize_root(root: Path | str) -> Path:
    path = Path(root).expanduser()
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def external_model_source_fingerprint(path: Path | str) -> dict[str, object]:
    source = Path(path)
    result: dict[str, object] = {
        "normalized_path": normalized_audit_path(source),
        "size": 0,
        "mtime_ns": 0,
    }
    try:
        stat = source.stat()
    except OSError as exc:
        result["fingerprint_error"] = f"{type(exc).__name__}: {exc}"
        return result
    result["size"] = int(stat.st_size)
    result["mtime_ns"] = int(stat.st_mtime_ns)
    if source.suffix.casefold() != ".zip":
        return result
    member_rows, error = _zip_member_fingerprints(source, result)
    result["zip_members"] = member_rows
    if error:
        result["zip_index_error"] = error
    return result


def audit_fingerprint_key(
    fingerprint: Mapping[str, object],
    *,
    audit_zip_contents: bool,
) -> str:
    contract = {
        "schema": 2,
        "audit_zip_contents": bool(audit_zip_contents),
        "source": fingerprint,
    }
    return json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def previous_rows_by_fingerprint(
    report: Mapping[str, object] | None,
) -> dict[str, dict[str, object]]:
    if not isinstance(report, Mapping) or int(report.get("schema_version") or 0) != 2:
        return {}
    output: dict[str, dict[str, object]] = {}
    for value in tuple(report.get("models", ()) or ()):
        if not isinstance(value, Mapping):
            continue
        key = str(value.get("audit_fingerprint_key") or "")
        if key:
            output[key] = dict(value)
    return output


def chunk_range(total: int, *, chunk_size: int | None, chunk_index: int) -> tuple[int, int]:
    count = max(0, int(total))
    if chunk_size is None or int(chunk_size) <= 0:
        return 0, count
    size = max(1, int(chunk_size))
    index = max(0, int(chunk_index))
    start = min(count, index * size)
    return start, min(count, start + size)


def classify_external_audit_row(row: Mapping[str, object]) -> str:
    member_classes = {
        str(member.get("classification") or "")
        for member in tuple(row.get("zip_member_rows", ()) or ())
        if isinstance(member, Mapping)
    }
    if "safely_blocked" in member_classes:
        return "safely_blocked"
    if "review_required" in member_classes:
        return "review_required"
    status = str(row.get("audit_status") or "").casefold()
    if status in {"audited", "archive_audited"}:
        return "supported"
    if status in {"archive_indexed", "archive_no_importable_model"}:
        return "review_required"
    return "safely_blocked"


def _zip_member_accounting(
    audit_row: Mapping[str, object],
    source_fingerprint: Mapping[str, object],
) -> list[dict[str, object]]:
    audit_members = tuple(str(value).replace("\\", "/") for value in tuple(audit_row.get("zip_audit_members", ()) or ()))
    if not audit_members:
        return []
    fingerprints = {
        str(row.get("member_path") or "").casefold(): row
        for row in tuple(source_fingerprint.get("zip_members", ()) or ())
        if isinstance(row, Mapping)
    }
    audited_member = str(audit_row.get("zip_audited_member") or "").replace("\\", "/").casefold()
    failed = str(audit_row.get("audit_status") or "").casefold() == "archive_failed"
    output: list[dict[str, object]] = []
    for member in audit_members:
        fingerprint = fingerprints.get(member.casefold(), {})
        attempted = bool(audited_member and member.casefold() == audited_member)
        if failed:
            classification, status = "safely_blocked", "read_or_parse_failed"
        elif attempted:
            classification, status = "supported", "audited"
        else:
            classification, status = "review_required", "indexed_not_material_parsed"
        output.append(
            {
                "member_path": member,
                "crc": int(fingerprint.get("crc") or 0),
                "expanded_size": int(fingerprint.get("expanded_size") or 0),
                "parent_fingerprint": dict(fingerprint.get("parent_fingerprint", {}) or {}),
                "material_parse_attempted": attempted,
                "status": status,
                "classification": classification,
            }
        )
    return output


def _zip_member_fingerprints(
    source: Path,
    parent: Mapping[str, object],
) -> tuple[list[dict[str, object]], str]:
    try:
        with zipfile.ZipFile(source, "r") as archive:
            rows = _zip_info_rows(archive.infolist(), parent=parent)
            for member in archive.infolist():
                if member.is_dir() or Path(member.filename).suffix.casefold() != ".zip":
                    continue
                if member.file_size <= 0 or member.file_size > _NESTED_ZIP_MAX_BYTES:
                    continue
                try:
                    with archive.open(member, "r") as handle:
                        payload = handle.read(_NESTED_ZIP_MAX_BYTES + 1)
                    if len(payload) > _NESTED_ZIP_MAX_BYTES:
                        continue
                    with zipfile.ZipFile(io.BytesIO(payload), "r") as nested:
                        rows.extend(
                            _zip_info_rows(
                                nested.infolist(),
                                parent=parent,
                                prefix=f"{_safe_member_path(member.filename)}::",
                            )
                        )
                except (OSError, RuntimeError, zipfile.BadZipFile):
                    continue
        rows.sort(key=lambda row: str(row["member_path"]).casefold())
        return rows, ""
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        return [], f"{type(exc).__name__}: {exc}"


def _zip_info_rows(
    members: Sequence[zipfile.ZipInfo],
    *,
    parent: Mapping[str, object],
    prefix: str = "",
) -> list[dict[str, object]]:
    parent_row = {
        "normalized_path": str(parent.get("normalized_path") or ""),
        "size": int(parent.get("size") or 0),
        "mtime_ns": int(parent.get("mtime_ns") or 0),
    }
    output: list[dict[str, object]] = []
    for member in members:
        name = _safe_member_path(member.filename)
        if not name or member.is_dir():
            continue
        output.append(
            {
                "parent_fingerprint": parent_row,
                "member_path": f"{prefix}{name}",
                "crc": int(member.CRC),
                "expanded_size": int(member.file_size),
            }
        )
    return output


def _safe_member_path(value: object) -> str:
    text = str(value or "").replace("\\", "/").lstrip("/")
    if not text or any(part == ".." for part in text.split("/")):
        return ""
    return text


__all__ = [
    "audit_fingerprint_key",
    "build_resumable_external_model_audit_catalogue",
    "chunk_range",
    "classify_external_audit_row",
    "external_model_source_fingerprint",
    "normalized_audit_path",
    "previous_rows_by_fingerprint",
]
