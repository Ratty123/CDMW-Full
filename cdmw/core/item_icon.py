from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Optional, Sequence

from PIL import Image

from cdmw.core.common import run_process_with_cancellation
from cdmw.core.pipeline import (
    build_texconv_command,
    ensure_dds_display_preview_png,
    max_mips_for_size,
    parse_dds,
)
from cdmw.core.texture_native import encode_dds_with_directxtex


ITEM_ICON_SOURCE_EXTENSIONS = {
    ".bmp",
    ".dds",
    ".jpeg",
    ".jpg",
    ".png",
    ".tga",
    ".tif",
    ".tiff",
    ".webp",
}


@dataclass(frozen=True, slots=True)
class ItemIconSourceCandidate:
    path: Path
    score: int
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ItemIconOverrideSpec:
    source_path: Path
    target_entry: object
    target_path: str
    source_mode: str
    fit_mode: str = "fit_pad"


@dataclass(frozen=True, slots=True)
class ItemIconBuildResult:
    payload_data: bytes
    target_path: str
    source_path: Path
    source_width: int
    source_height: int
    target_width: int
    target_height: int
    target_format: str
    target_mip_count: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ItemIconLibraryRecord:
    path: Path
    root_path: Path
    relative_path: str
    file_size: int
    mtime_ns: int
    width: int = 0
    height: int = 0
    tags: tuple[str, ...] = ()
    notes: str = ""
    favorite: bool = False
    source_kind: str = "folder"
    warning: str = ""


@dataclass(frozen=True, slots=True)
class ItemIconTemplateInfo:
    width: int
    height: int
    target_format: str
    mip_count: int
    suffix: str


def _icon_match_stem(value: object) -> str:
    stem = PurePosixPath(str(value or "").replace("\\", "/")).stem.casefold().strip()
    for prefix in ("itemicon_prefab_", "itemicon_", "icon_prefab_", "icon_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :].strip("_")
            break
    return stem


def _tokens(value: object) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", str(value or "").casefold()) if len(token) >= 2}


def _candidate_score(
    path: Path,
    *,
    target_path: str,
    related_stems: Sequence[str] = (),
    display_name: str = "",
) -> ItemIconSourceCandidate:
    candidate_stem = _icon_match_stem(path.name)
    target_stem = _icon_match_stem(target_path)
    related = tuple(dict.fromkeys(_icon_match_stem(stem) for stem in related_stems if _icon_match_stem(stem)))
    reasons: list[str] = []
    score = 0

    if candidate_stem and target_stem and candidate_stem == target_stem:
        score += 240
        reasons.append("exact target icon stem")
    elif candidate_stem and target_stem and (candidate_stem in target_stem or target_stem in candidate_stem):
        score += 150
        reasons.append("target icon stem contains match")

    for related_stem in related:
        if candidate_stem == related_stem:
            score += 210
            reasons.append("exact related model stem")
            break
        if candidate_stem and related_stem and (candidate_stem in related_stem or related_stem in candidate_stem):
            score += 120
            reasons.append("related model stem contains match")
            break

    target_tokens = _tokens(target_stem) | set().union(*(_tokens(stem) for stem in related)) | _tokens(display_name)
    candidate_tokens = _tokens(candidate_stem)
    overlap = candidate_tokens & target_tokens
    if overlap:
        score += min(90, len(overlap) * 18)
        reasons.append("token overlap: " + ", ".join(sorted(overlap)[:5]))
    if any(token in candidate_tokens for token in {"icon", "itemicon", "inventory", "ui"}):
        score += 20
        reasons.append("icon filename hint")

    return ItemIconSourceCandidate(path=path, score=score, reason="; ".join(reasons) or "weak filename match")


def find_item_icon_source_candidates(
    source: Path,
    *,
    target_path: str,
    related_stems: Sequence[str] = (),
    display_name: str = "",
    min_score: int = 80,
) -> tuple[ItemIconSourceCandidate, ...]:
    resolved = source.expanduser()
    if resolved.is_file():
        if resolved.suffix.lower() not in ITEM_ICON_SOURCE_EXTENSIONS:
            return ()
        return (ItemIconSourceCandidate(path=resolved, score=1000, reason="explicit source file"),)
    if not resolved.is_dir():
        return ()

    candidates: list[ItemIconSourceCandidate] = []
    for path in resolved.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in ITEM_ICON_SOURCE_EXTENSIONS:
            continue
        candidate = _candidate_score(path, target_path=target_path, related_stems=related_stems, display_name=display_name)
        if candidate.score >= min_score:
            candidates.append(candidate)
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.path.as_posix().casefold()))
    return tuple(candidates)


