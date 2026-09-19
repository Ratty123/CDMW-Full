//! Preview state is deliberately separate from WorkingMesh and the host protocol.
use super::*;
use crate::cdmw_ui::{state_bool, state_str, state_u64};
use cdmw_mesh::{Provenance, jiggle};
use std::collections::{HashMap, HashSet};

pub(super) struct JiggleView {
    pub selected_only: bool,
    pub use_height: bool,
    pub height: f64,
    key: Value,
    pub preview: Preview,
}

impl Default for JiggleView {
    fn default() -> Self {
        Self {
            selected_only: true,
            use_height: true,
            height: 0.0,
            key: Value::Null,
            preview: Preview::default(),
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Default)]
enum Comparison {
    #[default]
    Current,
    Original,
    Disabled,
}

pub(super) struct Preview {
    pub playing: bool,
    pub scene: Option<Scene>,
    motion: jiggle::Motion,
    comparison: Comparison,
    settings: jiggle::Settings,
    parts: Vec<u64>,
    feedback: String,
    last_tick: Instant,
}

impl Default for Preview {
    fn default() -> Self {
        Self {
            playing: false,
            scene: None,
            motion: jiggle::Motion::default(),
            comparison: Comparison::default(),
            settings: jiggle::Settings::default(),
            parts: Vec::new(),
            feedback: String::new(),
            last_tick: Instant::now(),
        }
    }
}

impl Preview {
    pub fn invalidate(&mut self) {
        self.playing = false;
        self.scene = None;
        self.feedback.clear();
        self.last_tick = Instant::now();
    }
}

pub(super) struct Scene {
    rest: DrawSnapshot,
    pub frame: DrawSnapshot,
    simulation: jiggle::Simulation,
    normal_sums: Vec<Vec3>,
    rest_surface_normals: Vec<Vec3>,
    tick: u64,
    moving: usize,
}

fn surface_normals(snapshot: &DrawSnapshot, sums: &mut [Vec3]) {
    sums.fill(Vec3::ZERO);
    for face in snapshot.indices.chunks_exact(3) {
        let [a, b, c] = [face[0] as usize, face[1] as usize, face[2] as usize];
        let pa = Vec3::from(snapshot.positions[a]);
        let normal =
            (Vec3::from(snapshot.positions[b]) - pa).cross(Vec3::from(snapshot.positions[c]) - pa);
        for i in [a, b, c] {
            sums[i] += normal;
        }
    }
}

impl LabApplication {
    pub(super) fn draw_cdmw_jiggle_page(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        ui.small("Experimental jiggle for body and clothing PAC meshes. Cloth bindings are not required.");
        let jiggle = self.cdmw_state["jiggle"].clone();
        ui.small("Reported on Damiane. Verify other models in-game. Strength is not decoded.");
        if !state_bool(&jiggle, "available") {
            if self.cdmw_jiggle.preview.scene.is_some() { self.publish_mesh_snapshot(); }
            ui.label(state_str(&jiggle, "reason").unwrap_or("Jiggle editing is unavailable."));
            return;
        }
        ui.checkbox(&mut self.cdmw_jiggle.selected_only, "Selected parts");
        let selected = self.selected_part_indices();
        let parts: Vec<Value> = jiggle["parts"]
            .as_array()
            .into_iter()
            .flatten()
            .filter(|part| {
                state_bool(part, "included")
                    && (!self.cdmw_jiggle.selected_only
                        || selected.contains(&(state_u64(part, "index") as u32)))
            })
            .cloned()
            .collect();
        if parts.is_empty() {
            if self.cdmw_jiggle.preview.scene.is_some() { self.publish_mesh_snapshot(); }
            ui.label("Select an included part with editable jiggle data.");
            return;
        }
        let ids: Vec<&str> = parts.iter().filter_map(|part| part["id"].as_str()).collect();
        let key = json!([ids, parts.iter().map(|part| &part["rule"]).collect::<Vec<_>>()]);
        let mixed = parts.iter().any(|part| part["rule"] != parts[0]["rule"]);
        let min_y = parts.iter().filter_map(|part| part["min_y"].as_f64()).fold(f64::INFINITY, f64::min);
        let max_y = parts.iter().filter_map(|part| part["max_y"].as_f64()).fold(f64::NEG_INFINITY, f64::max);
        if key != self.cdmw_jiggle.key {
            self.cdmw_jiggle.key = key;
            let rule = if mixed { &Value::Null } else { &parts[0]["rule"] };
            self.cdmw_jiggle.use_height = rule.is_null() || rule["below_y"].as_f64().is_some();
            self.cdmw_jiggle.height = rule["below_y"].as_f64().unwrap_or((min_y + max_y) * 0.5);
        }
        ui.small(format!("{} parts · applies to all {} LODs", parts.len(), state_u64(&jiggle, "lod_count")));
        if mixed {
            ui.small("Mixed saved settings. Disable replaces them for these parts.");
        }
        ui.checkbox(&mut self.cdmw_jiggle.use_height, "Only below height");
        if self.cdmw_jiggle.use_height {
            ui.horizontal(|ui| {
                ui.label("Below Y");
                ui.add(egui::DragValue::new(&mut self.cdmw_jiggle.height).speed(0.01));
            });
            ui.small(format!("Source height range: {min_y:.3} to {max_y:.3}"));
            ui.small("Uses displayed model coordinates. Choose the waist height for this model.");
        }
        ui.horizontal_wrapped(|ui| {
            if ui.button("Disable jiggle").clicked() {
                actions.push(UiAction::CdmwCommand {
                    command: "replacement_jiggle",
                    arguments: json!({"part_ids": ids, "rule": {
                        "below_y": self.cdmw_jiggle.use_height.then_some(self.cdmw_jiggle.height)
                    }}),
                    label: "Disable jiggle",
                });
            }
            if ui.add_enabled(parts.iter().any(|part| !part["rule"].is_null()), egui::Button::new("Restore original jiggle")).clicked() {
                actions.push(UiAction::CdmwCommand {
                    command: "replacement_jiggle",
                    arguments: json!({"part_ids": ids, "reset": true}),
                    label: "Restore original jiggle",
                });
            }
        });
        ui.small("Disable / Restore is saved with Build PAC and drafts.");
        self.draw_jiggle_preview_controls(ui, &parts);
    }

