//! Hair controls and background generation in the existing authoring viewport.
use super::*;
use cdmw_mesh::hair::locks::{self, LockKind};
use cdmw_mesh::hair::{
    self, Attachment, Groom, GroupMode, HairState, MotionSettings, Preset, Simulation,
};
use std::collections::{BTreeSet, VecDeque};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{Receiver, TryRecvError};
use std::thread;

#[cfg(test)]
use cdmw_mesh::hair::HairGroup;

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
    Move,
    Erase,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DrawShape { Freehand, Straight, Arc, Circle }

struct PreparedHair {
    state: HairState,
    document: MeshDocument,
    label: String,
    milliseconds: f64,
}
#[derive(Clone)]
enum Preparation {
    Analyze,
    Deform,
    Delete(Vec<u64>),
    Cut(u64, u32, f32, bool),
    Empty,
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
    head_reference_ranges: Vec<std::ops::Range<usize>>,
    show_reference: bool,
    applied: bool,
    picking: hair::surface::SurfaceIndex,
    vertex_locks: Vec<Option<u64>>,
    vertex_along: Vec<f32>,
    picking_indices: Vec<u32>,
    scalp_indices: Vec<u32>,
    scalp_picking: hair::surface::SurfaceIndex,
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
    queued: VecDeque<(HairState, MeshDocument, String, Preparation)>,
    publications: VecDeque<PreparedHair>,
    inflight: Option<PreparedHair>,
    acknowledged: Option<(HairState, MeshDocument)>,
    topology_busy: bool,
    pub hover: Option<u64>,
    stroke_changed: bool,
    stroke_primary: Option<u64>,
    stroke_distances: HashMap<usize, f32>,
    pub select_through: bool,
    stroke_start: Option<Vec2>,
    drawing: Vec<u64>,
    pub style_name: String,
    pub pending_preset: bool,
    pub requested_preset: Option<String>,
    pub pending_finish: bool,
    pending_history: VecDeque<bool>,
    cut_preview: Option<(u64, u32, f32)>,
    motion_validated_revision: Option<u64>,
    readiness_cache: Option<(u64, bool, Option<String>)>,
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
    pub show_collisions: bool,
    last_pointer: Option<Vec2>,
    drawing_samples: Vec<[f32; 3]>,
    draw_shape: DrawShape,
    draw_follow_scalp: bool,
    draw_smoothing: f32,
    arc_bend: f32,
    move_reach: f32,
    move_anchor: Option<(f32, Vec3)>,
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
            queued: VecDeque::new(),
            publications: VecDeque::new(),
            inflight: None,
            acknowledged: None,
            topology_busy: false,
            hover: None,
            stroke_changed: false,
            stroke_primary: None,
            stroke_distances: HashMap::new(),
            select_through: false,
            stroke_start: None,
            drawing: vec![],
            style_name: "My hairstyle".into(),
            pending_preset: false,
            requested_preset: None,
            pending_finish: false,
            cut_preview: None,
            motion_validated_revision: None,
            readiness_cache: None,
            pending_history: VecDeque::new(),
            generation: 0,
            playing: false,
            restart_after_stroke: false,
            simulation: None,
            motion: MotionSettings::default(),
            head_test: 3,
            rotation: Quat::IDENTITY,
            last_tick: Instant::now(),
            preview: None,
            group: 0,
            preset: Preset::Bob,
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
            show_guides: false,
            show_collisions: false,
            last_pointer: None,
            drawing_samples: vec![],
            draw_shape: DrawShape::Freehand,
            draw_follow_scalp: true,
            draw_smoothing: 0.6,
            arc_bend: 0.5,
            move_reach: 0.5,
            move_anchor: None,
            feedback: String::new(),
            draw_revision: 0,
            scene: None,
        }
    }
}

#[derive(Debug, Clone)]
pub(super) enum HairAction {
    Prepare,
    Empty,
    Rigid,
    Rebind,
    Convert,
    DeleteGuides,
    Settings,
    Settle,
    Reset,
    Fill,
    Registration,
}

