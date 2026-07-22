from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from cdmw.core.texture_native import ensure_native_dds_preview_png
from tools.mesh_harness.material_profile_corpus import _dds_header_row


SOURCE_BOARD_SCHEMA = "cdmw_mesh_visual_audit_source_board_v2"


def build_source_material_boards(
    asset_id: str,
    resolved_textures: Sequence[Mapping[str, object]],
    material_state: Mapping[str, object],
    output_root: Path,
) -> dict[str, object]:
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:  # pragma: no cover - environment contract
        raise RuntimeError(f"Pillow is required for PAC source boards: {exc}") from exc

    asset_root = Path(output_root).resolve() / _safe_component(asset_id)
    asset_root.mkdir(parents=True, exist_ok=True)
    decoded_root = asset_root / "decoded"
    decoded_root.mkdir(parents=True, exist_ok=True)
    analyses: list[dict[str, object]] = []
    by_submesh: defaultdict[int, list[dict[str, object]]] = defaultdict(list)
    for ordinal, row in enumerate(resolved_textures):
        analysis = _analyze_texture(row, decoded_root, ordinal=ordinal)
        analyses.append(analysis)
        by_submesh[_safe_int(row.get("submesh_index", -1), -1)].append(analysis)

    material_rows = [
        dict(row)
        for row in tuple(material_state.get("submeshes", ()) or ())
        if isinstance(row, Mapping)
    ]
    boards: list[dict[str, object]] = []
    for fallback_index, material in enumerate(material_rows):
        submesh_index = _safe_int(material.get("submesh_index", fallback_index), fallback_index)
        texture_rows = by_submesh.get(submesh_index, [])
        board_path = asset_root / f"submesh-{submesh_index:03d}-source-board.png"
        _draw_source_board(
            board_path,
            asset_id=asset_id,
            submesh_index=submesh_index,
            material=material,
            textures=texture_rows,
            image_type=Image,
            draw_type=ImageDraw,
        )
        source_contract = material.get("source_contract", {})
        boards.append(
            {
                "submesh_index": submesh_index,
                "material_name": str(material.get("material_name", "") or ""),
                "path": str(board_path),
                "sha256": _sha256_file(board_path),
                "texture_count": len(texture_rows),
                "source_contract_schema": str(
                    source_contract.get("schema", "") if isinstance(source_contract, Mapping) else ""
                ),
                "binding_conservation": dict(
                    material.get("binding_conservation", {})
                    if isinstance(material.get("binding_conservation"), Mapping)
                    else {}
                ),
            }
        )
    manifest = {
        "schema": SOURCE_BOARD_SCHEMA,
        "asset_id": asset_id,
        "boards": boards,
        "textures": analyses,
    }
    manifest_path = asset_root / "source-board-manifest.json"
    _atomic_write_json(manifest_path, manifest)
    return {**manifest, "manifest_path": str(manifest_path)}


