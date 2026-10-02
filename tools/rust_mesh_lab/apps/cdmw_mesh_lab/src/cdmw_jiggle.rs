//! Preview state is deliberately separate from WorkingMesh and the host protocol.
pub(crate) mod native;
use super::*;
use crate::cdmw_ui::{state_bool, state_str, state_u64};
use cdmw_mesh::{Provenance, jiggle};
use std::collections::{HashMap, HashSet};

const REGION_LOW: [f32; 4] = [0.05, 0.30, 0.85, 0.88];
const REGION_HIGH: [f32; 4] = [1.00, 0.55, 0.05, 0.88];
const REGION_DISABLED: [f32; 4] = [0.32, 0.34, 0.38, 0.88];
const REGION_UNKNOWN: [f32; 4] = [0.55, 0.12, 0.85, 0.88];

const BONE_SETTINGS: [(&str, f32, &str); 8] = [
    ("Linear response", 5000.0, "How strongly a displaced bone is pulled back. For example, a higher value makes it catch up faster after an up/down shake."),
    ("Linear damping", 1.0, "Movement speed kept each step. For example, 0.9 keeps 90%, so it settles more slowly than 0.5. Higher values mean less braking."),
    ("Linear speed limit", 20.0, "Maximum movement speed, relative to model size. For example, a low limit makes a displaced bone catch up slowly. It has no effect until that speed is reached."),
    ("Linear offset limit", 1.0, "Maximum distance a bone can lag behind, relative to model size. For example, a smaller limit keeps it closer to the body; zero prevents positional lag."),
    ("Angular response", 5000.0, "How strongly a rotated bone is pulled back. For example, a higher value makes it straighten faster after Turning. Use Turning to see angular settings clearly."),
    ("Angular damping", 1.0, "Rotation speed kept each step. For example, 0.9 keeps more spin than 0.5, so wobbling lasts longer. Higher values mean less braking."),
    ("Angular speed limit", 500.0, "Maximum rotation speed in radians per second. For example, a low limit makes a bone turn back slowly. It has no effect until that speed is reached."),
    ("Angular offset limit (radians)", std::f32::consts::PI, "Maximum angle a bone can lag behind. For example, 0.1 radians is about 6 degrees, while 0.7 is about 40 degrees. Zero prevents angular lag."),
];

fn preview_weights(data: &Value, key: &str, limit: usize) -> Result<Vec<f32>> {
    if data["available"].as_bool() != Some(true) {
        bail!("Unverified source vertex ownership.");
    }
    let count = data["vertex_count"].as_u64().filter(|n| *n > 0 && *n <= limit as u64)
        .ok_or_else(|| anyhow::anyhow!("Invalid preview vertex count."))? as usize;
    let values = data[key].as_array().filter(|v| v.len() == count)
        .ok_or_else(|| anyhow::anyhow!("Missing or incomplete jiggle vertex bytes."))?;
    values.iter().map(|value| {
        let byte = value.as_u64().and_then(|v| u8::try_from(v).ok())
            .ok_or_else(|| anyhow::anyhow!("Invalid jiggle vertex byte."))?;
        Ok(jiggle::WeightDecode::LowNibble.decode(byte))
    }).collect()
}

pub(super) struct JiggleView {
    pub show_regions: bool,
    pub region_opacity: f32,
    pub region_colours: Option<Vec<[f32; 4]>>,
    pub selected_only: bool,
    pub use_height: bool,
    pub height: f64,
    pub retained_percent: f64,
    key: Value,
    pub preview: Preview,
}

