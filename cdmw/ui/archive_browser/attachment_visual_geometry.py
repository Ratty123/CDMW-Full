"""Archive browser attachment visual geometry helpers."""

from __future__ import annotations

import dataclasses
import math
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.models import (
    AttachmentPlacementEvidence,
    AttachmentSocketInfo,
    ModelPreviewData,
    ModelPreviewMesh,
)
from cdmw.ui.archive_browser.attachment_visual_context import ArchiveAttachmentVisualContextMixin


class ArchiveAttachmentVisualGeometryMixin(ArchiveAttachmentVisualContextMixin):
    @staticmethod
    def _attachment_visual_chain_transform(
        evidence: Optional[AttachmentPlacementEvidence],
        *,
        visual_offset: Sequence[float] = (),
        visual_rotation_degrees: Sequence[float] = (),
        context: Optional[Mapping[str, object]] = None,
    ) -> Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float, float], str]:
        if not isinstance(evidence, AttachmentPlacementEvidence):
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), "No placement evidence"
        character_socket = context.get("character_socket_info") if isinstance(context, Mapping) else None
        weapon_socket = context.get("weapon_socket_info") if isinstance(context, Mapping) else None
        socket_name = str(evidence.character_socket_name or "")
        parent_name = str(
            getattr(character_socket, "parent", "") if isinstance(character_socket, AttachmentSocketInfo) else evidence.character_socket_parent
        )
        proxy_anchor = __class__._attachment_visual_socket_proxy_position(socket_name, parent_name)
        socket_translation = __class__._attachment_visual_finite_vector3(
            getattr(character_socket, "translation", ()) if isinstance(character_socket, AttachmentSocketInfo) else evidence.character_socket_translation
        )
        pivot_translation = __class__._attachment_visual_finite_vector3(
            getattr(weapon_socket, "translation", ()) if isinstance(weapon_socket, AttachmentSocketInfo) else evidence.weapon_socket_translation
        )
        visual_delta = __class__._attachment_visual_finite_vector3(visual_offset)
        rotation_values = tuple(visual_rotation_degrees or (0.0, 0.0, 0.0))
        while len(rotation_values) < 3:
            rotation_values = (*rotation_values, 0.0)
        character_rotation = __class__._attachment_visual_finite_quat(
            getattr(character_socket, "rotation", ()) if isinstance(character_socket, AttachmentSocketInfo) else evidence.character_socket_rotation
        )
        pivot_rotation = __class__._attachment_visual_finite_quat(
            getattr(weapon_socket, "rotation", ()) if isinstance(weapon_socket, AttachmentSocketInfo) else evidence.weapon_socket_rotation
        )
        base_rotation = __class__._attachment_visual_quat_multiply(
            character_rotation,
            __class__._attachment_visual_quat_inverse(pivot_rotation),
        )
        manual_rotation = __class__._attachment_visual_euler_quat(
            float(rotation_values[0]),
            float(rotation_values[1]),
            float(rotation_values[2]),
        )
        rotation = __class__._attachment_visual_quat_multiply(manual_rotation, base_rotation)
        scale = __class__._attachment_visual_context_transform_scale(context)
        context_anchor = context.get("character_anchor") if isinstance(context, Mapping) else None
        if __class__._attachment_visual_context_has_real_anchor(context):
            anchor = __class__._attachment_visual_finite_vector3(context_anchor)
        else:
            anchor = (
                proxy_anchor[0] + (socket_translation[0] * scale),
                proxy_anchor[1] + (socket_translation[1] * scale),
                proxy_anchor[2] + (socket_translation[2] * scale),
            )
        offset = (
            anchor[0] - (pivot_translation[0] * scale) + visual_delta[0],
            anchor[1] - (pivot_translation[1] * scale) + visual_delta[1],
            anchor[2] - (pivot_translation[2] * scale) + visual_delta[2],
        )
        label = f"{socket_name or '-'} -> {evidence.weapon_socket_name or '-'}"
        return offset, pivot_translation, rotation, label

    @staticmethod
    def _attachment_visual_transform_point(
        point: Sequence[float],
        *,
        offset: Sequence[float],
        pivot: Sequence[float],
        rotation: Sequence[float],
        placement_scale: float = 0.10,
    ) -> Tuple[float, float, float]:
        px, py, pz = __class__._attachment_visual_finite_vector3(point)
        ox, oy, oz = __class__._attachment_visual_finite_vector3(offset)
        qx, qy, qz = __class__._attachment_visual_finite_vector3(pivot)
        scale = float(placement_scale) if math.isfinite(float(placement_scale or 0.0)) else 0.10
        local = (px - (qx * scale), py - (qy * scale), pz - (qz * scale))
        rotated = __class__._attachment_visual_quat_rotate(rotation, local)
        return (rotated[0] + ox, rotated[1] + oy, rotated[2] + oz)

    @staticmethod
    def _attachment_visual_transform_local_point(
        point: Sequence[float],
        *,
        offset: Sequence[float],
        rotation: Sequence[float],
    ) -> Tuple[float, float, float]:
        x, y, z = __class__._attachment_visual_finite_vector3(point)
        ox, oy, oz = __class__._attachment_visual_finite_vector3(offset)
        rotated = __class__._attachment_visual_quat_rotate(rotation, (x, y, z))
        return (rotated[0] + ox, rotated[1] + oy, rotated[2] + oz)

    @staticmethod
    def _attachment_visual_denormalized_model_point(
        model: ModelPreviewData,
        point: Sequence[float],
    ) -> Tuple[float, float, float]:
        x, y, z = __class__._attachment_visual_finite_vector3(point)
        center = __class__._attachment_visual_finite_vector3(getattr(model, "normalization_center", (0.0, 0.0, 0.0)))
        try:
            scale = float(getattr(model, "normalization_scale", 1.0) or 1.0)
        except (TypeError, ValueError, OverflowError):
            scale = 1.0
        if not math.isfinite(scale) or abs(scale) <= 1e-8:
            scale = 1.0
        return ((x / scale) + center[0], (y / scale) + center[1], (z / scale) + center[2])

    @staticmethod
    def _attachment_visual_model_vertex_count(model: Optional[object]) -> int:
        if not isinstance(model, ModelPreviewData):
            return 0
        total = 0
        for mesh in tuple(getattr(model, "meshes", ()) or ()):
            if isinstance(mesh, ModelPreviewMesh):
                positions = getattr(mesh, "positions", ()) or ()
                try:
                    total += len(positions)
                except TypeError:
                    total += sum(1 for _position in positions)
        return total

    @staticmethod
    def _attachment_visual_clone_model_meshes(
        model: Optional[object],
        *,
        offset: Sequence[float],
        pivot: Sequence[float],
        rotation: Sequence[float],
        color: Tuple[float, float, float],
        clear_textures: bool,
        label_prefix: str,
        placement_scale: float = 0.10,
        use_raw_model_space: bool = False,
        max_vertices: Optional[int] = None,
        model_scale: float = 1.0,
    ) -> List[ModelPreviewMesh]:
        if not isinstance(model, ModelPreviewData):
            return []
        try:
            vertex_budget = int(max_vertices or 0)
        except (TypeError, ValueError, OverflowError):
            vertex_budget = 0
        total_vertices = __class__._attachment_visual_model_vertex_count(model)
        total_index_refs = 0
        for source_mesh in tuple(getattr(model, "meshes", ()) or ()):
            if not isinstance(source_mesh, ModelPreviewMesh):
                continue
            try:
                total_index_refs += len(getattr(source_mesh, "indices", ()) or ())
            except TypeError:
                total_index_refs += sum(1 for _index in getattr(source_mesh, "indices", ()) or ())
        sample_step = 1
        if vertex_budget > 0 and total_vertices > vertex_budget:
            sample_basis = max(total_vertices, total_index_refs, 1)
            sample_step = max(2, int(math.ceil(float(sample_basis) / float(max(vertex_budget, 1)))))
        try:
            display_scale = float(model_scale)
        except (TypeError, ValueError, OverflowError):
            display_scale = 1.0
        if not math.isfinite(display_scale) or display_scale <= 0.0:
            display_scale = 1.0

        def _transformed_point(position: Sequence[float]) -> Tuple[float, float, float]:
            model_point = __class__._attachment_visual_denormalized_model_point(model, position) if use_raw_model_space else position
            px, py, pz = __class__._attachment_visual_finite_vector3(model_point)
            return __class__._attachment_visual_transform_point(
                (px * display_scale, py * display_scale, pz * display_scale),
                offset=offset,
                pivot=pivot,
                rotation=rotation,
                placement_scale=placement_scale,
            )

        def _clear_texture_fields(cloned_mesh: ModelPreviewMesh) -> None:
            if not clear_textures:
                return
            for attr_name in (
                "preview_texture_path",
                "preview_texture_image",
                "preview_normal_texture_path",
                "preview_normal_texture_image",
                "preview_material_texture_path",
                "preview_material_texture_image",
                "preview_height_texture_path",
                "preview_height_texture_image",
            ):
                setattr(cloned_mesh, attr_name, None if attr_name.endswith("_image") else "")

        def _sample_mesh_triangles(mesh: ModelPreviewMesh, cloned_mesh: ModelPreviewMesh) -> bool:
            source_positions = tuple(getattr(mesh, "positions", ()) or ())
            if not source_positions:
                return False
            raw_indices: List[int] = []
            for raw_index in tuple(getattr(mesh, "indices", ()) or ()):
                try:
                    raw_indices.append(int(raw_index))
                except (TypeError, ValueError, OverflowError):
                    continue
            if len(raw_indices) < 3:
                return False
            raw_normals = tuple(getattr(mesh, "normals", ()) or ())
            raw_uvs = tuple(getattr(mesh, "texture_coordinates", ()) or ())
            raw_source_vertices = tuple(getattr(mesh, "source_vertex_indices", ()) or ())
            raw_source_faces = tuple(getattr(mesh, "source_face_indices", ()) or ())
            remap: Dict[int, int] = {}
            sampled_positions: List[Tuple[float, float, float]] = []
            sampled_normals: List[Tuple[float, float, float]] = []
            sampled_uvs: List[Tuple[float, float]] = []
            sampled_source_vertices: List[int] = []
            sampled_source_faces: List[int] = []
            sampled_indices: List[int] = []
            triangle_ordinal = 0
            for index_offset in range(0, len(raw_indices) - 2, 3):
                source_face_ordinal = triangle_ordinal
                if triangle_ordinal % sample_step:
                    triangle_ordinal += 1
                    continue
                triangle_ordinal += 1
                triangle = (
                    raw_indices[index_offset],
                    raw_indices[index_offset + 1],
                    raw_indices[index_offset + 2],
                )
                if any(vertex_index < 0 or vertex_index >= len(source_positions) for vertex_index in triangle):
                    continue
                if triangle[0] == triangle[1] or triangle[1] == triangle[2] or triangle[0] == triangle[2]:
                    continue
                if source_face_ordinal < len(raw_source_faces):
                    try:
                        sampled_source_faces.append(int(raw_source_faces[source_face_ordinal]))
                    except (TypeError, ValueError, OverflowError):
                        sampled_source_faces.append(int(source_face_ordinal))
                else:
                    sampled_source_faces.append(int(source_face_ordinal))
                for source_index in triangle:
                    sampled_index = remap.get(source_index)
                    if sampled_index is None:
                        sampled_index = len(sampled_positions)
                        remap[source_index] = sampled_index
                        sampled_positions.append(_transformed_point(source_positions[source_index]))
                        if len(raw_normals) == len(source_positions):
                            sampled_normals.append(__class__._attachment_visual_finite_vector3(raw_normals[source_index]))
                        if len(raw_uvs) == len(source_positions):
                            try:
                                u, v = raw_uvs[source_index]
                                sampled_uvs.append((float(u), float(v)))
                            except (TypeError, ValueError, OverflowError):
                                sampled_uvs.append((0.0, 0.0))
                        if len(raw_source_vertices) == len(source_positions):
                            try:
                                sampled_source_vertices.append(int(raw_source_vertices[source_index]))
                            except (TypeError, ValueError, OverflowError):
                                sampled_source_vertices.append(int(source_index))
                        else:
                            sampled_source_vertices.append(int(source_index))
                    sampled_indices.append(sampled_index)
            if not sampled_positions or not sampled_indices:
                return False
            cloned_mesh.positions = sampled_positions
            cloned_mesh.indices = sampled_indices
            cloned_mesh.normals = sampled_normals if len(sampled_normals) == len(sampled_positions) else []
            cloned_mesh.texture_coordinates = sampled_uvs if len(sampled_uvs) == len(sampled_positions) else []
            cloned_mesh.source_vertex_indices = sampled_source_vertices
            cloned_mesh.source_face_indices = sampled_source_faces
            cloned_mesh.material_name = f"{cloned_mesh.material_name} sampled"
            return True

        meshes: List[ModelPreviewMesh] = []
        for index, mesh in enumerate(tuple(getattr(model, "meshes", ()) or ())):
            if not isinstance(mesh, ModelPreviewMesh):
                continue
            values = {field_info.name: getattr(mesh, field_info.name) for field_info in dataclasses.fields(ModelPreviewMesh)}
            cloned = ModelPreviewMesh(**values)
            cloned.material_name = f"{label_prefix} {cloned.material_name or index}".strip()
            if sample_step > 1:
                if not _sample_mesh_triangles(mesh, cloned):
                    continue
            else:
                cloned.positions = [
                    _transformed_point(position)
                    for position in tuple(getattr(mesh, "positions", ()) or ())
                ]
            cloned.preview_color = color
            _clear_texture_fields(cloned)
            meshes.append(cloned)
        return meshes

    @staticmethod
    def _attachment_visual_box_mesh(
        name: str,
        center: Tuple[float, float, float],
        size: Tuple[float, float, float],
        color: Tuple[float, float, float],
    ) -> ModelPreviewMesh:
        cx, cy, cz = center
        sx, sy, sz = (max(0.002, abs(size[0])) * 0.5, max(0.002, abs(size[1])) * 0.5, max(0.002, abs(size[2])) * 0.5)
        positions = [
            (cx - sx, cy - sy, cz - sz),
            (cx + sx, cy - sy, cz - sz),
            (cx + sx, cy + sy, cz - sz),
            (cx - sx, cy + sy, cz - sz),
            (cx - sx, cy - sy, cz + sz),
            (cx + sx, cy - sy, cz + sz),
            (cx + sx, cy + sy, cz + sz),
            (cx - sx, cy + sy, cz + sz),
        ]
        indices = [
            0, 1, 2, 0, 2, 3,
            4, 6, 5, 4, 7, 6,
            0, 4, 5, 0, 5, 1,
            1, 5, 6, 1, 6, 2,
            2, 6, 7, 2, 7, 3,
            3, 7, 4, 3, 4, 0,
        ]
        return ModelPreviewMesh(material_name=name, preview_color=color, positions=positions, indices=indices)

    @staticmethod
    def _attachment_visual_oriented_box_mesh(
        name: str,
        *,
        center: Tuple[float, float, float],
        size: Tuple[float, float, float],
        offset: Sequence[float],
        rotation: Sequence[float],
        color: Tuple[float, float, float],
        source_submesh_index: int = -1,
        preview_role: str = "",
    ) -> ModelPreviewMesh:
        cx, cy, cz = center
        sx, sy, sz = (max(0.002, abs(size[0])) * 0.5, max(0.002, abs(size[1])) * 0.5, max(0.002, abs(size[2])) * 0.5)
        local_positions = [
            (cx - sx, cy - sy, cz - sz),
            (cx + sx, cy - sy, cz - sz),
            (cx + sx, cy + sy, cz - sz),
            (cx - sx, cy + sy, cz - sz),
            (cx - sx, cy - sy, cz + sz),
            (cx + sx, cy - sy, cz + sz),
            (cx + sx, cy + sy, cz + sz),
            (cx - sx, cy + sy, cz + sz),
        ]
        indices = [
            0, 1, 2, 0, 2, 3,
            4, 6, 5, 4, 7, 6,
            0, 4, 5, 0, 5, 1,
            1, 5, 6, 1, 6, 2,
            2, 6, 7, 2, 7, 3,
            3, 7, 4, 3, 4, 0,
        ]
        return ModelPreviewMesh(
            material_name=name,
            preview_color=color,
            positions=[
                __class__._attachment_visual_transform_local_point(
                    position,
                    offset=offset,
                    rotation=rotation,
                )
                for position in local_positions
            ],
            indices=indices,
            source_submesh_index=int(source_submesh_index),
            preview_role=str(preview_role or ""),
        )

    @staticmethod
    def _attachment_visual_segment_mesh(
        name: str,
        start: Tuple[float, float, float],
        end: Tuple[float, float, float],
        thickness: float,
        color: Tuple[float, float, float],
    ) -> Optional[ModelPreviewMesh]:
        sx, sy, sz = __class__._attachment_visual_finite_vector3(start)
        ex, ey, ez = __class__._attachment_visual_finite_vector3(end)
        dx, dy, dz = (ex - sx, ey - sy, ez - sz)
        length = math.sqrt((dx * dx) + (dy * dy) + (dz * dz))
        if not math.isfinite(length) or length <= 1e-6:
            return None
        ax, ay, az = (dx / length, dy / length, dz / length)
        up = (0.0, 1.0, 0.0)
        if abs(ay) > 0.92:
            up = (1.0, 0.0, 0.0)
        ux, uy, uz = (
            (ay * up[2]) - (az * up[1]),
            (az * up[0]) - (ax * up[2]),
            (ax * up[1]) - (ay * up[0]),
        )
        u_length = math.sqrt((ux * ux) + (uy * uy) + (uz * uz))
        if not math.isfinite(u_length) or u_length <= 1e-6:
            return None
        ux, uy, uz = (ux / u_length, uy / u_length, uz / u_length)
        vx, vy, vz = (
            (ay * uz) - (az * uy),
            (az * ux) - (ax * uz),
            (ax * uy) - (ay * ux),
        )
        radius = max(0.0015, abs(float(thickness or 0.0)) * 0.5)

        def corner(base: Tuple[float, float, float], u_sign: float, v_sign: float) -> Tuple[float, float, float]:
            return (
                base[0] + (ux * radius * u_sign) + (vx * radius * v_sign),
                base[1] + (uy * radius * u_sign) + (vy * radius * v_sign),
                base[2] + (uz * radius * u_sign) + (vz * radius * v_sign),
            )

        start_point = (sx, sy, sz)
        end_point = (ex, ey, ez)
        positions = [
            corner(start_point, -1.0, -1.0),
            corner(start_point, 1.0, -1.0),
            corner(start_point, 1.0, 1.0),
            corner(start_point, -1.0, 1.0),
            corner(end_point, -1.0, -1.0),
            corner(end_point, 1.0, -1.0),
            corner(end_point, 1.0, 1.0),
            corner(end_point, -1.0, 1.0),
        ]
        indices = [
            0, 1, 2, 0, 2, 3,
            4, 6, 5, 4, 7, 6,
            0, 4, 5, 0, 5, 1,
            1, 5, 6, 1, 6, 2,
            2, 6, 7, 2, 7, 3,
            3, 7, 4, 3, 4, 0,
        ]
        return ModelPreviewMesh(material_name=name, preview_color=color, positions=positions, indices=indices)

    def _attachment_visual_body_proxy_meshes(
        self,
        evidences: Sequence[Optional[AttachmentPlacementEvidence]],
        contexts: Sequence[Optional[Mapping[str, object]]] = (),
    ) -> List[ModelPreviewMesh]:
        skeleton_context = next(
            (
                context
                for context in tuple(contexts or ())
                if (
                    isinstance(context, Mapping)
                    and isinstance(context.get("bone_positions"), Mapping)
                    and self._attachment_visual_context_has_real_anchor(context)
                )
            ),
            None,
        )
        if isinstance(skeleton_context, Mapping):
            bone_positions = skeleton_context.get("bone_positions")
            parent_names = skeleton_context.get("bone_parent_names")
            meshes: List[ModelPreviewMesh] = []
            if isinstance(bone_positions, Mapping) and isinstance(parent_names, Mapping):
                added_segments = 0
                for child_key, parent_name in tuple(parent_names.items()):
                    if added_segments >= 140:
                        break
                    child_position = self._attachment_visual_lookup_named_vector(bone_positions, str(child_key))
                    parent_position = self._attachment_visual_lookup_named_vector(bone_positions, str(parent_name))
                    if child_position is None or parent_position is None:
                        continue
                    distance = math.sqrt(
                        ((child_position[0] - parent_position[0]) ** 2)
                        + ((child_position[1] - parent_position[1]) ** 2)
                        + ((child_position[2] - parent_position[2]) ** 2)
                    )
                    if not math.isfinite(distance) or distance <= 1e-5 or distance > 6.0:
                        continue
                    segment = self._attachment_visual_segment_mesh(
                        f"skeleton bone {child_key}",
                        parent_position,
                        child_position,
                        0.010,
                        (0.13, 0.18, 0.24),
                    )
                    if segment is None:
                        continue
                    meshes.append(segment)
                    added_segments += 1

            def position(*names: str) -> Optional[Tuple[float, float, float]]:
                for name in names:
                    value = self._attachment_visual_lookup_named_vector(bone_positions, name)
                    if value is not None:
                        return value
                return None

            def span_box(
                name: str,
                first: Optional[Tuple[float, float, float]],
                second: Optional[Tuple[float, float, float]],
                thickness: float,
                color: Tuple[float, float, float],
            ) -> Optional[ModelPreviewMesh]:
                if first is None or second is None:
                    return None
                center = ((first[0] + second[0]) * 0.5, (first[1] + second[1]) * 0.5, (first[2] + second[2]) * 0.5)
                size = (
                    max(thickness, abs(first[0] - second[0]) + thickness),
                    max(thickness, abs(first[1] - second[1]) + thickness),
                    max(thickness, abs(first[2] - second[2]) + thickness),
                )
                return self._attachment_visual_box_mesh(name, center, size, color)

            pelvis = position("Bip01 Pelvis", "Bip01")
            spine = position("Bip01 Spine2", "Bip01 Spine1", "Bip01 Spine")
            head = position("Bip01 Head", "Bip01 Neck")
            left_hand = position("Bip01 L Hand", "Bip_Weapon_L")
            right_hand = position("Bip01 R Hand", "Bip_Weapon_R")
            left_clavicle = position("Bip01 L Clavicle", "Bip01 L UpperArm")
            right_clavicle = position("Bip01 R Clavicle", "Bip01 R UpperArm")
            left_foot = position("Bip01 L Foot", "Bip01 L Calf")
            right_foot = position("Bip01 R Foot", "Bip01 R Calf")
            if not meshes:
                for mesh in (
                    span_box("socket guide torso", pelvis, spine, 0.035, (0.12, 0.16, 0.20)),
                    span_box("socket guide neck", spine, head, 0.028, (0.12, 0.16, 0.20)),
                    span_box("socket guide left arm", left_clavicle, left_hand, 0.024, (0.10, 0.14, 0.18)),
                    span_box("socket guide right arm", right_clavicle, right_hand, 0.024, (0.10, 0.14, 0.18)),
                    span_box("socket guide left leg", pelvis, left_foot, 0.026, (0.10, 0.14, 0.18)),
                    span_box("socket guide right leg", pelvis, right_foot, 0.026, (0.10, 0.14, 0.18)),
                ):
                    if mesh is not None:
                        meshes.append(mesh)
            for name, point, size in (
                ("skeleton pelvis marker", pelvis, (0.090, 0.090, 0.090)),
                ("skeleton head marker", head, (0.070, 0.070, 0.070)),
            ):
                if point is not None:
                    meshes.append(self._attachment_visual_box_mesh(name, point, size, (0.24, 0.30, 0.36)))
            marker_colors = ((0.34, 0.78, 0.53), (0.93, 0.63, 0.29))
            seen_markers: set[str] = set()
            for index, evidence in enumerate(evidences):
                if not isinstance(evidence, AttachmentPlacementEvidence):
                    continue
                context = contexts[index] if index < len(contexts) and isinstance(contexts[index], Mapping) else skeleton_context
                socket = context.get("character_socket_info") if isinstance(context, Mapping) else None
                marker_position = self._attachment_visual_socket_world_position(socket, context) if isinstance(socket, AttachmentSocketInfo) else None
                socket_name = str(evidence.character_socket_name or "")
                if marker_position is None:
                    parent_name = str(getattr(socket, "parent", "") if isinstance(socket, AttachmentSocketInfo) else evidence.character_socket_parent)
                    marker_position = self._attachment_visual_socket_proxy_position(socket_name, parent_name)
                marker_key = f"{socket_name.casefold()}::{marker_position}"
                if marker_key in seen_markers:
                    continue
                seen_markers.add(marker_key)
                meshes.append(
                    self._attachment_visual_box_mesh(
                        f"socket marker {socket_name or index}",
                        marker_position,
                        (0.070, 0.070, 0.070),
                        marker_colors[min(index, len(marker_colors) - 1)],
                    )
                )
            if meshes:
                return meshes

        meshes = [
            self._attachment_visual_box_mesh("socket guide torso", (0.0, 0.26, 0.0), (0.10, 0.54, 0.035), (0.12, 0.16, 0.20)),
            self._attachment_visual_box_mesh("socket guide pelvis", (0.0, -0.18, 0.0), (0.26, 0.055, 0.035), (0.13, 0.17, 0.21)),
            self._attachment_visual_box_mesh("socket guide head", (0.0, 0.66, 0.0), (0.070, 0.070, 0.055), (0.12, 0.16, 0.20)),
            self._attachment_visual_box_mesh("socket guide left arm", (-0.28, 0.18, 0.02), (0.035, 0.44, 0.035), (0.10, 0.14, 0.18)),
            self._attachment_visual_box_mesh("socket guide right arm", (0.28, 0.18, 0.02), (0.035, 0.44, 0.035), (0.10, 0.14, 0.18)),
        ]
        marker_colors = ((0.34, 0.78, 0.53), (0.93, 0.63, 0.29))
        seen_markers: set[Tuple[str, str]] = set()
        for index, evidence in enumerate(evidences):
            if not isinstance(evidence, AttachmentPlacementEvidence):
                continue
            socket_name = str(evidence.character_socket_name or "")
            parent_name = str(evidence.character_socket_parent or "")
            marker_key = (socket_name.casefold(), parent_name.casefold())
            if marker_key in seen_markers:
                continue
            seen_markers.add(marker_key)
            marker_position = self._attachment_visual_socket_proxy_position(socket_name, parent_name)
            meshes.append(
                self._attachment_visual_box_mesh(
                    f"socket marker {socket_name or index}",
                    marker_position,
                    (0.055, 0.055, 0.055),
                    marker_colors[min(index, len(marker_colors) - 1)],
                )
            )
        return meshes

    def _attachment_visual_weapon_proxy_meshes(
        self,
        evidence: Optional[AttachmentPlacementEvidence],
        *,
        context: Optional[Mapping[str, object]],
        visual_offset: Sequence[float] = (),
        visual_rotation_degrees: Sequence[float] = (),
        label_prefix: str,
        color: Tuple[float, float, float],
        source_submesh_index: int,
        preview_role: str,
    ) -> List[ModelPreviewMesh]:
        offset, _pivot, rotation, label = self._attachment_visual_chain_transform(
            evidence,
            visual_offset=visual_offset,
            visual_rotation_degrees=visual_rotation_degrees,
            context=context,
        )
        path_text = ""
        if isinstance(evidence, AttachmentPlacementEvidence):
            path_text = " ".join(
                str(value or "")
                for value in (
                    evidence.model_path,
                    evidence.prefab_path,
                    evidence.character_socket_name,
                    evidence.weapon_socket_name,
                )
            ).casefold()
        long_weapon = any(token in path_text for token in ("twohand", "2_twohand", "02_sword", "great", "long"))
        shield_like = "shield" in path_text
        if shield_like:
            parts = (
                ("plate", (0.0, 0.12, 0.0), (0.28, 0.34, 0.045)),
                ("rim", (0.0, 0.12, 0.0), (0.32, 0.38, 0.020)),
                ("grip", (0.0, -0.08, 0.0), (0.13, 0.035, 0.055)),
            )
        else:
            length = 0.68 if long_weapon else 0.52
            blade_length = length * 0.70
            grip_length = length * 0.22
            parts = (
                ("blade", (0.0, grip_length + (blade_length * 0.5), 0.0), (0.035, blade_length, 0.018)),
                ("grip", (0.0, grip_length * 0.48, 0.0), (0.025, grip_length, 0.025)),
                ("guard", (0.0, grip_length, 0.0), (0.16, 0.022, 0.026)),
                ("socket", (0.0, 0.0, 0.0), (0.060, 0.060, 0.060)),
            )
        meshes: List[ModelPreviewMesh] = []
        for part_name, center, size in parts:
            mesh = self._attachment_visual_oriented_box_mesh(
                f"{label_prefix} {part_name} {label}",
                center=center,
                size=size,
                offset=offset,
                rotation=rotation,
                color=color,
                source_submesh_index=source_submesh_index,
                preview_role=preview_role,
            )
            meshes.append(mesh)
        return meshes
