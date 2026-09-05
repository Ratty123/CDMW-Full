#![forbid(unsafe_code)]
#[cfg(test)]
use crate::preview_effects::particle_kinematics;
use crate::preview_effects::{effect_emitter_billboards, effect_emitter_lines, push_effect_line};

use crate::camera::{OrbitCamera, StandardView};
use crate::cdmw_material_preview_factors;
use crate::cdmw_session::{
    CdmwEffectTextureResource, CdmwTextureResource, LoadedCdmwSessionPackage, PREVIEW_BACKEND,
    PREVIEW_PROTOCOL, RENDERER, SessionMaterialPresentation,
};
use crate::preview_geometry::{PreviewGeometry, placed_scene, retain_live_placement};
use crate::preview_loader::{LoadRequest, PreviewLoader};
use anyhow::{Context, Result};
use cdmw_formats::{MeshDocument, SourceRange, Submesh};
use cdmw_mesh::{DrawSnapshot, Provenance, Selection, WorkingMesh};
use cdmw_render_wgpu::{
    EffectLineVertex, LightingPreset, MaterialPreviewFactors, ViewMode, WindowRenderer,
};
use crossbeam_channel::{Receiver, Sender, bounded};
use egui::{Pos2, Rect, Vec2 as EguiVec2};
use glam::{Mat4, Vec2, Vec3};
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};
use winit::application::ApplicationHandler;
use winit::event::{ElementState, MouseButton, MouseScrollDelta, WindowEvent};
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoopProxy};
use winit::keyboard::{Key, ModifiersState, NamedKey};
use winit::window::{Window, WindowAttributes, WindowId};

const CONTROL_QUEUE_BOUND: usize = 256;
const OUTBOUND_QUEUE_BOUND: usize = 128;
const MAX_CONTROL_LINE_BYTES: usize = 256 * 1024;

pub(crate) const CAPABILITIES: &[&str] = &[
    "embedded_child_window_v1",
    "rust_preview_runtime_v1",
    "preview_profile_read_only_v1",
    "preview_session_v1",
    "resident_package_load_v1",
    "resident_preview_package_replace_v2",
    "absolute_camera_state_v1",
    "view_state_changed_v1",
    "viewport_display_modes_v1",
    "read_only_part_pick_v1",
    "overlay_state_update_v1",
    "skeleton_overlay_v1",
    "pbd_cloth_overlay_v1",
    "deterministic_offscreen_capture_v1",
    "comparison_scene_v1",
    "alignment_preview_v1",
    "semantic_framing_v1",
    "gpu_scene_transforms_v1",
    "full_gizmo_handles_v1",
    "camera_navigator_v1",
    "lighting_presets_v1",
    "static_replacement_mesh_input_v1",
    "effect_particle_preview_v1",
    "textured_effect_particles_v1",
    "ui_theme_state_v1",
    "ui_localization_v1",
];

pub(crate) fn control_contract() -> Value {
    let commands = [
        ("preview_session_state", "both", "preview_session_state_ack"),
        ("package_load_request", "both", "package_loaded"),
        ("canonical_view_request", "both", "canonical_view_applied"),
        (
            "presentation_state_update",
            "both",
            "presentation_state_update_ack",
        ),
        ("overlay_state_update", "both", "overlay_state_update_ack"),
        ("scene_state_update", "both", "scene_state_update_ack"),
        (
            "material_parameter_update",
            "both",
            "material_parameter_update_ack",
        ),
        ("activate_request", "both", "activated"),
        ("deactivate_request", "both", "deactivated"),
        ("reembed_request", "both", "reembedded"),
        ("capture_request", "both", "capture_result"),
        ("ui_localization_state", "both", "ui_localization_state_ack"),
        ("ui_theme_state", "both", "ui_theme_state_ack"),
        ("tool_state", "static_replacement", "tool_state_ack"),
        (
            "preview_vertex_update",
            "static_replacement",
            "preview_vertex_update_ack",
        ),
        (
            "preview_triangle_update",
            "static_replacement",
            "preview_triangle_update_ack",
        ),
        (
            "selection_update",
            "static_replacement",
            "selection_update_ack",
        ),
        ("close_request", "both", "process_exit"),
        ("cancel", "both", "process_exit"),
    ]
    .into_iter()
    .map(|(command, profile, feedback)| {
        json!({
            "command": command,
            "profile": profile,
            "feedback": feedback,
            "compiled_dispatch": true,
            "rust_implemented": true,
        })
    })
    .collect::<Vec<_>>();
    json!({
        "schema": "cdmw_rust_preview_control_contract_v1",
        "protocol": PREVIEW_PROTOCOL,
        "package": "cdmw_rust_preview_package_v1",
        "renderer": RENDERER,
        "backend": PREVIEW_BACKEND,
        "viewport_only": true,
        "profiles": ["read_only", "static_replacement"],
        "capabilities": CAPABILITIES,
        "commands": commands,
        "read_only_mutations_rejected": true,
        "ok": true,
    })
}

#[derive(Debug)]
enum Incoming {
    Message(Value),
    Error(String),
    Closed,
}

#[derive(Debug)]
struct CaptureResult {
    request_id: u64,
    output_path: PathBuf,
    result: std::result::Result<(), String>,
}

#[derive(Debug)]
struct PreviewBridge {
    incoming: Receiver<Incoming>,
    outbound: Sender<Value>,
    session_id: String,
    process_generation: u64,
}

impl PreviewBridge {
    fn new(session_id: String, process_generation: u64, proxy: EventLoopProxy<()>) -> Self {
        let (incoming_tx, incoming) = bounded(CONTROL_QUEUE_BOUND);
        let (outbound, outbound_rx) = bounded(OUTBOUND_QUEUE_BOUND);
        thread::Builder::new()
            .name("cdmw-rust-preview-input".to_owned())
            .spawn(move || {
                let input = std::io::stdin();
                let mut reader = BufReader::new(input.lock());
                loop {
                    let mut line = String::new();
                    match reader.read_line(&mut line) {
                        Ok(0) => break,
                        Ok(_) if line.len() > MAX_CONTROL_LINE_BYTES => {
                            let _ = incoming_tx.try_send(Incoming::Error(
                                "Rust Preview protocol line exceeded its safety limit".to_owned(),
                            ));
                            break;
                        }
                        Ok(_) => match serde_json::from_str::<Value>(line.trim()) {
                            Ok(value) => {
                                if incoming_tx.try_send(Incoming::Message(value)).is_err() {
                                    let _ = incoming_tx.try_send(Incoming::Error(
                                        "Rust Preview protocol queue is full".to_owned(),
                                    ));
                                }
                                let _ = proxy.send_event(());
                            }
                            Err(error) => {
                                let _ = incoming_tx.try_send(Incoming::Error(format!(
                                    "Rust Preview received invalid JSON: {error}"
                                )));
                                let _ = proxy.send_event(());
                            }
                        },
                        Err(error) => {
                            let _ = incoming_tx.try_send(Incoming::Error(format!(
                                "Rust Preview input failed: {error}"
                            )));
                            break;
                        }
                    }
                }
                let _ = incoming_tx.send(Incoming::Closed);
                let _ = proxy.send_event(());
            })
            .expect("Rust Preview input thread");
        thread::Builder::new()
            .name("cdmw-rust-preview-output".to_owned())
            .spawn(move || {
                let output = std::io::stdout();
                let mut writer = BufWriter::new(output.lock());
                while let Ok(value) = outbound_rx.recv() {
                    if serde_json::to_writer(&mut writer, &value).is_err()
                        || writer.write_all(b"\n").is_err()
                        || writer.flush().is_err()
                    {
                        break;
                    }
                }
            })
            .expect("Rust Preview output thread");
        Self {
            incoming,
            outbound,
            session_id,
            process_generation: process_generation.max(1),
        }
    }

    fn send(&self, mut value: Value) {
        if let Some(object) = value.as_object_mut() {
            object
                .entry("protocol".to_owned())
                .or_insert_with(|| json!(PREVIEW_PROTOCOL));
            object
                .entry("session_id".to_owned())
                .or_insert_with(|| json!(self.session_id));
            object
                .entry("process_generation".to_owned())
                .or_insert_with(|| json!(self.process_generation));
        }
        let _ = self.outbound.try_send(value);
    }

    fn announce(&self, child_hwnd: u64, parent_hwnd: u64, adapter: &str) {
        let common = json!({
            "profile": "preview",
            "renderer": RENDERER,
            "edit_backend": PREVIEW_BACKEND,
            "process_id": std::process::id(),
            "child_hwnd": child_hwnd,
            "form_hwnd": child_hwnd,
            "embedded_parent_hwnd": parent_hwnd,
            "capabilities": CAPABILITIES,
            "adapter": adapter,
        });
        let mut protocol_ready = common.clone();
        protocol_ready["event"] = json!("protocol_ready");
        self.send(protocol_ready);
        let mut ready = common;
        ready["event"] = json!("ready");
        self.send(ready);
    }

    fn poll(&self) -> Vec<Incoming> {
        let mut events = Vec::new();
        while let Ok(event) = self.incoming.try_recv() {
            events.push(event);
        }
        events
    }
}

#[derive(Debug, Default)]
struct PreviewState {
    presentation: Value,
    overlays: Value,
    scene: Value,
    material_parameters: Value,
    theme: Value,
}

#[derive(Debug, Clone)]
struct GizmoDrag {
    tool: String,
    handle: String,
    start_pointer: Vec2,
    start_placement: Value,
    start_model_matrix: Mat4,
    start_pivot: Vec3,
}

#[derive(Debug, Clone)]
struct NavigatorDrag {
    start_pointer: Vec2,
    last_pointer: Vec2,
    moved: bool,
}

#[derive(Debug, Clone)]
struct PendingGizmoUpdate {
    tool: String,
    handle: String,
    placement: Value,
}

#[derive(Debug)]
struct EffectClock {
    elapsed: f32,
    last_tick: Instant,
}

impl EffectClock {
    fn new() -> Self {
        Self {
            elapsed: 0.0,
            last_tick: Instant::now(),
        }
    }

    fn sample(&mut self, paused: bool) -> f32 {
        let now = Instant::now();
        let delta = now.duration_since(self.last_tick).as_secs_f32();
        self.last_tick = now;
        if !paused {
            // A suspended or heavily loaded UI must not make the next frame
            // fast-forward through an unbounded amount of simulation.
            self.elapsed += delta.clamp(0.0, 0.1);
        }
        self.elapsed
    }

    fn reset(&mut self) {
        self.elapsed = 0.0;
        self.last_tick = Instant::now();
    }
}

pub struct PreviewApplication {
    window: Option<Arc<Window>>,
    parent_hwnd: u64,
    renderer: Option<WindowRenderer>,
    bridge: PreviewBridge,
    package: LoadedCdmwSessionPackage,
    document: MeshDocument,
    mesh: WorkingMesh,
    geometry: PreviewGeometry,
    snapshot: DrawSnapshot,
    snapshot_scene_roles: Option<Vec<u32>>,
    textures: Vec<CdmwTextureResource>,
    effect_textures: Vec<CdmwEffectTextureResource>,
    effect_texture_indices: HashMap<String, usize>,
    presentations: Vec<SessionMaterialPresentation>,
    camera: OrbitCamera,
    view_mode: ViewMode,
    state: PreviewState,
    visible: bool,
    exit_requested: bool,
    pointer: Option<Vec2>,
    orbiting: bool,
    modifiers: ModifiersState,
    left_camera_drag: bool,
    panning: bool,
    right_press: Option<Vec2>,
    hovered_part: Option<u32>,
    hovered_gizmo_handle: Option<String>,
    gizmo_drag: Option<GizmoDrag>,
    navigator_drag: Option<NavigatorDrag>,
    pending_gizmo_update: Option<PendingGizmoUpdate>,
    scene_revision: u64,
    effect_clock: EffectClock,
    loader: PreviewLoader,
    wake_proxy: EventLoopProxy<()>,
    capture_in_flight: bool,
    next_frame: Option<Instant>,
    render_failures: u32,
    capture_tx: Sender<CaptureResult>,
    capture_rx: Receiver<CaptureResult>,
    newest_package_generation: u64,
    newest_package_request_id: u64,
    package_waiting_for_interaction: bool,
}

impl PreviewApplication {
    pub fn open(manifest_path: &Path, parent_hwnd: u64, proxy: EventLoopProxy<()>) -> Result<Self> {
        let mut package = LoadedCdmwSessionPackage::load_preview(manifest_path)
            .context("failed to load the initial Rust Preview package")?;
        let document = package.document().clone();
        let mesh = WorkingMesh::from_document_lod(&document, package.source_lod_index())
            .context("Rust Preview document could not create its requested LOD")?;
        let snapshot = mesh.draw_snapshot();
        let geometry = PreviewGeometry::from_mesh(&mesh);
        let textures = package.take_textures();
        let effect_textures = package.take_effect_textures();
        let presentations = package.take_material_presentations();
        let scene = package
            .manifest()
            .state
            .get("preview_scene")
            .cloned()
            .unwrap_or(Value::Null);
        let bridge = PreviewBridge::new(
            package.manifest().session_id.clone(),
            package.manifest().process_generation,
            proxy.clone(),
        );
        let loader = PreviewLoader::new(proxy.clone())?;
        let (capture_tx, capture_rx) = bounded(2);
        let mut camera = OrbitCamera::default();
        camera.frame_integrated_startup(&mesh);
        let mut application = Self {
            window: None,
            parent_hwnd,
            renderer: None,
            bridge,
            package,
            document,
            mesh,
            geometry,
            snapshot,
            snapshot_scene_roles: None,
            textures,
            effect_textures,
            effect_texture_indices: HashMap::new(),
            presentations,
            camera,
            view_mode: ViewMode::TexturedSolid,
            state: PreviewState {
                scene,
                ..PreviewState::default()
            },
            visible: false,
            exit_requested: false,
            pointer: None,
            orbiting: false,
            modifiers: ModifiersState::empty(),
            left_camera_drag: false,
            panning: false,
            right_press: None,
            hovered_part: None,
            hovered_gizmo_handle: None,
            gizmo_drag: None,
            navigator_drag: None,
            pending_gizmo_update: None,
            scene_revision: 1,
            effect_clock: EffectClock::new(),
            loader,
            capture_in_flight: false,
            wake_proxy: proxy,
            next_frame: None,
            render_failures: 0,
            capture_tx,
            capture_rx,
            newest_package_generation: 0,
            newest_package_request_id: 0,
            package_waiting_for_interaction: false,
        };
        application.refresh_visible_snapshot();
        application.apply_canonical_view(false);
        Ok(application)
    }

    fn viewport_rect(&self) -> Rect {
        let size = self
            .window
            .as_ref()
            .map(|window| window.inner_size())
            .unwrap_or(winit::dpi::PhysicalSize::new(1, 1));
        Rect::from_min_size(
            Pos2::ZERO,
            EguiVec2::new(size.width.max(1) as f32, size.height.max(1) as f32),
        )
    }

