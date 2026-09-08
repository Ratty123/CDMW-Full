"""Reversible PABC coordinates for the disposable character editing mesh."""

from __future__ import annotations

import copy
import math
import struct
from dataclasses import dataclass

from cdmw.modding.mesh_edit_ops import refresh_mesh_totals
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.modding.skeleton_variation_parser import _influences, _invert_affine


def _point(value, matrix, *, normal=False):
    result = tuple(
        math.fsum(float(value[row]) * matrix[row * 4 + column] for row in range(3))
        + (0.0 if normal else matrix[12 + column])
        for column in range(3)
    )
    if not all(math.isfinite(component) for component in result):
        raise ValueError("Neutral face edit produced non-finite source coordinates")
    if normal:
        length = math.sqrt(math.fsum(component * component for component in result))
        if length > 1e-12:
            return tuple(component / length for component in result)
    return result


def _same_display_value(left, right):
    # Rust edits f32 vertices. Preserve untouched PAC values, including normals
    # whose packed source length is not exactly one, through a no-op Finish.
    return all(
        a == b or struct.pack("<f", a) == struct.pack("<f", b)
        for a, b in zip(left, right)
    )


def _mesh_parts(mesh):
    seen = set()
    for level in (mesh.submeshes, *(mesh.lod_levels or ())):
        for part in level:
            if id(part) not in seen:
                seen.add(id(part))
                yield part


@dataclass(frozen=True, slots=True)
class NeutralMeshAppearance:
    """The same resolved bone palette and neutral transforms as Archive Preview."""

    source: str
    bone_palette: tuple[int, ...]
    skin_matrices: tuple[tuple[float, ...], ...]

    def bone_position(self, index: int, position):
        if 0 <= index < len(self.skin_matrices):
            return _point(position, self.skin_matrices[index])
        return position

    def _normal_matrices(self):
        matrices = []
        for matrix in self.skin_matrices:
            inverse = _invert_affine(matrix)
            matrices.append(tuple(
                inverse[column * 4 + row] if row < 3 and column < 3
                else (1.0 if row == column else 0.0)
                for row in range(4) for column in range(4)
            ))
        return tuple(matrices)

    def _vertex_matrices(self, part, normal_matrices):
        count = len(part.vertices)
        if len(part.bone_indices) != count or len(part.bone_weights) != count:
            if part.bone_indices or part.bone_weights:
                raise ValueError("Neutral face editing requires complete vertex skin weights")
            return [None] * count
        cache = {}
        result = []
        for slots, weights in zip(part.bone_indices, part.bone_weights):
            influences = _influences(slots, weights, self.bone_palette, len(self.skin_matrices))
            if not influences:
                result.append(None)
                continue
            pair = cache.get(influences)
            if pair is None:
                pair = tuple(tuple(
                    math.fsum(weight * matrices[bone][index] for bone, weight in influences)
                    for index in range(16)
                ) for matrices in (self.skin_matrices, normal_matrices))
                # Blended matrices must themselves be invertible. Blending the
                # inverse bone transforms would not undo linear blend skinning.
                _invert_affine(pair[0])
                _invert_affine(pair[1])
                cache[influences] = pair
            result.append(pair)
        return result

    def to_neutral(self, mesh: ParsedMesh) -> ParsedMesh:
        result = copy.deepcopy(mesh)
        normal_matrices = self._normal_matrices()
        for part in _mesh_parts(result):
            matrices = self._vertex_matrices(part, normal_matrices)
            part.vertices = [_point(value, pair[0]) if pair else value for value, pair in zip(part.vertices, matrices)]
            if len(part.normals) == len(matrices):
                part.normals = [_point(value, pair[1], normal=True) if pair else value for value, pair in zip(part.normals, matrices)]
            # Tangents belong to the source coordinate frame. Regenerate them
            # through the normal editor command when needed.
            if any(matrices):
                part.tangents = []
        refresh_mesh_totals(result)
        return result

    def to_source(self, mesh: ParsedMesh, source: ParsedMesh) -> ParsedMesh:
        result = copy.deepcopy(mesh)
        originals = list(_mesh_parts(source))
        normal_matrices = self._normal_matrices()
        for part_index, part in enumerate(_mesh_parts(result)):
            matrices = self._vertex_matrices(part, normal_matrices)
            original = originals[part_index] if part_index < len(originals) else None
            if original is not None and (
                original.name != part.name
                or len(original.vertices) != len(part.vertices)
                or original.source_vertex_map != part.source_vertex_map
                or original.source_vertex_offsets != part.source_vertex_offsets
            ):
                original = None
            restored_positions = []
            restored_normals = []
            for index, pair in enumerate(matrices):
                if pair is None:
                    restored_positions.append(part.vertices[index])
                    if len(part.normals) == len(matrices):
                        restored_normals.append(part.normals[index])
                    continue
                position_matrix, normal_matrix = pair
                value = part.vertices[index]
                original_position = original.vertices[index] if original is not None else None
                if original_position is not None and _same_display_value(value, _point(original_position, position_matrix)):
                    restored_positions.append(original_position)
                else:
                    restored_positions.append(_point(value, _invert_affine(position_matrix)))
                if len(part.normals) == len(matrices):
                    value = part.normals[index]
                    original_normal = (
                        original.normals[index]
                        if original is not None and len(original.normals) == len(matrices) else None
                    )
                    if original_normal is not None and _same_display_value(value, _point(original_normal, normal_matrix, normal=True)):
                        restored_normals.append(original_normal)
                    else:
                        restored_normals.append(_point(value, _invert_affine(normal_matrix), normal=True))
            part.vertices = restored_positions
            if restored_normals:
                part.normals = restored_normals
            if any(matrices):
                part.tangents = (
                    list(original.tangents)
                    if original is not None and part.vertices == original.vertices
                    and part.normals == original.normals and part.uvs == original.uvs else []
                )
        refresh_mesh_totals(result)
        return result
