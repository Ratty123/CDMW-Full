from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence

from cdmw.core import texture_native as backend
from cdmw.core.texture_decode_cache import preview_staging_dir, publish_preview_pair
from cdmw.models import RunCancelled


def add_preview_result(
    results: Dict[str, Path],
    job: Mapping[str, object],
    output_path: Path,
    include_job_keys: bool,
) -> None:
    results[str(job["input"])] = output_path
    if include_job_keys:
        results[str(job["result_key"])] = output_path


def ensure_preview_batch_locked(
    binary: Path,
    jobs: Sequence[Mapping[str, object]],
    results: Dict[str, Path],
    *,
    timeout_seconds: float,
    include_job_keys: bool,
    stop_event: Optional[threading.Event],
) -> Dict[str, Path]:
    pending: list[Mapping[str, object]] = []
    for job in jobs:
        output = Path(str(job["output"]))
        if backend._cached_preview_is_valid(output):
            add_preview_result(results, job, output, include_job_keys)
        else:
            pending.append(job)
    if not pending:
        return results
    staging_parent = Path(str(pending[0]["output"])).parent
    with preview_staging_dir(staging_parent) as job_root:
        job_path = job_root / "job.json"
        report_path = job_root / "report.json"
        staged_by_output: Dict[str, tuple[Mapping[str, object], Path]] = {}
        helper_jobs: list[Dict[str, object]] = []
        for index, job in enumerate(pending):
            staged = job_root / f"{index:04d}-{Path(str(job['output'])).name}"
            helper_job = {key: value for key, value in job.items() if key not in {"result_key", "cache_key"}}
            helper_job["output"] = str(staged)
            helper_jobs.append(helper_job)
            staged_by_output[str(staged.resolve())] = (job, staged)
        job_path.write_text(
            json.dumps({"version": 1, "backend": backend.DIRECTXTEX_TEXTURE_BACKEND_ID, "jobs": helper_jobs}, indent=2),
            encoding="utf-8",
        )
        try:
            backend.raise_if_cancelled(stop_event, "DirectXTex preview conversion cancelled.")
            returncode, _stdout, stderr = backend.run_process_with_cancellation(
                [str(binary), "batch-preview-json", str(job_path), str(report_path), *backend._native_diagnostic_args()],
                timeout_seconds=max(1.0, float(timeout_seconds)),
                stop_event=stop_event,
            )
        except RunCancelled:
            raise
        except Exception as exc:
            backend._record_directxtex_failure(
                binary=binary,
                operation="batch-preview-json",
                returncode="exception",
                stderr=str(exc),
                fallback_available=True,
                reason=type(exc).__name__,
            )
            return results
        items = read_preview_items(binary, report_path, returncode, stderr)
        if items is None:
            return results
        published = False
        for item in items:
            if not isinstance(item, dict) or str(item.get("status") or "").lower() != "decoded":
                continue
            try:
                matched = staged_by_output.get(str(Path(str(item.get("output_path") or item.get("output") or "")).resolve()))
            except OSError:
                matched = None
            if matched is None:
                continue
            job, staged = matched
            item.setdefault("backend", backend.DIRECTXTEX_TEXTURE_BACKEND_ID)
            item.setdefault("native_backend", "directxtex")
            item["source_path"] = str(job["input"])
            try:
                output = publish_preview_pair(staged, Path(str(job["output"])), item)
            except (OSError, ValueError) as exc:
                backend._record_directxtex_failure(
                    binary=binary,
                    operation="batch-preview-json",
                    returncode="publication_failed",
                    stderr=str(exc),
                    source_path=job["input"],
                    fallback_available=True,
                    reason="atomic_publication_failed",
                )
                continue
            add_preview_result(results, job, output, include_job_keys)
            published = True
        if published:
            backend.request_app_temp_cache_prune()
        return results


def read_preview_items(
    binary: Path,
    report_path: Path,
    returncode: object,
    stderr: object,
    *,
    source_path: object = "",
) -> Optional[list[object]]:
    reason = ""
    if returncode != 0 or not report_path.is_file():
        reason = "missing_report" if not report_path.is_file() else "nonzero_returncode"
    else:
        try:
            parsed = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parsed = None
            stderr = str(exc)
            reason = "invalid_report_json"
        if not reason:
            items = parsed.get("items") if isinstance(parsed, dict) else None
            if isinstance(items, list):
                return items
            reason = "missing_report_items"
    backend._record_directxtex_failure(
        binary=binary,
        operation="batch-preview-json",
        returncode=returncode,
        stderr=stderr,
        source_path=source_path,
        fallback_available=True,
        reason=reason,
    )
    return None
