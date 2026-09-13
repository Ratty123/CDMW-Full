//! Hair controls and background generation in the existing authoring viewport.
use super::*;
use cdmw_mesh::hair::{
    self, Attachment, Groom, GroupMode, HairGroup, HairState, MotionSettings, Preset, Simulation,
};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{Receiver, TryRecvError};
use std::thread;

#[cfg(test)]
#[path = "cdmw_hair_tests.rs"]
mod tests;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum HairTool {
    Paint,
    Guide,
    Select,
    Root,
    Comb,
    Smooth,
    Cut,
    Lengthen,
    Curl,
    Clump,
}

struct PreparedHair {
    state: HairState,
    document: MeshDocument,
    label: String,
    milliseconds: f64,
}
#[derive(Clone)]
enum Preparation {
    Generate,
    Metadata,
    Bind(u32),
    Rebind,
    Fill(u32, Preset, f32),
}
struct HairScene {
    rest: DrawSnapshot,
    frame: DrawSnapshot,
    parts: Vec<(u32, usize, usize, Vec<u32>)>,
    reference_start: usize,
    show_reference: bool,
    applied: bool,
}
struct HairJob {
    revision: u64,
    cancel: Arc<AtomicBool>,
    receiver: Receiver<Result<PreparedHair, String>>,
    handle: thread::JoinHandle<()>,
}
impl Drop for HairJob {
    fn drop(&mut self) {
        self.cancel.store(true, Ordering::Relaxed);
    }
}

pub(super) struct HairEditor {
    pub state: Option<HairState>,
    stroke: Option<HairState>,
    pub tool: Option<HairTool>,
    pub selected: HashSet<usize>,
    job: Option<HairJob>,
    queued: Option<(HairState, MeshDocument, String, Preparation)>,
    generation: u64,
    pub playing: bool,
    restart_after_stroke: bool,
    simulation: Option<Simulation>,
    pub motion: MotionSettings,
    pub head_test: u32,
    rotation: Quat,
    last_tick: Instant,
    preview: Option<MeshDocument>,
    pub group: u32,
    pub preset: Preset,
    pub length: f32,
    pub radius: f32,
    pub strength: f32,
    pub symmetry: bool,
    pub width: f32,
    pub density: u32,
    pub atlas: [f32; 4],
    pub target_stem: String,
    pub texture_index: usize,
    pub pending_start: Option<String>,
    pub show_reference: bool,
    pub show_guides: bool,
    last_pointer: Option<Vec2>,
    last_plant: Option<Vec3>,
    pub feedback: String,
    draw_revision: u64,
    scene: Option<HairScene>,
}
impl Default for HairEditor {
    fn default() -> Self {
        Self {
            state: None,
            stroke: None,
            tool: None,
            selected: HashSet::new(),
            job: None,
            queued: None,
            generation: 0,
            playing: false,
            restart_after_stroke: false,
            simulation: None,
            motion: MotionSettings::default(),
            head_test: 0,
            rotation: Quat::IDENTITY,
            last_tick: Instant::now(),
            preview: None,
            group: 0,
            preset: Preset::Long,
            length: 0.3,
            radius: 35.0,
            strength: 0.25,
            symmetry: false,
            width: 0.01,
            density: 6,
            atlas: [0.0, 0.0, 1.0, 1.0],
            target_stem: String::new(),
            texture_index: 0,
            pending_start: None,
            show_reference: true,
            show_guides: true,
            last_pointer: None,
            last_plant: None,
            feedback: String::new(),
            draw_revision: 0,
            scene: None,
        }
    }
}

#[derive(Debug, Clone)]
pub(super) enum HairAction {
    Rebuild,
    Bind,
    AddGroups,
    Rebind,
    Convert,
    DeleteGuides,
    Settings,
    Settle,
    Reset,
    Fill,
    Registration,
}