def choose_item_icon_source(
    source: Path,
    *,
    target_path: str,
    related_stems: Sequence[str] = (),
    display_name: str = "",
    min_score: int = 80,
) -> tuple[Optional[ItemIconSourceCandidate], tuple[ItemIconSourceCandidate, ...], str]:
    candidates = find_item_icon_source_candidates(
        source,
        target_path=target_path,
        related_stems=related_stems,
        display_name=display_name,
        min_score=min_score,
    )
    if not candidates:
        return None, (), "No supported icon source image matched the selected target icon."
    if len(candidates) == 1:
        return candidates[0], candidates, candidates[0].reason
    if candidates[0].score == candidates[1].score:
        return None, candidates, "Icon source folder match is ambiguous; choose an explicit image file."
    return candidates[0], candidates, candidates[0].reason


def prepare_fit_pad_icon_png(source_path: Path, output_path: Path, width: int, height: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise ValueError(f"Icon dimensions are invalid: {width}x{height}.")
    with Image.open(source_path) as image:
        source_width, source_height = int(image.width), int(image.height)
        working = image.convert("RGBA")
        try:
            resampling = Image.Resampling.LANCZOS
        except AttributeError:  # pragma: no cover - Pillow compatibility fallback
            resampling = getattr(Image, "LANCZOS", 1)
        working.thumbnail((int(width), int(height)), resampling)
        canvas = Image.new("RGBA", (int(width), int(height)), (0, 0, 0, 0))
        x = max(0, (int(width) - int(working.width)) // 2)
        y = max(0, (int(height) - int(working.height)) // 2)
        canvas.alpha_composite(working, (x, y))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, "PNG")
    return source_width, source_height


def _copy_preview_to_output(preview_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if preview_path.expanduser().resolve() != output_path.expanduser().resolve():
        shutil.copy2(preview_path, output_path)
    return output_path


def _convert_dds_to_png(texconv_path: Optional[Path], dds_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    preview_path = ensure_dds_display_preview_png(
        texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None,
        dds_path,
        dds_info=parse_dds(dds_path),
        max_dimension=0,
    )
    expected = output_dir / f"{dds_path.stem}.png"
    return _copy_preview_to_output(Path(preview_path), expected)


def _image_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return int(image.width), int(image.height)


def _normalize_library_path_key(path: Path) -> str:
    try:
        return str(path.expanduser().resolve()).casefold()
    except OSError:
        return str(path.expanduser()).casefold()


def _coerce_string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _record_user_metadata(raw: object) -> tuple[tuple[str, ...], str, bool]:
    if not isinstance(raw, Mapping):
        return (), "", False
    return (
        _coerce_string_tuple(raw.get("tags")),
        str(raw.get("notes", "") or ""),
        bool(raw.get("favorite", False)),
    )


def load_item_icon_library_index(index_path: Path) -> dict[str, object]:
    resolved = index_path.expanduser()
    if not resolved.is_file():
        return {"version": 1, "roots": [], "records": {}}
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "roots": [], "records": {}}
    if not isinstance(raw, dict):
        return {"version": 1, "roots": [], "records": {}}
    roots = raw.get("roots")
    records = raw.get("records")
    return {
        "version": 1,
        "roots": [str(root) for root in roots] if isinstance(roots, list) else [],
        "records": records if isinstance(records, dict) else {},
    }


def save_item_icon_library_index(
    index_path: Path,
    *,
    roots: Sequence[Path],
    records: Sequence[ItemIconLibraryRecord],
) -> None:
    resolved = index_path.expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    payload_records: dict[str, dict[str, object]] = {}
    for record in records:
        key = _normalize_library_path_key(record.path)
        payload_records[key] = {
            "path": str(record.path),
            "root_path": str(record.root_path),
            "relative_path": record.relative_path,
            "file_size": int(record.file_size),
            "mtime_ns": int(record.mtime_ns),
            "width": int(record.width),
            "height": int(record.height),
            "tags": list(record.tags),
            "notes": record.notes,
            "favorite": bool(record.favorite),
            "source_kind": record.source_kind,
            "warning": record.warning,
        }
    payload = {
        "version": 1,
        "roots": [str(root) for root in roots],
        "records": payload_records,
    }
    resolved.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _read_source_dimensions(path: Path) -> tuple[int, int]:
    if path.suffix.lower() == ".dds":
        info = parse_dds(path)
        return int(info.width), int(info.height)
    return _image_dimensions(path)


def scan_item_icon_library(
    root_paths: Sequence[Path],
    *,
    index_path: Optional[Path] = None,
    edited_root: Optional[Path] = None,
) -> tuple[ItemIconLibraryRecord, ...]:
    existing_records: Mapping[str, object] = {}
    if index_path is not None:
        loaded = load_item_icon_library_index(index_path)
        raw_records = loaded.get("records", {})
        if isinstance(raw_records, Mapping):
            existing_records = raw_records

    roots: list[Path] = []
    seen_roots: set[str] = set()
    for root in tuple(root_paths) + ((edited_root,) if edited_root is not None else ()):
        if root is None:
            continue
        candidate = Path(root).expanduser()
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if not resolved.is_dir():
            continue
        key = _normalize_library_path_key(resolved)
        if key in seen_roots:
            continue
        seen_roots.add(key)
        roots.append(resolved)

    records: list[ItemIconLibraryRecord] = []
    for root in roots:
        source_kind = "edited" if edited_root is not None and _normalize_library_path_key(root) == _normalize_library_path_key(edited_root) else "folder"
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in ITEM_ICON_SOURCE_EXTENSIONS:
                continue
            key = _normalize_library_path_key(path)
            try:
                stat = path.stat()
                file_size = int(stat.st_size)
                mtime_ns = int(stat.st_mtime_ns)
            except OSError:
                continue
            old = existing_records.get(key)
            tags, notes, favorite = _record_user_metadata(old)
            width = height = 0
            warning = ""
            if isinstance(old, Mapping) and int(old.get("file_size", -1) or -1) == file_size and int(old.get("mtime_ns", -1) or -1) == mtime_ns:
                width = int(old.get("width", 0) or 0)
                height = int(old.get("height", 0) or 0)
                warning = str(old.get("warning", "") or "")
            else:
                try:
                    width, height = _read_source_dimensions(path)
                except Exception as exc:
                    warning = str(exc)
            records.append(
                ItemIconLibraryRecord(
                    path=path,
                    root_path=root,
                    relative_path=_relative_to_root(path, root),
                    file_size=file_size,
                    mtime_ns=mtime_ns,
                    width=width,
                    height=height,
                    tags=tags,
                    notes=notes,
                    favorite=favorite,
                    source_kind=source_kind,
                    warning=warning,
                )
            )
    records.sort(key=lambda record: (not record.favorite, record.path.name.casefold(), record.relative_path.casefold()))
    return tuple(records)


def update_item_icon_library_record_metadata(
    index_path: Path,
    record_path: Path,
    *,
    tags: Sequence[str] = (),
    notes: str = "",
    favorite: bool = False,
) -> None:
    loaded = load_item_icon_library_index(index_path)
    records = loaded.setdefault("records", {})
    if not isinstance(records, dict):
        records = {}
        loaded["records"] = records
    key = _normalize_library_path_key(record_path)
    record = records.get(key)
    if not isinstance(record, dict):
        record = {"path": str(record_path)}
        records[key] = record
    record["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()]
    record["notes"] = str(notes or "")
    record["favorite"] = bool(favorite)
    index_path.expanduser().parent.mkdir(parents=True, exist_ok=True)
    index_path.expanduser().write_text(json.dumps(loaded, indent=2, sort_keys=True), encoding="utf-8")


def import_edited_item_icon_source(source_path: Path, edited_root: Path) -> Path:
    source = source_path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Edited item icon export was not found: {source}")
    if source.suffix.lower() not in ITEM_ICON_SOURCE_EXTENSIONS:
        raise ValueError(f"Unsupported edited item icon source format: {source.suffix}")
    target_root = edited_root.expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    stem = source.stem or "item_icon"
    suffix = source.suffix.lower() or ".png"
    candidate = target_root / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        counter += 1
        candidate = target_root / f"{stem}_{counter}{suffix}"
    shutil.copy2(source, candidate)
    return candidate


def read_item_icon_template_info(target_path: str, target_template_path: Path) -> ItemIconTemplateInfo:
    target_template = target_template_path.expanduser().resolve()
    target_suffix = PurePosixPath(str(target_path or target_template.name).replace("\\", "/")).suffix.lower() or target_template.suffix.lower()
    if target_suffix == ".dds":
        target_info = parse_dds(target_template)
        target_width = int(target_info.width)
        target_height = int(target_info.height)
        target_format = str(target_info.texconv_format or "").strip()
        target_mip_count = max(1, min(max_mips_for_size(target_width, target_height), int(target_info.mip_count or 1)))
        if not target_format:
            raise ValueError(f"Target icon DDS format could not be determined: {target_path}")
        return ItemIconTemplateInfo(target_width, target_height, target_format, target_mip_count, target_suffix)
    width, height = _image_dimensions(target_template)
    return ItemIconTemplateInfo(width, height, target_suffix.lstrip(".") or "png", 1, target_suffix)


def build_item_icon_source_preview_png(
    source_path: Path,
    *,
    output_dir: Path,
    texconv_path: Optional[Path] = None,
) -> Path:
    source = source_path.expanduser().resolve()
    if source.suffix.lower() != ".dds":
        return source
    resolved_texconv = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
    return _convert_dds_to_png(resolved_texconv, source, output_dir.expanduser())


def build_item_icon_fit_pad_preview(
    source_path: Path,
    *,
    target_path: str,
    target_template_path: Path,
    output_path: Path,
    texconv_path: Optional[Path] = None,
) -> tuple[Path, ItemIconTemplateInfo, tuple[int, int]]:
    target_info = read_item_icon_template_info(target_path, target_template_path)
    source = source_path.expanduser().resolve()
    working_source = source
    with tempfile.TemporaryDirectory(prefix="cdmw_item_icon_preview_") as temp_text:
        temp_dir = Path(temp_text)
        if source.suffix.lower() == ".dds":
            resolved_texconv = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
            working_source = _convert_dds_to_png(resolved_texconv, source, temp_dir / "decoded")
        source_dimensions = prepare_fit_pad_icon_png(working_source, output_path, target_info.width, target_info.height)
    return output_path, target_info, source_dimensions


def _log(on_log: Optional[Callable[[str], None]], message: str) -> None:
    if on_log is not None:
        on_log(message)


def build_item_icon_payload(
    spec: ItemIconOverrideSpec,
    *,
    target_template_path: Path,
    texconv_path: Optional[Path],
    on_log: Optional[Callable[[str], None]] = None,
) -> ItemIconBuildResult:
    source_path = spec.source_path.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Custom icon source was not found: {source_path}")
    if source_path.suffix.lower() not in ITEM_ICON_SOURCE_EXTENSIONS:
        raise ValueError(f"Unsupported custom icon source format: {source_path.suffix}")

    target_path = str(spec.target_path or "").replace("\\", "/").strip()
    target_template = target_template_path.expanduser().resolve()
    if not target_template.is_file():
        raise FileNotFoundError(f"Target icon template was not found: {target_template}")

    warnings: list[str] = []
    target_suffix = PurePosixPath(target_path).suffix.lower() or target_template.suffix.lower()
    target_stem = PurePosixPath(target_path or target_template.name).stem or "item_icon"

    if target_suffix == ".dds":
        target_info = parse_dds(target_template)
        target_width = int(target_info.width)
        target_height = int(target_info.height)
        target_format = str(target_info.texconv_format or "").strip()
        target_mip_count = max(1, min(max_mips_for_size(target_width, target_height), int(target_info.mip_count or 1)))
        if not target_format:
            raise ValueError(f"Target icon DDS format could not be determined: {target_path}")
    else:
        target_width, target_height = _image_dimensions(target_template)
        target_format = target_suffix.lstrip(".") or "png"
        target_mip_count = 1

    with tempfile.TemporaryDirectory(prefix="cdmw_item_icon_") as temp_text:
        temp_dir = Path(temp_text)
        working_source = source_path
        if source_path.suffix.lower() == ".dds":
            if target_suffix == ".dds":
                source_info = parse_dds(source_path)
                source_matches_target = (
                    int(source_info.width) == target_width
                    and int(source_info.height) == target_height
                    and str(source_info.texconv_format or "").strip() == target_format
                    and int(source_info.mip_count or 1) == target_mip_count
                )
                if source_matches_target:
                    _log(on_log, f"Copying custom DDS icon without conversion: {source_path.name} -> {target_path}")
                    return ItemIconBuildResult(
                        payload_data=source_path.read_bytes(),
                        target_path=target_path,
                        source_path=source_path,
                        source_width=int(source_info.width),
                        source_height=int(source_info.height),
                        target_width=target_width,
                        target_height=target_height,
                        target_format=target_format,
                        target_mip_count=target_mip_count,
                        warnings=(),
                    )
            resolved_texconv = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
            working_source = _convert_dds_to_png(resolved_texconv, source_path, temp_dir / "decoded")
            warnings.append(f"Decoded DDS custom icon source with DirectXTex/native path before fitting: {source_path.name}")

        prepared_png = temp_dir / f"{target_stem}.png"
        source_width, source_height = prepare_fit_pad_icon_png(
            working_source,
            prepared_png,
            target_width,
            target_height,
        )

        if target_suffix != ".dds":
            _log(on_log, f"Writing custom image icon payload: {source_path.name} -> {target_path}")
            return ItemIconBuildResult(
                payload_data=prepared_png.read_bytes(),
                target_path=target_path,
                source_path=source_path,
                source_width=source_width,
                source_height=source_height,
                target_width=target_width,
                target_height=target_height,
                target_format=target_format,
                target_mip_count=target_mip_count,
                warnings=tuple(warnings),
            )

        output_dir = temp_dir / "dds"
        output_dir.mkdir(parents=True, exist_ok=True)
        _log(
            on_log,
            f"Generating custom item icon {source_path.name} -> {target_path} ({target_format}, {target_width}x{target_height}, {target_mip_count} mip(s)).",
        )
        produced = output_dir / f"{prepared_png.stem}.dds"
        native_report = encode_dds_with_directxtex(
            prepared_png,
            produced,
            dds_format=target_format,
            width=target_width,
            height=target_height,
            mip_count=target_mip_count,
        )
        if native_report and produced.is_file() and produced.stat().st_size > 0:
            _log(on_log, "Generated custom item icon with DirectXTex native DDS encode.")
        else:
            if texconv_path is None or not texconv_path.expanduser().is_file():
                raise FileNotFoundError(
                    "DirectXTex native DDS encode failed and no optional legacy texconv fallback is configured."
                )
            cmd = build_texconv_command(
                texconv_path.expanduser().resolve(),
                prepared_png,
                output_dir,
                target_format,
                target_mip_count,
                target_width,
                target_height,
                overwrite_existing_dds=True,
            )
            return_code, stdout, stderr = run_process_with_cancellation(cmd)
            if return_code != 0:
                detail = stderr.strip() or stdout.strip() or f"texconv exited with code {return_code}"
                raise RuntimeError(f"texconv fallback failed while generating custom item icon: {detail}")
        if not produced.is_file():
            raise FileNotFoundError(f"DDS encoder did not produce {produced.name}")
        produced_info = parse_dds(produced)
        if (int(produced_info.width), int(produced_info.height)) != (target_width, target_height):
            warnings.append(
                f"Generated icon dimensions {produced_info.width}x{produced_info.height} did not match target {target_width}x{target_height}."
            )
        if str(produced_info.texconv_format or "").strip() != target_format:
            warnings.append(
                f"Generated icon format {produced_info.texconv_format} did not match target {target_format}."
            )
        return ItemIconBuildResult(
            payload_data=produced.read_bytes(),
            target_path=target_path,
            source_path=source_path,
            source_width=source_width,
            source_height=source_height,
            target_width=target_width,
            target_height=target_height,
            target_format=target_format,
            target_mip_count=target_mip_count,
            warnings=tuple(warnings),
        )
