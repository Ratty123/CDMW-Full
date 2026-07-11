from __future__ import annotations

import math
from pathlib import Path
from urllib.parse import unquote, urlparse

from .mesh_parser import SubMesh, _compute_smooth_normals

def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return default


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _bbox(
    vertices: list[tuple[float, float, float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    if not vertices:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    xs, ys, zs = zip(*vertices)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

def _resolve_scene_uri(base_dir: Path, uri: str) -> Path:
    parsed = urlparse(uri)
    raw_path = unquote(parsed.path if parsed.scheme == "file" else uri)
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = base_dir / raw_path
    return candidate.expanduser().resolve()


def _transform_point(
    vertex: tuple[float, float, float],
    matrix: tuple[float, ...],
) -> tuple[float, float, float]:
    x, y, z = vertex
    return (
        matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
        matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
        matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
    )


def _transform_vector(
    vertex: tuple[float, float, float],
    matrix: tuple[float, ...],
) -> tuple[float, float, float]:
    x, y, z = vertex
    return (
        matrix[0] * x + matrix[1] * y + matrix[2] * z,
        matrix[4] * x + matrix[5] * y + matrix[6] * z,
        matrix[8] * x + matrix[9] * y + matrix[10] * z,
    )


def _linear_determinant(matrix: tuple[float, ...]) -> float:
    return (
        matrix[0] * (matrix[5] * matrix[10] - matrix[6] * matrix[9])
        - matrix[1] * (matrix[4] * matrix[10] - matrix[6] * matrix[8])
        + matrix[2] * (matrix[4] * matrix[9] - matrix[5] * matrix[8])
    )


def _transform_normal(
    normal: tuple[float, float, float],
    matrix: tuple[float, ...],
) -> tuple[float, float, float]:
    inverse = _invert_affine_matrix(matrix)
    if inverse is None:
        return _normalize_vec(_transform_vector(normal, matrix))
    x, y, z = normal
    return _normalize_vec(
        (
            inverse[0] * x + inverse[4] * y + inverse[8] * z,
            inverse[1] * x + inverse[5] * y + inverse[9] * z,
            inverse[2] * x + inverse[6] * y + inverse[10] * z,
        )
    )


def _normalize_vec(value: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(value[0] * value[0] + value[1] * value[1] + value[2] * value[2])
    if length <= 1e-8:
        return (0.0, 1.0, 0.0)
    return (value[0] / length, value[1] / length, value[2] / length)


def _identity_matrix() -> tuple[float, ...]:
    return (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def _invert_affine_matrix(matrix: tuple[float, ...]) -> Optional[tuple[float, ...]]:
    if len(matrix) < 16:
        return None
    a, b, c, tx = matrix[0], matrix[1], matrix[2], matrix[3]
    d, e, f, ty = matrix[4], matrix[5], matrix[6], matrix[7]
    g, h, i, tz = matrix[8], matrix[9], matrix[10], matrix[11]
    determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(determinant) <= 1e-12:
        return None
    scale = 1.0 / determinant
    r00 = (e * i - f * h) * scale
    r01 = (c * h - b * i) * scale
    r02 = (b * f - c * e) * scale
    r10 = (f * g - d * i) * scale
    r11 = (a * i - c * g) * scale
    r12 = (c * d - a * f) * scale
    r20 = (d * h - e * g) * scale
    r21 = (b * g - a * h) * scale
    r22 = (a * e - b * d) * scale
    return (
        r00, r01, r02, -(r00 * tx + r01 * ty + r02 * tz),
        r10, r11, r12, -(r10 * tx + r11 * ty + r12 * tz),
        r20, r21, r22, -(r20 * tx + r21 * ty + r22 * tz),
        0.0, 0.0, 0.0, 1.0,
    )


def _multiply_matrix(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    values: list[float] = []
    for row in range(4):
        for column in range(4):
            values.append(
                left[row * 4 + 0] * right[0 * 4 + column]
                + left[row * 4 + 1] * right[1 * 4 + column]
                + left[row * 4 + 2] * right[2 * 4 + column]
                + left[row * 4 + 3] * right[3 * 4 + column]
            )
    return tuple(values)


def _float_list(value: object, count: int, default: tuple[float, ...]) -> tuple[float, ...]:
    if isinstance(value, list) and len(value) >= count:
        try:
            return tuple(float(item) for item in value[:count])
        except Exception:
            return default
    return default


def _parse_float_list(text: str) -> list[float]:
    values: list[float] = []
    for raw_value in str(text or "").split():
        try:
            values.append(float(raw_value))
        except ValueError:
            continue
    return values

def _copy_submesh_with_transform(
    submesh: SubMesh,
    matrix: tuple[float, ...],
) -> SubMesh:
    vertices = [_transform_point(vertex, matrix) for vertex in submesh.vertices]
    mirrored = _linear_determinant(matrix) < 0.0
    faces = [
        (face[0], face[2], face[1]) if mirrored else tuple(face)
        for face in submesh.faces
        if len(face) == 3
    ]
    normals = [_transform_normal(normal, matrix) for normal in submesh.normals]
    tangents = [_normalize_vec(_transform_vector(tangent, matrix)) for tangent in submesh.tangents]
    copied = SubMesh(
        name=submesh.name,
        material=submesh.material,
        texture=submesh.texture,
        vertices=vertices,
        uvs=list(submesh.uvs),
        normals=normals if len(normals) == len(vertices) else _compute_smooth_normals(vertices, faces),
        tangents=tangents if len(tangents) == len(vertices) else [],
        faces=faces,
        vertex_count=len(vertices),
        face_count=len(faces),
    )
    tangent_signs = list(getattr(submesh, "tangent_signs", ()) or ())
    if len(tangent_signs) == len(vertices):
        sign_scale = -1.0 if mirrored else 1.0
        setattr(copied, "tangent_signs", [float(value) * sign_scale for value in tangent_signs])
    for attr_name in (
        "texture_slots",
        "preview_color",
        "preview_texture_path",
        "preview_texture_name",
        "preview_texture_tint",
        "preview_texture_brightness",
        "preview_texture_uv_scale",
        "preview_vertex_color_mean",
        "preview_vertex_alpha_mean",
        "preview_vertex_alpha_min",
        "preview_vertex_color_count",
        "preview_alpha_mode",
        "preview_double_sided",
        "preview_native_material_overrides",
        "preview_normal_texture_path",
        "preview_normal_texture_name",
        "preview_normal_texture_strength",
        "preview_material_texture_path",
        "preview_material_texture_name",
        "preview_material_texture_type",
        "preview_material_texture_subtype",
        "preview_material_texture_packed_channels",
        "preview_material_texture_inputs",
        "preview_material_parameters",
        "preview_height_texture_path",
        "preview_height_texture_name",
        "preview_sidecar_shader_family",
    ):
        if hasattr(submesh, attr_name):
            setattr(copied, attr_name, getattr(submesh, attr_name))
    return copied

def _dedupe_paths(values: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for value in values:
        try:
            path = value.expanduser().resolve()
        except Exception:
            continue
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result