fn prepare(
    mut state: HairState,
    mut document: MeshDocument,
    label: String,
    operation: Preparation,
    cancelled: &AtomicBool,
) -> Result<PreparedHair, String> {
    let start = Instant::now();
    if cancelled.load(Ordering::Relaxed) {
        return Err("Hair preparation cancelled".into());
    }
    if matches!(operation, Preparation::Rebind) {
        state
            .rebind_cancellable(state.scalp.clone(), cancelled)
            .map_err(|e| e.to_string())?;
    }
    if matches!(operation, Preparation::Metadata) {
        return Ok(PreparedHair {
            state,
            document,
            label,
            milliseconds: start.elapsed().as_secs_f64() * 1000.0,
        });
    }
    state.validate().map_err(|e| e.to_string())?;
    if let Preparation::Fill(group, preset, length) = operation {
        let (min, max) = hair_bounds(&state);
        let top = min.y + (max.y - min.y) * 0.60;
        let faces: Vec<_> = state
            .scalp
            .triangles
            .iter()
            .enumerate()
            .filter(|(_, face)| {
                face.iter()
                    .all(|i| state.scalp.positions[*i as usize][1] >= top)
            })
            .map(|(i, _)| i as u32)
            .collect();
        if faces.is_empty() {
            return Err("Paint scalp coverage on the reference head first".into());
        }
        for i in 0..256.min(faces.len()) {
            if cancelled.load(Ordering::Relaxed) {
                return Err("Hair preparation cancelled".into());
            }
            let triangle = faces[i * faces.len() / 256.min(faces.len())];
            hair::plant_guide(
                &mut state,
                Attachment {
                    triangle,
                    barycentric: [1.0 / 3.0; 3],
                },
                group,
                preset,
                length,
                16,
            )
            .map_err(|e| e.to_string())?;
        }
    }
    let lod = document.lods.first_mut().ok_or("Hair requires LOD0")?;
    if let Preparation::Bind(group) = operation {
        let parts: Vec<_> = state
            .groups
            .iter()
            .filter(|g| g.id == group && g.mode == GroupMode::Existing)
            .map(|g| g.part)
            .collect();
        if parts.is_empty() {
            return Err("Choose an existing hair group to bind".into());
        }
        for part in parts {
            let source = lod
                .submeshes
                .get(part as usize)
                .ok_or("Hair group has a missing part")?;
            hair::bind_existing(&mut state, part, &source.positions, cancelled)
                .map_err(|e| e.to_string())?;
        }
    }
    let generated = hair::generate(&state, cancelled).map_err(|e| e.to_string())?;
    for geometry in generated {
        let part = lod
            .submeshes
            .get_mut(geometry.part as usize)
            .ok_or("Choose an existing material part for this hair group")?;
        part.positions = geometry.positions;
        part.normals = geometry.normals;
        part.uvs = geometry.uvs;
        part.indices = geometry.indices;
        part.source_vertex_indices = vec![-1; part.positions.len()];
        state.bindings.retain(|b| b.part != geometry.part);
        state.bindings.extend(geometry.bindings);
    }
    let points: Vec<_> = state.guides.iter().map(|g| g.points.clone()).collect();
    for group in state
        .groups
        .iter()
        .filter(|g| g.mode == GroupMode::Existing)
    {
        let part = lod
            .submeshes
            .get_mut(group.part as usize)
            .ok_or("Hair group part is missing")?;
        hair::deform(&state.bindings, &points, group.part, &mut part.positions)
            .map_err(|e| e.to_string())?;
        normals(&part.positions, &part.indices, &mut part.normals);
    }
    if cancelled.load(Ordering::Relaxed) {
        return Err("Hair preparation cancelled".into());
    }
    Ok(PreparedHair {
        state,
        document,
        label,
        milliseconds: start.elapsed().as_secs_f64() * 1000.0,
    })
}

fn normals(positions: &[[f32; 3]], indices: &[u32], output: &mut Vec<[f32; 3]>) {
    output.resize(positions.len(), [0.0; 3]);
    normals_into(positions, indices, output);
}
fn normals_into(positions: &[[f32; 3]], indices: &[u32], output: &mut [[f32; 3]]) {
    output.fill([0.0; 3]);
    for face in indices.chunks_exact(3) {
        let [a, b, c] = [face[0] as usize, face[1] as usize, face[2] as usize];
        let normal = (Vec3::from(positions[b]) - Vec3::from(positions[a]))
            .cross(Vec3::from(positions[c]) - Vec3::from(positions[a]));
        for i in [a, b, c] {
            output[i] = (Vec3::from(output[i]) + normal).to_array();
        }
    }
    for n in output {
        *n = Vec3::from(*n).try_normalize().unwrap_or(Vec3::Y).to_array();
    }
}

impl LabApplication {
    pub(super) fn hydrate_hair(&mut self, state: Option<HairState>) {
        let changed = self.hair.state.as_ref() != state.as_ref();
        if !changed && self.hair.preview.is_none() {
            return;
        }
        let first = self.hair.state.is_none();
        self.hair.generation += 1;
        if let Some(job) = &self.hair.job {
            job.cancel.store(true, Ordering::Relaxed);
        }
        self.hair.queued = None;
        self.hair.stroke = None;
        self.hair.preview = None;
        self.hair.scene = None;
        self.hair.simulation = state.as_ref().and_then(|s| Simulation::new(s).ok());
        self.hair.last_tick = Instant::now();
        self.hair.rotation = Quat::IDENTITY;
        if let Some(hair) = &state {
            self.hair.target_stem = hair.template.target_stem.clone();
            self.hair
                .selected
                .retain(|index| *index < hair.guides.len());
            if let Some(group) = hair
                .groups
                .iter()
                .find(|g| g.id == self.hair.group)
                .or(hair.groups.first())
            {
                self.hair.group = group.id;
                self.hair.width = group.width;
                self.hair.density = group.cards_per_guide;
                self.hair.atlas = group.uv_rect;
            }
            if first {
                let (minimum, maximum) = hair_bounds(hair);
                self.hair.length = (maximum - minimum).max_element() * 0.9;
                if let Some(rect) = self.viewport_rect {
                    self.camera
                        .frame_explicit_bounds_in_viewport(minimum, maximum, rect);
                }
                self.hair.tool = Some(HairTool::Paint);
                self.cdmw_orbit_mode = false;
            }
            if hair.converted {
                self.hair.tool = None;
                self.hair.playing = false;
            }
            if hair.bound_reference != hair.scalp.identity {
                self.hair.playing = false;
                self.hair.feedback =
                    "Reference changed. Rebind roots before grooming or simulation.".into();
            }
        } else {
            self.hair.playing = false;
            self.hair.tool = None;
        }
        self.hair.state = state;
    }

    fn queue_hair(&mut self, state: HairState, label: &str, operation: Preparation) {
        let Some(document) = &self.document else {
            return;
        };
        self.hair.generation += 1;
        self.hair.queued = Some((state, document.clone(), label.to_owned(), operation));
        if let Some(job) = &self.hair.job {
            job.cancel.store(true, Ordering::Relaxed);
        }
        self.hair.feedback = "Preparing hair…".into();
        self.start_hair_job();
    }

