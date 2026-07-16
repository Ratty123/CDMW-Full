from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tools.mesh_harness.archive_provenance import _archive_content_fingerprints
from tools.mesh_harness.constants import _REAL_ARCHIVE_RIGGING_SAMPLES
from tools.mesh_harness.cli import main as mesh_harness_main
from tools.mesh_harness.evidence import _real_game_mesh_evidence
from tools.mesh_harness.performance_contract import (
    PERFORMANCE_MANIFEST_SCHEMA,
    PERFORMANCE_REPORT_SCHEMA,
    PerformanceContractError,
    begin_performance_capture,
    finish_performance_capture,
    load_performance_manifest,
    resolve_performance_request,
    run_performance_interaction_schedule,
    service_performance_heartbeat,
)
from tools.mesh_harness.scenario_runner import run_scenario


def _write_manifest(path: Path, *, model_path: str = _REAL_ARCHIVE_RIGGING_SAMPLES[0]) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema": PERFORMANCE_MANIFEST_SCHEMA,
                "capture": {
                    "name": "canonical-edit",
                    "warmup_frames": 300,
                    "width": 1920,
                    "height": 1080,
                    "repetition": 2,
                },
                "asset": {"model_path": model_path, "corpus_role": "median"},
                "interactions": [
                    {"name": "textured-orbit-pan-zoom", "input_rate_hz": 120},
                    {"name": "selection-brush-burst", "input_rate_hz": 240},
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def test_versioned_performance_manifest_is_strict_and_defaults_to_144_hz(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path / "capture.json")

    manifest = load_performance_manifest(manifest_path)
    request = resolve_performance_request(
        "real-archive-mesh-editor-dotnet-edit-smoke",
        manifest_path,
    )

    assert manifest.as_evidence()["schema"] == PERFORMANCE_MANIFEST_SCHEMA
    assert manifest.capture_name == "canonical-edit"
    assert manifest.asset_model_path == _REAL_ARCHIVE_RIGGING_SAMPLES[0]
    assert manifest.warmup_frames == 300
    assert manifest.repetition == 2
    assert [row.input_rate_hz for row in manifest.interactions] == [120.0, 240.0]
    assert request is not None
    assert request.duration_seconds == 30.0
    assert request.target_hz == 144.0


def test_performance_options_are_canonical_only_and_require_a_manifest(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path / "capture.json")

    with pytest.raises(PerformanceContractError, match="valid only"):
        resolve_performance_request("service-only", manifest_path)
    with pytest.raises(PerformanceContractError, match="performance-manifest"):
        resolve_performance_request(
            "real-archive-mesh-editor-dotnet-edit-smoke",
            None,
            duration_seconds=10.0,
        )
    with pytest.raises(PerformanceContractError, match="between 30 and 360"):
        resolve_performance_request(
            "real-archive-mesh-editor-dotnet-edit-smoke",
            manifest_path,
            target_hz=361.0,
        )


def test_performance_manifest_rejects_duplicate_and_unknown_fields(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema":"cdmw_dotnet_preview_performance_manifest_v1",'
        '"schema":"cdmw_dotnet_preview_performance_manifest_v1"}',
        encoding="utf-8",
    )
    with pytest.raises(PerformanceContractError, match="duplicate key"):
        load_performance_manifest(duplicate)

    unknown = _write_manifest(tmp_path / "unknown.json")
    payload = json.loads(unknown.read_text(encoding="utf-8"))
    payload["unversioned_extension"] = True
    unknown.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PerformanceContractError, match="unknown"):
        load_performance_manifest(unknown)


