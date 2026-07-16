from __future__ import annotations

import json
import shutil
import tempfile
import threading
import zipfile
from collections import deque
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Optional, Sequence

from PIL import Image, ImageFilter

from cdmw.core.atomic_file import atomic_publish_directory, atomic_publish_files, atomic_write_text
from cdmw.core.common import raise_if_cancelled
from cdmw.core.texture_pipeline.inspection import parse_dds
from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
from cdmw.core.texture_native import encode_dds_with_directxtex
from cdmw.domain.library.item_icons import (
    ITEM_ICON_BACKGROUND_MODES,
    ITEM_ICON_DEFAULT_BACKGROUND_MODE,
    ITEM_ICON_SOURCE_EXTENSIONS,
    ItemIconBuildResult,
    ItemIconLibraryRecord,
    ItemIconLooseModPatchResult,
    ItemIconOverrideSpec,
    ItemIconPreparedImageResult,
    ItemIconSourceCandidate,
    ItemIconTemplateInfo,
    normalize_item_icon_background_mode,
    score_item_icon_source_candidate as _candidate_score,
    select_item_icon_source_candidate,
)
from cdmw.domain.textures.output import max_mips_for_size
from cdmw.core.mod_package import is_mod_package_payload_path, normalize_mod_package_payload_path


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
    return select_item_icon_source_candidate(candidates)[1]


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
    return select_item_icon_source_candidate(candidates)


def _resampling_lanczos() -> int:
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:  # pragma: no cover - Pillow compatibility fallback
        return getattr(Image, "LANCZOS", 1)


