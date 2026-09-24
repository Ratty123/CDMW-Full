//! Island selection and visibility. Output inclusion remains a host transaction.
use super::*;
use cdmw_mesh::FaceHandle;
use egui::{Button, ScrollArea};
use std::hash::{Hash, Hasher};

#[derive(Clone)]
pub(super) struct HiddenIsland {
    part: u32,
    faces: Vec<u32>,
    topology: u64,
}

impl LabApplication {
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
        let handles = self.island_handles(part, &faces);
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
        let parts = self.cdmw_state["mesh_islands"]["parts"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        ui.separator();
        ui.strong("Mesh islands");
        ui.small("Select a part, then an island to move, scale or edit it.");
        ui.small("View: viewport only · Mod: include in exported PAC");
        let editing = self.cdmw_state["replacement"]["comparison"]
            .as_str()
            .is_none_or(|mode| mode == "edit");
        ui.add_enabled_ui(!self.cdmw_busy() && editing, |ui| {
            if ui.add_enabled(!self.cdmw_hidden_islands.is_empty(), Button::new("Show all islands")).clicked() {
                actions.push(UiAction::ShowAllIslands);
            }
            ScrollArea::vertical().id_salt("cdmw_mesh_islands").max_height(180.0).show(ui, |ui| {
                for row in parts {
                    let part = row["index"].as_u64().unwrap_or_default() as u32;
                    let selected_faces: HashSet<_> = self.mesh.as_ref().into_iter().flat_map(|mesh|
                        mesh.selection.faces.iter().filter_map(|handle| match mesh.face(*handle)?.provenance {
                            Provenance::Source { submesh, element } if submesh == part => Some(element),
                            _ => None,
                        })).collect();
                    ui.weak(row["name"].as_str().unwrap_or("Part"));
                    for (index, island) in row["islands"].as_array().into_iter().flatten().enumerate() {
                        let faces = island_faces(island);
                        let mut shown = !self.cdmw_hidden_islands.iter().any(|hidden| hidden.part == part && hidden.faces == faces);
                        let selected = !faces.is_empty() && faces.iter().all(|face| selected_faces.contains(face));
                        ui.push_id((part, index), |ui| ui.horizontal(|ui| {
                            if ui.checkbox(&mut shown, "View").changed() {
                                actions.push(UiAction::SetIslandVisibility { part, faces: faces.clone(), visible: shown });
                            }
                            let mut included = island["included"].as_bool().unwrap_or(true);
                            if ui.add_enabled(row["available"].as_bool().unwrap_or(false), egui::Checkbox::new(&mut included, "Mod"))
                                .on_disabled_hover_text(row["reason"].as_str().unwrap_or_default())
                                .on_hover_text("Reversible output exclusion across all LODs; keeps the part and material")
                                .changed() {
                                    actions.push(UiAction::CdmwCommand { command: "replacement_islands",
                                        arguments: json!({"part_id": row["part_id"], "faces": faces, "included": included}),
                                        label: "Change island output inclusion" });
                            }
                            if ui.add_enabled(shown, Button::selectable(selected, format!("Island {} · {} faces", index + 1, faces.len()))).clicked() {
                                actions.push(UiAction::SelectIsland { part, faces: faces.clone() });
                            }
                            if ui.small_button("Isolate").on_hover_text("Show only this island within its part").clicked() {
                                actions.push(UiAction::IsolateIsland { part, faces: faces.clone() });
                            }
                        }));
                    }
                }
            });
        });
        ui.small("Coincident seam vertices are grouped without welding the model.");
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
