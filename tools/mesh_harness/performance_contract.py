from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import stat
import time
from types import SimpleNamespace
from uuid import uuid4

from tools.mesh_harness.archive_provenance import _archive_content_fingerprints
from tools.mesh_harness.constants import _REAL_MESH_EDITOR_VISUAL_SCENARIO
from tools.mesh_harness.evidence import _write_json_atomic


PERFORMANCE_MANIFEST_SCHEMA = "cdmw_dotnet_preview_performance_manifest_v1"
PERFORMANCE_REPORT_SCHEMA = "cdmw_dotnet_preview_performance_v1"
PERFORMANCE_HARNESS_EVIDENCE_SCHEMA = "cdmw_dotnet_preview_performance_harness_v1"
DEFAULT_PERFORMANCE_DURATION_SECONDS = 30.0
DEFAULT_PERFORMANCE_TARGET_HZ = 144.0

_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_REPORT_BYTES = 64 * 1024 * 1024
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_ROOT_KEYS = frozenset({"schema", "capture", "asset", "interactions"})
_CAPTURE_KEYS = frozenset({"name", "warmup_frames", "width", "height", "repetition"})
_ASSET_KEYS = frozenset({"model_path", "corpus_role"})
_INTERACTION_KEYS = frozenset({"name", "input_rate_hz"})
SUPPORTED_PERFORMANCE_INTERACTIONS = frozenset(
    {
        "textured-orbit-pan-zoom",
        "side-by-side",
        "wire-vertices-part-highlight",
        "selection-brush-burst",
        "material-update",
        "texture-update",
        "topology-update",
        "resize-stress",
    }
)


class PerformanceContractError(ValueError):
    """Raised before a visible harness run when its performance contract is invalid."""


@dataclass(frozen=True, slots=True)
class PerformanceInteraction:
    name: str
    input_rate_hz: float

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "input_rate_hz": self.input_rate_hz}


@dataclass(frozen=True, slots=True)
class PerformanceManifest:
    path: Path
    sha256: str
    capture_name: str
    asset_model_path: str
    corpus_role: str
    warmup_frames: int
    width: int
    height: int
    repetition: int
    interactions: tuple[PerformanceInteraction, ...]

    def as_evidence(self) -> dict[str, object]:
        return {
            "schema": PERFORMANCE_MANIFEST_SCHEMA,
            "path": str(self.path),
            "sha256": self.sha256,
            "capture_name": self.capture_name,
            "asset_model_path": self.asset_model_path,
            "corpus_role": self.corpus_role,
            "warmup_frames": self.warmup_frames,
            "width": self.width,
            "height": self.height,
            "repetition": self.repetition,
            "interactions": [interaction.as_dict() for interaction in self.interactions],
        }


@dataclass(frozen=True, slots=True)
class PerformanceRequest:
    manifest: PerformanceManifest
    duration_seconds: float
    target_hz: float

    def as_evidence(self) -> dict[str, object]:
        return {
            "duration_seconds": self.duration_seconds,
            "target_hz": self.target_hz,
            "manifest": self.manifest.as_evidence(),
        }


def resolve_performance_request(
    scenario: str,
    manifest_path: Path | str | None,
    *,
    duration_seconds: float | None = None,
    target_hz: float | None = None,
) -> PerformanceRequest | None:
    configured = manifest_path is not None or duration_seconds is not None or target_hz is not None
    if not configured:
        return None
    if scenario != _REAL_MESH_EDITOR_VISUAL_SCENARIO:
        raise PerformanceContractError(
            "Performance capture options are valid only with "
            f"--scenario {_REAL_MESH_EDITOR_VISUAL_SCENARIO}."
        )
    if manifest_path is None:
        raise PerformanceContractError(
            "--performance-manifest is required when performance duration or target Hz is configured."
        )
    manifest = load_performance_manifest(Path(manifest_path))
    duration = _finite_number(
        DEFAULT_PERFORMANCE_DURATION_SECONDS if duration_seconds is None else duration_seconds,
        "performance duration seconds",
        minimum=0.1,
        maximum=600.0,
    )
    target = _finite_number(
        DEFAULT_PERFORMANCE_TARGET_HZ if target_hz is None else target_hz,
        "performance target Hz",
        minimum=30.0,
        maximum=360.0,
    )
    return PerformanceRequest(manifest=manifest, duration_seconds=duration, target_hz=target)


