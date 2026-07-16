#!/usr/bin/env python
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence
from unittest.mock import patch
from uuid import uuid4

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cdmw.constants import SUPPORTED_DDS_FORMAT_CHOICES
from cdmw.core import texture_native
from cdmw.core.archive_patching import (
    build_archive_texture_payload_from_dds,
    build_archive_texture_payload_from_png,
)
from cdmw.core.common import (
    ProcessTimeoutExpired,
    run_process_with_cancellation as run_process_with_cancellation_real,
)
from cdmw.core.dds_native import dds_native_report_dict, inspect_dds_native_path
from cdmw.core.item_icon import build_item_icon_payload
from cdmw.core.mod_package import mod_package_export_options_for_profiles
from cdmw.core.pipeline import rebuild_dds_files
from cdmw.core.recolor_variants import (
    analyze_recolor_variant_package,
    default_recolor_variant_templates,
    preview_recolor_variant_target_image,
)
from cdmw.core.replace_assistant import (
    build_replace_assistant_archive_index,
    build_replace_assistant_items,
    build_replace_assistant_package,
    match_replace_assistant_original,
)
from cdmw.core.texture_editor_project_io import normalize_texture_editor_source_to_png
from cdmw.core.texture_pipeline.inspection import parse_dds, read_png_header_info
from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
from cdmw.domain.library.item_icons import ItemIconOverrideSpec
from cdmw.modding.material_replacer import (
    ReplacementTextureSlot,
    TextureReplacementReport,
    _build_texture_payload,
)
from cdmw.models import (
    AppConfig,
    ArchiveEntry,
    ModPackageInfo,
    ReplaceAssistantBuildOptions,
    RunCancelled,
    TextureEditorDocument,
    TextureEditorLayer,
)
from cdmw.services.texture_editor_service import (
    TextureEditorNativeDdsOptions,
    TextureEditorNativeDdsService,
)


SCHEMA_VERSION = 1
DEFAULT_VIRTUAL_PATH = "0009/character/texture/cd_phw_00_nude_00_0001_hand.dds"
SCENARIO_NAMES = (
    "reported-bc7-rebuild",
    "policy-matrix",
    "consumer-matrix",
    "failure-lifecycle",
    "full-suite",
)
NATIVE_TEXTURE_EXECUTABLES = frozenset({"cd-texture-dx.exe", "cd-texture-dx"})
NATIVE_TEXTURE_COMMANDS = frozenset(
    {
        "self-test",
        "inspect-json",
        "batch-preview-json",
        "batch-encode-json",
    }
)
QT_MODULE_PREFIX = "Py" "Side6"


class HarnessPrerequisiteError(RuntimeError):
    pass


class ScenarioFailure(AssertionError):
    pass


def _check(condition: object, message: str) -> None:
    if not condition:
        raise ScenarioFailure(message)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(path: Path) -> dict[str, object]:
    resolved = path.expanduser().resolve()
    stat = resolved.stat()
    return {
        "path": str(resolved),
        "size": int(stat.st_size),
        "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
        "sha256": _sha256_file(resolved),
    }


def _assert_headless_imports() -> None:
    imported = sorted(name for name in sys.modules if name == QT_MODULE_PREFIX or name.startswith(f"{QT_MODULE_PREFIX}."))
    if imported:
        raise ScenarioFailure(f"Headless harness imported Qt modules: {', '.join(imported[:8])}")