    fn current_world_bounds(&self) -> Option<(Vec3, Vec3)> {
        let visible = self.visible_submeshes();
        let mut bounds: Option<(Vec3, Vec3)> = None;
        for part in &self.geometry.parts {
            if !visible.contains(&part.submesh) {
                continue;
            }
            let (low, high) = part.bounds(self.submesh_model_matrix(part.submesh));
            if low.is_finite() && high.is_finite() {
                bounds = Some(bounds.map_or((low, high), |(a, b)| (a.min(low), b.max(high))));
            }
        }
        bounds
    }

    fn apply_canonical_view(&mut self, emit: bool) {
        let initial = &self.state.scene["framing"]["initial_view"];
        let semantic = self.camera.set_semantic_view(
            vec3_value(initial.get("view_direction"), Vec3::ZERO),
            vec3_value(initial.get("screen_up_direction"), Vec3::ZERO),
        );
        if let Some((low, high)) = self.current_world_bounds() {
            if !semantic {
                self.camera
                    .frame_integrated_positions([low, high].into_iter());
            }
            self.camera
                .frame_explicit_bounds_in_viewport(low, high, self.viewport_rect());
        }
        if emit {
            self.emit_view_state("fit");
        }
    }

    fn configure_renderer(&mut self) -> Result<(), String> {
        let Some(renderer) = &mut self.renderer else {
            return Ok(());
        };
        let effect_texture_indices = renderer
            .replace_preview_scene(|renderer| {
                renderer.reset_texture();
                renderer.reset_effect_textures();
                let mut effect_texture_indices = HashMap::new();
                for texture in &self.effect_textures {
                    let index = renderer.add_effect_dds_texture(&texture.bytes)?;
                    effect_texture_indices.insert(texture.archive_path.clone(), index);
                }
                for texture in &self.textures {
                    renderer.add_dds_texture(
                        &texture.bytes,
                        texture.role,
                        &texture.material_indices_by_lod,
                    )?;
                }
                for presentation in &self.presentations {
                    let ownership =
                        presentation_ownership(presentation, self.package.document().lods.len());
                    renderer.add_material_factors(
                        cdmw_material_preview_factors(presentation),
                        &ownership,
                    )?;
                }
                renderer.set_material_lod(self.package.source_lod_index())?;
                if let Some(roles) = self.snapshot_scene_roles.as_deref() {
                    renderer.set_snapshot_with_scene_roles(&self.snapshot, roles)?;
                    renderer
                        .set_scene_transform(role_model_matrix(&self.state.scene, "editable"))?;
                } else {
                    renderer.set_snapshot(&self.snapshot)?;
                    renderer.set_scene_transform(Mat4::IDENTITY)?;
                }
                Ok(effect_texture_indices)
            })
            .map_err(|error| error.to_string())?;
        self.effect_texture_indices = effect_texture_indices;
        Ok(())
    }

    fn start_package_load(
        &mut self,
        request_id: u64,
        generation: u64,
        path: PathBuf,
        reset_view: bool,
    ) {
        if generation < self.newest_package_generation {
            return;
        }
        if reset_view {
            self.cancel_gesture();
        }
        self.newest_package_generation = generation;
        self.newest_package_request_id = request_id;
        self.package_waiting_for_interaction = false;
        self.loader.request(LoadRequest {
            request_id,
            generation,
            path,
            reset_view,
            revision: self.scene_revision.saturating_add(1),
            presentation: crate::preview_geometry::snapshot_presentation(&self.state.presentation),
        });
    }

    fn poll_package_loads(&mut self) -> bool {
        // Texture promotion must not cancel a live gesture or upload its new
        // GPU resources between pointer samples. The loader keeps one ready
        // result and replaces it when a newer selection arrives.
        if self.gizmo_drag.is_some()
            || self.orbiting
            || self.panning
            || self.navigator_drag.is_some()
        {
            if !self.package_waiting_for_interaction && !self.loader.results.is_empty() {
                self.package_waiting_for_interaction = true;
                self.bridge.send(json!({
                    "event": "package_load_progress", "phase": "waiting_for_interaction",
                    "request_id": self.newest_package_request_id,
                    "generation": self.newest_package_generation,
                }));
            }
            return false;
        }
        if self.package_waiting_for_interaction {
            self.package_waiting_for_interaction = false;
            self.bridge.send(json!({
                "event": "package_load_progress", "phase": "preparing",
                "request_id": self.newest_package_request_id,
                "generation": self.newest_package_generation,
            }));
        }
        let mut changed = false;
        while let Ok(result) = self.loader.results.try_recv() {
            let request = result.request;
            if request.generation != self.newest_package_generation {
                continue;
            }
            let applied = (|| -> Result<(), String> {
                let mut loaded = result.result?;
                self.cancel_gesture();
                let old_document = std::mem::replace(&mut self.document, loaded.document);
                let old_mesh = std::mem::replace(&mut self.mesh, loaded.mesh);
                let old_geometry = std::mem::replace(&mut self.geometry, loaded.geometry);
                let old_snapshot = std::mem::replace(&mut self.snapshot, loaded.snapshot);
                let old_roles = std::mem::replace(&mut self.snapshot_scene_roles, loaded.roles);
                let old_textures =
                    std::mem::replace(&mut self.textures, loaded.package.take_textures());
                let old_effects = std::mem::replace(
                    &mut self.effect_textures,
                    loaded.package.take_effect_textures(),
                );
                let old_presentations = std::mem::replace(
                    &mut self.presentations,
                    loaded.package.take_material_presentations(),
                );
                let old_scene = std::mem::replace(
                    &mut self.state.scene,
                    loaded
                        .package
                        .manifest()
                        .state
                        .get("preview_scene")
                        .cloned()
                        .unwrap_or(Value::Null),
                );
                let old_package = std::mem::replace(&mut self.package, loaded.package);
                let retained_placement =
                    retain_live_placement(&old_scene, &mut self.state.scene, request.reset_view);
                let old_revision = self.scene_revision;
                self.scene_revision = self.scene_revision.saturating_add(1);
                // Prepare visible CPU data without touching the resident GPU scene.
                let renderer = self.renderer.take();
                if request.presentation
                    != crate::preview_geometry::snapshot_presentation(&self.state.presentation)
                    || (retained_placement && self.snapshot_scene_roles.is_none())
                {
                    self.refresh_visible_snapshot();
                }
                self.renderer = renderer;
                if let Err(error) = self.configure_renderer() {
                    self.document = old_document;
                    self.mesh = old_mesh;
                    self.geometry = old_geometry;
                    self.snapshot = old_snapshot;
                    self.snapshot_scene_roles = old_roles;
                    self.textures = old_textures;
                    self.effect_textures = old_effects;
                    self.presentations = old_presentations;
                    self.state.scene = old_scene;
                    self.package = old_package;
                    self.scene_revision = old_revision;
                    return Err(error);
                }
                self.effect_clock.reset();
                self.state.material_parameters = Value::Null;
                if request.reset_view
                    && let Some(presentation) = self.state.presentation.as_object_mut()
                {
                    presentation.remove("camera");
                }
                self.apply_presentation(false);
                if request.reset_view {
                    self.apply_canonical_view(true);
                }
                Ok(())
            })();
            match applied {
                Ok(()) => {
                    self.bridge.send(
                        json!({"event":"package_load_applied","request_id":request.request_id,
                        "generation":request.generation,"package_path":request.path,
                        "material_signature":self.package.manifest().source.get("sha256")}),
                    );
                    changed = true;
                }
                Err(error) => self.bridge.send(
                    json!({"event":"package_load_failed","request_id":request.request_id,
                    "generation":request.generation,"package_path":request.path,"error":error}),
                ),
            }
        }
        changed
    }

    fn start_capture(&mut self, value: &Value) {
        let request_id = value.get("request_id").and_then(Value::as_u64).unwrap_or(0);
        let Some(output_path) = value
            .get("output_path")
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .map(PathBuf::from)
        else {
            self.bridge.send(json!({
                "event": "capture_result",
                "request_id": request_id,
                "status": "error",
                "message": "capture output path is missing",
            }));
            return;
        };
        let width = value
            .get("width")
            .and_then(Value::as_u64)
            .and_then(|value| u32::try_from(value).ok())
            .unwrap_or(512)
            .clamp(64, 2_048);
        let height = value
            .get("height")
            .and_then(Value::as_u64)
            .and_then(|value| u32::try_from(value).ok())
            .unwrap_or(512)
            .clamp(64, 2_048);
        let yaw_degrees = value.get("yaw_degrees").and_then(Value::as_f64);
        let pitch_degrees = value.get("pitch_degrees").and_then(Value::as_f64);
        let result = (|| -> Result<_> {
            if self.capture_in_flight {
                anyhow::bail!("A preview capture is already in progress");
            }
            let saved_camera = self.camera.clone();
            match yaw_degrees.zip(pitch_degrees) {
                Some((yaw, pitch))
                    if yaw.is_finite() && pitch.is_finite() && pitch.abs() <= 89.0 =>
                {
                    self.camera.set_orbit_state_with_roll(
                        (yaw as f32).to_radians(),
                        (pitch as f32).to_radians(),
                        self.camera.roll(),
                        None,
                        None,
                    );
                }
                None if yaw_degrees.is_none() && pitch_degrees.is_none() => {}
                _ => anyhow::bail!(
                    "capture yaw and pitch must both be finite and pitch must be within -89..89 degrees"
                ),
            }
            let time = self.effect_time();
            self.refresh_scene_overlays_for_capture(time, true);
            let rectangle =
                Rect::from_min_size(Pos2::ZERO, EguiVec2::new(width as f32, height as f32));
            let matrix = self.camera.view_projection(rectangle);
            let right = self.camera.right();
            let up = self.camera.up();
            let capture = self
                .renderer
                .as_mut()
                .ok_or_else(|| anyhow::anyhow!("Preview renderer is unavailable"))
                .and_then(|renderer| {
                    let isolated = value
                        .get("material_index")
                        .and_then(Value::as_u64)
                        .and_then(|v| u32::try_from(v).ok());
                    renderer.set_view_mode(if isolated.is_some() {
                        ViewMode::TexturedSolid
                    } else {
                        self.view_mode
                    });
                    renderer.set_camera_with_basis(matrix, right, up);
                    renderer
                        .capture_frame(width, height, isolated)
                        .map_err(|e| anyhow::anyhow!(e.to_string()))
                });
            self.camera = saved_camera;
            self.refresh_scene_overlays(time);
            let matrix = self.camera.view_projection(self.viewport_rect());
            if let Some(renderer) = &mut self.renderer {
                renderer.set_view_mode(self.view_mode);
                renderer.set_camera_with_basis(matrix, self.camera.right(), self.camera.up());
            }
            capture
        })();
        let capture = match result {
            Ok(capture) => capture,
            Err(error) => {
                self.bridge.send(json!({"event":"capture_result","request_id":request_id,"status":"error","message":error.to_string()}));
                return;
            }
        };
        let sender = self.capture_tx.clone();
        let proxy = self.wake_proxy.clone();
        let worker = thread::Builder::new()
            .name("cdmw-preview-capture".into())
            .spawn(move || {
                let result = (|| -> Result<()> {
                    if let Some(parent) = output_path.parent() {
                        fs::create_dir_all(parent)?;
                    }
                    capture
                        .write(&output_path)
                        .map_err(|e| anyhow::anyhow!(e.to_string()))
                })()
                .map_err(|e| e.to_string());
                let _ = sender.send(CaptureResult {
                    request_id,
                    output_path,
                    result,
                });
                let _ = proxy.send_event(());
            });
        match worker {
            Ok(_)=>self.capture_in_flight=true,
            Err(error)=>self.bridge.send(json!({"event":"capture_result","request_id":request_id,"status":"error","message":error.to_string()})),
        }
    }

    fn poll_captures(&mut self) {
        while let Ok(result) = self.capture_rx.try_recv() {
            self.capture_in_flight = false;
            match result.result {
                Ok(()) => self.bridge.send(json!({
                    "event": "capture_result",
                    "request_id": result.request_id,
                    "status": "captured",
                    "output_path": result.output_path,
                })),
                Err(error) => self.bridge.send(json!({
                    "event": "capture_result",
                    "request_id": result.request_id,
                    "status": "error",
                    "output_path": result.output_path,
                    "message": error,
                })),
            }
        }
    }

