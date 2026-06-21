from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict

from cdmw.models import DdsOutputSettings


def resolve_default_staging_png_root(png_root: Path, use_separate_output_root: bool) -> Path:
    if not use_separate_output_root:
        return png_root
    return png_root.parent / f"{png_root.name}_staged_input"


def build_manifest_path(output_root: Path) -> Path:
    return output_root / ".cdmw_manifest.json"


def load_incremental_manifest(manifest_path: Path) -> Dict[str, Dict[str, object]]:
    source_path = manifest_path
    if not source_path.exists():
        legacy_paths = (
            manifest_path.with_name(".dds_rebuild_manifest.json"),
        )
        source_path = next((legacy_path for legacy_path in legacy_paths if legacy_path.exists()), source_path)
        if not source_path.exists():
            return {}
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    entries = payload.get("entries", {}) if isinstance(payload, dict) else {}
    return entries if isinstance(entries, dict) else {}


def save_incremental_manifest(manifest_path: Path, entries: Dict[str, Dict[str, object]]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    payload = {
        "version": 1,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "entries": entries,
    }
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(manifest_path)


def build_incremental_manifest_entry(
    original_dds: Path,
    png_path: Path,
    output_file: Path,
    output_settings: DdsOutputSettings,
) -> Dict[str, object]:
    original_stat = original_dds.stat()
    png_stat = png_path.stat()
    output_stat = output_file.stat()
    return {
        "original_mtime_ns": original_stat.st_mtime_ns,
        "original_size": original_stat.st_size,
        "png_mtime_ns": png_stat.st_mtime_ns,
        "png_size": png_stat.st_size,
        "output_mtime_ns": output_stat.st_mtime_ns,
        "output_size": output_stat.st_size,
        "format": output_settings.texconv_format,
        "mips": output_settings.mip_count,
        "resize": output_settings.resize_to_dimensions,
        "width": output_settings.width,
        "height": output_settings.height,
        "color_args": list(output_settings.texconv_color_args),
        "extra_args": list(output_settings.texconv_extra_args),
    }


def manifest_entry_matches(
    entry: Dict[str, object],
    original_dds: Path,
    png_path: Path,
    output_file: Path,
    output_settings: DdsOutputSettings,
) -> bool:
    if not output_file.exists():
        return False
    try:
        expected = build_incremental_manifest_entry(original_dds, png_path, output_file, output_settings)
    except OSError:
        return False
    for key, value in expected.items():
        if entry.get(key) != value:
            return False
    return True