    pub(super) fn draw_jiggle_preview_controls(&mut self, ui: &mut egui::Ui, parts: &[Value]) {
        ui.separator();
        ui.label("Motion preview");
        let ids = parts
            .iter()
            .filter_map(|p| p["index"].as_u64())
            .collect::<Vec<_>>();
        if ids != self.cdmw_jiggle.preview.parts {
            self.publish_mesh_snapshot();
            self.cdmw_jiggle.preview.parts = ids;
        }
        let was_playing = self.cdmw_jiggle.preview.playing;
        let mut changed = false;
        let preview = &mut self.cdmw_jiggle.preview;
        ui.horizontal_wrapped(|ui| {
            changed |= ui
                .selectable_value(&mut preview.motion, jiggle::Motion::UpDown, "Up / down")
                .changed();
            changed |= ui
                .selectable_value(
                    &mut preview.motion,
                    jiggle::Motion::StartStop,
                    "Start / stop",
                )
                .changed();
            changed |= ui
                .selectable_value(&mut preview.motion, jiggle::Motion::Turn, "Turning")
                .changed();
        });
        ui.horizontal_wrapped(|ui| {
            changed |= ui
                .selectable_value(
                    &mut preview.comparison,
                    Comparison::Current,
                    "Current flags",
                )
                .changed();
            changed |= ui
                .selectable_value(
                    &mut preview.comparison,
                    Comparison::Original,
                    "Original flags",
                )
                .changed();
            changed |= ui
                .selectable_value(
                    &mut preview.comparison,
                    Comparison::Disabled,
                    "All disabled",
                )
                .changed();
        });
        ui.add(
            egui::Slider::new(&mut preview.settings.softness, 0.0..=1.0).text("Preview softness"),
        );
        ui.add(egui::Slider::new(&mut preview.settings.damping, 0.0..=1.0).text("Preview damping"));
        if changed {
            self.publish_mesh_snapshot();
            if was_playing && let Err(error) = self.start_jiggle_preview(parts) {
                self.cdmw_jiggle.preview.feedback = error.to_string();
            }
        }
        let reason = if self.cdmw_busy() {
            "Wait for the current operation."
        } else if self.cdmw_state["replacement"]["comparison"]
            .as_str()
            .unwrap_or("edit")
            != "edit"
        {
            "Use Edit comparison for motion preview."
        } else if parts
            .iter()
            .any(|p| p["preview"]["available"].as_bool() != Some(true))
        {
            "Preview requires unchanged source vertex ownership."
        } else {
            ""
        };
        ui.horizontal_wrapped(|ui| {
            let label = if self.cdmw_jiggle.preview.playing {
                "Pause preview"
            } else if self.cdmw_jiggle.preview.scene.is_some() {
                "Resume preview"
            } else {
                "Play preview"
            };
            if ui
                .add_enabled(reason.is_empty(), egui::Button::new(label))
                .clicked()
            {
                if self.cdmw_jiggle.preview.playing {
                    self.cdmw_jiggle.preview.playing = false;
                } else if self.cdmw_jiggle.preview.scene.is_some() {
                    self.cdmw_jiggle.preview.playing = true;
                    self.cdmw_jiggle.preview.last_tick = Instant::now();
                } else if let Err(error) = self.start_jiggle_preview(parts) {
                    self.cdmw_jiggle.preview.feedback = error.to_string();
                }
            }
            if ui
                .add_enabled(
                    self.cdmw_jiggle.preview.scene.is_some(),
                    egui::Button::new("Reset preview"),
                )
                .clicked()
            {
                self.publish_mesh_snapshot();
            }
        });
        if !reason.is_empty() {
            ui.small(reason);
        }
        if let Some(scene) = &self.cdmw_jiggle.preview.scene {
            ui.small(format!("{} simulated vertices", scene.moving));
        }
        if !self.cdmw_jiggle.preview.feedback.is_empty() {
            ui.small(&self.cdmw_jiggle.preview.feedback);
        }
        ui.small("Approximate motion. Inter-part collisions are not simulated.");
        ui.small("Preview settings are not exported. Reset preview to edit the surface.");
        if self.cdmw_jiggle.preview.playing {
            ui.ctx().request_repaint();
        }
    }

