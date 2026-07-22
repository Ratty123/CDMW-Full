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
    strict_evidence = (
        str(corpus.get("schema", "") or "") == "cdmw_mesh_visual_audit_corpus_v2"
    )
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
                strict=strict_evidence,
            )
            comparisons[view] = str(output_path)
        contact_sheet = temporary_root / "contact-sheets" / f"{asset_id}.png"
        _write_contact_sheet(
            tuple(Path(path) for path in comparisons.values()),
            contact_sheet,
            strict=strict_evidence,
        )
        region_rows = _build_material_region_review_sheets(
            asset,
            archive_captures,
            dotnet_row,
            temporary_root / "material-region-sheets" / asset_id,
            strict=strict_evidence,
        )
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
                "candidate_comparison_sha256": {
                    view: _sha256_file(Path(path)) for view, path in comparisons.items()
                },
                "contact_sheet": str(contact_sheet),
                "contact_sheet_sha256": _sha256_file(contact_sheet),
                "material_regions": region_rows,
                "primary_final_png": str(final_path),
                "primary_final_sha256": _sha256_file(final_path),
                "archive_browser_capture_ok": bool(archive_row.get("ok")),
                "mesh_editor_capture_ok": bool(dotnet_row.get("ok")),
            }
        )
    return rows


def _build_material_region_review_sheets(
    asset: Mapping[str, object],
    archive_captures: Mapping[str, Mapping[str, object]],
    dotnet_asset: Mapping[str, object],
    output_root: Path,
    *,
    strict: bool = False,
) -> list[dict[str, object]]:
    source_boards = asset.get("source_boards", {})
    if not isinstance(source_boards, Mapping):
        source_boards = {}
    board_map = {
        int(row.get("submesh_index", -1)): row
        for row in tuple(source_boards.get("boards", ()) or ())
        if isinstance(row, Mapping)
    }
    rows: list[dict[str, object]] = []
    for region in tuple(dotnet_asset.get("material_regions", ()) or ()):
        if not isinstance(region, Mapping):
            continue
        raw_submesh_index = region.get("source_submesh_index", -1)
        submesh_index = int(raw_submesh_index if raw_submesh_index is not None else -1)
        captures = {
            (str(row.get("angle", "")), str(row.get("debug_mode", ""))): row
            for row in tuple(region.get("captures", ()) or ())
            if isinstance(row, Mapping)
        }
        board = board_map.get(submesh_index, {})
        panels: list[tuple[str, Path]] = [
            ("PAC / DDS source board", Path(str(board.get("path", "") or ""))),
            (
                "Archive Browser compatibility (full model)",
                Path(str(archive_captures.get("three-quarter-front", {}).get("path", "") or "")),
            ),
            ("Mesh Editor region front", Path(str(captures.get(("front", "final"), {}).get("path", "") or ""))),
            ("Mesh Editor region oblique", Path(str(captures.get(("oblique", "final"), {}).get("path", "") or ""))),
        ]
        panels.extend(
            (
                f"Diagnostic: {mode}",
                Path(str(captures.get(("oblique", mode), {}).get("path", "") or "")),
            )
            for mode in ("base", "normal", "roughness", "metallic", "specular", "layer_mask")
        )
        output_path = output_root / f"submesh-{submesh_index:03d}.png"
        _write_labeled_grid(
            panels,
            output_path,
            footer=(
                f"{asset.get('asset_id', '')} | submesh {submesh_index} | "
                "PAC source authority; Archive Browser is compatibility evidence only"
            ),
            strict=strict,
        )
        rows.append(
            {
                "source_submesh_index": submesh_index,
                "submesh_name": str(region.get("submesh_name", "") or ""),
                "source_board": str(board.get("path", "") or ""),
                "source_board_sha256": str(board.get("sha256", "") or ""),
                "review_sheet": str(output_path),
                "review_sheet_sha256": _sha256_file(output_path),
                "capture_count": len(captures),
                "binding_conservation": dict(board.get("binding_conservation", {}) or {}),
            }
        )
    return rows


def _write_labeled_grid(
    panels: Sequence[tuple[str, Path]],
    output_path: Path,
    *,
    footer: str,
    strict: bool = False,
) -> None:
    cell_width = 420
    image_height = 360
    label_height = 34
    footer_height = 36
    columns = 3
    rows = (len(panels) + columns - 1) // columns
    canvas = Image.new(
        "RGB",
        (columns * cell_width, rows * (image_height + label_height) + footer_height),
        (13, 16, 20),
    )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, (label, path) in enumerate(panels):
        image = _open_or_error(path, f"Missing: {label}", strict=strict)
        image.thumbnail((cell_width - 12, image_height - 12))
        cell_x = (index % columns) * cell_width
        cell_y = (index // columns) * (image_height + label_height)
        x = cell_x + (cell_width - image.width) // 2
        y = cell_y + label_height + (image_height - image.height) // 2
        canvas.paste(image, (x, y))
        draw.text((cell_x + 8, cell_y + 10), label, fill=(232, 237, 244), font=font)
        image.close()
    draw.text(
        (10, canvas.height - footer_height + 12),
        footer,
        fill=(188, 201, 218),
        font=font,
    )
    _atomic_save(canvas, output_path)
    canvas.close()


def _write_pair(
    left_path: Path,
    right_path: Path,
    output_path: Path,
    *,
    left_label: str,
    right_label: str,
    footer: str,
    strict: bool = False,
) -> None:
    left = _open_or_error(left_path, "Archive Browser capture missing", strict=strict)
    right = _open_or_error(right_path, "Mesh Editor capture missing", strict=strict)
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


def _write_contact_sheet(
    comparisons: Sequence[Path],
    output_path: Path,
    *,
    strict: bool = False,
) -> None:
    images = [
        _open_or_error(path, f"Comparison missing: {path.name}", strict=strict)
        for path in comparisons
    ]
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


def _open_or_error(path: Path, message: str, *, strict: bool = False) -> Image.Image:
    try:
        if path.is_file():
            with Image.open(path) as image:
                return image.convert("RGB")
    except OSError as exc:
        if strict:
            raise ValueError(f"{message}: {path}") from exc
    if strict:
        raise ValueError(f"{message}: {path}")
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