#[path = "cdmw_hair_geometry.rs"]
mod geometry;
use geometry::prepare;
#[path = "cdmw_hair_input.rs"]
mod input;
#[path = "cdmw_hair_motion.rs"]
mod motion;

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
    pub(super) fn hydrate_hair(&mut self, mut state: Option<HairState>) {
        if let Some(hair) = state.as_mut().filter(|s| {
            s.locks.is_empty()
                && !s.bindings.is_empty()
                && s.groups.iter().all(|g| g.mode == GroupMode::Generated)
        }) {
            // Legacy generated geometry already has explicit vertex/guide
            // provenance. Recover ownership without regenerating the draft.
            locks::synchronize_generated(hair);
            hair.prepared_parts = hair.groups.iter().map(|g| g.part).collect();
            if let Some(document) = &self.document {
                let frames: Vec<_> = hair
                    .guides
                    .iter()
                    .map(|g| locks::frames(&g.points))
                    .collect();
                for binding in &mut hair.bindings {
                    if Vec3::from(binding.normal).length_squared() > 0.1 {
                        continue;
                    }
                    if let (Some(normal), Some(&(x, y, z))) = (
                        document
                            .lods
                            .first()
                            .and_then(|l| l.submeshes.get(binding.part as usize))
                            .and_then(|p| p.normals.get(binding.vertex as usize)),
                        frames
                            .get(binding.guide as usize)
                            .and_then(|f| f.get(binding.segment as usize)),
                    ) {
                        let normal = Vec3::from(*normal);
                        binding.normal = [normal.dot(x), normal.dot(y), normal.dot(z)];
                    }
                }
            }
        }
        let changed = self.hair.state.as_ref() != state.as_ref();
        if !changed {
            // Selection/material notifications can repeat the acknowledged hair
            // state without a new mesh document. Keep its generated geometry;
            // the generic document can still contain the original PAC donor.
            return;
        }
        let first = self.hair.state.is_none();
        self.hair.generation += 1;
        if let Some(job) = &self.hair.job {
            job.cancel.store(true, Ordering::Relaxed);
        }
        self.hair.queued.clear();
        self.hair.publications.clear();
        self.hair.stroke = None;
        self.hair.preview = None;
        self.hair.scene = None;
        self.hair.readiness_cache = None;
        self.hair.motion_validated_revision = None;
        self.hair.simulation = state.as_ref().and_then(|s| Simulation::new(s).ok());
        self.hair.last_tick = Instant::now();
        self.hair.rotation = Quat::IDENTITY;
        if let Some(hair) = &state {
            if let Some(doc) = &mut self.document {
                for (part, indices) in &hair.vertex_sources {
                    if let Some(part) = doc.lods[0].submeshes.get_mut(*part as usize) {
                        part.source_vertex_indices = indices.clone();
                    }
                }
            }
            self.hair.target_stem = hair.template.target_stem.clone();
            self.hair.style_name = hair.style_name.clone();
            self.hair
                .selected
                .retain(|id| hair.locks.iter().any(|l| l.id == *id as u64));
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
                self.camera
                    .set_standard_view(crate::camera::StandardView::Front);
                self.hair.length = (maximum - minimum).max_element() * 0.9;
                if let Some(rect) = self.viewport_rect {
                    let points =
                        hair.scalp
                            .positions
                            .iter()
                            .chain(hair.references.iter().flat_map(|r| r.positions.iter()))
                            .chain(self.document.iter().flat_map(|d| {
                                d.lods.iter().take(1).flat_map(|l| {
                                    l.submeshes.iter().flat_map(|p| p.positions.iter())
                                })
                            }))
                            .copied()
                            .map(Vec3::from);
                    self.camera.frame_positions_in_viewport(points, rect);
                }
                self.hair.tool = Some(HairTool::Select);
                self.view_mode = ViewMode::TexturedSolid;
                self.hair.pending_preset =
                    hair.revision == 0 && hair.guides.is_empty() && hair.locks.is_empty();
                self.hair.preset = match hair.startup_preset.as_str() {
                    "cropped" => Preset::Cropped,
                    "long" => Preset::Long,
                    "ponytail" => Preset::Ponytail,
                    _ => Preset::Bob,
                };
                self.hair.length = (maximum - minimum).max_element()
                    * match self.hair.preset {
                        Preset::Cropped => 0.18,
                        Preset::Bob => 0.7,
                        Preset::Long => 1.4,
                        Preset::Ponytail => 1.6,
                    };
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
        self.hair.acknowledged = state.clone().zip(self.document.clone());
        self.hair.inflight = None;
        self.hair.topology_busy = false;
        self.hair.pending_finish = false;
        self.hair.state = state;
    }

    fn queue_hair(&mut self, state: HairState, label: &str, operation: Preparation) {
        let Some(document) = self.hair.preview.as_ref().or(self.document.as_ref()) else {
            return;
        };
        if self.hair.queued.len() + self.hair.publications.len() >= 8 {
            self.hair.feedback =
                "Saving previous edits. Please wait for the pending actions.".into();
            return;
        }
        self.hair.topology_busy |=
            !matches!(operation, Preparation::Deform | Preparation::Metadata);
        self.hair.state = Some(state.clone());
        self.hair
            .queued
            .push_back((state, document.clone(), label.to_owned(), operation));
        self.start_hair_job();
    }

    fn start_hair_job(&mut self) {
        if self.hair.job.is_some() {
            return;
        }
        let Some((state, document, label, operation)) = self.hair.queued.pop_front() else {
            return;
        };
        self.hair.topology_busy = !matches!(operation, Preparation::Deform | Preparation::Metadata);
        let (sender, receiver) = std::sync::mpsc::sync_channel(1);
        let cancel = Arc::new(AtomicBool::new(false));
        let stop = cancel.clone();
        let revision = self.hair.generation;
        let handle = thread::spawn(move || {
            let _ = sender.send(prepare(state, document, label, operation, &stop));
        });
        self.hair.job = Some(HairJob {
            revision,
            cancel,
            receiver,
            handle,
        });
    }

    pub(super) fn accept_hair_ack(&mut self, revision: u64) -> Result<()> {
        let pending = self
            .hair
            .inflight
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("Unexpected hair acknowledgement"))?;
        if pending.state.revision != revision {
            anyhow::bail!("Stale hair acknowledgement");
        }
        let pending = self.hair.inflight.take().unwrap();
        self.hair.acknowledged = Some((pending.state, pending.document));
        Ok(())
    }

    pub(super) fn hair_input_ready(&self) -> bool {
        self.hair.pending_history.is_empty()
            && !self.hair.topology_busy
            && self.hair.queued.len() + self.hair.publications.len() < 8
            && (!self.cdmw_busy() || self.hair.inflight.is_some())
    }

    pub(super) fn defer_hair_history(&mut self, redo: bool) -> bool {
        if !self.hair.active() || (!self.hair.preparing() && !self.cdmw_busy()) {
            return false;
        }
        if self.hair.pending_history.len() < 8 {
            self.hair.pending_history.push_back(redo);
            self.hair.feedback =
                "History will update after the completed strokes are saved.".into();
        }
        // A shortcut during a stroke cancels that uncommitted gesture first.
        self.hair.stroke = None;
        self.hair.stroke_start = None;
        self.hair.drawing.clear();
        self.hair.scene = None;
        self.hair.playing = false;
        self.hair.restart_after_stroke = false;
        true
    }

    pub(super) fn poll_hair(&mut self) {
        if self.hair_input_ready() && !self.hair.preparing() && !self.cdmw_busy() {
            if let Some(preset) = self.hair.requested_preset.take() {
                if let Some(state) = self.hair.state.as_ref().filter(|s| {
                    !s.converted && s.groups.iter().all(|g| g.mode == GroupMode::Generated)
                }) {
                    self.hair.preset = match preset.as_str() {
                        "cropped" => Preset::Cropped,
                        "long" => Preset::Long,
                        "ponytail" => Preset::Ponytail,
                        _ => Preset::Bob,
                    };
                    let (minimum, maximum) = hair_bounds(state);
                    self.hair.length = (maximum - minimum).max_element()
                        * match self.hair.preset {
                            Preset::Cropped => 0.18,
                            Preset::Bob => 0.7,
                            Preset::Long => 1.4,
                            Preset::Ponytail => 1.6,
                        };
                    self.run_hair_action(if preset == "empty" {
                        HairAction::Empty
                    } else {
                        HairAction::Fill
                    });
                } else {
                    self.hair.feedback =
                        "Start a generated hairstyle before applying a preset.".into();
                }
            }
        }
        if !self.cdmw_busy() {
            if let Some(mode) = self.hair.pending_start.take() {
                self.submit_cdmw_command("hair_begin", json!({"mode": mode}), "Loading character");
                return;
            }
            if self.hair.pending_preset && self.hair.state.is_some() {
                self.hair.pending_preset = false;
                let existing = self
                    .hair
                    .state
                    .as_ref()
                    .unwrap()
                    .groups
                    .iter()
                    .any(|g| g.mode == GroupMode::Existing);
                self.run_hair_action(if existing {
                    HairAction::Prepare
                } else if self.hair.state.as_ref().unwrap().startup_preset == "empty" {
                    HairAction::Empty
                } else {
                    HairAction::Fill
                });
            }
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
                    Err("Hair preparation stopped before completing".into()),
                )),
                Err(TryRecvError::Empty) => None,
            });
        if let Some((generation, result)) = completion {
            self.hair.job.take();
            if generation == self.hair.generation {
                match result {
                    Ok(prepared) => {
                        self.hair.feedback =
                            format!("Ready · prepared in {:.1} ms", prepared.milliseconds);
                        if self
                            .hair
                            .state
                            .as_ref()
                            .is_none_or(|s| s.revision <= prepared.state.revision)
                        {
                            self.hair.state = Some(prepared.state.clone());
                            let elapsed = self.hair.simulation.as_ref().map_or(0.0, |s| s.elapsed);
                            let (min, max) = hair_bounds(&prepared.state);
                            self.hair.simulation = Simulation::at_pose(
                                &prepared.state,
                                elapsed,
                                self.hair.head_test,
                                (max.y - min.y).max(0.01),
                            )
                            .ok();
                        }
                        if self.hair.restart_after_stroke && self.hair.queued.is_empty() {
                            self.hair.playing = true;
                            self.hair.restart_after_stroke = false;
                        }
                        self.hair.preview = Some(prepared.document.clone());
                        self.hair.scene = None;
                        self.hair.publications.push_back(prepared);
                    }
                    Err(error) => {
                        self.hair.feedback = error;
                        self.hair.playing = false;
                        self.hair.pending_finish = false;
                        self.hair.queued.clear();
                        self.hair.publications.clear();
                        self.hair.pending_history.clear();
                        if let Some(pending) = &self.hair.inflight {
                            self.hair.acknowledged =
                                Some((pending.state.clone(), pending.document.clone()));
                        }
                        if let Some((state, document)) = &self.hair.acknowledged {
                            self.hair.state = Some(state.clone());
                            self.hair.preview = Some(document.clone());
                            self.hair.scene = None;
                        }
                    }
                }
            }
            self.hair.topology_busy = false;
            self.start_hair_job();
        }
        if !self.cdmw_busy() && self.hair.inflight.is_none() {
            if let Some(prepared) = self.hair.publications.pop_front() {
                let baseline = self
                    .hair
                    .acknowledged
                    .as_ref()
                    .map(|(_, doc)| doc)
                    .or(self.document.as_ref());
                if let (Some(bridge), Some(before)) = (self.cdmw_bridge.as_mut(), baseline) {
                    match if prepared.state.converted {
                        bridge.submit_hair_transaction(
                            &prepared.document,
                            &prepared.state,
                            &prepared.label,
                        )
                    } else {
                        bridge.submit_hair_update(
                            &prepared.document,
                            &prepared.state,
                            before,
                            self.hair.acknowledged.as_ref().map(|(s, _)| s),
                            &prepared.label,
                        )
                    } {
                        Ok(request_id) => {
                            self.cdmw_pending_request = Some(CdmwPendingRequest {
                                request_id,
                                event: "transaction_result",
                                label: prepared.label.clone(),
                                origin: None,
                            });
                            self.hair.inflight = Some(prepared);
                        }
                        Err(error) => {
                            self.hair.feedback =
                                format!("{} could not be saved: {error}", prepared.label);
                            self.hair.generation += 1;
                            if let Some(job) = &self.hair.job {
                                job.cancel.store(true, Ordering::Relaxed);
                            }
                            self.hair.queued.clear();
                            self.hair.publications.clear();
                            self.hair.pending_history.clear();
                            self.hair.pending_finish = false;
                            self.hair.playing = false;
                            self.hair.restart_after_stroke = false;
                            if let Some((state, document)) = &self.hair.acknowledged {
                                self.hair.state = Some(state.clone());
                                self.hair.preview = Some(document.clone());
                                self.hair.scene = None;
                            }
                        }
                    }
                }
            }
        }
        if !self.cdmw_busy()
            && self.hair.job.is_none()
            && self.hair.queued.is_empty()
            && self.hair.publications.is_empty()
            && self.hair.inflight.is_none()
        {
            if let Some(redo) = self.hair.pending_history.pop_front() {
                self.submit_cdmw_command(
                    if redo { "redo" } else { "undo" },
                    json!({}),
                    if redo { "Redo" } else { "Undo" },
                );
            }
        }
        if self.hair.pending_finish && !self.cdmw_busy() && !self.hair.preparing() {
            self.hair.pending_finish = false;
            self.submit_cdmw_finish();
        }
        if self.hair.job.is_some() || self.hair.playing || !self.hair.publications.is_empty() {
            self.egui_context.request_repaint();
        }
    }

    pub(super) fn run_hair_action(&mut self, action: HairAction) {
        if !self.hair_input_ready() && !matches!(action, HairAction::Reset) {
            self.hair.feedback = "Wait for the current hair edit to finish, then try again.".into();
            return;
        }
        let Some(mut state) = self.hair.state.clone() else {
            return;
        };
        let mut selected: Vec<u64> = self.hair.selected.iter().map(|i| *i as u64).collect();
        if self.hair.symmetry {
            let pairs: Vec<_> = state
                .locks
                .iter()
                .filter(|l| selected.contains(&l.id))
                .filter_map(|l| l.mirrored)
                .collect();
            selected.extend(pairs);
            selected.sort_unstable();
            selected.dedup();
        }
        let mut operation = Preparation::Deform;
        let result: Result<&str, String> = (|| {
            match action {
                HairAction::Reset => {
                    self.hair.simulation =
                        Some(Simulation::new(&state).map_err(|e| e.to_string())?);
                    self.hair.rotation = Quat::IDENTITY;
                    self.hair.playing = false;
                    self.hair.last_tick = Instant::now();
                    self.hair.scene = None;
                    return Ok("");
                }
                HairAction::Settle => {
                    self.hair_motion_reason()?;
                    state = self
                        .hair
                        .simulation
                        .as_ref()
                        .filter(|simulation| simulation.elapsed > 0.0)
                        .ok_or("Play motion first")?
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
                HairAction::Rebind => operation = Preparation::Rebind,
                HairAction::Prepare => operation = Preparation::Analyze,
                HairAction::Empty => operation = Preparation::Empty,
                HairAction::Fill => {
                    operation =
                        Preparation::Fill(self.hair.group, self.hair.preset, self.hair.length)
                }
                HairAction::Registration => {
                    state.style_name = self.hair.style_name.trim().to_owned();
                    operation = Preparation::Metadata;
                }
                HairAction::DeleteGuides => {
                    if selected.is_empty() {
                        return Err("Select hair locks before deleting them".into());
                    }
                    operation = Preparation::Delete(selected.clone());
                    self.hair.selected.clear();
                }
                HairAction::Rigid => {
                    if selected.is_empty() {
                        return Err("Select the scalp sections to attach rigidly".into());
                    }
                    let mut removed = BTreeSet::new();
                    for lock in state.locks.iter_mut().filter(|l| selected.contains(&l.id)) {
                        if let Some(g) = lock.guide.take() {
                            removed.insert(g as usize);
                        }
                        lock.kind = LockKind::Rigid;
                    }
                    locks::remove_guides(&mut state, &removed);
                    operation = Preparation::Metadata;
                }
                HairAction::Settings => {
                    if selected.is_empty() {
                        return Err("Select hair locks before changing thickness or density".into());
                    }
                    let mut regenerate = false;
                    for lock in state.locks.iter_mut().filter(|l| selected.contains(&l.id)) {
                        if !matches!(lock.kind, LockKind::Generated | LockKind::Bound) {
                            return Err(
                                "Correct the selected sections before changing their width".into(),
                            );
                        }
                        let group = state.groups.iter().find(|g| g.part == lock.part).unwrap();
                        let width = (self.hair.width / group.width).clamp(0.02, 20.0);
                        if lock.kind == LockKind::Bound {
                            let scale = width / lock.width_scale;
                            for binding in state
                                .bindings
                                .iter_mut()
                                .filter(|b| b.part == lock.part && Some(b.guide) == lock.guide)
                            {
                                binding.offset[0] *= scale;
                                binding.offset[1] *= scale;
                            }
                        } else {
                            lock.cards = self.hair.density;
                            regenerate = true;
                        }
                        lock.width_scale = width;
                    }
                    operation = if regenerate {
                        Preparation::Generate
                    } else {
                        Preparation::Deform
                    };
                }
            }
            state.revision += 1;
            Ok(match action {
                HairAction::Convert => "Convert hair to ordinary mesh",
                HairAction::Settle => "Use settled hair shape",
                HairAction::Rebind => "Rebind hair roots",
                HairAction::DeleteGuides => "Delete hair",
                HairAction::Settings => "Change selected hair thickness and density",
                HairAction::Fill => "Apply hairstyle preset",
                HairAction::Empty => "Clear generated hairstyle",
                HairAction::Prepare => "Prepare existing hair",
                HairAction::Rigid => "Attach scalp section rigidly",
                HairAction::Registration => "Name hairstyle",
                _ => "Prepare hair",
            })
        })();
        match result {
            Ok("") => {}
            Ok(label) => self.queue_hair(state, label, operation),
            Err(error) => self.hair.feedback = error,
        }
    }

    fn hair_motion_reason(&mut self) -> Result<(), String> {
        let revision = self.hair.state.as_ref().ok_or("Open Hair first")?.revision;
        let materials = self.cdmw_state["hair"]["materials_ready"].as_bool() == Some(true);
        if self.hair.topology_busy {
            return Err("Preparing hair sections".into());
        }
        if let Some((r, m, reason)) = &self.hair.readiness_cache {
            if *r == revision && *m == materials {
                return reason.clone().map_or(Ok(()), Err);
            }
        }
        let state = self.hair.state.as_ref().ok_or("Open Hair first")?;
        let doc = self
            .hair
            .preview
            .as_ref()
            .or(self.document.as_ref())
            .ok_or("Loading hair")?;
        if self.hair.topology_busy {
            return Err("Preparing hair sections".into());
        }
        if self.cdmw_state["hair"]["materials_ready"].as_bool() != Some(true) {
            return Err("Required hair textures are missing. Reload the hairstyle with its material dependencies.".into());
        }
        let parts: Vec<_> = doc.lods[0]
            .submeshes
            .iter()
            .enumerate()
            .filter(|(i, _)| {
                state.groups.iter().any(|g| g.part == *i as u32)
                    && (!state.prepared_parts.contains(&(*i as u32))
                        || state.locks.iter().any(|l| l.part == *i as u32))
            })
            .map(|(i, p)| (i as u32, p.positions.len()))
            .collect();
        let result = locks::readiness(state, &parts)
            .map_err(|e| e.to_string())
            .and_then(|()| {
                // A guide cannot safely rotate an entire scalp-sized section.
                // Keep these explicit bindings usable for static editing, but
                // require smaller root groups before simulating their offsets.
                let (min, max) = hair_bounds(state);
                let max_radius = (max - min).max_element() * 0.15;
                let existing: BTreeSet<_> = state
                    .locks
                    .iter()
                    .filter(|lock| lock.kind == LockKind::Bound)
                    .filter_map(|lock| lock.guide.map(|guide| (lock.part, guide)))
                    .collect();
                if state.bindings.iter().any(|binding| {
                    existing.contains(&(binding.part, binding.guide))
                        && binding.offset[0].hypot(binding.offset[1]) > max_radius
                }) {
                    Err("Existing hair sections are too wide for stable motion. Assign roots to smaller selections, or mark scalp sections rigid.".into())
                } else {
                    Ok(())
                }
            });
        self.hair.readiness_cache = Some((revision, materials, result.as_ref().err().cloned()));
        result
    }

    pub(super) fn draw_hair_parts(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let Some(state) = self.hair.state.as_ref() else {
            return;
        };
        ui.weak("Material sections · visibility does not change output");
        for group in &state.groups {
            let ids: Vec<_> = state
                .locks
                .iter()
                .filter(|l| l.part == group.part)
                .map(|l| l.id as usize)
                .collect();
            if ids.is_empty() {
                continue;
            }
            ui.horizontal(|ui| {
                let mut shown = !self.cdmw_hidden_parts.contains(&group.part);
                if ui
                    .checkbox(&mut shown, "")
                    .on_hover_text("Show section in viewport")
                    .changed()
                {
                    actions.push(UiAction::SetPartVisibility {
                        indices: vec![group.part],
                        visible: shown,
                    });
                    self.hair.scene = None;
                }
                let selected = ids.iter().all(|id| self.hair.selected.contains(id));
                if ui
                    .add_enabled(
                        shown,
                        egui::Button::new(format!("{} · {} locks", group.name, ids.len()))
                            .selected(selected),
                    )
                    .clicked()
                {
                    self.hair.selected = ids.iter().copied().collect();
                    self.hair.tool = Some(HairTool::Select);
                }
            });
        }
    }

    pub(super) fn draw_hair_controls(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let available = self.cdmw_state["hair"]["available"]
            .as_bool()
            .unwrap_or(false);
        if !available && self.hair.state.is_none() {
            return;
        }
        ui.heading("Hair Tools (Experimental)");
        ui.label("Not tested in game. Hairstyles may not work correctly.");
        if self.hair.state.is_none() {
            ui.label("Use Hair Tools above the editor to choose a character and create or edit a hairstyle.");
            return;
        }
        if self.hair.state.as_ref().is_some_and(|s| s.converted) {
            ui.weak("Converted to ordinary mesh. Undo restores Hair editing.");
            return;
        }
        let ready = self.hair_input_ready();
        let state = self.hair.state.as_ref().unwrap();
        let generated = state.groups.iter().all(|g| g.mode == GroupMode::Generated);
        let unresolved = state
            .locks
            .iter()
            .filter(|l| l.kind == LockKind::Unresolved)
            .count();
        let (min, max) = hair_bounds(state);
        let span = (max - min).max_element();
        ui.label(format!(
            "{} · {} locks selected",
            self.hair.style_name,
            self.hair.selected.len()
        ));
        ui.add_enabled_ui(ready,|ui| {
            ui.horizontal_wrapped(|ui| {
                for (tool,name) in [(HairTool::Select,"Select"),(HairTool::Move,"Move"),(HairTool::Guide,"Draw"),
                    (HairTool::Erase,"Erase"),(HairTool::Cut,"Cut"),(HairTool::Lengthen,"Lengthen"),
                    (HairTool::Comb,"Comb"),(HairTool::Smooth,"Smooth"),(HairTool::Curl,"Curl"),(HairTool::Clump,"Clump")] {
                    let enabled=generated || tool!=HairTool::Guide;
                    if ui.add_enabled(enabled,egui::Button::new(name).selected(self.hair.tool==Some(tool)))
                        .on_disabled_hover_text("Draw creates new cards in Create hairstyle. Existing hair preserves its original cards and UV layout.").clicked(){self.hair.tool=Some(tool);self.cdmw_orbit_mode=false;}
                }
            });
            ui.separator();
            let help=match self.hair.tool {
                Some(HairTool::Select)=>"Click visible hair. Ctrl-click adds or removes locks. Drag empty space for a marquee.",
                Some(HairTool::Move)=>"Drag the part of a lock you want to shape. Move reach controls how much nearby hair follows. The root stays attached.",
                Some(HairTool::Guide)=>"Start on the scalp, then drag to shape the lock. Escape cancels.",
                Some(HairTool::Erase)=>"Click or brush across visible locks to remove their geometry.",
                Some(HairTool::Cut)=>"Point at a lock and click to remove hair beyond the cut marker.",
                Some(HairTool::Lengthen)=>"Click a hair lock and drag to extend its tip. An existing selection stays selected.",
                Some(HairTool::Root)=>"Click the scalp to attach the selected sections as one lock. Select sections sharing a material.",
                _=>"Drag over highlighted hair. Only selected or brushed locks change."
            };ui.label(help);
            if self.hair.tool == Some(HairTool::Guide) {
                ui.horizontal_wrapped(|ui| {
                    for (shape, label) in [(DrawShape::Freehand,"Freehand"), (DrawShape::Straight,"Straight"),
                        (DrawShape::Arc,"Arc"), (DrawShape::Circle,"Circle")] {
                        if ui.selectable_value(&mut self.hair.draw_shape, shape, label).changed() {
                            self.hair.draw_follow_scalp = shape == DrawShape::Freehand;
                        }
                    }
                });
                ui.checkbox(&mut self.hair.draw_follow_scalp, "Follow scalp");
                ui.weak("Scalp collision stays active. Hold Ctrl to temporarily draw in the view plane.");
                match self.hair.draw_shape {
                    DrawShape::Freehand => { ui.add(egui::Slider::new(&mut self.hair.draw_smoothing, 0.0..=1.0).text("Stroke smoothing")); }
                    DrawShape::Arc => {
                        ui.label("Drag from the scalp to set the endpoints. Bend controls the curve and its direction.");
                        ui.add(egui::Slider::new(&mut self.hair.arc_bend, -1.5..=1.5).text("Bend"));
                    }
                    DrawShape::Circle => { ui.label("Drag from the scalp to set the circle diameter. Hold Ctrl to draw in the view plane."); }
                    DrawShape::Straight => { ui.label("Drag from the scalp to the tip. Enable Follow scalp to fit the line to the head."); }
                }
            }
            if self.hair.tool == Some(HairTool::Move) {
                ui.add(egui::Slider::new(&mut self.hair.move_reach, 0.05..=1.0).text("Move reach"));
            }
            if !matches!(self.hair.tool,Some(HairTool::Select|HairTool::Move|HairTool::Cut|HairTool::Guide|HairTool::Root)) {
                ui.add(egui::Slider::new(&mut self.hair.radius,5.0..=160.0).text("Brush size"));
                ui.add(egui::Slider::new(&mut self.hair.strength,0.01..=1.0).text("Strength"));
            }
            ui.checkbox(&mut self.hair.symmetry,"Symmetry");
            if self.hair.tool==Some(HairTool::Select) {ui.checkbox(&mut self.hair.select_through,"Select through");}
            if ui.add_enabled(!self.hair.selected.is_empty(),egui::Button::new("Delete selected hair")).clicked() {actions.push(UiAction::Hair(HairAction::DeleteGuides));}
            if unresolved>0 {
                ui.weak(format!("{unresolved} original sections have no grooming guides"));
                ui.weak("Unchanged sections can be exported with their original game skinning. Prepare them only for grooming or motion preview.");
                egui::CollapsingHeader::new("Prepare sections for grooming").show(ui, |ui| {
                let groups:Vec<_>=self.hair.state.as_ref().unwrap().groups.iter().filter_map(|g|{
                    let ids:Vec<_>=self.hair.state.as_ref().unwrap().locks.iter().filter(|l|l.part==g.part&&l.kind==LockKind::Unresolved).map(|l|l.id as usize).collect();
                    if ids.is_empty(){None}else{Some((g.name.clone(),ids))}
                }).collect();
                egui::ComboBox::from_id_salt("hair_unprepared_sections").selected_text("Select sections to prepare").show_ui(ui,|ui|{
                    for (name,ids) in &groups {
                        let label=if name.to_lowercase().contains("front"){"Front"}else if name.to_lowercase().contains("tail"){"Lengths"}else if name.to_lowercase().contains("top"){"Crown"}else{name};
                        if ui.button(format!("{label} · {} sections",ids.len())).clicked(){self.hair.selected=ids.iter().copied().collect();self.hair.tool=Some(HairTool::Select);}
                    }
                });
                if ui.button("Set root / group selected sections").clicked(){self.hair.tool=Some(HairTool::Root);}
                if ui.button("Mark selected scalp sections as rigid").clicked(){actions.push(UiAction::Hair(HairAction::Rigid));}
                });
            }
            egui::CollapsingHeader::new("Setup").show(ui,|ui| {
                ui.label("Hairstyle name");ui.text_edit_singleline(&mut self.hair.style_name);
                if ui.button("Apply name").clicked(){actions.push(UiAction::Hair(HairAction::Registration));}
                if generated {
                    egui::ComboBox::from_label("Preset").selected_text(format!("{:?}",self.hair.preset)).show_ui(ui,|ui| {
                        for preset in [Preset::Cropped,Preset::Bob,Preset::Long,Preset::Ponytail] {
                            if ui.selectable_value(&mut self.hair.preset,preset,format!("{preset:?}")).changed(){
                                self.hair.length=span*match preset {Preset::Cropped=>0.18,Preset::Bob=>0.7,Preset::Long=>1.4,Preset::Ponytail=>1.6};
                            }
                        }
                    });
                    ui.add(egui::Slider::new(&mut self.hair.length,span*0.02..=span*3.0).text("Preset length"));
                    if ui.button("Apply preset (replace current hair)").clicked(){actions.push(UiAction::Hair(HairAction::Fill));}
                    if ui.button("Start empty").clicked(){actions.push(UiAction::Hair(HairAction::Empty));}
                } else if ui.button("Prepare existing hair sections").clicked(){actions.push(UiAction::Hair(HairAction::Prepare));}
                if ui.button("Change references…").clicked(){actions.push(UiAction::CdmwCommand{command:"hair_begin",arguments:json!({"change_references":true}),label:"Change hair references"});}
                if self.hair.state.as_ref().unwrap().bound_reference!=self.hair.state.as_ref().unwrap().scalp.identity {
                    if ui.button("Rebind to changed head").clicked(){actions.push(UiAction::Hair(HairAction::Rebind));}
                }
            });
            egui::CollapsingHeader::new("Appearance").show(ui,|ui| {
                let supported=self.hair.state.as_ref().unwrap().locks.iter().filter(|l|self.hair.selected.contains(&(l.id as usize))).all(|l|l.kind==LockKind::Generated);
                ui.add_enabled_ui(!self.hair.selected.is_empty(),|ui| {
                    ui.add(egui::Slider::new(&mut self.hair.width,0.0001..=(span*0.2).clamp(0.001,10.0)).text("Lock width"));
                    ui.add_enabled(supported,egui::Slider::new(&mut self.hair.density,1..=32).text("Follower cards"));
                    if ui.button("Apply to selected locks").clicked(){actions.push(UiAction::Hair(HairAction::Settings));}
                });
                if !supported {ui.weak("Existing locks preserve their source cards and UVs; follower density is available for generated locks.");}
                let textures:Vec<_>=self.cdmw_state["hair"]["textures"].as_array().into_iter().flatten().filter_map(|v|v.as_str().map(String::from)).collect();
                if !textures.is_empty() {
                    self.hair.texture_index=self.hair.texture_index.min(textures.len()-1);
                    egui::ComboBox::from_label("Hair texture").selected_text(textures[self.hair.texture_index].rsplit('/').next().unwrap_or("DDS")).show_ui(ui,|ui| {
                        for (i,path) in textures.iter().enumerate(){ui.selectable_value(&mut self.hair.texture_index,i,path.rsplit('/').next().unwrap_or(path));}
                    });
                    for (title,command) in [("Open in Texture Editor","hair_texture_export"),("Apply edited DDS…","hair_texture")] {
                        if ui.button(title).clicked(){actions.push(UiAction::CdmwCommand{command,arguments:json!({"texture_path":textures[self.hair.texture_index]}),label:"Hair texture"});}
                    }
                }
            });
        });
        ui.separator();
        ui.strong("Motion");
        ui.weak("Editor motion preview. In-game movement depends on the donor's rig and physics; this preview does not simulate them.");
        let reason = self.hair_motion_reason().err();
        ui.horizontal(|ui| {
            if ui
                .add_enabled(
                    reason.is_none() || self.hair.playing,
                    egui::Button::new(if self.hair.playing { "Pause" } else { "Play" }),
                )
                .clicked()
            {
                self.hair.playing = !self.hair.playing;
                self.hair.last_tick = Instant::now();
            }
            if ui.button("Reset").clicked() {
                actions.push(UiAction::Hair(HairAction::Reset));
            }
        });
        if let Some(reason) = &reason {
            ui.weak(reason);
        }
        let tests = [
            "Still",
            "Turn",
            "Nod",
            "Head and shoulders",
            "Body sway",
            "Wind",
        ];
        egui::ComboBox::from_label("Movement test")
            .selected_text(tests[self.hair.head_test.min(5) as usize])
            .show_ui(ui, |ui| {
                for (i, label) in tests.iter().enumerate() {
                    ui.selectable_value(&mut self.hair.head_test, i as u32, *label);
                }
            });
        egui::CollapsingHeader::new("Advanced").show(ui, |ui| {
            ui.checkbox(&mut self.hair.show_reference, "Show character bust");
            ui.checkbox(&mut self.hair.show_guides, "Show guides and roots");
            ui.checkbox(&mut self.hair.show_collisions, "Show collision shapes");
            ui.weak("Alt-drag orbit · Shift-drag pan · wheel zoom · Escape cancel");
            ui.add(egui::Slider::new(&mut self.hair.motion.damping, 0.0..=20.0).text("Damping"));
            ui.add(
                egui::Slider::new(&mut self.hair.motion.bend_compliance, 0.0..=0.005)
                    .text("Shape softness"),
            );
            ui.add(
                egui::Slider::new(&mut self.hair.motion.gravity[1], -20.0..=0.0).text("Gravity"),
            );
            ui.horizontal(|ui| {
                ui.label("Wind");
                for v in &mut self.hair.motion.wind {
                    ui.add(egui::DragValue::new(v).speed(0.1).range(-30.0..=30.0));
                }
            });
            if ui
                .add_enabled(
                    ready
                        && reason.is_none()
                        && self
                            .hair
                            .simulation
                            .as_ref()
                            .is_some_and(|s| s.elapsed > 0.0),
                    egui::Button::new("Use settled shape"),
                )
                .clicked()
            {
                actions.push(UiAction::Hair(HairAction::Settle));
            }
            if ui
                .add_enabled(ready, egui::Button::new("Convert to ordinary mesh"))
                .clicked()
            {
                actions.push(UiAction::Hair(HairAction::Convert));
            }
            ui.weak("Preview motion is approximate. Game physics uses the donor's existing setup.");
        });
        if self.hair.topology_busy {
            ui.spinner();
            ui.label("Preparing hair…");
        }
        if self.hair.preparing() {
            ui.weak("Saving completed actions in order…");
        }
        if !self.hair.feedback.is_empty() {
            ui.weak(&self.hair.feedback);
        }
    }
}

