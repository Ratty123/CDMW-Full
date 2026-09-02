#![forbid(unsafe_code)]

use crate::camera::OrbitCamera;
use crate::cdmw_material_preview_factors;
use crate::cdmw_session::{
    CdmwTextureResource, LoadedCdmwSessionPackage, PREVIEW_BACKEND, PREVIEW_PROTOCOL, RENDERER,
    SessionMaterialPresentation,
};
use anyhow::{Context, Result};
use cdmw_formats::{MeshDocument, SourceRange, Submesh};
use cdmw_mesh::{DrawSnapshot, Provenance, Selection, WorkingMesh};
use cdmw_render_wgpu::{
    EffectLineVertex, HeadlessMaterialCaptureOptions, HeadlessMaterialCaptureOutput,
    HeadlessMaterialFactors, HeadlessMaterialTexture, MaterialPreviewFactors, ViewMode,
    WindowRenderer, run_headless_material_capture,
};
use crossbeam_channel::{Receiver, Sender, bounded};
use egui::{Pos2, Rect, Vec2 as EguiVec2};
use glam::{EulerRot, Mat3, Mat4, Quat, Vec2, Vec3};
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::thread;
use std::time::Instant;
use winit::application::ApplicationHandler;
use winit::event::{ElementState, MouseButton, MouseScrollDelta, WindowEvent};
use winit::event_loop::ActiveEventLoop;
use winit::window::{Window, WindowAttributes, WindowId};

const CONTROL_QUEUE_BOUND: usize = 256;
const OUTBOUND_QUEUE_BOUND: usize = 128;
const PACKAGE_QUEUE_BOUND: usize = 4;
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
    "static_replacement_mesh_input_v1",
    "effect_particle_preview_v1",
    "ui_theme_state_v1",
    "ui_localization_v1",
];