    fn start_hair_job(&mut self) {
        if self.hair.job.is_some() {
            return;
        }
        let Some((state, document, label, bind)) = self.hair.queued.take() else {
            return;
        };
        let (sender, receiver) = std::sync::mpsc::sync_channel(1);
        let cancel = Arc::new(AtomicBool::new(false));
        let stop = cancel.clone();
        let handle = thread::spawn(move || {
            let _ = sender.send(prepare(state, document, label, bind, &stop));
        });
        self.hair.job = Some(HairJob {
            revision: self.hair.generation,
            cancel,
            receiver,
            handle,
        });
    }

    pub(super) fn poll_hair(&mut self) {
        if self.cdmw_busy() {
            return;
        }
        if let Some(mode) = self.hair.pending_start.take() {
            self.submit_cdmw_command("hair_begin", json!({"mode": mode}), "Load hair reference");
            return;
        }
        let completion = self
            .hair
            .job
            .as_ref()
            .filter(|job| job.handle.is_finished())
            .and_then(|job| match job.receiver.try_recv() {
                Ok(result) => Some((job.revision, result)),
                Err(TryRecvError::Disconnected) => Some((
                    job.revision,
                    Err("Hair worker stopped before completing".into()),
                )),
                Err(TryRecvError::Empty) => None,
            });
        if let Some((revision, result)) = completion {
            self.hair.job.take();
            if let Some(scene) = &mut self.hair.scene {
                scene.applied = false;
            }
            if revision == self.hair.generation && !self.cdmw_busy() {
                match result {
                    Ok(prepared) => {
                        self.hair.feedback = format!("Prepared in {:.1} ms", prepared.milliseconds);
                        let result = self.cdmw_bridge.as_mut().map(|bridge| {
                            bridge.submit_hair_transaction(
                                &prepared.document,
                                &prepared.state,
                                &prepared.label,
                            )
                        });
                        match result {
                            Some(Ok(request_id)) => {
                                self.hair.preview = Some(prepared.document);
                                self.hair.state = Some(prepared.state);
                                self.hair.scene = None;
                                self.cdmw_pending_request = Some(CdmwPendingRequest {
                                    request_id,
                                    event: "transaction_result",
                                    label: prepared.label,
                                    origin: None,
                                });
                            }
                            Some(Err(error)) => self.hair.feedback = error.to_string(),
                            None => {}
                        }
                    }
                    Err(error) => self.hair.feedback = error,
                }
            }
            self.start_hair_job();
        }
        if self.hair.job.is_some() || self.hair.playing {
            self.egui_context.request_repaint();
        }
    }

    pub(super) fn run_hair_action(&mut self, action: HairAction) {
        if self.cdmw_busy() {
            return;
        }
        let Some(mut state) = self.hair.state.clone() else {
            return;
        };
        let mut operation = Preparation::Generate;
        let result: Result<&str, String> = (|| {
            match action {
                HairAction::Reset => {
                    self.hair.simulation =
                        Some(Simulation::new(&state).map_err(|e| e.to_string())?);
                    self.hair.rotation = Quat::IDENTITY;
                    self.hair.last_tick = Instant::now();
                    if let Some(scene) = &mut self.hair.scene {
                        scene.applied = false;
                    }
                    return Ok("");
                }
                HairAction::Settle => {
                    state = self
                        .hair
                        .simulation
                        .as_ref()
                        .ok_or("Play the simulation first")?
                        .settled_state(&state, self.hair.rotation)
                        .map_err(|e| e.to_string())?;
                    self.hair.playing = false;
                }
                HairAction::Convert => {
                    state.converted = true;
                    operation = Preparation::Metadata;
                    self.hair.playing = false;
                    self.hair.tool = None;
                }
                HairAction::Rebind => {
                    operation = Preparation::Rebind;
                }
                HairAction::AddGroups => {
                    let selected = self.selected_part_indices();
                    if selected.is_empty() {
                        return Err(
                            "Select hair Parts to create explicit deformation groups".into()
                        );
                    }
                    for part in selected {
                        if state.groups.iter().any(|g| g.part == part) {
                            continue;
                        }
                        let id = state.groups.iter().map(|g| g.id).max().unwrap_or(0) + 1;
                        state.groups.push(HairGroup {
                            id,
                            name: format!("Hair part {}", part + 1),
                            part,
                            mode: state.groups.first().map_or(GroupMode::Existing, |g| g.mode),
                            width: self.hair.width,
                            cards_per_guide: self.hair.density,
                            uv_rect: self.hair.atlas,
                        });
                        self.hair.group = id;
                    }
                }
                HairAction::DeleteGuides => {
                    let mut remap = HashMap::new();
                    let mut index = 0;
                    for i in 0..state.guides.len() {
                        if !self.hair.selected.contains(&i) {
                            remap.insert(i as u32, index);
                            index += 1;
                        }
                    }
                    state.guides = std::mem::take(&mut state.guides)
                        .into_iter()
                        .enumerate()
                        .filter(|(i, _)| !self.hair.selected.contains(i))
                        .map(|(_, g)| g)
                        .collect();
                    state.bindings.retain_mut(|binding| {
                        if let Some(index) = remap.get(&binding.guide) {
                            binding.guide = *index;
                            true
                        } else {
                            false
                        }
                    });
                    self.hair.selected.clear();
                }
                HairAction::Settings => {
                    let group = state
                        .groups
                        .iter_mut()
                        .find(|g| g.id == self.hair.group)
                        .ok_or("Choose a group")?;
                    group.width = self.hair.width;
                    group.cards_per_guide = self.hair.density;
                    group.uv_rect = self.hair.atlas;
                }
                HairAction::Fill => {
                    operation =
                        Preparation::Fill(self.hair.group, self.hair.preset, self.hair.length);
                }
                HairAction::Bind => operation = Preparation::Bind(self.hair.group),
                HairAction::Registration => {
                    state.template.target_stem = self.hair.target_stem.trim().to_owned();
                    operation = Preparation::Metadata;
                }
                HairAction::Rebuild => {}
            }
            state.revision += 1;
            Ok(match action {
                HairAction::Convert => "Convert hair to ordinary mesh",
                HairAction::Settle => "Use settled hair shape",
                HairAction::Rebind => "Rebind hair roots",
                HairAction::AddGroups => "Group existing hair",
                HairAction::DeleteGuides => "Delete hair guides",
                HairAction::Settings => "Set hair appearance",
                HairAction::Fill => "Generate hairstyle preset",
                HairAction::Bind => "Bind existing hair",
                HairAction::Registration => "Set hairstyle registration",
                _ => "Generate hair",
            })
        })();
        match result {
            Ok("") => {}
            Ok(label) => self.queue_hair(state, label, operation),
            Err(error) => self.hair.feedback = error,
        }
    }

