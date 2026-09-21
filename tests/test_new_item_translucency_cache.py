"""Repeated plans reuse exact source-derived BC7 without retaining cancelled work."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import threading

from PIL import Image
import pytest

from cdmw.core import texture_native
from cdmw.domain.cancellation import RunCancelled
from cdmw.modding.material_replacer import ReplacementTextureSlot
from cdmw.services import new_item_translucency as owner
from cdmw.services.new_item_materials import SourceMaterialTextures


@pytest.fixture
def encoding(tmp_path, monkeypatch):
    monkeypatch.setattr(owner, "_BASE_CACHE", OrderedDict())
    monkeypatch.setattr(texture_native, "native_texture_backend_identity", lambda: "owned-encoder-v1")
    path = tmp_path / "colour.png"
    Image.new("RGBA", (8, 8), (120, 80, 40, 128)).save(path)
    source = SourceMaterialTextures("Glass", base_slot=ReplacementTextureSlot("Glass", "base", path, alpha_mode="BLEND"))
    calls = []

    def encode(png, output, **kwargs):
        calls.append(kwargs)
        output.write_bytes(b"owned DDS fixture:" + hashlib.sha256(png.read_bytes()).digest())
        return {"status": "encoded"}

    monkeypatch.setattr(texture_native, "encode_dds_with_directxtex", encode)
    return source, calls, encode


def test_repeated_build_reuses_bytes_and_changes_to_source_factors_alpha_or_backend_invalidate(encoding, monkeypatch):
    source, calls, _ = encoding
    first = owner.encode_translucent_base(source)
    assert owner.encode_translucent_base(source) == first
    assert len(calls) == 1
    assert (calls[0]["dds_format"], calls[0]["mip_count"]) == ("BC7_UNORM", 4)
    tinted = replace(source, base_slot=replace(source.base_slot, base_color_factor=(0.5, 1, 1)))
    assert owner.encode_translucent_base(tinted) != first
    opaque = replace(source, base_slot=replace(source.base_slot, alpha_mode="OPAQUE"))
    assert owner.encode_translucent_base(opaque) != first
    Image.new("RGBA", (8, 8), (80, 120, 40, 128)).save(source.base_slot.source_path)
    changed = owner.encode_translucent_base(source)
    assert changed != first
    assert len(calls) == 4
    monkeypatch.setattr(texture_native, "native_texture_backend_identity", lambda: "owned-encoder-v2")
    assert owner.encode_translucent_base(source) == changed
    assert len(calls) == 5


@pytest.mark.parametrize("limit", ["bytes", "entries"])
def test_cache_has_byte_and_entry_limits(encoding, monkeypatch, limit):
    source, calls, _ = encoding
    first = owner.encode_translucent_base(source)
    monkeypatch.setattr(owner, "_BASE_CACHE_MAX_BYTES", len(first) * (1 if limit == "bytes" else 2))
    monkeypatch.setattr(owner, "_BASE_CACHE_MAX_ENTRIES", 2 if limit == "bytes" else 1)
    other = replace(source, base_slot=replace(source.base_slot, alpha_mode="OPAQUE"))
    owner.encode_translucent_base(other)
    assert len(owner._BASE_CACHE) == 1
    owner.encode_translucent_base(source)
    assert len(calls) == 3  # The least-recently-used entry was evicted.
    monkeypatch.setattr(owner, "_BASE_CACHE_MAX_BYTES", len(first) - 1)
    owner._BASE_CACHE.clear()
    owner.encode_translucent_base(other)
    assert not owner._BASE_CACHE  # Oversized output is usable but not retained.


def test_cancelled_encode_does_not_enter_cache_and_success_can_retry(encoding, monkeypatch):
    source, calls, encode = encoding
    stop = threading.Event()

    def cancelled(png, output, **kwargs):
        assert kwargs["stop_event"] is stop
        encode(png, output, **kwargs)
        stop.set()
        raise RunCancelled("owned cancellation")

    monkeypatch.setattr(texture_native, "encode_dds_with_directxtex", cancelled)
    with pytest.raises(RunCancelled):
        owner.encode_translucent_base(source, stop_event=stop)
    assert not owner._BASE_CACHE
    monkeypatch.setattr(texture_native, "encode_dds_with_directxtex", encode)
    owner.encode_translucent_base(source)
    assert len(calls) == 2
    with pytest.raises(RunCancelled):
        owner.encode_translucent_base(source, stop_event=stop)  # Also reject a cancelled cache hit.


def test_waiting_for_another_encode_is_cancellable_and_duplicate_work_is_shared(encoding, monkeypatch):
    source, calls, encode = encoding
    entered, release, stop = threading.Event(), threading.Event(), threading.Event()

    def blocked(png, output, **kwargs):
        entered.set()
        assert release.wait(5)
        return encode(png, output, **kwargs)

    monkeypatch.setattr(texture_native, "encode_dds_with_directxtex", blocked)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(owner.encode_translucent_base, source)
        try:
            assert entered.wait(3)
            waiting = pool.submit(owner.encode_translucent_base, source, stop_event=stop)
            duplicate = pool.submit(owner.encode_translucent_base, source)
            stop.set()
            with pytest.raises(RunCancelled):
                waiting.result(timeout=2)
        finally:
            release.set()
        assert duplicate.result(timeout=3) == first.result(timeout=3)
    assert len(calls) == 1


def test_failed_encode_is_not_cached(encoding, monkeypatch):
    source, _, encode = encoding
    monkeypatch.setattr(texture_native, "encode_dds_with_directxtex", lambda *args, **kwargs: None)
    with pytest.raises(owner.NewItemPlanError, match="produced nothing"):
        owner.encode_translucent_base(source)
    assert not owner._BASE_CACHE
    monkeypatch.setattr(texture_native, "encode_dds_with_directxtex", encode)
    assert owner.encode_translucent_base(source)


@pytest.mark.parametrize("current", [False, True])
def test_plan_forwards_cancellation_to_translucent_encoding(tmp_path, encoding, monkeypatch, current):
    from cdmw.core.pac_xml_standard_material import find_material_wrappers
    from cdmw.domain.new_item.spec import MaterialRoute, ModelSource
    from cdmw.domain.new_item.translucency import TranslucencyChoice
    from tests.test_new_item_materials import builder_files, XML
    from tests.test_new_item_provenance import setup_game, spec

    source, _, _ = encoding
    service, snapshot, _ = setup_game(tmp_path, current=current)
    files, stop, received = builder_files(), threading.Event(), []
    name = find_material_wrappers(files.side_files[XML].decode())[0].submesh_name
    monkeypatch.setattr("cdmw.services.new_item_service.model_files_from_import", lambda *a, **k: files)
    monkeypatch.setattr("cdmw.services.new_item_planning.model_files_from_import", lambda *a, **k: files)
    monkeypatch.setattr("cdmw.services.new_item_materials.source_materials_from_import",
                        lambda *args: {name.casefold(): replace(source, name=name)})

    def cancelled(*args, **kwargs):
        received.append(kwargs["stop_event"])
        stop.set()
        raise RunCancelled()

    monkeypatch.setattr(texture_native, "encode_dds_with_directxtex", cancelled)
    request = replace(spec(), model_source=ModelSource.IMPORTED, material_route=MaterialRoute.PLAIN_PBR,
                      translucency=TranslucencyChoice((name,)))
    with pytest.raises(RunCancelled):
        service.plan(request, snapshot, model=object(), scene=object(), stop_event=stop)
    assert received == [stop]
    assert not owner._BASE_CACHE