    fn start_jiggle_preview(&mut self, parts: &[Value]) -> Result<()> {
        if self.cdmw_busy()
            || self.hair.active()
            || self.edit_gesture.is_some()
            || self.selection_gesture.is_some()
            || self.cdmw_state["replacement"]["comparison"]
                .as_str()
                .unwrap_or("edit")
                != "edit"
        {
            bail!("Finish the current operation before previewing jiggle.");
        }
        let mesh = self
            .mesh
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("No editable mesh."))?;
        let visible = self.cdmw_visible_submeshes();
        let elements = visible
            .as_ref()
            .map(|v| mesh.element_handles_for_submeshes(v));
        let mut masks = HashMap::new();
        let mut expected = HashMap::new();
        for part in parts {
            let index = part["index"]
                .as_u64()
                .filter(|i| *i <= u32::MAX as u64)
                .ok_or_else(|| anyhow::anyhow!("Invalid preview part."))?
                as u32;
            if visible.as_ref().is_some_and(|v| !v.contains(&index)) {
                continue;
            }
            let data = &part["preview"];
            if data["available"].as_bool() != Some(true) {
                bail!("Unverified source vertex ownership.");
            }
            let count = data["vertex_count"]
                .as_u64()
                .filter(|n| *n > 0 && *n <= 100_000)
                .ok_or_else(|| anyhow::anyhow!("Invalid preview vertex count."))?
                as usize;
            let key = if self.cdmw_jiggle.preview.comparison == Comparison::Original {
                "original_vertices"
            } else {
                "current_vertices"
            };
            let values = data[key]
                .as_array()
                .ok_or_else(|| anyhow::anyhow!("Missing jiggle vertex flags."))?;
            let mut mask = vec![false; count];
            for value in values {
                let vertex = value
                    .as_u64()
                    .filter(|v| *v < count as u64)
                    .ok_or_else(|| anyhow::anyhow!("Invalid jiggle vertex flag."))?
                    as usize;
                if mask[vertex] {
                    bail!("Duplicate jiggle vertex flag.");
                }
                mask[vertex] = true;
            }
            if self.cdmw_jiggle.preview.comparison == Comparison::Disabled {
                mask.fill(false);
            }
            if masks.insert(index, mask).is_some() {
                bail!("Duplicate jiggle part.");
            }
            expected.insert(index, HashSet::new());
        }
        if masks.is_empty() {
            bail!("Select a visible part with verified jiggle data.");
        }
        let mut active = Vec::new();
        for (handle, vertex) in mesh.vertices() {
            let rendered = elements
                .as_ref()
                .is_none_or(|e| e.vertices.contains(&handle));
            let Provenance::Source { submesh, element } = vertex.provenance else {
                if rendered {
                    bail!("Reset topology edits before previewing jiggle.");
                }
                continue;
            };
            let value = if let Some(mask) = masks.get(&submesh) {
                if !expected.get_mut(&submesh).unwrap().insert(element) {
                    bail!("Ambiguous jiggle vertex ownership.");
                }
                *mask
                    .get(element as usize)
                    .ok_or_else(|| anyhow::anyhow!("Jiggle vertex ownership changed."))?
            } else {
                false
            };
            if rendered {
                active.push(value);
            }
        }
        if masks
            .iter()
            .any(|(part, mask)| expected[part].len() != mask.len())
        {
            bail!("Jiggle vertex ownership changed.");
        }
        let mut rest = visible.as_ref().map_or_else(
            || mesh.draw_snapshot(),
            |v| mesh.draw_snapshot_for_submeshes(v),
        );
        rest.selected_vertices.clear();
        let moving = active.iter().filter(|v| **v).count();
        let simulation = jiggle::Simulation::new(&rest.positions, &rest.indices, active)
            .map_err(anyhow::Error::msg)?;
        let mut rest_surface_normals = vec![Vec3::ZERO; rest.positions.len()];
        surface_normals(&rest, &mut rest_surface_normals);
        for normal in &mut rest_surface_normals {
            *normal = normal.normalize_or_zero();
        }
        let scene = Scene {
            rest_surface_normals,
            frame: rest.clone(),
            normal_sums: vec![Vec3::ZERO; rest.positions.len()],
            rest,
            simulation,
            tick: 0,
            moving,
        };
        self.cdmw_jiggle.preview.scene = Some(scene);
        self.cdmw_jiggle.preview.playing = true;
        self.cdmw_jiggle.preview.feedback.clear();
        self.cdmw_jiggle.preview.last_tick = Instant::now();
        Ok(())
    }

