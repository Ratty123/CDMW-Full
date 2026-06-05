from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from cdmw.core.model_preview import _build_vertex_normals, _normalize_model_meshes
from cdmw.models import ModelPreviewData, ModelPreviewMesh


PAT_MAGIC = b"PAR "
VERTEX_STRIDE = 32
_EXPORT_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MATERIAL_RE = re.compile(rb"([A-Za-z0-9_./ -]+?_mat)")
_TEXTURE_RE = re.compile(rb"([A-Za-z0-9_./ -]+?\.(?:tga|dds))", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PatDrawRecord:
    lod_index: int
    material_id: int
    flags: int
    first_index: int
    index_count: int


@dataclass(frozen=True, slots=True)
class PatMaterial:
    name: str
    textures: tuple[str, ...] = ()
    resolved_textures: tuple[Path, ...] = ()

    @property
    def color_texture(self) -> Path | None:
        color_matches = [
            path
            for path in self.resolved_textures
            if "_color" in path.stem.lower() or "_albedo" in path.stem.lower()
        ]
        if color_matches:
            return color_matches[0]
        return self.resolved_textures[0] if self.resolved_textures else None


@dataclass(frozen=True, slots=True)
class PatMesh:
    source_path: Path
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    lod_vertex_counts: tuple[int, ...]
    lod_index_counts: tuple[int, ...]
    lod_draw_counts: tuple[int, ...]
    vertices: tuple[tuple[float, float, float], ...]
    texture_coordinates: tuple[tuple[float, float], ...]
    indices: tuple[int, ...]
    draws: tuple[PatDrawRecord, ...]
    materials: tuple[PatMaterial, ...]
    tail_size: int
    meshinfo_path: Path | None = None
    meshinfo_strings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PatValidationResult:
    path: Path
    ok: bool
    reason: str = ""
    vertex_count: int = 0
    index_count: int = 0
    draw_count: int = 0
    material_count: int = 0


@dataclass(frozen=True, slots=True)
class PatBatchResult:
    valid: int = 0
    invalid: int = 0
    exported: int = 0
    results: tuple[PatValidationResult, ...] = field(default_factory=tuple)


class PatDecodeError(ValueError):
    pass


def decode_pat(path: Path | str, *, texture_root: Path | str | None = None) -> PatMesh:
    source_path = Path(path)
    data = source_path.read_bytes()
    return decode_pat_bytes(
        data,
        str(source_path),
        source_path=source_path,
        texture_root=texture_root,
    )


def decode_pat_bytes(
    data: bytes,
    virtual_path: str,
    *,
    source_path: Path | None = None,
    texture_root: Path | str | None = None,
) -> PatMesh:
    source_path = source_path or Path(virtual_path)
    if len(data) < 4:
        raise PatDecodeError(f"{source_path.name}: payload too short")
    if data[:4] != PAT_MAGIC:
        magic = data[:4].decode("latin1", errors="replace")
        raise PatDecodeError(f"{source_path.name}: unsupported magic {magic!r}")
    if len(data) < 48:
        raise PatDecodeError(f"{source_path.name}: payload too short")

    bbox_min = _unpack_float3(data, 16)
    bbox_max = _unpack_float3(data, 28)
    lod_count = _unpack_u32(data, 40)
    if not 1 <= lod_count <= 16:
        raise PatDecodeError(f"{source_path.name}: invalid LOD count {lod_count}")

    vertex_table_offset = 48
    vertex_start = vertex_table_offset + lod_count * 4
    if vertex_start > len(data):
        raise PatDecodeError(f"{source_path.name}: truncated vertex LOD table")

    lod_vertex_counts = _unpack_u32_tuple(data, vertex_table_offset, lod_count)
    _require_monotonic(lod_vertex_counts, f"{source_path.name}: vertex LOD counts")
    vertex_count = lod_vertex_counts[-1]
    vertex_end = vertex_start + vertex_count * VERTEX_STRIDE
    if vertex_end > len(data):
        raise PatDecodeError(f"{source_path.name}: vertex buffer exceeds file size")

    index_table_offset = vertex_end
    index_table_count = lod_count + 1
    index_start = index_table_offset + index_table_count * 4
    if index_start > len(data):
        raise PatDecodeError(f"{source_path.name}: truncated index LOD table")

    index_offsets = _unpack_u32_tuple(data, index_table_offset, index_table_count)
    _require_monotonic(index_offsets, f"{source_path.name}: index LOD offsets", starts_at_zero=True)
    index_count = index_offsets[-1]
    index_end = index_start + index_count * 2
    if index_end > len(data):
        raise PatDecodeError(f"{source_path.name}: index buffer exceeds file size")

    draw_table_offset = index_end
    draw_start = draw_table_offset + index_table_count * 4
    if draw_start > len(data):
        raise PatDecodeError(f"{source_path.name}: truncated draw LOD table")

    draw_offsets = _unpack_u32_tuple(data, draw_table_offset, index_table_count)
    _require_monotonic(draw_offsets, f"{source_path.name}: draw LOD offsets", starts_at_zero=True)
    draw_count = draw_offsets[-1]
    draw_end = draw_start + draw_count * 16
    if draw_end > len(data):
        raise PatDecodeError(f"{source_path.name}: draw buffer exceeds file size")

    vertices = tuple(_decode_vertex_position(data, vertex_start + i * VERTEX_STRIDE, bbox_min, bbox_max) for i in range(vertex_count))
    texture_coordinates = tuple(_decode_vertex_uv(data, vertex_start + i * VERTEX_STRIDE) for i in range(vertex_count))
    indices = _unpack_u16_tuple(data, index_start, index_count)
    draws = tuple(_decode_draws(data, draw_start, draw_offsets))
    materials = tuple(_decode_materials(data[draw_end:], Path(texture_root) if texture_root else _default_texture_root(source_path)))
    meshinfo_path = _matching_meshinfo_path(source_path)
    meshinfo_strings = tuple(_extract_printable_strings(meshinfo_path.read_bytes(), min_length=4)) if meshinfo_path else ()

    return PatMesh(
        source_path=source_path,
        bbox_min=bbox_min,
        bbox_max=bbox_max,
        lod_vertex_counts=lod_vertex_counts,
        lod_index_counts=tuple(index_offsets[i + 1] - index_offsets[i] for i in range(lod_count)),
        lod_draw_counts=tuple(draw_offsets[i + 1] - draw_offsets[i] for i in range(lod_count)),
        vertices=vertices,
        texture_coordinates=texture_coordinates,
        indices=indices,
        draws=draws,
        materials=materials,
        tail_size=len(data) - draw_end,
        meshinfo_path=meshinfo_path,
        meshinfo_strings=meshinfo_strings,
    )


def build_pat_model_preview(
    data: bytes,
    virtual_path: str,
    *,
    lod_index: int = 0,
    texture_root: Path | str | None = None,
) -> ModelPreviewData:
    mesh = decode_pat_bytes(data, virtual_path, texture_root=texture_root)
    selected_lod = max(0, min(len(mesh.lod_vertex_counts) - 1, int(lod_index)))
    lod_vertex_end = mesh.lod_vertex_counts[selected_lod]
    lod_index_base = sum(mesh.lod_index_counts[:selected_lod])
    preview_meshes: list[ModelPreviewMesh] = []
    for draw_index, draw in enumerate(draw for draw in mesh.draws if draw.lod_index == selected_lod):
        first = lod_index_base + draw.first_index
        last = min(first + draw.index_count, len(mesh.indices))
        draw_indices = list(mesh.indices[first:last])
        if len(draw_indices) < 3:
            continue
        used_vertex_indices = sorted({index for index in draw_indices if 0 <= index < lod_vertex_end})
        if len(used_vertex_indices) < 3:
            continue
        remap = {source_index: new_index for new_index, source_index in enumerate(used_vertex_indices)}
        remapped_indices = [remap[index] for index in draw_indices if index in remap]
        source_face_indices = list(range(len(remapped_indices) // 3))
        material = mesh.materials[draw.material_id] if 0 <= draw.material_id < len(mesh.materials) else None
        material_name = material.name if material is not None else f"material_{draw.material_id:03d}"
        texture_name = _preview_color_texture_name(material)
        preview_meshes.append(
            ModelPreviewMesh(
                material_name=material_name,
                texture_name=texture_name,
                preview_color=_preview_color_for_index(draw_index),
                positions=[mesh.vertices[index] for index in used_vertex_indices],
                texture_coordinates=[mesh.texture_coordinates[index] for index in used_vertex_indices],
                indices=remapped_indices,
                source_submesh_index=draw_index,
                source_vertex_indices=used_vertex_indices,
                source_face_indices=source_face_indices,
                preview_double_sided=True,
                preview_alpha_mode="cutout",
                preview_role=f"LOD {selected_lod + 1} draw {draw_index + 1}",
            )
        )
    if not preview_meshes:
        raise PatDecodeError(f"{Path(virtual_path).name}: no renderable PAT draw records")

    center, scale = _normalize_model_meshes(preview_meshes)
    for preview_mesh in preview_meshes:
        preview_mesh.normals = _build_vertex_normals(preview_mesh.positions, preview_mesh.indices)

    vertex_count = sum(len(preview_mesh.positions) for preview_mesh in preview_meshes)
    face_count = sum(len(preview_mesh.indices) // 3 for preview_mesh in preview_meshes)
    return ModelPreviewData(
        path=virtual_path,
        format="pat",
        summary=(
            f"{virtual_path}\n"
            f"PAT plant mesh\n"
            f"LOD {selected_lod + 1} of {len(mesh.lod_vertex_counts)}\n"
            f"{vertex_count:,} vertices\n"
            f"{face_count:,} faces"
        ),
        mesh_count=len(preview_meshes),
        vertex_count=vertex_count,
        face_count=face_count,
        lod_index=selected_lod,
        lod_count=len(mesh.lod_vertex_counts),
        normalization_center=center,
        normalization_scale=scale,
        meshes=preview_meshes,
    )


def validate_pat(path: Path | str, *, texture_root: Path | str | None = None) -> PatValidationResult:
    source_path = Path(path)
    try:
        mesh = decode_pat(source_path, texture_root=texture_root)
    except PatDecodeError as exc:
        return PatValidationResult(path=source_path, ok=False, reason=str(exc))
    except OSError as exc:
        return PatValidationResult(path=source_path, ok=False, reason=f"{source_path.name}: {exc}")
    return PatValidationResult(
        path=source_path,
        ok=True,
        vertex_count=len(mesh.vertices),
        index_count=len(mesh.indices),
        draw_count=len(mesh.draws),
        material_count=len(mesh.materials),
    )


def export_pat_to_obj(
    path: Path | str,
    output_dir: Path | str,
    *,
    texture_root: Path | str | None = None,
    copy_textures: bool = False,
) -> tuple[Path, Path]:
    mesh = decode_pat(path, texture_root=texture_root)
    resolved_output_dir = Path(output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stem = _sanitize_name(mesh.source_path.stem, fallback="pat_mesh")
    obj_path = resolved_output_dir / f"{stem}.obj"
    mtl_path = resolved_output_dir / f"{stem}.mtl"

    obj_lines: list[str] = [
        "# Exported by Crimson Desert Mod Workbench PAT decoder",
        f"# Source: {mesh.source_path}",
        f"# Bounds min: {_format_vec(mesh.bbox_min)}",
        f"# Bounds max: {_format_vec(mesh.bbox_max)}",
        f"# LOD vertex counts: {', '.join(str(v) for v in mesh.lod_vertex_counts)}",
        f"# LOD index counts: {', '.join(str(v) for v in mesh.lod_index_counts)}",
        f"mtllib {mtl_path.name}",
        f"o {stem}",
    ]
    obj_lines.extend(f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in mesh.vertices)
    obj_lines.extend(f"vt {u:.6f} {v:.6f}" for u, v in mesh.texture_coordinates)

    material_names = [_material_export_name(material, i) for i, material in enumerate(mesh.materials)]
    if not material_names:
        material_names = ["material_000"]

    for lod_index in range(len(mesh.lod_vertex_counts)):
        lod_index_base = sum(mesh.lod_index_counts[:lod_index])
        lod_draws = [draw for draw in mesh.draws if draw.lod_index == lod_index]
        for draw_index, draw in enumerate(lod_draws):
            group_name = f"lod{lod_index:02d}_draw{draw_index:02d}_mat{draw.material_id:03d}_flags{draw.flags:03d}"
            material_name = material_names[draw.material_id] if 0 <= draw.material_id < len(material_names) else material_names[0]
            obj_lines.append(f"g {group_name}")
            obj_lines.append(f"usemtl {material_name}")
            absolute_first = lod_index_base + draw.first_index
            absolute_last = min(absolute_first + draw.index_count, len(mesh.indices))
            for offset in range(absolute_first, absolute_last - 2, 3):
                a, b, c = mesh.indices[offset], mesh.indices[offset + 1], mesh.indices[offset + 2]
                if _valid_face((a, b, c), len(mesh.vertices)):
                    obj_lines.append(f"f {a + 1}/{a + 1} {b + 1}/{b + 1} {c + 1}/{c + 1}")

    texture_output_dir = resolved_output_dir / f"{stem}_textures"
    mtl_lines = ["# Exported by Crimson Desert Mod Workbench PAT decoder"]
    for index, material_name in enumerate(material_names):
        material = mesh.materials[index] if index < len(mesh.materials) else PatMaterial(name=material_name)
        texture_ref = _export_texture_reference(material, texture_output_dir, copy_textures=copy_textures)
        mtl_lines.extend(
            [
                "",
                f"newmtl {material_name}",
                "Kd 1.000000 1.000000 1.000000",
                "Ka 0.000000 0.000000 0.000000",
                "Ks 0.000000 0.000000 0.000000",
                "d 1.0",
                "illum 2",
                f"# Source material: {material.name}",
            ]
        )
        if material.textures:
            mtl_lines.append(f"# Source textures: {', '.join(material.textures)}")
        if texture_ref:
            mtl_lines.append(f"map_Kd {texture_ref}")

    obj_path.write_text("\n".join(obj_lines) + "\n", encoding="utf-8")
    mtl_path.write_text("\n".join(mtl_lines) + "\n", encoding="utf-8")
    return obj_path, mtl_path


def validate_tree(root: Path | str) -> PatBatchResult:
    paths = sorted(Path(root).rglob("*.pat"))
    results = tuple(validate_pat(path) for path in paths)
    return PatBatchResult(
        valid=sum(1 for result in results if result.ok),
        invalid=sum(1 for result in results if not result.ok),
        results=results,
    )


def export_many(
    paths: Iterable[Path | str],
    output_dir: Path | str,
    *,
    texture_root: Path | str | None = None,
    copy_textures: bool = False,
) -> PatBatchResult:
    results: list[PatValidationResult] = []
    exported = 0
    for path in paths:
        source_path = Path(path)
        try:
            mesh = decode_pat(source_path, texture_root=texture_root)
            export_pat_to_obj(mesh.source_path, output_dir, texture_root=texture_root, copy_textures=copy_textures)
        except PatDecodeError as exc:
            results.append(PatValidationResult(path=source_path, ok=False, reason=str(exc)))
            continue
        except OSError as exc:
            results.append(PatValidationResult(path=source_path, ok=False, reason=f"{source_path.name}: {exc}"))
            continue
        exported += 1
        results.append(
            PatValidationResult(
                path=source_path,
                ok=True,
                vertex_count=len(mesh.vertices),
                index_count=len(mesh.indices),
                draw_count=len(mesh.draws),
                material_count=len(mesh.materials),
            )
        )
    return PatBatchResult(
        valid=sum(1 for result in results if result.ok),
        invalid=sum(1 for result in results if not result.ok),
        exported=exported,
        results=tuple(results),
    )


def write_batch_report(result: PatBatchResult, report_path: Path | str, *, root: Path | str | None = None) -> Path:
    resolved_report_path = Path(report_path)
    resolved_report_path.parent.mkdir(parents=True, exist_ok=True)
    root_path = Path(root).resolve() if root else None
    payload = {
        "valid": result.valid,
        "invalid": result.invalid,
        "exported": result.exported,
        "files": [
            {
                "path": _relative_or_absolute(item.path, root_path),
                "ok": item.ok,
                "reason": item.reason,
                "vertex_count": item.vertex_count,
                "index_count": item.index_count,
                "draw_count": item.draw_count,
                "material_count": item.material_count,
            }
            for item in result.results
        ],
    }
    resolved_report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return resolved_report_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and export Crimson Desert .pat plant meshes.")
    parser.add_argument("paths", nargs="+", type=Path, help="One or more .pat files or folders containing .pat files.")
    parser.add_argument("--output-dir", type=Path, default=Path("pat_exports"), help="OBJ/MTL output folder.")
    parser.add_argument("--report", type=Path, default=None, help="Optional JSON validation/export report.")
    parser.add_argument("--validate-only", action="store_true", help="Parse files and report status without writing OBJ/MTL.")
    parser.add_argument("--copy-textures", action="store_true", help="Copy resolved DDS textures next to exported OBJ files.")
    parser.add_argument("--texture-root", type=Path, default=None, help="Optional texture folder override.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    files = _expand_pat_inputs(args.paths)
    if not files:
        parser.error("no .pat files found")
    if args.validate_only:
        results = [validate_pat(path, texture_root=args.texture_root) for path in files]
        result = PatBatchResult(
            valid=sum(1 for item in results if item.ok),
            invalid=sum(1 for item in results if not item.ok),
            results=tuple(results),
        )
    else:
        result = export_many(files, args.output_dir, texture_root=args.texture_root, copy_textures=args.copy_textures)
    if args.report:
        write_batch_report(result, args.report, root=_common_parent(files))
    print(f"PAT files: valid={result.valid} invalid={result.invalid} exported={result.exported}")
    for item in result.results:
        if not item.ok:
            print(f"INVALID {item.path}: {item.reason}")
    return 0 if result.valid else 1


def _decode_vertex_position(
    data: bytes,
    offset: int,
    bbox_min: tuple[float, float, float],
    bbox_max: tuple[float, float, float],
) -> tuple[float, float, float]:
    raw_x, raw_y, raw_z = struct.unpack_from("<3H", data, offset)
    return (
        _decode_axis(raw_x, bbox_min[0], bbox_max[0]),
        _decode_axis(raw_y, bbox_min[1], bbox_max[1]),
        _decode_axis(raw_z, bbox_min[2], bbox_max[2]),
    )


def _decode_vertex_uv(data: bytes, offset: int) -> tuple[float, float]:
    try:
        u, v = struct.unpack_from("<2e", data, offset + 12)
    except struct.error:
        return (0.0, 0.0)
    return (_finite_or_zero(u), _finite_or_zero(v))


def _decode_axis(value: int, axis_min: float, axis_max: float) -> float:
    if not math.isfinite(axis_min) or not math.isfinite(axis_max):
        return 0.0
    return axis_min + ((axis_max - axis_min) * (value / 65535.0))


def _finite_or_zero(value: float) -> float:
    return float(value) if math.isfinite(float(value)) else 0.0


def _preview_color_texture_name(material: PatMaterial | None) -> str:
    if material is None:
        return ""
    for texture in material.textures:
        stem = Path(texture).stem.lower()
        if "_color" in stem or "_albedo" in stem:
            return f"{Path(texture).stem}.dds"
    if material.textures:
        return f"{Path(material.textures[0]).stem}.dds"
    return ""


def _preview_color_for_index(index: int) -> tuple[float, float, float]:
    palette = (
        (0.45, 0.72, 0.38),
        (0.62, 0.45, 0.28),
        (0.48, 0.64, 0.78),
        (0.78, 0.58, 0.36),
        (0.70, 0.52, 0.72),
    )
    return palette[index % len(palette)]


def _decode_draws(data: bytes, draw_start: int, draw_offsets: Sequence[int]) -> Iterable[PatDrawRecord]:
    for lod_index in range(len(draw_offsets) - 1):
        for draw_index in range(draw_offsets[lod_index], draw_offsets[lod_index + 1]):
            material_id, flags, first_index, index_count = struct.unpack_from("<4I", data, draw_start + draw_index * 16)
            yield PatDrawRecord(
                lod_index=lod_index,
                material_id=material_id,
                flags=flags,
                first_index=first_index,
                index_count=index_count,
            )


def _decode_materials(tail: bytes, texture_root: Path) -> Iterable[PatMaterial]:
    material_names = _dedupe(_clean_ascii(match.group(1)) for match in _MATERIAL_RE.finditer(tail))
    texture_names = _dedupe(_clean_ascii(match.group(1)) for match in _TEXTURE_RE.finditer(tail))
    grouped_textures: list[list[str]] = [[] for _ in material_names]
    material_stems = [_material_base(name) for name in material_names]
    for texture_name in texture_names:
        assigned = False
        texture_base = _texture_base(texture_name)
        for index, material_base in enumerate(material_stems):
            if material_base and (material_base in texture_base or texture_base in material_base):
                grouped_textures[index].append(texture_name)
                assigned = True
                break
        if not assigned and grouped_textures:
            grouped_textures[min(len(grouped_textures) - 1, len([g for g in grouped_textures if g]))].append(texture_name)

    for index, name in enumerate(material_names):
        textures = tuple(grouped_textures[index])
        yield PatMaterial(
            name=name,
            textures=textures,
            resolved_textures=tuple(_resolve_texture_path(texture_root, texture) for texture in textures if _resolve_texture_path(texture_root, texture)),
        )


def _resolve_texture_path(texture_root: Path, texture_name: str) -> Path | None:
    if not texture_name:
        return None
    stem = Path(texture_name).stem
    candidates = [
        texture_root / f"{stem}.dds",
        texture_root / texture_name.replace(".tga", ".dds").replace(".TGA", ".dds"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    matches = list(texture_root.glob(f"{stem}*.dds")) if texture_root.is_dir() else []
    return matches[0] if matches else None


def _default_texture_root(source_path: Path) -> Path:
    return source_path.parent / "texture"


def _matching_meshinfo_path(source_path: Path) -> Path | None:
    candidate = source_path.parent / "bin__" / f"{source_path.stem}.meshinfo"
    return candidate if candidate.is_file() else None


def _extract_printable_strings(data: bytes, *, min_length: int) -> Iterable[str]:
    current: list[str] = []
    for value in data:
        if 32 <= value <= 126:
            current.append(chr(value))
        else:
            if len(current) >= min_length:
                yield "".join(current)
            current = []
    if len(current) >= min_length:
        yield "".join(current)


def _unpack_float3(data: bytes, offset: int) -> tuple[float, float, float]:
    return struct.unpack_from("<3f", data, offset)


def _unpack_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _unpack_u32_tuple(data: bytes, offset: int, count: int) -> tuple[int, ...]:
    return struct.unpack_from(f"<{count}I", data, offset)


def _unpack_u16_tuple(data: bytes, offset: int, count: int) -> tuple[int, ...]:
    return struct.unpack_from(f"<{count}H", data, offset)


def _require_monotonic(values: Sequence[int], label: str, *, starts_at_zero: bool = False) -> None:
    if starts_at_zero and values and values[0] != 0:
        raise PatDecodeError(f"{label} must start at zero")
    if any(values[index] > values[index + 1] for index in range(len(values) - 1)):
        raise PatDecodeError(f"{label} must be monotonic")


def _clean_ascii(value: bytes) -> str:
    text = value.decode("ascii", errors="ignore").strip().strip("\x00")
    if ".tga" in text.lower():
        text = re.split(r"(?i)(\.tga)", text, maxsplit=1)
        return "".join(text[:2])
    if ".dds" in text.lower():
        text = re.split(r"(?i)(\.dds)", text, maxsplit=1)
        return "".join(text[:2])
    if "_mat" in text:
        return text[: text.find("_mat") + 4]
    return text


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        clean = value.strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            output.append(clean)
    return output


def _material_base(value: str) -> str:
    return Path(value.replace("_mat", "")).stem.lower()


def _texture_base(value: str) -> str:
    return Path(value).stem.lower().replace("_color", "").replace("_normal", "").replace("_subsurface", "").replace("_dmap", "")


def _sanitize_name(value: str, *, fallback: str) -> str:
    clean = _EXPORT_NAME_RE.sub("_", value.strip()).strip("._")
    return clean or fallback


def _material_export_name(material: PatMaterial, index: int) -> str:
    return f"{_sanitize_name(material.name, fallback='material')}_{index:03d}"


def _format_vec(value: Sequence[float]) -> str:
    return ", ".join(f"{part:.6f}" for part in value)


def _valid_face(indices: Sequence[int], vertex_count: int) -> bool:
    return len(set(indices)) == 3 and all(0 <= index < vertex_count for index in indices)


def _export_texture_reference(material: PatMaterial, texture_output_dir: Path, *, copy_textures: bool) -> str:
    source = material.color_texture
    if source is None:
        return ""
    if not copy_textures:
        return str(source)
    texture_output_dir.mkdir(parents=True, exist_ok=True)
    output_path = texture_output_dir / source.name
    if not output_path.exists():
        shutil.copy2(source, output_path)
    return f"{texture_output_dir.name}/{output_path.name}"


def _expand_pat_inputs(paths: Sequence[Path]) -> list[Path]:
    output: list[Path] = []
    for path in paths:
        if path.is_dir():
            output.extend(sorted(path.rglob("*.pat")))
        else:
            output.append(path)
    return output


def _common_parent(paths: Sequence[Path]) -> Path | None:
    if not paths:
        return None
    try:
        return Path(os.path.commonpath([str(Path(path).resolve().parent) for path in paths]))
    except Exception:
        return paths[0].parent


def _relative_or_absolute(path: Path, root: Path | None) -> str:
    if root is None:
        return str(path)
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