    fn handle_message(&mut self, value: Value) -> bool {
        let event = value
            .get("event")
            .and_then(Value::as_str)
            .unwrap_or_default();
        match event {
            "preview_session_state" => {
                if let Some(session_id) = value.get("session_id").and_then(Value::as_str) {
                    self.bridge.session_id = session_id.to_owned();
                }
                if let Some(generation) = value.get("process_generation").and_then(Value::as_u64) {
                    self.bridge.process_generation = generation.max(1);
                }
                self.bridge
                    .send(json!({"event": "preview_session_state_ack", "status": "applied"}));
            }
            "package_load_request" => {
                let request_id = value.get("request_id").and_then(Value::as_u64).unwrap_or(0);
                let generation = value.get("generation").and_then(Value::as_u64).unwrap_or(0);
                if let Some(path) = value.get("package_path").and_then(Value::as_str) {
                    // Missing retains the original package-load behavior for
                    // older clients. Progressive geometry/material upgrades
                    // opt out explicitly so the user's view is conserved.
                    let reset_view = value
                        .get("reset_view")
                        .and_then(Value::as_bool)
                        .unwrap_or(true);
                    self.start_package_load(
                        request_id,
                        generation,
                        PathBuf::from(path),
                        reset_view,
                    );
                }
            }
            "canonical_view_request" => {
                self.apply_canonical_view(true);
                self.ack_state(event, &value);
                return true;
            }
            "presentation_state_update" => {
                let camera_changed = value.get("camera").is_some();
                let geometry_changed = [
                    "active_view",
                    "comparison_mode",
                    "visibility",
                    "uv",
                    "part_transforms",
                    "side_by_side_split_ratio",
                ]
                .iter()
                .any(|key| value.get(*key).is_some());
                merge_value(&mut self.state.presentation, &value);
                if geometry_changed {
                    self.scene_revision = self.scene_revision.saturating_add(1);
                    self.refresh_visible_snapshot();
                }
                self.apply_presentation(camera_changed);
                self.ack_state(event, &value);
                return true;
            }
            "overlay_state_update" => {
                merge_value(&mut self.state.overlays, &value);
                self.apply_overlays();
                self.ack_state(event, &value);
                return true;
            }
            "scene_state_update" => {
                let old_reference = role_model_matrix(&self.state.scene, "reference");
                let old_roles = (
                    editable_indices(&self.state.scene),
                    reference_indices(&self.state.scene),
                );
                let old_comparison = self.state.scene.get("comparison_mode").cloned();
                let old_reference_draw = self.state.scene.get("reference_draw").cloned();
                let old_identities = self.state.scene.get("part_identities").cloned();
                merge_value(&mut self.state.scene, &value);
                self.scene_revision = self.scene_revision.saturating_add(1);
                if self.snapshot_scene_roles.is_some()
                    && old_reference == role_model_matrix(&self.state.scene, "reference")
                    && old_roles
                        == (
                            editable_indices(&self.state.scene),
                            reference_indices(&self.state.scene),
                        )
                    && old_comparison == self.state.scene.get("comparison_mode").cloned()
                    && old_reference_draw == self.state.scene.get("reference_draw").cloned()
                    && old_identities == self.state.scene.get("part_identities").cloned()
                {
                    if let Some(renderer) = &mut self.renderer {
                        let _ = renderer
                            .set_scene_transform(role_model_matrix(&self.state.scene, "editable"));
                    }
                } else {
                    self.refresh_visible_snapshot();
                }
                self.apply_presentation(false);
                self.ack_state(event, &value);
                return true;
            }
            "material_parameter_update" => {
                let old = std::mem::replace(&mut self.state.material_parameters, value.clone());
                if let Err(error) = self.apply_material_parameters() {
                    self.state.material_parameters = old;
                    self.bridge.send(json!({"event":"material_parameter_update_ack","request_id":value.get("request_id"),"status":"rejected","error":error}));
                } else {
                    self.ack_state(event, &value);
                }
                return true;
            }
            "activate_request" => {
                self.visible = true;
                if let Some(window) = &self.window {
                    window.set_visible(true);
                    window.request_redraw();
                }
                self.bridge.send(json!({
                    "event": "activated",
                    "activation_request_id": value.get("activation_request_id").cloned().unwrap_or(Value::Null),
                    "package_generation": value.get("package_generation").cloned().unwrap_or(Value::Null),
                }));
            }
            "deactivate_request" => {
                self.cancel_gesture();
                self.visible = false;
                if let Some(window) = &self.window {
                    window.set_visible(false);
                }
                self.bridge.send(json!({"event": "deactivated"}));
            }
            "reembed_request" => {
                self.parent_hwnd = value
                    .get("parent_hwnd")
                    .and_then(Value::as_u64)
                    .unwrap_or(self.parent_hwnd);
                self.bridge
                    .send(json!({"event": "reembedded", "parent_hwnd": self.parent_hwnd}));
            }
            "capture_request" => self.start_capture(&value),
            "close_request" | "cancel" => self.exit_requested = true,
            "ui_localization_state" => self.bridge.send(json!({
                "event": "ui_localization_state_ack",
                "status": "applied",
                "revision": value.get("revision").cloned().unwrap_or(json!(0)),
            })),
            "ui_theme_state" => {
                self.state.theme = value.clone();
                if let Some(background) = value
                    .get("palette")
                    .and_then(|palette| palette.get("window"))
                    .and_then(Value::as_str)
                    .and_then(parse_color)
                    && let Some(renderer) = &mut self.renderer
                {
                    renderer.set_clear_colour(background);
                }
                self.ack_state(event, &value);
                return true;
            }
            "tool_state" => {
                if self.package.manifest().interaction_profile != "static_replacement" {
                    self.bridge.send(json!({
                        "event": "error",
                        "request_id": value.get("request_id").cloned().unwrap_or(Value::Null),
                        "error": "read_only preview rejects mesh mutations",
                    }));
                } else {
                    self.ack_state(event, &value);
                }
            }
            "preview_vertex_update" | "preview_triangle_update" | "selection_update" => {
                if self.package.manifest().interaction_profile != "static_replacement" {
                    self.bridge.send(json!({
                        "event": "error",
                        "request_id": value.get("request_id").cloned().unwrap_or(Value::Null),
                        "error": "read_only preview rejects mesh mutations",
                    }));
                } else {
                    let result = match event {
                        "preview_vertex_update" => self.apply_vertex_update(&value),
                        "preview_triangle_update" => self.apply_triangle_update(&value),
                        _ => self.apply_selection_update(&value),
                    };
                    match result {
                        Ok(changed) => {
                            self.bridge.send(json!({
                                "event": format!("{event}_ack"),
                                "request_id": value.get("request_id").cloned().unwrap_or(Value::Null),
                                "status": "applied",
                                "changed_count": changed,
                                "edit_revision": value.get("edit_revision").cloned().unwrap_or(Value::Null),
                            }));
                            return changed > 0;
                        }
                        Err(error) => self.bridge.send(json!({
                            "event": format!("{event}_ack"),
                            "request_id": value.get("request_id").cloned().unwrap_or(Value::Null),
                            "status": "rejected",
                            "error": error,
                        })),
                    }
                }
            }
            _ => {}
        }
        false
    }

    fn ack_state(&self, event: &str, value: &Value) {
        self.bridge.send(json!({
            "event": format!("{event}_ack"),
            "request_id": value.get("request_id").cloned().unwrap_or(Value::Null),
            "status": "applied",
        }));
    }

    fn poll_bridge(&mut self) -> bool {
        let mut changed = false;
        for incoming in self.bridge.poll() {
            match incoming {
                Incoming::Message(value) => changed |= self.handle_message(value),
                Incoming::Closed => self.exit_requested = true,
                Incoming::Error(error) => {
                    self.bridge.send(json!({"event": "error", "error": error}))
                }
            }
        }
        changed
    }

    fn apply_presentation(&mut self, apply_camera: bool) {
        let display = self
            .state
            .presentation
            .get("display")
            .unwrap_or(&Value::Null);
        if let Some(mode) = display.get("mode").and_then(Value::as_str) {
            self.view_mode = match mode {
                "textured" => ViewMode::TexturedSolid,
                "untextured_faces" => ViewMode::Solid,
                "untextured_wire" => ViewMode::SolidWire,
                "wire" => ViewMode::Wireframe,
                "vertices" => ViewMode::Vertices,
                "wire_vertices" => ViewMode::WireVertices,
                "xray" => ViewMode::XRay,
                _ => self.view_mode,
            };
        }
        let quality = display.get("quality").unwrap_or(&Value::Null);
        let background = display
            .get("viewport_background_color")
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .or_else(|| {
                quality
                    .get("d3d11_background_color")
                    .and_then(Value::as_str)
            })
            .and_then(parse_color);
        let wire = quality
            .get("d3d11_wire_color")
            .and_then(Value::as_str)
            .and_then(parse_color)
            .unwrap_or([0.72, 0.82, 1.0, 1.0]);
        let vertex = quality
            .get("d3d11_vertex_color")
            .and_then(Value::as_str)
            .and_then(parse_color)
            .unwrap_or([1.0, 0.22, 0.28, 1.0]);
        if let Some(renderer) = &mut self.renderer {
            if let Some(background) = background {
                renderer.set_clear_colour(background);
            }
            renderer.set_overlay_colours(wire, vertex);
            renderer.set_lighting_preset(
                match display.get("lighting_preset").and_then(Value::as_str) {
                    Some("showcase") => LightingPreset::Showcase,
                    _ => LightingPreset::NeutralStudio,
                },
            );
        }
        if apply_camera && let Some(camera) = self.state.presentation.get("camera") {
            let yaw_degrees = camera.get("yaw").and_then(Value::as_f64).unwrap_or(-35.0) as f32;
            let pitch_degrees = camera.get("pitch").and_then(Value::as_f64).unwrap_or(20.0) as f32;
            let pan = camera
                .get("pan")
                .and_then(Value::as_array)
                .map(|values| Vec2::new(number(values.first()), number(values.get(1))))
                .filter(|value| value.is_finite());
            let zoom = camera
                .get("fit_relative_zoom")
                .and_then(Value::as_f64)
                .map(|value| value as f32);
            let roll_degrees = camera.get("roll").and_then(Value::as_f64).unwrap_or(0.0) as f32;
            self.camera.set_orbit_state_with_roll(
                yaw_degrees.to_radians(),
                pitch_degrees.to_radians(),
                roll_degrees.to_radians(),
                None,
                None,
            );
            if camera.get("fit_mode").and_then(Value::as_str) == Some("fit")
                && let Some((low, high)) = self.current_world_bounds()
            {
                self.camera
                    .frame_explicit_bounds_in_viewport(low, high, self.viewport_rect());
            }
            self.camera.set_orbit_state_with_roll(
                yaw_degrees.to_radians(),
                pitch_degrees.to_radians(),
                roll_degrees.to_radians(),
                None,
                zoom,
            );
            if let Some(pan) = pan {
                let target = self.camera.fit_target()
                    + self.camera.right() * pan.x
                    + self.camera.up() * pan.y;
                self.camera.set_orbit_state_with_roll(
                    yaw_degrees.to_radians(),
                    pitch_degrees.to_radians(),
                    roll_degrees.to_radians(),
                    Some(target),
                    None,
                );
            }
        }
        self.apply_overlays();
    }

    fn apply_overlays(&mut self) {
        let normals = self
            .state
            .overlays
            .get("normals")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let bounds = self
            .state
            .overlays
            .get("bounds")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        if let Some(renderer) = &mut self.renderer {
            renderer.set_overlays(normals, bounds);
        }
        let effect_time = self.effect_time();
        self.refresh_scene_overlays(effect_time);
    }

    fn effect_time(&mut self) -> f32 {
        let paused = self
            .state
            .presentation
            .get("display")
            .and_then(|display| display.get("effect_particles_paused"))
            .and_then(Value::as_bool)
            .unwrap_or(false);
        self.effect_clock.sample(paused)
    }

    fn has_dynamic_effects(&self) -> bool {
        self.visible
            && self
                .state
                .presentation
                .get("display")
                .and_then(|display| display.get("effect_particles_visible"))
                .and_then(Value::as_bool)
                .unwrap_or(true)
            && self
                .state
                .scene
                .get("effects_overlay")
                .and_then(|effects| effects.get("emitters"))
                .and_then(Value::as_array)
                .is_some_and(|emitters| !emitters.is_empty())
            && !self
                .state
                .presentation
                .get("display")
                .and_then(|display| display.get("effect_particles_paused"))
                .and_then(Value::as_bool)
                .unwrap_or(false)
    }

    fn submesh_model_matrix(&self, source_submesh: u32) -> Mat4 {
        self.scene_view().submesh_model_matrix(source_submesh)
    }

    fn push_submesh_edges(
        &self,
        lines: &mut Vec<EffectLineVertex>,
        wanted: &HashSet<u32>,
        colour: [f32; 4],
    ) {
        for part in &self.geometry.parts {
            if !wanted.contains(&part.submesh) {
                continue;
            }
            let matrix = self.submesh_model_matrix(part.submesh);
            for [a, b] in &part.edges {
                if lines.len() >= 240_000 {
                    return;
                }
                push_effect_line(
                    lines,
                    matrix.transform_point3(*a),
                    matrix.transform_point3(*b),
                    colour,
                );
            }
        }
    }

    fn refresh_scene_overlays(&mut self, time: f32) {
        self.refresh_scene_overlays_for_capture(time, false);
    }

    fn refresh_scene_overlays_for_capture(&mut self, time: f32, capture: bool) {
        let editable_matrix = role_model_matrix(&self.state.scene, "editable");
        let skeleton_visible = self
            .state
            .overlays
            .get("skeleton")
            .and_then(|value| value.get("visible"))
            .and_then(Value::as_bool)
            .unwrap_or(true);
        let mut skeleton_lines = Vec::new();
        if skeleton_visible
            && let Some(bones) = self
                .state
                .scene
                .get("skeleton_overlay")
                .and_then(|value| value.get("bones"))
                .and_then(Value::as_array)
        {
            for bone in bones.iter().take(4_096) {
                let position = vec3_value(bone.get("position"), Vec3::ZERO);
                let parent = vec3_value(bone.get("parent_position"), position);
                if position != parent {
                    skeleton_lines.push(editable_matrix.transform_point3(parent).to_array());
                    skeleton_lines.push(editable_matrix.transform_point3(position).to_array());
                }
            }
        }

        let mut guide_lines = Vec::new();
        let mut emphasis_lines = Vec::new();
        let display = self
            .state
            .presentation
            .get("display")
            .unwrap_or(&Value::Null);
        let quality = display.get("quality").unwrap_or(&Value::Null);
        let guide_colours = scene_guide_colours(quality);
        if !capture
            && display
                .get("grid_visible")
                .and_then(Value::as_bool)
                .unwrap_or(false)
        {
            let grid = self.state.scene.get("grid").unwrap_or(&Value::Null);
            let origin = vec3_value(grid.get("origin"), Vec3::ZERO);
            let (grid_u, grid_v) = grid_plane_axes(grid);
            let spacing = grid.get("spacing").and_then(Value::as_f64).unwrap_or(0.1) as f32
                * quality
                    .get("d3d11_grid_spacing_scale")
                    .and_then(Value::as_f64)
                    .unwrap_or(1.0) as f32;
            let count = quality
                .get("d3d11_grid_line_count")
                .and_then(Value::as_u64)
                .and_then(|value| i32::try_from(value).ok())
                .unwrap_or(10)
                .clamp(2, 100);
            let radius = spacing.max(0.001) * count as f32;
            for index in -count..=count {
                let offset = spacing * index as f32;
                let colour = if index == 0 {
                    guide_colours.grid_major
                } else {
                    guide_colours.grid
                };
                push_effect_line(
                    &mut guide_lines,
                    origin - grid_u * radius + grid_v * offset,
                    origin + grid_u * radius + grid_v * offset,
                    colour,
                );
                push_effect_line(
                    &mut guide_lines,
                    origin + grid_u * offset - grid_v * radius,
                    origin + grid_u * offset + grid_v * radius,
                    colour,
                );
            }
        }

        let cloth_state = self.state.overlays.get("cloth").unwrap_or(&Value::Null);
        if cloth_state
            .get("enabled")
            .and_then(Value::as_bool)
            .unwrap_or(false)
            && let Some(cloth) = self.state.scene.get("cloth_overlay")
        {
            let particles = cloth
                .get("particles")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            let wind = cloth_state
                .get("wind_strength")
                .and_then(Value::as_f64)
                .unwrap_or(0.0) as f32;
            let paused = cloth_state
                .get("paused")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            let cloth_time = if paused { 0.0 } else { time };
            if let Some(constraints) = cloth.get("constraints").and_then(Value::as_array) {
                for constraint in constraints.iter().take(65_536) {
                    let Some(pair) = constraint.as_array().filter(|pair| pair.len() >= 2) else {
                        continue;
                    };
                    let points = pair
                        .iter()
                        .take(2)
                        .filter_map(Value::as_u64)
                        .filter_map(|index| {
                            particles.get(index as usize).map(|value| {
                                let mut point = vec3_value(Some(value), Vec3::ZERO);
                                point.x +=
                                    (cloth_time * 1.7 + index as f32 * 0.37).sin() * wind * 0.002;
                                editable_matrix.transform_point3(point).to_array()
                            })
                        })
                        .collect::<Vec<_>>();
                    if points.len() == 2 {
                        push_effect_line(
                            &mut guide_lines,
                            Vec3::from_array(points[0]),
                            Vec3::from_array(points[1]),
                            guide_colours.cloth,
                        );
                    }
                }
            }
        }

        let gizmo_visible = display
            .get("gizmo_visible")
            .and_then(Value::as_bool)
            .unwrap_or(false)
            && self
                .state
                .scene
                .get("gizmo")
                .and_then(|value| value.get("visible"))
                .and_then(Value::as_bool)
                .unwrap_or(true);
        if gizmo_visible && !capture {
            let pivot = vec3_value(self.state.scene.get("placement_pivot"), Vec3::ZERO);

            let selected = self
                .gizmo_drag
                .as_ref()
                .map(|drag| drag.handle.as_str())
                .or(self.hovered_gizmo_handle.as_deref());
            push_transform_gizmo(
                &mut emphasis_lines,
                pivot,
                self.gizmo_length(),
                self.camera.right(),
                self.camera.up(),
                &self.gizmo_tool(),
                selected,
                guide_colours.gizmo,
                guide_colours.highlight,
                self.gizmo_dimensions(),
                quality
                    .get("gizmo_label_color")
                    .and_then(Value::as_str)
                    .and_then(parse_color),
            );
        }

        let navigator_center = self.navigator_center();
        let rectangle = self.viewport_rect();
        if !capture
            && let Some(anchor) =
                self.camera
                    .point_on_view_plane(navigator_center, self.camera.target(), rectangle)
        {
            let length = self.camera.world_units_per_pixel(rectangle) * 28.0 * self.ui_scale();
            push_camera_navigator(
                &mut emphasis_lines,
                anchor,
                length,
                self.camera.right(),
                self.camera.up(),
                guide_colours.gizmo,
            );
        }

        let comparison_mode = self
            .state
            .presentation
            .get("comparison_mode")
            .and_then(Value::as_str)
            .or_else(|| {
                self.state
                    .scene
                    .get("comparison_mode")
                    .and_then(Value::as_str)
            })
            .unwrap_or("replacement_only");
        if comparison_mode == "overlay"
            && self
                .state
                .scene
                .get("reference_draw")
                .and_then(Value::as_str)
                .unwrap_or("wire")
                == "wire"
        {
            self.push_submesh_edges(
                &mut guide_lines,
                &reference_indices(&self.state.scene)
                    .intersection(&self.visible_submeshes())
                    .copied()
                    .collect(),
                guide_colours.reference,
            );
        }
        let highlighted = self
            .state
            .presentation
            .get("highlights")
            .and_then(|value| value.get("source_indices"))
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_u64)
            .filter_map(|value| u32::try_from(value).ok())
            .collect::<HashSet<_>>();
        if !highlighted.is_empty() {
            let visible = self.visible_submeshes();
            let scene_submeshes = self
                .geometry
                .parts
                .iter()
                .filter_map(|part| {
                    highlighted
                        .contains(&self.source_part_index(part.submesh))
                        .then_some(part.submesh)
                        .filter(|part| visible.contains(part))
                })
                .collect::<HashSet<_>>();
            self.push_submesh_edges(
                &mut emphasis_lines,
                &scene_submeshes,
                guide_colours.highlight,
            );
        }

