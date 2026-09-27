"""Repeated preview, placement and plan encodes retain the native output contract."""

from collections import OrderedDict
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import threading

from PIL import Image
import pytest

from cdmw.core import texture_encode_cache as cache, texture_native as native
from cdmw.domain.cancellation import RunCancelled
from tests.test_texture_native_backend import _encoded_dds_for_job


@pytest.fixture
def encoder(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_CACHE", OrderedDict())
    binary = tmp_path / "encoder.exe"
    binary.write_bytes(b"owned native encoder identity")
    monkeypatch.setattr(native, "find_directxtex_texture_binary", lambda: binary)
    source = tmp_path / "source.png"
    Image.new("RGBA", (8, 8), (32, 64, 96, 128)).save(source)
    request = native.NativeTextureEncodeRequest(source, tmp_path / "first.dds", "BC7_UNORM", 8, 8, 1)
    calls = []

    def run(command, **kwargs):
        jobs = json.loads(Path(command[2]).read_text(encoding="utf-8"))["jobs"]
        calls.append(jobs)
        items = []
        for job in jobs:
            data = _encoded_dds_for_job(job)
            digest = hashlib.sha256(Path(job["input"]).read_bytes()).digest()
            Path(job["output"]).write_bytes(data[:-16] + digest[:16])
            items.append(dict(status="encoded", source_path=job["input"], output_path=job["output"],
                              format=job["format"], width=job["width"], height=job["height"],
                              mip_count=job["mip_count"], encode_ms=123))
        Path(command[3]).write_text(json.dumps({"items": items}), encoding="utf-8")
        return 0, "", ""

    monkeypatch.setattr(native, "run_process_with_cancellation", run)
    return request, calls, run, binary


def test_repeated_encodes_reuse_exact_bytes_across_source_and_destination_paths(encoder, tmp_path):
    request, calls, _, _ = encoder
    native.encode_dds_batch_with_directxtex((request,))
    expected = request.output_path.read_bytes()
    copied = tmp_path / "prepared_again.png"
    copied.write_bytes(request.input_path.read_bytes())
    other = replace(request, input_path=copied, output_path=tmp_path / "second.dds")
    report = native.encode_dds_batch_with_directxtex((other,))[str(other.output_path)]
    assert len(calls) == 1
    assert other.output_path.read_bytes() == expected
    assert report["source_path"] == str(copied)
    assert report["output_path"] == str(other.output_path)
    assert report["encode_ms"] == 0
    # Reports and published files belong to their callers, not to the cache.
    report["format"] = "changed"
    other.output_path.write_bytes(b"caller edit")
    native.encode_dds_batch_with_directxtex((other,))
    assert other.output_path.read_bytes() == expected
    assert len(calls) == 1


def test_cache_retains_owned_staging_bytes_when_the_destination_is_replaced(encoder, tmp_path, monkeypatch):
    request, calls, _, _ = encoder
    publish = native.os.replace
    expected = []

    def replaced_by_another_writer(staged, destination):
        if destination == request.output_path:
            expected.append(staged.read_bytes())
        publish(staged, destination)
        if destination == request.output_path:
            destination.write_bytes(expected[-1][:-16] + b"different pixels")

    monkeypatch.setattr(native.os, "replace", replaced_by_another_writer)
    native.encode_dds_batch_with_directxtex((request,))
    other = replace(request, output_path=tmp_path / "second.dds")
    native.encode_dds_batch_with_directxtex((other,))
    assert other.output_path.read_bytes() == expected[0]
    assert len(calls) == 1


@pytest.mark.parametrize("changes", [
    {"dds_format": "BC7_UNORM_SRGB"}, {"width": 4}, {"height": 4}, {"mip_count": 2},
    {"source_color_policy": "assume_srgb"}, {"mip_alpha_policy": "separate"},
    {"alpha_coverage_reference": 0.25}, {"dds_alpha_mode": "straight"},
])
def test_every_conversion_policy_invalidates_reuse(encoder, changes):
    request, calls, _, _ = encoder
    native.encode_dds_batch_with_directxtex((request,))
    native.encode_dds_batch_with_directxtex((replace(request, **changes),))
    assert len(calls) == 2


def test_same_size_same_timestamp_source_edit_and_encoder_change_invalidate(encoder):
    request, calls, _, binary = encoder
    native.encode_dds_batch_with_directxtex((request,))
    before = request.output_path.read_bytes()
    stamp = request.input_path.stat()
    Image.new("RGBA", (8, 8), (64, 32, 96, 128)).save(request.input_path)
    assert request.input_path.stat().st_size == stamp.st_size
    os.utime(request.input_path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    native.encode_dds_batch_with_directxtex((request,))
    assert request.output_path.read_bytes() != before
    binary.write_bytes(b"replacement native encoder")
    native.encode_dds_batch_with_directxtex((request,))
    assert len(calls) == 3


def test_mixed_batch_encodes_only_missing_inputs(encoder, tmp_path):
    request, calls, _, _ = encoder
    native.encode_dds_batch_with_directxtex((request,))
    other = replace(request, output_path=tmp_path / "normal.dds", dds_format="BC5_UNORM")
    results = native.encode_dds_batch_with_directxtex((request, other))
    assert set(results) == {str(request.output_path), str(other.output_path)}
    assert len(calls) == 2 and len(calls[-1]) == 1
    assert calls[-1][0]["format"] == "BC5_UNORM"


def test_shared_output_paths_preserve_order_and_do_not_poison_cached_sources(encoder, tmp_path):
    request, calls, _, _ = encoder
    native.encode_dds_batch_with_directxtex((request,))
    expected = request.output_path.read_bytes()
    other_source = tmp_path / "other.png"
    Image.new("RGBA", (8, 8), (99, 7, 3, 128)).save(other_source)
    other = replace(request, input_path=other_source)
    # The last request is warm, but still has to publish after the preceding miss.
    native.encode_dds_batch_with_directxtex((other, request))
    assert request.output_path.read_bytes() == expected
    assert len(calls[-1]) == 2
    other = replace(other, output_path=tmp_path / "other.dds")
    native.encode_dds_batch_with_directxtex((other,))
    assert other.output_path.read_bytes() != expected
    assert len(calls) == 3


def test_cached_output_cannot_overwrite_another_batch_input_before_native_reads_it(encoder, tmp_path, monkeypatch):
    request, _, run, _ = encoder
    native.encode_dds_batch_with_directxtex((request,))
    shared = tmp_path / "shared.png"
    Image.new("RGBA", (8, 8), (99, 7, 3, 128)).save(shared)
    before = shared.read_bytes()
    first = replace(request, output_path=shared)
    second = replace(request, input_path=shared, output_path=tmp_path / "last.dds")
    called = []

    def inspect(command, **kwargs):
        assert shared.read_bytes() == before
        called.append(True)
        return run(command, **kwargs)

    monkeypatch.setattr(native, "run_process_with_cancellation", inspect)
    native.encode_dds_batch_with_directxtex((first, second))
    assert called == [True]


def test_cached_hits_preserve_overwrite_and_cancellation_guards(encoder):
    request, calls, _, _ = encoder
    native.encode_dds_batch_with_directxtex((request,))
    request.output_path.write_bytes(b"keep this destination")
    assert not native.encode_dds_batch_with_directxtex((replace(request, overwrite=False),))
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        native.encode_dds_batch_with_directxtex((request,), stop_event=stop)
    assert request.output_path.read_bytes() == b"keep this destination"
    assert len(calls) == 1


def test_cancellation_during_cache_lookup_keeps_the_existing_output(encoder, monkeypatch):
    request, calls, _, _ = encoder
    native.encode_dds_batch_with_directxtex((request,))
    request.output_path.write_bytes(b"retain existing output")
    lookup = cache.cached_encode
    stop = threading.Event()

    def cancel(key):
        result = lookup(key)
        stop.set()
        return result

    monkeypatch.setattr(cache, "cached_encode", cancel)
    with pytest.raises(RunCancelled):
        native.encode_dds_batch_with_directxtex((request,), stop_event=stop)
    assert request.output_path.read_bytes() == b"retain existing output"
    assert not tuple(request.output_path.parent.glob(".*.cdmw-*.dds"))
    assert len(calls) == 1


def test_unrelated_slow_encode_does_not_block_a_cached_preview(encoder, monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    request, calls, run, _ = encoder
    native.encode_dds_batch_with_directxtex((request,))
    entered, release = threading.Event(), threading.Event()

    def blocked(command, **kwargs):
        entered.set()
        assert release.wait(5)
        return run(command, **kwargs)

    monkeypatch.setattr(native, "run_process_with_cancellation", blocked)
    slow = replace(request, output_path=tmp_path / "slow.dds", dds_format="BC5_UNORM")
    warm = replace(request, output_path=tmp_path / "warm.dds")
    with ThreadPoolExecutor(max_workers=2) as workers:
        future = workers.submit(native.encode_dds_batch_with_directxtex, (slow,))
        try:
            assert entered.wait(5)
            assert workers.submit(native.encode_dds_batch_with_directxtex, (warm,)).result(timeout=2)
            assert warm.output_path.read_bytes() == request.output_path.read_bytes()
        finally:
            release.set()
        assert future.result(timeout=5)
    assert len(calls) == 2


@pytest.mark.parametrize("failure", ["cancel", "invalid", "source_changed"])
def test_unsuccessful_or_changed_source_results_are_never_retained(encoder, monkeypatch, failure):
    request, calls, run, _ = encoder
    stop = threading.Event()

    def failing(command, **kwargs):
        result = run(command, **kwargs)
        if failure == "cancel":
            stop.set()
        elif failure == "invalid":
            Path(calls[-1][0]["output"]).write_bytes(b"truncated")
        else:
            Image.new("RGBA", (8, 8), (99, 3, 5, 128)).save(request.input_path)
        return result

    monkeypatch.setattr(native, "run_process_with_cancellation", failing)
    if failure == "cancel":
        with pytest.raises(RunCancelled):
            native.encode_dds_batch_with_directxtex((request,), stop_event=stop)
    else:
        native.encode_dds_batch_with_directxtex((request,))
    assert not cache._CACHE
    stop.clear()
    monkeypatch.setattr(native, "run_process_with_cancellation", run)
    assert native.encode_dds_batch_with_directxtex((request,), stop_event=stop)
    assert len(calls) == 2


@pytest.mark.parametrize("limit", ["bytes", "entries"])
def test_memory_is_bounded_and_oversize_outputs_still_work(encoder, monkeypatch, limit):
    request, calls, _, _ = encoder
    native.encode_dds_batch_with_directxtex((request,))
    size = request.output_path.stat().st_size
    monkeypatch.setattr(cache, "_MAX_BYTES", size if limit == "bytes" else size * 2)
    monkeypatch.setattr(cache, "_MAX_ENTRIES", 2 if limit == "bytes" else 1)
    other = replace(request, source_color_policy="assume_srgb")
    native.encode_dds_batch_with_directxtex((other,))
    assert len(cache._CACHE) == 1
    native.encode_dds_batch_with_directxtex((request,))
    assert len(calls) == 3
    cache._CACHE.clear()
    monkeypatch.setattr(cache, "_MAX_BYTES", size - 1)
    assert native.encode_dds_batch_with_directxtex((request,))
    assert not cache._CACHE