def _has_meaningful_alpha(image: Image.Image) -> bool:
    alpha = image.getchannel("A")
    alpha_min, alpha_max = alpha.getextrema()
    if alpha_min >= 250 or alpha_max <= 0:
        return False
    histogram = alpha.histogram()
    transparentish = sum(histogram[:250])
    return transparentish >= max(16, (image.width * image.height) // 200)


def _alpha_content_bbox(image: Image.Image, *, threshold: int = 8) -> Optional[tuple[int, int, int, int]]:
    alpha = image.getchannel("A")
    mask = alpha.point(lambda value: 255 if value > threshold else 0)
    return mask.getbbox()


def _fit_rgba_on_canvas(
    working: Image.Image,
    *,
    width: int,
    height: int,
    scale: float,
    underlay: Optional[Image.Image] = None,
) -> Image.Image:
    canvas = Image.new("RGBA", (int(width), int(height)), (0, 0, 0, 0))
    if underlay is not None:
        background = underlay.convert("RGBA")
        if background.size != canvas.size:
            background = background.resize(canvas.size, _resampling_lanczos())
        canvas.alpha_composite(background)
    max_width = max(1, int(round(width * max(0.01, min(1.0, scale)))))
    max_height = max(1, int(round(height * max(0.01, min(1.0, scale)))))
    fitted = working.copy()
    fitted.thumbnail((max_width, max_height), _resampling_lanczos())
    x = max(0, (int(width) - int(fitted.width)) // 2)
    y = max(0, (int(height) - int(fitted.height)) // 2)
    canvas.alpha_composite(fitted, (x, y))
    return canvas


def _common_border_color(image: Image.Image) -> Optional[tuple[int, int, int]]:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    if width <= 0 or height <= 0:
        return None
    step = max(1, min(width, height) // 48)
    samples: list[tuple[int, int, int]] = []

    def add_sample(x: int, y: int) -> None:
        red, green, blue, alpha = rgba.getpixel((x, y))
        if alpha > 16:
            samples.append((red, green, blue))

    for x in range(0, width, step):
        add_sample(x, 0)
        add_sample(x, height - 1)
    for y in range(0, height, step):
        add_sample(0, y)
        add_sample(width - 1, y)
    if not samples:
        rgb = rgba.convert("RGB")
        for x in range(0, width, step):
            samples.append(rgb.getpixel((x, 0)))
            samples.append(rgb.getpixel((x, height - 1)))
        for y in range(0, height, step):
            samples.append(rgb.getpixel((0, y)))
            samples.append(rgb.getpixel((width - 1, y)))
    buckets: dict[tuple[int, int, int], list[tuple[int, int, int]]] = {}
    for red, green, blue in samples:
        buckets.setdefault((red // 8, green // 8, blue // 8), []).append((red, green, blue))
    _bucket, values = max(buckets.items(), key=lambda item: len(item[1]))
    if len(values) < max(4, len(samples) // 8):
        return None
    return (
        sum(pixel[0] for pixel in values) // len(values),
        sum(pixel[1] for pixel in values) // len(values),
        sum(pixel[2] for pixel in values) // len(values),
    )


def _color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
    return max(abs(left[0] - right[0]), abs(left[1] - right[1]), abs(left[2] - right[2]))


def _bbox_area(bbox: Optional[tuple[int, int, int, int]]) -> int:
    if bbox is None:
        return 0
    left, top, right, bottom = bbox
    return max(0, int(right) - int(left)) * max(0, int(bottom) - int(top))


def _background_removal_is_useful(before: Image.Image, after: Image.Image) -> bool:
    before_bbox = _alpha_content_bbox(before, threshold=16)
    after_bbox = _alpha_content_bbox(after, threshold=16)
    before_area = _bbox_area(before_bbox)
    after_area = _bbox_area(after_bbox)
    if before_area <= 0 or after_area <= 0:
        return False
    if after_area < max(16, before_area // 40):
        return False
    alpha_before = sum(before.getchannel("A").histogram()[17:])
    alpha_after = sum(after.getchannel("A").histogram()[17:])
    if alpha_after < max(16, alpha_before // 40):
        return False
    return after_area <= int(before_area * 0.94) or alpha_after <= int(alpha_before * 0.94)


def _remove_edge_connected_background(
    image: Image.Image,
    *,
    tolerance: int = 34,
    stop_event: Optional[threading.Event] = None,
) -> Optional[Image.Image]:
    raise_if_cancelled(stop_event, "Item icon background removal cancelled.")
    background_color = _common_border_color(image)
    if background_color is None:
        return None
    rgb = image.convert("RGB")
    alpha = image.getchannel("A")
    width, height = rgb.size
    tolerance = max(2, min(64, int(tolerance)))
    visited = bytearray(width * height)
    background = Image.new("L", (width, height), 0)
    background_pixels = background.load()
    queue: deque[tuple[int, int]] = deque()

    def enqueue_if_background(x: int, y: int) -> None:
        index = y * width + x
        if visited[index]:
            return
        visited[index] = 1
        if alpha.getpixel((x, y)) <= 8 or _color_distance(rgb.getpixel((x, y)), background_color) <= tolerance:
            queue.append((x, y))

    for x in range(width):
        enqueue_if_background(x, 0)
        enqueue_if_background(x, height - 1)
    for y in range(height):
        enqueue_if_background(0, y)
        enqueue_if_background(width - 1, y)

    visited_count = 0
    while queue:
        x, y = queue.popleft()
        visited_count += 1
        if visited_count % 4096 == 0:
            raise_if_cancelled(stop_event, "Item icon background removal cancelled.")
        background_pixels[x, y] = 255
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nx < 0 or ny < 0 or nx >= width or ny >= height:
                continue
            index = ny * width + nx
            if visited[index]:
                continue
            visited[index] = 1
            if alpha.getpixel((nx, ny)) <= 8 or _color_distance(rgb.getpixel((nx, ny)), background_color) <= tolerance:
                queue.append((nx, ny))

    blurred_background = background.filter(ImageFilter.GaussianBlur(radius=1.1))
    new_alpha = Image.new("L", (width, height), 0)
    alpha_pixels = alpha.load()
    bg_pixels = blurred_background.load()
    out_pixels = new_alpha.load()
    for y in range(height):
        if y % 32 == 0:
            raise_if_cancelled(stop_event, "Item icon background removal cancelled.")
        for x in range(width):
            out_pixels[x, y] = max(0, min(255, int(alpha_pixels[x, y] * (255 - bg_pixels[x, y]) / 255)))

    result = image.copy()
    result.putalpha(new_alpha)
    bbox = _alpha_content_bbox(result, threshold=16)
    if bbox is None:
        return None
    foreground_area = sum(new_alpha.histogram()[17:])
    if foreground_area < max(16, (width * height) // 250):
        return None
    return result


def _prepare_item_icon_image(
    source_path: Path,
    output_path: Path,
    width: int,
    height: int,
    *,
    background_mode: str,
    target_underlay_path: Optional[Path] = None,
    stop_event: Optional[threading.Event] = None,
) -> ItemIconPreparedImageResult:
    raise_if_cancelled(stop_event, "Item icon preview preparation cancelled.")
    if width <= 0 or height <= 0:
        raise ValueError(f"Icon dimensions are invalid: {width}x{height}.")
    mode = normalize_item_icon_background_mode(background_mode)
    with Image.open(source_path) as image:
        source_width, source_height = int(image.width), int(image.height)
        working = image.convert("RGBA")
    raise_if_cancelled(stop_event, "Item icon preview preparation cancelled.")
    warnings: list[str] = []
    underlay: Optional[Image.Image] = None
    if mode == "target_underlay" and target_underlay_path is not None:
        try:
            with Image.open(target_underlay_path) as target_image:
                underlay = target_image.convert("RGBA")
        except Exception as exc:
            warnings.append(f"Target underlay could not be loaded; using transparent canvas: {exc}")

    if mode == "keep_source":
        prepared = _fit_rgba_on_canvas(working, width=width, height=height, scale=1.0, underlay=None)
    else:
        processed = working
        if _has_meaningful_alpha(processed):
            bbox = _alpha_content_bbox(processed, threshold=8)
            if bbox is not None:
                cropped = processed.crop(bbox)
                removed = _remove_edge_connected_background(cropped, tolerance=12, stop_event=stop_event)
                if removed is not None and _background_removal_is_useful(cropped, removed):
                    processed = removed
                else:
                    processed = cropped
        else:
            removed = _remove_edge_connected_background(processed, tolerance=34, stop_event=stop_event)
            if removed is None:
                warnings.append("Auto transparent background removal could not isolate a foreground; preserved source background.")
            else:
                processed = removed
        bbox = _alpha_content_bbox(processed, threshold=8)
        if bbox is not None:
            processed = processed.crop(bbox)
        prepared = _fit_rgba_on_canvas(processed, width=width, height=height, scale=0.86, underlay=underlay)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    raise_if_cancelled(stop_event, "Item icon preview preparation cancelled.")
    prepared.save(output_path, "PNG")
    return ItemIconPreparedImageResult(
        source_width=source_width,
        source_height=source_height,
        output_path=output_path,
        background_mode=mode,
        warnings=tuple(warnings),
    )


def prepare_item_icon_png(
    source_path: Path,
    output_path: Path,
    width: int,
    height: int,
    *,
    background_mode: str = ITEM_ICON_DEFAULT_BACKGROUND_MODE,
    target_underlay_path: Optional[Path] = None,
    stop_event: Optional[threading.Event] = None,
) -> ItemIconPreparedImageResult:
    return _prepare_item_icon_image(
        source_path,
        output_path,
        width,
        height,
        background_mode=background_mode,
        target_underlay_path=target_underlay_path,
        stop_event=stop_event,
    )


def prepare_fit_pad_icon_png(
    source_path: Path,
    output_path: Path,
    width: int,
    height: int,
    *,
    background_mode: str = ITEM_ICON_DEFAULT_BACKGROUND_MODE,
    target_underlay_path: Optional[Path] = None,
    stop_event: Optional[threading.Event] = None,
) -> tuple[int, int]:
    result = prepare_item_icon_png(
        source_path,
        output_path,
        width,
        height,
        background_mode=background_mode,
        target_underlay_path=target_underlay_path,
        stop_event=stop_event,
    )
    return result.source_width, result.source_height


def _copy_preview_to_output(preview_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if preview_path.expanduser().resolve() != output_path.expanduser().resolve():
        shutil.copy2(preview_path, output_path)
    return output_path


def _convert_dds_to_png(
    dds_path: Path,
    output_dir: Path,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Path:
    raise_if_cancelled(stop_event, "Item icon DDS preview conversion cancelled.")
    output_dir.mkdir(parents=True, exist_ok=True)
    preview_path = ensure_dds_display_preview_png(
        dds_path,
        dds_info=parse_dds(dds_path),
        max_dimension=0,
        stop_event=stop_event,
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
    stop_event: Optional[threading.Event] = None,
) -> None:
    resolved = index_path.expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    payload_records: dict[str, dict[str, object]] = {}
    for index, record in enumerate(records):
        if index % 256 == 0:
            raise_if_cancelled(stop_event, "Item icon library index save cancelled.")
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
    raise_if_cancelled(stop_event, "Item icon library index save cancelled.")
    atomic_write_text(resolved, json.dumps(payload, indent=2, sort_keys=True))


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


def inspect_item_icon_library_source(
    source_path: Path,
    *,
    record_path: Optional[Path] = None,
    root_path: Optional[Path] = None,
    tags: Sequence[str] = (),
    notes: str = "",
    favorite: bool = False,
    source_kind: str = "edited",
    stop_event: Optional[threading.Event] = None,
) -> ItemIconLibraryRecord:
    """Build one library record without scanning its containing directory."""

    source = source_path.expanduser()
    raise_if_cancelled(stop_event, "Item icon source inspection cancelled.")
    stat = source.stat()
    width = height = 0
    warning = ""
    try:
        width, height = _read_source_dimensions(source)
    except Exception as exc:
        warning = str(exc)
    raise_if_cancelled(stop_event, "Item icon source inspection cancelled.")
    stored = (record_path or source).expanduser()
    root = (root_path or stored.parent).expanduser()
    return ItemIconLibraryRecord(
        path=stored,
        root_path=root,
        relative_path=_relative_to_root(stored, root),
        file_size=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
        width=int(width),
        height=int(height),
        tags=tuple(str(tag).strip() for tag in tags if str(tag).strip()),
        notes=str(notes or ""),
        favorite=bool(favorite),
        source_kind=str(source_kind or "edited"),
        warning=warning,
    )


def scan_item_icon_library(
    root_paths: Sequence[Path],
    *,
    index_path: Optional[Path] = None,
    edited_root: Optional[Path] = None,
    stop_event: Optional[threading.Event] = None,
) -> tuple[ItemIconLibraryRecord, ...]:
    raise_if_cancelled(stop_event, "Item icon library scan cancelled.")
    existing_records: Mapping[str, object] = {}
    if index_path is not None:
        loaded = load_item_icon_library_index(index_path)
        raw_records = loaded.get("records", {})
        if isinstance(raw_records, Mapping):
            existing_records = raw_records

    roots: list[Path] = []
    seen_roots: set[str] = set()
    for root in tuple(root_paths) + ((edited_root,) if edited_root is not None else ()):
        raise_if_cancelled(stop_event, "Item icon library scan cancelled.")
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
        raise_if_cancelled(stop_event, "Item icon library scan cancelled.")
        source_kind = "edited" if edited_root is not None and _normalize_library_path_key(root) == _normalize_library_path_key(edited_root) else "folder"
        for path in root.rglob("*"):
            raise_if_cancelled(stop_event, "Item icon library scan cancelled.")
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
    stop_event: Optional[threading.Event] = None,
) -> None:
    raise_if_cancelled(stop_event, "Item icon metadata save cancelled.")
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
    raise_if_cancelled(stop_event, "Item icon metadata save cancelled.")
    atomic_write_text(index_path.expanduser(), json.dumps(loaded, indent=2, sort_keys=True))


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
        target_format = str(target_info.dds_format or "").strip()
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
    stop_event: Optional[threading.Event] = None,
) -> Path:
    raise_if_cancelled(stop_event, "Item icon source preview cancelled.")
    source = source_path.expanduser().resolve()
    if source.suffix.lower() != ".dds":
        return source
    return _convert_dds_to_png(
        source,
        output_dir.expanduser(),
        stop_event=stop_event,
    )


def build_item_icon_fit_pad_preview(
    source_path: Path,
    *,
    target_path: str,
    target_template_path: Path,
    output_path: Path,
    background_mode: str = ITEM_ICON_DEFAULT_BACKGROUND_MODE,
    stop_event: Optional[threading.Event] = None,
) -> tuple[Path, ItemIconTemplateInfo, tuple[int, int], tuple[str, ...]]:
    raise_if_cancelled(stop_event, "Item icon final preview cancelled.")
    target_info = read_item_icon_template_info(target_path, target_template_path)
    source = source_path.expanduser().resolve()
    working_source = source
    with tempfile.TemporaryDirectory(prefix="cdmw_item_icon_preview_") as temp_text:
        temp_dir = Path(temp_text)
        if source.suffix.lower() == ".dds":
            working_source = _convert_dds_to_png(
                source,
                temp_dir / "decoded",
                stop_event=stop_event,
            )
        target_underlay_path: Optional[Path] = None
        if normalize_item_icon_background_mode(background_mode) == "target_underlay":
            if target_info.suffix == ".dds":
                target_underlay_path = _convert_dds_to_png(
                    target_template_path,
                    temp_dir / "target_underlay",
                    stop_event=stop_event,
                )
            else:
                target_underlay_path = target_template_path
        prepared = prepare_item_icon_png(
            working_source,
            output_path,
            target_info.width,
            target_info.height,
            background_mode=background_mode,
            target_underlay_path=target_underlay_path,
            stop_event=stop_event,
        )
        source_dimensions = (prepared.source_width, prepared.source_height)
        warnings = prepared.warnings
    return output_path, target_info, source_dimensions, warnings


def _safe_loose_mod_payload_path(path_value: str | Path) -> PurePosixPath:
    raw_parts = PurePosixPath(str(path_value or "").replace("\\", "/")).parts
    if any(part == ".." for part in raw_parts):
        raise ValueError(f"Invalid loose mod payload path: {path_value}")
    normalized = normalize_mod_package_payload_path(path_value)
    parts = [part for part in normalized.parts if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"Invalid loose mod payload path: {path_value}")
    return PurePosixPath(*parts)


def _item_icon_manifest_payload_prefix(
    manifest: Mapping[str, object] | None,
    source_root: Path,
    *,
    stop_event: Optional[threading.Event] = None,
) -> PurePosixPath:
    if manifest is not None:
        for key in ("files_root", "files_dir"):
            value = str(manifest.get(key) or "").replace("\\", "/").strip().strip("/")
            if value and value not in {".", "/"}:
                prefix = PurePosixPath(value)
                if any(part in {"", ".", ".."} for part in prefix.parts):
                    raise ValueError(f"Invalid loose mod manifest {key}: {value}")
                return prefix
        structure = str(manifest.get("structure") or "").strip().lower()
        if structure in {"files_wrapper", "custom_compact_paths"}:
            return PurePosixPath("files")
    files_root = source_root / "files"
    if files_root.is_dir():
        for path in files_root.rglob("*"):
            raise_if_cancelled(stop_event, "Item icon loose-mod inspection cancelled.")
            if not path.is_file() or path.suffix.lower() == ".zip":
                continue
            try:
                relative = path.relative_to(files_root)
            except ValueError:
                continue
            if is_mod_package_payload_path(relative):
                return PurePosixPath("files")
    return PurePosixPath()


def _looks_like_loose_mod_root(
    root: Path,
    *,
    stop_event: Optional[threading.Event] = None,
) -> bool:
    if (root / "manifest.json").is_file():
        return True
    for path in root.rglob("*"):
        raise_if_cancelled(stop_event, "Item icon loose-mod inspection cancelled.")
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if path.suffix.lower() == ".zip":
            continue
        normalized = normalize_mod_package_payload_path(relative)
        if len(normalized.parts) >= 2 and is_mod_package_payload_path(relative):
            return True
    return False


def _next_item_icon_patch_root(source_root: Path, suffix: str) -> Path:
    normalized_suffix = str(suffix or "_with_icon").strip() or "_with_icon"
    base = source_root.with_name(f"{source_root.name}{normalized_suffix}")
    if not base.exists() and not base.with_suffix(".zip").exists():
        return base
    for index in range(2, 1000):
        candidate = source_root.with_name(f"{source_root.name}{normalized_suffix}_{index}")
        if not candidate.exists() and not candidate.with_suffix(".zip").exists():
            return candidate
    raise FileExistsError(f"Could not choose a free patched output folder beside {source_root}")


def _copy_loose_mod_tree_without_root_zips(
    source_root: Path,
    output_root: Path,
    *,
    stop_event: Optional[threading.Event] = None,
) -> int:
    copied = 0
    output_root.mkdir(parents=True, exist_ok=False)
    for path in sorted(source_root.rglob("*")):
        raise_if_cancelled(stop_event, "Item icon loose-mod copy cancelled.")
        try:
            relative = path.relative_to(source_root)
        except ValueError:
            continue
        if path.is_dir():
            (output_root / relative).mkdir(parents=True, exist_ok=True)
            continue
        if not path.is_file():
            continue
        if relative.parent == Path(".") and path.suffix.lower() == ".zip":
            continue
        destination = output_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied += 1
    return copied


def _write_item_icon_patch_zip(
    output_root: Path,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Path:
    zip_path = output_root.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output_root.rglob("*")):
            raise_if_cancelled(stop_event, "Item icon loose-mod zip cancelled.")
            if not path.is_file() or path.suffix.lower() == ".zip":
                continue
            archive.write(path, path.relative_to(output_root).as_posix())
    return zip_path


def _manifest_row_path(value: object) -> str:
    if isinstance(value, Mapping):
        raw_path = value.get("path") or value.get("entry_path") or ""
    else:
        raw_path = value
    try:
        return _safe_loose_mod_payload_path(str(raw_path or "")).as_posix()
    except ValueError:
        return ""


def _update_loose_mod_manifest_for_item_icon(
    manifest_path: Path,
    *,
    target_path: PurePosixPath,
    target_entry: object | None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    raise_if_cancelled(stop_event, "Item icon loose-mod manifest update cancelled.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse loose mod manifest.json: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Loose mod manifest.json must contain a JSON object.")

    target_text = target_path.as_posix()
    raw_files = manifest.get("files")
    files = list(raw_files) if isinstance(raw_files, list) else []
    kept_files = [row for row in files if _manifest_row_path(row).casefold() != target_text.casefold()]

    package_group = ""
    pamt_path = getattr(target_entry, "pamt_path", None)
    if isinstance(pamt_path, Path):
        package_group = pamt_path.parent.name
    elif pamt_path is not None:
        package_group = Path(str(pamt_path)).parent.name

    icon_row: dict[str, object] = {
        "path": target_text,
        "format": target_path.suffix.lstrip(".").lower() or "dds",
        "note": "Generated item icon override from Icon Creator.",
    }
    if package_group:
        icon_row["package_group"] = package_group
    kept_files.append(icon_row)
    manifest["files"] = kept_files
    manifest["file_count"] = len(kept_files)

    if target_entry is not None:
        new_paths = manifest.get("new_paths")
        if isinstance(new_paths, list):
            filtered_new_paths = [
                value
                for value in new_paths
                if _manifest_row_path(value).casefold() != target_text.casefold()
            ]
            if filtered_new_paths:
                manifest["new_paths"] = filtered_new_paths
            else:
                manifest.pop("new_paths", None)

    raise_if_cancelled(stop_event, "Item icon loose-mod manifest update cancelled.")
    atomic_write_text(manifest_path, json.dumps(manifest, indent=2))


def patch_existing_loose_mod_with_item_icon(
    loose_mod_root: Path,
    *,
    target_path: str,
    payload_data: bytes,
    target_entry: object | None = None,
    output_suffix: str = "_with_icon",
    stop_event: Optional[threading.Event] = None,
) -> ItemIconLooseModPatchResult:
    raise_if_cancelled(stop_event, "Item icon loose-mod patch cancelled.")
    source_root = loose_mod_root.expanduser().resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"Choose an existing loose mod folder: {source_root}")
    if not _looks_like_loose_mod_root(source_root, stop_event=stop_event):
        raise ValueError(f"{source_root} does not look like a loose mod package or game-relative loose file tree.")
    if not payload_data:
        raise ValueError("Generated item icon payload is empty.")

    normalized_target_path = _safe_loose_mod_payload_path(target_path)
    output_root = _next_item_icon_patch_root(source_root, output_suffix)
    had_source_zip = False
    for path in source_root.iterdir():
        raise_if_cancelled(stop_event, "Item icon loose-mod patch cancelled.")
        if path.is_file() and path.suffix.lower() == ".zip":
            had_source_zip = True
            break

    staging_parent = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}.", suffix=".tmp", dir=output_root.parent)
    )
    staged_root = staging_parent / "package"
    final_zip_path = output_root.with_suffix(".zip") if had_source_zip else None
    published_root = False
    try:
        copied_file_count = _copy_loose_mod_tree_without_root_zips(
            source_root,
            staged_root,
            stop_event=stop_event,
        )
        staged_manifest_path = staged_root / "manifest.json"
        had_manifest = staged_manifest_path.is_file()
        manifest: Mapping[str, object] | None = None
        if had_manifest:
            try:
                raw_manifest = json.loads(staged_manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Could not parse loose mod manifest.json: {exc}") from exc
            if not isinstance(raw_manifest, dict):
                raise ValueError("Loose mod manifest.json must contain a JSON object.")
            manifest = raw_manifest

        payload_prefix = _item_icon_manifest_payload_prefix(
            manifest,
            staged_root,
            stop_event=stop_event,
        )
        destination_relative = PurePosixPath(*(payload_prefix.parts + normalized_target_path.parts))
        staged_icon_path = staged_root.joinpath(*destination_relative.parts)
        staged_icon_path.parent.mkdir(parents=True, exist_ok=True)
        raise_if_cancelled(stop_event, "Item icon loose-mod patch cancelled.")
        staged_icon_path.write_bytes(payload_data)
        raise_if_cancelled(stop_event, "Item icon loose-mod patch cancelled.")

        if had_manifest:
            _update_loose_mod_manifest_for_item_icon(
                staged_manifest_path,
                target_path=normalized_target_path,
                target_entry=target_entry,
                stop_event=stop_event,
            )

        staged_zip_path = (
            _write_item_icon_patch_zip(staged_root, stop_event=stop_event)
            if had_source_zip
            else None
        )
        raise_if_cancelled(stop_event, "Item icon loose-mod patch cancelled.")
        atomic_publish_directory(staged_root, output_root)
        published_root = True
        if staged_zip_path is not None and final_zip_path is not None:
            atomic_publish_files({staged_zip_path: final_zip_path})

        return ItemIconLooseModPatchResult(
            source_root=source_root,
            output_root=output_root,
            icon_path=output_root.joinpath(*destination_relative.parts),
            manifest_path=(output_root / "manifest.json") if had_manifest else None,
            zip_path=final_zip_path,
            copied_file_count=copied_file_count,
        )
    except Exception:
        if published_root:
            shutil.rmtree(output_root, ignore_errors=True)
        if final_zip_path is not None:
            final_zip_path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def _log(on_log: Optional[Callable[[str], None]], message: str) -> None:
    if on_log is not None:
        on_log(message)


def build_item_icon_payload(
    spec: ItemIconOverrideSpec,
    *,
    target_template_path: Path,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> ItemIconBuildResult:
    raise_if_cancelled(stop_event, "Item icon build cancelled.")
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
    background_mode = normalize_item_icon_background_mode(spec.background_mode)

    if target_suffix == ".dds":
        target_info = parse_dds(target_template)
        target_width = int(target_info.width)
        target_height = int(target_info.height)
        target_format = str(target_info.dds_format or "").strip()
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
                    and str(source_info.dds_format or "").strip() == target_format
                    and int(source_info.mip_count or 1) == target_mip_count
                )
                if source_matches_target and background_mode == "keep_source":
                    _log(on_log, f"Copying custom DDS icon without conversion: {source_path.name} -> {target_path}")
                    raise_if_cancelled(stop_event, "Item icon build cancelled.")
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
            working_source = _convert_dds_to_png(
                source_path,
                temp_dir / "decoded",
                stop_event=stop_event,
            )
            warnings.append(f"Decoded DDS custom icon source with DirectXTex/native path before fitting: {source_path.name}")

        prepared_png = temp_dir / f"{target_stem}.png"
        target_underlay_path: Optional[Path] = None
        if background_mode == "target_underlay":
            if target_suffix == ".dds":
                target_underlay_path = _convert_dds_to_png(
                    target_template,
                    temp_dir / "target_underlay",
                    stop_event=stop_event,
                )
            else:
                target_underlay_path = target_template
        prepared = prepare_item_icon_png(
            working_source,
            prepared_png,
            target_width,
            target_height,
            background_mode=background_mode,
            target_underlay_path=target_underlay_path,
            stop_event=stop_event,
        )
        source_width, source_height = prepared.source_width, prepared.source_height
        warnings.extend(prepared.warnings)

        if target_suffix != ".dds":
            _log(on_log, f"Writing custom image icon payload: {source_path.name} -> {target_path}")
            raise_if_cancelled(stop_event, "Item icon build cancelled.")
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
            stop_event=stop_event,
        )
        if native_report and produced.is_file() and produced.stat().st_size > 0:
            _log(on_log, "Generated custom item icon with DirectXTex native DDS encode.")
        else:
            raise RuntimeError("Native DDS encode failed while generating the custom item icon.")
        if not produced.is_file():
            raise FileNotFoundError(f"DDS encoder did not produce {produced.name}")
        produced_info = parse_dds(produced)
        if (int(produced_info.width), int(produced_info.height)) != (target_width, target_height):
            warnings.append(
                f"Generated icon dimensions {produced_info.width}x{produced_info.height} did not match target {target_width}x{target_height}."
            )
        if str(produced_info.dds_format or "").strip() != target_format:
            warnings.append(
                f"Generated icon format {produced_info.dds_format} did not match target {target_format}."
            )
        raise_if_cancelled(stop_event, "Item icon build cancelled.")
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