        let mut effect_lines = emphasis_lines;
        let mut effect_particles = Vec::new();
        if display
            .get("effect_particles_visible")
            .and_then(Value::as_bool)
            .unwrap_or(true)
            && let Some(emitters) = self
                .state
                .scene
                .get("effects_overlay")
                .and_then(|value| value.get("emitters"))
                .and_then(Value::as_array)
        {
            const MAX_EFFECT_LINE_VERTICES: usize = 65_536;
            let framing_extent = self
                .state
                .scene
                .get("framing")
                .and_then(|value| value.get("extent"))
                .and_then(Value::as_f64)
                .map(|value| value as f32)
                .filter(|value| value.is_finite())
                .unwrap_or(1.0)
                .abs()
                .max(0.01);
            let minimum_radius = (framing_extent * 0.006).max(0.003);
            for (emitter_index, emitter) in emitters.iter().take(128).enumerate() {
                let kind = emitter
                    .get("kind")
                    .and_then(Value::as_str)
                    .unwrap_or("billboard");
                if kind == "mesh"
                    && emitter
                        .get("particle_faces")
                        .and_then(Value::as_array)
                        .is_none_or(|v| v.is_empty())
                {
                    for mut vertex in
                        effect_emitter_lines(emitter, emitter_index, time, minimum_radius)
                    {
                        if effect_lines.len() >= MAX_EFFECT_LINE_VERTICES {
                            break;
                        }
                        vertex.position = editable_matrix
                            .transform_point3(Vec3::from_array(vertex.position))
                            .to_array();
                        effect_lines.push(vertex);
                    }
                } else {
                    let texture_index = emitter
                        .get("texture")
                        .and_then(Value::as_str)
                        .and_then(|path| self.effect_texture_indices.get(path))
                        .copied()
                        .unwrap_or(0);
                    let instances = effect_emitter_billboards(
                        emitter,
                        emitter_index,
                        time,
                        minimum_radius,
                        texture_index,
                        editable_matrix,
                        self.camera.right(),
                        self.camera.up(),
                        self.camera.forward(),
                    );
                    let faces_per_particle = if kind == "mesh" {
                        emitter
                            .get("particle_faces")
                            .and_then(Value::as_array)
                            .map(Vec::len)
                            .unwrap_or(1)
                            .max(1)
                    } else {
                        1
                    };
                    let remaining = 32_768usize.saturating_sub(effect_particles.len());
                    let allowed = remaining / faces_per_particle * faces_per_particle;
                    for mut instance in instances.into_iter().take(allowed) {
                        let mut center = Vec3::from_array(instance.center);
                        if instance.triangle_uvs.is_some() {
                            center += (Vec3::from_array(instance.axis_right)
                                + Vec3::from_array(instance.axis_up))
                                / 3.0;
                        }
                        instance.depth = (center - self.camera.eye()).dot(self.camera.forward());
                        effect_particles.push(instance);
                    }
                }
                if effect_lines.len() >= MAX_EFFECT_LINE_VERTICES
                    || effect_particles.len() >= 32_768
                {
                    break;
                }
            }
        }