    pub(super) fn advance_jiggle_preview(&mut self, seconds: f64) -> Result<()> {
        let preview = &mut self.cdmw_jiggle.preview;
        let Some(scene) = &mut preview.scene else {
            return Ok(());
        };
        let before = scene.simulation.elapsed;
        if preview.playing {
            scene
                .simulation
                .advance(seconds, preview.motion, preview.settings)
                .map_err(anyhow::Error::msg)?;
        }
        // Pausing/camera movement does not need a new geometry upload.
        if scene.tick > 0 && scene.simulation.elapsed == before {
            return Ok(());
        }
        for (out, position) in scene
            .frame
            .positions
            .iter_mut()
            .zip(scene.simulation.positions())
        {
            *out = position;
        }
        surface_normals(&scene.frame, &mut scene.normal_sums);
        let rotation = scene.simulation.rotation(preview.motion);
        for (i, normal) in scene.frame.normals.iter_mut().enumerate() {
            let authored = rotation * Vec3::from(scene.rest.normals[i]);
            let before = rotation * scene.rest_surface_normals[i];
            *normal = match (before.try_normalize(), scene.normal_sums[i].try_normalize()) {
                (Some(before), Some(after)) => {
                    (Quat::from_rotation_arc(before, after) * authored).to_array()
                }
                _ => authored.to_array(),
            };
        }
        scene.tick = scene.tick.wrapping_add(1);
        scene.frame.draw_revision = scene.rest.draw_revision.wrapping_add(scene.tick);
        Ok(())
    }

    pub(super) fn render_jiggle(&mut self) {
        if self.cdmw_jiggle.preview.scene.is_none() {
            return;
        }
        let now = Instant::now();
        let seconds = now
            .duration_since(self.cdmw_jiggle.preview.last_tick)
            .as_secs_f64();
        self.cdmw_jiggle.preview.last_tick = now;
        let result = self.advance_jiggle_preview(seconds).and_then(|()| {
            if let (Some(renderer), Some(scene)) =
                (&mut self.renderer, &self.cdmw_jiggle.preview.scene)
            {
                renderer.set_face_selection(&[], [0.0; 4])?;
                renderer.set_snapshot_with_deformation_interactive(&scene.frame, None)?;
            }
            Ok(())
        });
        if let Err(error) = result {
            self.publish_mesh_snapshot();
            self.cdmw_jiggle.preview.feedback = format!("Motion preview stopped: {error}");
        }
        if self.cdmw_jiggle.preview.playing
            && let Some(window) = &self.window
        {
            window.request_redraw();
        }
    }
}
