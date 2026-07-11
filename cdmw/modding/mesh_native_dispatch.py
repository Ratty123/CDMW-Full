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
    try:
        response = _get_native_mesh_core_service(binary).run_inline_job(
            command,
            payload,
            timeout_seconds=max(0.5, float(timeout_seconds)),
            stop_event=stop_event,
        )
        report = response.get("inline_report")
        if not isinstance(report, dict) or str(report.get("status") or "").lower() != "ok":
            return None
        return report
    except RunCancelled:
        raise
    except Exception:
        shutdown_native_mesh_core_service()
        return None

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
        if returncode != 0 or not report_path.is_file():
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
        return None
    finally:
        shutil.rmtree(job_root, ignore_errors=True)