        if let Some(renderer) = &mut self.renderer {
            let _ = renderer.set_skeleton_lines(&skeleton_lines);
            renderer.set_bone_overlay(skeleton_visible && !skeleton_lines.is_empty());
            let _ = renderer.set_preview_lines(&guide_lines);
            let _ = renderer.set_effect_lines(&effect_lines);
            let _ = renderer.set_effect_particles(&effect_particles);
        }
    }

    fn apply_material_parameters(&mut self) -> Result<(), String> {
        let Some(renderer) = &mut self.renderer else {
            return Err("Preview renderer is unavailable".into());
        };
        let mut authored = Vec::new();
        let mut overrides = Vec::new();
        let lod_count = self.package.document().lods.len();
        for presentation in &self.presentations {
            let ownership = presentation_ownership(presentation, lod_count);
            authored.push((cdmw_material_preview_factors(presentation), ownership));
        }
        let groups = self
            .state
            .material_parameters
            .get("groups")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        for group in &groups {
            let indices = group
                .get("source_submesh_indices")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(Value::as_u64)
                .filter_map(|value| u32::try_from(value).ok())
                .collect::<Vec<_>>();
            if indices.is_empty() {
                continue;
            }
            let ownership = vec![indices; lod_count];
            let factors = MaterialPreviewFactors {
                roughness: optional_f32(group, "roughness"),
                metalness: optional_f32(group, "metalness"),
                specular: optional_f32(group, "specular"),
                height_scale: optional_f32(group, "height_scale"),
                base_tint_strength: optional_f32(group, "base_tint_strength"),
                texture_tint: color3(group.get("texture_tint")),
                emissive_color: color3(group.get("emissive_color")),
                emissive_intensity: optional_f32(group, "emissive_intensity"),
                ..MaterialPreviewFactors::default()
            };
            if factors != MaterialPreviewFactors::default() {
                overrides.push((factors, ownership));
            }
        }
        let lod = self.package.source_lod_index();
        let factors = cdmw_render_wgpu::preview_material_factors(&authored, &overrides, lod)
            .map_err(|e| e.to_string())?;
        renderer
            .replace_material_factors(&factors, lod)
            .map_err(|e| e.to_string())
    }

    fn rebuild_working_mesh(&mut self) -> std::result::Result<(), String> {
        self.mesh = WorkingMesh::from_document_lod(&self.document, self.package.source_lod_index())
            .map_err(|error| error.to_string())?;
        self.geometry = PreviewGeometry::from_mesh(&self.mesh);
        self.scene_revision = self.scene_revision.saturating_add(1);
        self.refresh_visible_snapshot();
        Ok(())
    }

    fn document_submesh_mut(&mut self, source_index: usize) -> Option<&mut Submesh> {
        self.document
            .lods
            .get_mut(self.package.source_lod_index())?
            .submeshes
            .get_mut(source_index)
    }

    fn ensure_document_submesh(
        &mut self,
        source_index: usize,
        group: &Value,
    ) -> Option<&mut Submesh> {
        let lod = self
            .document
            .lods
            .get_mut(self.package.source_lod_index())?;
        while lod.submeshes.len() <= source_index {
            let index = lod.submeshes.len();
            lod.submeshes.push(Submesh {
                name: format!("preview_part_{index}"),
                material: format!("preview_material_{index}"),
                positions: Vec::new(),
                normals: Vec::new(),
                uvs: Vec::new(),
                source_vertex_indices: Vec::new(),
                indices: Vec::new(),
                source_range: SourceRange {
                    offset: 0,
                    length: 0,
                },
                vertex_stride: 0,
                layout: "rust_preview_dynamic".to_owned(),
            });
        }
        let submesh = lod.submeshes.get_mut(source_index)?;
        if let Some(name) = group.get("part_name").and_then(Value::as_str) {
            submesh.name = name.to_owned();
        }
        if let Some(material) = group.get("material_name").and_then(Value::as_str) {
            submesh.material = material.to_owned();
        }
        Some(submesh)
    }

    fn apply_vertex_update(&mut self, value: &Value) -> std::result::Result<usize, String> {
        let groups = value
            .get("groups")
            .and_then(Value::as_array)
            .ok_or_else(|| "vertex update groups are missing".to_owned())?;
        let mut changed = 0usize;
        for group in groups {
            let source_index = json_index(group, "source_submesh_index")?;
            let positions = numeric_values(group, "positions", "positions_binary", 3, "f64")?;
            if positions.is_empty() {
                continue;
            }
            let indices = group_indices(group, "source_vertex", positions.len() / 3)?;
            if indices.len().saturating_mul(3) != positions.len() {
                return Err("vertex update position count does not match source indices".to_owned());
            }
            let normals = numeric_values(group, "normals", "normals_binary", 3, "f64")?;
            let uvs = numeric_values(group, "uvs", "uvs_binary", 2, "f64")?;
            let has_normals = normals.len() == indices.len().saturating_mul(3);
            let has_uvs = uvs.len() == indices.len().saturating_mul(2);
            let submesh = self
                .document_submesh_mut(source_index)
                .ok_or_else(|| format!("vertex update submesh {source_index} is out of range"))?;
            for (row, vertex_index) in indices.into_iter().enumerate() {
                let position = [
                    positions[row * 3],
                    positions[row * 3 + 1],
                    positions[row * 3 + 2],
                ];
                if position.iter().any(|value| !value.is_finite()) {
                    return Err("vertex update contains a non-finite position".to_owned());
                }
                let target = submesh
                    .positions
                    .get_mut(vertex_index)
                    .ok_or_else(|| format!("vertex update index {vertex_index} is out of range"))?;
                *target = position;
                if has_normals && let Some(target) = submesh.normals.get_mut(vertex_index) {
                    *target = [normals[row * 3], normals[row * 3 + 1], normals[row * 3 + 2]];
                }
                if has_uvs && let Some(target) = submesh.uvs.get_mut(vertex_index) {
                    *target = [uvs[row * 2], uvs[row * 2 + 1]];
                }
                changed = changed.saturating_add(1);
            }
        }
        if changed > 0 {
            self.rebuild_working_mesh()?;
        }
        Ok(changed)
    }

    fn apply_triangle_update(&mut self, value: &Value) -> std::result::Result<usize, String> {
        let groups = value
            .get("groups")
            .and_then(Value::as_array)
            .ok_or_else(|| "triangle update groups are missing".to_owned())?;
        let mut updated = HashSet::new();
        let mut changed = 0usize;
        for group in groups {
            let source_index = json_index(group, "source_submesh_index")?;
            let positions = numeric_values(group, "positions", "positions_binary", 3, "f64")?;
            let normals = numeric_values(group, "normals", "normals_binary", 3, "f64")?;
            let uvs = numeric_values(group, "uvs", "uvs_binary", 2, "f64")?;
            let indices = integer_values(group, "indices", "indices_binary")?;
            if !indices.len().is_multiple_of(3) {
                return Err("triangle update index count is not divisible by three".to_owned());
            }
            let source_vertices = if positions.is_empty() {
                Vec::new()
            } else {
                group_indices(group, "source_vertex", positions.len() / 3)?
            };
            let submesh = self
                .ensure_document_submesh(source_index, group)
                .ok_or_else(|| "triangle update has no editable LOD".to_owned())?;
            if positions.is_empty() {
                submesh.positions.clear();
                submesh.normals.clear();
                submesh.uvs.clear();
                submesh.source_vertex_indices.clear();
                submesh.indices.clear();
            } else {
                if source_vertices.len().saturating_mul(3) != positions.len() {
                    return Err(
                        "triangle update position count does not match source indices".to_owned(),
                    );
                }
                submesh.positions = positions
                    .chunks_exact(3)
                    .map(|row| [row[0], row[1], row[2]])
                    .collect();
                submesh.normals = if normals.len() == submesh.positions.len().saturating_mul(3) {
                    normals
                        .chunks_exact(3)
                        .map(|row| [row[0], row[1], row[2]])
                        .collect()
                } else {
                    vec![[0.0, 1.0, 0.0]; submesh.positions.len()]
                };
                submesh.uvs = if uvs.len() == submesh.positions.len().saturating_mul(2) {
                    uvs.chunks_exact(2).map(|row| [row[0], row[1]]).collect()
                } else {
                    vec![[0.0, 0.0]; submesh.positions.len()]
                };
                submesh.source_vertex_indices = source_vertices
                    .into_iter()
                    .map(|index| i32::try_from(index).unwrap_or(i32::MAX))
                    .collect();
                submesh.indices = indices
                    .into_iter()
                    .map(|index| {
                        u32::try_from(index).map_err(|_| "triangle index exceeds u32".to_owned())
                    })
                    .collect::<std::result::Result<Vec<_>, _>>()?;
            }
            changed = changed.saturating_add(submesh.indices.len() / 3);
            updated.insert(source_index);
        }
        if value
            .get("replace_all")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            let listed = value
                .get("source_submesh_indices")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(Value::as_u64)
                .filter_map(|value| usize::try_from(value).ok())
                .collect::<HashSet<_>>();
            if let Some(lod) = self.document.lods.get_mut(self.package.source_lod_index()) {
                for (index, submesh) in lod.submeshes.iter_mut().enumerate() {
                    if (listed.contains(&index) || listed.is_empty()) && !updated.contains(&index) {
                        submesh.positions.clear();
                        submesh.normals.clear();
                        submesh.uvs.clear();
                        submesh.source_vertex_indices.clear();
                        submesh.indices.clear();
                    }
                }
            }
        }
        self.rebuild_working_mesh()?;
        Ok(changed)
    }

    fn apply_selection_update(&mut self, value: &Value) -> std::result::Result<usize, String> {
        let groups = value
            .get("selection")
            .and_then(|selection| selection.get("groups"))
            .or_else(|| value.get("groups"))
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let mut wanted_vertices: HashMap<u32, HashSet<u32>> = HashMap::new();
        let mut wanted_faces: HashMap<u32, HashSet<u32>> = HashMap::new();
        let mut wanted_submeshes = HashSet::new();
        for group in &groups {
            let submesh = u32::try_from(json_index(group, "source_submesh_index")?)
                .map_err(|_| "selection submesh exceeds u32".to_owned())?;
            if group
                .get("source_selected")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            {
                wanted_submeshes.insert(submesh);
            }
            wanted_vertices.insert(
                submesh,
                group_indices(group, "source_vertex", 0)?
                    .into_iter()
                    .filter_map(|value| u32::try_from(value).ok())
                    .collect(),
            );
            wanted_faces.insert(
                submesh,
                group_indices(group, "source_face", 0)?
                    .into_iter()
                    .filter_map(|value| u32::try_from(value).ok())
                    .collect(),
            );
        }
        let mut selection = Selection {
            submeshes: wanted_submeshes,
            ..Selection::default()
        };
        for (handle, vertex) in self.mesh.vertices() {
            if let Provenance::Source { submesh, element } = vertex.provenance
                && wanted_vertices
                    .get(&submesh)
                    .is_some_and(|values| values.contains(&element))
            {
                selection.vertices.insert(handle);
            }
        }
        for (handle, face) in self.mesh.faces() {
            if let Provenance::Source { submesh, element } = face.provenance
                && wanted_faces
                    .get(&submesh)
                    .is_some_and(|values| values.contains(&element))
            {
                selection.faces.insert(handle);
            }
        }
        let changed = selection.vertices.len() + selection.faces.len() + selection.submeshes.len();
        self.mesh
            .set_selection(selection)
            .map_err(|error| error.to_string())?;
        self.scene_revision = self.scene_revision.saturating_add(1);
        self.refresh_visible_snapshot();
        Ok(changed)
    }

    fn scene_view(&self) -> crate::preview_geometry::SceneView<'_> {
        crate::preview_geometry::SceneView {
            scene: &self.state.scene,
            presentation: &self.state.presentation,
            geometry: &self.geometry,
        }
    }

    fn refresh_visible_snapshot(&mut self) {
        (self.snapshot, self.snapshot_scene_roles) = crate::preview_geometry::prepare_snapshot(
            &self.mesh,
            &self.geometry,
            &self.state.scene,
            &self.state.presentation,
            &self.package.manifest().interaction_profile,
            self.scene_revision,
        );
        if let Some(renderer) = &mut self.renderer {
            if let Some(roles) = self.snapshot_scene_roles.as_deref() {
                let _ = renderer.set_snapshot_with_scene_roles(&self.snapshot, roles);
                let _ =
                    renderer.set_scene_transform(role_model_matrix(&self.state.scene, "editable"));
            } else {
                let _ = renderer.set_snapshot(&self.snapshot);
                let _ = renderer.set_scene_transform(Mat4::IDENTITY);
            }
        }
    }

    fn emit_view_state(&self, reason: &str) {
        let (yaw, pitch, target, distance) = self.camera.orbit_state();
        let pan_delta = target - self.camera.fit_target();
        let pan = [
            pan_delta.dot(self.camera.right()),
            pan_delta.dot(self.camera.up()),
        ];
        self.bridge.send(json!({
            "event": "view_state_changed",
            "reason": reason,
            "active_camera_context": "editable",
            "view_contexts": [{
                "id": "editable",
                "camera": {
                    "yaw_degrees": yaw.to_degrees(),
                    "pitch_degrees": pitch.to_degrees(),
                    "roll_degrees": self.camera.roll().to_degrees(),
                    "pan": pan,
                    "fit_relative_zoom": self.camera.relative_zoom(),
                    "fit_mode": "manual",
                    "distance": distance,
                }
            }],
        }));
    }

    fn part_picking_enabled(&self) -> bool {
        self.state
            .presentation
            .get("display")
            .and_then(|value| value.get("part_pick_enabled"))
            .and_then(Value::as_bool)
            .unwrap_or(false)
    }

    fn visible_submeshes(&self) -> HashSet<u32> {
        self.scene_view().visible_submeshes()
    }

    fn pick_part(&self, point: Vec2) -> Option<u32> {
        let (origin, direction, maximum) = self.camera.screen_ray(point, self.viewport_rect())?;
        self.geometry.pick(
            origin,
            direction,
            maximum,
            &self.visible_submeshes(),
            |part| self.submesh_model_matrix(part),
        )
    }

    fn source_part_index(&self, scene_submesh: u32) -> u32 {
        self.scene_view().source_part_index(scene_submesh)
    }

    fn emit_part_pick(&self, phase: &str, point: Vec2, part: Option<u32>) {
        let source = part.map(|value| self.source_part_index(value));
        self.bridge.send(json!({
            "event": "part_pick_result",
            "phase": phase,
            "source_indices": source.into_iter().collect::<Vec<_>>(),
            "scene_submesh_index": part,
            "x": point.x.round() as i64,
            "y": point.y.round() as i64,
        }));
    }

    fn gizmo_visible(&self) -> bool {
        self.package.manifest().interaction_profile == "static_replacement"
            && self
                .state
                .presentation
                .get("display")
                .and_then(|display| display.get("gizmo_visible"))
                .and_then(Value::as_bool)
                .unwrap_or(false)
            && self
                .state
                .scene
                .get("gizmo")
                .and_then(|gizmo| gizmo.get("visible"))
                .and_then(Value::as_bool)
                .unwrap_or(true)
    }

    fn ui_scale(&self) -> f32 {
        self.window
            .as_ref()
            .map(|window| window.scale_factor() as f32)
            .filter(|value| value.is_finite())
            .unwrap_or(1.0)
            .clamp(0.75, 4.0)
    }

    fn gizmo_tool(&self) -> String {
        self.state
            .scene
            .get("gizmo")
            .and_then(|gizmo| gizmo.get("tool"))
            .and_then(Value::as_str)
            .filter(|tool| matches!(*tool, "move" | "rotate" | "scale"))
            .unwrap_or("move")
            .to_owned()
    }

    fn gizmo_length(&self) -> f32 {
        let scale = self.state.presentation["display"]["quality"]["gizmo_size_scale"]
            .as_f64()
            .unwrap_or(1.0)
            .clamp(0.5, 3.0) as f32;
        self.camera.world_units_per_pixel(self.viewport_rect()) * 88.0 * self.ui_scale() * scale
    }

    fn gizmo_dimensions(&self) -> [f32; 3] {
        let quality = &self.state.presentation["display"]["quality"];
        let pixel = self.camera.world_units_per_pixel(self.viewport_rect())
            * self.ui_scale()
            * quality_number(quality, "gizmo_size_scale", 1.0, 0.5, 3.0);
        [
            quality_number(quality, "gizmo_line_thickness_pixels", 1.0, 0.5, 8.0) * pixel,
            quality_number(quality, "gizmo_handle_size_pixels", 8.0, 3.0, 40.0) * pixel,
            quality_number(quality, "gizmo_label_size_pixels", 12.0, 6.0, 48.0) * pixel * 0.5,
        ]
    }

    fn gizmo_handle_at(&self, point: Vec2) -> Option<String> {
        if !self.gizmo_visible() || !point.is_finite() {
            return None;
        }
        let rectangle = self.viewport_rect();
        let pivot = vec3_value(self.state.scene.get("placement_pivot"), Vec3::ZERO);
        let pivot_screen = self.camera.project(pivot, rectangle)?.screen;
        let scale = self.ui_scale();
        let handle = self.gizmo_dimensions()[1] / self.camera.world_units_per_pixel(rectangle);
        let threshold = (handle + 4.0 * scale).max(12.0 * scale);
        if pivot_screen.distance(point) <= handle + 3.0 * scale {
            return Some("center".to_owned());
        }
        let length = self.gizmo_length();
        let axes = [("x", Vec3::X), ("y", Vec3::Y), ("z", Vec3::Z)];
        let tool = self.gizmo_tool();
        let mut best: Option<(f32, String)> = None;
        let mut consider = |distance: f32, handle: &str| {
            if distance <= threshold && best.as_ref().is_none_or(|(value, _)| distance < *value) {
                best = Some((distance, handle.to_owned()));
            }
        };
        if tool == "rotate" {
            for (label, axis) in axes {
                let (u, v) = axis_plane_basis(axis);
                let mut previous = None;
                for step in 0..=64 {
                    let angle = std::f32::consts::TAU * step as f32 / 64.0;
                    let world = pivot + (u * angle.cos() + v * angle.sin()) * length * 0.78;
                    let current = self
                        .camera
                        .project(world, rectangle)
                        .map(|value| value.screen);
                    if let (Some(a), Some(b)) = (previous, current) {
                        consider(screen_segment_distance(point, a, b), label);
                    }
                    previous = current;
                }
            }
            return best.map(|(_, handle)| handle);
        }
        for (label, axis) in axes {
            if let Some(end) = self
                .camera
                .project(pivot + axis * length, rectangle)
                .map(|value| value.screen)
            {
                consider(screen_segment_distance(point, pivot_screen, end), label);
            }
        }
        if tool == "move" {
            for (label, first, second) in [
                ("xy", Vec3::X, Vec3::Y),
                ("xz", Vec3::X, Vec3::Z),
                ("yz", Vec3::Y, Vec3::Z),
            ] {
                let center = pivot + (first + second) * length * 0.28;
                if let Some(projected) = self.camera.project(center, rectangle) {
                    consider(projected.screen.distance(point), label);
                }
            }
        }
        best.map(|(_, handle)| handle)
    }

    fn navigator_center(&self) -> Vec2 {
        let rectangle = self.viewport_rect();
        let inset = 58.0 * self.ui_scale();
        Vec2::new(rectangle.right() - inset, rectangle.top() + inset)
    }

    fn navigator_view_at(&self, point: Vec2) -> Option<StandardView> {
        if !point.is_finite() {
            return None;
        }
        let rectangle = self.viewport_rect();
        let center = self.navigator_center();
        let anchor = self
            .camera
            .point_on_view_plane(center, self.camera.target(), rectangle)?;
        let length = self.camera.world_units_per_pixel(rectangle) * 28.0 * self.ui_scale();
        let mut best: Option<(f32, StandardView)> = None;
        for (axis, positive, negative) in [
            (Vec3::X, StandardView::Right, StandardView::Left),
            (Vec3::Y, StandardView::Top, StandardView::Bottom),
            (Vec3::Z, StandardView::Back, StandardView::Front),
        ] {
            for (endpoint, view) in [
                (anchor + axis * length, positive),
                (anchor - axis * length, negative),
            ] {
                if let Some(projected) = self.camera.project(endpoint, rectangle) {
                    let distance = projected.screen.distance(point);
                    if distance <= 13.0 * self.ui_scale()
                        && best.as_ref().is_none_or(|(current, _)| distance < *current)
                    {
                        best = Some((distance, view));
                    }
                }
            }
        }
        best.map(|(_, view)| view)
    }

    fn navigator_hit(&self, point: Vec2) -> bool {
        point.is_finite() && point.distance(self.navigator_center()) <= 48.0 * self.ui_scale()
    }

    fn placement_payload(&self) -> Value {
        self.state
            .scene
            .get("placement")
            .cloned()
            .unwrap_or_else(|| {
                json!({
                    "translation": [0.0, 0.0, 0.0],
                    "rotation_degrees": [0.0, 0.0, 0.0],
                    "scale": [1.0, 1.0, 1.0],
                })
            })
    }

    fn emit_gizmo(&self, phase: &str, tool: &str, handle: &str, placement: &Value) {
        self.bridge.send(json!({
            "event": "placement_transform_request",
            "placement": placement,
            "placement_phase": phase,
            "gizmo_tool": tool,
            "gizmo_handle": handle,
        }));
    }

    fn begin_gizmo_drag(&mut self, point: Vec2) -> bool {
        let Some(handle) = self.gizmo_handle_at(point) else {
            return false;
        };
        let tool = self.gizmo_tool();
        let start_placement = self.placement_payload();
        let start_pivot = vec3_value(self.state.scene.get("placement_pivot"), Vec3::ZERO);
        self.emit_gizmo("begin", &tool, &handle, &start_placement);
        self.gizmo_drag = Some(GizmoDrag {
            tool,
            handle,
            start_pointer: point,
            start_placement,
            start_model_matrix: role_model_matrix(&self.state.scene, "editable"),
            start_pivot,
        });
        true
    }

    fn cancel_gesture(&mut self) {
        self.pending_gizmo_update = None;
        if let Some(drag) = self.gizmo_drag.take() {
            self.scene_revision = self.scene_revision.saturating_add(1);
            self.state.scene["placement"] = drag.start_placement.clone();
            self.state.scene["placement_pivot"] = json!(drag.start_pivot.to_array());
            self.state.scene["roles"]["editable"]["model_matrix"] =
                json!(drag.start_model_matrix.to_cols_array());
            if self.snapshot_scene_roles.is_some() {
                if let Some(renderer) = &mut self.renderer {
                    let _ = renderer.set_scene_transform(drag.start_model_matrix);
                }
            } else {
                self.refresh_visible_snapshot();
            }
            self.emit_gizmo("cancel", &drag.tool, &drag.handle, &drag.start_placement);
        }
        self.navigator_drag = None;
        self.orbiting = false;
        self.panning = false;
        self.left_camera_drag = false;
        self.right_press = None;
        self.hovered_gizmo_handle = None;
    }

    fn camera_drag(&mut self, delta: Vec2) {
        let quality = &self.state.presentation["display"]["quality"];
        if self.orbiting {
            let sensitivity = quality_number(quality, "orbit_sensitivity", 0.22, 0.001, 10.0)
                .to_radians()
                / 0.008;
            let x = if quality["invert_orbit_x"].as_bool() == Some(true) {
                -1.0
            } else {
                1.0
            };
            let y = if quality["invert_orbit_y"].as_bool() == Some(true) {
                -1.0
            } else {
                1.0
            };
            self.camera.orbit(delta * Vec2::new(x, y) * sensitivity);
        }
        if self.panning {
            let sensitivity = quality["pan_sensitivity"]
                .as_f64()
                .unwrap_or(0.60)
                .clamp(0.001, 10.0) as f32
                / 0.60;
            let x = if quality["invert_pan_x"].as_bool() == Some(true) {
                -1.0
            } else {
                1.0
            };
            let y = if quality["invert_pan_y"].as_bool() == Some(true) {
                -1.0
            } else {
                1.0
            };
            self.camera
                .pan(delta * Vec2::new(x, y) * sensitivity, self.viewport_rect());
        }
    }

    fn update_gizmo_drag(&mut self, point: Vec2, phase: &str) -> bool {
        let Some(drag) = self.gizmo_drag.clone() else {
            return false;
        };
        let delta = point - drag.start_pointer;
        let mut placement = drag.start_placement.clone();
        let pivot = drag.start_pivot;
        match drag.tool.as_str() {
            "rotate" => {
                let start = vec3_value(placement.get("rotation_degrees"), Vec3::ZERO);
                let amount = (delta.x - delta.y) * 0.22;
                let axis = handle_axis(&drag.handle).unwrap_or(Vec3::Z);
                let degrees = axis * amount;
                placement["rotation_degrees"] = json!((start + degrees).to_array());
            }
            "scale" => {
                let start = vec3_value(
                    placement
                        .get("scale")
                        .or_else(|| placement.get("scale_xyz")),
                    Vec3::ONE,
                );
                let factor = (delta.x - delta.y).mul_add(0.006, 1.0).clamp(0.01, 100.0);
                let scale_delta = match drag.handle.as_str() {
                    "x" => Vec3::new(factor, 1.0, 1.0),
                    "y" => Vec3::new(1.0, factor, 1.0),
                    "z" => Vec3::new(1.0, 1.0, factor),
                    _ => Vec3::splat(factor),
                };
                placement["scale"] = json!((start * scale_delta).to_array());
            }
            _ => {
                let start = vec3_value(placement.get("translation"), Vec3::ZERO);
                let movement = match drag.handle.as_str() {
                    "x" | "y" | "z" => self.camera.axis_drag_delta(
                        handle_axis(&drag.handle).unwrap_or(Vec3::X),
                        pivot,
                        delta,
                        self.viewport_rect(),
                    ),
                    "xy" | "xz" | "yz" => {
                        let normal = match drag.handle.as_str() {
                            "xy" => Vec3::Z,
                            "xz" => Vec3::Y,
                            _ => Vec3::X,
                        };
                        self.camera.plane_drag_delta(
                            normal,
                            pivot,
                            drag.start_pointer,
                            point,
                            self.viewport_rect(),
                        )
                    }
                    _ => self
                        .camera
                        .screen_delta_to_world(delta, self.viewport_rect()),
                };
                placement["translation"] = json!((start + movement).to_array());
            }
        }
        let (model_matrix, pivot) = placed_scene(&self.state.scene, &placement);
        if let Some(scene) = self.state.scene.as_object_mut() {
            scene.insert("placement".to_owned(), placement.clone());
            scene.insert("placement_pivot".to_owned(), json!(pivot.to_array()));
            if let Some(editable) = scene
                .get_mut("roles")
                .and_then(Value::as_object_mut)
                .and_then(|roles| roles.get_mut("editable"))
                .and_then(Value::as_object_mut)
            {
                editable.insert(
                    "model_matrix".to_owned(),
                    json!(model_matrix.to_cols_array()),
                );
            }
        }
        self.scene_revision = self.scene_revision.saturating_add(1);
        if self.snapshot_scene_roles.is_some() {
            if let Some(renderer) = &mut self.renderer {
                let _ = renderer.set_scene_transform(model_matrix);
            }
        } else {
            self.refresh_visible_snapshot();
        }
        if phase == "end" {
            self.pending_gizmo_update = None;
            self.emit_gizmo("end", &drag.tool, &drag.handle, &placement);
        } else {
            self.pending_gizmo_update = Some(PendingGizmoUpdate {
                tool: drag.tool,
                handle: drag.handle,
                placement,
            });
        }
        true
    }
}

