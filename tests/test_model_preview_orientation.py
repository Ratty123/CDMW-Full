from pathlib import Path

from cdmw.core.model_preview_orientation import scene_import_normalizes_texture_v


def test_scene_import_normalizes_texture_v_for_scene_formats_only() -> None:
    for extension in ("obj", "gltf", "glb", "dae", "collada"):
        assert scene_import_normalizes_texture_v(extension) is True

    for extension in ("pac", "pam", "pamlod", ""):
        assert scene_import_normalizes_texture_v(extension) is False

    assert scene_import_normalizes_texture_v("", Path("model.obj")) is True
    assert scene_import_normalizes_texture_v("", Path("model.pac")) is False
