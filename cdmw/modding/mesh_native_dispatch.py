from __future__ import annotations

from array import array
import ctypes
import dataclasses
from importlib import import_module
import json
import math
import os
import queue
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence
from uuid import uuid4

from cdmw.core.common import ProcessTimeoutExpired
from cdmw.modding.mesh_deformer import MeshFaceDeleteResult, MeshPartSplitResult
from cdmw.modding.mesh_native_core_constants import (
    Face,
    NATIVE_MESH_CORE_BACKEND_ID,
    NATIVE_MESH_CORE_BINARY_NAME,
    NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR,
    Vec2,
    Vec3,
    _NATIVE_MATERIAL_REPORT_ATTRS,
    _NATIVE_MESH_EDITOR_NORMAL_OPERATIONS,
    _NATIVE_MESH_SESSION_TOKEN_ATTR,
    _NATIVE_PREVIEW_MATERIAL_OVERRIDE_KEYS,
    _TRANSIENT_NATIVE_SUBMESH_ATTRS,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.models import RunCancelled


def _proxy(name: str):
    def call(*args, **kwargs):
        return getattr(import_module("cdmw.modding.mesh_native_core"), name)(*args, **kwargs)

    return call

_get_native_mesh_core_service = _proxy("_get_native_mesh_core_service")
_native_mesh_core_service_enabled = _proxy("_native_mesh_core_service_enabled")
run_process_with_cancellation = _proxy("run_process_with_cancellation")
shutdown_native_mesh_core_service = _proxy("shutdown_native_mesh_core_service")


def _native_job_kwargs(*, stop_event: threading.Event | None, timeout_seconds: float) -> dict[str, object]:
    kwargs: dict[str, object] = {"timeout_seconds": timeout_seconds}
    if stop_event is not None:
        kwargs["stop_event"] = stop_event
    return kwargs

def _run_native_mesh_core_service_job(
    binary: Path,
    command: str,
    payload: Mapping[str, object],
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float,
) -> dict[str, object] | None:
    if str(command or "").strip().lower() == "mesh-editor-session-json":
        return _run_native_mesh_core_service_inline_job(
            binary,
            command,
            payload,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
    job_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_service_"))
    job_path = job_root / "job.json"
    report_path = job_root / "report.json"
    try:
        job_path.write_text(json.dumps(dict(payload), separators=(",", ":"), allow_nan=False), encoding="utf-8")
        service_kwargs: dict[str, object] = {"timeout_seconds": max(0.5, float(timeout_seconds))}
        if stop_event is not None:
            service_kwargs["stop_event"] = stop_event
        _get_native_mesh_core_service(binary).run_job(
            command,
            job_path,
            report_path,
            **service_kwargs,
        )
        if not report_path.is_file():
            return None
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(report, dict) or str(report.get("status") or "").lower() != "ok":
            return None
        return report
    except RunCancelled:
        raise
    except Exception:
        shutdown_native_mesh_core_service()
        return None
    finally:
        shutil.rmtree(job_root, ignore_errors=True)

def _run_native_mesh_core_service_inline_job(
    binary: Path,
    command: str,
    payload: Mapping[str, object],
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float,
) -> dict[str, object] | None:
    _LAST_NATIVE_JOB_REJECTION[0] = ""
    try:
        response = _get_native_mesh_core_service(binary).run_inline_job(
            command,
            payload,
            timeout_seconds=max(0.5, float(timeout_seconds)),
            stop_event=stop_event,
        )
        report = response.get("inline_report")
        if not isinstance(report, dict):
            # This is the path every live stroke takes, and it was the one layer
            # with no account of itself: a refused stroke reported "native
            # apply returned no report" with nothing behind it, because the
            # instrumentation sat on the other runner.
            _note_native_job_failure(
                command,
                f"inline response carried {type(report).__name__} instead of a report; "
                f"keys={sorted(str(key) for key in response)[:8]}",
            )
            return None
        status = str(report.get("status") or "").lower()
        if status != "ok":
            detail = str(report.get("error") or report.get("message") or report.get("reason") or "").strip()
            # A structured non-ok report is the native core answering "no", not
            # the native core failing: the process replied and its session state
            # is untouched. Record the rejection separately so callers can keep
            # the session alive and show the native reason instead of tearing
            # the session down as lost.
            if detail:
                _LAST_NATIVE_JOB_REJECTION[0] = detail
            _note_native_job_failure(
                command,
                f"inline status {status or 'missing'}" + (f": {detail}" if detail else " with no message"),
            )
            return None
        _LAST_NATIVE_JOB_ERROR[0] = ""
        return report
    except RunCancelled:
        raise
    except Exception as exc:
        _note_native_job_failure(command, f"inline {type(exc).__name__}: {exc}")
        shutdown_native_mesh_core_service()
        return None

# Every native mesh job in the application funnels through the runner below, and
# it answers None for five different reasons: the process failed, it wrote no
# report, the report would not parse, the report said something other than ok, or
# something else raised. Around a hundred callers turn that None into a falsy
# result of their own, so by the time it reaches a user the only thing left is
# that "something native failed". The reason is kept here instead. Native jobs
# run one at a time per call, and this is diagnostic only, so a single slot is
# enough; the alternative is threading an error out through a hundred signatures.
_LAST_NATIVE_JOB_ERROR: list[str] = [""]


def last_native_mesh_core_job_error() -> str:
    """Why the most recent native mesh job answered None, if it did."""

    return _LAST_NATIVE_JOB_ERROR[0]


# A rejection is the subset of job failures where the native core itself wrote a
# structured non-ok report: the process is alive and its resident session state
# is exactly as it was, because every session command validates and throws
# before its first mutation. Kept apart from _LAST_NATIVE_JOB_ERROR so callers
# can tell "the native core said no, and why" from "the native core is gone".
_LAST_NATIVE_JOB_REJECTION: list[str] = [""]


def last_native_mesh_core_job_rejection() -> str:
    """The native core's own reason for refusing the most recent job, if it did."""

    return _LAST_NATIVE_JOB_REJECTION[0]


def _note_native_job_failure(command: str, reason: str) -> None:
    _LAST_NATIVE_JOB_ERROR[0] = f"{command}: {reason}"


def _run_native_mesh_core_job(
    binary: Path,
    command: str,
    payload: Mapping[str, object],
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float,
) -> dict[str, object] | None:
    job_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_"))
    job_path = job_root / "job.json"
    report_path = job_root / "report.json"
    try:
        job_path.write_text(json.dumps(dict(payload), separators=(",", ":"), allow_nan=False), encoding="utf-8")
        returncode = 0
        use_service = _native_mesh_core_service_enabled(stop_event=stop_event)
        if use_service:
            try:
                service_kwargs: dict[str, object] = {"timeout_seconds": max(0.5, float(timeout_seconds))}
                if stop_event is not None:
                    service_kwargs["stop_event"] = stop_event
                _get_native_mesh_core_service(binary).run_job(
                    command,
                    job_path,
                    report_path,
                    **service_kwargs,
                )
            except ProcessTimeoutExpired:
                raise
            except RunCancelled:
                raise
            except Exception:
                shutdown_native_mesh_core_service()
                returncode, _stdout, _stderr = run_process_with_cancellation(
                    [str(binary), command, str(job_path), str(report_path)],
                    stop_event=stop_event,
                    timeout_seconds=max(0.5, float(timeout_seconds)),
                )
        else:
            returncode, _stdout, _stderr = run_process_with_cancellation(
                [str(binary), command, str(job_path), str(report_path)],
                stop_event=stop_event,
                timeout_seconds=max(0.5, float(timeout_seconds)),
            )
        if returncode != 0:
            _note_native_job_failure(command, f"native process exited {returncode}")
            return None
        if not report_path.is_file():
            _note_native_job_failure(command, "native process wrote no report")
            return None
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _note_native_job_failure(command, f"report unreadable: {type(exc).__name__}: {exc}")
            return None
        if not isinstance(report, dict):
            _note_native_job_failure(command, f"report was {type(report).__name__}, not an object")
            return None
        status = str(report.get("status") or "").lower()
        if status != "ok":
            # The native side says why it refused, in its own words, and this is
            # the only place that text exists. Discarding it is what left a
            # refused stroke describable only as "something native failed".
            detail = str(report.get("error") or report.get("message") or report.get("reason") or "").strip()
            _note_native_job_failure(
                command,
                f"native status {status or 'missing'}" + (f": {detail}" if detail else " with no message"),
            )
            return None
        _LAST_NATIVE_JOB_ERROR[0] = ""
        return report
    except RunCancelled:
        raise
    except Exception as exc:
        _note_native_job_failure(command, f"{type(exc).__name__}: {exc}")
        return None
    finally:
        shutil.rmtree(job_root, ignore_errors=True)