impl ApplicationHandler for PreviewApplication {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if self.window.is_some() {
            return;
        }
        let attributes = match cdmw_win32_embed::with_parent_window(
            WindowAttributes::default()
                .with_title("CDMW — Rust Preview")
                .with_decorations(false)
                .with_visible(false),
            self.parent_hwnd,
        ) {
            Ok(attributes) => attributes,
            Err(error) => {
                self.bridge
                    .send(json!({"event": "error", "error": error.to_string()}));
                self.exit_requested = true;
                return;
            }
        };
        let window = match event_loop.create_window(attributes) {
            Ok(window) => Arc::new(window),
            Err(error) => {
                self.bridge
                    .send(json!({"event": "error", "error": error.to_string()}));
                self.exit_requested = true;
                return;
            }
        };
        let renderer = match pollster::block_on(WindowRenderer::new(window.clone())) {
            Ok(renderer) => renderer,
            Err(error) => {
                self.bridge
                    .send(json!({"event": "error", "error": error.to_string()}));
                self.exit_requested = true;
                return;
            }
        };
        let adapter = renderer.adapter_report().name;
        self.renderer = Some(renderer);
        self.window = Some(window.clone());
        if let Err(error) = self.configure_renderer() {
            self.bridge.send(json!({"event": "error", "error": error}));
            self.exit_requested = true;
            return;
        }
        let has_explicit_camera = self.state.presentation.get("camera").is_some();
        self.apply_presentation(has_explicit_camera);
        if !has_explicit_camera {
            // The package was opened before the native child had its real
            // dimensions. Refit the semantic view once against that viewport.
            self.apply_canonical_view(false);
        }
        let child_hwnd = cdmw_win32_embed::window_hwnd(window.as_ref()).unwrap_or(0);
        self.bridge.announce(child_hwnd, self.parent_hwnd, &adapter);
        window.request_redraw();
    }

    fn window_event(
        &mut self,
        event_loop: &ActiveEventLoop,
        window_id: WindowId,
        event: WindowEvent,
    ) {
        let Some(window) = self
            .window
            .as_ref()
            .filter(|window| window.id() == window_id)
            .cloned()
        else {
            return;
        };
        match event {
            WindowEvent::ModifiersChanged(modifiers) => self.modifiers = modifiers.state(),
            WindowEvent::CloseRequested => self.exit_requested = true,
            WindowEvent::Focused(false) => {
                self.cancel_gesture();
                window.request_redraw();
            }
            WindowEvent::KeyboardInput { event, .. }
                if event.state == ElementState::Pressed
                    && event.logical_key == Key::Named(NamedKey::Escape) =>
            {
                self.cancel_gesture();
                window.request_redraw();
            }
            WindowEvent::Resized(size) => {
                self.cancel_gesture();
                if let Some(renderer) = &mut self.renderer {
                    renderer.resize(size);
                }
                window.request_redraw();
            }
            WindowEvent::CursorMoved { position, .. } => {
                let current = Vec2::new(position.x as f32, position.y as f32);
                if let Some(mut drag) = self.navigator_drag.take() {
                    let delta = current - drag.last_pointer;
                    if delta.length_squared() > 0.0 {
                        self.camera.orbit(delta);
                        drag.moved |= current.distance(drag.start_pointer) > 4.0 * self.ui_scale();
                    }
                    drag.last_pointer = current;
                    self.navigator_drag = Some(drag);
                    self.pointer = Some(current);
                    window.request_redraw();
                    return;
                }
                if self.gizmo_drag.is_some() && self.update_gizmo_drag(current, "update") {
                    self.pointer = Some(current);
                    window.request_redraw();
                    return;
                }
                if let Some(previous) = self.pointer {
                    let delta = current - previous;
                    self.camera_drag(delta);
                    if self.orbiting || self.panning {
                        window.request_redraw();
                    }
                }
                self.pointer = Some(current);
                if !self.orbiting && !self.panning {
                    let hovered = self.gizmo_handle_at(current);
                    if hovered != self.hovered_gizmo_handle {
                        self.hovered_gizmo_handle = hovered;
                        window.request_redraw();
                    }
                }
                if self.part_picking_enabled() && !self.orbiting && !self.panning {
                    let part = self.pick_part(current);
                    if part != self.hovered_part {
                        self.hovered_part = part;
                        self.emit_part_pick("hover", current, part);
                    }
                }
            }
            WindowEvent::MouseInput { state, button, .. } => match (state, button) {
                (ElementState::Pressed, MouseButton::Left) => {
                    let quality = &self.state.presentation["display"]["quality"];
                    let pan = camera_modifier_matches(
                        quality["camera_pan_modifier"].as_str().unwrap_or("shift"),
                        self.modifiers,
                    );
                    let orbit = camera_modifier_matches(
                        quality["camera_orbit_modifier"]
                            .as_str()
                            .unwrap_or("alt_or_ctrl"),
                        self.modifiers,
                    );
                    if pan || orbit {
                        self.panning = pan;
                        self.orbiting = !pan && orbit;
                        self.left_camera_drag = true;
                    } else if let Some(point) = self.pointer
                        && self.navigator_hit(point)
                    {
                        self.navigator_drag = Some(NavigatorDrag {
                            start_pointer: point,
                            last_pointer: point,
                            moved: false,
                        });
                        window.request_redraw();
                    } else if let Some(point) = self.pointer
                        && self.begin_gizmo_drag(point)
                    {
                        window.request_redraw();
                    } else if self.part_picking_enabled()
                        && let Some(point) = self.pointer
                    {
                        self.emit_part_pick("select", point, self.pick_part(point));
                    }
                }
                (ElementState::Released, MouseButton::Left) => {
                    if self.left_camera_drag {
                        self.left_camera_drag = false;
                        self.panning = false;
                        self.orbiting = false;
                        self.emit_view_state("camera");
                    } else if let Some(drag) = self.navigator_drag.take() {
                        if !drag.moved
                            && let Some(point) = self.pointer
                            && let Some(view) = self.navigator_view_at(point)
                        {
                            self.camera.set_standard_view(view);
                            self.emit_view_state("navigator_snap");
                        } else {
                            self.emit_view_state("navigator_orbit");
                        }
                        window.request_redraw();
                    } else if let Some(point) = self.pointer
                        && self.update_gizmo_drag(point, "end")
                    {
                        self.gizmo_drag = None;
                        window.request_redraw();
                    }
                }
                (ElementState::Pressed, MouseButton::Right) => {
                    let binding =
                        self.state.presentation["display"]["quality"]["camera_right_drag"]
                            .as_str()
                            .unwrap_or("pan");
                    self.orbiting = binding == "orbit";
                    self.panning = binding == "pan";
                    self.right_press = self.pointer;
                }
                (ElementState::Released, MouseButton::Right) => {
                    self.orbiting = false;
                    self.panning = false;
                    let context_click = self
                        .right_press
                        .zip(self.pointer)
                        .is_some_and(|(start, end)| start.distance(end) <= 4.0);
                    self.right_press = None;
                    if context_click && self.part_picking_enabled() {
                        if let Some(point) = self.pointer {
                            self.emit_part_pick("context", point, self.pick_part(point));
                        }
                    } else {
                        self.emit_view_state("orbit");
                    }
                }
                (ElementState::Pressed, MouseButton::Middle) => {
                    let binding =
                        self.state.presentation["display"]["quality"]["camera_middle_drag"]
                            .as_str()
                            .unwrap_or("pan");
                    self.orbiting = binding == "orbit";
                    self.panning = binding == "pan";
                }
                (ElementState::Released, MouseButton::Middle) => {
                    self.panning = false;
                    self.orbiting = false;
                    self.emit_view_state("pan");
                }
                _ => {}
            },
            WindowEvent::MouseWheel { delta, .. } => {
                let amount = match delta {
                    MouseScrollDelta::LineDelta(_, y) => y * 120.0,
                    MouseScrollDelta::PixelDelta(position) => position.y as f32,
                };
                self.camera.zoom(amount);
                self.emit_view_state("zoom");
                window.request_redraw();
            }
            WindowEvent::RedrawRequested => {
                if let Some(pending) = self.pending_gizmo_update.take() {
                    self.emit_gizmo("update", &pending.tool, &pending.handle, &pending.placement);
                }
                let effect_time = self.effect_time();
                self.refresh_scene_overlays(effect_time);
                let camera = self.camera.view_projection(self.viewport_rect());
                if let Some(renderer) = &mut self.renderer {
                    renderer.set_view_mode(self.view_mode);
                    renderer.set_camera_with_basis(camera, self.camera.right(), self.camera.up());
                    renderer.set_mesh_viewport(None);
                    match renderer.render() {
                        Ok(()) => {
                            self.render_failures = 0;
                            self.next_frame = None;
                        }
                        Err(cdmw_render_wgpu::RenderError::SurfaceFrame(reason))
                            if matches!(
                                reason.as_str(),
                                "timeout" | "outdated" | "lost" | "occluded"
                            ) =>
                        {
                            self.render_failures = self.render_failures.saturating_add(1);
                            if self.visible && self.render_failures <= 5 {
                                self.next_frame = Some(Instant::now() + Duration::from_millis(50));
                            } else if self.render_failures == 6 {
                                self.next_frame = None;
                                self.bridge.send(json!({"event":"error","error":format!("Preview surface failed: {reason}")}));
                            }
                        }
                        Err(error) => {
                            self.render_failures = 6;
                            self.bridge
                                .send(json!({"event":"error","error":error.to_string()}));
                            self.next_frame = None;
                        }
                    }
                }
                if self.render_failures == 0 && self.has_dynamic_effects() {
                    self.next_frame = Some(Instant::now() + Duration::from_millis(16));
                }
            }
            _ => {}
        }
        if self.exit_requested {
            event_loop.exit();
        }
    }

    fn about_to_wait(&mut self, event_loop: &ActiveEventLoop) {
        let changed = self.poll_bridge() | self.poll_package_loads();
        self.poll_captures();
        if changed && let Some(window) = &self.window {
            window.request_redraw();
        }
        if let Some(deadline) = self.next_frame
            && Instant::now() >= deadline
        {
            self.next_frame = None;
            if self.visible
                && let Some(window) = &self.window
            {
                window.request_redraw();
            }
        }
        event_loop.set_control_flow(
            self.next_frame
                .map_or(ControlFlow::Wait, ControlFlow::WaitUntil),
        );
        if self.exit_requested {
            // winit 0.30 on Windows prepares AboutToWait before entering its
            // OS wait. Make this final wait nonblocking when closing hidden.
            event_loop.set_control_flow(ControlFlow::Poll);
            event_loop.exit();
        }
    }
}

fn quality_number(quality: &Value, key: &str, default: f32, min: f32, max: f32) -> f32 {
    quality
        .get(key)
        .and_then(Value::as_f64)
        .map(|v| v as f32)
        .filter(|v| v.is_finite())
        .unwrap_or(default)
        .clamp(min, max)
}

fn camera_modifier_matches(binding: &str, modifiers: ModifiersState) -> bool {
    match binding {
        "shift" => modifiers.shift_key(),
        "ctrl" => modifiers.control_key(),
        "alt" => modifiers.alt_key(),
        "alt_or_ctrl" => modifiers.alt_key() || modifiers.control_key(),
        _ => false,
    }
}

fn merge_value(target: &mut Value, source: &Value) {
    if !target.is_object() {
        *target = Value::Object(Map::new());
    }
    let Some(target) = target.as_object_mut() else {
        return;
    };
    let Some(source) = source.as_object() else {
        return;
    };
    for (key, value) in source {
        if matches!(
            key.as_str(),
            "event" | "request_id" | "session_id" | "process_generation" | "protocol_version"
        ) {
            continue;
        }
        if value.is_object() && target.get(key).is_some_and(Value::is_object) {
            if let Some(existing) = target.get_mut(key) {
                merge_value(existing, value);
            }
        } else {
            target.insert(key.clone(), value.clone());
        }
    }
}