impl Default for JiggleView {
    fn default() -> Self {
        Self {
            show_regions: false,
            region_opacity: 0.60,
            region_colours: None,
            selected_only: true,
            use_height: true,
            height: 0.0,
            retained_percent: 50.0,
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

#[derive(Clone, Copy, PartialEq, Eq, Default)]
enum Solver {
    #[default]
    Decoded,
    Approximate,
    Cloth,
}

pub(super) struct Preview {
    pub playing: bool,
    pub scene: Option<Scene>,
    pub pending: Option<u64>,
    solver: Solver,
    native_settings: native::Settings,
    pub(super) cloth_settings: cdmw_mesh::cloth::Settings,
    motion: jiggle::Motion,
    comparison: Comparison,
    settings: jiggle::Settings,
    parts: Vec<u64>,
    feedback: String,
    last_tick: Instant,
    pub manual_drag: Option<(Vec2, Vec3)>,
    keep_centred: bool,
    show_weapon_colliders: bool,
}

impl Default for Preview {
    fn default() -> Self {
        Self {
            playing: false,
            scene: None,
            pending: None,
            solver: Solver::default(),
            native_settings: native::Settings::default(),
            cloth_settings: cdmw_mesh::cloth::Settings::default(),
            motion: jiggle::Motion::default(),
            comparison: Comparison::default(),
            settings: jiggle::Settings::default(),
            parts: Vec::new(),
            feedback: String::new(),
            last_tick: Instant::now(),
            manual_drag: None,
            keep_centred: true,
            show_weapon_colliders: true,
        }
    }
}

impl Preview {
    pub fn invalidate(&mut self) {
        self.playing = false;
        self.scene = None;
        self.pending = None;
        self.feedback.clear();
        self.last_tick = Instant::now();
        self.manual_drag = None;
        if matches!(self.motion, jiggle::Motion::Freehand(_)) {
            self.motion = jiggle::Motion::Freehand(Vec3::ZERO);
        }
    }
}

pub(super) struct Scene {
    rest: DrawSnapshot,
    pub frame: DrawSnapshot,
    simulation: Simulation,
    normal_sums: Vec<Vec3>,
    rest_surface_normals: Vec<Vec3>,
    tick: u64,
    moving: usize,
    motion_scale: f32,
    centred: bool,
}

fn motion_scale(rest: &DrawSnapshot) -> f32 {
    let (min, max) = rest.positions.iter().map(|v| Vec3::from(*v)).fold(
        (Vec3::splat(f32::INFINITY), Vec3::splat(f32::NEG_INFINITY)),
        |(min, max), point| (min.min(point), max.max(point)),
    );
    (max - min).max_element().max(1e-6)
}

pub(crate) enum Simulation {
    Approximate(jiggle::Simulation),
    Decoded(Box<native::Simulation>),
    Cloth(Box<crate::cdmw_cloth::preview::Simulation>),
}

impl std::fmt::Debug for Simulation {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let kind = match self { Self::Approximate(_) => "Approximate", Self::Decoded(_) => "Decoded", Self::Cloth(_) => "Cloth" };
        f.debug_struct(kind).field("elapsed", &self.elapsed()).finish_non_exhaustive()
    }
}

impl Simulation {
    fn elapsed(&self) -> f64 {
        match self { Self::Approximate(s) => s.elapsed, Self::Decoded(s) => s.elapsed, Self::Cloth(s) => s.elapsed }
    }
    fn advance(&mut self, seconds: f64, motion: jiggle::Motion, settings: jiggle::Settings, native: native::Settings,
               cloth: cdmw_mesh::cloth::Settings) -> Result<()> {
        match self {
            Self::Approximate(s) => s.advance(seconds, motion, settings).map_err(anyhow::Error::msg),
            Self::Decoded(s) => s.advance(seconds, motion, native),
            Self::Cloth(s) => s.advance(seconds, motion, cloth),
        }
    }
    fn copy_positions(&self, output: &mut [[f32; 3]]) {
        match self {
            Self::Approximate(s) => { for (out, value) in output.iter_mut().zip(s.positions()) { *out = value; } },
            Self::Decoded(s) => output.copy_from_slice(&s.positions),
            Self::Cloth(s) => output.copy_from_slice(s.positions()),
        }
    }
    fn rotation(&self, motion: jiggle::Motion) -> Quat {
        match self { Self::Approximate(s) => s.rotation(motion), Self::Decoded(s) => s.rotation, Self::Cloth(s) => s.rotation }
    }

    fn motion_transform(&self) -> glam::Mat4 {
        match self { Self::Approximate(s) => s.motion_transform(),
            Self::Decoded(s) => s.motion_transform, Self::Cloth(s) => s.motion_transform }
    }
    fn weapon_lines(&self, centred: bool) -> Vec<cdmw_render_wgpu::EffectLineVertex> {
        match self { Self::Cloth(simulation) => simulation.weapon_lines(centred), _ => Vec::new() }
    }
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
        if ui.checkbox(&mut self.cdmw_jiggle.show_regions, "Show jiggle regions").changed() {
            if self.cdmw_jiggle.preview.scene.is_some() || self.cdmw_jiggle.preview.pending.is_some() {
                self.refresh_jiggle_regions();
            } else {
                self.publish_mesh_snapshot();
            }
        }
        if self.cdmw_jiggle.show_regions {
            if ui.add(crate::cdmw_ui::numeric::slider(&mut self.cdmw_jiggle.region_opacity, 0.15..=0.85)
                .text("Region tint")).changed() {
                if self.cdmw_jiggle.preview.scene.is_some() || self.cdmw_jiggle.preview.pending.is_some() {
                    self.refresh_jiggle_regions();
                } else {
                    self.publish_mesh_snapshot();
                }
            }
            ui.horizontal_wrapped(|ui| {
                ui.colored_label(egui::Color32::from_rgb(15, 80, 220), "Low weight");
                ui.colored_label(egui::Color32::from_rgb(255, 140, 15), "High weight");
                ui.colored_label(egui::Color32::GRAY, "Zero weight");
                ui.colored_label(egui::Color32::from_rgb(195, 90, 240), "Unknown");
            });
            ui.small("Current vertex contribution on visible parts. Colours do not prove live physics activation.");
            ui.small("Unknown: no verified PAC LOD0 bytes for this geometry or comparison view.");
        }
        ui.separator();
        let jiggle = self.cdmw_state["jiggle"].clone();
        ui.small("Reductions preserve the source gradient. Final motion still needs in-game verification.");
        if !state_bool(&jiggle, "available") {
            if self.cdmw_jiggle.preview.scene.is_some() || self.cdmw_jiggle.preview.pending.is_some() { self.publish_mesh_snapshot(); }
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
            self.cdmw_jiggle.retained_percent = if rule.is_null() { 50.0 }
                else { rule["retained"].as_f64().unwrap_or(0.0) * 100.0 };
        }
        ui.small(format!("{} parts · applies to all {} LODs", parts.len(), state_u64(&jiggle, "lod_count")));
        if mixed {
            ui.small("Mixed saved settings. Applying a change replaces them for these parts.");
        }
        ui.checkbox(&mut self.cdmw_jiggle.use_height, "Only below height");
        if self.cdmw_jiggle.use_height {
            ui.horizontal(|ui| {
                ui.label("Below Y");
                ui.add(crate::cdmw_ui::numeric::value(&mut self.cdmw_jiggle.height).speed(0.01));
            });
            ui.small(format!("Source height range: {min_y:.3} to {max_y:.3}"));
            ui.small("Uses displayed model coordinates. Choose the waist height for this model.");
        }
        let relative_available = parts.iter().all(|part| state_bool(part, "relative_available"));
        ui.add_enabled(relative_available, crate::cdmw_ui::numeric::slider(&mut self.cdmw_jiggle.retained_percent, 0.0..=100.0)
            .text("Retain original %"));
        ui.small("Rounded to available byte steps. 100% keeps the source; 0% removes the vertex contribution.");
        if !relative_available {
            ui.small("This source encoding supports Disable / Restore only.");
        }
        ui.horizontal_wrapped(|ui| {
            if ui.add_enabled(relative_available, egui::Button::new("Apply contribution")).clicked() {
                actions.push(UiAction::CdmwCommand {
                    command: "replacement_jiggle",
                    arguments: json!({"part_ids": ids, "rule": {
                        "below_y": self.cdmw_jiggle.use_height.then_some(self.cdmw_jiggle.height),
                        "retained": self.cdmw_jiggle.retained_percent / 100.0
                    }}),
                    label: "Set jiggle contribution",
                });
            }
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
        ui.small("Contribution edits are saved with Build PAC and drafts.");
        self.draw_jiggle_preview_controls(ui, &parts);
    }

    pub(super) fn refresh_jiggle_regions(&mut self) {
        self.cdmw_jiggle.region_colours = None;
        if !self.cdmw_jiggle.show_regions || self.hair.active() {
            return;
        }
        let Some(mesh) = &self.mesh else { return; };
        let visible = self.cdmw_visible_submeshes();
        let elements = visible.as_ref().map(|v| mesh.element_handles_for_submeshes(v));
        let mut masks = HashMap::new();
        let mut invalid = HashSet::new();
        let vertex_count = mesh.vertices().count();
        let verified_view = self.active_lod_index == 0
            && self.cdmw_state["replacement"]["comparison"].as_str().unwrap_or("edit") == "edit";
        if verified_view {
            for part in self.cdmw_state["jiggle"]["overlay_parts"].as_array().into_iter().flatten() {
                let Some(index) = part["index"].as_u64().and_then(|v| u32::try_from(v).ok()) else { continue; };
                let data = &part["preview"];
                let mask = preview_weights(data, "current_bytes", vertex_count).ok();
                if let Some(mask) = mask {
                    if masks.insert(index, mask).is_some() { invalid.insert(index); }
                } else {
                    invalid.insert(index);
                }
            }
        }
        let mut seen: HashMap<u32, HashSet<u32>> = HashMap::new();
        for (_, vertex) in mesh.vertices() {
            if let Provenance::Source { submesh, element } = vertex.provenance
                && let Some(mask) = masks.get(&submesh)
                && (element as usize >= mask.len() || !seen.entry(submesh).or_default().insert(element))
            {
                invalid.insert(submesh);
            }
        }
        masks.retain(|index, mask| !invalid.contains(index) && seen.get(index).is_some_and(|s| s.len() == mask.len()));
        let colours = mesh.vertices()
            .filter(|(handle, _)| elements.as_ref().is_none_or(|e| e.vertices.contains(handle)))
            .map(|(_, vertex)| {
                let Provenance::Source { submesh, element } = vertex.provenance else { return REGION_UNKNOWN; };
                match masks.get(&submesh).and_then(|mask| mask.get(element as usize)) {
                    Some(weight) if *weight > 0.0 => std::array::from_fn(|i|
                        REGION_LOW[i] + (REGION_HIGH[i] - REGION_LOW[i]) * weight),
                    Some(_) => REGION_DISABLED,
                    None => REGION_UNKNOWN,
                }
            }).map(|mut colour| { colour[3] = self.cdmw_jiggle.region_opacity; colour }).collect();
        self.cdmw_jiggle.region_colours = Some(colours);
    }

    pub(super) fn draw_jiggle_preview_controls(&mut self, ui: &mut egui::Ui, parts: &[Value]) {
        self.draw_motion_preview_controls(ui, parts, false, &mut Vec::new());
    }

    pub(super) fn draw_cloth_collision_inputs(&self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let jiggle = &self.cdmw_state["jiggle"];
        let inputs = &jiggle["collision_inputs"];
        let model_owned = jiggle["decoded"]["cloth"]["body_collider_source"] == "pac_model";
        let available = !self.cdmw_busy()
            && jiggle["decoded"]["rig_mode"] != "rigid_attachment"
            && jiggle["decoded"]["cloth"]["available"].as_bool() == Some(true) && !model_owned;
        let weapon_available = !self.cdmw_busy() && jiggle["decoded"]["cloth"]["available"].as_bool() == Some(true);
        ui.collapsing("Collision sources", |ui| {
            ui.small("Choose body/head PABV files or a weapon PAC for this preview. Inputs are not saved to the model or draft.");
            if model_owned { ui.small("This model's embedded volumes take precedence over appearance inputs."); }
            for (role, label, default) in [("body", "Body volumes", "Rig defaults"), ("head", "Head volumes", "No head override")] {
                ui.label(format!("{label}: {}", inputs[role].as_str().unwrap_or(default)));
                if ui.add_enabled(available, egui::Button::new(format!("Choose {role} PABV…"))).clicked() {
                    actions.push(UiAction::ChooseClothCollisionInput { role });
                }
            }
            ui.label(format!("Weapon volumes: {}", inputs["weapon"].as_str().unwrap_or("Current rigid weapon parts")));
            if ui.add_enabled(weapon_available, egui::Button::new("Choose weapon PAC…")).clicked() {
                actions.push(UiAction::ChooseClothCollisionInput { role: "weapon" });
            }
            if inputs["weapon"].is_string() {
                let placement = &jiggle["weapon_placement"];
                let mut offset: [f64; 3] = std::array::from_fn(|i| placement["offset"][i].as_f64().unwrap_or(0.));
                let mut rotation: [f64; 3] = std::array::from_fn(|i| placement["rotation"][i].as_f64().unwrap_or(0.));
                let mut changed = false;
                ui.add_enabled_ui(weapon_available, |ui| {
                    ui.label("Weapon preview position");
                    ui.horizontal_wrapped(|ui| { for (i, axis) in ["X", "Y", "Z"].iter().enumerate() {
                        ui.label(*axis);
                        changed |= ui.add(crate::cdmw_ui::numeric::value(&mut offset[i]).speed(0.01).range(-100.0..=100.0)).changed();
                    }});
                    ui.label("Weapon preview rotation");
                    ui.horizontal_wrapped(|ui| { for (i, axis) in ["X", "Y", "Z"].iter().enumerate() {
                        ui.label(*axis);
                        changed |= ui.add(crate::cdmw_ui::numeric::value(&mut rotation[i]).speed(1.0).range(-360.0..=360.0).suffix("°")).changed();
                    }});
                });
                if changed {
                    actions.push(UiAction::CdmwCommand { command: "cloth_collision_input",
                        arguments: json!({"weapon_placement": {"offset": offset, "rotation": rotation}}), label: "Place weapon preview" });
                }
                ui.small("Place the weapon in model space. In-game sockets and weapon animation are not loaded.");
            }
            let has_inputs = inputs.as_object().is_some_and(|values| !values.is_empty());
            if ui.add_enabled(!self.cdmw_busy() && has_inputs, egui::Button::new("Clear collision inputs")).clicked() {
                actions.push(UiAction::CdmwCommand {
                    command: "cloth_collision_input", arguments: json!({"clear": true}), label: "Clear collision inputs",
                });
            }
        });
    }

    pub(super) fn choose_cloth_collision_input(&mut self, role: &'static str) {
        if self.cdmw_busy() { return; }
        let dialog = self.cdmw_file_dialog();
        let dialog = if role == "weapon" { dialog.add_filter("Weapon model", &["pac"]) }
            else { dialog.add_filter("Skeleton volumes", &["pabv"]) };
        let Some(path) = dialog.pick_file() else { return; };
        self.submit_cdmw_command("cloth_collision_input", json!({"role": role, "path": path.to_string_lossy()}), "Load collision input");
    }

    pub(super) fn draw_cloth_preview_controls(&mut self, ui: &mut egui::Ui, parts: &[Value], actions: &mut Vec<UiAction>) {
        let verified = self.cdmw_state["jiggle"]["overlay_parts"].as_array();
        let parts = parts.iter().map(|part| {
            let mut part = part.clone();
            part["preview"] = verified.and_then(|rows| rows.iter().find(|row| row["index"] == part["index"]))
                .map(|row| row["preview"].clone()).unwrap_or(Value::Null);
            part
        }).collect::<Vec<_>>();
        self.draw_motion_preview_controls(ui, &parts, true, actions);
    }

    fn draw_motion_preview_controls(&mut self, ui: &mut egui::Ui, parts: &[Value], cloth: bool, actions: &mut Vec<UiAction>) {
        ui.separator();
        ui.label("Motion preview");
        if (self.cdmw_jiggle.preview.solver == Solver::Cloth) != cloth {
            self.publish_mesh_snapshot();
            self.cdmw_jiggle.preview.solver = if cloth { Solver::Cloth } else { Solver::Decoded };
        }
        let ids = parts
            .iter()
            .filter_map(|p| p["index"].as_u64())
            .collect::<Vec<_>>();
        if ids != self.cdmw_jiggle.preview.parts {
            self.publish_mesh_snapshot();
            self.cdmw_jiggle.preview.parts = ids;
        }
        let was_playing = self.cdmw_jiggle.preview.playing || self.cdmw_jiggle.preview.pending.is_some();
        let can_author = !self.cdmw_busy() && state_bool(&self.cdmw_state, "authoring_enabled");
        let mut changed = false;
        let preview = &mut self.cdmw_jiggle.preview;
        if !cloth { ui.horizontal_wrapped(|ui| {
            for (solver, label) in [(Solver::Decoded, "Decoded bones"), (Solver::Approximate, "Approximate vertices")] {
                if ui.add(egui::Button::new(label).selected(preview.solver == solver)).clicked() && preview.solver != solver {
                    preview.solver = solver;
                    changed = true;
                }
            }
        }); }
        // Frame strokes count toward egui's layout size. Keep them present in
        // every state so hovering a choice cannot make the row wrap and unwrap.
        ui.horizontal_wrapped(|ui| {
            for (motion, label) in [
                (jiggle::Motion::UpDown, "Up / down"),
                (jiggle::Motion::StartStop, "Start / stop"),
                (jiggle::Motion::Turn, "Turning"),
                (jiggle::Motion::Freehand(Vec3::ZERO), "Freehand"),
            ] {
                let selected = std::mem::discriminant(&preview.motion) == std::mem::discriminant(&motion);
                if ui
                    .add(egui::Button::new(label).selected(selected))
                    .clicked()
                    && !selected
                {
                    preview.motion = motion;
                    changed = true;
                }
            }
        });
        if matches!(preview.motion, jiggle::Motion::Freehand(_)) {
            ui.small("Play, then drag in the viewport to shake the preview. Release to let physics settle.");
            ui.small("Right mouse orbits; middle mouse pans. Reset clears the motion.");
        }
        ui.checkbox(&mut preview.keep_centred, "Keep model centred")
            .on_hover_text("Keeps the body's position and facing steady while motion still drives physics. For example, an up/down shake shows the jiggle without bouncing the whole model. Uncheck to see the full motion.");
        ui.horizontal_wrapped(|ui| {
            for (comparison, label) in [
                (Comparison::Current, "Current flags"),
                (Comparison::Original, "Original flags"),
                (Comparison::Disabled, "All disabled"),
            ] {
                if ui
                    .add(egui::Button::new(label).selected(preview.comparison == comparison))
                    .clicked()
                    && preview.comparison != comparison
                {
                    preview.comparison = comparison;
                    changed = true;
                }
            }
        });
        if preview.solver == Solver::Decoded {
            ui.collapsing("Bone solver settings", |ui| {
                for (index, (label, max, help)) in BONE_SETTINGS.into_iter().enumerate() {
                    ui.add(crate::cdmw_ui::numeric::slider(&mut preview.native_settings.values[index], 0.0..=max).text(label))
                        .on_hover_text(crate::localization::tr(help));
                }
                if ui.button("Reset bone settings").clicked() { preview.native_settings.values = native::Settings::default().values; }
            });
            ui.collapsing("Wind preview", |ui| {
                let wind = &mut preview.native_settings.wind;
                ui.checkbox(&mut wind.enabled, "Enable wind")
                    .on_hover_text("Adds wind to the preview. For example, enable it while Freehand is still to see wind-driven movement on its own.");
                ui.add_enabled_ui(wind.enabled, |ui| {
                    ui.add(crate::cdmw_ui::numeric::slider(&mut wind.speed, 0.0..=20.0).text("Wind speed"))
                        .on_hover_text("Strength of the preview wind. For example, zero supplies no wind force; a higher value pushes affected regions more strongly.");
                    ui.add(crate::cdmw_ui::numeric::slider(&mut wind.direction, 0.0..=360.0).text("Wind direction").suffix("°"))
                        .on_hover_text("Horizontal wind direction. For example, 0 degrees blows along +X and 90 degrees along +Z in model coordinates.");
                    ui.add(crate::cdmw_ui::numeric::slider(&mut wind.cycle, 0.05..=10.0).text("Gust cycle (seconds)"))
                        .on_hover_text("Time between repeating gusts. For example, 1 second gives quick changes, while 5 seconds gives slower changes.");
                    ui.add(crate::cdmw_ui::numeric::slider(&mut wind.gusts, 0.0..=1.0).text("Gust amount"))
                        .on_hover_text("How much the wind varies. For example, zero gives steadier wind; a higher value adds stronger gusts and small direction changes.");
                });
                if ui.button("Reset wind").clicked() { *wind = native::Wind::default(); }
                ui.small("Preview wind is supplied manually; game weather is not loaded.");
            });
            ui.small("Decoded solver with a procedural pose test and model bounds. Live game activation is not reproduced.");
        } else if cloth {
            let cloth_state = &self.cdmw_state["jiggle"]["decoded"]["cloth"];
            let standalone = self.cdmw_state["jiggle"]["decoded"]["rig_mode"] == "rigid_attachment";
            let spline_available = cloth_state["spline_available"].as_bool() == Some(true);
            if !self.cdmw_cloth.profiles.has_loaded() {
                let detected = self.cdmw_state["physics"]["parts"].as_array();
                let has_cloth = parts.iter().any(|part| detected.and_then(|rows|
                    rows.iter().find(|row| row["index"] == part["index"]))
                    .is_some_and(|row| row["kind"] == "cloth"));
                let spline = !has_cloth && (standalone
                    || (!parts.is_empty()
                        && parts.iter().all(|part| {
                            detected
                                .and_then(|rows| {
                                    rows.iter().find(|row| row["index"] == part["index"])
                                })
                                .is_some_and(|row| row["kind"] == "spline")
                        })));
                if preview.cloth_settings.spline != spline {
                    preview.cloth_settings = crate::cdmw_cloth::preview::default_settings(spline);
                }
            }
            let rotation_available = if preview.cloth_settings.spline {
                spline_available
            } else {
                cloth_state["rotation_available"].as_bool() == Some(true)
            };
            if !rotation_available {
                preview.cloth_settings.rotate_guides = false;
            }
            if standalone {
                ui.small("Standalone rigid attachment: motion drives the model root.");
            }
            let body_source = cloth_state["body_collider_source"].as_str();
            let body_available = cloth_state["body_collider_count"].as_u64().is_some_and(|count| count > 0)
                && matches!(body_source, Some("pab_primary" | "pac_model" | "appearance"));
            if !body_available { preview.cloth_settings.body_collisions = false; }
            let weapon_available = cloth_state["weapon_collider_count"].as_u64().is_some_and(|count| count > 0);
            if !weapon_available { preview.cloth_settings.weapon_collisions = false; }
            ui.collapsing(if preview.cloth_settings.spline { "Spline preview settings" } else { "Cloth preview settings" }, |ui| {
                let settings = &mut preview.cloth_settings;
                // Keep the displayed sign consistent with raw profile XML.
                let mut gravity = -settings.gravity;
                if ui.add(crate::cdmw_ui::numeric::slider(&mut gravity, -100.0..=100.0).text("Gravity"))
                    .on_hover_text("Negative pulls down; positive lifts up.").changed() {
                    settings.gravity = -gravity;
                }
                ui.add(crate::cdmw_ui::numeric::slider(&mut settings.stretch, 0.0..=1.0).text("Stretch response"));
                ui.add(crate::cdmw_ui::numeric::slider(&mut settings.bend, 0.0..=1.0).text("Bend response"));
                if settings.spline {
                    ui.add(crate::cdmw_ui::numeric::slider(&mut settings.restore_angle, 0.0..=1.0).text("Spring-back response"))
                        .on_hover_text("Pulls the tail toward its original direction. Zero lets it hang freely; higher values make it return more strongly after a shake.");
                }
                ui.add(crate::cdmw_ui::numeric::slider(&mut settings.damping, 0.0..=10.0).text("Preview damping"));
                ui.add(crate::cdmw_ui::numeric::slider(&mut settings.iterations, 1..=8).text("Solver iterations"));
                ui.checkbox(&mut settings.use_vertex_alpha, "Use authored vertex alpha");
                ui.add_enabled(rotation_available, egui::Checkbox::new(&mut settings.rotate_guides, "Guide rotation correction"));
                if !settings.spline {
                    ui.add_enabled(rotation_available && settings.rotate_guides,
                    egui::Checkbox::new(&mut settings.single_edge_rotation, "Single-edge rotation"));
                }
                if !rotation_available { ui.small("Guide rotation needs known orientation neighbors."); }
                ui.add_enabled(body_available, egui::Checkbox::new(&mut settings.body_collisions, "Body collisions"));
                ui.add_enabled(weapon_available, egui::Checkbox::new(&mut settings.weapon_collisions, "Weapon collisions"))
                    .on_hover_text("Uses fitted capsules around rigid weapon parts. This switch affects the preview; Create weapon colliders saves shapes for the mod.");
                ui.add_enabled(weapon_available, egui::Checkbox::new(&mut preview.show_weapon_colliders, "Show weapon colliders"))
                    .on_hover_text("Shows the fitted collision shapes during playback or pause. Use them to position a weapon reference.");
                if body_available {
                    if body_source == Some("pac_model") {
                        ui.small("Uses this model's authored collision volumes.");
                    } else if body_source == Some("appearance") {
                        ui.small("Uses the explicitly selected body/head collision inputs.");
                    } else {
                        ui.small("Uses the matched rig's default volumes.");
                    }
                } else {
                    ui.small("Body collisions need supported model or rig volumes.")
                        .on_hover_text(cloth_state["body_collider_reason"].as_str().unwrap_or("No authored body volumes available."));
                }
                if !weapon_available {
                    ui.small("Weapon collisions need supported rigid weapon parts.")
                        .on_hover_text(cloth_state["weapon_collider_reason"].as_str().unwrap_or("No weapon colliders available."));
                }
                if settings.body_collisions || settings.weapon_collisions {
                    ui.add(crate::cdmw_ui::numeric::slider(&mut settings.collision_margin, 0.0..=0.1).text("Collision margin"));
                }
                let mut floor = settings.ground_height.is_some();
                if ui.checkbox(&mut floor, "Preview floor").changed() { settings.ground_height = floor.then_some(0.0); }
                if let Some(height) = &mut settings.ground_height {
                    ui.horizontal(|ui| { ui.label("Floor height (Y)"); ui.add(crate::cdmw_ui::numeric::value(height).speed(0.01)); });
                }
                if ui.button("Reset cloth preview settings").clicked() {
                    *settings = crate::cdmw_cloth::preview::default_settings(settings.spline);
                    self.cdmw_cloth.profiles.clear_loaded();
                }
            });
            changed |= crate::cdmw_cloth::profiles::draw(ui, &self.cdmw_state["physics_profiles"], parts,
                &mut self.cdmw_cloth.profiles, &mut preview.cloth_settings,
                cloth_state["available"].as_bool() == Some(true), cloth_state["rotation_available"].as_bool() == Some(true),
                spline_available,
                actions,
                can_author,
            );
            ui.small(if preview.cloth_settings.spline {
                "Experimental ordered spline chains with stretch, bend and angular spring-back."
            } else {
                "Experimental guide cloth with controlled motion and preview settings."
            });
        } else {
            ui.add(crate::cdmw_ui::numeric::slider(&mut preview.settings.softness, 0.0..=1.0).text("Preview softness"));
            ui.add(crate::cdmw_ui::numeric::slider(&mut preview.settings.damping, 0.0..=1.0).text("Preview damping"));
        }
        if changed {
            self.cancel_pending_jiggle();
            if was_playing {
                self.cdmw_jiggle.preview.playing = false;
                if let Err(error) = self.start_jiggle_preview(parts) { self.cdmw_jiggle.preview.feedback = error.to_string(); }
            } else {
                self.publish_mesh_snapshot();
            }
        }
        let reason = if self.cdmw_busy() {
            "Wait for the current operation."
        } else if self.cdmw_jiggle.preview.pending.is_some() {
            "Preparing decoded motion."
        } else if self.cdmw_jiggle.preview.solver != Solver::Approximate
            && self.cdmw_state["jiggle"]["decoded"]["available"].as_bool() != Some(true) {
            self.cdmw_state["jiggle"]["decoded"]["reason"].as_str()
                .unwrap_or("Decoded motion needs a matching fixed-layout PAB skeleton.")
        } else if cloth && self.cdmw_state["jiggle"]["decoded"]["cloth"]["available"].as_bool() != Some(true) {
            self.cdmw_state["jiggle"]["decoded"]["cloth"]["reason"].as_str()
                .unwrap_or("Cloth preview needs a decoded guide mesh.")
        } else if !cloth
            && self.cdmw_jiggle.preview.solver == Solver::Decoded
            && self.cdmw_state["jiggle"]["decoded"]["rig_mode"] == "rigid_attachment"
        {
            "Decoded bone motion needs a matching fixed-layout PAB skeleton."
        } else if cloth
            && self.cdmw_jiggle.preview.cloth_settings.spline
            && self.cdmw_state["jiggle"]["decoded"]["cloth"]["spline_available"].as_bool()
                != Some(true)
        {
            "Spline preview needs complete ordered guide chains with fixed roots."
        } else if cloth
            && !self.cdmw_jiggle.preview.cloth_settings.spline
            && self.cdmw_state["jiggle"]["decoded"]["rig_mode"] == "rigid_attachment"
        {
            "Standalone rigid attachment preview requires spline mode."
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
        }.to_owned();
        ui.horizontal_wrapped(|ui| {
            let label = if self.cdmw_jiggle.preview.pending.is_some() {
                "Preparing preview"
            } else if self.cdmw_jiggle.preview.playing {
                "Pause preview"
            } else if self.cdmw_jiggle.preview.scene.is_some() && self.cdmw_jiggle.preview.feedback.is_empty() {
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
                    self.cdmw_jiggle.preview.manual_drag = None;
                } else if self.cdmw_jiggle.preview.scene.is_some() && self.cdmw_jiggle.preview.feedback.is_empty() {
                    self.cdmw_jiggle.preview.playing = true;
                    self.cdmw_jiggle.preview.last_tick = Instant::now();
                } else if let Err(error) = self.start_jiggle_preview(parts) {
                    self.cdmw_jiggle.preview.feedback = error.to_string();
                }
            }
            if ui
                .add_enabled(
                    self.cdmw_jiggle.preview.scene.is_some() || self.cdmw_jiggle.preview.pending.is_some(),
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
        if cloth {
            ui.small("Runtime profile activation and layer/world collisions are not simulated.");
        } else {
            ui.small("Inter-part collisions and guide-cloth simulation are not included in this preview.");
        }
        ui.small("Preview settings are not exported. Reset preview to edit the surface.");
        if self.cdmw_jiggle.preview.playing || self.cdmw_jiggle.preview.pending.is_some() {
            ui.ctx().request_repaint();
        }
    }

    fn start_jiggle_preview(&mut self, parts: &[Value]) -> Result<()> {
        if self.cdmw_jiggle.preview.solver == Solver::Decoded
            && self.cdmw_state["jiggle"]["decoded"]["rig_mode"] == "rigid_attachment" {
            bail!("Decoded bone motion needs a matching fixed-layout PAB skeleton.");
        }
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
        let mut retained_bytes = HashMap::new();
        let mut expected = HashMap::new();
        let cloth = self.cdmw_jiggle.preview.solver == Solver::Cloth;
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
            let original = self.cdmw_jiggle.preview.comparison == Comparison::Original;
            let key = match (cloth, original) {
                (true, true) => "original_cloth_bytes", (true, false) => "current_cloth_bytes",
                (false, true) => "original_bytes", (false, false) => "current_bytes",
            };
            let mut mask = if cloth {
                if data["available"].as_bool() != Some(true) { bail!("Unverified source vertex ownership."); }
                let count = data["vertex_count"].as_u64().filter(|n| *n > 0 && *n <= 100_000)
                    .ok_or_else(|| anyhow::anyhow!("Invalid preview vertex count."))? as usize;
                let values = data[key].as_array().filter(|values| values.len() == count)
                    .ok_or_else(|| anyhow::anyhow!("Missing or incomplete cloth vertex bytes."))?;
                values.iter().map(|value| value.as_u64().filter(|v| *v <= 63)
                    .map(|v| (63 - v) as f32/63.0).ok_or_else(|| anyhow::anyhow!("Invalid cloth vertex byte.")))
                    .collect::<Result<Vec<_>>>()?
            } else { preview_weights(data, key, 100_000)? };
            let mut bytes = data[key].as_array().expect("validated preview bytes").iter()
                .map(|value| value.as_u64().expect("validated preview byte") as u8).collect::<Vec<_>>();
            if self.cdmw_jiggle.preview.comparison == Comparison::Disabled {
                mask.fill(0.0);
                bytes.fill(if cloth { 63 } else { 255 });
            }
            if masks.insert(index, mask).is_some() {
                bail!("Duplicate jiggle part.");
            }
            expected.insert(index, HashSet::new());
            retained_bytes.insert(index, bytes);
        }
        if masks.is_empty() {
            bail!("Select a visible part with verified jiggle data.");
        }
        let mut active = Vec::new();
        let mut native_vertices = Vec::new();
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
                0.0
            };
            if rendered {
                active.push(value);
                let byte = retained_bytes.get(&submesh).and_then(|bytes| bytes.get(element as usize)).copied()
                    .unwrap_or(if cloth { 63 } else { 255 });
                native_vertices.push((submesh, element, byte));
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
        if self.cdmw_jiggle.preview.solver != Solver::Approximate {
            let source = self.cdmw_bridge.as_ref().ok_or_else(|| anyhow::anyhow!("No active Mesh Editor session."))?
                .jiggle_source(&self.cdmw_state)?;
            let generation = self.loader.prepare_jiggle(native::Request {
                source, rest, vertices: native_vertices,
                enabled: self.cdmw_jiggle.preview.comparison != Comparison::Disabled,
                cloth,
                geometry_revision: mesh.geometry_revision,
            })?;
            self.cdmw_jiggle.preview.pending = Some(generation);
            self.cdmw_jiggle.preview.feedback.clear();
            return Ok(());
        }
        let moving = active.iter().filter(|v| **v > 0.0).count();
        let simulation = jiggle::Simulation::new(&rest.positions, &rest.indices, active)
            .map_err(anyhow::Error::msg)?;
        let mut rest_surface_normals = vec![Vec3::ZERO; rest.positions.len()];
        surface_normals(&rest, &mut rest_surface_normals);
        for normal in &mut rest_surface_normals {
            *normal = normal.normalize_or_zero();
        }
        let scene = Scene {
            centred: false,
            motion_scale: motion_scale(&rest),
            rest_surface_normals,
            frame: rest.clone(),
            normal_sums: vec![Vec3::ZERO; rest.positions.len()],
            rest,
            simulation: Simulation::Approximate(simulation),
            tick: 0,
            moving,
        };
        self.cdmw_jiggle.preview.scene = Some(scene);
        self.cdmw_jiggle.preview.playing = true;
        self.cdmw_jiggle.preview.feedback.clear();
        self.cdmw_jiggle.preview.last_tick = Instant::now();
        Ok(())
    }

    pub(super) fn handle_jiggle_pointer(&mut self, event: &ViewportPointerEvent, rectangle: egui::Rect) -> bool {
        let preview = &mut self.cdmw_jiggle.preview;
        let Some(scene) = &preview.scene else { return false; };
        let jiggle::Motion::Freehand(offset) = preview.motion else { return false; };
        match *event {
            ViewportPointerEvent::PrimaryPressed(point) => {
                if preview.playing && point.is_finite() {
                    preview.manual_drag = Some((point, offset));
                }
            }
            ViewportPointerEvent::PrimaryMoved(point) | ViewportPointerEvent::PrimaryReleased(point) => {
                if let Some((start, offset)) = preview.manual_drag
                    && preview.playing && point.is_finite()
                {
                    let offset = offset + self.camera.screen_delta_to_world(point - start, rectangle);
                    if offset.is_finite() {
                        preview.motion = jiggle::Motion::Freehand(offset.clamp_length_max(scene.motion_scale));
                    }
                }
                if matches!(event, ViewportPointerEvent::PrimaryReleased(_)) {
                    preview.manual_drag = None;
                }
            }
            _ => return false,
        }
        true
    }

    pub(super) fn advance_jiggle_preview(&mut self, seconds: f64) -> Result<()> {
        let preview = &mut self.cdmw_jiggle.preview;
        let Some(scene) = &mut preview.scene else {
            return Ok(());
        };
        let before = scene.simulation.elapsed();
        if preview.playing {
            scene
                .simulation
                .advance(seconds, preview.motion, preview.settings, preview.native_settings, preview.cloth_settings)?;
        }
        // Pausing/camera movement does not need a new geometry upload.
        if scene.tick > 0 && scene.simulation.elapsed() == before && scene.centred == preview.keep_centred {
            return Ok(());
        }
        scene.simulation.copy_positions(&mut scene.frame.positions);
        if preview.keep_centred {
            // Follow only the test's rigid motion, never the simulated vertices.
            // Applying the inverse to the draw copy is equivalent to following
            // the body with the camera, without changing orbit/pan or solver state.
            let inverse = scene.simulation.motion_transform().inverse();
            for position in &mut scene.frame.positions {
                *position = inverse.transform_point3(Vec3::from(*position)).to_array();
            }
        }
        surface_normals(&scene.frame, &mut scene.normal_sums);
        let rotation = if preview.keep_centred { Quat::IDENTITY } else { scene.simulation.rotation(preview.motion) };
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
        scene.centred = preview.keep_centred;
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
            let lines = self.jiggle_weapon_lines();
            if let (Some(renderer), Some(scene)) =
                (&mut self.renderer, &self.cdmw_jiggle.preview.scene)
            {
                renderer.set_face_selection(&[], [0.0; 4])?;
                renderer.set_preview_lines(&lines)?;
                if let Some(colours) = &self.cdmw_jiggle.region_colours {
                    renderer.set_snapshot_with_vertex_colours(&scene.frame, colours)?;
                } else {
                    renderer.set_snapshot_with_deformation_interactive(&scene.frame, None)?;
                }
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

    pub(super) fn jiggle_weapon_lines(&self) -> Vec<cdmw_render_wgpu::EffectLineVertex> {
        let preview = &self.cdmw_jiggle.preview;
        if !preview.show_weapon_colliders { return Vec::new(); }
        preview.scene.as_ref().map(|scene| scene.simulation.weapon_lines(preview.keep_centred)).unwrap_or_default()
    }

    pub(super) fn cancel_pending_jiggle(&mut self) {
        if let Some(generation) = self.cdmw_jiggle.preview.pending.take() { self.loader.cancel_generation(generation); }
    }

    pub(super) fn accept_prepared_jiggle(&mut self, generation: u64, result: std::result::Result<native::Prepared, String>) {
        if self.cdmw_jiggle.preview.pending != Some(generation) { return; }
        self.cdmw_jiggle.preview.pending = None;
        match result {
            Ok(prepared) => {
                if self.edit_gesture.is_some() || self.selection_gesture.is_some() || self.cdmw_busy()
                    || self.mesh.as_ref().is_none_or(|mesh| mesh.geometry_revision != prepared.geometry_revision
                        || mesh.topology_generation != prepared.rest.topology_generation) {
                    self.cdmw_jiggle.preview.feedback = "The mesh changed while preparing decoded motion. Play again after the operation.".into();
                    return;
                }
                let count = prepared.rest.positions.len();
                self.cdmw_jiggle.preview.scene = Some(Scene { motion_scale: motion_scale(&prepared.rest), frame: prepared.rest.clone(), rest: prepared.rest,
                    simulation: prepared.simulation, normal_sums: vec![Vec3::ZERO; count],
                    rest_surface_normals: prepared.rest_surface_normals, tick: 0, moving: prepared.moving, centred: false });
                self.cdmw_jiggle.preview.playing = true;
                self.cdmw_jiggle.preview.feedback.clear();
                self.cdmw_jiggle.preview.last_tick = Instant::now();
            }
            Err(error) => self.cdmw_jiggle.preview.feedback = error,
        }
    }
}
