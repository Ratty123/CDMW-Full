//! Island selection and visibility. Output inclusion remains a host transaction.
use super::*;
use cdmw_mesh::{DrawSnapshot, FaceHandle};
use egui::{Button, ScrollArea};
use std::hash::{Hash, Hasher};

pub(super) fn island_colour(part: u32, first_face: u32) -> [f32; 4] {
    viewport::part_colour(part.wrapping_mul(0x9e37_79b9).wrapping_add(first_face))
}

pub(super) fn identity_colour_snapshot(
    mesh: &WorkingMesh, visible: Option<&HashSet<u32>>, snapshot: &DrawSnapshot,
    island_faces: Option<&Value>,
) -> Vec<[f32; 4]> {
    let Some(islands) = island_faces else {
        return viewport::part_colour_snapshot(mesh, visible, snapshot);
    };
    let elements = visible.map(|parts| mesh.element_handles_for_submeshes(parts));
    let mut colours = vec![[0.0; 4]; snapshot.positions.len()];
    let mut palette = HashMap::new();
    for ((_, face), triangle) in mesh.faces().filter(|(handle, _)|
        elements.as_ref().is_none_or(|elements| elements.faces.contains(handle)))
        .zip(snapshot.indices.chunks_exact(3))
    {
        let root = match face.provenance {
            Provenance::Source { submesh, element } if submesh == face.submesh =>
                islands[submesh as usize][element as usize].as_u64().and_then(|root| u32::try_from(root).ok()),
            _ => None,
        };
        // Unmapped local geometry has no authoritative island name yet.
        let colour = root.map_or([0.55, 0.55, 0.55, 0.88], |root|
            *palette.entry((face.submesh, root)).or_insert_with(|| island_colour(face.submesh, root)));
        for index in triangle {
            colours[*index as usize] = colour;
        }
    }
    colours
}

#[derive(Clone)]
pub(super) struct HiddenIsland {
    part: u32,
    faces: Vec<u32>,
    topology: u64,
}