fn matrix_from_protocol(value: Option<&Value>) -> Mat4 {
    let Some(values) = value.and_then(Value::as_array) else {
        return Mat4::IDENTITY;
    };
    if values.len() != 16 {
        return Mat4::IDENTITY;
    }
    let mut matrix = [0.0_f32; 16];
    for (target, value) in matrix.iter_mut().zip(values) {
        let Some(component) = value.as_f64().map(|value| value as f32) else {
            return Mat4::IDENTITY;
        };
        if !component.is_finite() {
            return Mat4::IDENTITY;
        }
        *target = component;
    }
    // The Archive Preview protocol uses System.Numerics row vectors and a
    // row-major wire representation.  Interpreting those same 16 values as
    // glam columns is the required transpose for column-vector rendering.
    Mat4::from_cols_array(&matrix)
}

pub(crate) fn role_model_matrix(scene: &Value, role: &str) -> Mat4 {
    matrix_from_protocol(
        scene
            .get("roles")
            .and_then(|roles| roles.get(role))
            .and_then(|role| role.get("model_matrix")),
    )
}

fn vec3_value(value: Option<&Value>, fallback: Vec3) -> Vec3 {
    let Some(values) = value.and_then(Value::as_array) else {
        return fallback;
    };
    if values.len() < 3 {
        return fallback;
    }
    let result = Vec3::new(
        values[0].as_f64().unwrap_or(f64::from(fallback.x)) as f32,
        values[1].as_f64().unwrap_or(f64::from(fallback.y)) as f32,
        values[2].as_f64().unwrap_or(f64::from(fallback.z)) as f32,
    );
    if result.is_finite() { result } else { fallback }
}

fn json_index(value: &Value, key: &str) -> std::result::Result<usize, String> {
    value
        .get(key)
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .ok_or_else(|| format!("{key} is missing or out of range"))
}

fn flattened_numbers(value: Option<&Value>) -> std::result::Result<Vec<f32>, String> {
    let Some(values) = value.and_then(Value::as_array) else {
        return Ok(Vec::new());
    };
    let mut result = Vec::new();
    for value in values {
        if let Some(row) = value.as_array() {
            for component in row {
                let number = component
                    .as_f64()
                    .ok_or_else(|| "numeric payload contains a non-number".to_owned())?
                    as f32;
                if !number.is_finite() {
                    return Err("numeric payload contains a non-finite value".to_owned());
                }
                result.push(number);
            }
        } else {
            let number = value
                .as_f64()
                .ok_or_else(|| "numeric payload contains a non-number".to_owned())?
                as f32;
            if !number.is_finite() {
                return Err("numeric payload contains a non-finite value".to_owned());
            }
            result.push(number);
        }
    }
    Ok(result)
}

fn descriptor_bytes(
    descriptor: &Value,
    components: usize,
    expected_kind: &str,
) -> std::result::Result<(Vec<u8>, usize, String), String> {
    let path = descriptor
        .get("path")
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .map(PathBuf::from)
        .ok_or_else(|| "binary descriptor path is missing".to_owned())?;
    let count = descriptor
        .get("count")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .ok_or_else(|| "binary descriptor count is missing".to_owned())?;
    let declared_components = descriptor
        .get("components")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .unwrap_or(components);
    if declared_components != components || count > 16_777_216 {
        return Err("binary descriptor dimensions exceed preview limits".to_owned());
    }
    let kind = descriptor
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or(expected_kind)
        .to_ascii_lowercase();
    if kind != expected_kind && !(expected_kind == "f64" && kind == "f32") {
        return Err(format!("binary descriptor type {kind} is unsupported"));
    }
    let bytes_per_value = if kind == "f64" { 8 } else { 4 };
    let expected = count
        .checked_mul(components)
        .and_then(|value| value.checked_mul(bytes_per_value))
        .ok_or_else(|| "binary descriptor size overflows".to_owned())?;
    if expected > 256 * 1024 * 1024 {
        return Err("binary descriptor exceeds the 256 MiB preview limit".to_owned());
    }
    let metadata = fs::symlink_metadata(&path).map_err(|error| error.to_string())?;
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err("binary descriptor is not a regular file".to_owned());
    }
    if usize::try_from(metadata.len()).ok() != Some(expected) {
        return Err("binary descriptor byte length does not match its declaration".to_owned());
    }
    let bytes = fs::read(&path).map_err(|error| error.to_string())?;
    if descriptor
        .get("delete_after")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        let _ = fs::remove_file(path);
    }
    Ok((bytes, count, kind))
}

fn numeric_values(
    group: &Value,
    inline_key: &str,
    binary_key: &str,
    components: usize,
    kind: &str,
) -> std::result::Result<Vec<f32>, String> {
    if let Some(descriptor) = group.get(binary_key).filter(|value| value.is_object()) {
        let (bytes, count, actual_kind) = descriptor_bytes(descriptor, components, kind)?;
        let mut values = Vec::with_capacity(count.saturating_mul(components));
        if actual_kind == "f64" {
            for chunk in bytes.chunks_exact(8) {
                values.push(f64::from_le_bytes(chunk.try_into().unwrap_or([0; 8])) as f32);
            }
        } else {
            for chunk in bytes.chunks_exact(4) {
                values.push(f32::from_le_bytes(chunk.try_into().unwrap_or([0; 4])));
            }
        }
        if values.iter().any(|value| !value.is_finite()) {
            return Err("binary numeric payload contains a non-finite value".to_owned());
        }
        return Ok(values);
    }
    flattened_numbers(group.get(inline_key))
}

fn integer_values(
    group: &Value,
    inline_key: &str,
    binary_key: &str,
) -> std::result::Result<Vec<usize>, String> {
    if let Some(descriptor) = group.get(binary_key).filter(|value| value.is_object()) {
        let (bytes, count, _) = descriptor_bytes(descriptor, 1, "i32")?;
        let mut values = Vec::with_capacity(count);
        for chunk in bytes.chunks_exact(4) {
            let value = i32::from_le_bytes(chunk.try_into().unwrap_or([0; 4]));
            values.push(
                usize::try_from(value)
                    .map_err(|_| "binary index payload is negative".to_owned())?,
            );
        }
        return Ok(values);
    }
    let Some(values) = group.get(inline_key).and_then(Value::as_array) else {
        return Ok(Vec::new());
    };
    values
        .iter()
        .map(|value| {
            value
                .as_u64()
                .and_then(|value| usize::try_from(value).ok())
                .ok_or_else(|| "index payload contains an invalid value".to_owned())
        })
        .collect()
}

fn group_indices(
    group: &Value,
    prefix: &str,
    default_count: usize,
) -> std::result::Result<Vec<usize>, String> {
    let values_key = format!("{prefix}_indices");
    let binary_key = format!("{prefix}_indices_binary");
    let start_key = format!("{prefix}_start");
    let count_key = format!("{prefix}_count");
    if group.get(&binary_key).is_some_and(Value::is_object) {
        return integer_values(group, &values_key, &binary_key);
    }
    if let (Some(start), Some(count)) = (
        group.get(&start_key).and_then(Value::as_u64),
        group.get(&count_key).and_then(Value::as_u64),
    ) {
        let start =
            usize::try_from(start).map_err(|_| "index range start is too large".to_owned())?;
        let count =
            usize::try_from(count).map_err(|_| "index range count is too large".to_owned())?;
        let end = start
            .checked_add(count)
            .ok_or_else(|| "index range overflows".to_owned())?;
        if count > 16_777_216 {
            return Err("index range exceeds preview limits".to_owned());
        }
        return Ok((start..end).collect());
    }
    let explicit = integer_values(group, &values_key, &binary_key)?;
    if !explicit.is_empty() || group.get(&values_key).is_some() {
        return Ok(explicit);
    }
    Ok((0..default_count).collect())
}

fn presentation_ownership(
    presentation: &SessionMaterialPresentation,
    lod_count: usize,
) -> Vec<Vec<u32>> {
    let mut ownership = vec![Vec::new(); lod_count];
    if let Some(row) = ownership.get_mut(presentation.lod_index as usize) {
        row.push(presentation.material_index);
    }
    ownership
}

fn role_indices(scene: &Value, role: &str) -> HashSet<u32> {
    scene
        .get("roles")
        .and_then(|roles| roles.get(role))
        .and_then(|value| value.get("submesh_indices").or(Some(value)))
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_u64)
        .filter_map(|value| u32::try_from(value).ok())
        .collect()
}

pub(crate) fn editable_indices(scene: &Value) -> HashSet<u32> {
    role_indices(scene, "editable")
}
pub(crate) fn reference_indices(scene: &Value) -> HashSet<u32> {
    role_indices(scene, "reference")
}
pub(crate) fn scene_role_indices(scene: &Value) -> HashSet<u32> {
    let mut values = editable_indices(scene);
    values.extend(reference_indices(scene));
    values
}

fn number(value: Option<&Value>) -> f32 {
    value.and_then(Value::as_f64).unwrap_or(0.0) as f32
}
fn optional_f32(value: &Value, key: &str) -> Option<f32> {
    value
        .get(key)
        .and_then(Value::as_f64)
        .map(|number| number as f32)
        .filter(|number| number.is_finite())
}
fn color3(value: Option<&Value>) -> Option<[f32; 3]> {
    let values = value?.as_array()?;
    if values.len() < 3 {
        return None;
    }
    let result = [
        number(values.first()),
        number(values.get(1)),
        number(values.get(2)),
    ];
    result
        .iter()
        .all(|value| value.is_finite())
        .then_some(result)
}
fn parse_color(value: &str) -> Option<[f32; 4]> {
    let value = value.trim().strip_prefix('#')?;
    if value.len() != 6 {
        return None;
    }
    let red = u8::from_str_radix(&value[0..2], 16).ok()?;
    let green = u8::from_str_radix(&value[2..4], 16).ok()?;
    let blue = u8::from_str_radix(&value[4..6], 16).ok()?;
    Some([
        red as f32 / 255.0,
        green as f32 / 255.0,
        blue as f32 / 255.0,
        1.0,
    ])
}

#[derive(Debug, Clone, Copy, PartialEq)]
struct SceneGuideColours {
    grid: [f32; 4],
    grid_major: [f32; 4],
    reference: [f32; 4],
    cloth: [f32; 4],
    highlight: [f32; 4],
    gizmo: [[f32; 4]; 3],
}

fn quality_colour(quality: &Value, key: &str, fallback: [f32; 4]) -> [f32; 4] {
    quality
        .get(key)
        .and_then(Value::as_str)
        .and_then(parse_color)
        .unwrap_or(fallback)
}

fn scene_guide_colours(quality: &Value) -> SceneGuideColours {
    let mut grid = quality_colour(quality, "d3d11_grid_color", [0.35, 0.41, 0.47, 1.0]);
    grid[3] = 0.30;
    let grid_major = [
        (grid[0] * 1.22).min(1.0),
        (grid[1] * 1.22).min(1.0),
        (grid[2] * 1.22).min(1.0),
        0.48,
    ];
    let fallback_reference = [0.18, 0.68, 1.0, 0.92];
    let mut reference = quality_colour(quality, "d3d11_wire_color", fallback_reference);
    let reference_luma = reference[0] * 0.299 + reference[1] * 0.587 + reference[2] * 0.114;
    let distance = (reference[0] - grid[0]).powi(2)
        + (reference[1] - grid[1]).powi(2)
        + (reference[2] - grid[2]).powi(2);
    if reference_luma < 0.08 || distance < 0.035 {
        reference = fallback_reference;
    } else {
        reference[3] = 0.92;
    }
    SceneGuideColours {
        grid,
        grid_major,
        reference,
        cloth: [0.82, 0.68, 0.30, 0.72],
        highlight: quality_colour(quality, "gizmo_highlight_color", [1.0, 0.88, 0.37, 0.96]),
        gizmo: [
            quality_colour(quality, "gizmo_x_axis_color", [0.92, 0.29, 0.29, 1.0]),
            quality_colour(quality, "gizmo_y_axis_color", [0.31, 0.86, 0.41, 1.0]),
            quality_colour(quality, "gizmo_z_axis_color", [0.29, 0.57, 1.0, 1.0]),
        ],
    }
}

fn push_axis_label(
    lines: &mut Vec<EffectLineVertex>,
    center: Vec3,
    right: Vec3,
    up: Vec3,
    size: f32,
    label: char,
    colour: [f32; 4],
) {
    let r = right.normalize_or(Vec3::X) * size;
    let u = up.normalize_or(Vec3::Y) * size;
    match label {
        'X' => {
            push_effect_line(lines, center - r - u, center + r + u, colour);
            push_effect_line(lines, center - r + u, center + r - u, colour);
        }
        'Y' => {
            push_effect_line(lines, center - r + u, center, colour);
            push_effect_line(lines, center + r + u, center, colour);
            push_effect_line(lines, center, center - u, colour);
        }
        'Z' => {
            push_effect_line(lines, center - r + u, center + r + u, colour);
            push_effect_line(lines, center + r + u, center - r - u, colour);
            push_effect_line(lines, center - r - u, center + r - u, colour);
        }
        _ => {}
    }
}

fn handle_axis(handle: &str) -> Option<Vec3> {
    match handle {
        "x" => Some(Vec3::X),
        "y" => Some(Vec3::Y),
        "z" => Some(Vec3::Z),
        _ => None,
    }
}

fn axis_plane_basis(axis: Vec3) -> (Vec3, Vec3) {
    if axis.abs().x > 0.5 {
        (Vec3::Y, Vec3::Z)
    } else if axis.abs().y > 0.5 {
        (Vec3::X, Vec3::Z)
    } else {
        (Vec3::X, Vec3::Y)
    }
}

fn screen_segment_distance(point: Vec2, start: Vec2, end: Vec2) -> f32 {
    let segment = end - start;
    if segment.length_squared() <= 1.0e-6 {
        return point.distance(start);
    }
    let amount = ((point - start).dot(segment) / segment.length_squared()).clamp(0.0, 1.0);
    point.distance(start + segment * amount)
}

fn selected_colour(
    selected: Option<&str>,
    handle: &str,
    regular: [f32; 4],
    highlight: [f32; 4],
) -> [f32; 4] {
    if selected == Some(handle) {
        highlight
    } else {
        regular
    }
}

fn push_outlined_line(
    lines: &mut Vec<EffectLineVertex>,
    start: Vec3,
    end: Vec3,
    camera_right: Vec3,
    camera_up: Vec3,
    width: f32,
    colour: [f32; 4],
) {
    let outline = [0.015, 0.018, 0.025, 0.96];
    for offset in [
        camera_right * width,
        -camera_right * width,
        camera_up * width,
        -camera_up * width,
    ] {
        push_effect_line(lines, start + offset, end + offset, outline);
    }
    push_effect_line(lines, start, end, colour);
}

