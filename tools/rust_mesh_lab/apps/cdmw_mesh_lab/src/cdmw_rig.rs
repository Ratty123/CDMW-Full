//! Rig inspection stays display-only until the user explicitly selects vertices.

use super::*;
use crate::cdmw_ui::{state_bool, state_str, state_u64, value_u32_list};
use egui::{Button, ComboBox};

pub(super) struct RigView {
    pub search: String,
    pub show_weights: bool,
    pub available: bool,
    pub reason: String,
    pub weights: HashMap<(u32, u32), f32>,
    influence: Value,
    active_bone: Option<i64>,
    pub overlay_key: Option<(u64, u64, bool)>,
    visible: Option<HashSet<u32>>,
    pub positions: Vec<[f32; 3]>,
    pub colours: Vec<[f32; 4]>,
    uploaded: bool,
}

impl Default for RigView {
    fn default() -> Self {
        Self {
            search: String::new(),
            show_weights: true,
            available: false,
            reason: "Choose a bone to inspect its influence.".to_owned(),
            weights: HashMap::new(),
            influence: Value::Null,
            active_bone: None,
            overlay_key: None,
            visible: None,
            positions: Vec::new(),
            colours: Vec::new(),
            uploaded: false,
        }
    }
}

impl RigView {
    pub fn update(&mut self, state: &Value) {
        let influence = state.get("rig_influence").unwrap_or(&Value::Null);
        let active = state["skeleton"]["selected_bone_index"].as_i64();
        if &self.influence == influence && self.active_bone == active {
            return;
        }
        self.active_bone = active;
        self.influence = influence.clone();
        self.overlay_key = None;
        self.weights.clear();
        self.available = false;
        self.reason = state_str(influence, "reason")
            .unwrap_or("Weight display is unavailable for this mesh.")
            .to_owned();
        if !state_bool(influence, "available") {
            return;
        }
        if active.is_none() || active != influence["bone_index"].as_i64() {
            self.reason = "Waiting for the active bone's weights.".to_owned();
            return;
        }
        let parsed = parse_influence(influence);
        match parsed {
            Some(weights) => {
                self.weights = weights;
                self.available = true;
            }
            None => self.reason = "The host supplied incomplete weight display data.".to_owned(),
        }
    }

    fn prepare(&mut self, mesh: &WorkingMesh, visible: Option<HashSet<u32>>, enabled: bool) {
        let key = (mesh.geometry_revision, mesh.topology_generation, enabled);
        if self.overlay_key == Some(key) && self.visible == visible {
            return;
        }
        self.positions.clear();
        self.colours.clear();
        if enabled {
            let parts = self
                .weights
                .keys()
                .map(|(part, _)| *part)
                .collect::<HashSet<_>>();
            for (_, face) in mesh.faces() {
                if !parts.contains(&face.submesh)
                    || visible
                        .as_ref()
                        .is_some_and(|shown| !shown.contains(&face.submesh))
                {
                    continue;
                }
                let vertices = face.vertices.map(|handle| mesh.vertex(handle));
                let [Some(a), Some(b), Some(c)] = vertices else {
                    continue;
                };
                for vertex in [a, b, c] {
                    let weight = match vertex.provenance {
                        Provenance::Source { submesh, element } => self
                            .weights
                            .get(&(submesh, element))
                            .copied()
                            .unwrap_or(0.0),
                        Provenance::Generated { .. } => 0.0,
                    };
                    self.positions.push(vertex.position);
                    self.colours.push(weight_colour(weight));
                }
            }
        }
        self.overlay_key = Some(key);
        self.visible = visible;
        self.uploaded = false;
    }
}