def load_performance_manifest(path: Path) -> PerformanceManifest:
    manifest_path = Path(path).expanduser()
    _require_plain_file(manifest_path, label="Performance manifest")
    if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
        raise PerformanceContractError(
            f"Performance manifest exceeds {_MAX_MANIFEST_BYTES} bytes."
        )
    raw = manifest_path.read_bytes()
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise PerformanceContractError(
            f"Performance manifest exceeds {_MAX_MANIFEST_BYTES} bytes."
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PerformanceContractError("Performance manifest must be UTF-8 JSON.") from exc
    payload = _load_json_object(text, label="Performance manifest")
    _require_exact_keys(payload, _ROOT_KEYS, "Performance manifest")
    if payload.get("schema") != PERFORMANCE_MANIFEST_SCHEMA:
        raise PerformanceContractError(
            f"Performance manifest schema must be {PERFORMANCE_MANIFEST_SCHEMA}."
        )

    capture = _mapping(payload.get("capture"), "Performance manifest capture")
    _require_exact_keys(capture, _CAPTURE_KEYS, "Performance manifest capture")
    capture_name = _safe_token(capture.get("name"), "capture name")
    warmup_frames = _integer(capture.get("warmup_frames"), "warmup_frames", 0, 10_000)
    width = _integer(capture.get("width"), "width", 64, 7680)
    height = _integer(capture.get("height"), "height", 64, 4320)
    repetition = _integer(capture.get("repetition"), "repetition", 1, 100)

    asset = _mapping(payload.get("asset"), "Performance manifest asset")
    _require_exact_keys(asset, _ASSET_KEYS, "Performance manifest asset")
    asset_model_path = _archive_path(asset.get("model_path"))
    corpus_role = _safe_token(asset.get("corpus_role"), "corpus role")

    interaction_rows = payload.get("interactions")
    if not isinstance(interaction_rows, Sequence) or isinstance(interaction_rows, (str, bytes)):
        raise PerformanceContractError("Performance manifest interactions must be a JSON array.")
    if not 1 <= len(interaction_rows) <= 64:
        raise PerformanceContractError("Performance manifest requires 1 to 64 interactions.")
    interactions: list[PerformanceInteraction] = []
    for index, row in enumerate(interaction_rows):
        interaction = _mapping(row, f"Performance interaction {index}")
        _require_exact_keys(interaction, _INTERACTION_KEYS, f"Performance interaction {index}")
        interaction_name = _safe_token(interaction.get("name"), f"interaction {index} name")
        if interaction_name not in SUPPORTED_PERFORMANCE_INTERACTIONS:
            raise PerformanceContractError(
                f"Performance interaction {interaction_name!r} is unsupported; expected one of "
                + ", ".join(sorted(SUPPORTED_PERFORMANCE_INTERACTIONS))
                + "."
            )
        interactions.append(
            PerformanceInteraction(
                name=interaction_name,
                input_rate_hz=_finite_number(
                    interaction.get("input_rate_hz"),
                    f"interaction {index} input_rate_hz",
                    minimum=1.0,
                    maximum=1000.0,
                ),
            )
        )
    resolved = manifest_path.resolve(strict=True)
    return PerformanceManifest(
        path=resolved,
        sha256=sha256(raw).hexdigest(),
        capture_name=capture_name,
        asset_model_path=asset_model_path,
        corpus_role=corpus_role,
        warmup_frames=warmup_frames,
        width=width,
        height=height,
        repetition=repetition,
        interactions=tuple(interactions),
    )


def run_performance_interaction_schedule(
    request: PerformanceRequest,
    *,
    begin: Callable[[PerformanceInteraction], bool],
    send: Callable[[PerformanceInteraction, int], bool],
    end: Callable[[PerformanceInteraction, int], bool],
    service: Callable[[], None],
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Drive every declared interaction at a monotonic rate without catch-up bursts."""
    interactions = request.manifest.interactions
    started = monotonic()
    segment_seconds = request.duration_seconds / len(interactions)
    rows: list[dict[str, object]] = []
    for index, interaction in enumerate(interactions):
        segment_start = started + index * segment_seconds
        segment_stop = started + (index + 1) * segment_seconds
        while monotonic() < segment_start:
            service()
            sleep(min(0.001, max(0.0, segment_start - monotonic())))
        begin_ok = bool(begin(interaction))
        interval = 1.0 / interaction.input_rate_hz
        next_due = segment_start
        sent = 0
        failed = 0
        skipped = 0
        maximum_lag_ms = 0.0
        while monotonic() < segment_stop:
            now = monotonic()
            if now + 1e-12 >= next_due:
                lag = max(0.0, now - next_due)
                maximum_lag_ms = max(maximum_lag_ms, lag * 1000.0)
                missed = max(0, int(lag // interval))
                skipped += missed
                next_due += (missed + 1) * interval
                ordinal = sent + failed + skipped + 1
                if send(interaction, ordinal):
                    sent += 1
                else:
                    failed += 1
            service()
            delay = min(0.001, max(0.0, next_due - monotonic()))
            if delay > 0.0:
                sleep(delay)
        end_ok = bool(end(interaction, sent))
        rows.append(
            {
                "name": interaction.name,
                "input_rate_hz": interaction.input_rate_hz,
                "segment_seconds": segment_seconds,
                "begin_ok": begin_ok,
                "events_sent": sent,
                "send_failures": failed,
                "schedule_slots_skipped": skipped,
                "maximum_schedule_lag_ms": maximum_lag_ms,
                "end_ok": end_ok,
            }
        )
    service()
    elapsed = max(0.0, monotonic() - started)
    return {
        "schema": "cdmw_dotnet_preview_performance_interactions_v1",
        "ok": bool(
            rows
            and all(
                row["begin_ok"]
                and row["end_ok"]
                and int(row["events_sent"]) > 0
                and int(row["send_failures"]) == 0
                for row in rows
            )
        ),
        "requested_duration_seconds": request.duration_seconds,
        "elapsed_seconds": elapsed,
        "interactions": rows,
    }


def begin_performance_capture(
    state: SimpleNamespace,
    request: PerformanceRequest,
    *,
    pump_until: Callable[[SimpleNamespace, Callable[[], bool], float | None], bool],
) -> str:
    evidence = _capture_evidence(state)
    evidence.clear()
    evidence.update(
        {
            "schema": PERFORMANCE_HARNESS_EVIDENCE_SCHEMA,
            "configured": True,
            "active": False,
            "ok": False,
            "request": request.as_evidence(),
        }
    )
    actual_model_path = str(getattr(getattr(state, "model_entry", None), "path", "") or "")
    if _normalized_archive_path(actual_model_path) != _normalized_archive_path(
        request.manifest.asset_model_path
    ):
        message = (
            "Performance manifest asset does not match the canonical resident PAC: "
            f"{request.manifest.asset_model_path!r} != {actual_model_path!r}."
        )
        evidence.update({"status": "rejected", "error": message})
        return message
    tab = getattr(state, "tab", None)
    capabilities = set(getattr(tab, "standalone_dotnet_capabilities", ()) or ())
    if "performance_capture_v1" not in capabilities:
        message = "Resident .NET helper does not advertise performance_capture_v1."
        evidence.update({"status": "unsupported", "error": message})
        return message
    session_id = str(getattr(tab, "standalone_dotnet_lifecycle_session_id", "") or "")
    process_generation = int(getattr(tab, "standalone_dotnet_process_generation", 0) or 0)
    if not session_id or process_generation <= 0:
        message = "Resident .NET performance capture has no live session/process correlation."
        evidence.update({"status": "uncorrelated", "error": message})
        return message
    package = getattr(tab, "standalone_dotnet_experiment_package", None)
    package_output_text = str(getattr(package, "output_dir", "") or "").strip()
    package_output = Path(package_output_text) if package_output_text else Path()
    if not package_output_text or not package_output.is_dir():
        message = "Resident .NET package output directory is unavailable."
        evidence.update({"status": "missing_package_output", "error": message})
        return message

    capture_id = f"{request.manifest.capture_name[:32]}-{uuid4().hex}"
    request_id = max(1, time.monotonic_ns() & 0x7FFF_FFFF_FFFF_FFFF)
    report_name = f"dotnet-preview-performance-{capture_id}.json"
    pid = _resident_pid(tab)
    window_identity = _resident_window_identity(state)
    asset_provenance = {
        "model_path": actual_model_path,
        "source_payload_sha256": str(getattr(state, "source_payload_sha256", "") or ""),
        "archive_provenance": dict(
            getattr(state, "archive_provenance", None)
            or _state_archive_provenance(state)
        ),
        "archive_content_fingerprints_before": dict(
            getattr(state, "archive_content_fingerprints_before", {}) or {}
        ),
        "performance_manifest": request.manifest.as_evidence(),
        "resident_process": {"pid": pid, **window_identity},
    }
    correlation = {
        "capture_id": capture_id,
        "session_id": session_id,
        "request_id": request_id,
        "process_generation": process_generation,
        "protocol_version": 2,
    }
    payload = {
        "event": "performance_capture_start",
        **correlation,
        "report_path": report_name,
        "duration_seconds": request.duration_seconds,
        "target_hz": request.target_hz,
        "warmup_frames": request.manifest.warmup_frames,
        "width": request.manifest.width,
        "height": request.manifest.height,
        "asset_provenance": asset_provenance,
    }
    cursor = len(tuple(getattr(tab, "standalone_dotnet_protocol_events", ()) or ()))
    if not bool(tab._send_dotnet_protocol_message(payload)):
        message = "Could not send performance_capture_start to the resident .NET helper."
        evidence.update({"status": "send_failed", "error": message})
        return message
    _flush_protocol(tab)
    response = _wait_correlated_event(
        state,
        correlation,
        {"performance_capture_started", "performance_capture_complete"},
        cursor,
        pump_until=pump_until,
        timeout_seconds=10.0,
    )
    if str(response.get("event", "")) != "performance_capture_started":
        message = str(response.get("message", "") or "Resident .NET performance capture did not start.")
        evidence.update({"status": str(response.get("status", "rejected") or "rejected"), "error": message})
        return message

    evidence.update(
        {
            "active": True,
            "status": "capturing",
            "capture_id": capture_id,
            "correlation": correlation,
            "helper_report_name": report_name,
            "package_output_dir": str(package_output.resolve()),
            "process_identity_start": {"pid": pid, **window_identity},
            "archive_content_fingerprints_before": dict(
                getattr(state, "archive_content_fingerprints_before", {}) or {}
            ),
            "asset_provenance": asset_provenance,
            "started_event": dict(response),
        }
    )
    state.performance_capture_started_monotonic = time.monotonic()
    state.performance_heartbeat_callback = _heartbeat_sender(state, correlation)
    return ""


def finish_performance_capture(
    state: SimpleNamespace,
    *,
    pump_until: Callable[[SimpleNamespace, Callable[[], bool], float | None], bool],
) -> str:
    evidence = _capture_evidence(state)
    if not evidence.get("active"):
        return str(evidence.get("error", "") or "")
    tab = getattr(state, "tab", None)
    correlation = dict(evidence.get("correlation", {}) or {})
    capture_id = str(correlation.get("capture_id", "") or "")
    cursor = len(tuple(getattr(tab, "standalone_dotnet_protocol_events", ()) or ()))
    payload = {"event": "performance_capture_stop", **correlation}
    evidence["active"] = False
    state.performance_heartbeat_callback = None
    if tab is None or not bool(tab._send_dotnet_protocol_message(payload)):
        message = "Could not send performance_capture_stop to the resident .NET helper."
        evidence.update({"status": "stop_send_failed", "error": message})
        return message
    _flush_protocol(tab)
    completion = _wait_correlated_event(
        state,
        correlation,
        {"performance_capture_complete"},
        cursor,
        pump_until=pump_until,
        timeout_seconds=30.0,
    )
    if not completion:
        message = "Resident .NET helper did not complete the performance report."
        evidence.update({"status": "completion_timeout", "error": message})
        return message
    if str(completion.get("schema", "") or "") != PERFORMANCE_REPORT_SCHEMA:
        message = "Resident .NET performance completion used an unsupported report schema."
        evidence.update({"status": "invalid_completion", "error": message})
        return message
    if str(completion.get("status", "") or "") in {"rejected", "error"}:
        message = str(completion.get("message", "") or "Resident .NET performance report failed.")
        evidence.update({"status": str(completion.get("status")), "error": message})
        return message
    try:
        report, helper_report_path, helper_sha = _read_completed_report(state, completion, evidence)
    except PerformanceContractError as exc:
        message = str(exc)
        evidence.update({"status": "invalid_report", "error": message})
        return message

    external_path = Path(state.output_dir) / "dotnet_preview_performance.json"
    _write_json_atomic(external_path, report)
    external_sha = sha256(external_path.read_bytes()).hexdigest()
    process_identity_stop = {"pid": _resident_pid(tab), **_resident_window_identity(state)}
    before_fingerprints = dict(evidence.get("archive_content_fingerprints_before", {}) or {})
    after_fingerprints = _archive_content_fingerprints(getattr(state, "fingerprint_paths", ()))
    identities_stable = process_identity_stop == dict(evidence.get("process_identity_start", {}) or {})
    archives_unchanged = bool(before_fingerprints and before_fingerprints == after_fingerprints)
    report_ok = bool(report.get("ok"))
    interaction_execution = dict(evidence.get("interaction_execution", {}) or {})
    interactions_ok = bool(interaction_execution.get("ok"))
    scheduled_inputs = sum(
        int(row.get("events_sent", 0) or 0)
        for row in tuple(interaction_execution.get("interactions", ()) or ())
        if isinstance(row, Mapping)
    )
    report_protocol = _mapping(report.get("protocol"), "Resident .NET performance report protocol")
    reported_inputs = _int_or_zero(report_protocol.get("inputs_received"))
    interaction_inputs_accounted = bool(scheduled_inputs > 0 and reported_inputs >= scheduled_inputs)
    evidence.update(
        {
            "status": str(completion.get("status", "complete") or "complete"),
            "ok": bool(
                report_ok
                and interactions_ok
                and interaction_inputs_accounted
                and identities_stable
                and archives_unchanged
            ),
            "compact_completion": "raw" not in completion,
            "completion": dict(completion),
            "helper_report_path": str(helper_report_path),
            "helper_report_sha256": helper_sha,
            "external_report_path": str(external_path),
            "external_report_size_bytes": external_path.stat().st_size,
            "external_report_sha256": external_sha,
            "report_schema": str(report.get("schema", "") or ""),
            "report_ok": report_ok,
            "interactions_ok": interactions_ok,
            "scheduled_interaction_inputs": scheduled_inputs,
            "reported_inputs_received": reported_inputs,
            "interaction_inputs_accounted": interaction_inputs_accounted,
            "interaction_execution": interaction_execution,
            "capture": dict(report.get("capture", {}) or {}),
            "frame_pacing": dict(report.get("frame_pacing", {}) or {}),
            "timings": dict(report.get("timings", {}) or {}),
            "managed_runtime": dict(report.get("managed_runtime", {}) or {}),
            "protocol": dict(report.get("protocol", {}) or {}),
            "memory": dict(report.get("memory", {}) or {}),
            "instrumentation": dict(report.get("instrumentation", {}) or {}),
            "lifecycle": dict(report.get("lifecycle", {}) or {}),
            "gates": dict(report.get("gates", {}) or {}),
            "process_identity_stop": process_identity_stop,
            "resident_identity_stable": identities_stable,
            "archive_content_fingerprints_after": after_fingerprints,
            "archive_sources_unchanged": archives_unchanged,
        }
    )
    evidence.pop("error", None)
    return ""


def service_performance_heartbeat(state: SimpleNamespace) -> None:
    callback = getattr(state, "performance_heartbeat_callback", None)
    if callable(callback):
        callback()


def _read_completed_report(
    state: SimpleNamespace,
    completion: Mapping[str, object],
    evidence: Mapping[str, object],
) -> tuple[dict[str, object], Path, str]:
    package = getattr(getattr(state, "tab", None), "standalone_dotnet_experiment_package", None)
    output_root = Path(str(getattr(package, "output_dir", "") or "")).resolve(strict=True)
    expected_candidate = output_root / str(evidence.get("helper_report_name", "") or "")
    reported_candidate = Path(str(completion.get("report_path", "") or ""))
    _require_plain_file(reported_candidate, label="Resident .NET performance report")
    expected_path = expected_candidate.resolve(strict=True)
    reported_path = reported_candidate.resolve(strict=True)
    if reported_path != expected_path or not reported_path.is_relative_to(output_root):
        raise PerformanceContractError("Resident .NET performance report escaped its package output root.")
    if reported_path.stat().st_size > _MAX_REPORT_BYTES:
        raise PerformanceContractError(f"Resident .NET performance report exceeds {_MAX_REPORT_BYTES} bytes.")
    raw = reported_path.read_bytes()
    if len(raw) > _MAX_REPORT_BYTES:
        raise PerformanceContractError(f"Resident .NET performance report exceeds {_MAX_REPORT_BYTES} bytes.")
    reported_size = int(completion.get("report_size_bytes", -1) or -1)
    if reported_size != len(raw):
        raise PerformanceContractError("Resident .NET performance report size did not match completion metadata.")
    digest = sha256(raw).hexdigest()
    if digest != str(completion.get("report_sha256", "") or "").strip().lower():
        raise PerformanceContractError("Resident .NET performance report hash did not match completion metadata.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PerformanceContractError("Resident .NET performance report must be UTF-8 JSON.") from exc
    report = _load_json_object(text, label="Resident .NET performance report")
    if report.get("schema") != PERFORMANCE_REPORT_SCHEMA:
        raise PerformanceContractError("Resident .NET performance report schema is unsupported.")
    capture = _mapping(report.get("capture"), "Resident .NET performance report capture")
    if str(capture.get("capture_id", "") or "") != str(evidence.get("capture_id", "") or ""):
        raise PerformanceContractError("Resident .NET performance report capture id did not match the request.")
    if str(capture.get("source", "") or "") != "resident_protocol":
        raise PerformanceContractError("Resident .NET performance report source did not match the protocol capture.")
    request = _mapping(evidence.get("request"), "Resident .NET performance request evidence")
    manifest = _mapping(request.get("manifest"), "Resident .NET performance manifest evidence")
    for field, expected in (
        ("requested_duration_seconds", request.get("duration_seconds")),
        ("target_hz", request.get("target_hz")),
        ("width", manifest.get("width")),
        ("height", manifest.get("height")),
    ):
        if not _numbers_match(capture.get(field), expected):
            raise PerformanceContractError(
                f"Resident .NET performance report {field} did not match the request."
            )
    asset_provenance = _mapping(
        capture.get("asset_provenance"),
        "Resident .NET performance report asset provenance",
    )
    expected_provenance = _mapping(
        evidence.get("asset_provenance"),
        "Resident .NET performance request asset provenance",
    )
    for field in ("model_path", "source_payload_sha256"):
        if str(asset_provenance.get(field, "") or "") != str(
            expected_provenance.get(field, "") or ""
        ):
            raise PerformanceContractError(
                f"Resident .NET performance report {field} provenance did not match the resident asset."
            )
    reported_manifest = _mapping(
        asset_provenance.get("performance_manifest"),
        "Resident .NET performance report manifest provenance",
    )
    if str(reported_manifest.get("sha256", "") or "") != str(manifest.get("sha256", "") or ""):
        raise PerformanceContractError(
            "Resident .NET performance report manifest fingerprint did not match the request."
        )
    reported_resident = _mapping(
        asset_provenance.get("resident_process"),
        "Resident .NET performance report process provenance",
    )
    expected_resident = _mapping(
        expected_provenance.get("resident_process"),
        "Resident .NET performance request process provenance",
    )
    if reported_resident != expected_resident:
        raise PerformanceContractError(
            "Resident .NET performance report PID/HWND provenance did not match the capture owner."
        )
    reported_fingerprints = _mapping(
        asset_provenance.get("archive_content_fingerprints_before"),
        "Resident .NET performance report archive fingerprints",
    )
    expected_fingerprints = _mapping(
        expected_provenance.get("archive_content_fingerprints_before"),
        "Resident .NET performance request archive fingerprints",
    )
    if reported_fingerprints != expected_fingerprints:
        raise PerformanceContractError(
            "Resident .NET performance report archive fingerprints did not match capture start."
        )
    for key in (
        "raw",
        "frame_pacing",
        "gates",
        "timings",
        "managed_runtime",
        "protocol",
        "memory",
        "instrumentation",
        "lifecycle",
    ):
        if key not in report and key not in {"raw", "frame_pacing", "gates"}:
            continue
        _mapping(report.get(key), f"Resident .NET performance report {key}")
    return report, reported_path, digest


def _wait_correlated_event(
    state: SimpleNamespace,
    correlation: Mapping[str, object],
    names: set[str],
    cursor: int,
    *,
    pump_until: Callable[[SimpleNamespace, Callable[[], bool], float | None], bool],
    timeout_seconds: float,
) -> dict[str, object]:
    found: dict[str, object] = {}

    def locate() -> bool:
        nonlocal found
        events = tuple(getattr(state.tab, "standalone_dotnet_protocol_events", ()) or ())
        start = max(0, min(int(cursor), len(events)))
        candidates = events[start:]
        if not candidates:
            candidates = events
        for event in candidates:
            if (
                str(event.get("event", "") or "").strip().lower() in names
                and str(event.get("capture_id", "") or "")
                == str(correlation.get("capture_id", "") or "")
                and str(event.get("session_id", "") or "")
                == str(correlation.get("session_id", "") or "")
                and _int_or_zero(event.get("request_id"))
                == _int_or_zero(correlation.get("request_id"))
                and _int_or_zero(event.get("process_generation"))
                == _int_or_zero(correlation.get("process_generation"))
            ):
                found = dict(event)
                return True
        return False

    pump_until(state, locate, timeout_seconds)
    return found


def _heartbeat_sender(state: SimpleNamespace, correlation: Mapping[str, object]) -> Callable[[], None]:
    last_sent = 0.0

    def send() -> None:
        nonlocal last_sent
        evidence = _capture_evidence(state)
        if not evidence.get("active"):
            return
        now = time.perf_counter()
        if now - last_sent < 0.01:
            return
        last_sent = now
        tab = getattr(state, "tab", None)
        if tab is not None:
            tab._send_dotnet_protocol_message({"event": "performance_heartbeat", **dict(correlation)})

    return send


def _capture_evidence(state: SimpleNamespace) -> dict[str, object]:
    evidence = getattr(state, "performance_capture_evidence", None)
    if not isinstance(evidence, dict):
        evidence = {}
        state.performance_capture_evidence = evidence
    return evidence


def _resident_pid(tab: object) -> int:
    process = getattr(tab, "standalone_dotnet_editor_process", None)
    try:
        return int(process.processId()) if process is not None else 0
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return 0


def _resident_window_identity(state: SimpleNamespace) -> dict[str, int]:
    return {
        "form_hwnd": int(getattr(state, "form_hwnd", 0) or 0),
        "viewport_hwnd": int(getattr(state, "viewport_hwnd", 0) or 0),
        "qt_host_hwnd": int(getattr(state, "qt_host_hwnd", 0) or 0),
    }


def _state_archive_provenance(state: SimpleNamespace) -> dict[str, object]:
    from tools.mesh_harness.archive_provenance import _archive_entry_provenance

    entry = getattr(state, "model_entry", None)
    return _archive_entry_provenance(entry) if entry is not None else {}


def _flush_protocol(tab: object) -> None:
    flush = getattr(tab, "_flush_dotnet_protocol_messages", None)
    if callable(flush):
        flush()


def _require_plain_file(path: Path, *, label: str) -> None:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise PerformanceContractError(f"{label} is unavailable: {path}") from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = int(getattr(metadata, "st_file_attributes", 0) or 0)
    if path.is_symlink() or bool(attributes & reparse_flag):
        raise PerformanceContractError(f"{label} must not be a symlink or reparse point.")
    if not path.is_file():
        raise PerformanceContractError(f"{label} is not a regular file: {path}")


def _load_json_object(text: str, *, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise PerformanceContractError(f"{label} contains duplicate key {key!r}.")
            result[key] = value
        return result

    try:
        payload = json.loads(text, object_pairs_hook=reject_duplicates)
    except PerformanceContractError:
        raise
    except (TypeError, ValueError) as exc:
        raise PerformanceContractError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise PerformanceContractError(f"{label} root must be a JSON object.")
    return payload


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise PerformanceContractError(f"{label} must be a JSON object.")
    return {str(key): item for key, item in value.items()}


def _require_exact_keys(payload: Mapping[str, object], expected: frozenset[str], label: str) -> None:
    keys = set(payload)
    missing = sorted(expected - keys)
    unknown = sorted(keys - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise PerformanceContractError(f"{label} fields are invalid ({'; '.join(details)}).")


def _safe_token(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_TOKEN.fullmatch(text):
        raise PerformanceContractError(
            f"Performance manifest {label} must match {_SAFE_TOKEN.pattern}."
        )
    return text


def _archive_path(value: object) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text or text.startswith("/") or "\x00" in text:
        raise PerformanceContractError("Performance manifest model_path must be a relative archive path.")
    parts = tuple(part for part in text.split("/") if part)
    if not parts or any(part in {".", ".."} for part in parts):
        raise PerformanceContractError("Performance manifest model_path must not traverse directories.")
    return "/".join(parts)


def _normalized_archive_path(value: object) -> str:
    return str(value or "").strip().replace("\\", "/").strip("/").casefold()


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PerformanceContractError(f"Performance manifest {label} must be an integer.")
    if not minimum <= value <= maximum:
        raise PerformanceContractError(
            f"Performance manifest {label} must be between {minimum} and {maximum}."
        )
    return value


def _finite_number(value: object, label: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise PerformanceContractError(f"{label} must be numeric.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PerformanceContractError(f"{label} must be numeric.") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise PerformanceContractError(f"{label} must be between {minimum:g} and {maximum:g}.")
    return number


def _numbers_match(left: object, right: object) -> bool:
    try:
        left_number = float(left)
        right_number = float(right)
    except (TypeError, ValueError):
        return False
    return math.isfinite(left_number) and math.isfinite(right_number) and math.isclose(
        left_number,
        right_number,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )


def _int_or_zero(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "DEFAULT_PERFORMANCE_DURATION_SECONDS",
    "DEFAULT_PERFORMANCE_TARGET_HZ",
    "PERFORMANCE_HARNESS_EVIDENCE_SCHEMA",
    "PERFORMANCE_MANIFEST_SCHEMA",
    "PERFORMANCE_REPORT_SCHEMA",
    "PerformanceContractError",
    "PerformanceInteraction",
    "PerformanceManifest",
    "PerformanceRequest",
    "SUPPORTED_PERFORMANCE_INTERACTIONS",
    "begin_performance_capture",
    "finish_performance_capture",
    "load_performance_manifest",
    "resolve_performance_request",
    "run_performance_interaction_schedule",
    "service_performance_heartbeat",
]
