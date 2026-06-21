"""Archive browser attachment visual preview model builders."""

from __future__ import annotations

from typing import List, Mapping, Optional, Sequence, Tuple

from cdmw.models import (
    AttachmentPlacementEvidence,
    AttachmentSocketDocument,
    AttachmentSocketInfo,
    ModelPreviewData,
    ModelPreviewMesh,
)
from cdmw.ui.archive_browser.attachment_visual_geometry import ArchiveAttachmentVisualGeometryMixin


class ArchiveAttachmentVisualPreviewMixin(ArchiveAttachmentVisualGeometryMixin):
    def _build_attachment_placement_schematic_preview_model(
        self,
        *,
        target_evidence: Optional[AttachmentPlacementEvidence],
        donor_evidence: Optional[AttachmentPlacementEvidence],
        target_context: Optional[Mapping[str, object]] = None,
        donor_context: Optional[Mapping[str, object]] = None,
        visual_offset: Sequence[float] = (),
        visual_rotation_degrees: Sequence[float] = (),
    ) -> Tuple[Optional[ModelPreviewData], Tuple[int, ...]]:
        candidate_evidence = donor_evidence or target_evidence
        candidate_context = donor_context if isinstance(donor_context, Mapping) else target_context
        meshes = self._attachment_visual_body_proxy_meshes(
            (target_evidence, candidate_evidence),
            (target_context, candidate_context),
        )
        for mesh in meshes:
            if isinstance(mesh, ModelPreviewMesh):
                mesh.source_submesh_index = -1
                mesh.preview_role = "original_reference"
        meshes.extend(
            self._attachment_visual_weapon_proxy_meshes(
                target_evidence,
                context=target_context,
                label_prefix="current placement",
                color=(0.30, 0.43, 0.82),
                source_submesh_index=9000,
                preview_role="original_reference",
            )
        )
        editable_source_id = 9001
        meshes.extend(
            self._attachment_visual_weapon_proxy_meshes(
                candidate_evidence,
                context=candidate_context,
                visual_offset=visual_offset,
                visual_rotation_degrees=visual_rotation_degrees,
                label_prefix="selected placement",
                color=(0.22, 0.78, 0.42),
                source_submesh_index=editable_source_id,
                preview_role="replacement_preview",
            )
        )
        vertex_count = sum(len(mesh.positions) for mesh in meshes)
        face_count = sum(len(mesh.indices) // 3 for mesh in meshes)
        return (
            ModelPreviewData(
                path="attachment-placement-schematic-preview",
                format="placement-schematic-preview",
                summary=(
                    "Socket schematic placement preview\n"
                    "Blue proxy is current target placement. Green proxy is selected placement and receives drag/numeric edits. "
                    "This preview intentionally avoids decoded PAC geometry so placement changes are visible and stable."
                ),
                mesh_count=len(meshes),
                vertex_count=vertex_count,
                face_count=face_count,
                normalization_center=(0.0, 0.0, 0.0),
                normalization_scale=1.0,
                meshes=meshes,
            ),
            (editable_source_id,),
        )

    def _attachment_visual_socket_anchor_position(
        self,
        evidence: Optional[AttachmentPlacementEvidence],
        context: Optional[Mapping[str, object]],
    ) -> Tuple[float, float, float]:
        if not isinstance(evidence, AttachmentPlacementEvidence):
            return (0.0, 0.0, 0.0)
        character_socket = context.get("character_socket_info") if isinstance(context, Mapping) else None
        if self._attachment_visual_context_has_real_anchor(context):
            return self._attachment_visual_finite_vector3(
                context.get("character_anchor") if isinstance(context, Mapping) else (),
            )
        socket_name = str(evidence.character_socket_name or "")
        parent_name = str(
            getattr(character_socket, "parent", "") if isinstance(character_socket, AttachmentSocketInfo) else evidence.character_socket_parent
        )
        proxy_anchor = self._attachment_visual_socket_proxy_position(socket_name, parent_name)
        socket_translation = self._attachment_visual_finite_vector3(
            getattr(character_socket, "translation", ()) if isinstance(character_socket, AttachmentSocketInfo) else evidence.character_socket_translation
        )
        scale = self._attachment_visual_context_transform_scale(context)
        return (
            proxy_anchor[0] + (socket_translation[0] * scale),
            proxy_anchor[1] + (socket_translation[1] * scale),
            proxy_anchor[2] + (socket_translation[2] * scale),
        )

    def _build_attachment_socket_only_preview_model(
        self,
        evidence: Optional[AttachmentPlacementEvidence],
        context: Optional[Mapping[str, object]] = None,
    ) -> Optional[ModelPreviewData]:
        if not isinstance(evidence, AttachmentPlacementEvidence):
            return None
        context_map = context if isinstance(context, Mapping) else {}
        meshes: List[ModelPreviewMesh] = self._attachment_visual_body_proxy_meshes((evidence,), (context_map,))
        anchor = self._attachment_visual_socket_anchor_position(evidence, context_map)
        _offset, pivot_translation, rotation, label = self._attachment_visual_chain_transform(
            evidence,
            context=context_map,
        )
        scale = self._attachment_visual_context_transform_scale(context_map)
        meshes.append(
            self._attachment_visual_box_mesh(
                f"attachment socket {evidence.character_socket_name or 'selected'}",
                anchor,
                (0.075, 0.075, 0.075),
                (0.34, 0.78, 0.53),
            )
        )
        weapon_document = context_map.get("weapon_socket_document")
        weapon_sockets: List[AttachmentSocketInfo] = []
        if isinstance(weapon_document, AttachmentSocketDocument):
            weapon_sockets = [
                socket
                for socket in tuple(getattr(weapon_document, "sockets", ()) or ())
                if isinstance(socket, AttachmentSocketInfo)
            ]
        weapon_socket = context_map.get("weapon_socket_info")
        if isinstance(weapon_socket, AttachmentSocketInfo) and all(
            str(socket.name or "").casefold() != str(weapon_socket.name or "").casefold()
            for socket in weapon_sockets
        ):
            weapon_sockets.insert(0, weapon_socket)
        important_names = {
            str(evidence.weapon_socket_name or "").strip().casefold(),
            str(getattr(weapon_socket, "name", "") if isinstance(weapon_socket, AttachmentSocketInfo) else "").strip().casefold(),
        }
        important_names.discard("")
        for index, socket in enumerate(weapon_sockets[:24]):
            socket_translation = self._attachment_visual_finite_vector3(socket.translation)
            local = (
                (socket_translation[0] - pivot_translation[0]) * scale,
                (socket_translation[1] - pivot_translation[1]) * scale,
                (socket_translation[2] - pivot_translation[2]) * scale,
            )
            rotated = self._attachment_visual_quat_rotate(rotation, local)
            socket_position = (
                anchor[0] + rotated[0],
                anchor[1] + rotated[1],
                anchor[2] + rotated[2],
            )
            is_pivot = str(socket.name or "").strip().casefold() in important_names
            meshes.append(
                self._attachment_visual_box_mesh(
                    f"weapon socket {socket.name or index}",
                    socket_position,
                    (0.060, 0.060, 0.060) if is_pivot else (0.036, 0.036, 0.036),
                    (0.93, 0.63, 0.29) if is_pivot else (0.72, 0.78, 0.86),
                )
            )
        if len(meshes) <= 0:
            return None
        vertex_count = sum(len(mesh.positions) for mesh in meshes)
        face_count = sum(len(mesh.indices) // 3 for mesh in meshes)
        source_summary = str(context_map.get("placement_source_summary", "") or "socket-name proxy fallback")
        return ModelPreviewData(
            path=str(evidence.socket_file_path or evidence.prefab_path or "attachment-socket-placement-preview"),
            format="placement-socket-preview",
            summary=(
                "Socket-only placement preview\n"
                f"Chain: {label}\n"
                f"Evidence: {source_summary}\n"
                "Green marker is the character attachment socket; amber marker is the selected weapon pivot."
            ),
            mesh_count=len(meshes),
            vertex_count=vertex_count,
            face_count=face_count,
            normalization_center=(0.0, 0.0, 0.0),
            normalization_scale=1.0,
            meshes=meshes,
        )

    def _build_attachment_visual_preview_model(
        self,
        target_model: Optional[object],
        donor_model: Optional[object],
        *,
        body_model: Optional[object] = None,
        target_evidence: Optional[AttachmentPlacementEvidence],
        donor_evidence: Optional[AttachmentPlacementEvidence],
        target_context: Optional[Mapping[str, object]] = None,
        donor_context: Optional[Mapping[str, object]] = None,
        visual_offset: Sequence[float] = (),
        visual_rotation_degrees: Sequence[float] = (),
        mode: str = "target_with_donor",
        include_body_proxy: bool = True,
        show_candidate: bool = True,
    ) -> Tuple[Optional[ModelPreviewData], Tuple[int, ...]]:
        if not isinstance(target_model, ModelPreviewData):
            return None, ()
        effective_donor_context = donor_context if isinstance(donor_context, Mapping) else target_context
        model_vertex_budget = 160_000
        body_vertex_budget = 80_000
        simplified_notes: List[str] = []
        meshes: List[ModelPreviewMesh] = []
        if isinstance(body_model, ModelPreviewData):
            if self._attachment_visual_model_vertex_count(body_model) > body_vertex_budget:
                simplified_notes.append("Large body context was triangle-sampled to keep the editor stable.")
            meshes.extend(
                self._attachment_visual_clone_model_meshes(
                    body_model,
                    offset=(0.0, 0.0, 0.0),
                    pivot=(0.0, 0.0, 0.0),
                    rotation=(0.0, 0.0, 0.0, 1.0),
                    color=(0.62, 0.60, 0.54),
                    clear_textures=False,
                    label_prefix="body context",
                    placement_scale=1.0,
                    use_raw_model_space=False,
                    max_vertices=body_vertex_budget,
                    model_scale=1.0,
                )
            )
        if include_body_proxy:
            meshes.extend(
                self._attachment_visual_body_proxy_meshes(
                    (target_evidence, donor_evidence),
                    (target_context, effective_donor_context),
                )
            )
        target_offset, target_pivot, target_rotation, target_label = self._attachment_visual_chain_transform(
            target_evidence,
            context=target_context,
        )
        donor_offset, donor_pivot, donor_rotation, donor_label = self._attachment_visual_chain_transform(
            donor_evidence or target_evidence,
            visual_offset=visual_offset,
            visual_rotation_degrees=visual_rotation_degrees,
            context=effective_donor_context,
        )
        target_scale = self._attachment_visual_context_transform_scale(target_context)
        donor_scale = self._attachment_visual_context_transform_scale(effective_donor_context)
        target_uses_raw_space = False
        donor_uses_raw_space = False
        if self._attachment_visual_model_vertex_count(target_model) > model_vertex_budget:
            simplified_notes.append("Large target model was triangle-sampled to keep the editor stable.")
        meshes.extend(
            self._attachment_visual_clone_model_meshes(
                target_model,
                offset=target_offset,
                pivot=target_pivot,
                rotation=target_rotation,
                color=(0.30, 0.43, 0.62),
                clear_textures=bool(1),
                label_prefix="current",
                placement_scale=target_scale,
                use_raw_model_space=target_uses_raw_space,
                max_vertices=model_vertex_budget,
                model_scale=0.24,
            )
        )
        editable_start = len(meshes)
        if show_candidate:
            source_model = donor_model if mode == "donor_model" and isinstance(donor_model, ModelPreviewData) else target_model
            if self._attachment_visual_model_vertex_count(source_model) > model_vertex_budget:
                simplified_notes.append("Large candidate model was triangle-sampled to keep the editor stable.")
            meshes.extend(
                self._attachment_visual_clone_model_meshes(
                    source_model,
                    offset=donor_offset,
                    pivot=donor_pivot,
                    rotation=donor_rotation,
                    color=(0.28, 0.74, 0.47),
                    clear_textures=bool(1),
                    label_prefix="candidate",
                    placement_scale=donor_scale,
                    use_raw_model_space=donor_uses_raw_space,
                    max_vertices=model_vertex_budget,
                    model_scale=0.24,
                )
            )
        for mesh_index, mesh in enumerate(meshes):
            if not isinstance(mesh, ModelPreviewMesh):
                continue
            mesh.source_submesh_index = int(mesh_index)
            mesh.preview_role = "replacement_preview" if show_candidate and mesh_index >= editable_start else "original_reference"
        editable_indices = tuple(
            int(mesh.source_submesh_index)
            for mesh in meshes[editable_start:]
            if isinstance(mesh, ModelPreviewMesh) and int(mesh.source_submesh_index) >= 0
        ) if show_candidate else ()
        if mode == "donor_model" and isinstance(donor_model, ModelPreviewData):
            summary_subject = "Placement source model at source placement"
        elif show_candidate and donor_evidence is not None:
            summary_subject = "Target model using candidate placement"
        else:
            summary_subject = "Target model current placement"
        vertex_count = sum(len(mesh.positions) for mesh in meshes)
        face_count = sum(len(mesh.indices) // 3 for mesh in meshes)
        source_summary = "Skeleton socket placement"
        target_source = (
            str(target_context.get("placement_source_summary", "") or "")
            if isinstance(target_context, Mapping)
            else "socket-name proxy fallback"
        )
        donor_source = (
            str(effective_donor_context.get("placement_source_summary", "") or "")
            if isinstance(effective_donor_context, Mapping)
            else "socket-name proxy fallback"
        )
        simplification_summary = f"\n{' '.join(simplified_notes)}" if simplified_notes else ""
        return (
            ModelPreviewData(
                path=str(getattr(target_model, "path", "") or "attachment-placement-preview"),
                format="placement-preview",
                summary=(
                    f"{summary_subject}\n"
                    f"Current: {target_label}\n"
                    f"Candidate: {donor_label}\n"
                    f"{source_summary}: current [{target_source}], candidate [{donor_source}].\n"
                    "Body proxy is socket-name based only when PAB/socket XML evidence is unavailable; final export writes loose package files only."
                    f"{simplification_summary}"
                ),
                mesh_count=len(meshes),
                vertex_count=vertex_count,
                face_count=face_count,
                normalization_center=(0.0, 0.0, 0.0),
                normalization_scale=1.0,
                meshes=meshes,
            ),
            editable_indices,
        )