def _normalize_virtual_path(raw_value: str) -> PurePosixPath:
    text = str(raw_value or DEFAULT_VIRTUAL_PATH).replace("\\", "/").strip().strip("/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise HarnessPrerequisiteError(f"Invalid virtual path: {raw_value!r}")
    parts = list(path.parts)
    if not (parts and len(parts[0]) == 4 and parts[0].isdigit()):
        parts.insert(0, "0009")
    normalized = PurePosixPath(*parts)
    if normalized.suffix.lower() != ".dds":
        raise HarnessPrerequisiteError("The harness virtual path must end in .dds.")
    return normalized


def _dds_alpha_mode_value(path: Path) -> int:
    data = path.read_bytes()[:148]
    if len(data) < 148 or data[84:88] != b"DX10":
        return 0
    return int.from_bytes(data[144:148], "little") & 0x7


def _make_fixture_png(path: Path, width: int, height: int, variant: str) -> Path:
    width = max(1, int(width))
    height = max(1, int(height))
    x = np.arange(width, dtype=np.uint32)[None, :]
    y = np.arange(height, dtype=np.uint32)[:, None]
    pixels = np.empty((height, width, 4), dtype=np.uint8)
    if variant == "albedo-original":
        pixels[..., 0] = ((x * 7 + y * 3 + 31) & 0xFF).astype(np.uint8)
        pixels[..., 1] = ((x * 2 + y * 5 + 67) & 0xFF).astype(np.uint8)
        pixels[..., 2] = ((x * 3 + y * 2 + 113) & 0xFF).astype(np.uint8)
        pixels[..., 3] = 255
    elif variant == "albedo-edited":
        pixels[..., 0] = ((x * 5 + y * 2 + 83) & 0xFF).astype(np.uint8)
        pixels[..., 1] = ((x * 3 + y * 7 + 29) & 0xFF).astype(np.uint8)
        pixels[..., 2] = ((x * 2 + y * 3 + 151) & 0xFF).astype(np.uint8)
        pixels[..., 3] = np.where(((x // 32 + y // 32) & 1) == 0, 255, 224).astype(np.uint8)
    elif variant == "gradient":
        pixels[..., 0] = ((x * 255) // max(1, width - 1)).astype(np.uint8)
        pixels[..., 1] = ((y * 255) // max(1, height - 1)).astype(np.uint8)
        pixels[..., 2] = (((x + y) * 255) // max(1, width + height - 2)).astype(np.uint8)
        pixels[..., 3] = 255
    elif variant == "checker-alpha":
        block = max(1, min(width, height) // 8)
        pixels[..., 0] = 210
        pixels[..., 1] = 80
        pixels[..., 2] = 30
        pixels[..., 3] = np.where(((x // block + y // block) & 1) == 0, 255, 0).astype(np.uint8)
    elif variant == "normal":
        pixels[..., 0] = 128
        pixels[..., 1] = 64
        pixels[..., 2] = 255
        pixels[..., 3] = 255
    elif variant == "gray":
        value = ((x * 255) // max(1, width - 1)).astype(np.uint8)
        pixels[..., 0] = value
        pixels[..., 1] = value
        pixels[..., 2] = value
        pixels[..., 3] = 255
    elif variant == "solid-red":
        pixels[...] = (220, 30, 20, 255)
    elif variant == "solid-blue":
        pixels[...] = (20, 60, 220, 255)
    elif variant == "icon":
        pixels[...] = (0, 0, 0, 0)
        inset_x = max(1, width // 4)
        inset_y = max(1, height // 4)
        pixels[inset_y : height - inset_y, inset_x : width - inset_x] = (240, 180, 40, 255)
    else:
        raise ValueError(f"Unknown fixture variant: {variant}")
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels, "RGBA").save(path, format="PNG")
    return path


def _rgba_pixels(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()


def _encode_required(
    png_path: Path,
    output_path: Path,
    *,
    dds_format: str,
    width: int = 0,
    height: int = 0,
    mip_count: int = 1,
    overwrite: bool = True,
    source_color_policy: str = "auto",
    mip_alpha_policy: str = "default",
    alpha_coverage_reference: float = 0.5,
    dds_alpha_mode: str = "unknown",
) -> dict[str, object]:
    report = texture_native.encode_dds_with_directxtex(
        png_path,
        output_path,
        dds_format=dds_format,
        width=width,
        height=height,
        mip_count=mip_count,
        overwrite=overwrite,
        source_color_policy=source_color_policy,
        mip_alpha_policy=mip_alpha_policy,
        alpha_coverage_reference=alpha_coverage_reference,
        dds_alpha_mode=dds_alpha_mode,
    )
    _check(bool(report), f"Native encode returned no report for {output_path.name}.")
    _check(output_path.is_file(), f"Native encode did not create {output_path}.")
    return dict(report or {})


def _decode_required(
    dds_path: Path,
    output_path: Path,
    *,
    requested_mip: int = 0,
    output_pixel_type: str = "rgba8",
    slot_kind: str = "base",
    normal_space: str = "auto",
) -> dict[str, object]:
    report = texture_native.decode_dds_preview_with_directxtex(
        dds_path,
        output_path,
        max_dimension=0,
        requested_mip=requested_mip,
        output_pixel_type=output_pixel_type,
        slot_kind=slot_kind,
        normal_space=normal_space,
    )
    _check(bool(report), f"Native decode returned no report for {dds_path.name} mip {requested_mip}.")
    _check(output_path.is_file(), f"Native decode did not create {output_path}.")
    return dict(report or {})


def _archive_entry(root: Path, virtual_path: str) -> ArchiveEntry:
    package_root = root / "0009"
    package_root.mkdir(parents=True, exist_ok=True)
    return ArchiveEntry(
        path=virtual_path,
        pamt_path=package_root / "0.pamt",
        paz_file=package_root / "0.paz",
        offset=0,
        comp_size=0,
        orig_size=0,
        flags=0,
        paz_index=0,
    )


def _replace_build_options(output_parent: Path, *, title: str) -> ReplaceAssistantBuildOptions:
    return ReplaceAssistantBuildOptions(
        package_output_root=output_parent,
        overwrite_existing_package_files=True,
        create_no_encrypt_file=True,
        build_mode="rebuild_only",
        size_mode="match_original",
        ncnn_exe_path=None,
        ncnn_model_dir=None,
        ncnn_model_name="",
        ncnn_scale=4,
        ncnn_tile_size=0,
        ncnn_extra_args="",
        retry_smaller_tile_on_failure=False,
        upscale_post_correction_mode="none",
        upscale_texture_preset="all",
        enable_automatic_texture_rules=False,
        enable_unsafe_technical_override=False,
        package_info=ModPackageInfo(title=title),
        export_options=mod_package_export_options_for_profiles(("dmm",)),
    )


def _write_recolor_package(root: Path, base_dds: Path, normal_dds: Path) -> Path:
    mod_root = root / "SourceMod"
    files_root = mod_root / "files"
    sidecar_path = files_root / "character" / "modelproperty" / "weapon.pac_xml"
    model_path = files_root / "character" / "model" / "weapon.pac"
    texture_root = files_root / "character" / "texture"
    texture_root.mkdir(parents=True, exist_ok=True)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    (mod_root / "manifest.json").write_text(
        json.dumps({"title": "Harness Recolor Source", "version": "1.0", "author": "CDMW"}),
        encoding="utf-8",
    )
    (mod_root / "modinfo.json").write_text(json.dumps({"name": "Harness Recolor Source"}), encoding="utf-8")
    model_path.write_bytes(b"PAC")
    sidecar_path.write_text(
        """
<SkinnedMeshMaterialWrapper _subMeshName="Blade">
  <Material _materialName="SkinnedMeshStandard_Ver2">
    <Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/blade_basecolor.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterTexture StringItemID="_normalTexture" _name="_normalTexture" Index="1">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/blade_n.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterColor StringItemID="_tintColorR" _name="_tintColorR" Value="#112233ff"/>
    </Vector>
  </Material>
</SkinnedMeshMaterialWrapper>
""".strip(),
        encoding="utf-8",
    )
    shutil.copy2(base_dds, texture_root / "blade_basecolor.dds")
    shutil.copy2(normal_dds, texture_root / "blade_n.dds")
    return mod_root


def _pid_is_running(process_id: int) -> bool:
    pid = int(process_id)
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
    open_process.restype = ctypes.c_void_p
    get_exit_code = kernel32.GetExitCodeProcess
    get_exit_code.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
    get_exit_code.restype = ctypes.c_int
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_int
    handle = open_process(0x1000 | 0x00100000, 0, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not get_exit_code(handle, ctypes.byref(exit_code)):
            return False
        return int(exit_code.value) == 259
    finally:
        close_handle(handle)


@dataclass(slots=True)
class RecordingProcessDelegate:
    delegate: Callable[..., tuple[int, str, str]]
    commands: list[dict[str, object]] = field(default_factory=list)

    def _validate(self, command: Sequence[str]) -> None:
        if not command:
            raise ScenarioFailure("Attempted to launch an empty subprocess command.")
        executable_name = Path(str(command[0])).name.casefold()
        operation = str(command[1]).casefold() if len(command) > 1 else ""
        retired_names = {"tex" + "conv.exe", "tex" + "conv"}
        if executable_name in retired_names:
            raise ScenarioFailure("Retired texture executable was launched by the harness.")
        is_texture_command = operation in NATIVE_TEXTURE_COMMANDS or "texture" in executable_name
        if is_texture_command and executable_name not in NATIVE_TEXTURE_EXECUTABLES:
            raise ScenarioFailure(
                f"Texture subprocess must be cd-texture-dx.exe, got {Path(str(command[0])).name}."
            )

    def __call__(self, command: Sequence[str], *args: object, **kwargs: object) -> tuple[int, str, str]:
        normalized = [str(part) for part in command]
        self._validate(normalized)
        record: dict[str, object] = {
            "index": len(self.commands),
            "command": normalized,
            "started_utc": _utc_now(),
            "injected": False,
        }
        started = time.monotonic()
        try:
            returncode, stdout, stderr = self.delegate(normalized, *args, **kwargs)
        except BaseException as exc:
            record.update(
                {
                    "status": "exception",
                    "exception_type": type(exc).__name__,
                    "exception": str(exc),
                    "elapsed_seconds": time.monotonic() - started,
                }
            )
            self.commands.append(record)
            raise
        record.update(
            {
                "status": "completed",
                "returncode": int(returncode),
                "stdout_tail": str(stdout or "")[-4000:],
                "stderr_tail": str(stderr or "")[-4000:],
                "elapsed_seconds": time.monotonic() - started,
            }
        )
        self.commands.append(record)
        return int(returncode), str(stdout or ""), str(stderr or "")

    def record_injected(self, command: Sequence[str], *, failure: str) -> None:
        normalized = [str(part) for part in command]
        self._validate(normalized)
        self.commands.append(
            {
                "index": len(self.commands),
                "command": normalized,
                "started_utc": _utc_now(),
                "elapsed_seconds": 0.0,
                "status": "injected_failure",
                "injected": True,
                "failure": str(failure),
            }
        )


@dataclass(slots=True)
class HarnessContext:
    output_root: Path
    run_root: Path
    temp_root: Path
    native_binary: Path
    recorder: RecordingProcessDelegate
    args: argparse.Namespace
    artifacts: list[dict[str, object]] = field(default_factory=list)
    dds_metadata: list[dict[str, object]] = field(default_factory=list)

    def scenario_root(self, name: str) -> Path:
        path = self.run_root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def add_artifact(self, path: Path, kind: str) -> None:
        resolved = path.expanduser().resolve()
        record: dict[str, object] = {
            "kind": str(kind),
            "path": str(resolved),
            "exists": resolved.exists(),
        }
        try:
            record["relative_path"] = resolved.relative_to(self.output_root).as_posix()
        except ValueError:
            record["relative_path"] = ""
        if resolved.is_file():
            stat = resolved.stat()
            record["size"] = int(stat.st_size)
            record["sha256"] = _sha256_file(resolved)
        self.artifacts.append(record)
        if resolved.is_file() and resolved.suffix.lower() == ".dds":
            info = inspect_dds_native_path(resolved)
            metadata = dds_native_report_dict(resolved, info)
            metadata["dds_alpha_mode_value"] = _dds_alpha_mode_value(resolved)
            self.dds_metadata.append(metadata)


def _scenario_reported_bc7_rebuild(context: HarnessContext) -> dict[str, object]:
    root = context.scenario_root("reported-bc7-rebuild")
    virtual_path = _normalize_virtual_path(context.args.virtual_path)
    original_path = root.joinpath("originals", *virtual_path.parts)
    edited_path = root.joinpath("edits", *virtual_path.parts)
    original_path.parent.mkdir(parents=True, exist_ok=True)
    edited_path.parent.mkdir(parents=True, exist_ok=True)

    if context.args.original_dds is not None:
        shutil.copy2(Path(context.args.original_dds).expanduser().resolve(), original_path)
    else:
        original_png = _make_fixture_png(root / "fixtures" / "original.png", 2048, 2048, "albedo-original")
        _encode_required(
            original_png,
            original_path,
            dds_format="BC7_UNORM",
            width=2048,
            height=2048,
            mip_count=12,
            dds_alpha_mode="straight",
        )
        context.add_artifact(original_png, "reported-original-png")

    if context.args.edited_dds is not None:
        shutil.copy2(Path(context.args.edited_dds).expanduser().resolve(), edited_path)
    else:
        edited_png = _make_fixture_png(root / "fixtures" / "edited.png", 2048, 2048, "albedo-edited")
        _encode_required(
            edited_png,
            edited_path,
            dds_format="BC7_UNORM",
            width=2048,
            height=2048,
            mip_count=12,
            dds_alpha_mode="straight",
        )
        context.add_artifact(edited_png, "reported-edited-png")

    try:
        original_info = parse_dds(original_path)
        edited_info = parse_dds(edited_path)
    except Exception as exc:
        raise HarnessPrerequisiteError(f"Reported scenario DDS input is invalid: {exc}") from exc
    if (
        original_info.dds_format != "BC7_UNORM"
        or int(original_info.width) != 2048
        or int(original_info.height) != 2048
        or int(original_info.mip_count) != 12
    ):
        raise HarnessPrerequisiteError(
            "The reported scenario authority DDS must be BC7_UNORM, 2048x2048, with 12 mips."
        )

    archive_index = build_replace_assistant_archive_index((), original_dds_root=root / "originals")
    self_match = match_replace_assistant_original(original_path, archive_index)
    _check(
        self_match.original_dds_path is None and self_match.archive_entry is None,
        "Texture Replacer self-match rejection regressed.",
    )

    items = build_replace_assistant_items((edited_path,), archive_index=archive_index)
    _check(len(items) == 1, "Texture Replacer did not produce exactly one build item.")
    item = items[0]
    _check(item.status == "matched", f"Edited DDS did not match its distinct authority: {item.status_detail}")
    _check(item.matched_original is not None, "Edited DDS match omitted authority metadata.")
    _check(
        item.matched_original is not None
        and item.matched_original.original_dds_path == original_path.resolve(),
        "Edited DDS matched the wrong local authority.",
    )
    _check(item.detected_package_root == virtual_path.parts[0], "Detected package root is incorrect.")
    _check(
        item.detected_relative_path == PurePosixPath(*virtual_path.parts[1:]).as_posix(),
        "Detected package-relative route is incorrect.",
    )

    logs: list[str] = []
    summary = build_replace_assistant_package(
        items,
        _replace_build_options(root / "packages", title="Texture Replacer Headless Harness"),
        archive_entries=(),
        original_dds_root=root / "originals",
        on_log=logs.append,
    )
    _check(summary.built_items == 1, f"Expected one built item, got {summary.built_items}.")
    _check(summary.failed_items == 0, f"Texture Replacer reported {summary.failed_items} failure(s).")
    _check(summary.unresolved_items == 0, f"Texture Replacer reported {summary.unresolved_items} unresolved item(s).")
    _check(summary.output_root is not None, "Texture Replacer did not publish a package root.")
    routed_relative = Path(*virtual_path.parts[1:])
    output_dds = Path(summary.output_root) / routed_relative
    _check(output_dds.is_file(), f"Texture Replacer package route is missing: {output_dds}")
    output_info = parse_dds(output_dds)
    _check(output_info.dds_format == "BC7_UNORM", f"Rebuilt format is {output_info.dds_format}.")
    _check((output_info.width, output_info.height) == (2048, 2048), "Rebuilt dimensions are not 2048x2048.")
    _check(int(output_info.mip_count) == 12, f"Rebuilt mip count is {output_info.mip_count}.")
    _check(
        all("WinError 5" not in line and "Access is denied" not in line for line in logs),
        "Reported access-denied failure reappeared.",
    )

    context.add_artifact(original_path, "reported-authority-dds")
    context.add_artifact(edited_path, "reported-edited-dds")
    context.add_artifact(Path(summary.output_root), "reported-package-root")
    context.add_artifact(output_dds, "reported-package-dds")
    return {
        "virtual_path": virtual_path.as_posix(),
        "original_metadata": {
            "format": original_info.dds_format,
            "width": original_info.width,
            "height": original_info.height,
            "mip_count": original_info.mip_count,
        },
        "edited_metadata": {
            "format": edited_info.dds_format,
            "width": edited_info.width,
            "height": edited_info.height,
            "mip_count": edited_info.mip_count,
        },
        "summary": {
            "total": summary.total_items,
            "built": summary.built_items,
            "failed": summary.failed_items,
            "unresolved": summary.unresolved_items,
            "skipped": summary.skipped_items,
        },
        "package_root": str(summary.output_root),
        "package_dds": str(output_dds),
        "self_match_rejected": True,
        "logs": logs,
    }


def _scenario_policy_matrix(context: HarnessContext) -> dict[str, object]:
    root = context.scenario_root("policy-matrix")
    source_png = _make_fixture_png(root / "fixtures" / "gradient.png", 16, 16, "gradient")
    formats = (*SUPPORTED_DDS_FORMAT_CHOICES, "R16_UNORM")
    requests = tuple(
        texture_native.NativeTextureEncodeRequest(
            input_path=source_png,
            output_path=root / "formats" / f"{dds_format}.dds",
            dds_format=dds_format,
            width=16,
            height=16,
            mip_count=1,
        )
        for dds_format in formats
    )
    reports = texture_native.encode_dds_batch_with_directxtex(requests)
    format_results: list[dict[str, object]] = []
    for request in requests:
        output_key = str(request.output_path.resolve())
        report = reports.get(output_key)
        _check(report is not None, f"Format matrix did not encode {request.dds_format}.")
        info = inspect_dds_native_path(request.output_path)
        _check(info.format_name == request.dds_format, f"{request.dds_format} inspected as {info.format_name}.")
        _check((info.width, info.height, info.mip_count) == (16, 16, 1), f"{request.dds_format} metadata mismatch.")
        format_results.append(
            {
                "format": request.dds_format,
                "actual_format": info.format_name,
                "width": info.width,
                "height": info.height,
                "mip_count": info.mip_count,
            }
        )
        context.add_artifact(request.output_path, "policy-format-dds")

    linear_dds = root / "color" / "linear.dds"
    srgb_dds = root / "color" / "srgb.dds"
    ignored_dds = root / "color" / "ignore-srgb-metadata.dds"
    linear_report = _encode_required(source_png, linear_dds, dds_format="BC7_UNORM", mip_count=1)
    srgb_report = _encode_required(source_png, srgb_dds, dds_format="BC7_UNORM_SRGB", mip_count=1)
    ignored_report = _encode_required(
        source_png,
        ignored_dds,
        dds_format="BC7_UNORM",
        mip_count=1,
        source_color_policy="ignore_srgb_metadata",
    )
    _check(not inspect_dds_native_path(linear_dds).srgb, "Linear BC7 output was marked sRGB.")
    _check(inspect_dds_native_path(srgb_dds).srgb, "sRGB BC7 output lost its sRGB metadata.")
    _check(ignored_report.get("source_color_policy") == "ignore_srgb_metadata", "Source color policy was not applied.")
    linear_png = root / "color" / "linear.png"
    srgb_png = root / "color" / "srgb.png"
    _decode_required(linear_dds, linear_png)
    _decode_required(srgb_dds, srgb_png)
    linear_pixels = _rgba_pixels(linear_png).astype(np.int16)
    srgb_pixels = _rgba_pixels(srgb_png).astype(np.int16)
    mean_color_difference = float(np.abs(linear_pixels[..., :3] - srgb_pixels[..., :3]).mean())
    _check(mean_color_difference <= 8.0, f"Linear/sRGB decoded pixels diverged unexpectedly ({mean_color_difference:.3f}).")
    _check(np.array_equal(linear_pixels[..., 3], srgb_pixels[..., 3]), "Linear/sRGB alpha behavior diverged.")

    alpha_png = _make_fixture_png(root / "fixtures" / "checker-alpha.png", 64, 64, "checker-alpha")
    separate_dds = root / "alpha" / "separate.dds"
    coverage_dds = root / "alpha" / "coverage.dds"
    separate_report = _encode_required(
        alpha_png,
        separate_dds,
        dds_format="BC7_UNORM",
        mip_count=7,
        mip_alpha_policy="separate",
    )
    coverage_report = _encode_required(
        alpha_png,
        coverage_dds,
        dds_format="BC7_UNORM",
        mip_count=7,
        mip_alpha_policy="preserve_coverage",
        alpha_coverage_reference=0.5,
    )
    _check(separate_report.get("mip_alpha_policy") == "separate", "Separate-alpha policy was not reported.")
    _check(coverage_report.get("mip_alpha_policy") == "preserve_coverage", "Coverage policy was not reported.")
    separate_mip_png = root / "alpha" / "separate-mip3.png"
    _decode_required(separate_dds, separate_mip_png, requested_mip=3)
    separate_alpha = _rgba_pixels(separate_mip_png)[..., 3]
    _check(separate_alpha.min() < 16 and separate_alpha.max() >= 128, "Separate-alpha lower mip lost cutout range.")
    _check(len(np.unique(separate_alpha)) >= 2, "Separate-alpha lower mip collapsed to one alpha value.")

    coverage_rows: list[dict[str, object]] = []
    base_coverage: float | None = None
    for mip in range(4):
        output_png = root / "alpha" / f"coverage-mip{mip}.png"
        _decode_required(coverage_dds, output_png, requested_mip=mip)
        pixels = _rgba_pixels(output_png)
        coverage = float((pixels[..., 3] >= 128).mean())
        if base_coverage is None:
            base_coverage = coverage
        delta = abs(coverage - float(base_coverage))
        _check(
            delta <= 0.05 + 1e-9,
            f"Alpha coverage drifted by {delta * 100.0:.2f} percentage points at mip {mip}.",
        )
        coverage_rows.append(
            {
                "mip": mip,
                "width": int(pixels.shape[1]),
                "height": int(pixels.shape[0]),
                "coverage": coverage,
                "delta": delta,
            }
        )

    normal_png = _make_fixture_png(root / "fixtures" / "normal.png", 16, 16, "normal")
    normal_dds = root / "normal" / "bc5.dds"
    _encode_required(normal_png, normal_dds, dds_format="BC5_UNORM", mip_count=5)
    normal_preview = root / "normal" / "bc5-preview.png"
    normal_report = _decode_required(
        normal_dds,
        normal_preview,
        slot_kind="normal",
        normal_space="auto",
    )
    normal_pixels = _rgba_pixels(normal_preview)
    _check(bool(normal_report.get("normal_green_inverted")), "BC5 normal-space handling was not applied.")
    _check(float(normal_pixels[..., 1].mean()) > 128.0, "BC5 normal green channel was not inverted for preview.")

    mip_png = _make_fixture_png(root / "fixtures" / "mips.png", 16, 8, "gradient")
    mip_expectations = {"single": (1, 1), "explicit": (3, 3), "full": (0, 5)}
    mip_results: dict[str, int] = {}
    for label, (requested, expected) in mip_expectations.items():
        output_dds = root / "mips" / f"{label}.dds"
        _encode_required(mip_png, output_dds, dds_format="BC3_UNORM", mip_count=requested)
        actual = int(inspect_dds_native_path(output_dds).mip_count)
        _check(actual == expected, f"{label} mip mode produced {actual}, expected {expected}.")
        mip_results[label] = actual

    overwrite_output = root / "overwrite" / "existing.dds"
    overwrite_output.parent.mkdir(parents=True, exist_ok=True)
    overwrite_output.write_bytes(b"existing-output-must-survive")
    overwrite_before = overwrite_output.read_bytes()
    overwrite_report = texture_native.encode_dds_with_directxtex(
        source_png,
        overwrite_output,
        dds_format="BC7_UNORM",
        mip_count=1,
        overwrite=False,
    )
    _check(overwrite_report is None, "overwrite=false unexpectedly replaced an existing output.")
    _check(overwrite_output.read_bytes() == overwrite_before, "overwrite=false changed the existing destination.")

    gray_png = _make_fixture_png(root / "fixtures" / "gray.png", 16, 16, "gray")
    gray_dds = root / "gray16" / "r16.dds"
    gray_preview = root / "gray16" / "r16.png"
    _encode_required(gray_png, gray_dds, dds_format="R16_UNORM", mip_count=1)
    gray_report = _decode_required(gray_dds, gray_preview, output_pixel_type="gray16")
    width, height, bit_depth, color_type = read_png_header_info(gray_preview)
    _check((width, height, bit_depth, color_type) == (16, 16, 16, 0), "R16 staging did not produce true gray16 PNG.")
    with Image.open(gray_preview) as gray_image:
        gray_extrema = gray_image.getextrema()
    gray_min, gray_max = int(gray_extrema[0]), int(gray_extrema[1])
    _check(gray_max - gray_min > 255, "Gray16 output silently collapsed to 8-bit range.")
    _check(gray_report.get("output_pixel_type") == "gray16", "Gray16 decode report lost output pixel type.")

    alpha_mode_values = {
        "unknown": 0,
        "straight": 1,
        "premultiplied": 2,
        "opaque": 3,
        "custom": 4,
    }
    alpha_mode_results: dict[str, int] = {}
    for mode, expected_value in alpha_mode_values.items():
        output_dds = root / "alpha-metadata" / f"{mode}.dds"
        report = _encode_required(
            alpha_png,
            output_dds,
            dds_format="BC7_UNORM",
            mip_count=1,
            dds_alpha_mode=mode,
        )
        actual_value = _dds_alpha_mode_value(output_dds)
        _check(actual_value == expected_value, f"DDS alpha metadata {mode} encoded as {actual_value}.")
        _check(report.get("dds_alpha_mode") == mode, f"DDS alpha report lost {mode} mode.")
        alpha_mode_results[mode] = actual_value

    for path, kind in (
        (source_png, "policy-source-png"),
        (linear_dds, "policy-linear-dds"),
        (srgb_dds, "policy-srgb-dds"),
        (ignored_dds, "policy-ignore-srgb-dds"),
        (separate_dds, "policy-separate-alpha-dds"),
        (coverage_dds, "policy-coverage-dds"),
        (normal_dds, "policy-normal-dds"),
        (gray_dds, "policy-gray16-dds"),
        (gray_preview, "policy-gray16-png"),
    ):
        context.add_artifact(path, kind)
    return {
        "format_results": format_results,
        "linear_report": linear_report,
        "srgb_report": srgb_report,
        "ignore_srgb_report": ignored_report,
        "linear_srgb_mean_pixel_difference": mean_color_difference,
        "separate_alpha_unique_values": int(len(np.unique(separate_alpha))),
        "coverage_results": coverage_rows,
        "normal_report": normal_report,
        "mip_results": mip_results,
        "overwrite_preserved": True,
        "gray16": {
            "bit_depth": bit_depth,
            "color_type": color_type,
            "minimum": gray_min,
            "maximum": gray_max,
        },
        "alpha_metadata": alpha_mode_results,
    }


def _scenario_consumer_matrix(context: HarnessContext) -> dict[str, object]:
    root = context.scenario_root("consumer-matrix")
    owners: dict[str, object] = {}

    workflow_rel = Path("0009/character/texture/harness_consumer_basecolor.dds")
    workflow_original = root / "workflow" / "originals" / workflow_rel
    workflow_source_png = _make_fixture_png(root / "workflow" / "source.png", 16, 16, "gradient")
    _encode_required(
        workflow_source_png,
        workflow_original,
        dds_format="BC7_UNORM",
        width=16,
        height=16,
        mip_count=5,
    )
    workflow_config = AppConfig(
        original_dds_root=str(root / "workflow" / "originals"),
        png_root=str(root / "workflow" / "png"),
        texture_editor_png_root="",
        output_root=str(root / "workflow" / "output"),
        dds_staging_root=str(root / "workflow" / "staging"),
        dds_format_mode="match_original",
        dds_size_mode="original",
        dds_mip_mode="match_original",
        enable_dds_staging=True,
        enable_incremental_resume=False,
        overwrite_existing_dds=True,
        include_filters="*.dds",
        upscale_backend="none",
        enable_mod_ready_loose_export=False,
    )
    workflow_logs: list[str] = []
    workflow_summary = rebuild_dds_files(workflow_config, on_log=workflow_logs.append)
    workflow_output = root / "workflow" / "output" / workflow_rel
    workflow_staged_png = root / "workflow" / "staging" / workflow_rel.with_suffix(".png")
    _check(workflow_summary.converted == 1 and workflow_summary.failed == 0, "Texture Workflow native rebuild failed.")
    _check(workflow_output.is_file(), "Texture Workflow output DDS is missing.")
    _check(workflow_staged_png.is_file(), "Texture Workflow native DDS staging PNG is missing.")
    owners["texture_workflow"] = {
        "converted": workflow_summary.converted,
        "failed": workflow_summary.failed,
        "staged_png": str(workflow_staged_png),
        "output_dds": str(workflow_output),
    }

    replacer_virtual = PurePosixPath("0009/character/texture/harness_replacer_basecolor.dds")
    replacer_original = root.joinpath("replacer", "originals", *replacer_virtual.parts)
    replacer_edited = root.joinpath("replacer", "edits", *replacer_virtual.parts)
    replacer_original_png = _make_fixture_png(root / "replacer" / "original.png", 16, 16, "solid-red")
    replacer_edited_png = _make_fixture_png(root / "replacer" / "edited.png", 16, 16, "solid-blue")
    _encode_required(replacer_original_png, replacer_original, dds_format="BC7_UNORM", mip_count=5)
    _encode_required(replacer_edited_png, replacer_edited, dds_format="R8G8B8A8_UNORM", mip_count=1)
    replacer_index = build_replace_assistant_archive_index(
        (),
        original_dds_root=root / "replacer" / "originals",
    )
    replacer_items = build_replace_assistant_items((replacer_edited,), archive_index=replacer_index)
    replacer_summary = build_replace_assistant_package(
        replacer_items,
        _replace_build_options(root / "replacer" / "packages", title="Harness Consumer Replacer"),
        original_dds_root=root / "replacer" / "originals",
    )
    _check(
        replacer_summary.built_items == 1
        and replacer_summary.failed_items == 0
        and replacer_summary.unresolved_items == 0,
        "Texture Replacer consumer path failed.",
    )
    replacer_output = Path(replacer_summary.output_root or "") / Path(*replacer_virtual.parts[1:])
    _check(replacer_output.is_file(), "Texture Replacer consumer package output is missing.")
    owners["texture_replacer"] = {
        "built": replacer_summary.built_items,
        "failed": replacer_summary.failed_items,
        "output_dds": str(replacer_output),
    }

    editor_import_png = normalize_texture_editor_source_to_png(
        workflow_output,
        output_dir=root / "texture-editor" / "import",
        output_stem="imported",
    )
    editor_pixels = _rgba_pixels(editor_import_png)
    editor_document = TextureEditorDocument(
        "headless_consumer",
        int(editor_pixels.shape[1]),
        int(editor_pixels.shape[0]),
        active_layer_id="base",
        layers=(TextureEditorLayer("base", "Base", ""),),
    )
    editor_result = TextureEditorNativeDdsService().preview_compressed(
        editor_document,
        {"base": editor_pixels},
        TextureEditorNativeDdsOptions(
            output_path=root / "texture-editor" / "export.dds",
            preview_output_path=root / "texture-editor" / "export-preview.png",
            temp_root=root / "texture-editor" / "temp",
        ),
    )
    _check(editor_result.dds_path.is_file(), "Texture Editor native export is missing.")
    _check(editor_result.preview_path is not None and editor_result.preview_path.is_file(), "Texture Editor preview is missing.")
    owners["texture_editor"] = {
        "import_png": str(editor_import_png),
        "export_dds": str(editor_result.dds_path),
        "preview_png": str(editor_result.preview_path),
        "format": editor_result.report.get("format"),
    }

    display_preview = ensure_dds_display_preview_png(workflow_output, max_dimension=8)
    display_pixels = _rgba_pixels(display_preview)
    _check(max(display_pixels.shape[:2]) <= 8, "Display preview max-dimension policy was not applied.")
    owners["preview_and_staging"] = {
        "display_preview": str(display_preview),
        "display_dimensions": [int(display_pixels.shape[1]), int(display_pixels.shape[0])],
        "staged_png": str(workflow_staged_png),
    }

    normal_png = _make_fixture_png(root / "recolor" / "normal.png", 16, 16, "normal")
    normal_dds = root / "recolor" / "normal.dds"
    _encode_required(normal_png, normal_dds, dds_format="BC5_UNORM", mip_count=5)
    recolor_package = _write_recolor_package(root / "recolor", workflow_output, normal_dds)
    recolor_analysis = analyze_recolor_variant_package(recolor_package)
    recolor_target = next(
        (
            target
            for target in recolor_analysis.targets
            if target.target_kind == "texture_slot" and target.game_path.endswith("blade_basecolor.dds")
        ),
        None,
    )
    _check(recolor_target is not None and recolor_target.editable, "Recolor analysis did not expose the base-color target.")
    recolor_preview = preview_recolor_variant_target_image(
        recolor_analysis,
        default_recolor_variant_templates()[0],
        recolor_target.target_id if recolor_target is not None else "",
        max_dimension=16,
    )
    _check(recolor_preview.source_png.is_file() and recolor_preview.preview_png.is_file(), "Recolor preview failed.")
    owners["recolor"] = {
        "package": str(recolor_package),
        "target_id": recolor_preview.target_id,
        "source_png": str(recolor_preview.source_png),
        "preview_png": str(recolor_preview.preview_png),
    }

    icon_png = _make_fixture_png(root / "item-icon" / "source.png", 24, 24, "icon")
    icon_result = build_item_icon_payload(
        ItemIconOverrideSpec(
            source_path=icon_png,
            target_entry=object(),
            target_path="ui/itemicon/harness_item_icon.dds",
            source_mode="file",
        ),
        target_template_path=workflow_output,
    )
    icon_dds = root / "item-icon" / "output.dds"
    icon_dds.write_bytes(icon_result.payload_data)
    icon_info = parse_dds(icon_dds)
    _check(icon_info.dds_format == "BC7_UNORM" and icon_info.mip_count == 5, "Item icon DDS contract changed.")
    owners["item_icon"] = {
        "output_dds": str(icon_dds),
        "format": icon_info.dds_format,
        "mip_count": icon_info.mip_count,
    }

    material_source_png = _make_fixture_png(root / "material" / "source.png", 16, 16, "solid-blue")
    material_entry = _archive_entry(root / "material" / "archive", "character/texture/harness_material.dds")
    material_report = TextureReplacementReport()
    material_payload = _build_texture_payload(
        ReplacementTextureSlot("Harness", "base", material_source_png),
        target_entry=material_entry,
        read_original_texture_bytes=lambda _entry: workflow_output.read_bytes(),
        original_texture_source_path=lambda _entry: workflow_output,
        report=material_report,
        on_log=None,
    )
    material_dds = root / "material" / "output.dds"
    material_dds.write_bytes(material_payload)
    material_info = parse_dds(material_dds)
    _check(material_info.dds_format == "BC7_UNORM", "Static/material replacement did not preserve authority format.")
    owners["static_material_replacement"] = {
        "output_dds": str(material_dds),
        "format": material_info.dds_format,
        "warnings": list(material_report.warnings),
    }

    direct_archive_payload = build_archive_texture_payload_from_dds(material_entry, material_dds)
    direct_archive_dds = root / "archive-payload" / "direct.dds"
    direct_archive_dds.parent.mkdir(parents=True, exist_ok=True)
    direct_archive_dds.write_bytes(direct_archive_payload)
    with patch(
        "cdmw.core.archive_media_preview.ensure_archive_preview_source",
        return_value=(workflow_output, "headless authority"),
    ):
        png_archive_payload = build_archive_texture_payload_from_png(material_entry, material_source_png)
    png_archive_dds = root / "archive-payload" / "from-png.dds"
    png_archive_dds.write_bytes(png_archive_payload)
    _check(parse_dds(png_archive_dds).dds_format == "BC7_UNORM", "Archive PNG payload lost authority format.")
    owners["archive_payload_preparation"] = {
        "direct_dds": str(direct_archive_dds),
        "from_png_dds": str(png_archive_dds),
        "archive_mutation_calls": 0,
    }

    for path, kind in (
        (workflow_original, "consumer-workflow-original-dds"),
        (workflow_staged_png, "consumer-workflow-staged-png"),
        (workflow_output, "consumer-workflow-output-dds"),
        (replacer_output, "consumer-replacer-output-dds"),
        (editor_import_png, "consumer-editor-import-png"),
        (editor_result.dds_path, "consumer-editor-output-dds"),
        (Path(editor_result.preview_path or ""), "consumer-editor-preview-png"),
        (display_preview, "consumer-display-preview-png"),
        (recolor_preview.source_png, "consumer-recolor-source-png"),
        (recolor_preview.preview_png, "consumer-recolor-preview-png"),
        (icon_dds, "consumer-item-icon-dds"),
        (material_dds, "consumer-material-dds"),
        (direct_archive_dds, "consumer-archive-direct-dds"),
        (png_archive_dds, "consumer-archive-png-dds"),
    ):
        if str(path):
            context.add_artifact(path, kind)
    return {
        "owners": owners,
        "workflow_logs": workflow_logs,
        "archive_mutation_reached": False,
    }


def _scenario_failure_lifecycle(context: HarnessContext) -> dict[str, object]:
    root = context.scenario_root("failure-lifecycle")
    source_png = _make_fixture_png(root / "fixtures" / "valid.png", 16, 16, "solid-red")
    checks: dict[str, object] = {}

    missing_output = root / "missing-helper.dds"
    command_count = len(context.recorder.commands)
    with patch.object(texture_native, "find_directxtex_texture_binary", return_value=None):
        missing_report = texture_native.encode_dds_with_directxtex(
            source_png,
            missing_output,
            dds_format="BC7_UNORM",
            mip_count=1,
        )
    _check(missing_report is None and not missing_output.exists(), "Missing-helper failure produced an output.")
    _check(len(context.recorder.commands) == command_count, "Missing-helper failure launched a subprocess.")
    checks["missing_helper"] = True

    malformed_png = root / "fixtures" / "malformed.png"
    malformed_png.write_bytes(b"not a PNG")
    malformed_output = root / "malformed.dds"
    command_count = len(context.recorder.commands)
    malformed_report = texture_native.encode_dds_with_directxtex(
        malformed_png,
        malformed_output,
        dds_format="BC7_UNORM",
        mip_count=1,
    )
    _check(malformed_report is None and not malformed_output.exists(), "Malformed PNG produced a DDS.")
    _check(len(context.recorder.commands) == command_count, "Malformed PNG launched the native helper.")
    checks["malformed_input"] = True

    unsupported_output = root / "unsupported.dds"
    unsupported_report = texture_native.encode_dds_with_directxtex(
        source_png,
        unsupported_output,
        dds_format="UNSUPPORTED_FORMAT",
        mip_count=1,
    )
    _check(unsupported_report is None and not unsupported_output.exists(), "Unsupported native job produced an output.")
    checks["unsupported_job"] = True

    good_output = root / "batch-good.dds"
    bad_output = root / "batch-bad.dds"
    mixed_results = texture_native.encode_dds_batch_with_directxtex(
        (
            texture_native.NativeTextureEncodeRequest(
                input_path=source_png,
                output_path=good_output,
                dds_format="BC3_UNORM",
                mip_count=5,
            ),
            texture_native.NativeTextureEncodeRequest(
                input_path=source_png,
                output_path=bad_output,
                dds_format="UNSUPPORTED_FORMAT",
                mip_count=1,
            ),
        )
    )
    _check(str(good_output.resolve()) in mixed_results and good_output.is_file(), "Per-item success was not published.")
    _check(str(bad_output.resolve()) not in mixed_results and not bad_output.exists(), "Per-item failure was published.")
    checks["per_item_failure"] = True

    rollback_output = root / "atomic-rollback.dds"
    rollback_bytes = b"existing-destination-remains-unchanged"
    rollback_output.write_bytes(rollback_bytes)
    rollback_report = texture_native.encode_dds_with_directxtex(
        source_png,
        rollback_output,
        dds_format="UNSUPPORTED_FORMAT",
        mip_count=1,
        overwrite=True,
    )
    _check(rollback_report is None, "Atomic rollback failure unexpectedly succeeded.")
    _check(rollback_output.read_bytes() == rollback_bytes, "Atomic rollback changed the existing destination.")
    checks["atomic_rollback"] = True

    timeout_output = root / "timeout.dds"
    timeout_output.write_bytes(b"timeout-destination")
    timeout_before = timeout_output.read_bytes()

    def timeout_runner(command: Sequence[str], *_args: object, **_kwargs: object) -> tuple[int, str, str]:
        context.recorder.record_injected(command, failure="timeout")
        raise ProcessTimeoutExpired(command, 0.01)

    with patch.object(texture_native, "run_process_with_cancellation", side_effect=timeout_runner):
        timeout_report = texture_native.encode_dds_with_directxtex(
            source_png,
            timeout_output,
            dds_format="BC7_UNORM",
            mip_count=1,
            overwrite=True,
        )
    _check(timeout_report is None, "Injected timeout unexpectedly succeeded.")
    _check(timeout_output.read_bytes() == timeout_before, "Timeout changed the existing destination.")
    checks["timeout"] = True

    cancelled_output = root / "cancelled.dds"
    stop_event = threading.Event()
    stop_event.set()
    try:
        texture_native.encode_dds_with_directxtex(
            source_png,
            cancelled_output,
            dds_format="BC7_UNORM",
            mip_count=1,
            stop_event=stop_event,
        )
    except RunCancelled:
        cancelled = True
    else:
        cancelled = False
    _check(cancelled and not cancelled_output.exists(), "Pre-cancelled encode was not cancelled cleanly.")
    checks["cancellation"] = True

    stale_source = root / "stale" / "source.dds"
    stale_red_png = _make_fixture_png(root / "stale" / "red.png", 16, 16, "solid-red")
    stale_blue_png = _make_fixture_png(root / "stale" / "blue.png", 16, 16, "solid-blue")
    _encode_required(stale_red_png, stale_source, dds_format="BC7_UNORM", mip_count=1)
    first_preview = texture_native.ensure_native_dds_preview_png(stale_source, max_dimension=16)
    _check(first_preview is not None and first_preview.is_file(), "Initial stale-result preview failed.")
    first_pixels = _rgba_pixels(Path(first_preview))
    replacement_dds = root / "stale" / "replacement.dds"
    _encode_required(stale_blue_png, replacement_dds, dds_format="BC7_UNORM", mip_count=1)
    old_mtime_ns = stale_source.stat().st_mtime_ns
    os.replace(replacement_dds, stale_source)
    os.utime(stale_source, ns=(old_mtime_ns + 2_000_000_000, old_mtime_ns + 2_000_000_000))
    second_preview = texture_native.ensure_native_dds_preview_png(stale_source, max_dimension=16)
    _check(second_preview is not None and second_preview.is_file(), "Updated stale-result preview failed.")
    second_pixels = _rgba_pixels(Path(second_preview))
    _check(Path(first_preview) != Path(second_preview), "Changed source reused a stale preview cache path.")
    _check(
        float(np.abs(first_pixels.astype(np.int16) - second_pixels.astype(np.int16)).mean()) > 20.0,
        "Changed source reused stale preview pixels.",
    )
    checks["stale_results"] = True

    child_pid_path = root / "process-tree-child.pid"
    process_tree_script = root / "process-tree-probe.py"
    process_tree_script.write_text(
        "\n".join(
            (
                "import pathlib",
                "import subprocess",
                "import sys",
                "import time",
                "pid_path = pathlib.Path(sys.argv[1])",
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])",
                "pid_path.write_text(str(child.pid), encoding='utf-8')",
                "time.sleep(60)",
            )
        ),
        encoding="utf-8",
    )
    try:
        context.recorder(
            [sys.executable, str(process_tree_script), str(child_pid_path)],
            timeout_seconds=2.0,
        )
    except ProcessTimeoutExpired:
        process_timed_out = True
    else:
        process_timed_out = False
    _check(process_timed_out, "Process-tree timeout probe did not time out.")
    _check(child_pid_path.is_file(), "Process-tree timeout probe did not publish its child PID.")
    child_pid = int(child_pid_path.read_text(encoding="utf-8").strip())
    deadline = time.monotonic() + 5.0
    while _pid_is_running(child_pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    _check(not _pid_is_running(child_pid), f"Timed-out subprocess child {child_pid} survived termination.")
    checks["process_tree_termination"] = True

    leaked_staging_files = [
        path
        for path in context.output_root.rglob("*.dds")
        if path.name.startswith(".") and ".cdmw-" in path.name
    ]
    leaked_job_dirs = [
        path
        for path in context.temp_root.rglob("*")
        if path.is_dir() and path.name.startswith(("cdmw_directxtex_encode_", "cdmw_replace_stage_", "cdmw_replace_work_"))
    ]
    _check(not leaked_staging_files, f"Native staging DDS files leaked: {leaked_staging_files[:3]}")
    _check(not leaked_job_dirs, f"Native temporary job directories leaked: {leaked_job_dirs[:3]}")
    checks["temporary_cleanup"] = True

    context.add_artifact(good_output, "failure-lifecycle-good-dds")
    context.add_artifact(rollback_output, "failure-lifecycle-rollback-sentinel")
    context.add_artifact(Path(first_preview), "failure-lifecycle-first-preview")
    context.add_artifact(Path(second_preview), "failure-lifecycle-second-preview")
    context.add_artifact(process_tree_script, "failure-lifecycle-process-tree-script")
    return {
        "checks": checks,
        "child_pid": child_pid,
        "leaked_staging_files": [],
        "leaked_job_directories": [],
    }


SCENARIO_FUNCTIONS: Mapping[str, Callable[[HarnessContext], dict[str, object]]] = {
    "reported-bc7-rebuild": _scenario_reported_bc7_rebuild,
    "policy-matrix": _scenario_policy_matrix,
    "consumer-matrix": _scenario_consumer_matrix,
    "failure-lifecycle": _scenario_failure_lifecycle,
}


def _run_scenario(name: str, context: HarnessContext) -> dict[str, object]:
    command_start = len(context.recorder.commands)
    artifact_start = len(context.artifacts)
    metadata_start = len(context.dds_metadata)
    started = time.monotonic()
    started_utc = _utc_now()
    try:
        details = SCENARIO_FUNCTIONS[name](context)
        _assert_headless_imports()
    except HarnessPrerequisiteError:
        raise
    except BaseException as exc:
        return {
            "name": name,
            "passed": False,
            "started_utc": started_utc,
            "elapsed_seconds": time.monotonic() - started,
            "command_indexes": list(range(command_start, len(context.recorder.commands))),
            "artifact_indexes": list(range(artifact_start, len(context.artifacts))),
            "dds_metadata_indexes": list(range(metadata_start, len(context.dds_metadata))),
            "failure": {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        }
    return {
        "name": name,
        "passed": True,
        "started_utc": started_utc,
        "elapsed_seconds": time.monotonic() - started,
        "command_indexes": list(range(command_start, len(context.recorder.commands))),
        "artifact_indexes": list(range(artifact_start, len(context.artifacts))),
        "dds_metadata_indexes": list(range(metadata_start, len(context.dds_metadata))),
        "details": details,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the production Texture Replacer and native DDS backend without starting CDMW."
    )
    parser.add_argument("--scenario", choices=SCENARIO_NAMES, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-binary", type=Path)
    parser.add_argument("--edited-dds", type=Path)
    parser.add_argument("--original-dds", type=Path)
    parser.add_argument("--virtual-path", default=DEFAULT_VIRTUAL_PATH)
    return parser.parse_args(argv)


def _validate_input_file(path: Path | None, label: str) -> Path | None:
    if path is None:
        return None
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise HarnessPrerequisiteError(f"{label} does not exist or is not a file: {resolved}")
    return resolved


def _write_result(output_root: Path, result: Mapping[str, object]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    result_path = output_root / "result.json"
    staged_path = output_root / f".result-{uuid4().hex}.json"
    staged_path.write_text(json.dumps(dict(result), indent=2, sort_keys=True), encoding="utf-8")
    os.replace(staged_path, result_path)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    output_root = args.output.expanduser().resolve()
    started_utc = _utc_now()
    started = time.monotonic()
    result: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "selected_scenario": args.scenario,
        "started_utc": started_utc,
        "passed": False,
        "exit_code": 2,
        "scenario_results": [],
        "commands": [],
        "artifacts": [],
        "dds_metadata": [],
        "external_inputs": {},
        "failures": [],
    }
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        run_root = output_root / f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{os.getpid()}"
        run_root.mkdir(parents=True, exist_ok=False)
        temp_root = output_root / f"t-{os.getpid()}"
        temp_root.mkdir(parents=True, exist_ok=True)
        os.environ["TEMP"] = str(temp_root)
        os.environ["TMP"] = str(temp_root)
        os.environ["TMPDIR"] = str(temp_root)
        os.environ["CDMW_TEMP_CACHE_ROOT"] = str(temp_root)
        tempfile.tempdir = str(temp_root)

        native_binary = (
            args.native_binary.expanduser().resolve()
            if args.native_binary is not None
            else texture_native.default_directxtex_texture_binary_path(release=True).resolve()
        )
        if not native_binary.is_file():
            raise HarnessPrerequisiteError(f"Native texture helper is missing: {native_binary}")
        if native_binary.name.casefold() not in NATIVE_TEXTURE_EXECUTABLES:
            raise HarnessPrerequisiteError(
                f"Native texture helper must be named cd-texture-dx.exe, got {native_binary.name}."
            )
        args.native_binary = native_binary
        args.edited_dds = _validate_input_file(args.edited_dds, "Edited DDS")
        args.original_dds = _validate_input_file(args.original_dds, "Original DDS")
        _normalize_virtual_path(args.virtual_path)
        os.environ["CDMW_DIRECTXTEX_TEXTURE_BIN"] = str(native_binary)

        external_before: dict[str, dict[str, object]] = {}
        if args.edited_dds is not None:
            external_before["edited_dds"] = _fingerprint(args.edited_dds)
        if args.original_dds is not None:
            external_before["original_dds"] = _fingerprint(args.original_dds)
        result["external_inputs"] = {
            key: {"before": value}
            for key, value in external_before.items()
        }

        recorder = RecordingProcessDelegate(run_process_with_cancellation_real)
        self_test_code, self_test_stdout, self_test_stderr = recorder(
            [str(native_binary), "self-test"],
            timeout_seconds=3600.0,
        )
        if self_test_code != 0:
            raise HarnessPrerequisiteError(
                f"Native texture helper self-test failed with exit {self_test_code}: {self_test_stderr[-1000:]}"
            )
        try:
            self_test = json.loads(self_test_stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise HarnessPrerequisiteError("Native texture helper self-test did not return valid JSON.") from exc
        if not isinstance(self_test, dict) or not bool(self_test.get("ok")):
            raise HarnessPrerequisiteError(f"Native texture helper self-test did not pass: {self_test!r}")

        result["helper"] = {
            "path": str(native_binary),
            "name": native_binary.name,
            "size": native_binary.stat().st_size,
            "sha256": _sha256_file(native_binary),
            "backend_identity": texture_native.native_texture_backend_identity(binary=native_binary),
            "self_test": self_test,
        }
        result["run_root"] = str(run_root)
        context = HarnessContext(
            output_root=output_root,
            run_root=run_root,
            temp_root=temp_root,
            native_binary=native_binary,
            recorder=recorder,
            args=args,
        )
        _assert_headless_imports()

        selected = tuple(SCENARIO_FUNCTIONS) if args.scenario == "full-suite" else (args.scenario,)
        with patch.object(texture_native, "run_process_with_cancellation", side_effect=recorder):
            scenario_results = [_run_scenario(name, context) for name in selected]

        for key, before in external_before.items():
            source_path = Path(str(before["path"]))
            after = _fingerprint(source_path)
            unchanged = (
                before["size"] == after["size"]
                and before["mtime_ns"] == after["mtime_ns"]
                and before["sha256"] == after["sha256"]
            )
            result["external_inputs"][key]["after"] = after  # type: ignore[index]
            result["external_inputs"][key]["unchanged"] = unchanged  # type: ignore[index]
            if not unchanged:
                scenario_results.append(
                    {
                        "name": f"external-input-{key}",
                        "passed": False,
                        "elapsed_seconds": 0.0,
                        "failure": {
                            "type": "ScenarioFailure",
                            "message": f"External input changed during harness run: {source_path}",
                        },
                    }
                )

        passed = all(bool(item.get("passed")) for item in scenario_results)
        result.update(
            {
                "scenario_results": scenario_results,
                "commands": recorder.commands,
                "artifacts": context.artifacts,
                "dds_metadata": context.dds_metadata,
                "passed": passed,
                "exit_code": 0 if passed else 1,
            }
        )
        if args.scenario == "full-suite":
            result["full_suite"] = {
                "passed": passed,
                "scenario_count": len(selected),
                "passed_count": sum(1 for item in scenario_results if bool(item.get("passed"))),
                "failed_count": sum(1 for item in scenario_results if not bool(item.get("passed"))),
            }
        return_code = 0 if passed else 1
    except HarnessPrerequisiteError as exc:
        result["failures"] = [{"type": type(exc).__name__, "message": str(exc)}]
        result["exit_code"] = 2
        return_code = 2
    except BaseException as exc:
        result["failures"] = [
            {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
        ]
        result["exit_code"] = 1
        return_code = 1
    finally:
        result["completed_utc"] = _utc_now()
        result["elapsed_seconds"] = time.monotonic() - started
        try:
            _write_result(output_root, result)
        except Exception as exc:
            print(f"Failed to write harness result.json: {exc}", file=sys.stderr)
            return_code = 2
    print(json.dumps({"passed": bool(result.get("passed")), "exit_code": return_code, "result": str(output_root / "result.json")}))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
