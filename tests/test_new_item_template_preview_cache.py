from dataclasses import replace
from types import SimpleNamespace
import threading

import pytest

from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.new_item import template_preview_cache


@pytest.mark.parametrize("changed", ["primary", "other_texture", "other_index", "removed_archive", "native", "settings", "dependency", "prepared"])
def test_native_template_identity_tracks_all_archive_and_render_inputs(tmp_path, monkeypatch, changed):
    root = tmp_path / "game"
    primary = root / "0000"
    other = root / "0001"
    primary.mkdir(parents=True)
    other.mkdir()
    paths = {
        "primary": primary / "0.paz", "other_texture": other / "0.paz",
        "other_index": other / "0.pamt", "removed_archive": other / "1.paz",
        "native": tmp_path / "preview-core.exe",
        "prepared": tmp_path / "prepared.pac",
    }
    (primary / "0.pamt").write_bytes(b"index")
    for path in paths.values():
        path.write_bytes(b"before")
    monkeypatch.setattr(template_preview_cache, "find_native_preview_core_binary", lambda: paths["native"])
    entry = SimpleNamespace(path="item.pac", pamt_path=primary / "0.pamt", paz_file="0.paz", offset=7, comp_size=3)
    entry.prepared_path = paths["prepared"]
    settings = ModelPreviewRenderSettings(use_textures_by_default=True)
    stop = threading.Event()

    def identity():
        return template_preview_cache.template_preview_cache_identity(entry, (entry,), 17, settings, stop)

    before = identity()
    assert identity() == before
    if changed == "settings":
        settings = replace(settings, d3d11_tone_gamma=1.17)
    elif changed == "dependency":
        entry.offset += 1
    elif changed == "removed_archive":
        paths[changed].unlink()
    else:
        paths[changed].write_bytes(b"changed archive or compiler")
    assert identity() != before
