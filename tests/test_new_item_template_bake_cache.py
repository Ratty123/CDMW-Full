"""Template bake reuse must track authored inputs and never retain partial work."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace

import pytest

from cdmw.core import texture_native
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.new_item.translucency import TranslucencyChoice
from cdmw.services import new_item_template_materials as owner
from cdmw.services.new_item_template_model import prepare_template_model
from tests.test_new_item_template_translucency_bake import BLADE, MASK, PAC, PAC_XML, layered_inputs


@pytest.fixture
def baking(monkeypatch):
    files, calls, reads = layered_inputs(), [], []
    def payload(path):
        reads.append(path)
        return files[path]
    def bake(*args):
        calls.append(args)
        return {"base": b"base", "normal": b"normal", "material": b"surface"}
    monkeypatch.setattr(owner, "_BAKE_CACHE", OrderedDict())
    monkeypatch.setattr(owner, "_bake_material_maps", bake)
    monkeypatch.setattr(texture_native, "native_texture_backend_identity", lambda: "encoder-one")
    snapshot = SimpleNamespace(payload=payload, has_entry=files.__contains__)
    def prepare(stop=None):
        return prepare_template_model(snapshot, [PAC], translucency=TranslucencyChoice((BLADE,)), stop_event=stop)
    return files, calls, reads, bake, prepare


@pytest.mark.parametrize("change", ["dds", "xml", "encoder", "missing"])
def test_cache_rechecks_source_bytes_material_parameters_and_encoder(baking, monkeypatch, change):
    files, calls, reads, _, prepare = baking
    first = prepare()
    reads.clear()
    assert prepare().side_files == first.side_files
    assert len(calls) == 1
    assert MASK in reads, "cached output still registers source DDS provenance"
    if change == "dds":
        # The path and length stay unchanged.
        data = files[MASK]
        files[MASK] = data[:-1] + bytes([data[-1] ^ 1])
    elif change == "xml":
        files[PAC_XML] = files[PAC_XML].replace(b"#FF2020FF", b"#FF1020FF")
    elif change == "encoder":
        monkeypatch.setattr(texture_native, "native_texture_backend_identity", lambda: "encoder-two")
    else:
        del files[MASK]
        with pytest.raises(owner.NewItemPlanError, match="missing texture"):
            prepare()
        return
    prepare()
    assert len(calls) == 2


@pytest.mark.parametrize("limit", ["bytes", "entries"])
def test_cache_evicts_lru_and_does_not_keep_oversized_bakes(baking, monkeypatch, limit):
    files, calls, _, _, prepare = baking
    monkeypatch.setattr(owner, "_BAKE_CACHE_MAX_BYTES", 17 if limit == "bytes" else 34)
    monkeypatch.setattr(owner, "_BAKE_CACHE_MAX_ENTRIES", 2 if limit == "bytes" else 1)
    original = files[PAC_XML]
    prepare()
    files[PAC_XML] = original.replace(b"#FF2020FF", b"#FF1020FF")
    prepare()
    assert len(owner._BAKE_CACHE) == 1
    files[PAC_XML] = original
    prepare()
    assert len(calls) == 3
    owner._BAKE_CACHE.clear()
    monkeypatch.setattr(owner, "_BAKE_CACHE_MAX_BYTES", 16)
    prepare()
    assert not owner._BAKE_CACHE


@pytest.mark.parametrize("failure", ["error", "cancel"])
def test_failed_or_cancelled_material_is_not_cached_and_can_retry(baking, monkeypatch, failure):
    _, _, _, bake, prepare = baking
    stop = threading.Event()
    def incomplete(*args):
        if failure == "error":
            raise owner.NewItemPlanError("encode failed")
        result = bake(*args)
        stop.set()  # The helper can finish just as cancellation arrives.
        return result
    monkeypatch.setattr(owner, "_bake_material_maps", incomplete)
    with pytest.raises(owner.NewItemPlanError if failure == "error" else RunCancelled):
        prepare(stop)
    assert not owner._BAKE_CACHE
    stop.clear()
    monkeypatch.setattr(owner, "_bake_material_maps", bake)
    assert prepare(stop)
    stop.set()
    with pytest.raises(RunCancelled):
        prepare(stop)


def test_waiting_for_shared_bake_is_cancellable_and_duplicate_is_reused(baking, monkeypatch):
    _, calls, _, bake, prepare = baking
    entered, release, stop = threading.Event(), threading.Event(), threading.Event()
    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return bake(*args)
    monkeypatch.setattr(owner, "_bake_material_maps", blocked)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(prepare)
        try:
            assert entered.wait(3)
            waiting = pool.submit(prepare, stop)
            duplicate = pool.submit(prepare)
            stop.set()
            with pytest.raises(RunCancelled):
                waiting.result(timeout=2)
        finally:
            release.set()
        assert duplicate.result(timeout=3).side_files == first.result(timeout=3).side_files
    assert len(calls) == 1