    pub(super) fn draw_hair_controls(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let available = self.cdmw_state["hair"]["available"]
            .as_bool()
            .unwrap_or(false);
        if !available && self.hair.state.is_none() {
            return;
        }
        egui::CollapsingHeader::new("Hair").id_salt("hair-authoring").default_open(true).show(ui, |ui| {
            if self.hair.state.is_none() {
                ui.label("Create hair from guides or reshape the loaded hairstyle.");
                ui.horizontal_wrapped(|ui| {
                    for (label, mode) in [("Create Hair", "generated"), ("Edit Hair", "existing")] {
                        if ui.button(label).clicked() {
                            actions.push(UiAction::CdmwCommand { command: "hair_begin",
                                arguments: json!({"mode": mode}), label: "Load hair reference" });
                        }
                    }
                });
                return;
            }
            let state = self.hair.state.as_ref().unwrap();
            let groups = state.groups.clone();
            let converted = state.converted;
            let bound = state.bound_reference == state.scalp.identity;
            let guide_count = state.guides.len();
            let (minimum, maximum) = hair_bounds(state);
            let span = (maximum - minimum).max_element();
            ui.weak("Additional Damiane choice · game checks pending");
            egui::CollapsingHeader::new("Setup").default_open(true).show(ui, |ui| {
                egui::ComboBox::from_label("Group").selected_text(
                    groups.iter().find(|g| g.id == self.hair.group).map_or("Choose group", |g| g.name.as_str()))
                    .show_ui(ui, |ui| {
                        for group in &groups {
                            if ui.selectable_value(&mut self.hair.group, group.id, &group.name).changed() {
                                self.hair.width = group.width;
                                self.hair.density = group.cards_per_guide;
                                self.hair.atlas = group.uv_rect;
                            }
                        }
                    });
                ui.label("New hairstyle asset name");
                ui.text_edit_singleline(&mut self.hair.target_stem);
                if ui.button("Apply registration name").clicked() { actions.push(UiAction::Hair(HairAction::Registration)); }
                if ui.add_enabled(!converted && bound, egui::Button::new("Group selected Parts")).clicked() { actions.push(UiAction::Hair(HairAction::AddGroups)); }
                if ui.add_enabled(!converted, egui::Button::new("Change reference head…")).clicked() {
                    actions.push(UiAction::CdmwCommand { command: "hair_begin", arguments: json!({}), label: "Change hair reference" });
                }
                if !bound {
                    ui.colored_label(Color32::YELLOW, "Bindings need rebinding");
                    if ui.button("Rebind roots").clicked() { actions.push(UiAction::Hair(HairAction::Rebind)); }
                }
                ui.checkbox(&mut self.hair.show_reference, "Show head and shoulders");
                ui.checkbox(&mut self.hair.show_guides, "Show guides and roots");
                if converted {
                    ui.label("Ordinary mesh geometry. Undo conversion to restore grooming.");
                }
            });
            ui.add_enabled_ui(!converted && bound, |ui| {
                egui::CollapsingHeader::new("Groom").default_open(true).show(ui, |ui| {
                    egui::ComboBox::from_label("Preset").selected_text(format!("{:?}", self.hair.preset)).show_ui(ui, |ui| {
                        for preset in [Preset::Cropped, Preset::Bob, Preset::Long, Preset::Ponytail] {
                            if ui.selectable_value(&mut self.hair.preset, preset, format!("{preset:?}")).changed() {
                                self.hair.length = span * match preset {
                                    Preset::Cropped => 0.18, Preset::Bob => 0.7, Preset::Long => 1.4, Preset::Ponytail => 1.6,
                                };
                            }
                        }
                    });
                    ui.add(egui::Slider::new(&mut self.hair.length, span * 0.02..=span * 3.0).text("Length"));
                    if ui.button("Fill upper scalp from preset").clicked() { actions.push(UiAction::Hair(HairAction::Fill)); }
                    ui.horizontal_wrapped(|ui| {
                        for (tool, label) in [(HairTool::Paint, "Coverage"), (HairTool::Guide, "Place guide"),
                            (HairTool::Select, "Select"), (HairTool::Root, "Correct roots"), (HairTool::Comb, "Comb"),
                            (HairTool::Smooth, "Smooth"), (HairTool::Cut, "Cut"), (HairTool::Lengthen, "Lengthen"),
                            (HairTool::Curl, "Curl"), (HairTool::Clump, "Clump")] {
                            if ui.selectable_label(self.hair.tool == Some(tool), label).clicked() {
                                self.hair.tool = if self.hair.tool == Some(tool) { None } else { Some(tool) };
                                self.cdmw_orbit_mode = false;
                            }
                        }
                    });
                    ui.add(egui::Slider::new(&mut self.hair.radius, 5.0..=160.0).text("Brush pixels"));
                    ui.add(egui::Slider::new(&mut self.hair.strength, 0.01..=1.0).text("Strength"));
                    ui.checkbox(&mut self.hair.symmetry, "Symmetry");
                    ui.label(format!("{} guides · {} selected", guide_count, self.hair.selected.len()));
                    ui.horizontal_wrapped(|ui| {
                        if ui.button("Bind existing group").clicked() { actions.push(UiAction::Hair(HairAction::Bind)); }
                        if ui.button("Delete selected guides").clicked() { actions.push(UiAction::Hair(HairAction::DeleteGuides)); }
                        if ui.button("Regenerate").clicked() { actions.push(UiAction::Hair(HairAction::Rebuild)); }
                    });
                });
                egui::CollapsingHeader::new("Appearance").show(ui, |ui| {
                    ui.label("Template hair materials and DDS textures");
                    let textures: Vec<_> = self.cdmw_state["hair"]["textures"].as_array().into_iter().flatten()
                        .filter_map(|v| v.as_str().map(String::from)).collect();
                    if !textures.is_empty() {
                        self.hair.texture_index = self.hair.texture_index.min(textures.len() - 1);
                        egui::ComboBox::from_label("Texture").selected_text(
                            textures[self.hair.texture_index].rsplit('/').next().unwrap_or("DDS")).show_ui(ui, |ui| {
                                for (i, path) in textures.iter().enumerate() {
                                    ui.selectable_value(&mut self.hair.texture_index, i, path.rsplit('/').next().unwrap_or(path));
                                }
                            });
                        for (title, command) in [("Open in Texture Editor", "hair_texture_export"), ("Apply edited DDS…", "hair_texture")] {
                            if ui.button(title).clicked() {
                                actions.push(UiAction::CdmwCommand { command, arguments: json!({"texture_path": textures[self.hair.texture_index]}),
                                    label: "Hair texture" });
                            }
                        }
                        ui.weak("Export the edited DDS, then apply it here.");
                    }
                    let generated = groups.iter().any(|g| g.id == self.hair.group && g.mode == GroupMode::Generated);
                    ui.add_enabled_ui(generated, |ui| {
                    ui.add(egui::Slider::new(&mut self.hair.width, 0.0001..=(span * 0.2).clamp(0.001, 10.0)).text("Card width"));
                    ui.add(egui::Slider::new(&mut self.hair.density, 1..=32).text("Density"));
                    ui.label("Texture atlas region (U/V minimum and maximum)");
                    ui.horizontal_wrapped(|ui| { for value in &mut self.hair.atlas { ui.add(egui::DragValue::new(value).speed(0.01)); } });
                    if ui.button("Apply appearance").clicked() { actions.push(UiAction::Hair(HairAction::Settings)); }
                    });
                    if !generated { ui.weak("Existing groups retain their card topology and UV layout."); }
                });
                egui::CollapsingHeader::new("Motion").show(ui, |ui| {
                    ui.weak("Approximate preview; exported game physics uses the template.");
                    ui.horizontal_wrapped(|ui| {
                        if ui.button(if self.hair.playing { "Pause" } else { "Play" }).clicked() {
                            self.hair.playing = !self.hair.playing;
                            self.hair.last_tick = Instant::now();
                        }
                        if ui.button("Reset").clicked() { actions.push(UiAction::Hair(HairAction::Reset)); }
                    });
                    egui::ComboBox::from_label("Head test").selected_text(["Still", "Turn", "Nod"][self.hair.head_test as usize])
                        .show_ui(ui, |ui| {
                            for (i, label) in ["Still", "Turn", "Nod"].iter().enumerate() {
                                ui.selectable_value(&mut self.hair.head_test, i as u32, *label);
                            }
                        });
                    ui.add(egui::Slider::new(&mut self.hair.motion.damping, 0.0..=20.0).text("Damping"));
                    ui.add(egui::Slider::new(&mut self.hair.motion.bend_compliance, 0.0..=0.005).text("Bend softness"));
                    ui.add(egui::Slider::new(&mut self.hair.motion.gravity[1], -20.0..=0.0).text("Gravity"));
                    ui.horizontal_wrapped(|ui| {
                        ui.label("Wind");
                        for v in &mut self.hair.motion.wind { ui.add(egui::DragValue::new(v).speed(0.1).range(-30.0..=30.0)); }
                    });
                    if ui.button("Use settled shape").clicked() { actions.push(UiAction::Hair(HairAction::Settle)); }
                });
                if ui.button("Convert to ordinary mesh").on_hover_text("Stops guide editing; Undo restores the complete hair state.").clicked() {
                    actions.push(UiAction::Hair(HairAction::Convert));
                }
            });
            if self.hair.job.is_some() {
                ui.horizontal(|ui| { ui.spinner(); ui.label("Generating…"); });
                if ui.button("Cancel generation").clicked() {
                    if let Some(job) = &self.hair.job { job.cancel.store(true, Ordering::Relaxed); }
                    self.hair.generation += 1;
                    self.hair.queued = None;
                }
            }
            if !self.hair.feedback.is_empty() { ui.weak(&self.hair.feedback); }
        });
    }

