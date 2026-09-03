from __future__ import annotations

import hashlib
import json
import textwrap
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from cdmw.core.texture_native import ensure_native_dds_preview_png
from tools.mesh_harness.material_profile_corpus import _dds_header_row

SOURCE_BOARD_SCHEMA = "cdmw_mesh_visual_audit_source_board_v2"

_GRAPH_BOARD_HEADER_HEIGHT = 96
_GRAPH_BOARD_PANEL = 176
_GRAPH_BOARD_ROW_GAP = 84
_GRAPH_BOARD_TEXT_WIDTH = 760
_GRAPH_BOARD_WRAP_COLUMNS = 118
# 1,640 x 16,000 stays below common image/GPU dimension limits and Pillow's
# decompression-bomb pixel threshold. Graph-only rows are sharded below this cap.
GRAPH_BOARD_MAX_HEIGHT = 16_000


def build_source_material_boards(
    asset_id: str,
    resolved_textures: Sequence[Mapping[str, object]],
    material_state: Mapping[str, object],
    output_root: Path,
    *,
    decoded_cache_root: Path | None = None,
) -> dict[str, object]:
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:  # pragma: no cover - environment contract
        raise RuntimeError(f"Pillow is required for PAC source boards: {exc}") from exc

    asset_root = Path(output_root).resolve() / _safe_component(asset_id)
    asset_root.mkdir(parents=True, exist_ok=True)
    decoded_root = (
        Path(decoded_cache_root).resolve()
        if decoded_cache_root is not None
        else asset_root / "decoded"
    )
    decoded_root.mkdir(parents=True, exist_ok=True)
    analyses: list[dict[str, object]] = []
    by_submesh: defaultdict[int, list[dict[str, object]]] = defaultdict(list)
    graph_only: list[dict[str, object]] = []
    for ordinal, row in enumerate(resolved_textures):
        analysis = _analyze_texture(row, decoded_root, ordinal=ordinal)
        analyses.append(analysis)
        submesh_indices = tuple(row.get("submesh_indices", ()) or ())
        if not submesh_indices:
            submesh_indices = (_safe_int(row.get("submesh_index", -1), -1),)
        normalized_indices = tuple(
            dict.fromkeys(
                _safe_int(value, -1) for value in submesh_indices
            )
        )
        visible_indices = tuple(index for index in normalized_indices if index >= 0)
        for submesh_index in visible_indices:
            by_submesh[submesh_index].append(analysis)
        if not visible_indices:
            graph_only.append(analysis)

    material_rows = [
        dict(row)
        for row in tuple(material_state.get("submeshes", ()) or ())
        if isinstance(row, Mapping)
    ]
    boards: list[dict[str, object]] = []
    for fallback_index, material in enumerate(material_rows):
        submesh_index = _safe_int(
            material.get("submesh_index", fallback_index), fallback_index
        )
        if submesh_index < 0:
            continue
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
                "component_scope_ids": sorted(
                    {
                        str(row.get("component_scope_id", "") or "")
                        for row in texture_rows
                        if str(row.get("component_scope_id", "") or "")
                    },
                    key=str.casefold,
                ),
                "source_contract_schema": str(
                    source_contract.get("schema", "")
                    if isinstance(source_contract, Mapping)
                    else ""
                ),
                "binding_conservation": dict(
                    material.get("binding_conservation", {})
                    if isinstance(material.get("binding_conservation"), Mapping)
                    else {}
                ),
            }
        )
    graph_shards = _shard_graph_textures(
        graph_only,
        max_height=GRAPH_BOARD_MAX_HEIGHT,
    )
    graph_boards: list[dict[str, object]] = []
    shard_count = len(graph_shards)
    for shard_index, texture_rows in enumerate(graph_shards):
        board_path = asset_root / f"graph-source-board-{shard_index:03d}.png"
        _draw_graph_board(
            board_path,
            asset_id=asset_id,
            textures=texture_rows,
            shard_index=shard_index,
            shard_count=shard_count,
            image_type=Image,
            draw_type=ImageDraw,
        )
        graph_boards.append(
            {
                "graph_board_index": shard_index,
                "shard_index": shard_index,
                "shard_count": shard_count,
                "path": str(board_path),
                "sha256": _sha256_file(board_path),
                "texture_count": len(texture_rows),
                "component_scope_ids": sorted(
                    {
                        str(row.get("component_scope_id", "") or "")
                        for row in texture_rows
                        if str(row.get("component_scope_id", "") or "")
                    },
                    key=str.casefold,
                ),
                "source_texture_ordinals": [
                    _safe_int(row.get("source_texture_ordinal"), -1)
                    for row in texture_rows
                ],
                "logical_edges": [
                    _graph_edge_manifest_row(row) for row in texture_rows
                ],
            }
        )
    manifest = {
        "schema": SOURCE_BOARD_SCHEMA,
        "asset_id": asset_id,
        "boards": boards,
        "graph_boards": graph_boards,
        "textures": analyses,
        "materials": material_rows,
        "parameters": [
            dict(row)
            for row in tuple(material_state.get("parameters", ()) or ())
            if isinstance(row, Mapping)
        ],
        "unassigned_parameters": [
            dict(row)
            for row in tuple(material_state.get("unassigned_parameters", ()) or ())
            if isinstance(row, Mapping)
        ],
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
    slot_kind = (
        "base"
        if semantic in {"base", "albedo", "color", "diffuse"}
        else "normal"
        if semantic == "normal"
        else "material"
    )
    source_sha256 = str(
        row.get("source_sha256", "")
        or (_sha256_file(source) if source.is_file() else "")
    )
    decoded_name = (
        f"{source_sha256}-{slot_kind}.png"
        if source_sha256
        else f"{ordinal:03d}-{_safe_component(source.stem or semantic)}.png"
    )
    decoded_copy = decoded_root / decoded_name
    preview = None
    decode_error = ""
    if decoded_copy.is_file():
        preview = decoded_copy
    elif source.is_file():
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
    channel_stats: dict[str, object] = {}
    alpha_coverage: dict[str, object] = {}
    if not decode_error:
        image = _load_source_board_rgba(Path(preview), image_type=Image)
        if Path(preview) != decoded_copy and not decoded_copy.is_file():
            temporary = decoded_copy.with_name(f".{decoded_copy.name}.tmp.png")
            try:
                image.save(temporary, "PNG")
                try:
                    temporary.replace(decoded_copy)
                except FileExistsError:
                    pass
            finally:
                temporary.unlink(missing_ok=True)
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
    dds = (
        _dds_header_row(source)
        if source.is_file()
        else {"dds_header_status": "missing"}
    )
    return {
        "source_texture_ordinal": ordinal,
        "submesh_index": _safe_int(row.get("submesh_index", -1), -1),
        "submesh_indices": [
            _safe_int(value, -1)
            for value in tuple(row.get("submesh_indices", ()) or ())
        ],
        "archive_path": str(row.get("archive_path", "") or "").replace("\\", "/"),
        "declared_archive_path": str(
            row.get("declared_archive_path", "")
            or row.get("archive_path", "")
            or ""
        ).replace("\\", "/"),
        "resolved_archive_path": str(
            row.get("resolved_archive_path", "")
            or row.get("archive_path", "")
            or ""
        ).replace("\\", "/"),
        "source_resolution": str(row.get("source_resolution", "") or ""),
        "source_resolution_detail": str(
            row.get("source_resolution_detail", "") or ""
        ),
        "declared_source_missing": row.get("declared_source_missing") is True,
        "archive_provenance": dict(row.get("archive_provenance", {}) or {}),
        "source_path": str(source),
        "source_bytes": int(
            row.get("source_bytes", 0)
            or (source.stat().st_size if source.is_file() else 0)
        ),
        "source_sha256": source_sha256,
        "decoded_path": str(decoded_copy) if decoded_copy.is_file() else "",
        "decoded_sha256": _sha256_file(decoded_copy) if decoded_copy.is_file() else "",
        "decode_error": decode_error,
        "dds": dds,
        "semantic": semantic,
        "parameter_name": str(row.get("parameter_name", "") or ""),
        "parameter_kind": str(row.get("parameter_kind", "") or ""),
        "parameter_tag": str(row.get("parameter_tag", "") or ""),
        "parameter_item_id": str(row.get("parameter_item_id", "") or ""),
        "parameter_index": row.get("parameter_index"),
        "owner_slot_index": row.get("owner_slot_index"),
        "owner_wrapper_item_id": str(row.get("owner_wrapper_item_id", "") or ""),
        "material_wrapper_index": row.get("material_wrapper_index"),
        "component_scope_id": str(row.get("component_scope_id", "") or ""),
        "representation_sidecar_paths": [
            str(value)
            for value in tuple(row.get("representation_sidecar_paths", ()) or ())
        ],
        "material_name": str(row.get("material_name", "") or ""),
        "shader_family": str(row.get("shader_family", "") or ""),
        "layer_role": str(row.get("layer_role", "") or ""),
        "layer_channel": str(row.get("layer_channel", "") or ""),
        "packed_channels": str(row.get("packed_channels", "") or ""),
        "srgb_mode": str(row.get("srgb_mode", "") or ""),
        "logical_graph_edge": row.get("logical_graph_edge"),
        "binding_authority": str(row.get("binding_authority", "") or ""),
        "binding_disposition": str(row.get("binding_disposition", "") or ""),
        "source_kind": str(row.get("source_kind", "") or ""),
        "channel_statistics": channel_stats,
        "alpha_coverage": alpha_coverage,
    }


def _load_source_board_rgba(
    preview: Path,
    *,
    image_type: object,
    attempts: int = 20,
) -> object:
    """Open a newly decoded preview after its bytes become fully readable."""

    last_error: OSError | None = None
    for attempt in range(max(1, attempts)):
        try:
            with image_type.open(preview) as raw:
                image = raw.convert("RGBA")
                image.load()
                return image.copy()
        except OSError as exc:
            last_error = exc
            if attempt + 1 >= max(1, attempts):
                raise OSError(
                    "Source-board preview remained unreadable after "
                    f"{max(1, attempts)} attempts: {preview}: {exc}"
                ) from exc
            time.sleep(min(0.5, 0.1 * (attempt + 1)))
    assert last_error is not None
    raise last_error


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


def _graph_edge_manifest_row(texture: Mapping[str, object]) -> dict[str, object]:
    stats = texture.get("channel_statistics", {})
    decoded_channels = [
        channel
        for channel in ("R", "G", "B", "A")
        if isinstance(stats, Mapping) and isinstance(stats.get(channel), Mapping)
    ]
    return {
        "source_texture_ordinal": _safe_int(
            texture.get("source_texture_ordinal"), -1
        ),
        "component_scope_id": str(texture.get("component_scope_id", "") or ""),
        "owner_wrapper_item_id": str(
            texture.get("owner_wrapper_item_id", "") or ""
        ),
        "owner_slot_index": texture.get("owner_slot_index"),
        "material_wrapper_index": texture.get("material_wrapper_index"),
        "parameter_name": str(texture.get("parameter_name", "") or ""),
        "declared_archive_path": str(
            texture.get("declared_archive_path", "")
            or texture.get("archive_path", "")
            or ""
        ),
        "resolved_archive_path": str(
            texture.get("resolved_archive_path", "")
            or texture.get("archive_path", "")
            or ""
        ),
        "source_resolution": str(texture.get("source_resolution", "") or ""),
        "source_sha256": str(texture.get("source_sha256", "") or ""),
        "decoded_channels": decoded_channels,
    }


def _graph_texture_lines(texture: Mapping[str, object]) -> list[str]:
    dds = texture.get("dds", {})
    dds = dds if isinstance(dds, Mapping) else {}
    stats = texture.get("channel_statistics", {})
    decoded_channels = "/".join(
        channel
        for channel in ("R", "G", "B", "A")
        if isinstance(stats, Mapping) and isinstance(stats.get(channel), Mapping)
    )
    owner = str(texture.get("owner_wrapper_item_id", "") or "<unknown>")
    owner_slot = texture.get("owner_slot_index")
    parameter = str(texture.get("parameter_name", "") or "<unnamed>")
    parameter_kind = str(texture.get("parameter_kind", "") or "unknown")
    declared = str(
        texture.get("declared_archive_path", "")
        or texture.get("archive_path", "")
        or "<missing>"
    )
    resolved = str(
        texture.get("resolved_archive_path", "")
        or texture.get("archive_path", "")
        or "<missing>"
    )
    resolution = str(texture.get("source_resolution", "") or "<unspecified>")
    resolution_detail = str(texture.get("source_resolution_detail", "") or "")
    detail_suffix = f" | detail={resolution_detail}" if resolution_detail else ""
    role = str(texture.get("layer_role", "") or "")
    channel = str(texture.get("layer_channel", "") or "")
    return [
        f"component scope={texture.get('component_scope_id', '') or '<missing>'}",
        f"owner={owner} owner_slot={owner_slot}",
        (
            f"parameter={parameter} kind={parameter_kind} "
            f"item={texture.get('parameter_item_id')} index={texture.get('parameter_index')}"
        ),
        (
            f"semantic={texture.get('semantic', '')} role={role} channel={channel} "
            f"packed={texture.get('packed_channels', '')} srgb={texture.get('srgb_mode', '')}"
        ),
        f"declared archive source={declared}",
        f"resolved archive source={resolved}",
        f"archive resolution={resolution}{detail_suffix}",
        f"decoded channels={decoded_channels or '<unavailable>'}",
        (
            f"DDS={dds.get('source_width', '?')}x{dds.get('source_height', '?')} "
            f"mips={dds.get('source_mip_count', '?')} "
            f"format={dds.get('source_format', '')}"
        ),
        f"source sha256={texture.get('source_sha256', '') or '<missing>'!s}",
    ]


def _wrapped_graph_texture_lines(texture: Mapping[str, object]) -> list[str]:
    wrapped: list[str] = []
    for line in _graph_texture_lines(texture):
        wrapped.extend(
            textwrap.wrap(
                line,
                width=_GRAPH_BOARD_WRAP_COLUMNS,
                break_long_words=True,
                break_on_hyphens=False,
            )
            or [""]
        )
    return wrapped


def _graph_texture_row_height(texture: Mapping[str, object]) -> int:
    text_height = 24 + len(_wrapped_graph_texture_lines(texture)) * 18
    return max(_GRAPH_BOARD_PANEL + _GRAPH_BOARD_ROW_GAP, text_height)


def _shard_graph_textures(
    textures: Sequence[Mapping[str, object]],
    *,
    max_height: int,
) -> list[list[Mapping[str, object]]]:
    if not textures:
        return []
    if max_height <= _GRAPH_BOARD_HEADER_HEIGHT:
        raise ValueError("Graph-board height cap cannot fit its header.")
    shards: list[list[Mapping[str, object]]] = []
    current: list[Mapping[str, object]] = []
    current_height = _GRAPH_BOARD_HEADER_HEIGHT
    for texture in textures:
        row_height = _graph_texture_row_height(texture)
        if _GRAPH_BOARD_HEADER_HEIGHT + row_height > max_height:
            raise ValueError(
                "One graph-only PAC texture row exceeds the graph-board height cap."
            )
        if current and current_height + row_height > max_height:
            shards.append(current)
            current = []
            current_height = _GRAPH_BOARD_HEADER_HEIGHT
        current.append(texture)
        current_height += row_height
    if current:
        shards.append(current)
    return shards


def _draw_graph_board(
    output_path: Path,
    *,
    asset_id: str,
    textures: Sequence[Mapping[str, object]],
    shard_index: int,
    shard_count: int,
    image_type: object,
    draw_type: object,
) -> None:
    row_heights = [_graph_texture_row_height(texture) for texture in textures]
    height = _GRAPH_BOARD_HEADER_HEIGHT + sum(row_heights)
    if height > GRAPH_BOARD_MAX_HEIGHT:
        raise ValueError(
            f"Graph source board would exceed {GRAPH_BOARD_MAX_HEIGHT}px: {height}px"
        )
    width = _GRAPH_BOARD_TEXT_WIDTH + _GRAPH_BOARD_PANEL * 5
    board = image_type.new("RGB", (width, height), (17, 20, 25))
    draw = draw_type.Draw(board)
    draw.text(
        (14, 12),
        f"PAC logical graph source authority | {asset_id}",
        fill=(242, 244, 248),
    )
    draw.text(
        (14, 34),
        (
            "no visible-submesh assignment | no visible-region association | "
            f"shard {shard_index + 1}/{shard_count}"
        ),
        fill=(255, 193, 112),
    )
    headings = ("decoded", "R", "G", "B", "A")
    for index, heading in enumerate(headings):
        draw.text(
            (_GRAPH_BOARD_TEXT_WIDTH + index * _GRAPH_BOARD_PANEL + 8, 70),
            heading,
            fill=(220, 225, 232),
        )

    y = _GRAPH_BOARD_HEADER_HEIGHT
    for texture, row_height in zip(textures, row_heights, strict=True):
        for line_index, line in enumerate(_wrapped_graph_texture_lines(texture)):
            draw.text(
                (14, y + 8 + line_index * 18),
                line,
                fill=(190, 203, 222),
            )
        decoded_path = Path(str(texture.get("decoded_path", "") or ""))
        if decoded_path.is_file():
            with image_type.open(decoded_path) as raw:
                rgba = raw.convert("RGBA")
                panels = [rgba.convert("RGB")]
                for channel_name in ("R", "G", "B", "A"):
                    gray = rgba.getchannel(channel_name)
                    panels.append(image_type.merge("RGB", (gray, gray, gray)))
                for panel_index, panel_image in enumerate(panels):
                    panel_image.thumbnail(
                        (_GRAPH_BOARD_PANEL - 12, _GRAPH_BOARD_PANEL - 12)
                    )
                    x = (
                        _GRAPH_BOARD_TEXT_WIDTH
                        + panel_index * _GRAPH_BOARD_PANEL
                        + (_GRAPH_BOARD_PANEL - panel_image.width) // 2
                    )
                    board.paste(panel_image, (x, y + 4))
            stats = texture.get("channel_statistics", {})
            for channel_index, channel_name in enumerate(("R", "G", "B", "A"), 1):
                channel_stats = (
                    stats.get(channel_name, {}) if isinstance(stats, Mapping) else {}
                )
                draw.text(
                    (
                        _GRAPH_BOARD_TEXT_WIDTH
                        + channel_index * _GRAPH_BOARD_PANEL
                        + 5,
                        y + _GRAPH_BOARD_PANEL + 6,
                    ),
                    (
                        f"mean {channel_stats.get('mean', '?')} q10/50/90 "
                        f"{channel_stats.get('q10', '?')}/"
                        f"{channel_stats.get('q50', '?')}/"
                        f"{channel_stats.get('q90', '?')}"
                    ),
                    fill=(176, 188, 204),
                )
        else:
            draw.text(
                (_GRAPH_BOARD_TEXT_WIDTH + 10, y + 12),
                str(texture.get("decode_error", "decode unavailable")),
                fill=(255, 135, 120),
            )
        draw.line((0, y + row_height - 1, width, y + row_height - 1), fill=(60, 66, 78))
        y += row_height
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    board.save(temporary, "PNG")
    temporary.replace(output_path)


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
    parameter_lines = _source_parameter_lines(material)
    header_height = 150 + len(parameter_lines) * 18
    row_height = panel + 84
    height = header_height + max(1, len(textures)) * row_height
    width = text_width + panel * 5
    board = image_type.new("RGB", (width, height), (17, 20, 25))
    draw = draw_type.Draw(board)
    shader = str(material.get("shader_family", "") or "unknown")
    name = str(material.get("material_name", "") or "")
    draw.text(
        (14, 12),
        f"PAC source authority | {asset_id} | submesh {submesh_index}",
        fill=(242, 244, 248),
    )
    draw.text(
        (14, 36),
        f"material={name or '<unnamed>'} shader={shader}",
        fill=(188, 205, 228),
    )
    conservation = material.get("binding_conservation", {})
    conserved = (
        conservation.get("conserved") if isinstance(conservation, Mapping) else None
    )
    draw.text(
        (14, 60),
        f"binding conservation={conserved}",
        fill=(135, 225, 168) if conserved else (255, 130, 120),
    )
    _draw_tint_swatches(draw, material, origin=(14, 88))
    for line_index, line in enumerate(parameter_lines):
        draw.text(
            (14, 126 + line_index * 18),
            line[:180],
            fill=(168, 181, 202),
        )
    headings = ("decoded", "R", "G", "B", "A")
    for index, heading in enumerate(headings):
        draw.text(
            (text_width + index * panel + 8, header_height - 24),
            heading,
            fill=(220, 225, 232),
        )

    for row_index, texture in enumerate(
        textures or ({"decode_error": "no resolved DDS for this submesh"},)
    ):
        y = header_height + row_index * row_height
        parameter = str(texture.get("parameter_name", "") or "<fallback>")
        semantic = str(texture.get("semantic", "") or "")
        disposition = str(texture.get("binding_disposition", "") or "")
        draw.text(
            (14, y + 8),
            f"{parameter} | {semantic} | {disposition}",
            fill=(235, 238, 244),
        )
        draw.text(
            (14, y + 30),
            str(texture.get("archive_path", "") or "")[:76],
            fill=(172, 184, 202),
        )
        dds = texture.get("dds", {}) if isinstance(texture.get("dds"), Mapping) else {}
        draw.text(
            (14, y + 52),
            f"{dds.get('source_width', '?')}x{dds.get('source_height', '?')} mips={dds.get('source_mip_count', '?')} {dds.get('source_format', '')}",
            fill=(172, 184, 202),
        )
        draw.text(
            (14, y + 74),
            f"sha256={str(texture.get('source_sha256', ''))[:32]}",
            fill=(145, 158, 178),
        )
        decoded_path = Path(str(texture.get("decoded_path", "") or ""))
        if not decoded_path.is_file():
            draw.text(
                (14, y + 102),
                str(texture.get("decode_error", "decode unavailable")),
                fill=(255, 135, 120),
            )
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


def _draw_tint_swatches(
    draw: object, material: Mapping[str, object], *, origin: tuple[int, int]
) -> None:
    parameters = material.get("parameters", {})
    if not isinstance(parameters, Mapping):
        return
    x, y = origin
    swatches = []
    for key in ("base_tint_color", "texture_tint", "tint_color", "emissive_color"):
        value = parameters.get(key)
        if (
            isinstance(value, Sequence)
            and not isinstance(value, (str, bytes))
            and len(value) >= 3
        ):
            try:
                rgb = tuple(
                    max(0, min(255, round(float(value[index]) * 255)))
                    for index in range(3)
                )
            except (TypeError, ValueError, OverflowError):
                continue
            swatches.append((key, rgb))
    for row in tuple(material.get("color_parameters", ()) or ()):
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("name", "") or "")
        value = str(row.get("value", "") or "").strip()
        if not key or len(value) not in {7, 9} or not value.startswith("#"):
            continue
        try:
            rgb = tuple(int(value[offset : offset + 2], 16) for offset in (1, 3, 5))
        except ValueError:
            continue
        swatches.append((key, rgb))
    swatches = list(dict.fromkeys(swatches))[:6]
    for key, rgb in swatches:
        draw.rectangle((x, y, x + 34, y + 24), fill=rgb, outline=(230, 232, 236))
        draw.text((x + 42, y + 5), key, fill=(205, 212, 222))
        x += 168


def _source_parameter_lines(material: Mapping[str, object]) -> list[str]:
    lines: list[str] = []
    for raw in tuple(material.get("pac_xml_parameters", ()) or ()):
        if not isinstance(raw, Mapping):
            continue
        component_scope = str(raw.get("component_scope_id", "") or "?")
        owner = str(raw.get("owner_wrapper_item_id", "") or "?")
        kind = str(raw.get("parameter_kind", "") or "unknown")
        name = str(raw.get("parameter_name", "") or "<unnamed>")
        value = raw.get("integer_value")
        if value is None:
            value = raw.get("numeric_value")
        if value is None:
            value = raw.get("texture_path") or raw.get("value", "")
        role = str(raw.get("role", "") or "")
        channel = str(raw.get("layer_channel", "") or "")
        suffix = "/".join(part for part in (role, channel) if part)
        lines.append(
            f"scope={component_scope} owner={owner} {kind} {name}={value}"
            + (f" [{suffix}]" if suffix else "")
        )
    return lines


def _safe_component(value: str) -> str:
    normalized = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in str(value)
    )
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
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


__all__ = ["SOURCE_BOARD_SCHEMA", "build_source_material_boards"]
