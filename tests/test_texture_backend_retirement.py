from __future__ import annotations

import ast
import dataclasses
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.core.chainner import build_chainner_override_payload
from cdmw.core.dds_native import inspect_dds_native_path
from cdmw.core.texture_pipeline.inspection import parse_dds
from cdmw.core.texture_legacy_compat import (
    OBSOLETE_CHAIN_TOKEN,
    OBSOLETE_CONFIG_KEY,
    OBSOLETE_SETTINGS_KEY,
    resolve_deprecated_preview_source,
    sanitized_profile_mapping,
)
from cdmw.models import AppConfig
from cdmw.ui.shell.profile_controller import ProfileControllerMixin, load_profile_import_document


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_RETIREMENT_SOURCE = ROOT / "cdmw" / "core" / "texture_legacy_compat.py"
SOURCE_SUFFIXES = {".py", ".pyi", ".cpp", ".h", ".cs", ".csproj", ".ps1", ".spec", ".md", ".txt"}
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "bin",
    "build",
    "dist",
    "obj",
    # `docs/plans/` is in `.git/info/exclude`: implementation plans are local scratch
    # and are never committed. Scanning them makes this guard fail on whatever notes a
    # developer happens to have open, which says nothing about the shipped source.
    "plans",
    "third_party",
}


def _production_source_files() -> tuple[Path, ...]:
    roots = (
        ROOT / "cdmw",
        ROOT / "native",
        ROOT / "tools",
        ROOT / "scripts",
        ROOT / "docs",
    )
    files: list[Path] = [
        ROOT / "README.md",
        ROOT / "THIRD_PARTY_NOTICES.md",
        ROOT / "CrimsonDesertModWorkbench.spec",
        ROOT / "build_native_windows.ps1",
        ROOT / "build_pyside6_app.ps1",
    ]
    for source_root in roots:
        for path in source_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            if EXCLUDED_PARTS.intersection(path.relative_to(ROOT).parts):
                continue
            files.append(path)
    return tuple(dict.fromkeys(path.resolve() for path in files if path.is_file()))


def test_retired_texture_tool_name_is_confined_to_compatibility_shim() -> None:
    retired_name = "tex" + "conv"
    offenders = []
    for path in _production_source_files():
        if path == ALLOWED_RETIREMENT_SOURCE.resolve():
            continue
        if retired_name in path.read_text(encoding="utf-8", errors="ignore").casefold():
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []
    assert not (ROOT / "cdmw" / "core" / "texture_pipeline" / f"{retired_name}.py").exists()


def test_canonical_configuration_has_no_retired_backend_path() -> None:
    assert OBSOLETE_CONFIG_KEY not in {field.name for field in dataclasses.fields(AppConfig)}
    assert OBSOLETE_CONFIG_KEY not in dataclasses.asdict(AppConfig())


def test_legacy_profile_values_are_accepted_discarded_and_not_reexported(tmp_path: Path) -> None:
    payload = {
        "profile_format": 3,
        OBSOLETE_CONFIG_KEY: "C:/legacy/tool.exe",
        "paths": {OBSOLETE_CONFIG_KEY: "C:/legacy/nested.exe", "keep": "value"},
        "config": {
            "output_root": "D:/output",
            OBSOLETE_CONFIG_KEY: "C:/legacy/config.exe",
            "paths": {OBSOLETE_CONFIG_KEY: "C:/legacy/config-nested.exe", "keep": "config"},
        },
        "settings": {
            OBSOLETE_SETTINGS_KEY: "C:/legacy/settings.exe",
            "appearance/theme": "dark",
        },
    }
    sanitized = sanitized_profile_mapping(payload)
    assert OBSOLETE_CONFIG_KEY not in sanitized
    assert OBSOLETE_CONFIG_KEY not in sanitized["paths"]
    assert OBSOLETE_CONFIG_KEY not in sanitized["config"]
    assert OBSOLETE_CONFIG_KEY not in sanitized["config"]["paths"]
    assert OBSOLETE_SETTINGS_KEY not in sanitized["settings"]
    assert sanitized["paths"]["keep"] == "value"
    assert sanitized["config"]["paths"]["keep"] == "config"

    source = tmp_path / "legacy-profile.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    document = load_profile_import_document(source, current_theme_key="dark")
    assert document.config.output_root == "D:/output"
    assert document.decoded_settings == (("appearance/theme", "dark"),)

    class _Profile(ProfileControllerMixin):
        current_theme_key = "dark"

        @staticmethod
        def collect_config() -> AppConfig:
            return AppConfig(output_root="D:/output")

        @staticmethod
        def _collect_profile_settings_snapshot(*, flush: bool = True) -> dict[str, object]:
            del flush
            return {"appearance/theme": "dark"}

    exported = _Profile()._collect_profile_payload(flush=False)
    assert exported["profile_format"] == 4
    exported_text = json.dumps(exported)
    assert OBSOLETE_CONFIG_KEY not in exported_text
    assert OBSOLETE_SETTINGS_KEY not in exported_text