impl HairEditor {
    pub(super) fn active(&self) -> bool {
        self.state.as_ref().is_some_and(|s| !s.converted)
    }
    pub(super) fn invalidate_scene(&mut self) {
        self.scene = None;
    }
    pub(super) fn preparing(&self) -> bool {
        self.job.is_some()
            || !self.queued.is_empty()
            || !self.publications.is_empty()
            || self.inflight.is_some()
            || self.stroke.is_some()
            || !self.pending_history.is_empty()
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
        if state.prepared_parts.contains(&(index as u32))
            && !state
                .locks
                .iter()
                .any(|l| l.part == index as u32 && !l.vertices.is_empty())
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
    let mut head_reference_ranges = vec![];
    if reference {
        for mesh in std::iter::once(&state.scalp).chain(&state.references) {
            let first = snapshot.positions.len() as u32;
            if std::ptr::eq(mesh, &state.scalp) || mesh.identity.starts_with("head:") {
                head_reference_ranges.push(first as usize..first as usize + mesh.positions.len());
            }
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
        // Scalp and neck remain separate motion roles but share a fitting seam.
        // Average coincident reference normals so that boundary and PAC UV seams
        // do not appear as a hard collar on the untextured mannequin.
        let key = |p: [f32; 3]| p.map(|v| (v * 100_000.0).round() as i64);
        let mut shared = std::collections::HashMap::<[i64; 3], Vec3>::new();
        for i in reference_start..snapshot.positions.len() {
            *shared.entry(key(snapshot.positions[i])).or_default() +=
                Vec3::from(snapshot.normals[i]);
        }
        for i in reference_start..snapshot.positions.len() {
            snapshot.normals[i] = shared[&key(snapshot.positions[i])]
                .normalize_or_zero()
                .to_array();
        }
    }
    let mut vertex_locks = vec![None; snapshot.positions.len()];
    for (part, first, count, _) in &parts {
        for lock in state.locks.iter().filter(|l| l.part == *part) {
            for vertex in &lock.vertices {
                if (*vertex as usize) < *count {
                    vertex_locks[first + *vertex as usize] = Some(lock.id);
                }
            }
        }
    }
    let mut vertex_along = vec![0.0; snapshot.positions.len()];
    for (part, first, count, _) in &parts {
        for binding in state.bindings.iter().filter(|b| b.part == *part) {
            if (binding.vertex as usize) < *count {
                vertex_along[first + binding.vertex as usize] = binding.segment as f32 + binding.t;
            }
        }
    }
    let picking = hair::surface::SurfaceIndex::new(&snapshot.positions, &snapshot.indices);
    let scalp_indices: Vec<_> = state.scalp.triangles.iter().flatten().copied().collect();
    let scalp_picking = hair::surface::SurfaceIndex::new(&state.scalp.positions, &scalp_indices);
    HairScene {
        picking,
        vertex_locks,
        vertex_along,
        picking_indices: snapshot.indices.clone(),
        scalp_indices,
        scalp_picking,
        rest: snapshot.clone(),
        frame: snapshot,
        parts,
        reference_start,
        head_reference_ranges,
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