    pub(super) fn handle_hair_input(&mut self, ui: &egui::Ui, rectangle: egui::Rect) -> bool {
        if self.cdmw_state["replacement"]["comparison"]
            .as_str()
            .is_some_and(|v| v != "edit")
        {
            return false;
        }
        if self.hair.tool.is_none()
            || self
                .hair
                .state
                .as_ref()
                .is_none_or(|s| s.converted || s.bound_reference != s.scalp.identity)
        {
            return false;
        }
        if self.cdmw_orbit_mode
            || ui.input(|i| i.modifiers.alt || i.modifiers.ctrl || i.modifiers.shift)
        {
            return false;
        }
        if ui.input(|i| i.key_pressed(egui::Key::Escape)) {
            self.hair.stroke = None;
            self.hair.playing = self.hair.restart_after_stroke;
            self.hair.last_pointer = None;
            if let Some(scene) = &mut self.hair.scene {
                scene.applied = false;
            }
        }
        let events: Vec<_> = self.pointer_events.drain().collect();
        for event in events {
            match event {
                ViewportPointerEvent::PrimaryPressed(point) if !self.cdmw_busy() => {
                    self.hair.stroke = self.hair.state.clone();
                    self.hair.restart_after_stroke = self.hair.playing;
                    self.hair.playing = false;
                    self.hair.last_plant = None;
                    self.hair.last_pointer = Some(point);
                    self.hair_stroke_point(rectangle, point);
                }
                ViewportPointerEvent::PrimaryMoved(point) => {
                    self.hair_stroke_point(rectangle, point)
                }
                ViewportPointerEvent::PrimaryReleased(point) => {
                    self.hair_stroke_point(rectangle, point);
                    if let Some(mut state) = self.hair.stroke.take()
                        && self.hair.tool != Some(HairTool::Select)
                    {
                        state.revision += 1;
                        self.queue_hair(state, "Groom hair", Preparation::Generate);
                    }
                    self.hair.playing = self.hair.restart_after_stroke;
                    self.hair.last_pointer = None;
                    if let Some(scene) = &mut self.hair.scene {
                        scene.applied = false;
                    }
                }
                ViewportPointerEvent::Orbit(delta) => self.camera.orbit(delta),
                ViewportPointerEvent::Pan(delta) => self.camera.pan(delta, rectangle),
                _ => {}
            }
        }
        if ui.rect_contains_pointer(rectangle) {
            let scroll = ui.input(|i| i.smooth_scroll_delta.y);
            if scroll.abs() > 0.0 {
                self.camera.zoom(scroll);
            }
        }
        true
    }

