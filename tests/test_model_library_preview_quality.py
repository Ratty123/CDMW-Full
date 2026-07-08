from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = ROOT / "cdmw" / "ui" / "model_library" / "preview.py"
SERVICE_SOURCE = ROOT / "cdmw" / "services" / "model_library_preview.py"


def test_model_library_preview_uses_active_render_setting_for_high_quality_textures() -> None:
    source = UI_SOURCE.read_text(encoding="utf-8")

    assert 'high_quality_textures = bool(getattr(preview_render_settings, "high_quality_by_default", True))' in source
    assert "high_quality_textures=high_quality_textures" in source
    assert "high_quality_textures=False" not in source


def test_model_library_preview_event_logs_actual_high_quality_value() -> None:
    source = UI_SOURCE.read_text(encoding="utf-8")

    assert 'high_quality_textures=bool(result.get("high_quality_textures", high_quality_textures))' in source
    assert source.count("model_library_preview_prepared") >= 2


def test_model_library_preview_service_returns_high_quality_value() -> None:
    source = SERVICE_SOURCE.read_text(encoding="utf-8")

    assert '"high_quality_textures": bool(high_quality_textures)' in source
    assert "write_isolated_d3d11_preview_package" in source
    assert "high_quality_textures=bool(high_quality_textures)" in source
