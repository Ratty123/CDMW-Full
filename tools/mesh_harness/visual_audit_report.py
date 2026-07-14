from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def build_visual_audit_composites(
    corpus: Mapping[str, object],
    archive_report: Mapping[str, object],
    dotnet_report: Mapping[str, object],
    temporary_root: Path,
    final_root: Path,
    *,
    selected_angles: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    temporary_root = Path(temporary_root)
    final_root = Path(final_root)
    temporary_root.mkdir(parents=True, exist_ok=True)
    final_root.mkdir(parents=True, exist_ok=True)
    archive_assets = _asset_map(archive_report)
    dotnet_assets = _asset_map(dotnet_report)
    rows: list[dict[str, object]] = []
    for asset in tuple(corpus.get("assets", ()) or ()):
        if not isinstance(asset, Mapping):
            continue
        asset_id = str(asset.get("asset_id", "") or "")
        archive_row = archive_assets.get(asset_id, {})
        dotnet_row = dotnet_assets.get(asset_id, {})
        archive_captures = _capture_map(archive_row)
        dotnet_captures = _capture_map(dotnet_row)
        comparisons: dict[str, str] = {}
        for view in ("front", "three-quarter-front", "side", "back", "slightly-above", "slightly-below"):
            output_path = temporary_root / "comparisons" / asset_id / f"{view}.png"
            _write_pair(
                Path(str(archive_captures.get(view, {}).get("path", ""))),
                Path(str(dotnet_captures.get(view, {}).get("path", ""))),
                output_path,
                left_label="Archive Browser",
                right_label="Mesh Editor .NET/Vortice",
                footer=f"{asset_id} | {view}",
            )
            comparisons[view] = str(output_path)
        contact_sheet = temporary_root / "contact-sheets" / f"{asset_id}.png"
        _write_contact_sheet(tuple(Path(path) for path in comparisons.values()), contact_sheet)
        selected = str((selected_angles or {}).get(asset_id, "three-quarter-front"))
        if selected not in comparisons:
            selected = "three-quarter-front"
        final_path = final_root / f"{asset_id}.png"
        _copy_png_without_color_change(Path(comparisons[selected]), final_path)
        rows.append(
            {
                "id": asset_id,
                "virtual_path": str(asset.get("virtual_path", "") or ""),
                "selected_camera_angle": selected,
                "candidate_comparisons": comparisons,
                "contact_sheet": str(contact_sheet),
                "primary_final_png": str(final_path),
                "primary_final_sha256": _sha256_file(final_path),
                "archive_browser_capture_ok": bool(archive_row.get("ok")),
                "mesh_editor_capture_ok": bool(dotnet_row.get("ok")),
            }
        )
    return rows


def _write_pair(
    left_path: Path,
    right_path: Path,
    output_path: Path,
    *,
    left_label: str,
    right_label: str,
    footer: str,
) -> None:
    left = _open_or_error(left_path, "Archive Browser capture missing")
    right = _open_or_error(right_path, "Mesh Editor capture missing")
    width = max(left.width, right.width)
    height = max(left.height, right.height)
    left = _pad_without_resampling(left, width, height)
    right = _pad_without_resampling(right, width, height)
    header_height = 32
    footer_height = 28
    canvas = Image.new("RGB", (width * 2, height + header_height + footer_height), (20, 23, 28))
    canvas.paste(left, (0, header_height))
    canvas.paste(right, (width, header_height))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    draw.text((10, 10), left_label, fill=(235, 240, 246), font=font)
    draw.text((width + 10, 10), right_label, fill=(235, 240, 246), font=font)
    draw.line((width, 0, width, canvas.height), fill=(100, 110, 125), width=1)
    draw.text((10, header_height + height + 8), footer, fill=(205, 213, 224), font=font)
    _atomic_save(canvas, output_path)
    left.close()
    right.close()
    canvas.close()


def _write_contact_sheet(comparisons: Sequence[Path], output_path: Path) -> None:
    images = [_open_or_error(path, f"Comparison missing: {path.name}") for path in comparisons]
    if not images:
        raise ValueError("Contact sheet requires at least one comparison.")
    cell_width = max(image.width for image in images)
    cell_height = max(image.height for image in images)
    columns = 2
    rows = (len(images) + columns - 1) // columns
    canvas = Image.new("RGB", (cell_width * columns, cell_height * rows), (13, 16, 20))
    for index, image in enumerate(images):
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        canvas.paste(_pad_without_resampling(image, cell_width, cell_height), (x, y))
    _atomic_save(canvas, output_path)
    for image in images:
        image.close()
    canvas.close()


def _open_or_error(path: Path, message: str) -> Image.Image:
    try:
        if path.is_file():
            with Image.open(path) as image:
                return image.convert("RGB")
    except OSError:
        pass
    image = Image.new("RGB", (768, 768), (40, 20, 24))
    draw = ImageDraw.Draw(image)
    draw.text((24, 24), message, fill=(255, 190, 190), font=ImageFont.load_default())
    return image


def _pad_without_resampling(image: Image.Image, width: int, height: int) -> Image.Image:
    if image.width == width and image.height == height:
        return image
    padded = Image.new("RGB", (width, height), (16, 18, 22))
    padded.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
    return padded


def _copy_png_without_color_change(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        copy = image.copy()
    _atomic_save(copy, destination)
    copy.close()


def _atomic_save(image: Image.Image, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp.png")
    try:
        image.save(temporary, format="PNG")
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)


def _asset_map(report: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    return {
        str(row.get("id", "")): row
        for row in tuple(report.get("assets", ()) or ())
        if isinstance(row, Mapping)
    }


def _capture_map(asset: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    return {
        str(row.get("name", "")): row
        for row in tuple(asset.get("captures", ()) or ())
        if isinstance(row, Mapping)
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["build_visual_audit_composites"]