    fn hair_stroke_point(&mut self, rectangle: egui::Rect, pointer: Vec2) {
        let Some(mut state) = self.hair.stroke.take() else {
            return;
        };
        let Some(tool) = self.hair.tool else {
            return;
        };
        let previous = self.hair.last_pointer.replace(pointer).unwrap_or(pointer);
        let selected: Vec<_> = state
            .guides
            .iter()
            .enumerate()
            .filter_map(|(i, guide)| {
                (guide.group == self.hair.group
                    && guide.points.iter().any(|p| {
                        self.camera
                            .project(Vec3::from(*p), rectangle)
                            .is_some_and(|p| p.screen.distance(pointer) <= self.hair.radius)
                    }))
                .then_some(i)
            })
            .collect();
        let result: Result<(), String> = (|| {
            if matches!(tool, HairTool::Paint | HairTool::Guide | HairTool::Root) {
                let ray = self
                    .camera
                    .screen_ray(pointer, rectangle)
                    .ok_or("Cannot place a root outside the viewport")?;
                let Some(root) = pick_scalp(&state, ray.0, ray.1) else {
                    return Ok(());
                };
                let hit = state.scalp.point(&root).map_err(|e| e.to_string())?;
                if tool == HairTool::Root {
                    let index = self
                        .hair
                        .selected
                        .iter()
                        .copied()
                        .min()
                        .ok_or("Select a guide root to correct")?;
                    let guide = state
                        .guides
                        .get_mut(index)
                        .ok_or("Selected guide no longer exists")?;
                    let shift = hit - Vec3::from(guide.points[0]);
                    guide.root = root;
                    for point in &mut guide.points {
                        *point = (Vec3::from(*point) + shift).to_array();
                    }
                } else if self.hair.last_plant.is_none_or(|p| {
                    tool == HairTool::Paint && p.distance(hit) > self.hair.width * 0.5
                }) {
                    let index = hair::plant_guide(
                        &mut state,
                        root,
                        self.hair.group,
                        self.hair.preset,
                        self.hair.length,
                        16,
                    )
                    .map_err(|e| e.to_string())?;
                    self.hair.selected = HashSet::from([index]);
                    self.hair.last_plant = Some(hit);
                    if self.hair.symmetry {
                        let mirrored = state.scalp.nearest(hit * Vec3::new(-1.0, 1.0, 1.0));
                        if state
                            .scalp
                            .point(&mirrored)
                            .map_err(|e| e.to_string())?
                            .distance(hit)
                            > 0.001
                        {
                            hair::plant_guide(
                                &mut state,
                                mirrored,
                                self.hair.group,
                                self.hair.preset,
                                self.hair.length,
                                16,
                            )
                            .map_err(|e| e.to_string())?;
                        }
                    }
                }
            } else if tool == HairTool::Select {
                self.hair.selected = selected.into_iter().collect();
            } else if !selected.is_empty() {
                let pivot = Vec3::from(state.guides[selected[0]].points[0]);
                let delta = self.camera.plane_drag_delta(
                    self.camera.forward(),
                    pivot,
                    previous,
                    pointer,
                    rectangle,
                );
                if previous != pointer {
                    let groom = match tool {
                        HairTool::Comb => Groom::Comb,
                        HairTool::Smooth => Groom::Smooth,
                        HairTool::Cut => Groom::Cut,
                        HairTool::Lengthen => Groom::Lengthen,
                        HairTool::Curl => Groom::Curl,
                        _ => Groom::Clump,
                    };
                    hair::groom(
                        &mut state,
                        &selected,
                        groom,
                        self.hair.strength * 0.15,
                        delta.to_array(),
                        self.hair.symmetry,
                    )
                    .map_err(|e| e.to_string())?;
                }
            }
            Ok(())
        })();
        if let Err(error) = result {
            self.hair.feedback = error;
        }
        self.hair.stroke = Some(state);
    }

