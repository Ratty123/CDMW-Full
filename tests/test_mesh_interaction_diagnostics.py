from __future__ import annotations

import json
import threading
from pathlib import Path

import cdmw.services.mesh_interaction_diagnostics as diagnostics
from cdmw.services.mesh_interaction_diagnostics import MeshInteractionFlightRecorder


def test_record_does_not_wait_for_path_or_disk(tmp_path: Path) -> None:
    resolver_entered = threading.Event()
    release_resolver = threading.Event()

    def blocked_resolver() -> Path:
        resolver_entered.set()
        release_resolver.wait(2.0)
        return tmp_path / "interaction.jsonl"

    recorder = MeshInteractionFlightRecorder(blocked_resolver)
    completed = threading.Event()

    def produce() -> None:
        recorder.record("protocol", "helper_to_host", {"event": "stroke_update"})
        completed.set()

    producer = threading.Thread(target=produce)
    producer.start()
    assert resolver_entered.wait(0.5)
    assert completed.wait(0.5), "the event producer waited for filesystem work"
    release_resolver.set()
    producer.join(1.0)
    assert recorder.shutdown()


def test_queue_overflow_is_bounded_and_reported(tmp_path: Path) -> None:
    resolver_entered = threading.Event()
    release_resolver = threading.Event()

    def blocked_resolver() -> Path:
        resolver_entered.set()
        release_resolver.wait(2.0)
        return tmp_path / "interaction.jsonl"

    recorder = MeshInteractionFlightRecorder(blocked_resolver, queue_limit=1)
    assert recorder.record("protocol", "helper_to_host", {"event": "stroke_update"})
    assert resolver_entered.wait(0.5)
    assert not recorder.record(
        "protocol", "helper_to_host", {"event": "stroke_update"}
    )
    snapshot = recorder.snapshot()
    assert snapshot["queued_events"] == 1
    assert snapshot["dropped_queue_full"] == 1
    release_resolver.set()
    assert recorder.shutdown()


def test_recent_view_summarizes_large_payload_but_disk_keeps_it(tmp_path: Path) -> None:
    path = tmp_path / "interaction.jsonl"
    recorder = MeshInteractionFlightRecorder(lambda: path)
    vertices = [[float(index), 0.0, 0.0] for index in range(64)]
    assert recorder.record(
        "protocol",
        "host_to_helper",
        {"event": "scene_state_update", "vertices": vertices},
    )
    recent = recorder.snapshot(recent_limit=1)["recent_events"]
    assert recent[0]["vertices"] == {"value_type": "list", "item_count": 64}
    assert recorder.shutdown()
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["vertices"] == vertices


def test_protocol_send_helper_records_failure_reason_and_criticality(monkeypatch) -> None:
    calls: list[tuple[str, str, dict[str, object], bool]] = []
    monkeypatch.setattr(
        diagnostics,
        "record_mesh_interaction_event",
        lambda kind, direction, payload, *, critical=False: calls.append(
            (kind, direction, dict(payload), critical)
        )
        or True,
    )

    assert diagnostics.record_mesh_protocol_send(
        {"event": "stroke_update", "request_id": 8},
        sent=False,
        reason="no_active_controller",
    )

    assert calls == [
        (
            "protocol",
            "host_to_helper",
            {
                "event": "stroke_update",
                "request_id": 8,
                "sent": False,
                "send_reason": "no_active_controller",
            },
            True,
        )
    ]


def test_recorded_protocol_sender_preserves_send_result_and_exception(monkeypatch) -> None:
    records: list[tuple[bool, str]] = []
    monkeypatch.setattr(
        diagnostics,
        "record_mesh_protocol_send",
        lambda _payload, *, sent, reason="": records.append((sent, reason)) or True,
    )

    class Controller:
        def __init__(self, error: bool = False) -> None:
            self.error = error

        def send_authoring_message(self, _payload) -> bool:
            if self.error:
                raise RuntimeError("writer stopped")
            return True

    assert diagnostics.send_recorded_mesh_protocol_message(
        Controller(), {"event": "stroke_update"}
    )
    assert not diagnostics.send_recorded_mesh_protocol_message(
        Controller(error=True), {"event": "stroke_end"}
    )
    assert records == [(True, ""), (False, "RuntimeError: writer stopped")]