fn push_billboard_diamond(
    lines: &mut Vec<EffectLineVertex>,
    center: Vec3,
    camera_right: Vec3,
    camera_up: Vec3,
    radius: f32,
    colour: [f32; 4],
) {
    let points = [
        center + camera_right * radius,
        center + camera_up * radius,
        center - camera_right * radius,
        center - camera_up * radius,
    ];
    for index in 0..4 {
        push_outlined_line(
            lines,
            points[index],
            points[(index + 1) % 4],
            camera_right,
            camera_up,
            radius * 0.08,
            colour,
        );
    }
}

fn push_transform_gizmo(
    lines: &mut Vec<EffectLineVertex>,
    pivot: Vec3,
    length: f32,
    camera_right: Vec3,
    camera_up: Vec3,
    tool: &str,
    selected: Option<&str>,
    colours: [[f32; 4]; 3],
    highlight: [f32; 4],
    dimensions: [f32; 3],
    label_colour: Option<[f32; 4]>,
) {
    let length = length.max(1.0e-4);
    let [width, handle, label_size] = dimensions;
    if tool == "rotate" {
        for (index, (axis, label)) in [(Vec3::X, "x"), (Vec3::Y, "y"), (Vec3::Z, "z")]
            .into_iter()
            .enumerate()
        {
            let colour = selected_colour(selected, label, colours[index], highlight);
            let (first, second) = axis_plane_basis(axis);
            let radius = length * 0.78;
            let mut previous = pivot + first * radius;
            for step in 1..=64 {
                let angle = std::f32::consts::TAU * step as f32 / 64.0;
                let current = pivot + (first * angle.cos() + second * angle.sin()) * radius;
                push_outlined_line(
                    lines,
                    previous,
                    current,
                    camera_right,
                    camera_up,
                    width,
                    colour,
                );
                previous = current;
            }
        }
        push_billboard_diamond(
            lines,
            pivot,
            camera_right,
            camera_up,
            handle,
            selected_colour(selected, "center", [0.82, 0.84, 0.90, 1.0], highlight),
        );
        return;
    }

    for (index, (axis, label, glyph)) in [
        (Vec3::X, "x", 'X'),
        (Vec3::Y, "y", 'Y'),
        (Vec3::Z, "z", 'Z'),
    ]
    .into_iter()
    .enumerate()
    {
        let colour = selected_colour(selected, label, colours[index], highlight);
        let tip = pivot + axis * length;
        push_outlined_line(lines, pivot, tip, camera_right, camera_up, width, colour);
        if tool == "scale" {
            push_billboard_diamond(lines, tip, camera_right, camera_up, handle, colour);
        } else {
            let perpendicular = if axis.dot(camera_right).abs() < 0.86 {
                camera_right.normalize_or(Vec3::X)
            } else {
                camera_up.normalize_or(Vec3::Y)
            };
            for side in [-1.0_f32, 1.0] {
                push_outlined_line(
                    lines,
                    tip,
                    tip - axis * length * 0.17 + perpendicular * length * 0.09 * side,
                    camera_right,
                    camera_up,
                    width,
                    colour,
                );
            }
        }
        push_axis_label(
            lines,
            tip + axis * length * 0.20,
            camera_right,
            camera_up,
            label_size,
            glyph,
            label_colour.unwrap_or(colour),
        );
    }

    if tool == "move" {
        for (label, first, second, colour) in [
            ("xy", Vec3::X, Vec3::Y, [0.88, 0.80, 0.20, 0.88]),
            ("xz", Vec3::X, Vec3::Z, [0.80, 0.30, 0.78, 0.88]),
            ("yz", Vec3::Y, Vec3::Z, [0.20, 0.78, 0.76, 0.88]),
        ] {
            let colour = selected_colour(selected, label, colour, highlight);
            let side = length * 0.20;
            let offset = length * 0.18;
            let corners = [
                pivot + first * offset + second * offset,
                pivot + first * (offset + side) + second * offset,
                pivot + first * (offset + side) + second * (offset + side),
                pivot + first * offset + second * (offset + side),
            ];
            for index in 0..4 {
                push_outlined_line(
                    lines,
                    corners[index],
                    corners[(index + 1) % 4],
                    camera_right,
                    camera_up,
                    width,
                    colour,
                );
            }
        }
    }
    push_billboard_diamond(
        lines,
        pivot,
        camera_right,
        camera_up,
        handle,
        selected_colour(selected, "center", [0.88, 0.90, 0.96, 1.0], highlight),
    );
}

fn push_camera_navigator(
    lines: &mut Vec<EffectLineVertex>,
    center: Vec3,
    length: f32,
    camera_right: Vec3,
    camera_up: Vec3,
    colours: [[f32; 4]; 3],
) {
    let width = length * 0.012;
    for step in 0..32 {
        let first = std::f32::consts::TAU * step as f32 / 32.0;
        let second = std::f32::consts::TAU * (step + 1) as f32 / 32.0;
        push_effect_line(
            lines,
            center + (camera_right * first.cos() + camera_up * first.sin()) * length * 1.45,
            center + (camera_right * second.cos() + camera_up * second.sin()) * length * 1.45,
            [0.52, 0.56, 0.66, 0.58],
        );
    }
    for (index, (axis, glyph)) in [(Vec3::X, 'X'), (Vec3::Y, 'Y'), (Vec3::Z, 'Z')]
        .into_iter()
        .enumerate()
    {
        let colour = colours[index];
        for sign in [-1.0_f32, 1.0] {
            let end = center + axis * length * sign;
            let dimmed = if sign > 0.0 {
                colour
            } else {
                [colour[0] * 0.45, colour[1] * 0.45, colour[2] * 0.45, 0.78]
            };
            push_outlined_line(lines, center, end, camera_right, camera_up, width, dimmed);
            push_billboard_diamond(lines, end, camera_right, camera_up, length * 0.12, dimmed);
            if sign > 0.0 {
                push_axis_label(
                    lines,
                    end,
                    camera_right,
                    camera_up,
                    length * 0.09,
                    glyph,
                    colour,
                );
            }
        }
    }
}

#[cfg(test)]
fn push_gizmo_axes(
    lines: &mut Vec<EffectLineVertex>,
    pivot: Vec3,
    length: f32,
    camera_right: Vec3,
    camera_up: Vec3,
    colours: [[f32; 4]; 3],
) {
    push_transform_gizmo(
        lines,
        pivot,
        length,
        camera_right,
        camera_up,
        "move",
        None,
        colours,
        [1.0, 0.88, 0.37, 0.96],
        [length * 0.008, length * 0.085, length * 0.065],
        None,
    );
}

fn grid_plane_axes(grid: &Value) -> (Vec3, Vec3) {
    match grid
        .get("normal_axis")
        .and_then(Value::as_str)
        .unwrap_or("y")
        .trim()
        .to_ascii_lowercase()
        .as_str()
    {
        "x" => (Vec3::Y, Vec3::Z),
        "z" => (Vec3::X, Vec3::Y),
        _ => (Vec3::X, Vec3::Z),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn read_only_capabilities_cover_the_resident_archive_contract() {
        for required in [
            "resident_package_load_v1",
            "viewport_display_modes_v1",
            "absolute_camera_state_v1",
            "comparison_scene_v1",
            "ui_theme_state_v1",
        ] {
            assert!(CAPABILITIES.contains(&required));
        }
    }

    #[test]
    fn merge_preserves_unmentioned_nested_state() {
        let mut target = json!({"display": {"mode": "textured", "grid_visible": true}});
        merge_value(
            &mut target,
            &json!({"event": "presentation_state_update", "display": {"mode": "wire"}}),
        );
        assert_eq!(target["display"]["mode"], "wire");
        assert_eq!(target["display"]["grid_visible"], true);
        assert!(target.get("event").is_none());
    }

    #[test]
    fn grid_plane_axes_follow_the_scene_normal_axis() {
        assert_eq!(grid_plane_axes(&json!({})), (Vec3::X, Vec3::Z));
        assert_eq!(
            grid_plane_axes(&json!({"normal_axis": "z"})),
            (Vec3::X, Vec3::Y),
        );
        assert_eq!(
            grid_plane_axes(&json!({"normal_axis": "x"})),
            (Vec3::Y, Vec3::Z),
        );
    }

    #[test]
    fn grid_reference_and_xyz_gizmo_use_distinct_readable_colours() {
        let colours = scene_guide_colours(&json!({
            "d3d11_grid_color": "#39C5FF",
            "d3d11_wire_color": "#39C5FF",
            "gizmo_x_axis_color": "#EB4B4B",
            "gizmo_y_axis_color": "#50DC69",
            "gizmo_z_axis_color": "#4B91FF"
        }));
        assert_ne!(colours.grid[..3], colours.reference[..3]);
        assert!(colours.grid[3] < colours.reference[3]);
        assert_ne!(colours.gizmo[0], colours.gizmo[1]);
        assert_ne!(colours.gizmo[1], colours.gizmo[2]);

        let mut lines = Vec::new();
        push_gizmo_axes(&mut lines, Vec3::ZERO, 1.0, Vec3::X, Vec3::Y, colours.gizmo);
        assert!(
            lines.len() >= 250,
            "outlined arrows, plane handles, center handle, and X/Y/Z labels"
        );
        for colour in colours.gizmo {
            assert!(lines.iter().any(|vertex| vertex.colour == colour));
        }
    }

    #[test]
    fn effect_clock_freezes_at_the_current_frame_and_resumes_without_a_jump() {
        let mut clock = EffectClock::new();
        clock.last_tick = Instant::now() - Duration::from_millis(20);
        let moving = clock.sample(false);
        assert!(moving >= 0.015);

        clock.last_tick = Instant::now() - Duration::from_secs(2);
        let held = clock.sample(true);
        assert_eq!(held, moving);

        clock.last_tick = Instant::now() - Duration::from_millis(10);
        let resumed = clock.sample(false);
        assert!(resumed > held);
        assert!(resumed - held < 0.05);
    }

    #[test]
    fn particle_motion_integrates_force_and_damping_once() {
        let (position, velocity) =
            particle_kinematics(Vec3::ZERO, Vec3::X, Vec3::Y * 2.0, 0.0, 2.0);
        assert!((position - Vec3::new(2.0, 4.0, 0.0)).length() < 1.0e-5);
        assert!((velocity - Vec3::new(1.0, 4.0, 0.0)).length() < 1.0e-5);

        let (damped_position, damped_velocity) =
            particle_kinematics(Vec3::ZERO, Vec3::X, Vec3::ZERO, 1.0, 1.0);
        let attenuation = (-1.0_f32).exp();
        assert!((damped_velocity - Vec3::X * attenuation).length() < 1.0e-5);
        assert!((damped_position - Vec3::X * (1.0 - attenuation)).length() < 1.0e-5);
    }

    #[test]
    fn billboard_planes_stay_camera_facing_after_scene_rotation() {
        let instances = effect_emitter_billboards(
            &json!({
                "kind": "billboard",
                "burst": 1,
                "max_particles": 1,
                "loop": false,
                "life": [1.0, 1.0],
                "scale": [[0.1, 0.1, 0.1], [0.1, 0.1, 0.1]],
                "alpha_over_life": [1.0, 1.0]
            }),
            0,
            0.0,
            0.01,
            3,
            Mat4::from_scale_rotation_translation(
                Vec3::splat(2.0),
                glam::Quat::from_rotation_z(std::f32::consts::FRAC_PI_2),
                Vec3::new(1.0, 2.0, 3.0),
            ),
            Vec3::X,
            Vec3::Y,
            Vec3::Z,
        );

        assert_eq!(instances.len(), 1);
        let right = Vec3::from_array(instances[0].axis_right).normalize();
        let up = Vec3::from_array(instances[0].axis_up).normalize();
        assert!(right.dot(Vec3::X) > 0.999);
        assert!(up.dot(Vec3::Y) > 0.999);
        assert_eq!(instances[0].texture_index, 3);
    }

    #[test]
    fn effect_simulation_consumes_the_complete_emitter_shape_with_bounded_output() {
        let emitter = json!({
            "name": "contract",
            "kind": "billboard",
            "texture": "effect/smoke.dds",
            "blend": "alpha",
            "burst": 4,
            "bursts_per_second": 8.0,
            "max_particles": 32,
            "life": [0.5, 1.2],
            "loop": true,
            "spawn": "points",
            "spread": [0.2, 0.3, 0.4],
            "points": [[0.1, 0.2, 0.3], [-0.2, 0.1, 0.0]],
            "force": [[-0.1, 0.2, 0.0], [0.1, 0.8, 0.2]],
            "damping": 0.2,
            "speed_limit": 2.0,
            "scale": [[0.02, 0.03, 0.02], [0.08, 0.1, 0.08]],
            "rotation": [-30.0, 45.0],
            "scale_over_life": [0.2, 1.0, 0.1],
            "alpha_over_life": [0.0, 1.0, 0.2],
            "color_over_life": [[1.0, 0.2, 0.1], [0.2, 0.5, 1.0]],
            "emissive_color": [0.8, 0.6, 0.2],
            "brightness": 2.0,
            "beam_width": 0.03,
            "beam_jitter": 0.1,
            "beam_length": 1.0,
            "beam_axis": [0.0, 1.0, 0.0],
            "mass": 0.8,
            "simulation_speed": 1.5,
            "spawn_time": 3.0,
            "sequence": [4, 4],
            "velocity_stretch": 0.7
        });
        let first = effect_emitter_lines(&emitter, 2, 0.65, 0.01);
        let repeated = effect_emitter_lines(&emitter, 2, 0.65, 0.01);
        let later = effect_emitter_lines(&emitter, 2, 0.72, 0.01);
        assert!(!first.is_empty());
        assert_eq!(first, repeated);
        assert_ne!(first, later);
        assert!(first.len() <= 256 * 20);
        assert!(first.len().is_multiple_of(2));
        assert!(first.iter().all(|vertex| {
            vertex
                .position
                .iter()
                .chain(vertex.colour.iter())
                .all(|value| value.is_finite())
        }));
        assert!(first.iter().all(|vertex| {
            vertex
                .colour
                .iter()
                .all(|value| (0.0..=1.0).contains(value))
        }));
        assert!(
            first
                .iter()
                .any(|vertex| vertex.colour[0] != vertex.colour[2])
        );
    }

    #[test]
    fn zero_alpha_effect_still_has_a_bounded_visible_emitter_marker() {
        let emitter = json!({
            "kind": "billboard",
            "alpha_over_life": [0.0, 0.0],
            "color_over_life": [[0.1, 0.4, 1.0]],
            "emissive_color": [0.2, 0.8, 1.0],
            "brightness": 2.0
        });
        let marker = effect_emitter_lines(&emitter, 0, 0.0, 0.025);
        assert_eq!(marker.len(), 6);
        assert!(marker.iter().all(|vertex| vertex.colour[3] >= 0.38));
        let maximum_extent = marker
            .iter()
            .flat_map(|vertex| vertex.position)
            .map(f32::abs)
            .fold(0.0_f32, f32::max);
        assert!(maximum_extent >= 0.025);
    }
}