    pub(super) fn paint_hair_guides(&self, ui: &egui::Ui, rectangle: egui::Rect) {
        if self.cdmw_state["replacement"]["comparison"]
            .as_str()
            .is_some_and(|v| v != "edit")
        {
            return;
        }
        if !self.hair.show_guides {
            return;
        }
        let Some(state) = self.hair.stroke.as_ref().or(self.hair.state.as_ref()) else {
            return;
        };
        if state.converted {
            return;
        }
        for (index, guide) in state.guides.iter().enumerate() {
            let color = if self.hair.selected.contains(&index) {
                Color32::YELLOW
            } else {
                Color32::from_rgb(100, 190, 230)
            };
            let points = if self.hair.stroke.is_none() && self.hair.preview.is_none() {
                self.hair
                    .simulation
                    .as_ref()
                    .and_then(|s| s.points.get(index))
                    .unwrap_or(&guide.points)
            } else {
                &guide.points
            };
            for pair in points.windows(2) {
                if let (Some(a), Some(b)) = (
                    self.camera.project(Vec3::from(pair[0]), rectangle),
                    self.camera.project(Vec3::from(pair[1]), rectangle),
                ) {
                    ui.painter().line_segment(
                        [
                            egui::pos2(a.screen.x, a.screen.y),
                            egui::pos2(b.screen.x, b.screen.y),
                        ],
                        egui::Stroke::new(1.0, color),
                    );
                }
            }
            if let Some(root) = self.camera.project(Vec3::from(points[0]), rectangle) {
                ui.painter()
                    .circle_filled(egui::pos2(root.screen.x, root.screen.y), 2.5, color);
            }
        }
    }

    pub(super) fn render_hair(&mut self) {
        if self.cdmw_state["replacement"]["comparison"]
            .as_str()
            .is_some_and(|v| v != "edit")
        {
            return;
        }
        let visible = self.cdmw_visible_submeshes();
        let Some(state) = self.hair.state.as_ref() else {
            return;
        };
        if state.converted {
            return;
        }
        let Some(document) = self.hair.preview.as_ref().or(self.document.as_ref()) else {
            return;
        };
        if self
            .hair
            .scene
            .as_ref()
            .is_none_or(|scene| scene.show_reference != self.hair.show_reference)
        {
            self.hair.scene = Some(build_scene(
                document,
                state,
                self.hair.show_reference,
                visible.as_ref(),
                self.hair.generation,
            ));
        }
        let now = Instant::now();
        let dt = now.duration_since(self.hair.last_tick).as_secs_f64();
        self.hair.last_tick = now;
        if self.hair.playing && !self.cdmw_busy() && self.hair.job.is_none() {
            if self.hair.simulation.is_none() {
                self.hair.simulation = Simulation::new(state).ok();
            }
            if let Some(sim) = &mut self.hair.simulation {
                let angle = (sim.elapsed as f32 * 1.5).sin() * 0.35;
                self.hair.rotation = match self.hair.head_test {
                    1 => Quat::from_rotation_y(angle),
                    2 => Quat::from_rotation_x(angle),
                    _ => Quat::IDENTITY,
                };
                if let Err(error) =
                    sim.advance(dt, self.hair.motion, &state.collisions, self.hair.rotation)
                {
                    self.hair.feedback = error.to_string();
                    self.hair.playing = false;
                }
            }
        }
        let scene = self.hair.scene.as_mut().unwrap();
        if scene.applied && !self.hair.playing && self.hair.stroke.is_none() {
            return;
        }
        let snapshot = &mut scene.frame;
        snapshot.positions.copy_from_slice(&scene.rest.positions);
        snapshot.normals.copy_from_slice(&scene.rest.normals);
        let stroke_points = self.hair.stroke.as_ref().map(|s| {
            s.guides
                .iter()
                .map(|g| g.points.clone())
                .collect::<Vec<_>>()
        });
        let points = stroke_points.as_ref().or_else(|| {
            if self.hair.preview.is_none() {
                self.hair.simulation.as_ref().map(|s| &s.points)
            } else {
                None
            }
        });
        if let Some(points) = points {
            for (part, first, count, indices) in &scene.parts {
                let positions = &mut snapshot.positions[*first..first + count];
                if let Err(error) = hair::deform(&state.bindings, points, *part, positions) {
                    self.hair.feedback = error.to_string();
                }
                normals_into(
                    positions,
                    indices,
                    &mut snapshot.normals[*first..first + count],
                );
            }
        }
        for i in scene.reference_start
            ..(scene.reference_start + state.scalp.positions.len()).min(snapshot.positions.len())
        {
            let pivot = self
                .hair
                .simulation
                .as_ref()
                .map_or(Vec3::ZERO, |s| s.pivot);
            snapshot.positions[i] = (pivot
                + self.hair.rotation * (Vec3::from(scene.rest.positions[i]) - pivot))
                .to_array();
            snapshot.normals[i] =
                (self.hair.rotation * Vec3::from(scene.rest.normals[i])).to_array();
        }
        self.hair.draw_revision += 1;
        snapshot.draw_revision = self.hair.draw_revision;
        if let Some(renderer) = &mut self.renderer
            && let Err(error) = renderer.set_snapshot_with_deformation_interactive(snapshot, None)
        {
            self.hair.feedback = error.to_string();
        }
        scene.applied = true;
    }
}