def test_performance_interactions_use_monotonic_rate_schedule_and_finalize_each_stream(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest(tmp_path / "capture.json")
    request = resolve_performance_request(
        "real-archive-mesh-editor-dotnet-edit-smoke",
        manifest_path,
        duration_seconds=0.1,
        target_hz=144.0,
    )
    assert request is not None
    clock = [10.0]
    begun: list[str] = []
    ended: list[tuple[str, int]] = []
    sent: list[tuple[str, int]] = []

    result = run_performance_interaction_schedule(
        request,
        begin=lambda interaction: begun.append(interaction.name) is None,
        send=lambda interaction, ordinal: sent.append((interaction.name, ordinal)) is None,
        end=lambda interaction, count: ended.append((interaction.name, count)) is None,
        service=lambda: None,
        monotonic=lambda: clock[0],
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )

    assert result["ok"] is True
    assert begun == ["textured-orbit-pan-zoom", "selection-brush-burst"]
    assert [name for name, _count in ended] == begun
    assert all(count > 0 for _name, count in ended)
    assert {name for name, _ordinal in sent} == set(begun)


def test_resident_performance_capture_is_correlated_and_externalizes_verified_report(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest(tmp_path / "capture.json")
    request = resolve_performance_request(
        "real-archive-mesh-editor-dotnet-edit-smoke",
        manifest_path,
        duration_seconds=2.0,
        target_hz=120.0,
    )
    assert request is not None
    package_output = tmp_path / "package" / "output"
    package_output.mkdir(parents=True)
    archive_path = tmp_path / "0.paz"
    archive_path.write_bytes(b"archive")
    events: list[dict[str, object]] = []
    sent: list[dict[str, object]] = []

    class Process:
        @staticmethod
        def processId() -> int:
            return 73

    def send(payload: dict[str, object]) -> bool:
        sent.append(dict(payload))
        event = str(payload.get("event", ""))
        if event == "performance_capture_start":
            events.append(
                {
                    "event": "performance_capture_started",
                    "schema": PERFORMANCE_REPORT_SCHEMA,
                    "status": "capturing",
                    **{
                        key: payload[key]
                        for key in ("capture_id", "session_id", "request_id", "process_generation")
                    },
                    "process_generation": 3,
                }
            )
            events.append(
                {
                    "event": "performance_capture_started",
                    "schema": PERFORMANCE_REPORT_SCHEMA,
                    "status": "capturing",
                    **{key: payload[key] for key in ("capture_id", "session_id", "request_id", "process_generation")},
                }
            )
        elif event == "performance_capture_stop":
            start_payload = sent[0]
            report_path = package_output / str(start_payload["report_path"])
            report = {
                "schema": PERFORMANCE_REPORT_SCHEMA,
                "ok": True,
                "capture": {
                    "capture_id": payload["capture_id"],
                    "source": "resident_protocol",
                    "requested_duration_seconds": start_payload["duration_seconds"],
                    "target_hz": start_payload["target_hz"],
                    "width": start_payload["width"],
                    "height": start_payload["height"],
                    "asset_provenance": start_payload["asset_provenance"],
                },
                "raw": {"frame_intervals_ms": [7.0, 7.1]},
                "frame_pacing": {"summary": {"p95_ms": 7.1}},
                "instrumentation": {"probe_average_ns": 12.5},
                "protocol": {"inputs_received": 2},
                "gates": {"frame_interval_p95_at_most_8_68_ms": True},
            }
            report_path.write_text(json.dumps(report), encoding="utf-8")
            raw = report_path.read_bytes()
            events.extend(
                (
                    {
                        "event": "performance_capture_stopping",
                        "capture_id": payload["capture_id"],
                    },
                    {
                        "event": "performance_capture_complete",
                        "schema": PERFORMANCE_REPORT_SCHEMA,
                        "status": "complete",
                        "ok": True,
                        "capture_id": payload["capture_id"],
                        "session_id": payload["session_id"],
                        "request_id": payload["request_id"],
                        "process_generation": payload["process_generation"],
                        "report_path": str(report_path),
                        "report_size_bytes": len(raw),
                        "report_sha256": sha256(raw).hexdigest(),
                        "frame_pacing": report["frame_pacing"],
                        "gates": report["gates"],
                    },
                )
            )
        return True

    tab = SimpleNamespace(
        standalone_dotnet_capabilities={"performance_capture_v1"},
        standalone_dotnet_lifecycle_session_id="resident-session",
        standalone_dotnet_process_generation=4,
        standalone_dotnet_experiment_package=SimpleNamespace(output_dir=package_output),
        standalone_dotnet_editor_process=Process(),
        standalone_dotnet_protocol_events=events,
        _send_dotnet_protocol_message=send,
        _flush_dotnet_protocol_messages=lambda: None,
    )
    state = SimpleNamespace(
        tab=tab,
        output_dir=tmp_path / "evidence",
        model_entry=SimpleNamespace(path=_REAL_ARCHIVE_RIGGING_SAMPLES[0]),
        source_payload_sha256="asset-sha",
        archive_provenance={"paz_path": str(archive_path)},
        fingerprint_paths=(archive_path,),
        archive_content_fingerprints_before=_archive_content_fingerprints((archive_path,)),
        form_hwnd=101,
        viewport_hwnd=102,
        qt_host_hwnd=103,
    )
    state.output_dir.mkdir()

    def pump(target: SimpleNamespace, predicate: object, _timeout: float | None = None) -> bool:
        del target
        return bool(predicate())  # type: ignore[operator]

    assert begin_performance_capture(state, request, pump_until=pump) == ""
    state.performance_capture_evidence["interaction_execution"] = {
        "schema": "cdmw_dotnet_preview_performance_interactions_v1",
        "ok": True,
        "interactions": [{"name": "fixture", "events_sent": 2}],
    }
    service_performance_heartbeat(state)
    assert finish_performance_capture(state, pump_until=pump) == ""

    start = sent[0]
    assert start["event"] == "performance_capture_start"
    assert start["session_id"] == "resident-session"
    assert start["process_generation"] == 4
    assert start["duration_seconds"] == 2.0
    assert start["target_hz"] == 120.0
    assert start["asset_provenance"]["source_payload_sha256"] == "asset-sha"  # type: ignore[index]
    assert [row["event"] for row in sent] == [
        "performance_capture_start",
        "performance_heartbeat",
        "performance_capture_stop",
    ]
    evidence = state.performance_capture_evidence
    assert evidence["ok"] is True
    assert evidence["compact_completion"] is True
    assert evidence["instrumentation"] == {"probe_average_ns": 12.5}
    assert evidence["resident_identity_stable"] is True
    assert evidence["archive_sources_unchanged"] is True
    assert Path(str(evidence["external_report_path"])).is_file()
    assert evidence["process_identity_start"] == {
        "pid": 73,
        "form_hwnd": 101,
        "viewport_hwnd": 102,
        "qt_host_hwnd": 103,
    }


def test_scenario_routes_performance_request_only_to_canonical_edit_subrun(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path / "capture.json")
    proof = {
        "ok": True,
        "renderer_backend": "d3d11_vortice_shader",
        "edit_backend": "cdmw_mesh_core_0.1",
    }
    with (
        patch(
            "tools.mesh_harness.real_dotnet.run_real_archive_mesh_editor_dotnet_edit_smoke",
            return_value=proof,
        ) as run_edit,
        patch(
            "tools.mesh_harness.real_dotnet.run_real_archive_mesh_editor_dotnet_zoom_smoke",
            return_value=proof,
        ) as run_zoom,
    ):
        result = run_scenario(
            "real-archive-mesh-editor-dotnet-edit-smoke",
            tmp_path / "out",
            game_root=tmp_path / "game",
            performance_manifest=manifest_path,
            performance_duration_seconds=3.0,
            performance_target_hz=144.0,
        )

    assert result["ok"] is True
    request = run_edit.call_args.kwargs["performance_request"]
    assert request.duration_seconds == 3.0
    assert request.target_hz == 144.0
    assert "performance_request" not in run_zoom.call_args.kwargs


def test_canonical_edit_preparation_uses_manifest_selected_corpus_asset(tmp_path: Path) -> None:
    from tools.mesh_harness.real_dotnet import run_real_archive_mesh_editor_dotnet_edit_smoke

    selected = "character/model/performance/maximum_vertex_sample.pac"
    manifest_path = _write_manifest(tmp_path / "capture.json", model_path=selected)
    request = resolve_performance_request(
        "real-archive-mesh-editor-dotnet-edit-smoke",
        manifest_path,
    )
    assert request is not None
    with patch(
        "tools.mesh_harness.real_dotnet._prepare_real_asset",
        return_value={"ok": False, "read_only": True, "error": "fixture stop"},
    ) as prepare:
        result = run_real_archive_mesh_editor_dotnet_edit_smoke(
            tmp_path / "game",
            tmp_path / "out",
            performance_request=request,
        )

    prepare.assert_called_once_with(
        tmp_path / "game",
        tmp_path / "out",
        105.0,
        model_path=selected,
    )
    assert result["performance_capture"]["status"] == "not_started"


def test_canonical_performance_capture_drives_manifest_interactions_instead_of_idling() -> None:
    source = (Path(__file__).resolve().parents[1] / "tools" / "mesh_harness" / "real_dotnet.py").read_text(
        encoding="utf-8"
    )
    flow = source.split("def run_real_archive_mesh_editor_dotnet_edit_smoke", maxsplit=1)[1]
    capture = source.split("def _execute_performance_capture", maxsplit=1)[1].split(
        "def _wait_protocol_event", maxsplit=1
    )[0]

    assert "run_performance_interaction_schedule(" in source
    assert "_run_performance_interactions(state, request)" in capture
    assert flow.count("_execute_performance_capture(state, performance_request)") == 2
    assert flow.index("_performance_requires_edit_preparation(performance_request)") < flow.index(
        "exercise_coherent_export"
    )
    assert flow.rindex("_execute_performance_capture(state, performance_request)") > flow.index(
        "exercise_coherent_export"
    )
    assert "performance_request.duration_seconds - capture_elapsed" not in flow
    for workload in (
        "textured-orbit-pan-zoom",
        "wire-vertices-part-highlight",
        "selection-brush-burst",
        "material-update",
        "texture-update",
        "topology-update",
        "resize-stress",
    ):
        assert f'"{workload}"' in source


def test_cli_forwards_additive_performance_options_and_rejects_other_scenarios(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest(tmp_path / "capture.json")
    with patch(
        "tools.mesh_harness.scenario_runner.run_scenario",
        return_value={"ok": True},
    ) as run:
        exit_code = mesh_harness_main(
            [
                "--scenario",
                "real-archive-mesh-editor-dotnet-edit-smoke",
                "--output",
                str(tmp_path / "out"),
                "--performance-manifest",
                str(manifest_path),
                "--performance-duration-seconds",
                "4",
                "--performance-target-hz",
                "144",
            ]
        )

    assert exit_code == 0
    assert run.call_args.kwargs["performance_manifest"] == manifest_path
    assert run.call_args.kwargs["performance_duration_seconds"] == 4.0
    assert run.call_args.kwargs["performance_target_hz"] == 144.0

    with pytest.raises(SystemExit) as exc:
        mesh_harness_main(
            [
                "--scenario",
                "service-only",
                "--output",
                str(tmp_path / "blocked"),
                "--performance-manifest",
                str(manifest_path),
            ]
        )
    assert exc.value.code == 2


def test_real_game_evidence_keeps_external_performance_report_reference() -> None:
    capture = {
        "schema": "cdmw_dotnet_preview_performance_harness_v1",
        "ok": True,
        "external_report_path": "outside-repo/report.json",
    }

    evidence = _real_game_mesh_evidence({"performance_capture": capture})

    assert evidence["performance_capture"] == capture
