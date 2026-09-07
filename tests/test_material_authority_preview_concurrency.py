from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from cdmw.core import texture_native
from cdmw.domain.cancellation import RunCancelled
from cdmw.services import material_authority_resource_service as owner


def _requests(root: Path):
    return tuple(
        texture_native.NativeTextureEncodeRequest(
            input_path=root / f"source-{index}.png", output_path=root / f"map-{index}.dds",
            dds_format="R8G8B8A8_UNORM", width=2048, height=2048, mip_count=12,
        )
        for index in range(6)
    )


def test_large_preview_uses_two_lanes_and_preserves_every_request(tmp_path, monkeypatch):
    requests = _requests(tmp_path)
    barrier = threading.Barrier(2)
    seen = []

    def encode(group, **kwargs):
        seen.append(tuple(group))
        barrier.wait(timeout=5)
        return {str(request.output_path): {"status": "encoded"} for request in group}

    monkeypatch.setattr(owner.os, "cpu_count", lambda: 2)
    monkeypatch.setattr(texture_native, "encode_dds_batch_with_directxtex", encode)
    reports = owner._encode_preview_image_requests(
        requests, [4096**2] * len(requests), threading.Event(), enable_parallel=True,
    )
    assert len(seen) == 2
    assert sorted(len(group) for group in seen) == [3, 3]
    assert {request for group in seen for request in group} == set(requests)
    assert set(reports) == {str(request.output_path) for request in requests}


@pytest.mark.parametrize("reason", ("export", "small", "memory", "cpu", "duplicate"))
def test_preview_retains_serial_encoding_when_parallel_work_is_unsuitable(tmp_path, monkeypatch, reason):
    requests = _requests(tmp_path)
    pixels = [8192**2 if reason == "memory" else 8**2 if reason == "small" else 4096**2] * len(requests)
    if reason == "duplicate":
        requests = (requests[0],) * len(requests)
    calls = []
    monkeypatch.setattr(owner.os, "cpu_count", lambda: 1 if reason == "cpu" else 2)
    monkeypatch.setattr(texture_native, "encode_dds_batch_with_directxtex", lambda jobs, **kwargs: calls.append(tuple(jobs)) or {})
    owner._encode_preview_image_requests(requests, pixels, threading.Event(), enable_parallel=reason != "export")
    assert calls == [requests]


@pytest.mark.parametrize("failure", ("exception", "missing_report", "cancel"))
def test_parallel_failure_stops_and_joins_the_other_lane(tmp_path, monkeypatch, failure):
    requests = _requests(tmp_path)
    parent = threading.Event()
    barrier = threading.Barrier(2)
    stopped = []

    def encode(group, *, stop_event, **kwargs):
        try:
            barrier.wait(timeout=5)
            if group[0] == requests[0]:
                if failure == "cancel":
                    parent.set()
                    raise RunCancelled("cancelled")
                if failure == "exception":
                    raise RuntimeError("encode failed")
                return {}
            deadline = time.monotonic() + 5
            while not stop_event.is_set() and time.monotonic() < deadline:
                time.sleep(0.005)
            assert stop_event.is_set(), "Sibling helper did not receive cancellation"
            raise RunCancelled("sibling stopped")
        finally:
            stopped.append(tuple(group))

    monkeypatch.setattr(owner.os, "cpu_count", lambda: 2)
    monkeypatch.setattr(texture_native, "encode_dds_batch_with_directxtex", encode)
    with pytest.raises(RunCancelled if failure == "cancel" else RuntimeError):
        owner._encode_preview_image_requests(
            requests, [4096**2] * len(requests), parent, enable_parallel=True,
        )
    assert len(stopped) == 2
    assert parent.is_set() is (failure == "cancel")
    assert not tuple(tmp_path.glob("*.dds"))