impl LabApplication {
    pub(crate) fn cdmw_island_name_atoms<'a>(
        &self, part: u32, faces: &[u32], label: impl egui::IntoAtoms<'a>,
    ) -> egui::Atoms<'a> {
        let colour = faces.first().filter(|_| self.cdmw_island_colours_active())
            .map(|root| island_colour(part, *root));
        crate::cdmw_ui::cdmw_colour_name_atoms(label, colour)
    }

    pub(crate) fn cdmw_island_colours_active(&self) -> bool {
        self.cdmw_island_colours && self.cdmw_identity_colours_active()
    }

    pub(crate) fn cdmw_render_display_mode(&self) -> ViewMode {
        if self.view_mode == ViewMode::PartId && self.cdmw_island_colours && !self.cdmw_island_colours_active() {
            self.cdmw_part_colours_previous_mode
        } else {
            self.view_mode
        }
    }

    pub(super) fn set_cdmw_island_colours(&mut self, enabled: bool) {
        if enabled {
            if self.view_mode != ViewMode::PartId {
                self.cdmw_part_colours_previous_mode = self.view_mode;
            }
            self.view_mode = ViewMode::PartId;
        } else {
            self.view_mode = self.cdmw_part_colours_previous_mode;
        }
        self.cdmw_island_colours = enabled;
        self.refresh_cdmw_mesh_display();
    }

    pub(crate) fn draw_cdmw_island_colour_option(&mut self, ui: &mut egui::Ui) {
        let mut enabled = self.view_mode == ViewMode::PartId && self.cdmw_island_colours;
        let available = self.cdmw_state["mesh_islands"]["color_faces"].is_array();
        if ui.add_enabled(available || enabled, egui::Checkbox::new(&mut enabled, crate::localization::tr("Island colors")))
            .on_hover_text(crate::localization::tr("Give each Mesh Island a different color with matching list swatches. Edit view only; fitting and exports stay unchanged."))
            .changed()
        {
            self.set_cdmw_island_colours(enabled);
        }
    }

    pub(super) fn selected_refit_islands(&self, bound: &[u32]) -> Vec<(u32, Vec<u32>)> {
        let selected: HashSet<_> = self.mesh.as_ref().into_iter().flat_map(|mesh|
            mesh.selection.faces.iter().filter_map(|handle| match mesh.face(*handle)?.provenance {
                Provenance::Source { submesh, element } => Some((submesh, element)),
                _ => None,
            })).collect();
        self.cdmw_state["mesh_islands"]["fit_parts"].as_array().into_iter().flatten()
            .filter_map(|part| Some((part["index"].as_u64()? as u32, part["islands"].as_array()?)))
            .filter(|(part, _)| bound.contains(part))
            .flat_map(|(part, islands)| {
                let selected = &selected;
                islands.iter().filter_map(move |island| {
                let faces = island_faces(island);
                (!faces.is_empty() && faces.iter().all(|face| selected.contains(&(part, *face))))
                    .then_some((part, faces))
                })
            }).collect()
    }

    fn island_topology(&self, part: u32) -> Option<u64> {
        let part = self
            .document
            .as_ref()?
            .lods
            .get(self.active_lod_index)?
            .submeshes
            .get(part as usize)?;
        let mut hash = std::collections::hash_map::DefaultHasher::new();
        part.name.hash(&mut hash);
        part.positions.len().hash(&mut hash);
        part.indices.hash(&mut hash);
        Some(hash.finish())
    }

    fn island_handles(&self, part: u32, faces: &[u32]) -> HashSet<FaceHandle> {
        let faces: HashSet<_> = faces.iter().copied().collect();
        self.mesh.as_ref().map_or_else(HashSet::new, |mesh| {
            mesh.faces()
                .filter_map(|(handle, face)| match face.provenance {
                    Provenance::Source { submesh, element }
                        if submesh == part && faces.contains(&element) =>
                    {
                        Some(handle)
                    }
                    _ => None,
                })
                .collect()
        })
    }

    pub(super) fn sync_island_visibility(&mut self) {
        let editing = self.cdmw_state["replacement"]["comparison"]
            .as_str()
            .is_none_or(|mode| mode == "edit");
        if editing {
            let retained = self
                .cdmw_hidden_islands
                .iter()
                .filter(|island| self.island_topology(island.part) == Some(island.topology))
                .cloned()
                .collect();
            self.cdmw_hidden_islands = retained;
        }
        let hidden = if editing {
            self.cdmw_hidden_islands
                .iter()
                .flat_map(|island| self.island_handles(island.part, &island.faces))
                .collect()
        } else {
            HashSet::new()
        };
        if let Some(mesh) = &mut self.mesh {
            let _ = mesh.set_viewport_hidden_faces(hidden.clone());
        }
        if let Some(reference) = &mut self.deformation_reference
            && reference.mesh.viewport_hidden_faces() != &hidden
            && reference.mesh.set_viewport_hidden_faces(hidden).is_ok()
        {
            reference.positions = reference
                .mesh
                .draw_snapshot_for_submeshes(&reference.mesh.submesh_indices())
                .positions;
            reference.visible_submeshes = None;
        }
    }

    pub(super) fn set_island_visibility(&mut self, part: u32, faces: Vec<u32>, visible: bool) {
        self.cdmw_hidden_islands
            .retain(|island| island.part != part || island.faces != faces);
        if !visible && let Some(topology) = self.island_topology(part) {
            self.cdmw_hidden_islands.push(HiddenIsland {
                part,
                faces,
                topology,
            });
        }
        self.sync_island_visibility();
        // Use the shared part/layer filter to clip all element selection domains.
        self.set_cdmw_part_visibility(Vec::new(), true);
    }

    pub(super) fn select_island(&mut self, part: u32, faces: Vec<u32>) {
        self.select_islands(vec![(part, faces)]);
    }

    pub(super) fn select_islands(&mut self, islands: Vec<(u32, Vec<u32>)>) {
        let handles = islands.iter().flat_map(|(part, faces)| self.island_handles(*part, faces)).collect::<HashSet<_>>();
        let visible = self.cdmw_visible_submeshes();
        if let Some(mesh) = &mut self.mesh {
            let allowed = visible
                .as_ref()
                .map(|parts| mesh.element_handles_for_submeshes(parts));
            let selection = Selection {
                faces: handles
                    .into_iter()
                    .filter(|handle| {
                        allowed
                            .as_ref()
                            .is_none_or(|allowed| allowed.faces.contains(handle))
                    })
                    .collect(),
                ..Selection::default()
            };
            if mesh.set_selection(selection).is_ok() {
                self.selection_domain = SelectionDomain::Face;
                self.submit_cdmw_local_edit(CdmwLocalEdit::Selection(
                    "Select mesh island".to_owned(),
                ));
            }
        }
        self.publish_mesh_snapshot();
    }

    pub(super) fn isolate_island(&mut self, part: u32, faces: Vec<u32>) {
        let groups = self.cdmw_state["mesh_islands"]["parts"]
            .as_array()
            .and_then(|parts| {
                parts
                    .iter()
                    .find(|row| row["index"].as_u64() == Some(u64::from(part)))
            })
            .and_then(|row| row["islands"].as_array())
            .cloned()
            .unwrap_or_default();
        self.cdmw_hidden_islands
            .retain(|island| island.part != part);
        if let Some(topology) = self.island_topology(part) {
            for group in groups {
                let other = island_faces(&group);
                if other != faces {
                    self.cdmw_hidden_islands.push(HiddenIsland {
                        part,
                        faces: other,
                        topology,
                    });
                }
            }
        }
        self.sync_island_visibility();
        self.select_island(part, faces);
    }

    pub(super) fn draw_cdmw_islands(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        use crate::cdmw_ui::{cdmw_list_cell, cdmw_list_columns, cdmw_list_header};
        self.draw_cdmw_island_colour_option(ui);
        let parts = self.cdmw_state["mesh_islands"]["parts"].as_array().cloned().unwrap_or_default();
        let editing = self.cdmw_state["replacement"]["comparison"].as_str().is_none_or(|mode| mode == "edit");
        ui.add_enabled_ui(!self.cdmw_busy() && editing, |ui| {
            if ui.add_enabled(!self.cdmw_hidden_islands.is_empty(), Button::new(crate::localization::tr("Show all islands"))).clicked() {
                actions.push(UiAction::ShowAllIslands);
            }
            ui.separator();
            ScrollArea::vertical().id_salt("cdmw_mesh_islands").auto_shrink([false, false]).show(ui, |ui| {
                if parts.is_empty() {
                    ui.small(crate::localization::tr("Select a part, then an island to move, scale or edit it."));
                }
                let widths = cdmw_list_columns(ui, "Isolate");
                let headers = cdmw_list_header(ui, widths, "Island", "");
                ui.spacing_mut().item_spacing.y = 2.0;
                for row in parts {
                    let part = row["index"].as_u64().unwrap_or_default() as u32;
                    let selected_faces: HashSet<_> = self.mesh.as_ref().into_iter().flat_map(|mesh|
                        mesh.selection.faces.iter().filter_map(|handle| match mesh.face(*handle)?.provenance {
                            Provenance::Source { submesh, element } if submesh == part => Some(element),
                            _ => None,
                        })).collect();
                    ui.push_id(part, |ui| {
                        ui.separator();
                        let name = row["name"].as_str().map(str::to_owned).unwrap_or_else(|| crate::localization::tr("Part"));
                        ui.add(egui::Label::new(egui::RichText::new(&name).strong()).truncate()).on_hover_text(&name);
                        if !row["available"].as_bool().unwrap_or(false)
                            && let Some(reason) = row["reason"].as_str().filter(|reason| !reason.is_empty()) {
                            ui.add(egui::Label::new(crate::localization::tr(reason)).wrap());
                        }
                        for (index, island) in row["islands"].as_array().into_iter().flatten().enumerate() {
                            let faces = island_faces(island);
                            let mut shown = !self.cdmw_hidden_islands.iter().any(|hidden| hidden.part == part && hidden.faces == faces);
                            let selected = !faces.is_empty() && faces.iter().all(|face| selected_faces.contains(face));
                            let mut name_response = None;
                            ui.push_id(index, |ui| ui.horizontal(|ui| {
                                let title = crate::localization::tr(format!("Island {} · {} faces", index + 1, faces.len()));
                                cdmw_list_cell(ui, widths[0], |ui| {
                                    let response = ui.add_enabled_ui(shown, |ui| {
                                        ui.add_sized([ui.available_width(), ui.spacing().interact_size.y],
                                            Button::selectable(selected, self.cdmw_island_name_atoms(
                                                part, &faces, (&title, egui::Atom::grow()))).truncate())
                                    }).inner;
                                    name_response = Some(response.clone());
                                    if response.on_hover_text(&title).clicked() {
                                        actions.push(UiAction::SelectIsland { part, faces: faces.clone() });
                                    }
                                });
                                cdmw_list_cell(ui, widths[1], |ui| {
                                    if ui.small_button(crate::localization::tr("Isolate"))
                                        .on_hover_text(crate::localization::tr("Show only this island within its part")).clicked() {
                                        actions.push(UiAction::IsolateIsland { part, faces: faces.clone() });
                                    }
                                });
                                cdmw_list_cell(ui, widths[2], |ui| {
                                    ui.with_layout(egui::Layout::centered_and_justified(egui::Direction::LeftToRight), |ui| {
                                        if ui.add(egui::Checkbox::without_text(&mut shown)).labelled_by(headers[0])
                                            .on_hover_text(crate::localization::tr("View: viewport only · Include: exported mesh")).changed() {
                                            actions.push(UiAction::SetIslandVisibility { part, faces: faces.clone(), visible: shown });
                                        }
                                    });
                                });
                                cdmw_list_cell(ui, widths[3], |ui| {
                                    let mut included = island["included"].as_bool().unwrap_or(true);
                                    ui.with_layout(egui::Layout::centered_and_justified(egui::Direction::LeftToRight), |ui| {
                                        if ui.add_enabled(row["available"].as_bool().unwrap_or(false), egui::Checkbox::without_text(&mut included))
                                            .labelled_by(headers[1])
                                            .on_disabled_hover_text(crate::localization::tr(row["reason"].as_str().unwrap_or_default()))
                                            .on_hover_text(crate::localization::tr("Reversible output exclusion across all LODs; keeps the part and material")).changed() {
                                            actions.push(UiAction::CdmwCommand { command: "replacement_islands",
                                                arguments: json!({"part_id": row["part_id"], "faces": faces, "included": included}),
                                                label: "Change island output inclusion" });
                                        }
                                    });
                                });
                            }));
                            if let Some(response) = name_response {
                                self.track_cdmw_island_name(ui, part, faces, &response);
                            }
                        }
                    });
                }
            });
        });
    }
}

fn island_faces(row: &Value) -> Vec<u32> {
    row["faces"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|value| value.as_u64().and_then(|value| u32::try_from(value).ok()))
        .collect()
}