fn parse_influence(value: &Value) -> Option<HashMap<(u32, u32), f32>> {
    let count = usize::try_from(value["vertex_count"].as_u64()?).ok()?;
    if count > 131_072 {
        return None;
    }
    let mut result = HashMap::with_capacity(count);
    for part in value["parts"].as_array()? {
        let submesh = u32::try_from(part["submesh_index"].as_u64()?).ok()?;
        for row in part["weights"].as_array()? {
            let row = row.as_array()?;
            if row.len() != 2 {
                return None;
            }
            let vertex = u32::try_from(row[0].as_u64()?).ok()?;
            let weight = row[1].as_f64()? as f32;
            if !weight.is_finite()
                || weight <= 0.0
                || weight > 1.0
                || result.insert((submesh, vertex), weight).is_some()
                || result.len() > count
            {
                return None;
            }
        }
    }
    (result.len() == count).then_some(result)
}

/// A restrained blue-to-gold scale, shared by the surface and its labelled legend.
fn weight_colour(weight: f32) -> [f32; 4] {
    let stops = [[0.10, 0.16, 0.24], [0.10, 0.68, 0.76], [1.0, 0.72, 0.18]];
    let t = weight.clamp(0.0, 1.0) * 2.0;
    let start = usize::from(t > 1.0);
    let fraction = t - start as f32;
    let rgb: [f32; 3] = std::array::from_fn(|i| {
        stops[start][i] * (1.0 - fraction) + stops[start + 1][i] * fraction
    });
    [rgb[0], rgb[1], rgb[2], 0.86]
}

fn file_label(path: &str) -> &str {
    path.rsplit(['/', '\\'])
        .next()
        .filter(|name| !name.is_empty())
        .unwrap_or(path)
}

impl LabApplication {
    fn draw_rig_identity(&self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>, skeleton: &Value) {
        ui.label(RichText::new("Loaded mesh").strong());
        ui.add(egui::Label::new(file_label(&self.source_label)).truncate())
            .on_hover_text(&self.source_label);
        let parts = skeleton["parts"].as_array().cloned().unwrap_or_default();
        let selected_parts = self.selected_part_indices();
        if !parts.is_empty() {
            ui.collapsing(format!("Loaded parts ({})", parts.len()), |ui| {
                egui::ScrollArea::vertical()
                    .id_salt("rig_loaded_parts")
                    .max_height(110.0)
                    .show(ui, |ui| {
                        for part in &parts {
                            let index = state_u64(part, "index") as u32;
                            let name = state_str(part, "name")
                                .filter(|name| !name.is_empty())
                                .map(str::to_owned)
                                .unwrap_or_else(|| format!("Part {index}"));
                            if ui
                                .selectable_label(selected_parts.contains(&index), &name)
                                .on_hover_text(format!(
                                    "{} vertices · {} weighted. Select this Part in the viewport.",
                                    state_u64(part, "vertex_count"),
                                    state_u64(part, "weighted_vertex_count")
                                ))
                                .clicked()
                            {
                                actions.push(UiAction::SetPartSelection(vec![index]));
                            }
                        }
                    });
            });
        }
        let rig = state_str(skeleton, "skeleton_source").unwrap_or("");
        let bone_count = skeleton["bones"].as_array().map_or(0, Vec::len);
        if bone_count > 0 && !rig.is_empty() {
            ui.horizontal(|ui| {
                ui.label(RichText::new("Rig loaded").strong());
                ui.add(egui::Label::new(file_label(rig)).truncate())
                    .on_hover_text(format!(
                        "{rig}\nAttached automatically from this mesh's dependencies."
                    ));
            });
            ui.small(format!(
                "{} weighted vertices · {bone_count} bones",
                state_u64(skeleton, "weighted_vertex_count")
            ));
        } else {
            ui.colored_label(ui.visuals().warn_fg_color, "No named rig attached");
        }
    }