pub(crate) fn control_contract() -> Value {
    let commands = [
        ("preview_session_state", "both", "preview_session_state_ack"),
        ("package_load_request", "both", "package_loaded"),
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
}

#[derive(Debug)]
struct PackageResult {
    request_id: u64,
    generation: u64,
    path: PathBuf,
    result: std::result::Result<LoadedCdmwSessionPackage, String>,
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
    fn new(session_id: String, process_generation: u64) -> Self {
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
                            }
                            Err(error) => {
                                let _ = incoming_tx.try_send(Incoming::Error(format!(
                                    "Rust Preview received invalid JSON: {error}"
                                )));
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
    start_pointer: Vec2,
    start_placement: Value,
    start_model_matrix: Mat4,
    start_pivot: Vec3,
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
    snapshot: DrawSnapshot,
    textures: Vec<CdmwTextureResource>,
    presentations: Vec<SessionMaterialPresentation>,
    camera: OrbitCamera,
    view_mode: ViewMode,
    state: PreviewState,
    visible: bool,
    exit_requested: bool,
    pointer: Option<Vec2>,
    orbiting: bool,
    panning: bool,
    right_press: Option<Vec2>,
    hovered_part: Option<u32>,
    gizmo_drag: Option<GizmoDrag>,
    scene_revision: u64,
    effect_clock: EffectClock,
    package_tx: Sender<PackageResult>,
    package_rx: Receiver<PackageResult>,
    capture_tx: Sender<CaptureResult>,
    capture_rx: Receiver<CaptureResult>,
    newest_package_generation: u64,
}

impl PreviewApplication {
    pub fn open(manifest_path: &Path, parent_hwnd: u64) -> Result<Self> {
        let mut package = LoadedCdmwSessionPackage::load_preview(manifest_path)
            .context("failed to load the initial Rust Preview package")?;
        let document = package.document().clone();
        let mesh = WorkingMesh::from_document_lod(&document, package.source_lod_index())
            .context("Rust Preview document could not create its requested LOD")?;
        let snapshot = mesh.draw_snapshot();
        let textures = package.take_textures();
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
        );
        let (package_tx, package_rx) = bounded(PACKAGE_QUEUE_BOUND);
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
            snapshot,
            textures,
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
            panning: false,
            right_press: None,
            hovered_part: None,
            gizmo_drag: None,
            scene_revision: 1,
            effect_clock: EffectClock::new(),
            package_tx,
            package_rx,
            capture_tx,
            capture_rx,
            newest_package_generation: 0,
        };
        application.refresh_visible_snapshot();
        application.camera.frame_integrated_positions(
            application
                .snapshot
                .positions
                .iter()
                .copied()
                .map(Vec3::from_array),
        );
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

    fn configure_renderer(&mut self) -> Result<(), String> {
        let Some(renderer) = &mut self.renderer else {
            return Ok(());
        };
        renderer.reset_texture();
        for texture in &self.textures {
            renderer
                .add_dds_texture(
                    &texture.bytes,
                    texture.role,
                    &texture.material_indices_by_lod,
                )
                .map_err(|error| error.to_string())?;
        }
        for presentation in &self.presentations {
            let ownership =
                presentation_ownership(presentation, self.package.document().lods.len());
            renderer
                .add_material_factors(cdmw_material_preview_factors(presentation), &ownership)
                .map_err(|error| error.to_string())?;
        }
        renderer
            .set_material_lod(self.package.source_lod_index())
            .map_err(|error| error.to_string())?;
        renderer
            .set_snapshot(&self.snapshot)
            .map_err(|error| error.to_string())?;
        Ok(())
    }

    fn start_package_load(&mut self, request_id: u64, generation: u64, path: PathBuf) {
        if generation < self.newest_package_generation {
            return;
        }
        self.newest_package_generation = generation;
        let sender = self.package_tx.clone();
        thread::Builder::new()
            .name(format!("cdmw-rust-preview-package-{generation}"))
            .spawn(move || {
                let manifest = if path.is_dir() {
                    path.join("manifest.json")
                } else {
                    path.clone()
                };
                let result = LoadedCdmwSessionPackage::load_preview(&manifest)
                    .map_err(|error| error.to_string());
                let _ = sender.send(PackageResult {
                    request_id,
                    generation,
                    path,
                    result,
                });
            })
            .ok();
    }

    fn poll_package_loads(&mut self) -> bool {
        let mut changed = false;
        while let Ok(result) = self.package_rx.try_recv() {
            if result.generation != self.newest_package_generation {
                continue;
            }
            match result.result {
                Ok(mut package) => {
                    let loaded = WorkingMesh::from_document_lod(
                        package.document(),
                        package.source_lod_index(),
                    );
                    match loaded {
                        Ok(mesh) => {
                            self.document = package.document().clone();
                            self.mesh = mesh;
                            self.snapshot = self.mesh.draw_snapshot();
                            self.textures = package.take_textures();
                            self.presentations = package.take_material_presentations();
                            self.state.scene = package
                                .manifest()
                                .state
                                .get("preview_scene")
                                .cloned()
                                .unwrap_or(Value::Null);
                            self.package = package;
                            self.effect_clock.reset();
                            self.scene_revision = self.scene_revision.saturating_add(1);
                            self.refresh_visible_snapshot();
                            self.camera.frame_integrated_positions(
                                self.snapshot
                                    .positions
                                    .iter()
                                    .copied()
                                    .map(Vec3::from_array),
                            );
                            let apply = self.configure_renderer();
                            if let Err(error) = apply {
                                self.bridge.send(json!({
                                    "event": "package_load_failed",
                                    "request_id": result.request_id,
                                    "generation": result.generation,
                                    "package_path": result.path,
                                    "error": error,
                                }));
                            } else {
                                self.apply_presentation();
                                self.bridge.send(json!({
                                    "event": "package_load_applied",
                                    "request_id": result.request_id,
                                    "generation": result.generation,
                                    "package_path": result.path,
                                    "material_signature": self.package.manifest().source.get("sha256").cloned().unwrap_or(Value::Null),
                                }));
                                changed = true;
                            }
                        }
                        Err(error) => self.bridge.send(json!({
                            "event": "package_load_failed",
                            "request_id": result.request_id,
                            "generation": result.generation,
                            "package_path": result.path,
                            "error": error.to_string(),
                        })),
                    }
                }
                Err(error) => self.bridge.send(json!({
                    "event": "package_load_failed",
                    "request_id": result.request_id,
                    "generation": result.generation,
                    "package_path": result.path,
                    "error": error,
                })),
            }
        }
        changed
    }

    fn start_capture(&self, value: &Value) {
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
        let snapshot = self.snapshot.clone();
        let textures = self.textures.clone();
        let presentations = self.presentations.clone();
        let lod_index = self.package.source_lod_index();
        let lod_count = self.package.document().lods.len();
        let sender = self.capture_tx.clone();
        thread::Builder::new()
            .name(format!("cdmw-rust-preview-capture-{request_id}"))
            .spawn(move || {
                let result = (|| -> Result<()> {
                    if let Some(parent) = output_path.parent() {
                        std::fs::create_dir_all(parent).with_context(|| {
                            format!("could not create capture directory {}", parent.display())
                        })?;
                    }
                    let base_path = output_path.with_extension("base.bmp");
                    let part_path = output_path.with_extension("parts.bmp");
                    let texture_inputs = textures
                        .iter()
                        .map(|texture| HeadlessMaterialTexture {
                            bytes: &texture.bytes,
                            role: texture.role,
                            material_indices_by_lod: &texture.material_indices_by_lod,
                        })
                        .collect::<Vec<_>>();
                    let ownership = presentations
                        .iter()
                        .map(|presentation| presentation_ownership(presentation, lod_count))
                        .collect::<Vec<_>>();
                    let factor_inputs = presentations
                        .iter()
                        .zip(ownership.iter())
                        .map(
                            |(presentation, material_indices_by_lod)| HeadlessMaterialFactors {
                                factors: cdmw_material_preview_factors(presentation),
                                material_indices_by_lod,
                            },
                        )
                        .collect::<Vec<_>>();
                    pollster::block_on(run_headless_material_capture(
                        &snapshot,
                        &texture_inputs,
                        &factor_inputs,
                        HeadlessMaterialCaptureOptions {
                            width,
                            height,
                            lod_index,
                        },
                        HeadlessMaterialCaptureOutput {
                            textured_bmp: &output_path,
                            base_color_bmp: &base_path,
                            part_id_bmp: &part_path,
                        },
                    ))
                    .map_err(|error| anyhow::anyhow!(error.to_string()))?;
                    let _ = std::fs::remove_file(base_path);
                    let _ = std::fs::remove_file(part_path);
                    Ok(())
                })()
                .map_err(|error| error.to_string());
                let _ = sender.send(CaptureResult {
                    request_id,
                    output_path,
                    result,
                });
            })
            .ok();
    }

    fn poll_captures(&self) {
        while let Ok(result) = self.capture_rx.try_recv() {
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
                    self.start_package_load(request_id, generation, PathBuf::from(path));
                }
            }
            "presentation_state_update" => {
                merge_value(&mut self.state.presentation, &value);
                self.apply_presentation();
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
                merge_value(&mut self.state.scene, &value);
                self.scene_revision = self.scene_revision.saturating_add(1);
                self.apply_presentation();
                self.ack_state(event, &value);
                return true;
            }
            "material_parameter_update" => {
                self.state.material_parameters = value.clone();
                self.apply_material_parameters();
                self.ack_state(event, &value);
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
                Incoming::Error(error) => {
                    self.bridge.send(json!({"event": "error", "error": error}))
                }
            }
        }
        changed
    }

    fn apply_presentation(&mut self) {
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
        }
        if let Some(camera) = self.state.presentation.get("camera") {
            if camera.get("fit_mode").and_then(Value::as_str) == Some("fit") {
                self.camera.frame_positions_in_current_view(
                    self.snapshot
                        .positions
                        .iter()
                        .copied()
                        .map(Vec3::from_array),
                    self.viewport_rect(),
                );
            }
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
            self.camera.set_orbit_state(
                yaw_degrees.to_radians(),
                pitch_degrees.to_radians(),
                None,
                zoom,
            );
            if let Some(pan) = pan {
                let target = self.camera.fit_target()
                    + self.camera.right() * pan.x
                    + self.camera.up() * pan.y;
                self.camera.set_orbit_state(
                    yaw_degrees.to_radians(),
                    pitch_degrees.to_radians(),
                    Some(target),
                    None,
                );
            }
        }
        self.refresh_visible_snapshot();
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
        let editable = editable_indices(&self.state.scene);
        let reference = reference_indices(&self.state.scene);
        let mut matrix = if reference.contains(&source_submesh) {
            role_model_matrix(&self.state.scene, "reference")
        } else if editable.contains(&source_submesh) {
            role_model_matrix(&self.state.scene, "editable")
        } else {
            Mat4::IDENTITY
        };
        let source_part = self.source_part_index(source_submesh);
        if let Some(part) = self
            .state
            .presentation
            .get("part_transforms")
            .and_then(Value::as_object)
            .and_then(|items| items.get(source_part.to_string().as_str()))
        {
            matrix *= placement_matrix(part);
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
        if comparison_mode == "side_by_side" {
            let extent = self
                .state
                .scene
                .get("framing")
                .and_then(|value| value.get("extent"))
                .and_then(Value::as_f64)
                .unwrap_or(1.0) as f32;
            let split = self
                .state
                .presentation
                .get("side_by_side_split_ratio")
                .and_then(Value::as_f64)
                .unwrap_or(0.5)
                .clamp(0.18, 0.82) as f32;
            let side_offset = (extent.max(0.01) * 0.65).max(0.05);
            let translation = if reference.contains(&source_submesh) {
                Vec3::new(-side_offset * split.recip().min(4.0), 0.0, 0.0)
            } else {
                Vec3::new(side_offset * (1.0 - split).recip().min(4.0), 0.0, 0.0)
            };
            matrix = Mat4::from_translation(translation) * matrix;
        }
        matrix
    }

    fn push_submesh_edges(&self, lines: &mut Vec<[f32; 3]>, wanted: &HashSet<u32>) {
        const MAX_GUIDE_VERTICES: usize = 240_000;
        for (_handle, face) in self.mesh.faces() {
            if !wanted.contains(&face.submesh) || lines.len() >= MAX_GUIDE_VERTICES {
                continue;
            }
            let matrix = self.submesh_model_matrix(face.submesh);
            let points = face.vertices.map(|handle| {
                self.mesh
                    .vertex(handle)
                    .map(|vertex| matrix.transform_point3(Vec3::from_array(vertex.position)))
            });
            let [Some(a), Some(b), Some(c)] = points else {
                continue;
            };
            lines.extend_from_slice(&[
                a.to_array(),
                b.to_array(),
                b.to_array(),
                c.to_array(),
                c.to_array(),
                a.to_array(),
            ]);
        }
    }

    fn refresh_scene_overlays(&mut self, time: f32) {
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

        let mut lines = Vec::new();
        let display = self
            .state
            .presentation
            .get("display")
            .unwrap_or(&Value::Null);
        if display
            .get("grid_visible")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            let grid = self.state.scene.get("grid").unwrap_or(&Value::Null);
            let origin = vec3_value(grid.get("origin"), Vec3::ZERO);
            let quality = display.get("quality").unwrap_or(&Value::Null);
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
                lines.extend_from_slice(&[
                    (origin + Vec3::new(-radius, 0.0, offset)).to_array(),
                    (origin + Vec3::new(radius, 0.0, offset)).to_array(),
                    (origin + Vec3::new(offset, 0.0, -radius)).to_array(),
                    (origin + Vec3::new(offset, 0.0, radius)).to_array(),
                ]);
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
                        lines.extend_from_slice(&points);
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
        if gizmo_visible {
            let pivot = vec3_value(self.state.scene.get("placement_pivot"), Vec3::ZERO);
            let length = self
                .state
                .scene
                .get("framing")
                .and_then(|value| value.get("extent"))
                .and_then(Value::as_f64)
                .unwrap_or(1.0) as f32
                * 0.12;
            for axis in [Vec3::X, Vec3::Y, Vec3::Z] {
                lines.push(pivot.to_array());
                lines.push((pivot + axis * length.max(0.025)).to_array());
            }
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
            self.push_submesh_edges(&mut lines, &reference_indices(&self.state.scene));
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
            let scene_submeshes = self
                .mesh
                .faces()
                .filter_map(|(_, face)| {
                    highlighted
                        .contains(&self.source_part_index(face.submesh))
                        .then_some(face.submesh)
                })
                .collect::<HashSet<_>>();
            self.push_submesh_edges(&mut lines, &scene_submeshes);
        }

        let mut effect_lines = Vec::new();
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
                for mut vertex in effect_emitter_lines(emitter, emitter_index, time, minimum_radius)
                {
                    if effect_lines.len() >= MAX_EFFECT_LINE_VERTICES {
                        break;
                    }
                    vertex.position = editable_matrix
                        .transform_point3(Vec3::from_array(vertex.position))
                        .to_array();
                    effect_lines.push(vertex);
                }
                if effect_lines.len() >= MAX_EFFECT_LINE_VERTICES {
                    break;
                }
            }
        }

        if let Some(renderer) = &mut self.renderer {
            let _ = renderer.set_skeleton_lines(&skeleton_lines);
            renderer.set_bone_overlay(skeleton_visible && !skeleton_lines.is_empty());
            let _ = renderer.set_preview_lines(&lines);
            let _ = renderer.set_effect_lines(&effect_lines);
        }
    }

    fn apply_material_parameters(&mut self) {
        let Some(renderer) = &mut self.renderer else {
            return;
        };
        renderer.reset_material_factors();
        let lod_count = self.package.document().lods.len();
        for presentation in &self.presentations {
            let ownership = presentation_ownership(presentation, lod_count);
            let _ = renderer
                .add_material_factors(cdmw_material_preview_factors(presentation), &ownership);
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
            let _ = renderer.add_material_factors(factors, &ownership);
        }
        let _ = renderer.set_material_lod(self.package.source_lod_index());
    }

    fn rebuild_working_mesh(&mut self) -> std::result::Result<(), String> {
        self.mesh = WorkingMesh::from_document_lod(&self.document, self.package.source_lod_index())
            .map_err(|error| error.to_string())?;
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

    fn refresh_visible_snapshot(&mut self) {
        let mut visible = scene_role_indices(&self.state.scene);
        let scene_has_roles = !visible.is_empty();
        let active = self
            .state
            .presentation
            .get("active_view")
            .and_then(Value::as_str)
            .unwrap_or_else(|| {
                match self
                    .state
                    .scene
                    .get("comparison_mode")
                    .and_then(Value::as_str)
                {
                    Some("original_only") => "reference",
                    Some("overlay" | "side_by_side") => "comparison",
                    _ => "editable",
                }
            });
        if active == "editable" {
            visible = editable_indices(&self.state.scene);
        } else if active == "reference" {
            visible = reference_indices(&self.state.scene);
        }
        if let Some(hidden) = self
            .state
            .presentation
            .get("visibility")
            .and_then(|value| value.get("hidden_submesh_indices"))
            .and_then(Value::as_array)
        {
            let hidden = hidden
                .iter()
                .filter_map(Value::as_u64)
                .filter_map(|value| u32::try_from(value).ok())
                .collect::<HashSet<_>>();
            visible.retain(|index| !hidden.contains(&self.source_part_index(*index)));
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
            for index in reference_indices(&self.state.scene) {
                visible.remove(&index);
            }
        }
        self.snapshot = if visible.is_empty() && !scene_has_roles {
            self.mesh.draw_snapshot()
        } else {
            self.mesh.draw_snapshot_for_submeshes(&visible)
        };
        if self
            .state
            .presentation
            .get("uv")
            .and_then(|value| value.get("flip_v"))
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            for uv in &mut self.snapshot.uvs {
                uv[1] = 1.0 - uv[1];
            }
        }
        self.transform_snapshot(&visible, scene_has_roles);
        if let Some(renderer) = &mut self.renderer {
            let _ = renderer.set_snapshot(&self.snapshot);
        }
    }

    fn transform_snapshot(&mut self, visible: &HashSet<u32>, filtered: bool) {
        let mut snapshot_index = 0usize;
        for (_handle, vertex) in self.mesh.vertices() {
            let source_submesh = match vertex.provenance {
                Provenance::Source { submesh, .. } => submesh,
                Provenance::Generated { .. } => 0,
            };
            if filtered && !visible.contains(&source_submesh) {
                continue;
            }
            let matrix = self.submesh_model_matrix(source_submesh);
            if let Some(position) = self.snapshot.positions.get_mut(snapshot_index) {
                *position = matrix
                    .transform_point3(Vec3::from_array(*position))
                    .to_array();
            }
            if let Some(normal) = self.snapshot.normals.get_mut(snapshot_index) {
                let normal_matrix = Mat3::from_mat4(matrix).inverse().transpose();
                *normal = (normal_matrix * Vec3::from_array(*normal))
                    .normalize_or(Vec3::Y)
                    .to_array();
            }
            snapshot_index = snapshot_index.saturating_add(1);
        }
        self.snapshot.draw_revision = self
            .snapshot
            .draw_revision
            .wrapping_mul(1_099_511_628_211)
            .wrapping_add(self.scene_revision);
        self.snapshot.fingerprint = format!(
            "{}:scene:{}",
            self.snapshot.fingerprint, self.scene_revision
        );
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
        let mut visible = scene_role_indices(&self.state.scene);
        let active = self
            .state
            .presentation
            .get("active_view")
            .and_then(Value::as_str)
            .unwrap_or_else(|| {
                match self
                    .state
                    .scene
                    .get("comparison_mode")
                    .and_then(Value::as_str)
                {
                    Some("original_only") => "reference",
                    Some("overlay" | "side_by_side") => "comparison",
                    _ => "editable",
                }
            });
        if active == "editable" {
            visible = editable_indices(&self.state.scene);
        } else if active == "reference" {
            visible = reference_indices(&self.state.scene);
        }
        if let Some(hidden) = self
            .state
            .presentation
            .get("visibility")
            .and_then(|value| value.get("hidden_submesh_indices"))
            .and_then(Value::as_array)
        {
            let hidden = hidden
                .iter()
                .filter_map(Value::as_u64)
                .filter_map(|value| u32::try_from(value).ok())
                .collect::<HashSet<_>>();
            visible.retain(|index| !hidden.contains(&self.source_part_index(*index)));
        }
        visible
    }

    fn pick_part(&self, point: Vec2) -> Option<u32> {
        if !point.is_finite() {
            return None;
        }
        let rectangle = self.viewport_rect();
        let visible = self.visible_submeshes();
        let mut best: Option<(f32, u32)> = None;
        for (_handle, face) in self.mesh.faces() {
            if !visible.is_empty() && !visible.contains(&face.submesh) {
                continue;
            }
            let mut screen = [Vec2::ZERO; 3];
            let mut depth = 0.0_f32;
            let mut valid = true;
            let matrix = self.submesh_model_matrix(face.submesh);
            for (corner, handle) in face.vertices.iter().enumerate() {
                let Some(vertex) = self.mesh.vertex(*handle) else {
                    valid = false;
                    break;
                };
                let Some(projected) = self.camera.project(
                    matrix.transform_point3(Vec3::from_array(vertex.position)),
                    rectangle,
                ) else {
                    valid = false;
                    break;
                };
                if !projected.inside_view {
                    valid = false;
                    break;
                }
                screen[corner] = projected.screen;
                depth += projected.depth;
            }
            if !valid || !point_in_triangle(point, screen[0], screen[1], screen[2]) {
                continue;
            }
            depth /= 3.0;
            if best.is_none_or(|(current, _)| depth < current) {
                best = Some((depth, face.submesh));
            }
        }
        best.map(|(_, submesh)| submesh)
    }

    fn source_part_index(&self, scene_submesh: u32) -> u32 {
        self.state
            .scene
            .get("part_identities")
            .and_then(Value::as_array)
            .and_then(|identities| {
                identities.iter().find_map(|identity| {
                    (identity.get("scene_submesh_index").and_then(Value::as_u64)
                        == Some(u64::from(scene_submesh)))
                    .then(|| {
                        identity
                            .get("source_submesh_index")
                            .and_then(Value::as_u64)
                            .and_then(|value| u32::try_from(value).ok())
                            .unwrap_or(scene_submesh)
                    })
                })
            })
            .unwrap_or(scene_submesh)
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

    fn gizmo_hit(&self, point: Vec2) -> bool {
        if !self.gizmo_visible() {
            return false;
        }
        let pivot = vec3_value(self.state.scene.get("placement_pivot"), Vec3::ZERO);
        self.camera
            .project(pivot, self.viewport_rect())
            .is_some_and(|projected| {
                projected.inside_view && projected.screen.distance(point) <= 72.0
            })
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

    fn emit_gizmo(&self, phase: &str, tool: &str, placement: &Value) {
        self.bridge.send(json!({
            "event": "placement_transform_request",
            "placement": placement,
            "placement_phase": phase,
            "gizmo_tool": tool,
            "gizmo_handle": "screen",
        }));
    }

    fn begin_gizmo_drag(&mut self, point: Vec2) -> bool {
        if !self.gizmo_hit(point) {
            return false;
        }
        let tool = self
            .state
            .scene
            .get("gizmo")
            .and_then(|gizmo| gizmo.get("tool"))
            .and_then(Value::as_str)
            .filter(|tool| matches!(*tool, "move" | "rotate" | "scale"))
            .unwrap_or("move")
            .to_owned();
        let start_placement = self.placement_payload();
        let start_pivot = vec3_value(self.state.scene.get("placement_pivot"), Vec3::ZERO);
        self.emit_gizmo("begin", &tool, &start_placement);
        self.gizmo_drag = Some(GizmoDrag {
            tool,
            start_pointer: point,
            start_placement,
            start_model_matrix: role_model_matrix(&self.state.scene, "editable"),
            start_pivot,
        });
        true
    }

    fn update_gizmo_drag(&mut self, point: Vec2, phase: &str) -> bool {
        let Some(drag) = self.gizmo_drag.clone() else {
            return false;
        };
        let delta = point - drag.start_pointer;
        let mut placement = drag.start_placement.clone();
        let mut model_matrix = drag.start_model_matrix;
        let mut pivot = drag.start_pivot;
        match drag.tool.as_str() {
            "rotate" => {
                let start = vec3_value(placement.get("rotation_degrees"), Vec3::ZERO);
                let degrees = Vec3::new(delta.y * 0.18, delta.x * 0.18, 0.0);
                placement["rotation_degrees"] = json!((start + degrees).to_array());
                let radians = degrees * std::f32::consts::PI / 180.0;
                let rotation = Mat4::from_quat(Quat::from_euler(
                    EulerRot::XYZ,
                    radians.x,
                    radians.y,
                    radians.z,
                ));
                model_matrix = Mat4::from_translation(pivot)
                    * rotation
                    * Mat4::from_translation(-pivot)
                    * model_matrix;
            }
            "scale" => {
                let start = vec3_value(
                    placement
                        .get("scale")
                        .or_else(|| placement.get("scale_xyz")),
                    Vec3::ONE,
                );
                let factor = (delta.x - delta.y).mul_add(0.006, 1.0).clamp(0.01, 100.0);
                placement["scale"] = json!((start * factor).to_array());
                model_matrix = Mat4::from_translation(pivot)
                    * Mat4::from_scale(Vec3::splat(factor))
                    * Mat4::from_translation(-pivot)
                    * model_matrix;
            }
            _ => {
                let start = vec3_value(placement.get("translation"), Vec3::ZERO);
                let movement = self
                    .camera
                    .screen_delta_to_world(delta, self.viewport_rect());
                placement["translation"] = json!((start + movement).to_array());
                model_matrix = Mat4::from_translation(movement) * model_matrix;
                pivot += movement;
            }
        }
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
        self.refresh_visible_snapshot();
        let effect_time = self.effect_time();
        self.refresh_scene_overlays(effect_time);
        self.emit_gizmo(phase, &drag.tool, &placement);
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
        self.apply_presentation();
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
            WindowEvent::CloseRequested => self.exit_requested = true,
            WindowEvent::Resized(size) => {
                if let Some(renderer) = &mut self.renderer {
                    renderer.resize(size);
                }
                window.request_redraw();
            }
            WindowEvent::CursorMoved { position, .. } => {
                let current = Vec2::new(position.x as f32, position.y as f32);
                if self.gizmo_drag.is_some() && self.update_gizmo_drag(current, "update") {
                    self.pointer = Some(current);
                    window.request_redraw();
                    return;
                }
                if let Some(previous) = self.pointer {
                    let delta = current - previous;
                    if self.orbiting {
                        self.camera.orbit(delta);
                    }
                    if self.panning {
                        self.camera.pan(delta, self.viewport_rect());
                    }
                    if self.orbiting || self.panning {
                        window.request_redraw();
                    }
                }
                self.pointer = Some(current);
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
                    if let Some(point) = self.pointer
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
                    if let Some(point) = self.pointer
                        && self.update_gizmo_drag(point, "end")
                    {
                        self.gizmo_drag = None;
                        window.request_redraw();
                    }
                }
                (ElementState::Pressed, MouseButton::Right) => {
                    self.orbiting = true;
                    self.right_press = self.pointer;
                }
                (ElementState::Released, MouseButton::Right) => {
                    self.orbiting = false;
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
                (ElementState::Pressed, MouseButton::Middle) => self.panning = true,
                (ElementState::Released, MouseButton::Middle) => {
                    self.panning = false;
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
                if self.has_dynamic_effects() {
                    let effect_time = self.effect_time();
                    self.refresh_scene_overlays(effect_time);
                }
                let camera = self.camera.view_projection(self.viewport_rect());
                if let Some(renderer) = &mut self.renderer {
                    renderer.set_view_mode(self.view_mode);
                    renderer.set_camera(camera);
                    renderer.set_mesh_viewport(None);
                    let _ = renderer.render();
                }
                if self.has_dynamic_effects() {
                    window.request_redraw();
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
        if self.exit_requested {
            event_loop.exit();
        }
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

fn role_model_matrix(scene: &Value, role: &str) -> Mat4 {
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

fn value_pair(value: Option<&Value>, fallback: (f32, f32)) -> (f32, f32) {
    let Some(values) = value.and_then(Value::as_array) else {
        return fallback;
    };
    let first = values
        .first()
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(fallback.0);
    let second = values
        .get(1)
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(fallback.1);
    (first.min(second), first.max(second))
}

fn seed_unit(seed: f32) -> f32 {
    (seed.sin() * 43_758.547).fract().abs()
}

fn seed_signed(seed: f32) -> f32 {
    seed_unit(seed) * 2.0 - 1.0
}

fn curve_sample(value: Option<&Value>, progress: f32, fallback: f32) -> f32 {
    let Some(samples) = value
        .and_then(Value::as_array)
        .filter(|samples| !samples.is_empty())
    else {
        return fallback;
    };
    let scaled = progress.clamp(0.0, 1.0) * (samples.len().saturating_sub(1)) as f32;
    let lower = scaled.floor() as usize;
    let upper = (lower + 1).min(samples.len() - 1);
    let read = |index: usize| {
        samples[index]
            .as_f64()
            .map(|value| value as f32)
            .filter(|value| value.is_finite())
            .unwrap_or(fallback)
    };
    read(lower) + (read(upper) - read(lower)) * scaled.fract()
}

fn color_curve_sample(value: Option<&Value>, progress: f32) -> Vec3 {
    let Some(samples) = value
        .and_then(Value::as_array)
        .filter(|samples| !samples.is_empty())
    else {
        return Vec3::ONE;
    };
    let scaled = progress.clamp(0.0, 1.0) * (samples.len().saturating_sub(1)) as f32;
    let lower = scaled.floor() as usize;
    let upper = (lower + 1).min(samples.len() - 1);
    vec3_value(samples.get(lower), Vec3::ONE)
        .lerp(vec3_value(samples.get(upper), Vec3::ONE), scaled.fract())
        .max(Vec3::ZERO)
}

fn effect_preview_colour(
    emitter: &Value,
    progress: f32,
    alpha: f32,
    brightness: f32,
    blend: &str,
) -> [f32; 4] {
    let life_colour = color_curve_sample(emitter.get("color_over_life"), progress);
    let emissive = vec3_value(emitter.get("emissive_color"), Vec3::ONE).max(Vec3::ZERO);
    let mut colour = life_colour * emissive * brightness.max(0.15).sqrt();
    let peak = colour.max_element();
    if peak > 1.0 {
        colour /= peak;
    } else if peak < 0.08 {
        // Black smoke and incomplete material records still need a visible guide
        // against the dark Preview background.
        colour = Vec3::splat(0.42);
    }
    let preview_alpha = if blend.eq_ignore_ascii_case("additive") {
        alpha.max(0.72)
    } else {
        alpha.max(0.38)
    };
    [
        colour.x.clamp(0.04, 1.0),
        colour.y.clamp(0.04, 1.0),
        colour.z.clamp(0.04, 1.0),
        preview_alpha.clamp(0.0, 1.0),
    ]
}

fn push_effect_line(lines: &mut Vec<EffectLineVertex>, start: Vec3, end: Vec3, colour: [f32; 4]) {
    lines.extend_from_slice(&[
        EffectLineVertex {
            position: start.to_array(),
            colour,
        },
        EffectLineVertex {
            position: end.to_array(),
            colour,
        },
    ]);
}

fn effect_spawn_position(emitter: &Value, seed: f32) -> Vec3 {
    if emitter.get("spawn").and_then(Value::as_str) == Some("points")
        && let Some(points) = emitter.get("points").and_then(Value::as_array)
        && !points.is_empty()
    {
        let index = (seed_unit(seed) * points.len() as f32).floor() as usize % points.len();
        return vec3_value(points.get(index), Vec3::ZERO);
    }
    let spread = vec3_value(emitter.get("spread"), Vec3::splat(0.1)).abs();
    Vec3::new(
        seed_signed(seed + 1.37) * spread.x,
        seed_signed(seed + 4.11) * spread.y,
        seed_signed(seed + 7.93) * spread.z,
    )
}

fn effect_force(emitter: &Value, seed: f32) -> Vec3 {
    let Some(values) = emitter.get("force").and_then(Value::as_array) else {
        return Vec3::ZERO;
    };
    let low = vec3_value(values.first(), Vec3::ZERO);
    let high = vec3_value(values.get(1), low);
    Vec3::new(
        low.x + (high.x - low.x) * seed_unit(seed + 2.03),
        low.y + (high.y - low.y) * seed_unit(seed + 5.17),
        low.z + (high.z - low.z) * seed_unit(seed + 8.29),
    )
}

fn effect_scale(emitter: &Value, seed: f32) -> f32 {
    let Some(values) = emitter.get("scale").and_then(Value::as_array) else {
        return 0.04;
    };
    let low = vec3_value(values.first(), Vec3::splat(0.04)).abs();
    let high = vec3_value(values.get(1), low).abs();
    let selected = low.lerp(high, seed_unit(seed + 0.91));
    selected.max_element().max(0.002)
}

fn effect_emitter_lines(
    emitter: &Value,
    emitter_index: usize,
    time: f32,
    minimum_radius: f32,
) -> Vec<EffectLineVertex> {
    const MAX_PARTICLES_PER_EMITTER: usize = 256;
    const MAX_LINE_VERTICES_PER_EMITTER: usize = MAX_PARTICLES_PER_EMITTER * 20;

    let simulation_speed = emitter
        .get("simulation_speed")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(1.0)
        .clamp(0.0, 20.0);
    let simulation_time = time.max(0.0) * simulation_speed;
    let burst = emitter
        .get("burst")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .unwrap_or(1)
        .clamp(1, 64);
    let maximum = emitter
        .get("max_particles")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .unwrap_or(burst)
        .clamp(1, MAX_PARTICLES_PER_EMITTER);
    let bursts_per_second = emitter
        .get("bursts_per_second")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(1.0)
        .clamp(0.01, 120.0);
    let interval = bursts_per_second.recip();
    let (life_low, life_high) = value_pair(emitter.get("life"), (1.0, 1.0));
    let longest_life = life_high.clamp(0.01, 120.0);
    let looping = emitter.get("loop").and_then(Value::as_bool).unwrap_or(true);
    let spawn_time = emitter
        .get("spawn_time")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(0.0)
        .max(0.0);
    let newest_burst = (simulation_time / interval).floor() as i64;
    let burst_history =
        ((longest_life / interval).ceil() as usize + 1).min(MAX_PARTICLES_PER_EMITTER);
    let kind = emitter
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or("billboard");
    let mass = emitter
        .get("mass")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(1.0)
        .abs()
        .max(0.01);
    let damping = emitter
        .get("damping")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(0.0)
        .clamp(0.0, 100.0);
    let speed_limit = emitter
        .get("speed_limit")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(0.0)
        .max(0.0);
    let (rotation_low, rotation_high) = value_pair(emitter.get("rotation"), (0.0, 0.0));
    let velocity_stretch = emitter
        .get("velocity_stretch")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(0.0)
        .max(0.0);
    let brightness = emitter
        .get("brightness")
        .and_then(Value::as_f64)
        .map(|value| value as f32)
        .filter(|value| value.is_finite())
        .unwrap_or(1.0)
        .max(0.0);
    let emissive_luma = vec3_value(emitter.get("emissive_color"), Vec3::ONE)
        .max(Vec3::ZERO)
        .dot(Vec3::new(0.2126, 0.7152, 0.0722))
        .max(0.05);
    let sequence_cells = emitter
        .get("sequence")
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .take(2)
                .filter_map(Value::as_u64)
                .product::<u64>()
                .max(1) as f32
        })
        .unwrap_or(1.0);
    // Texture identity remains in the package for a future sprite pass. The
    // line preview below preserves the authored blend and colour meanwhile.
    let _sprite_identity = emitter.get("texture").and_then(Value::as_str).unwrap_or("");
    let blend = emitter
        .get("blend")
        .and_then(Value::as_str)
        .unwrap_or("alpha");

    let mut lines = Vec::new();
    let mut emitted = 0_usize;
    'bursts: for history in 0..burst_history {
        let burst_index = newest_burst - history as i64;
        if burst_index < 0 {
            continue;
        }
        let birth = burst_index as f32 * interval;
        if !looping
            && ((spawn_time <= 0.0 && burst_index > 0) || (spawn_time > 0.0 && birth > spawn_time))
        {
            continue;
        }
        let age = simulation_time - birth;
        if age < 0.0 || age > longest_life {
            continue;
        }
        for particle in 0..burst {
            if emitted >= maximum || lines.len() + 20 > MAX_LINE_VERTICES_PER_EMITTER {
                break 'bursts;
            }
            let seed =
                emitter_index as f32 * 173.17 + burst_index as f32 * 19.91 + particle as f32 * 7.13;
            let life =
                (life_low + (life_high - life_low) * seed_unit(seed + 3.73)).clamp(0.01, 120.0);
            if age > life {
                continue;
            }
            let progress = (age / life).clamp(0.0, 1.0);
            let origin = effect_spawn_position(emitter, seed);
            let acceleration = effect_force(emitter, seed) / mass;
            let initial_direction = Vec3::new(
                seed_signed(seed + 11.1),
                seed_signed(seed + 13.7),
                seed_signed(seed + 17.9),
            )
            .normalize_or(Vec3::Y);
            let initial_speed = vec3_value(emitter.get("spread"), Vec3::splat(0.1))
                .abs()
                .max_element()
                .max(0.01);
            let attenuation = (-damping * age).exp();
            let mut velocity =
                (initial_direction * initial_speed + acceleration * age) * attenuation;
            if speed_limit > 0.0 && velocity.length() > speed_limit {
                velocity = velocity.normalize_or_zero() * speed_limit;
            }
            let center = origin + velocity * age + acceleration * (0.5 * age * age);
            let alpha = curve_sample(emitter.get("alpha_over_life"), progress, 1.0).clamp(0.0, 1.0);
            if alpha <= 0.001 {
                continue;
            }
            let scale_curve = curve_sample(emitter.get("scale_over_life"), progress, 1.0).max(0.0);
            let color_luma = color_curve_sample(emitter.get("color_over_life"), progress)
                .dot(Vec3::new(0.2126, 0.7152, 0.0722))
                .max(0.05);
            let flipbook_pulse = 0.9
                + 0.1
                    * (progress * sequence_cells * std::f32::consts::TAU)
                        .sin()
                        .abs();
            let radius = (effect_scale(emitter, seed)
                * scale_curve
                * alpha.sqrt()
                * (brightness * emissive_luma * color_luma)
                    .clamp(0.25, 4.0)
                    .sqrt()
                * flipbook_pulse)
                .max(minimum_radius);
            let colour = effect_preview_colour(emitter, progress, alpha, brightness, blend);
            let angle = (rotation_low + (rotation_high - rotation_low) * seed_unit(seed + 23.3))
                .to_radians();
            let right = Vec3::new(angle.cos(), angle.sin(), 0.0) * radius;
            let mut up = Vec3::new(-angle.sin(), angle.cos(), 0.0) * radius;
            if velocity_stretch > 0.0 && velocity.length_squared() > 1.0e-8 {
                up += velocity.normalize() * radius * velocity_stretch.min(20.0);
            }
            if kind == "beam" {
                let axis = vec3_value(emitter.get("beam_axis"), Vec3::Y).normalize_or(Vec3::Y);
                let length = emitter
                    .get("beam_length")
                    .and_then(Value::as_f64)
                    .map(|value| value as f32)
                    .filter(|value| value.is_finite())
                    .unwrap_or(0.0)
                    .abs();
                let width = emitter
                    .get("beam_width")
                    .and_then(Value::as_f64)
                    .map(|value| value as f32)
                    .filter(|value| value.is_finite())
                    .unwrap_or(radius)
                    .abs()
                    .max(minimum_radius * 0.5);
                let jitter = emitter
                    .get("beam_jitter")
                    .and_then(Value::as_f64)
                    .map(|value| value as f32)
                    .filter(|value| value.is_finite())
                    .unwrap_or(0.0)
                    .abs();
                let side = axis.cross(Vec3::Y).normalize_or(Vec3::X);
                let segments = 6;
                let mut previous = center;
                for segment in 1..=segments {
                    let fraction = segment as f32 / segments as f32;
                    let point = center
                        + axis * length * fraction
                        + side * seed_signed(seed + segment as f32 * 5.19) * length * jitter;
                    push_effect_line(&mut lines, previous, point, colour);
                    previous = point;
                }
                push_effect_line(
                    &mut lines,
                    center - side * width,
                    center + side * width,
                    colour,
                );
            } else {
                push_effect_line(&mut lines, center - right, center + right, colour);
                push_effect_line(&mut lines, center - up, center + up, colour);
                if kind == "mesh" {
                    let forward = right.cross(up).normalize_or(Vec3::Z) * radius;
                    push_effect_line(&mut lines, center - forward, center + forward, colour);
                }
            }
            emitted += 1;
        }
    }
    if lines.is_empty() {
        // At time zero many authored alpha curves intentionally start at zero.
        // Keep the emitter discoverable instead of presenting an empty preview.
        let radius = minimum_radius.max(0.003);
        let colour = effect_preview_colour(emitter, 0.5, 0.7, brightness, blend);
        for axis in [Vec3::X, Vec3::Y, Vec3::Z] {
            push_effect_line(&mut lines, -axis * radius, axis * radius, colour);
        }
    }
    lines
}

fn placement_matrix(value: &Value) -> Mat4 {
    let translation = vec3_value(value.get("translation"), Vec3::ZERO);
    let degrees = vec3_value(value.get("rotation_degrees"), Vec3::ZERO);
    let rotation = Vec3::new(
        degrees.x.to_radians(),
        degrees.y.to_radians(),
        degrees.z.to_radians(),
    );
    let scale = vec3_value(
        value.get("scale").or_else(|| value.get("scale_xyz")),
        Vec3::ONE,
    );
    let rotation = Quat::from_euler(EulerRot::XYZ, rotation.x, rotation.y, rotation.z);
    Mat4::from_scale_rotation_translation(scale, rotation, translation)
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

fn editable_indices(scene: &Value) -> HashSet<u32> {
    role_indices(scene, "editable")
}
fn reference_indices(scene: &Value) -> HashSet<u32> {
    role_indices(scene, "reference")
}
fn scene_role_indices(scene: &Value) -> HashSet<u32> {
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

fn point_in_triangle(point: Vec2, a: Vec2, b: Vec2, c: Vec2) -> bool {
    let edge = |first: Vec2, second: Vec2, sample: Vec2| {
        (sample.x - second.x) * (first.y - second.y) - (first.x - second.x) * (sample.y - second.y)
    };
    let d1 = edge(point, a, b);
    let d2 = edge(point, b, c);
    let d3 = edge(point, c, a);
    let negative = d1 < -1.0e-4 || d2 < -1.0e-4 || d3 < -1.0e-4;
    let positive = d1 > 1.0e-4 || d2 > 1.0e-4 || d3 > 1.0e-4;
    !(negative && positive)
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