def _analyze_texture(
    row: Mapping[str, object],
    decoded_root: Path,
    *,
    ordinal: int,
) -> dict[str, object]:
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - environment contract
        raise RuntimeError(f"Pillow is required for PAC source boards: {exc}") from exc
    source = Path(str(row.get("source_path", "") or ""))
    semantic = str(row.get("semantic", "") or "material").casefold()
    slot_kind = "base" if semantic in {"base", "albedo", "color", "diffuse"} else "normal" if semantic == "normal" else "material"
    preview = None
    decode_error = ""
    if source.is_file():
        try:
            preview = ensure_native_dds_preview_png(
                source,
                max_dimension=512,
                slot_kind=slot_kind,
                srgb="auto",
                normal_space="auto",
                timeout_seconds=60.0,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            decode_error = f"{type(exc).__name__}: {exc}"
    if preview is None or not Path(preview).is_file():
        decode_error = decode_error or "native DDS preview unavailable"
    decoded_copy = decoded_root / f"{ordinal:03d}-{_safe_component(source.stem or semantic)}.png"
    channel_stats: dict[str, object] = {}
    alpha_coverage: dict[str, object] = {}
    if not decode_error:
        with Image.open(preview) as raw:
            image = raw.convert("RGBA")
            image.save(decoded_copy, "PNG")
            channel_stats = {
                name: _channel_statistics(image.getchannel(name))
                for name in ("R", "G", "B", "A")
            }
            alpha = image.getchannel("A")
            histogram = alpha.histogram()
            total = max(1, sum(histogram))
            alpha_coverage = {
                "transparent_fraction": round(histogram[0] / total, 8),
                "below_half_fraction": round(sum(histogram[:128]) / total, 8),
                "nonopaque_fraction": round(sum(histogram[:255]) / total, 8),
            }
    dds = _dds_header_row(source) if source.is_file() else {"dds_header_status": "missing"}
    return {
        "submesh_index": _safe_int(row.get("submesh_index", -1), -1),
        "archive_path": str(row.get("archive_path", "") or "").replace("\\", "/"),
        "archive_provenance": dict(row.get("archive_provenance", {}) or {}),
        "source_path": str(source),
        "source_bytes": int(row.get("source_bytes", 0) or (source.stat().st_size if source.is_file() else 0)),
        "source_sha256": str(row.get("source_sha256", "") or (_sha256_file(source) if source.is_file() else "")),
        "decoded_path": str(decoded_copy) if decoded_copy.is_file() else "",
        "decoded_sha256": _sha256_file(decoded_copy) if decoded_copy.is_file() else "",
        "decode_error": decode_error,
        "dds": dds,
        "semantic": semantic,
        "parameter_name": str(row.get("parameter_name", "") or ""),
        "owner_slot_index": row.get("owner_slot_index"),
        "owner_wrapper_item_id": str(row.get("owner_wrapper_item_id", "") or ""),
        "binding_authority": str(row.get("binding_authority", "") or ""),
        "binding_disposition": str(row.get("binding_disposition", "") or ""),
        "source_kind": str(row.get("source_kind", "") or ""),
        "channel_statistics": channel_stats,
        "alpha_coverage": alpha_coverage,
    }


def _channel_statistics(channel: object) -> dict[str, object]:
    histogram = channel.histogram()
    total = max(1, sum(histogram))
    mean = sum(index * count for index, count in enumerate(histogram)) / total

    def quantile(fraction: float) -> int:
        target = max(0, int((total - 1) * fraction))
        seen = 0
        for value, count in enumerate(histogram):
            seen += count
            if seen > target:
                return value
        return 255

    nonzero = [index for index, count in enumerate(histogram) if count]
    return {
        "min": nonzero[0] if nonzero else 0,
        "max": nonzero[-1] if nonzero else 0,
        "mean": round(mean, 6),
        "q10": quantile(0.10),
        "q50": quantile(0.50),
        "q90": quantile(0.90),
    }


def _draw_source_board(
    output_path: Path,
    *,
    asset_id: str,
    submesh_index: int,
    material: Mapping[str, object],
    textures: Sequence[Mapping[str, object]],
    image_type: object,
    draw_type: object,
) -> None:
    panel = 176
    text_width = 500
    header_height = 150
    row_height = panel + 84
    height = header_height + max(1, len(textures)) * row_height
    width = text_width + panel * 5
    board = image_type.new("RGB", (width, height), (17, 20, 25))
    draw = draw_type.Draw(board)
    shader = str(material.get("shader_family", "") or "unknown")
    name = str(material.get("material_name", "") or "")
    draw.text((14, 12), f"PAC source authority | {asset_id} | submesh {submesh_index}", fill=(242, 244, 248))
    draw.text((14, 36), f"material={name or '<unnamed>'} shader={shader}", fill=(188, 205, 228))
    conservation = material.get("binding_conservation", {})
    conserved = conservation.get("conserved") if isinstance(conservation, Mapping) else None
    draw.text((14, 60), f"binding conservation={conserved}", fill=(135, 225, 168) if conserved else (255, 130, 120))
    _draw_tint_swatches(draw, material, origin=(14, 88))
    headings = ("decoded", "R", "G", "B", "A")
    for index, heading in enumerate(headings):
        draw.text((text_width + index * panel + 8, 126), heading, fill=(220, 225, 232))

    for row_index, texture in enumerate(textures or ({"decode_error": "no resolved DDS for this submesh"},)):
        y = header_height + row_index * row_height
        parameter = str(texture.get("parameter_name", "") or "<fallback>")
        semantic = str(texture.get("semantic", "") or "")
        disposition = str(texture.get("binding_disposition", "") or "")
        draw.text((14, y + 8), f"{parameter} | {semantic} | {disposition}", fill=(235, 238, 244))
        draw.text((14, y + 30), str(texture.get("archive_path", "") or "")[:76], fill=(172, 184, 202))
        dds = texture.get("dds", {}) if isinstance(texture.get("dds"), Mapping) else {}
        draw.text(
            (14, y + 52),
            f"{dds.get('source_width', '?')}x{dds.get('source_height', '?')} mips={dds.get('source_mip_count', '?')} {dds.get('source_format', '')}",
            fill=(172, 184, 202),
        )
        draw.text((14, y + 74), f"sha256={str(texture.get('source_sha256', ''))[:32]}", fill=(145, 158, 178))
        decoded_path = Path(str(texture.get("decoded_path", "") or ""))
        if not decoded_path.is_file():
            draw.text((14, y + 102), str(texture.get("decode_error", "decode unavailable")), fill=(255, 135, 120))
            continue
        with image_type.open(decoded_path) as raw:
            rgba = raw.convert("RGBA")
            panels = [rgba.convert("RGB")]
            for channel_name in ("R", "G", "B", "A"):
                gray = rgba.getchannel(channel_name)
                panels.append(image_type.merge("RGB", (gray, gray, gray)))
            for panel_index, panel_image in enumerate(panels):
                panel_image.thumbnail((panel - 12, panel - 12))
                x = text_width + panel_index * panel + (panel - panel_image.width) // 2
                board.paste(panel_image, (x, y + 4))
        stats = texture.get("channel_statistics", {})
        for channel_index, channel_name in enumerate(("R", "G", "B", "A"), 1):
            channel = stats.get(channel_name, {}) if isinstance(stats, Mapping) else {}
            draw.text(
                (text_width + channel_index * panel + 5, y + panel + 6),
                f"mean {channel.get('mean', '?')} q10/50/90 {channel.get('q10', '?')}/{channel.get('q50', '?')}/{channel.get('q90', '?')}",
                fill=(176, 188, 204),
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    board.save(temporary, "PNG")
    temporary.replace(output_path)


def _draw_tint_swatches(draw: object, material: Mapping[str, object], *, origin: tuple[int, int]) -> None:
    parameters = material.get("parameters", {})
    if not isinstance(parameters, Mapping):
        return
    x, y = origin
    swatches = []
    for key in ("base_tint_color", "texture_tint", "tint_color", "emissive_color"):
        value = parameters.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 3:
            try:
                rgb = tuple(max(0, min(255, round(float(value[index]) * 255))) for index in range(3))
            except (TypeError, ValueError, OverflowError):
                continue
            swatches.append((key, rgb))
    for key, rgb in swatches:
        draw.rectangle((x, y, x + 34, y + 24), fill=rgb, outline=(230, 232, 236))
        draw.text((x + 42, y + 5), key, fill=(205, 212, 222))
        x += 168


def _safe_component(value: str) -> str:
    normalized = "".join(character if character.isalnum() or character in "-_" else "-" for character in str(value))
    normalized = normalized.strip("-")
    return normalized[:120] or "asset"


def _safe_int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


__all__ = ["SOURCE_BOARD_SCHEMA", "build_source_material_boards"]