    fn draw_rig_inspection(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        skeleton: &Value,
    ) {
        let selected = skeleton["selected_bone_index"].as_i64().unwrap_or(-1);
        if let Some(bone) = skeleton["bones"]
            .as_array()
            .into_iter()
            .flatten()
            .find(|bone| bone["index"].as_i64() == Some(selected))
        {
            let parent = state_str(bone, "parent_name")
                .filter(|name| !name.is_empty())
                .unwrap_or("Root");
            let children = state_u64(bone, "child_count");
            ui.small(format!(
                "Parent: {parent} · {children} {}",
                if children == 1 { "child" } else { "children" }
            ));
        }
        if selected < 0 {
            ui.small("Choose a bone to locate it and see its weights.");
        } else if self.cdmw_rig.available {
            let part_ids = self
                .cdmw_rig
                .weights
                .keys()
                .map(|(part, _)| *part)
                .collect::<BTreeSet<_>>();
            if self.cdmw_rig.weights.is_empty() {
                ui.small("This bone has no influence on the loaded mesh.");
            } else {
                let names = skeleton["parts"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter(|part| part_ids.contains(&(state_u64(part, "index") as u32)))
                    .filter_map(|part| state_str(part, "name"))
                    .collect::<Vec<_>>()
                    .join(", ");
                ui.label(format!(
                    "{} influenced vertices · {} {}",
                    self.cdmw_rig.weights.len(),
                    part_ids.len(),
                    if part_ids.len() == 1 { "part" } else { "parts" }
                ));
                if !names.is_empty() {
                    ui.add(egui::Label::new(RichText::new(&names).small()).truncate())
                        .on_hover_text(&names);
                }
            }
        } else {
            ui.small(&self.cdmw_rig.reason);
        }
        ui.horizontal_wrapped(|ui| {
            ui.add_enabled(self.cdmw_rig.available, egui::Checkbox::new(&mut self.cdmw_rig.show_weights, "Weight colours"))
                .on_hover_text("Shows the active bone's influence on the surface. The colours are a preview and do not change the mesh material.");
            ui.add_enabled(!self.skeleton_overlay_lines.is_empty(), egui::Checkbox::new(&mut self.show_bones, "Skeleton"))
                .on_hover_text(&self.cdmw_skeleton_overlay_reason)
                .on_disabled_hover_text(&self.cdmw_skeleton_overlay_reason);
        });
        if self.cdmw_rig.show_weights && self.cdmw_rig.available {
            ui.horizontal(|ui| {
                for (weight, label) in [(0.0, "0%"), (0.5, "50%"), (1.0, "100% weight")] {
                    let rgba = weight_colour(weight);
                    let colour = Color32::from_rgb(
                        (rgba[0] * 255.0) as u8,
                        (rgba[1] * 255.0) as u8,
                        (rgba[2] * 255.0) as u8,
                    );
                    let (rect, _) =
                        ui.allocate_exact_size(egui::vec2(12.0, 12.0), egui::Sense::hover());
                    ui.painter().rect_filled(rect, 2.0, colour);
                    ui.small(label);
                }
            });
        }
        let visible_count = self.rig_influenced_vertices().len();
        let has_influence = visible_count > 0;
        if visible_count < self.cdmw_rig.weights.len() {
            ui.weak(format!(
                "{} influenced vertices are in hidden Parts",
                self.cdmw_rig.weights.len() - visible_count
            ));
        }
        ui.horizontal_wrapped(|ui| {
            if ui.add_enabled(self.rig_active_bone().is_some(), Button::new("Frame bone"))
                .on_hover_text("Centre the camera on the labelled bone without changing the edit selection.").clicked() {
                actions.push(UiAction::FrameRigBone);
            }
            if ui.add_enabled(has_influence, Button::new("Frame influence"))
                .on_hover_text("Fit the visible area controlled by this bone without changing the edit selection.").clicked() {
                actions.push(UiAction::FrameRigInfluence);
            }
        });
        if ui.add_enabled(has_influence, Button::new("Select influenced vertices"))
            .on_hover_text("Replace the edit selection with all visible vertices whose weight for this bone is greater than zero, including vertices on the back of the mesh.")
            .on_disabled_hover_text("This bone has no resolved influence on visible Parts.")
            .clicked() {
            actions.push(UiAction::SelectRigInfluence);
        }
    }

    fn rig_active_bone(&self) -> Option<&Value> {
        if self.skeleton_overlay_lines.is_empty() {
            return None;
        }
        let skeleton = &self.cdmw_state["skeleton"];
        let selected = skeleton["selected_bone_index"].as_i64()?;
        skeleton["bones"]
            .as_array()?
            .iter()
            .find(|bone| bone["index"].as_i64() == Some(selected))
    }

    fn rig_bone_points(&self) -> Vec<Vec3> {
        let Some(bone) = self.rig_active_bone() else {
            return Vec::new();
        };
        let selected = bone["index"].as_i64();
        let parent = bone["parent_index"].as_i64();
        let mut points = vec![bone_point(bone)];
        let bones = self.cdmw_state["skeleton"]["bones"]
            .as_array()
            .into_iter()
            .flatten();
        points.extend(
            bones
                .clone()
                .filter(|row| row["parent_index"].as_i64() == selected)
                .map(bone_point),
        );
        if points.len() == 1 {
            points.extend(
                bones
                    .filter(|row| row["index"].as_i64() == parent)
                    .map(bone_point),
            );
        }
        points.into_iter().flatten().collect()
    }

    pub(super) fn rig_influenced_vertices(&self) -> HashSet<VertexHandle> {
        let visible = self.cdmw_visible_submeshes();
        self.mesh
            .as_ref()
            .into_iter()
            .flat_map(WorkingMesh::vertices)
            .filter_map(|(handle, vertex)| {
                let Provenance::Source { submesh, element } = vertex.provenance else {
                    return None;
                };
                (self.cdmw_rig.weights.contains_key(&(submesh, element))
                    && visible
                        .as_ref()
                        .is_none_or(|shown| shown.contains(&submesh)))
                .then_some(handle)
            })
            .collect()
    }

    pub(super) fn frame_rig(&mut self, influence: bool) {
        let Some(rectangle) = self.viewport_rect else {
            return;
        };
        let mut points = if influence {
            self.rig_influenced_vertices()
                .into_iter()
                .filter_map(|handle| {
                    self.mesh
                        .as_ref()?
                        .vertex(handle)
                        .map(|v| Vec3::from_array(v.position))
                })
                .collect::<Vec<_>>()
        } else {
            self.rig_bone_points()
        };
        if points.is_empty() {
            return;
        }
        // Keep a point-like helper bone at a useful scale instead of zooming into a speck.
        if points
            .iter()
            .all(|p| p.distance_squared(points[0]) < 1.0e-8)
        {
            let extent = self
                .mesh
                .as_ref()
                .map(|mesh| {
                    mesh.vertices().fold(
                        (Vec3::splat(f32::INFINITY), Vec3::splat(f32::NEG_INFINITY)),
                        |(lo, hi), (_, v)| {
                            let p = Vec3::from_array(v.position);
                            (lo.min(p), hi.max(p))
                        },
                    )
                })
                .map_or(1.0, |(lo, hi)| (hi - lo).length());
            let padding = Vec3::splat((extent * 0.04).max(0.01));
            points.extend([points[0] - padding, points[0] + padding]);
        }
        self.camera
            .frame_positions_in_viewport(points.into_iter(), rectangle);
        self.projection = None;
        self.status = if influence {
            "Camera framed the visible influenced vertices"
        } else {
            "Camera framed the active bone"
        }
        .to_owned();
    }

    pub(super) fn paint_rig_overlay(&mut self, ui: &egui::Ui, rectangle: egui::Rect) {
        let active = self.cdmw_rail_page == Some(CdmwRailPage::RigWeights);
        let visible = self.cdmw_visible_submeshes();
        if let Some(mesh) = &self.mesh {
            self.cdmw_rig.prepare(
                mesh,
                visible,
                active && self.cdmw_rig.show_weights && self.cdmw_rig.available,
            );
        }
        if !self.cdmw_rig.uploaded
            && let Some(renderer) = &mut self.renderer
        {
            match renderer.set_rig_weights(&self.cdmw_rig.positions, &self.cdmw_rig.colours) {
                Ok(()) => self.cdmw_rig.uploaded = true,
                Err(error) => self.status = format!("Weight display failed: {error}"),
            }
        }
        if !active {
            return;
        }
        let Some(bone) = self.rig_active_bone() else {
            return;
        };
        let points = self.rig_bone_points();
        let projected = points
            .first()
            .and_then(|p| self.camera.project(*p, rectangle))
            .filter(|p| p.inside_view);
        let anchor = projected.map(|point| egui::pos2(point.screen.x, point.screen.y));
        let painter = ui.painter().with_clip_rect(rectangle);
        let colour = Color32::from_rgb(255, 195, 90);
        if let Some(anchor) = anchor {
            for other in points
                .iter()
                .skip(1)
                .filter_map(|p| self.camera.project(*p, rectangle))
                .filter(|p| p.inside_view)
            {
                let end = egui::pos2(other.screen.x, other.screen.y);
                painter.line_segment(
                    [anchor, end],
                    Stroke::new(4.5, Color32::from_black_alpha(190)),
                );
                painter.line_segment([anchor, end], Stroke::new(2.0, colour));
            }
            painter.circle_filled(anchor, 6.5, Color32::from_black_alpha(210));
            painter.circle_stroke(anchor, 5.0, Stroke::new(2.0, colour));
        }
        let text = if anchor.is_some() {
            format!(
                "{} · Bone {}",
                state_str(bone, "name").unwrap_or("Bone"),
                state_u64(bone, "index")
            )
        } else {
            format!(
                "{} · outside view · Frame bone",
                state_str(bone, "name").unwrap_or("Bone")
            )
        };
        let galley = painter.layout(
            text,
            egui::TextStyle::Body.resolve(ui.style()),
            colour,
            (rectangle.width() - 40.0).max(40.0),
        );
        let size = galley.size() + egui::vec2(16.0, 10.0);
        let origin = anchor.map_or(rectangle.left_top() + egui::vec2(12.0, 36.0), |anchor| {
            egui::pos2(
                (anchor.x + 15.0)
                    .min(rectangle.right() - size.x - 6.0)
                    .max(rectangle.left() + 6.0),
                (anchor.y - size.y - 10.0).max(rectangle.top() + 36.0),
            )
        });
        let label = egui::Rect::from_min_size(origin, size);
        if let Some(anchor) = anchor {
            painter.line_segment([anchor, label.center_bottom()], Stroke::new(1.0, colour));
        }
        painter.rect_filled(label, 4.0, Color32::from_rgba_unmultiplied(22, 27, 34, 235));
        painter.galley(origin + egui::vec2(8.0, 5.0), galley, colour);
    }
}

fn bone_point(bone: &Value) -> Option<Vec3> {
    let row = bone["position"].as_array()?;
    if row.len() != 3 {
        return None;
    }
    let point = Vec3::new(
        row[0].as_f64()? as f32,
        row[1].as_f64()? as f32,
        row[2].as_f64()? as f32,
    );
    point.is_finite().then_some(point)
}

impl LabApplication {
    pub(super) fn draw_cdmw_rig_weights_page(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
    ) {
        let skeleton = self
            .cdmw_state
            .get("skeleton")
            .cloned()
            .unwrap_or(Value::Null);
        let skinned = state_bool(&skeleton, "skinned");
        let source_weights_available = state_bool(&skeleton, "source_weights_available");
        let weight_capability = skeleton
            .get("weight_edit_capability")
            .cloned()
            .unwrap_or(Value::Null);
        let weight_edit_enabled = state_bool(&weight_capability, "enabled");
        let weight_edit_reason = state_str(&weight_capability, "reason")
            .filter(|reason| !reason.trim().is_empty())
            .unwrap_or("The host did not authorize a safe skin-weight output route");
        let palette_size = state_u64(&weight_capability, "palette_size");
        let selected_bone = skeleton
            .get("selected_bone_index")
            .and_then(Value::as_i64)
            .unwrap_or(-1);
        let bones = skeleton
            .get("bones")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        self.draw_rig_identity(ui, actions, &skeleton);
        ui.separator();
        ComboBox::from_label("Active bone")
            .width((ui.available_width() - 100.0).max(100.0))
            .truncate()
            .height(250.0)
            .close_behavior(egui::PopupCloseBehavior::CloseOnClickOutside)
            .selected_text(
                bones
                    .iter()
                    .find(|bone| bone.get("index").and_then(Value::as_i64) == Some(selected_bone))
                    .and_then(|bone| bone.get("name").and_then(Value::as_str))
                    .map(|name| format!("{selected_bone}: {name}"))
                    .unwrap_or_else(|| "Choose bone".to_owned()),
            )
            .show_ui(ui, |ui| {
                ui.add(
                    egui::TextEdit::singleline(&mut self.cdmw_rig.search)
                        .hint_text("Search bones")
                        .desired_width(f32::INFINITY),
                );
                let filter = self.cdmw_rig.search.trim().to_lowercase();
                let mut matches = 0;
                for bone in &bones {
                    let searchable = format!(
                        "{} {}",
                        state_u64(bone, "index"),
                        state_str(bone, "name").unwrap_or("Bone")
                    );
                    if !searchable.to_lowercase().contains(&filter) {
                        continue;
                    }
                    matches += 1;
                    let index = bone.get("index").and_then(Value::as_i64).unwrap_or(-1);
                    let name = bone.get("name").and_then(Value::as_str).unwrap_or("Bone");
                    if ui
                        .selectable_label(index == selected_bone, format!("{index}: {name}"))
                        .clicked()
                    {
                        actions.push(UiAction::CdmwCommand {
                            command: "rig_select_bone",
                            arguments: json!({"bone_index": index}),
                            label: "Select rig bone",
                        });
                        ui.close();
                    }
                }
                if matches == 0 {
                    ui.weak("No matching bones");
                }
            });
        self.draw_rig_inspection(ui, actions, &skeleton);
        ui.separator();
        ui.label(RichText::new("Edit weights").strong());
        let count = self
            .mesh
            .as_ref()
            .map_or(0, |mesh| mesh.selection.vertices.len());
        ui.small(if count == 0 {
            "No vertices selected".to_owned()
        } else {
            format!("Edit selection: {count} vertices")
        });
        if weight_edit_enabled {
            ui.small("Weight editing ready").on_hover_text(format!("{palette_size} PAC palette slots mapped to {} rig bones. Weight edits apply only to the explicit vertex selection.", bones.len()));
        } else {
            ui.colored_label(ui.visuals().warn_fg_color, weight_edit_reason);
        }
        ui.horizontal(|ui| {
            ui.label("Weight step");
            ui.add(
                egui::DragValue::new(&mut self.cdmw_weight_step)
                    .speed(0.01)
                    .range(0.001..=1.0),
            );
        });
        let selected_vertices = self
            .mesh
            .as_ref()
            .is_some_and(|mesh| !mesh.selection.vertices.is_empty());
        let selected_part_indices = self.selected_part_indices();
        let selected_parts = !selected_part_indices.is_empty();
        let eligible_submeshes = value_u32_list(&weight_capability, "eligible_submesh_indices")
            .into_iter()
            .collect::<HashSet<_>>();
        let mut selected_target_submeshes =
            selected_part_indices.into_iter().collect::<HashSet<_>>();
        let mut has_unmappable_target = false;
        if let Some(mesh) = &self.mesh {
            for handle in &mesh.selection.vertices {
                match mesh.vertex(*handle).map(|vertex| vertex.provenance) {
                    Some(Provenance::Source { submesh, .. }) => {
                        selected_target_submeshes.insert(submesh);
                    }
                    Some(Provenance::Generated { .. }) | None => has_unmappable_target = true,
                }
            }
        }
        let has_explicit_weight_target = selected_vertices || selected_parts;
        let target_is_eligible = has_explicit_weight_target
            && !has_unmappable_target
            && selected_target_submeshes
                .iter()
                .all(|submesh| eligible_submeshes.contains(submesh));
        let target_reason = if has_unmappable_target {
            "Generated vertices do not have an exact-safe skin-weight target"
        } else if has_explicit_weight_target && !target_is_eligible {
            "The explicit selection includes vertices or Parts outside the exact-safe skin-weight subset"
        } else {
            "Explicitly select target vertices or Parts first"
        };
        if weight_edit_enabled && has_explicit_weight_target && !target_is_eligible {
            ui.colored_label(Color32::from_rgb(245, 190, 75), target_reason);
        }
        let can_adjust = weight_edit_enabled
            && target_is_eligible
            && skinned
            && selected_vertices
            && selected_bone >= 0;
        let step = self.cdmw_weight_step;
        ui.horizontal_wrapped(|ui| {
            for (label, delta) in [("Weight -", -step), ("Weight +", step)] {
                if ui
                    .add_enabled(can_adjust, Button::new(label))
                    .on_disabled_hover_text(if !weight_edit_enabled {
                        weight_edit_reason
                    } else if !target_is_eligible {
                        target_reason
                    } else {
                        "Choose a bone and explicitly select Vertex elements first"
                    })
                    .clicked()
                {
                    actions.push(UiAction::CdmwCommand {
                        command: "rig_adjust_weight",
                        arguments: json!({"delta": delta}),
                        label,
                    });
                }
            }
            if ui
                .add_enabled(
                    weight_edit_enabled && target_is_eligible && skinned && selected_vertices,
                    Button::new("Normalize Weights"),
                )
                .on_disabled_hover_text(if !weight_edit_enabled {
                    weight_edit_reason
                } else if !target_is_eligible {
                    target_reason
                } else {
                    "Switch Select target to Vertex and explicitly select weighted vertices"
                })
                .clicked()
            {
                actions.push(UiAction::CdmwCommand {
                    command: "rig_normalize_weights",
                    arguments: json!({}),
                    label: "Normalize weights",
                });
            }
        });
        if ui
            .add_enabled(
                weight_edit_enabled
                    && target_is_eligible
                    && source_weights_available
                    && (selected_vertices || selected_parts),
                Button::new("Transfer from Original"),
            )
            .on_disabled_hover_text(if !weight_edit_enabled {
                weight_edit_reason
            } else if !source_weights_available {
                "The immutable source mesh has no transferable skin weights"
            } else if !target_is_eligible {
                target_reason
            } else {
                "Explicitly select target vertices or Parts first"
            })
            .clicked()
        {
            actions.push(UiAction::CdmwCommand {
                command: "rig_transfer_weights",
                arguments: json!({}),
                label: "Transfer source weights",
            });
        }
        let unnormalized = state_u64(&skeleton, "unnormalized_vertex_count");
        if unnormalized > 0 {
            ui.colored_label(
                Color32::from_rgb(245, 190, 75),
                format!("{unnormalized} vertices have unnormalized weights"),
            );
        }
        let selected_weights = skeleton
            .get("selected_vertex_weights")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        if !selected_weights.is_empty() {
            ui.collapsing("Selected vertex weights", |ui| {
                let bone_names = bones
                    .iter()
                    .filter_map(|bone| {
                        Some((
                            bone.get("index")?.as_i64()?,
                            bone.get("name")?.as_str()?.to_owned(),
                        ))
                    })
                    .collect::<HashMap<_, _>>();
                for row in selected_weights.iter().take(8) {
                    let submesh = row
                        .get("submesh_index")
                        .and_then(Value::as_i64)
                        .unwrap_or(-1);
                    let vertex = row
                        .get("vertex_index")
                        .and_then(Value::as_i64)
                        .unwrap_or(-1);
                    let mapped = row
                        .get("influences")
                        .and_then(Value::as_array)
                        .into_iter()
                        .flatten()
                        .filter_map(Value::as_array)
                        .filter_map(|influence| {
                            let bone = influence.first()?.as_i64()?;
                            let weight = influence.get(1)?.as_f64()?;
                            (weight.is_finite() && weight > 0.0).then_some((bone, weight))
                        })
                        .collect::<Vec<_>>();
                    let influences_resolved = row
                        .get("influences_resolved")
                        .and_then(Value::as_bool)
                        .unwrap_or(!mapped.is_empty());
                    let influence_labels = if influences_resolved {
                        mapped
                            .iter()
                            .map(|(bone, weight)| {
                                let name = bone_names
                                    .get(bone)
                                    .cloned()
                                    .unwrap_or_else(|| format!("Bone {bone}"));
                                (name, *weight)
                            })
                            .collect::<Vec<_>>()
                    } else {
                        row.get("influence_labels")
                            .and_then(Value::as_array)
                            .into_iter()
                            .flatten()
                            .filter_map(Value::as_array)
                            .filter_map(|influence| {
                                let label = influence.first()?.as_str()?.to_owned();
                                let weight = influence.get(1)?.as_f64()?;
                                (weight.is_finite() && weight > 0.0).then_some((label, weight))
                            })
                            .collect::<Vec<_>>()
                    };
                    let mut influence_text = influence_labels
                        .iter()
                        .take(3)
                        .map(|(label, weight)| format!("{label} {weight:.3}"))
                        .collect::<Vec<_>>()
                        .join(", ");
                    if influence_labels.len() > 3 {
                        influence_text.push_str(&format!(" +{}", influence_labels.len() - 3));
                    }
                    if influence_text.is_empty() {
                        influence_text = if influences_resolved {
                            "No weighted influences".to_owned()
                        } else {
                            "No resolved influence labels".to_owned()
                        };
                    }
                    let total = row
                        .get("total_weight")
                        .and_then(Value::as_f64)
                        .filter(|weight| weight.is_finite())
                        .unwrap_or(0.0);
                    let label =
                        format!("SM {submesh} · V {vertex} · {influence_text} · Σ {total:.3}");
                    if row.get("invalid").and_then(Value::as_bool) == Some(true) {
                        ui.colored_label(Color32::from_rgb(245, 120, 105), label);
                    } else {
                        ui.small(label);
                    }
                }
                if selected_weights.len() > 8 {
                    ui.small(format!(
                        "+{} more selected vertices",
                        selected_weights.len() - 8
                    ));
                }
                if state_bool(&skeleton, "selected_weights_truncated") {
                    ui.small(
                        "Additional selected weight rows are hidden by the bounded host summary",
                    );
                }
            });
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rig_influence_rejects_stale_partial_and_invalid_rows_and_clears_colours() {
        let mut state = json!({
            "skeleton": {"selected_bone_index": 7},
            "rig_influence": {"bone_index": 7, "available": true, "vertex_count": 1,
                "parts": [{"submesh_index": 0, "weights": [[2, 0.75]]}]}
        });
        let mut rig = RigView::default();
        rig.update(&state);
        assert!(rig.available);
        assert_eq!(rig.weights.get(&(0, 2)), Some(&0.75));
        state["skeleton"]["selected_bone_index"] = json!(8);
        rig.update(&state);
        assert!(!rig.available && rig.weights.is_empty());
        state["skeleton"]["selected_bone_index"] = json!(7);
        rig.update(&state);
        assert!(rig.available);
        state["rig_influence"]["vertex_count"] = json!(2);
        rig.update(&state);
        assert!(!rig.available && rig.weights.is_empty());
        state["rig_influence"]["vertex_count"] = json!(1);
        state["rig_influence"]["parts"][0]["weights"][0][1] = json!(1.5);
        rig.update(&state);
        assert!(!rig.available && rig.weights.is_empty());
    }

    #[test]
    fn rig_weight_surface_reuses_buffers_across_camera_and_selection_changes()
    -> crate::headless_tests::TestResult {
        let mut application = crate::headless_tests::triangle_application()?;
        let mesh = application.mesh.as_mut().ok_or("mesh")?;
        let mut rig = RigView::default();
        rig.weights.insert((0, 0), 0.25);
        rig.weights.insert((0, 1), 1.0);
        rig.prepare(mesh, None, true);
        let positions = rig.positions.clone();
        rig.uploaded = true;
        mesh.set_selection(Selection {
            submeshes: HashSet::from([0]),
            ..Selection::default()
        })?;
        application.camera.orbit(Vec2::new(10.0, 0.0));
        rig.prepare(mesh, None, true);
        assert!(rig.uploaded);
        assert_eq!(rig.positions, positions);
        rig.prepare(mesh, Some(HashSet::new()), true);
        assert!(rig.positions.is_empty() && !rig.uploaded);
        Ok(())
    }
}
