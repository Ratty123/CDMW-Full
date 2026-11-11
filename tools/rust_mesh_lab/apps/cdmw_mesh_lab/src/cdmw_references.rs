//! View-only set pieces never enter WorkingMesh, selection or outgoing documents.
use crate::cdmw_session::LoadedReferencePiece;
use crate::{DrawSnapshot, LabApplication, MeshDocument, UiAction, WindowRenderer};

pub(crate) fn material_offset(document: Option<&MeshDocument>) -> u32 {
    document.map_or(0, |document| {
        document
            .lods
            .iter()
            .map(|lod| lod.submeshes.len() as u32)
            .max()
            .unwrap_or(0)
    })
}

pub(crate) fn upload_materials(
    renderer: &mut WindowRenderer,
    pieces: &[LoadedReferencePiece],
    document: Option<&MeshDocument>,
) -> anyhow::Result<()> {
    let lod_count = document.map_or(1, |document| document.lods.len());
    let mut offset = material_offset(document);
    for piece in pieces {
        for texture in &piece.textures {
            let ownership = texture
                .material_indices_by_lod
                .first()
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .map(|index| index + offset)
                .collect::<Vec<_>>();
            renderer.add_dds_texture(&texture.bytes, texture.role, &vec![ownership; lod_count])?;
        }
        for presentation in piece
            .material_presentations
            .iter()
            .filter(|row| row.lod_index == 0)
        {
            renderer.add_material_factors(
                crate::cdmw_material_preview_factors(presentation),
                &vec![vec![presentation.material_index + offset]; lod_count],
            )?;
        }
        offset += piece.part_count;
    }
    Ok(())
}

/// Append only draw data. Editable handles, provenance and selection remain intact.
pub(crate) fn append_to_snapshot(
    snapshot: &mut DrawSnapshot,
    pieces: &[LoadedReferencePiece],
    mut offset: u32,
) -> Vec<u32> {
    let mut roles = vec![1; snapshot.positions.len()];
    for piece in pieces {
        if piece.visible {
            let base = snapshot.positions.len() as u32;
            let reference = &piece.snapshot;
            snapshot.positions.extend_from_slice(&reference.positions);
            snapshot.normals.extend_from_slice(&reference.normals);
            snapshot.uvs.extend_from_slice(&reference.uvs);
            snapshot
                .shader_masks
                .extend_from_slice(&reference.shader_masks);
            snapshot
                .indices
                .extend(reference.indices.iter().map(|index| index + base));
            snapshot.triangle_materials.extend(
                reference
                    .triangle_materials
                    .iter()
                    .map(|index| index + offset),
            );
            roles.resize(snapshot.positions.len(), 0);
            // A visibility change must invalidate the renderer's cached draw data.
            snapshot.fingerprint.push_str(&format!(
                ":reference:{}:{}",
                piece.index, reference.fingerprint
            ));
            snapshot.draw_revision = snapshot
                .draw_revision
                .wrapping_add(reference.draw_revision + piece.index as u64);
            snapshot.topology_generation = snapshot
                .topology_generation
                .wrapping_add(piece.index as u64);
        }
        offset += piece.part_count;
    }
    roles
}

pub(crate) fn upload_scene(
    renderer: &mut WindowRenderer,
    snapshot: &DrawSnapshot,
    pieces: &[LoadedReferencePiece],
    offset: u32,
    colours: Option<&[[f32; 4]]>,
    deformation: Option<&[[f32; 3]]>,
    interactive: bool,
) -> Result<(), cdmw_render_wgpu::RenderError> {
    if pieces.is_empty() {
        return if let Some(colours) = colours {
            renderer.set_snapshot_with_vertex_colours(snapshot, colours)
        } else if interactive {
            renderer.set_snapshot_with_deformation_interactive(snapshot, deformation)
        } else {
            renderer.set_snapshot_with_deformation(snapshot, deformation)
        };
    }
    let mut scene = snapshot.clone();
    let roles = append_to_snapshot(&mut scene, pieces, offset);
    let colours = colours.map(|colours| {
        let mut colours = colours.to_vec();
        colours.resize(scene.positions.len(), [0.55, 0.55, 0.55, 1.0]);
        colours
    });
    let deformation = deformation.map(|positions| {
        let mut positions = positions.to_vec();
        positions.extend_from_slice(&scene.positions[snapshot.positions.len()..]);
        positions
    });
    renderer.set_editor_scene(
        &scene,
        &roles,
        colours.as_deref(),
        deformation.as_deref(),
        interactive,
    )
}

impl LabApplication {
    pub(crate) fn frame_item_set(&mut self) {
        if let Some(mesh) = &self.mesh {
            let positions = mesh
                .vertices()
                .map(|(_, vertex)| glam::Vec3::from_array(vertex.position))
                .chain(
                    self.cdmw_reference_pieces
                        .iter()
                        .filter(|piece| piece.visible)
                        .flat_map(|piece| {
                            piece
                                .snapshot
                                .positions
                                .iter()
                                .copied()
                                .map(glam::Vec3::from_array)
                        }),
                );
            if let Some(rectangle) = self.viewport_rect {
                self.camera
                    .frame_positions_in_viewport(positions, rectangle);
            } else {
                self.camera.frame_positions(positions);
            }
        }
    }

    pub(crate) fn draw_item_set_references(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
    ) {
        if self.cdmw_reference_pieces.is_empty() {
            return;
        }
        let set_files = self
            .cdmw_bridge
            .as_ref()
            .is_some_and(|bridge| !bridge.manifest().item_set_files.is_empty());
        // Companions of a single file (eyes, teeth) are references too, but
        // there is no other set file to switch to.
        if set_files {
            ui.menu_button(crate::localization::tr("Switch editable piece"), |ui| {
                if let Some(bridge) = &self.cdmw_bridge {
                    for (index, name) in bridge.manifest().item_set_files.iter().enumerate() {
                        if ui.add_enabled(index > 0, egui::Button::new(name)).clicked() {
                            actions.push(UiAction::SwitchItemPiece(index));
                            ui.close();
                        }
                    }
                }
            });
        }
        let mut changed = false;
        crate::localization::collapsing("Reference pieces").show(ui, |ui| {
            for piece in &mut self.cdmw_reference_pieces {
                ui.horizontal(|ui| {
                    changed |= ui
                        .checkbox(&mut piece.visible, crate::localization::tr("View"))
                        .changed();
                    ui.label(&piece.name)
                        .on_hover_text(crate::localization::tr("Reference (read-only)"));
                });
            }
        });
        if changed {
            self.refresh_cdmw_mesh_display();
        }
        ui.separator();
    }
}