impl HairEditor {
    pub(super) fn invalidate_scene(&mut self) {
        self.scene = None;
    }
    pub(super) fn preparing(&self) -> bool {
        self.job.is_some() || self.queued.is_some() || self.stroke.is_some()
    }
}

fn build_scene(
    document: &MeshDocument,
    state: &HairState,
    reference: bool,
    visible: Option<&HashSet<u32>>,
    generation: u64,
) -> HairScene {
    let mut snapshot = DrawSnapshot {
        mesh_identity: u64::MAX - 1,
        draw_revision: 0,
        topology_generation: generation,
        positions: vec![],
        normals: vec![],
        uvs: vec![],
        indices: vec![],
        triangle_materials: vec![],
        selected_vertices: vec![],
        fingerprint: format!("hair-{generation}"),
    };
    let generated = state.groups.iter().all(|g| g.mode == GroupMode::Generated);
    let mut parts = vec![];
    for (index, part) in document.lods[0].submeshes.iter().enumerate() {
        if visible.is_some_and(|v| !v.contains(&(index as u32))) {
            continue;
        }
        if generated
            && !state.groups.iter().any(|g| {
                g.part == index as u32 && state.guides.iter().any(|guide| guide.group == g.id)
            })
        {
            continue;
        }
        let first = snapshot.positions.len();
        snapshot.positions.extend_from_slice(&part.positions);
        let mut part_normals = part.normals.clone();
        if part_normals.len() != part.positions.len() {
            normals(&part.positions, &part.indices, &mut part_normals);
        }
        snapshot.normals.extend(part_normals);
        snapshot.uvs.extend(
            part.uvs
                .iter()
                .copied()
                .chain(std::iter::repeat([0.0; 2]))
                .take(part.positions.len()),
        );
        snapshot
            .indices
            .extend(part.indices.iter().map(|i| i + first as u32));
        snapshot
            .triangle_materials
            .extend(std::iter::repeat_n(index as u32, part.indices.len() / 3));
        parts.push((
            index as u32,
            first,
            part.positions.len(),
            part.indices.clone(),
        ));
    }
    let reference_start = snapshot.positions.len();
    if reference {
        for mesh in std::iter::once(&state.scalp).chain(&state.references) {
            let first = snapshot.positions.len() as u32;
            let indices: Vec<_> = mesh.triangles.iter().flatten().copied().collect();
            let mut reference_normals = vec![];
            normals(&mesh.positions, &indices, &mut reference_normals);
            snapshot.positions.extend_from_slice(&mesh.positions);
            snapshot.normals.extend(reference_normals);
            snapshot
                .uvs
                .extend(std::iter::repeat_n([0.0; 2], mesh.positions.len()));
            snapshot.indices.extend(indices.iter().map(|i| i + first));
            snapshot.triangle_materials.extend(std::iter::repeat_n(
                document.lods[0].submeshes.len() as u32,
                indices.len() / 3,
            ));
        }
    }
    HairScene {
        rest: snapshot.clone(),
        frame: snapshot,
        parts,
        reference_start,
        show_reference: reference,
        applied: false,
    }
}

fn hair_bounds(state: &HairState) -> (Vec3, Vec3) {
    state.scalp.positions.iter().fold(
        (Vec3::splat(f32::INFINITY), Vec3::splat(f32::NEG_INFINITY)),
        |(min, max), p| (min.min(Vec3::from(*p)), max.max(Vec3::from(*p))),
    )
}

fn pick_scalp(state: &HairState, origin: Vec3, direction: Vec3) -> Option<Attachment> {
    let mut nearest = f32::INFINITY;
    let mut result = None;
    for (i, face) in state.scalp.triangles.iter().enumerate() {
        let [a, b, c] = face.map(|i| Vec3::from(state.scalp.positions[i as usize]));
        let e1 = b - a;
        let e2 = c - a;
        let p = direction.cross(e2);
        let det = e1.dot(p);
        if det.abs() < 1e-8 {
            continue;
        }
        let t = origin - a;
        let u = t.dot(p) / det;
        let q = t.cross(e1);
        let v = direction.dot(q) / det;
        let distance = e2.dot(q) / det;
        if u >= 0.0 && v >= 0.0 && u + v <= 1.0 && distance >= 0.0 && distance < nearest {
            nearest = distance;
            result = Some(Attachment {
                triangle: i as u32,
                barycentric: [1.0 - u - v, u, v],
            });
        }
    }
    result
}