def test_cancelled_preview_does_not_start_either_lane(tmp_path, monkeypatch):
    parent = threading.Event()
    parent.set()
    monkeypatch.setattr(texture_native, "encode_dds_batch_with_directxtex", lambda *a, **k: pytest.fail("cancelled helper launched"))
    with pytest.raises(RunCancelled):
        owner._encode_preview_image_requests(_requests(tmp_path), [4096**2] * 6, parent, enable_parallel=True)


def test_partial_worker_start_failure_stops_the_started_lane(tmp_path, monkeypatch):
    started = threading.Event()
    stopped = []
    parent = threading.Event()
    executor_type = owner.ThreadPoolExecutor

    class FailedSecondWorker(executor_type):
        calls = 0

        def submit(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 2:
                assert started.wait(timeout=5)
                raise RuntimeError("worker start failed")
            return super().submit(*args, **kwargs)

    def encode(group, *, stop_event, **kwargs):
        started.set()
        deadline = time.monotonic() + 5
        while not stop_event.is_set() and time.monotonic() < deadline:
            time.sleep(0.005)
        stopped.append(stop_event.is_set())
        raise RunCancelled("stopped")

    monkeypatch.setattr(owner.os, "cpu_count", lambda: 2)
    monkeypatch.setattr(owner, "ThreadPoolExecutor", FailedSecondWorker)
    monkeypatch.setattr(texture_native, "encode_dds_batch_with_directxtex", encode)
    with pytest.raises(RuntimeError, match="worker start failed"):
        owner._encode_preview_image_requests(_requests(tmp_path), [4096**2] * 6, parent, enable_parallel=True)
    assert stopped == [True]
    assert not parent.is_set()


def test_parallel_cancel_reaps_both_owned_helper_processes(tmp_path, monkeypatch):
    import sys
    from cdmw.core.common import run_process_with_cancellation

    parent = threading.Event()
    finished = []

    def encode(group, *, stop_event, **kwargs):
        marker = tmp_path / (group[0].input_path.stem + ".ready")
        try:
            return run_process_with_cancellation(
                [sys.executable, "-c", "import pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text('ready');time.sleep(30)", str(marker)],
                stop_event=stop_event,
            )
        finally:
            finished.append(marker)

    def cancel_when_running():
        deadline = time.monotonic() + 5
        while len(tuple(tmp_path.glob("*.ready"))) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        parent.set()

    monkeypatch.setattr(owner.os, "cpu_count", lambda: 2)
    monkeypatch.setattr(texture_native, "encode_dds_batch_with_directxtex", encode)
    canceller = threading.Thread(target=cancel_when_running)
    canceller.start()
    started = time.monotonic()
    try:
        with pytest.raises(RunCancelled):
            owner._encode_preview_image_requests(_requests(tmp_path), [4096**2] * 6, parent, enable_parallel=True)
    finally:
        parent.set()
        canceller.join(timeout=6)
    assert len(finished) == 2
    assert all(marker.is_file() for marker in finished)
    assert time.monotonic() - started < 10
    assert not canceller.is_alive()


def test_parallel_preview_dds_bytes_match_serial_native_encoding(tmp_path, monkeypatch):
    if texture_native.find_directxtex_texture_binary() is None:
        pytest.skip("cd-texture-dx is not built")
    source = tmp_path / "source.png"
    Image.new("RGBA", (2048, 1024), (73, 41, 19, 157)).save(source)
    original = source.read_bytes()
    reports = []
    for workers in (1, 2):
        monkeypatch.setattr(owner.os, "cpu_count", lambda: workers)
        jobs = tuple(
            (source, tmp_path / f"{workers}-{channel}.dds", channel)
            for channel in ("base", "normal", "material_mask", "emissive")
        )
        reports.append(owner._encode_owned_image_dds_batch(
            jobs, threading.Event(), preview_uncompressed_max_bytes=64 * 1024 * 1024, max_dimension=512,
        ))
    assert reports[0] == reports[1]
    for channel in ("base", "normal", "material_mask", "emissive"):
        assert (tmp_path / f"1-{channel}.dds").read_bytes() == (tmp_path / f"2-{channel}.dds").read_bytes()
    assert source.read_bytes() == original