def test_obsolete_chain_token_fails_preflight_explicitly() -> None:
    config = SimpleNamespace(
        chainner_override_json=json.dumps({"inputs": {"legacy": OBSOLETE_CHAIN_TOKEN}}),
        dds_staging_root=None,
    )
    with pytest.raises(ValueError, match="obsolete"):
        build_chainner_override_payload(config)


def test_legacy_preview_argument_is_accepted_but_warned_and_ignored(tmp_path: Path) -> None:
    source = tmp_path / "source.dds"
    obsolete_backend = tmp_path / "retired.exe"
    with pytest.warns(DeprecationWarning, match="obsolete and ignored"):
        resolved = resolve_deprecated_preview_source(obsolete_backend, source)
    assert resolved == source


def test_packaging_bundles_only_native_texture_helper() -> None:
    spec_source = (ROOT / "CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")
    builder_source = (ROOT / "build_pyside6_app.ps1").read_text(encoding="utf-8")
    retired_name = "tex" + "conv.exe"
    assert "cd-texture-dx.exe" in spec_source
    assert retired_name not in spec_source.casefold()
    assert "Test-OnedirTextureBackend" in builder_source
    assert "Test-OnefileTextureBackend" in builder_source
    assert retired_name not in builder_source.casefold()


def test_headless_harness_imports_no_qt_and_calls_production_owners() -> None:
    harness_path = ROOT / "tools" / "texture_replacer_headless_harness.py"
    source = harness_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module)
            imported_names.update(alias.name for alias in node.names)
    qt_prefix = "Py" + "Side6"
    assert all(not name.startswith(qt_prefix) for name in imported_modules)
    assert {"QApplication", "MainWindow"}.isdisjoint(imported_names)
    for required in (
        "build_replace_assistant_package(",
        "rebuild_dds_files(",
        "normalize_texture_editor_source_to_png(",
        "TextureEditorNativeDdsService().preview_compressed(",
        "analyze_recolor_variant_package(",
        "build_item_icon_payload(",
        "_build_texture_payload(",
        "build_archive_texture_payload_from_dds(",
        "build_archive_texture_payload_from_png(",
    ):
        assert required in source
    assert "--scenario" in source
    assert "--native-binary" in source
    assert "--edited-dds" in source
    assert "--original-dds" in source
    assert "--virtual-path" in source


def _legacy_numeric_dds(numeric_fourcc: int, *, bytes_per_pixel: int) -> bytes:
    width = height = 4
    data = bytearray(128)
    data[0:4] = b"DDS "
    struct.pack_into("<I", data, 4, 124)
    struct.pack_into("<I", data, 12, height)
    struct.pack_into("<I", data, 16, width)
    struct.pack_into("<I", data, 28, 1)
    struct.pack_into("<I", data, 76, 32)
    struct.pack_into("<I", data, 80, 0x4)
    struct.pack_into("<I", data, 84, numeric_fourcc)
    return bytes(data) + (b"\x00" * (width * height * bytes_per_pixel))


def _legacy_bgrx_dds() -> bytes:
    width = height = 4
    data = bytearray(128)
    data[0:4] = b"DDS "
    struct.pack_into("<I", data, 4, 124)
    struct.pack_into("<I", data, 12, height)
    struct.pack_into("<I", data, 16, width)
    struct.pack_into("<I", data, 28, 1)
    struct.pack_into("<I", data, 76, 32)
    struct.pack_into("<I", data, 80, 0x40)
    struct.pack_into("<I", data, 88, 32)
    struct.pack_into("<I", data, 92, 0x00FF0000)
    struct.pack_into("<I", data, 96, 0x0000FF00)
    struct.pack_into("<I", data, 100, 0x000000FF)
    struct.pack_into("<I", data, 104, 0)
    return bytes(data) + (b"\x00" * (width * height * 4))


@pytest.mark.parametrize(
    ("numeric_fourcc", "expected_format", "bytes_per_pixel"),
    (
        (110, "R16G16B16A16_SNORM", 8),
        (111, "R16_FLOAT", 2),
        (112, "R16G16_FLOAT", 4),
        (113, "R16G16B16A16_FLOAT", 8),
        (114, "R32_FLOAT", 4),
        (115, "R32G32_FLOAT", 8),
        (116, "R32G32B32A32_FLOAT", 16),
    ),
)
def test_legacy_numeric_native_outputs_roundtrip_through_both_parsers(
    tmp_path: Path,
    numeric_fourcc: int,
    expected_format: str,
    bytes_per_pixel: int,
) -> None:
    path = tmp_path / f"{expected_format}.dds"
    path.write_bytes(_legacy_numeric_dds(numeric_fourcc, bytes_per_pixel=bytes_per_pixel))
    assert parse_dds(path).dds_format == expected_format
    assert inspect_dds_native_path(path).format_name == expected_format


def test_legacy_bgrx_output_is_not_misclassified_as_bgra(tmp_path: Path) -> None:
    path = tmp_path / "bgrx.dds"
    path.write_bytes(_legacy_bgrx_dds())
    assert parse_dds(path).dds_format == "B8G8R8X8_UNORM"
    info = inspect_dds_native_path(path)
    assert info.format_name == "B8G8R8X8_UNORM"
    assert info.has_alpha is False
