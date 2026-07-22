from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = ROOT / "cdmw" / "ui" / "model_library" / "preview.py"
SERVICE_SOURCE = ROOT / "cdmw" / "services" / "model_library_preview.py"


def test_model_library_preview_keeps_fast_first_dotnet_package_and_tracks_quality_setting() -> None:
    source = UI_SOURCE.read_text(encoding="utf-8")

    assert 'high_quality_textures = bool(getattr(preview_render_settings, "high_quality_by_default", True))' in source
    assert "high_quality_textures=False" in source
    assert 'high_quality_textures=bool(result.get("high_quality_textures", high_quality_textures))' in source


def test_model_library_preview_event_logs_actual_high_quality_value() -> None:
    source = UI_SOURCE.read_text(encoding="utf-8")

    assert 'high_quality_textures=bool(result.get("high_quality_textures", high_quality_textures))' in source
    assert source.count("model_library_preview_prepared") == 1
    assert "model_library_dotnet_package_requested" in source


def test_model_library_preview_service_returns_high_quality_value() -> None:
    source = SERVICE_SOURCE.read_text(encoding="utf-8")

    assert '"high_quality_textures": bool(high_quality_textures)' in source
    assert "build_or_lookup_dotnet_preview_package_from_model" in source
    assert '"dotnet_preview_package_path": package_dir' in source
