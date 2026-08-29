#![forbid(unsafe_code)]

mod camera;
#[cfg(test)]
mod headless_stress_tests;
#[cfg(test)]
mod headless_tests;
mod loader;
mod viewport;

use anyhow::{Context, Result};
use camera::{OrbitCamera, StandardView};
use cdmw_archive::ArchiveCatalog;
use cdmw_formats::MeshDocument;
use cdmw_interaction::{
    OperatorController, SelectionDomain, SelectionOperation, SelectionQueryStats,
};
use cdmw_mesh::{History, Selection, VertexHandle, WorkingMesh};
use cdmw_render_wgpu::{ViewMode, WindowRenderer};
use cdmw_texture::{DdsMetadata, TextureRole};
use egui::{Color32, RichText, Stroke};
use glam::{Quat, Vec2, Vec3};
use loader::{LoadEvent, LoadedMesh, Loader};
use std::collections::VecDeque;
use std::env;
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;
use tracing::error;
use viewport::{
    EditGesture, GizmoAxis, PointerEventQueue, SelectionGesture, SelectionTool,
    ViewportPointerEvent, ViewportProjection, ViewportTool, brush_vertex_scope,
};
use winit::application::ApplicationHandler;
use winit::event::{ElementState, MouseButton, WindowEvent};
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop};
use winit::window::{Window, WindowAttributes, WindowId};

const LATENCY_SAMPLE_WINDOW: usize = 256;
const HISTORY_BUDGET_BYTES: usize = 512 * 1024 * 1024;

fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .with_target(false)
        .try_init()
        .ok();
    let (mesh_path, archive_root) = parse_startup_paths();
    let event_loop = EventLoop::new().context("failed to create the Windows event loop")?;
    event_loop.set_control_flow(ControlFlow::Wait);
    let mut application = LabApplication::new(mesh_path, archive_root);
    event_loop
        .run_app(&mut application)
        .context("Rust Mesh Lab event loop failed")?;
    Ok(())
}

fn parse_startup_paths() -> (Option<PathBuf>, Option<PathBuf>) {
    let mut arguments = env::args().skip(1);
    let mut mesh_path = None;
    let mut archive_root = None;
    while let Some(argument) = arguments.next() {
        match argument.as_str() {
            "--mesh" => mesh_path = arguments.next().map(PathBuf::from),
            "--archive-root" => archive_root = arguments.next().map(PathBuf::from),
            _ => {}
        }
    }
    (mesh_path, archive_root)
}

#[derive(Debug, Clone, Copy)]
enum UiAction {
    OpenArchive,
    OpenMesh,
    QueryArchive,
    LoadSelectedArchiveEntry,
    SwitchLod(usize),
    SelectAllVertices,
    SelectAllFaces,
    ClearSelection,
    FrameAll,
    FrameSelected,
    StandardView(StandardView),
    DeleteFaces,
    SubdivideFaces,
    DuplicateFaces,
    Undo,
    Redo,
    ExportObj,
}

struct LodSession {
    mesh: WorkingMesh,
    history: History,
}

struct LabApplication {
    window: Option<Arc<Window>>,
    renderer: Option<WindowRenderer>,
    egui_context: egui::Context,
    egui_state: Option<egui_winit::State>,
    loader: Loader,
    current_generation: u64,
    archive: Option<Arc<ArchiveCatalog>>,
    archive_query: String,
    archive_matches: Vec<usize>,
    archive_total_matches: usize,
    selected_archive_entry: Option<usize>,
    document: Option<MeshDocument>,
    mesh: Option<WorkingMesh>,
    active_lod_index: usize,
    lod_sessions: Vec<Option<LodSession>>,
    texture_metadata: Option<DdsMetadata>,
    texture_label: Option<String>,
    source_label: String,
    status: String,
    history: History,
    operator: OperatorController,
    selection_domain: SelectionDomain,
    selection_operation: SelectionOperation,
    selection_visible_only: bool,
    viewport_rect: Option<egui::Rect>,
    viewport_revision: u64,
    camera: OrbitCamera,
    view_mode: ViewMode,
    show_normals: bool,
    show_bounds: bool,
    viewport_tool: ViewportTool,
    selection_tool: SelectionTool,
    brush_radius: f32,
    brush_strength: f32,
    selection_gesture: Option<SelectionGesture>,
    edit_gesture: Option<EditGesture>,
    projection: Option<ViewportProjection>,
    last_selection_ms: Option<f64>,
    last_edit_ms: Option<f64>,
    last_selection_stats: Option<SelectionQueryStats>,
    selection_latency_ms: VecDeque<f64>,
    edit_latency_ms: VecDeque<f64>,
    pointer_events: PointerEventQueue,
    raw_pointer_position: Option<Vec2>,
    raw_primary_captured: bool,
    raw_orbit_captured: bool,
    raw_pan_captured: bool,
}

impl LabApplication {
    fn new(mesh_path: Option<PathBuf>, archive_root: Option<PathBuf>) -> Self {
        let mut loader = Loader::start();
        let mut status = "Choose an archive root or extracted PAC, PAM, or PAMLOD.".to_owned();
        let mut current_generation = 0;
        if let Some(root) = archive_root {
            match loader.open_archive(root) {
                Ok(generation) => {
                    current_generation = generation;
                    status = "Discovering archive indexes on the native worker…".to_owned();
                }
                Err(error) => status = error.to_string(),
            }
        } else if let Some(path) = mesh_path {
            match loader.load_mesh(path) {
                Ok(generation) => {
                    current_generation = generation;
                    status = "Loading the extracted mesh on the native worker…".to_owned();
                }
                Err(error) => status = error.to_string(),
            }
        }
        Self {
            window: None,
            renderer: None,
            egui_context: egui::Context::default(),
            egui_state: None,
            loader,
            current_generation,
            archive: None,
            archive_query: String::new(),
            archive_matches: Vec::new(),
            archive_total_matches: 0,
            selected_archive_entry: None,
            document: None,
            mesh: None,
            active_lod_index: 0,
            lod_sessions: Vec::new(),
            texture_metadata: None,
            texture_label: None,
            source_label: "No asset loaded".to_owned(),
            status,
            history: History::new(HISTORY_BUDGET_BYTES),
            operator: OperatorController::default(),
            selection_domain: SelectionDomain::Vertex,
            selection_operation: SelectionOperation::Replace,
            selection_visible_only: true,
            viewport_rect: None,
            viewport_revision: 1,
            camera: OrbitCamera::default(),
            view_mode: ViewMode::TexturedSolid,
            show_normals: false,
            show_bounds: false,
            viewport_tool: ViewportTool::Select,
            selection_tool: SelectionTool::Click,
            brush_radius: 48.0,
            brush_strength: 0.18,
            selection_gesture: None,
            edit_gesture: None,
            projection: None,
            last_selection_ms: None,
            last_edit_ms: None,
            last_selection_stats: None,
            selection_latency_ms: VecDeque::new(),
            edit_latency_ms: VecDeque::new(),
            pointer_events: PointerEventQueue::default(),
            raw_pointer_position: None,
            raw_primary_captured: false,
            raw_orbit_captured: false,
            raw_pan_captured: false,
        }
    }

    fn poll_loader(&mut self) -> bool {
        let events = self.loader.try_events().collect::<Vec<_>>();
        let mut changed = false;
        for event in events {
            match event {
                LoadEvent::Progress {
                    generation,
                    progress,
                } if generation == self.current_generation => {
                    self.status = format!(
                        "Archive {}/{} · {} entries · {}",
                        progress.indexes_complete,
                        progress.indexes_total,
                        progress.entries_loaded,
                        progress.label
                    );
                    changed = true;
                }
                LoadEvent::Mesh { generation, result } if generation == self.current_generation => {
                    match *result {
                        Ok(loaded) => self.install_loaded_mesh(loaded),
                        Err(message) => self.status = format!("Mesh load failed: {message}"),
                    }
                    changed = true;
                }
                LoadEvent::Archive { generation, result }
                    if generation == self.current_generation =>
                {
                    match result {
                        Ok(archive) => {
                            self.status = format!(
                                "Opened {} read-only indexes with {} entries",
                                archive.indexes.len(),
                                archive.entries.len()
                            );
                            self.archive_total_matches = archive.entries.len();
                            self.archive_matches.clear();
                            self.selected_archive_entry = None;
                            self.archive = Some(archive.clone());
                            match self
                                .loader
                                .query_archive(archive, self.archive_query.clone())
                            {
                                Ok(generation) => self.current_generation = generation,
                                Err(error) => self.status = error.to_string(),
                            }
                        }
                        Err(message) => self.status = format!("Archive open failed: {message}"),
                    }
                    changed = true;
                }
                LoadEvent::Query {
                    generation,
                    indices,
                    total_matches,
                } if generation == self.current_generation => {
                    self.archive_matches = indices;
                    self.archive_total_matches = total_matches;
                    self.status = format!(
                        "{} archive matches{}",
                        total_matches,
                        if total_matches > self.archive_matches.len() {
                            " (first 20,000 indexed for display)"
                        } else {
                            ""
                        }
                    );
                    changed = true;
                }
                LoadEvent::Export { generation, result }
                    if generation == self.current_generation =>
                {
                    self.status = match result {
                        Ok(path) => format!(
                            "Neutral OBJ/MTL export published after reparse: {}",
                            path.display()
                        ),
                        Err(message) => format!("Neutral export failed: {message}"),
                    };
                    changed = true;
                }
                _ => {}
            }
        }
        if changed && let Some(window) = &self.window {
            window.set_title(format!("CDMW Rust Mesh Lab — {}", self.status).as_str());
        }
        changed
    }

    fn install_loaded_mesh(&mut self, loaded: LoadedMesh) {
        let LoadedMesh {
            path,
            document,
            mesh,
            other_lod_meshes,
            texture,
        } = loaded;
        let editable_lod_count = other_lod_meshes.len().saturating_add(1);
        debug_assert_eq!(editable_lod_count, document.lods.len());
        let per_lod_history_budget = HISTORY_BUDGET_BYTES / editable_lod_count.max(1);

        self.source_label = path.to_string_lossy().replace('\\', "/");
        self.status = format!(
            "Loaded {} vertices and {} faces with {}",
            mesh.vertices().count(),
            mesh.faces().count(),
            document.parser
        );
        self.camera.frame_all(&mesh);
        self.projection = None;
        self.selection_gesture = None;
        self.edit_gesture = None;
        self.pointer_events.clear();
        self.raw_primary_captured = false;
        self.raw_orbit_captured = false;
        self.raw_pan_captured = false;
        if let Some(renderer) = &mut self.renderer {
            renderer.reset_texture();
            renderer.set_view_mode(self.view_mode);
            if let Some(rectangle) = self.viewport_rect {
                renderer.set_camera(self.camera.view_projection(rectangle));
            }
            if let Some(texture) = &texture
                && let Err(error) = renderer.set_dds_texture(&texture.bytes, TextureRole::BaseColor)
            {
                self.status = format!("DDS GPU upload failed: {error}");
            }
            if let Err(error) = renderer.set_snapshot(&mesh.draw_snapshot()) {
                self.status = format!("GPU upload failed: {error}");
            }
        }
        if let Some(texture) = &texture {
            self.status.push_str(
                format!(
                    " · textured {}×{} {:?}",
                    texture.metadata.width, texture.metadata.height, texture.metadata.format
                )
                .as_str(),
            );
        }
        self.history = History::new(per_lod_history_budget);
        self.operator = OperatorController::default();
        self.last_selection_ms = None;
        self.last_edit_ms = None;
        self.last_selection_stats = None;
        self.selection_latency_ms.clear();
        self.edit_latency_ms.clear();
        self.active_lod_index = 0;
        self.lod_sessions = Vec::with_capacity(editable_lod_count);
        self.lod_sessions.push(None);
        self.lod_sessions
            .extend(other_lod_meshes.into_iter().map(|mesh| {
                Some(LodSession {
                    mesh,
                    history: History::new(per_lod_history_budget),
                })
            }));
        self.document = Some(document);
        self.mesh = Some(mesh);
        self.texture_label = texture.as_ref().map(|texture| texture.label.clone());
        self.texture_metadata = texture.map(|texture| texture.metadata);
    }

    fn draw_ui(&mut self, root_ui: &mut egui::Ui) -> Vec<UiAction> {
        let mut actions = Vec::new();
        egui::Panel::top("notice").show(root_ui, |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.label(RichText::new("CDMW Rust Mesh Lab").strong());
                ui.separator();
                ui.label("Unofficial local diagnostic tool. Source game files are opened read-only; edits affect only the in-memory working copy.");
            });
        });
        egui::Panel::bottom("status").show(root_ui, |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.label(RichText::new("Status").strong());
                ui.label(&self.status);
            });
        });
        egui::Panel::left("archive_assets")
            .default_size(310.0)
            .resizable(true)
            .show(root_ui, |ui| {
                ui.heading("Archive / Assets");
                ui.horizontal(|ui| {
                    if ui.button("Open Archive Root…").clicked() {
                        actions.push(UiAction::OpenArchive);
                    }
                    if ui.button("Open Mesh…").clicked() {
                        actions.push(UiAction::OpenMesh);
                    }
                });
                ui.add_space(6.0);
                let search = ui.add(
                    egui::TextEdit::singleline(&mut self.archive_query)
                        .hint_text("Search virtual path, name, extension"),
                );
                if ui.button("Search").clicked()
                    || (search.lost_focus()
                        && ui.input(|input| input.key_pressed(egui::Key::Enter)))
                {
                    actions.push(UiAction::QueryArchive);
                }
                ui.label(format!(
                    "{} matches · {} shown",
                    self.archive_total_matches,
                    self.archive_matches.len()
                ));
                ui.separator();
                if let Some(archive) = &self.archive {
                    for warning in archive.warnings.iter().take(3) {
                        ui.colored_label(Color32::YELLOW, warning);
                    }
                    let row_height = ui.text_style_height(&egui::TextStyle::Body) + 5.0;
                    egui::ScrollArea::vertical().show_rows(
                        ui,
                        row_height,
                        self.archive_matches.len(),
                        |ui, range| {
                            for row in range {
                                let Some(entry_index) = self.archive_matches.get(row).copied()
                                else {
                                    continue;
                                };
                                let Some(entry) = archive.entries.get(entry_index) else {
                                    continue;
                                };
                                let selected = self.selected_archive_entry == Some(entry_index);
                                if ui
                                    .selectable_label(selected, &entry.entry.virtual_path)
                                    .clicked()
                                {
                                    self.selected_archive_entry = Some(entry_index);
                                }
                            }
                        },
                    );
                } else {
                    ui.label(RichText::new("No archive root opened").italics());
                }
            });
        egui::Panel::right("inspector")
            .default_size(330.0)
            .resizable(true)
            .show(root_ui, |ui| {
                ui.heading("Inspector");
                ui.label(RichText::new(&self.source_label).strong());
                if let Some(document) = &self.document {
                    let active_lod = document.lods.get(self.active_lod_index);
                    let vertices = self.mesh.as_ref().map_or(0, |mesh| mesh.vertices().count());
                    let faces = self.mesh.as_ref().map_or(0, |mesh| mesh.faces().count());
                    ui.label(format!("Format: {:?}", document.format));
                    ui.label(format!(
                        "LODs: {} editable / {} declared",
                        document.lods.len(),
                        document.lod_count_reported
                    ));
                    let mut requested_lod = self.active_lod_index;
                    egui::ComboBox::from_label("Editable LOD")
                        .selected_text(active_lod.map_or_else(
                            || "No LOD".to_owned(),
                            |lod| format!("LOD {}", lod.level),
                        ))
                        .show_ui(ui, |ui| {
                            for (index, lod) in document.lods.iter().enumerate() {
                                let lod_mesh = if index == self.active_lod_index {
                                    self.mesh.as_ref()
                                } else {
                                    self.lod_sessions
                                        .get(index)
                                        .and_then(Option::as_ref)
                                        .map(|session| &session.mesh)
                                };
                                let lod_vertices = lod_mesh.map_or(0, |mesh| mesh.vertices().count());
                                let lod_faces = lod_mesh.map_or(0, |mesh| mesh.faces().count());
                                ui.selectable_value(
                                    &mut requested_lod,
                                    index,
                                    format!(
                                        "LOD {} · {lod_vertices} vertices · {lod_faces} faces",
                                        lod.level
                                    ),
                                );
                            }
                        });
                    if requested_lod != self.active_lod_index {
                        actions.push(UiAction::SwitchLod(requested_lod));
                    }
                    ui.label(format!("Active vertices: {vertices}"));
                    ui.label(format!("Active faces: {faces}"));
                    ui.label(format!("Parser: {}", document.parser));
                    for warning in &document.warnings {
                        ui.colored_label(Color32::YELLOW, warning);
                    }
                    if let (Some(label), Some(texture)) =
                        (&self.texture_label, &self.texture_metadata)
                    {
                        ui.separator();
                        ui.label(RichText::new("Viewport texture").strong());
                        ui.label(label);
                        ui.label(format!(
                            "{} × {} · {:?} · {:?} · {} mip(s)",
                            texture.width,
                            texture.height,
                            texture.format,
                            texture.color_space,
                            texture.mip_count
                        ));
                    }
                }
                if let Some(index) = self.selected_archive_entry
                    && let Some(entry) = self
                        .archive
                        .as_ref()
                        .and_then(|archive| archive.entries.get(index))
                {
                    ui.separator();
                    ui.label(RichText::new("Archive entry").strong());
                    ui.label(&entry.entry.virtual_path);
                    ui.label(format!("Stored: {} bytes", entry.entry.stored_size));
                    ui.label(format!("Original: {} bytes", entry.entry.original_size));
                    ui.label(format!("Compression: {}", entry.entry.compression_type()));
                    ui.label(format!("Encryption: {}", entry.entry.encryption_type()));
                    let is_mesh = matches!(
                        entry.entry.extension().to_ascii_lowercase().as_str(),
                        ".pac" | ".pam" | ".pamlod"
                    );
                    if ui
                        .add_enabled(is_mesh, egui::Button::new("Load in viewport"))
                        .on_disabled_hover_text(
                            "Only PAC, PAM, and PAMLOD entries can open in this viewport",
                        )
                        .clicked()
                    {
                        actions.push(UiAction::LoadSelectedArchiveEntry);
                    }
                }
                ui.separator();
                ui.label(RichText::new("Viewport").strong());
                egui::ComboBox::from_label("Preview mode")
                    .selected_text(self.view_mode.label())
                    .show_ui(ui, |ui| {
                        for mode in [
                            ViewMode::TexturedSolid,
                            ViewMode::Solid,
                            ViewMode::SolidWire,
                            ViewMode::Wireframe,
                            ViewMode::Vertices,
                            ViewMode::WireVertices,
                            ViewMode::XRay,
                        ] {
                            ui.selectable_value(&mut self.view_mode, mode, mode.label());
                        }
                    });
                ui.horizontal_wrapped(|ui| {
                    ui.checkbox(&mut self.show_normals, "Normals");
                    ui.checkbox(&mut self.show_bounds, "Bounds");
                    let mut show_bones = false;
                    ui.add_enabled(
                        false,
                        egui::Checkbox::new(&mut show_bones, "Bones"),
                    )
                    .on_disabled_hover_text(
                        "Bone overlay requires a decoded skeleton; PAB/PAC binding is not implemented yet",
                    );
                });
                ui.horizontal_wrapped(|ui| {
                    if ui.button("Frame All").clicked() {
                        actions.push(UiAction::FrameAll);
                    }
                    if ui.button("Frame Selected").clicked() {
                        actions.push(UiAction::FrameSelected);
                    }
                });
                ui.horizontal_wrapped(|ui| {
                    for (label, view) in [
                        ("Front", StandardView::Front),
                        ("Back", StandardView::Back),
                        ("Left", StandardView::Left),
                        ("Right", StandardView::Right),
                        ("Top", StandardView::Top),
                        ("Bottom", StandardView::Bottom),
                    ] {
                        if ui.small_button(label).clicked() {
                            actions.push(UiAction::StandardView(view));
                        }
                    }
                });
                ui.label("RMB orbit · MMB pan · wheel zoom · F frame selected/all");
                ui.separator();
                ui.label(RichText::new("Selection").strong());
                let has_mesh = self.mesh.is_some();
                ui.horizontal(|ui| {
                    ui.selectable_value(
                        &mut self.selection_domain,
                        SelectionDomain::Vertex,
                        "Vertex",
                    );
                    ui.selectable_value(&mut self.selection_domain, SelectionDomain::Edge, "Edge");
                    ui.selectable_value(&mut self.selection_domain, SelectionDomain::Face, "Face");
                });
                egui::ComboBox::from_label("Click operation")
                    .selected_text(format!("{:?}", self.selection_operation))
                    .show_ui(ui, |ui| {
                        for operation in [
                            SelectionOperation::Replace,
                            SelectionOperation::Add,
                            SelectionOperation::Subtract,
                            SelectionOperation::Toggle,
                        ] {
                            ui.selectable_value(
                                &mut self.selection_operation,
                                operation,
                                format!("{operation:?}"),
                            );
                        }
                    });
                ui.horizontal_wrapped(|ui| {
                    for tool in [
                        SelectionTool::Click,
                        SelectionTool::Brush,
                        SelectionTool::Rectangle,
                        SelectionTool::Lasso,
                    ] {
                        let selected = self.viewport_tool == ViewportTool::Select
                            && self.selection_tool == tool;
                        if ui.selectable_label(selected, tool.label()).clicked() {
                            self.viewport_tool = ViewportTool::Select;
                            self.selection_tool = tool;
                        }
                    }
                });
                ui.horizontal(|ui| {
                    ui.label("Depth mode");
                    ui.selectable_value(&mut self.selection_visible_only, true, "Visible");
                    ui.selectable_value(&mut self.selection_visible_only, false, "X-Ray");
                });
                ui.label(if self.selection_visible_only {
                    "Visible uses depth-tested triangle BVH queries."
                } else {
                    "X-Ray includes occluded element candidates."
                });
                ui.horizontal(|ui| {
                    if ui
                        .add_enabled(has_mesh, egui::Button::new("All Vertices"))
                        .on_disabled_hover_text("Load a mesh first")
                        .clicked()
                    {
                        actions.push(UiAction::SelectAllVertices);
                    }
                    if ui
                        .add_enabled(has_mesh, egui::Button::new("All Faces"))
                        .on_disabled_hover_text("Load a mesh first")
                        .clicked()
                    {
                        actions.push(UiAction::SelectAllFaces);
                    }
                    if ui
                        .add_enabled(has_mesh, egui::Button::new("Clear"))
                        .on_disabled_hover_text("Load a mesh first")
                        .clicked()
                    {
                        actions.push(UiAction::ClearSelection);
                    }
                });
                let selected_vertices = self
                    .mesh
                    .as_ref()
                    .map(WorkingMesh::selected_vertex_scope)
                    .map_or(0, |scope| scope.len());
                let selected_faces = self
                    .mesh
                    .as_ref()
                    .map_or(0, |mesh| mesh.selection.faces.len());
                let selected_edges = self
                    .mesh
                    .as_ref()
                    .map_or(0, |mesh| mesh.selection.edges.len());
                ui.label(format!(
                    "Selected: {selected_vertices} vertices · {selected_edges} edges · {selected_faces} faces"
                ));
                if self.selection_tool == SelectionTool::Brush
                    || self.viewport_tool.sculpt_tool().is_some()
                {
                    ui.add(
                        egui::Slider::new(&mut self.brush_radius, 4.0..=240.0)
                            .text("Brush radius px"),
                    );
                }
                ui.separator();
                ui.label(RichText::new("Interactive Edit / Sculpt").strong());
                ui.label(format!("Active tool: {}", self.viewport_tool.label()));
                ui.horizontal_wrapped(|ui| {
                    for tool in [ViewportTool::Move, ViewportTool::Rotate, ViewportTool::Scale] {
                        if ui
                            .add_enabled(
                                selected_vertices > 0,
                                egui::Button::new(tool.label())
                                    .selected(self.viewport_tool == tool),
                            )
                            .on_disabled_hover_text(
                                "Select vertices, edges, or faces before using transforms",
                            )
                            .clicked()
                        {
                            self.viewport_tool = tool;
                        }
                    }
                });
                ui.horizontal_wrapped(|ui| {
                    for tool in [
                        ViewportTool::Grab,
                        ViewportTool::Smooth,
                        ViewportTool::Inflate,
                        ViewportTool::Pinch,
                    ] {
                        if ui
                            .add_enabled(
                                has_mesh,
                                egui::Button::new(tool.label())
                                    .selected(self.viewport_tool == tool),
                            )
                            .on_disabled_hover_text("Load a mesh first")
                            .clicked()
                        {
                            self.viewport_tool = tool;
                        }
                    }
                });
                if self.viewport_tool.sculpt_tool().is_some() {
                    ui.add(
                        egui::Slider::new(&mut self.brush_strength, 0.01..=1.0)
                            .text("Strength"),
                    );
                }
                ui.label("Drag the gizmo for transforms; drag over the surface for sculpt tools. Esc cancels the active gesture.");
                ui.horizontal(|ui| {
                    for (label, action) in [
                        ("Delete", UiAction::DeleteFaces),
                        ("Subdivide", UiAction::SubdivideFaces),
                        ("Duplicate", UiAction::DuplicateFaces),
                    ] {
                        if ui
                            .add_enabled(selected_faces > 0, egui::Button::new(label))
                            .on_disabled_hover_text("Select one or more faces first")
                            .clicked()
                        {
                            actions.push(action);
                        }
                    }
                });
                ui.horizontal(|ui| {
                    if ui
                        .add_enabled(has_mesh, egui::Button::new("Undo"))
                        .clicked()
                    {
                        actions.push(UiAction::Undo);
                    }
                    if ui
                        .add_enabled(has_mesh, egui::Button::new("Redo"))
                        .clicked()
                    {
                        actions.push(UiAction::Redo);
                    }
                });
                if self.last_selection_ms.is_some() || self.last_edit_ms.is_some() {
                    let selection_p95 = percentile95(&self.selection_latency_ms);
                    let edit_p95 = percentile95(&self.edit_latency_ms);
                    let candidates = self.last_selection_stats.map_or_else(
                        || "—".to_owned(),
                        |stats| {
                            format!(
                                "{}/{} · depth triangles {}",
                                stats.candidates_inspected,
                                stats.total_elements,
                                stats.depth_triangles_inspected
                            )
                        },
                    );
                    ui.label(format!(
                        "CPU selection: last {} · p95 {} · indexed candidates {}\nCPU edit operator: last {} · p95 {}",
                        self.last_selection_ms
                            .map_or_else(|| "—".to_owned(), |value| format!("{value:.2} ms")),
                        selection_p95
                            .map_or_else(|| "—".to_owned(), |value| format!("{value:.2} ms")),
                        candidates,
                        self.last_edit_ms
                            .map_or_else(|| "—".to_owned(), |value| format!("{value:.2} ms")),
                        edit_p95
                            .map_or_else(|| "—".to_owned(), |value| format!("{value:.2} ms"))
                    ));
                }
                if ui
                    .add_enabled(has_mesh, egui::Button::new("Export Neutral OBJ…"))
                    .on_disabled_hover_text("Load a mesh first")
                    .clicked()
                {
                    actions.push(UiAction::ExportObj);
                }
            });
        egui::CentralPanel::no_frame().show(root_ui, |ui| {
            let rectangle = ui.max_rect();
            self.update_viewport_rect(rectangle);
            let response = ui.allocate_rect(rectangle, egui::Sense::click_and_drag());
            self.handle_viewport_input(ui, rectangle, &response);
            self.paint_viewport_overlay(ui, rectangle);
            ui.painter().text(
                rectangle.left_top() + egui::vec2(12.0, 12.0),
                egui::Align2::LEFT_TOP,
                format!(
                    "wgpu viewport · D3D12 · {} · {}",
                    self.view_mode.label(),
                    self.viewport_tool.label()
                ),
                egui::TextStyle::Monospace.resolve(ui.style()),
                Color32::from_gray(180),
            );
        });
        actions
    }

    fn handle_actions(&mut self, actions: Vec<UiAction>) {
        let mut publish_mesh = false;
        for action in actions {
            match action {
                UiAction::OpenArchive => self.choose_archive(),
                UiAction::OpenMesh => self.choose_mesh(),
                UiAction::QueryArchive => self.query_archive(),
                UiAction::LoadSelectedArchiveEntry => self.load_selected_archive_entry(),
                UiAction::SwitchLod(index) => self.switch_lod(index),
                UiAction::SelectAllVertices => self.select_all_vertices(),
                UiAction::SelectAllFaces => self.select_all_faces(),
                UiAction::ClearSelection => {
                    if let Some(mesh) = &mut self.mesh {
                        match mesh.set_selection(Selection::default()) {
                            Ok(()) => self.status = "Selection cleared".to_owned(),
                            Err(error) => self.status = error.to_string(),
                        }
                    }
                }
                UiAction::FrameAll => {
                    if let Some(mesh) = &self.mesh {
                        self.camera.frame_all(mesh);
                        self.projection = None;
                        self.status = "Camera framed the complete mesh".to_owned();
                    }
                }
                UiAction::FrameSelected => {
                    if let Some(mesh) = &self.mesh {
                        self.camera.frame_selected(mesh);
                        self.projection = None;
                        self.status = "Camera framed the selected elements".to_owned();
                    }
                }
                UiAction::StandardView(view) => {
                    self.camera.set_standard_view(view);
                    self.projection = None;
                    self.status = format!("Camera switched to {view:?} view");
                }
                UiAction::DeleteFaces => {
                    self.run_topology("Delete faces", |mesh, faces| mesh.delete_faces(faces));
                    publish_mesh = true;
                }
                UiAction::SubdivideFaces => self.run_topology("Subdivide faces", |mesh, faces| {
                    publish_mesh = true;
                    mesh.subdivide_faces(faces).map(|_| ())
                }),
                UiAction::DuplicateFaces => self.run_topology("Duplicate faces", |mesh, faces| {
                    publish_mesh = true;
                    mesh.duplicate_faces(faces).map(|_| ())
                }),
                UiAction::Undo => {
                    if let Some(mesh) = &mut self.mesh {
                        match self.history.undo(mesh) {
                            Ok(()) => {
                                self.status = "Undo restored geometry and selection".to_owned();
                                publish_mesh = true;
                            }
                            Err(error) => self.status = error.to_string(),
                        }
                    }
                    self.projection = None;
                }
                UiAction::Redo => {
                    if let Some(mesh) = &mut self.mesh {
                        match self.history.redo(mesh) {
                            Ok(()) => {
                                self.status = "Redo restored geometry and selection".to_owned();
                                publish_mesh = true;
                            }
                            Err(error) => self.status = error.to_string(),
                        }
                    }
                    self.projection = None;
                }
                UiAction::ExportObj => self.choose_export(),
            }
        }
        if publish_mesh {
            self.publish_mesh_snapshot();
        }
    }

    fn choose_archive(&mut self) {
        if let Some(root) = rfd::FileDialog::new().pick_folder() {
            match self.loader.open_archive(root) {
                Ok(generation) => {
                    self.current_generation = generation;
                    self.status = "Discovering archive indexes on the native worker…".to_owned();
                }
                Err(error) => self.status = error.to_string(),
            }
        }
    }

    fn choose_mesh(&mut self) {
        if let Some(path) = rfd::FileDialog::new()
            .add_filter("Crimson Desert mesh", &["pac", "pam", "pamlod"])
            .pick_file()
        {
            match self.loader.load_mesh(path) {
                Ok(generation) => {
                    self.current_generation = generation;
                    self.status = "Decoding mesh on the native worker…".to_owned();
                }
                Err(error) => self.status = error.to_string(),
            }
        }
    }

    fn query_archive(&mut self) {
        if let Some(archive) = &self.archive {
            match self
                .loader
                .query_archive(archive.clone(), self.archive_query.clone())
            {
                Ok(generation) => {
                    self.current_generation = generation;
                    self.status = "Filtering the archive index…".to_owned();
                }
                Err(error) => self.status = error.to_string(),
            }
        }
    }

    fn load_selected_archive_entry(&mut self) {
        if let (Some(archive), Some(entry_index)) = (&self.archive, self.selected_archive_entry) {
            match self.loader.load_archive_mesh(archive.clone(), entry_index) {
                Ok(generation) => {
                    self.current_generation = generation;
                    self.status = "Reading and decoding the archive mesh read-only…".to_owned();
                }
                Err(error) => self.status = error.to_string(),
            }
        }
    }

    fn switch_lod(&mut self, target_index: usize) {
        if target_index == self.active_lod_index {
            return;
        }
        let Some(target_session) = self
            .lod_sessions
            .get_mut(target_index)
            .and_then(Option::take)
        else {
            self.status = format!("LOD {target_index} is not available for editing");
            return;
        };
        if self.selection_gesture.is_some() || self.edit_gesture.is_some() {
            self.cancel_active_gesture("LOD switch cancelled the active gesture");
        }
        let Some(current_mesh) = self.mesh.take() else {
            self.lod_sessions[target_index] = Some(target_session);
            self.status = "No active mesh is available for the LOD switch".to_owned();
            return;
        };
        let LodSession {
            mesh: target_mesh,
            history: target_history,
        } = target_session;
        let current_history = std::mem::replace(&mut self.history, target_history);
        self.lod_sessions[self.active_lod_index] = Some(LodSession {
            mesh: current_mesh,
            history: current_history,
        });
        self.mesh = Some(target_mesh);
        self.active_lod_index = target_index;
        self.operator = OperatorController::default();
        self.selection_gesture = None;
        self.edit_gesture = None;
        self.pointer_events.clear();
        self.raw_primary_captured = false;
        self.raw_orbit_captured = false;
        self.raw_pan_captured = false;
        self.projection = None;
        let lod_level = self
            .document
            .as_ref()
            .and_then(|document| document.lods.get(target_index))
            .map_or_else(|| target_index.to_string(), |lod| lod.level.to_string());
        if let Some(mesh) = &self.mesh {
            self.status = format!(
                "LOD {lod_level} active · {} vertices · {} faces · edits and Undo history are preserved per LOD",
                mesh.vertices().count(),
                mesh.faces().count()
            );
        }
        self.publish_mesh_snapshot();
    }

    fn select_all_vertices(&mut self) {
        if let Some(mesh) = &mut self.mesh {
            let selection = Selection {
                vertices: mesh.vertices().map(|(handle, _)| handle).collect(),
                ..Selection::default()
            };
            if let Err(error) = mesh.set_selection(selection) {
                self.status = error.to_string();
            }
        }
    }

    fn select_all_faces(&mut self) {
        if let Some(mesh) = &mut self.mesh {
            let selection = Selection {
                faces: mesh.faces().map(|(handle, _)| handle).collect(),
                ..Selection::default()
            };
            if let Err(error) = mesh.set_selection(selection) {
                self.status = error.to_string();
            }
        }
    }

    fn choose_export(&mut self) {
        let Some(mesh) = &self.mesh else {
            return;
        };
        let Some(parent) = rfd::FileDialog::new().pick_folder() else {
            return;
        };
        if let Some(archive) = &self.archive
            && path_is_within(&parent, &archive.root)
        {
            self.status =
                "Neutral export refuses destinations inside the selected game/archive root"
                    .to_owned();
            return;
        }
        let destination = parent.join("cdmw-rust-mesh-export");
        match self.loader.export_obj(mesh.clone(), destination) {
            Ok(generation) => {
                self.current_generation = generation;
                self.status = "Staging and reparsing the neutral OBJ export…".to_owned();
            }
            Err(error) => self.status = error.to_string(),
        }
    }

    fn run_topology(
        &mut self,
        label: &str,
        operation: impl FnOnce(
            &mut WorkingMesh,
            &std::collections::HashSet<cdmw_mesh::FaceHandle>,
        ) -> Result<(), cdmw_mesh::MeshError>,
    ) {
        let Some(mesh) = &mut self.mesh else {
            return;
        };
        let faces = mesh.selection.faces.clone();
        let before = mesh.clone();
        match operation(mesh, &faces).and_then(|()| self.history.commit(label, before, mesh)) {
            Ok(()) => self.status = format!("{label} committed as one undo entry"),
            Err(error) => self.status = error.to_string(),
        }
    }

    fn publish_mesh_snapshot(&mut self) {
        self.projection = None;
        if let (Some(renderer), Some(mesh)) = (&mut self.renderer, &self.mesh)
            && let Err(error) = renderer.set_snapshot(&mesh.draw_snapshot())
        {
            self.status = format!("GPU update failed: {error}");
        }
    }

    fn update_viewport_rect(&mut self, rectangle: egui::Rect) {
        if self.viewport_rect == Some(rectangle) {
            return;
        }
        if self.viewport_rect.is_some()
            && (self.selection_gesture.is_some() || self.edit_gesture.is_some())
        {
            self.cancel_active_gesture("Viewport changed; active gesture cancelled");
        }
        self.viewport_rect = Some(rectangle);
        self.viewport_revision = self.viewport_revision.saturating_add(1);
        self.projection = None;
    }

    fn ensure_projection(&mut self, rectangle: egui::Rect) -> bool {
        let Some(mesh) = &self.mesh else {
            self.projection = None;
            return false;
        };
        let matches = self.projection.as_ref().is_some_and(|projection| {
            projection.matches(mesh, &self.camera, rectangle, self.viewport_revision)
        });
        if !matches {
            self.projection = Some(ViewportProjection::build(
                mesh,
                &self.camera,
                rectangle,
                self.viewport_revision,
            ));
        }
        true
    }

    fn capture_viewport_pointer_event(&mut self, event: &WindowEvent, scale_factor: f64) -> bool {
        match event {
            WindowEvent::CursorMoved { position, .. } => {
                let scale = scale_factor.max(1.0e-6) as f32;
                let next = Vec2::new(position.x as f32 / scale, position.y as f32 / scale);
                let delta = self
                    .raw_pointer_position
                    .map_or(Vec2::ZERO, |previous| next - previous);
                self.raw_pointer_position = Some(next);
                let mut captured = false;
                if self.raw_primary_captured {
                    self.pointer_events
                        .push(ViewportPointerEvent::PrimaryMoved(next));
                    captured = true;
                }
                if self.raw_orbit_captured && delta != Vec2::ZERO {
                    self.pointer_events.push(ViewportPointerEvent::Orbit(delta));
                    captured = true;
                }
                if self.raw_pan_captured && delta != Vec2::ZERO {
                    self.pointer_events.push(ViewportPointerEvent::Pan(delta));
                    captured = true;
                }
                captured
            }
            WindowEvent::MouseInput { state, button, .. } => {
                let Some(point) = self.raw_pointer_position else {
                    return false;
                };
                let inside = self
                    .viewport_rect
                    .is_some_and(|rectangle| rectangle.contains(egui::pos2(point.x, point.y)));
                match (state, button) {
                    (ElementState::Pressed, MouseButton::Left) if inside => {
                        self.raw_primary_captured = true;
                        self.pointer_events
                            .push(ViewportPointerEvent::PrimaryPressed(point));
                        true
                    }
                    (ElementState::Released, MouseButton::Left) if self.raw_primary_captured => {
                        self.raw_primary_captured = false;
                        self.pointer_events
                            .push(ViewportPointerEvent::PrimaryReleased(point));
                        true
                    }
                    (ElementState::Pressed, MouseButton::Right) if inside => {
                        self.raw_orbit_captured = true;
                        true
                    }
                    (ElementState::Released, MouseButton::Right) if self.raw_orbit_captured => {
                        self.raw_orbit_captured = false;
                        true
                    }
                    (ElementState::Pressed, MouseButton::Middle) if inside => {
                        self.raw_pan_captured = true;
                        true
                    }
                    (ElementState::Released, MouseButton::Middle) if self.raw_pan_captured => {
                        self.raw_pan_captured = false;
                        true
                    }
                    _ => false,
                }
            }
            _ => false,
        }
    }

    fn handle_viewport_input(
        &mut self,
        ui: &egui::Ui,
        rectangle: egui::Rect,
        response: &egui::Response,
    ) {
        if ui.input(|input| input.key_pressed(egui::Key::Escape)) {
            self.cancel_active_gesture("Gesture cancelled");
        }

        let geometry_before = self.mesh.as_ref().map(|mesh| mesh.geometry_revision);
        let pointer_events = self.pointer_events.drain().collect::<Vec<_>>();
        for event in pointer_events {
            match event {
                ViewportPointerEvent::PrimaryPressed(point) => {
                    self.begin_primary_gesture(rectangle, point);
                }
                ViewportPointerEvent::PrimaryMoved(point) => {
                    if self.selection_gesture.is_some() || self.edit_gesture.is_some() {
                        self.update_primary_gesture(rectangle, point, false);
                    }
                }
                ViewportPointerEvent::PrimaryReleased(point) => {
                    if self.selection_gesture.is_some() || self.edit_gesture.is_some() {
                        self.update_primary_gesture(rectangle, point, true);
                        self.finish_primary_gesture();
                    }
                }
                ViewportPointerEvent::Orbit(delta) => {
                    self.cancel_active_gesture("Camera orbit took pointer ownership");
                    self.camera.orbit(delta);
                    self.projection = None;
                    self.status = "Camera orbit · release RMB to finish".to_owned();
                }
                ViewportPointerEvent::Pan(delta) => {
                    self.cancel_active_gesture("Camera pan took pointer ownership");
                    self.camera.pan(delta, rectangle);
                    self.projection = None;
                    self.status = "Camera pan · release MMB to finish".to_owned();
                }
            }
        }
        let geometry_after = self.mesh.as_ref().map(|mesh| mesh.geometry_revision);
        if geometry_before != geometry_after {
            self.publish_mesh_snapshot();
        }

        if response.hovered() {
            let wheel = ui.input(|input| input.smooth_scroll_delta.y);
            if wheel.abs() > f32::EPSILON {
                self.cancel_active_gesture("Camera zoom took pointer ownership");
                self.camera.zoom(wheel);
                self.projection = None;
                self.status = "Camera zoom".to_owned();
            }
            if ui.input(|input| input.key_pressed(egui::Key::F))
                && let Some(mesh) = &self.mesh
            {
                if mesh.selected_vertex_scope().is_empty() {
                    self.camera.frame_all(mesh);
                } else {
                    self.camera.frame_selected(mesh);
                }
                self.projection = None;
            }
        }

        if self.selection_gesture.is_some() || self.edit_gesture.is_some() {
            ui.ctx().request_repaint();
        }
    }

    fn begin_primary_gesture(&mut self, rectangle: egui::Rect, point: Vec2) {
        if self.mesh.is_none() || self.selection_gesture.is_some() || self.edit_gesture.is_some() {
            return;
        }
        if self.viewport_tool == ViewportTool::Select {
            if !self.ensure_projection(rectangle) {
                return;
            }
            let started = Instant::now();
            let Some(mesh) = &mut self.mesh else {
                return;
            };
            let mut gesture = SelectionGesture::new(
                mesh,
                self.selection_tool,
                self.selection_domain,
                self.selection_operation,
                self.selection_visible_only,
                point,
                self.brush_radius,
            );
            let result = self.projection.as_ref().map_or(
                Err(cdmw_interaction::InteractionError::InvalidTransition),
                |projection| gesture.update(mesh, &projection.interaction, point),
            );
            let elapsed_ms = started.elapsed().as_secs_f64() * 1_000.0;
            self.last_selection_ms = Some(elapsed_ms);
            self.last_selection_stats = gesture.last_query_stats();
            push_latency_sample(&mut self.selection_latency_ms, elapsed_ms);
            match result {
                Ok(()) => {
                    self.selection_gesture = Some(gesture);
                    self.status = format!(
                        "{} selection preview · release to commit · Esc cancels",
                        self.selection_tool.label()
                    );
                }
                Err(error) => self.status = format!("Selection failed: {error}"),
            }
            return;
        }

        let is_sculpt = self.viewport_tool.sculpt_tool().is_some();
        if is_sculpt && !self.ensure_projection(rectangle) {
            return;
        }
        let Some(mesh) = &self.mesh else {
            return;
        };
        let selected_handles = mesh.selected_vertex_scope();
        let pivot = OrbitCamera::selected_center(mesh).unwrap_or_else(|| self.camera.target());
        let (axis, handles) = if matches!(
            self.viewport_tool,
            ViewportTool::Move | ViewportTool::Rotate | ViewportTool::Scale
        ) {
            if selected_handles.is_empty() {
                self.status = "Select vertices, edges, or faces before transforming".to_owned();
                return;
            }
            let Some(axis) = self.hit_test_gizmo(self.viewport_tool, point, pivot, rectangle)
            else {
                self.status = "Drag a visible gizmo axis, ring, or center handle".to_owned();
                return;
            };
            (axis, selected_handles)
        } else {
            let handles = self
                .projection
                .as_ref()
                .and_then(|projection| {
                    brush_vertex_scope(
                        mesh,
                        &projection.interaction,
                        point,
                        self.brush_radius,
                        true,
                    )
                    .ok()
                })
                .unwrap_or_default();
            if handles.is_empty() {
                self.status = "The sculpt brush has no eligible vertices here".to_owned();
                return;
            }
            (GizmoAxis::Free, handles)
        };
        let pivot = center_of_handles(mesh, &handles).unwrap_or(pivot);
        let gesture_id = match self.operator.begin(mesh, self.viewport_tool.label()) {
            Ok(gesture_id) => gesture_id,
            Err(error) => {
                self.status = format!("Could not start tool: {error}");
                return;
            }
        };
        self.edit_gesture = Some(EditGesture {
            gesture_id,
            tool: self.viewport_tool,
            axis,
            handles,
            pivot,
            last_pointer: point,
            last_sample: point,
        });
        if self.viewport_tool.sculpt_tool().is_some() && self.viewport_tool != ViewportTool::Grab {
            self.update_edit_gesture(rectangle, point, true);
            if self.edit_gesture.is_none() {
                return;
            }
        }
        self.status = format!(
            "{} preview · release to commit · Esc cancels",
            self.viewport_tool.label()
        );
    }

    fn update_primary_gesture(&mut self, rectangle: egui::Rect, point: Vec2, terminal: bool) {
        if self.selection_gesture.is_some() {
            if !self.ensure_projection(rectangle) {
                return;
            }
            let started = Instant::now();
            let Some(mut gesture) = self.selection_gesture.take() else {
                return;
            };
            let defer_query = matches!(
                gesture.tool,
                SelectionTool::Rectangle | SelectionTool::Lasso
            ) && !terminal;
            let result = if defer_query {
                gesture.record_point(point);
                Ok(())
            } else {
                match (&mut self.mesh, &self.projection) {
                    (Some(mesh), Some(projection)) => {
                        gesture.update(mesh, &projection.interaction, point)
                    }
                    _ => Err(cdmw_interaction::InteractionError::InvalidTransition),
                }
            };
            let elapsed_ms = started.elapsed().as_secs_f64() * 1_000.0;
            self.last_selection_ms = Some(elapsed_ms);
            self.last_selection_stats = gesture.last_query_stats();
            push_latency_sample(&mut self.selection_latency_ms, elapsed_ms);
            if let Err(error) = result {
                if let Some(mesh) = &mut self.mesh {
                    gesture.cancel(mesh);
                }
                self.status = format!("Selection cancelled: {error}");
            } else {
                self.selection_gesture = Some(gesture);
            }
        } else if self.edit_gesture.is_some() {
            self.update_edit_gesture(rectangle, point, false);
        }
    }

    fn update_edit_gesture(&mut self, rectangle: egui::Rect, point: Vec2, force: bool) {
        let Some(current) = &self.edit_gesture else {
            return;
        };
        if current.tool.sculpt_tool().is_some() && current.tool != ViewportTool::Grab {
            self.ensure_projection(rectangle);
        }
        let Some(mut gesture) = self.edit_gesture.take() else {
            return;
        };
        let screen_delta = point - gesture.last_pointer;
        let sample_delta = point - gesture.last_sample;
        if !force && screen_delta.length_squared() < 0.25 && sample_delta.length_squared() < 4.0 {
            self.edit_gesture = Some(gesture);
            return;
        }
        let started = Instant::now();
        let result: Result<(), cdmw_interaction::InteractionError> = (|| {
            let mesh = self
                .mesh
                .as_mut()
                .ok_or(cdmw_interaction::InteractionError::InvalidTransition)?;
            match gesture.tool {
                ViewportTool::Move => {
                    let delta = if gesture.axis == GizmoAxis::Free {
                        self.camera.screen_delta_to_world(screen_delta, rectangle)
                    } else {
                        self.camera.axis_drag_delta(
                            gesture.axis.vector(&self.camera),
                            gesture.pivot,
                            screen_delta,
                            rectangle,
                        )
                    };
                    self.operator
                        .translate(mesh, gesture.gesture_id, &gesture.handles, delta)
                }
                ViewportTool::Rotate => {
                    let axis = if gesture.axis == GizmoAxis::Free {
                        self.camera.forward()
                    } else {
                        gesture.axis.vector(&self.camera)
                    };
                    let angle = self.camera.project(gesture.pivot, rectangle).map_or(
                        (screen_delta.x - screen_delta.y) * 0.008,
                        |center| {
                            signed_screen_angle(
                                gesture.last_pointer - center.screen,
                                point - center.screen,
                            )
                        },
                    );
                    self.operator.rotate(
                        mesh,
                        gesture.gesture_id,
                        &gesture.handles,
                        gesture.pivot,
                        Quat::from_axis_angle(axis.normalize_or_zero(), angle),
                    )
                }
                ViewportTool::Scale => {
                    let factor = ((screen_delta.x - screen_delta.y) * 0.01)
                        .exp()
                        .clamp(0.2, 5.0);
                    let scale = match gesture.axis {
                        GizmoAxis::X => Vec3::new(factor, 1.0, 1.0),
                        GizmoAxis::Y => Vec3::new(1.0, factor, 1.0),
                        GizmoAxis::Z => Vec3::new(1.0, 1.0, factor),
                        _ => Vec3::splat(factor),
                    };
                    self.operator.scale(
                        mesh,
                        gesture.gesture_id,
                        &gesture.handles,
                        gesture.pivot,
                        scale,
                    )
                }
                ViewportTool::Grab => {
                    let delta = self.camera.screen_delta_to_world(screen_delta, rectangle);
                    self.operator.sculpt(
                        mesh,
                        gesture.gesture_id,
                        cdmw_interaction::SculptTool::Grab,
                        &gesture.handles,
                        gesture.pivot,
                        delta,
                        1.0,
                    )
                }
                ViewportTool::Smooth | ViewportTool::Inflate | ViewportTool::Pinch => {
                    if let Some(projection) = &self.projection {
                        gesture.handles = brush_vertex_scope(
                            mesh,
                            &projection.interaction,
                            point,
                            self.brush_radius,
                            true,
                        )?;
                    }
                    gesture.pivot = center_of_handles(mesh, &gesture.handles)
                        .ok_or(cdmw_interaction::InteractionError::InvalidShape)?;
                    let tool = gesture
                        .tool
                        .sculpt_tool()
                        .ok_or(cdmw_interaction::InteractionError::InvalidTransition)?;
                    let strength = match tool {
                        cdmw_interaction::SculptTool::Inflate => {
                            self.brush_strength * self.camera.world_units_per_pixel(rectangle) * 8.0
                        }
                        cdmw_interaction::SculptTool::Smooth => self.brush_strength * 0.35,
                        cdmw_interaction::SculptTool::Pinch => self.brush_strength * 0.12,
                        cdmw_interaction::SculptTool::Grab => 1.0,
                    };
                    self.operator.sculpt(
                        mesh,
                        gesture.gesture_id,
                        tool,
                        &gesture.handles,
                        gesture.pivot,
                        Vec3::ZERO,
                        strength,
                    )
                }
                ViewportTool::Select => Err(cdmw_interaction::InteractionError::InvalidTransition),
            }
        })();
        let elapsed_ms = started.elapsed().as_secs_f64() * 1_000.0;
        self.last_edit_ms = Some(elapsed_ms);
        push_latency_sample(&mut self.edit_latency_ms, elapsed_ms);
        match result {
            Ok(()) => {
                gesture.last_pointer = point;
                gesture.last_sample = point;
                self.edit_gesture = Some(gesture);
                self.projection = None;
            }
            Err(error) => {
                self.edit_gesture = Some(gesture);
                self.cancel_active_gesture(format!("Tool failed and was rolled back: {error}"));
            }
        }
    }

    fn finish_primary_gesture(&mut self) {
        if let Some(gesture) = self.selection_gesture.take() {
            let result = self
                .mesh
                .as_ref()
                .map_or(Ok(false), |mesh| gesture.commit(mesh, &mut self.history));
            self.status = match result {
                Ok(true) => format!(
                    "{} selection committed as one undo entry",
                    self.selection_tool.label()
                ),
                Ok(false) => "Selection gesture made no change".to_owned(),
                Err(error) => format!("Selection commit failed: {error}"),
            };
        }
        if let Some(gesture) = self.edit_gesture.take() {
            let result = self.mesh.as_mut().map_or(
                Err(cdmw_interaction::InteractionError::InvalidTransition),
                |mesh| {
                    self.operator
                        .confirm(mesh, &mut self.history, gesture.gesture_id)
                },
            );
            self.status = match result {
                Ok(()) => format!("{} committed as one undo entry", gesture.tool.label()),
                Err(error) => format!("Tool commit failed: {error}"),
            };
        }
    }

    fn cancel_active_gesture(&mut self, reason: impl Into<String>) {
        let reason = reason.into();
        let mut cancelled = false;
        if let Some(gesture) = self.selection_gesture.take()
            && let Some(mesh) = &mut self.mesh
        {
            gesture.cancel(mesh);
            cancelled = true;
        }
        if let Some(gesture) = self.edit_gesture.take()
            && let Some(mesh) = &mut self.mesh
        {
            if let Err(error) = self.operator.cancel(mesh, gesture.gesture_id) {
                self.status = format!("Gesture rollback failed: {error}");
                return;
            }
            cancelled = true;
        }
        if cancelled {
            self.status = reason;
            self.publish_mesh_snapshot();
        }
    }

    fn paint_viewport_overlay(&mut self, ui: &egui::Ui, rectangle: egui::Rect) {
        if !self.ensure_projection(rectangle) {
            return;
        }
        let (Some(mesh), Some(projection)) = (&self.mesh, &self.projection) else {
            return;
        };
        let painter = ui.painter();
        let show_vertices = matches!(self.view_mode, ViewMode::Vertices | ViewMode::WireVertices)
            || (self.viewport_tool == ViewportTool::Select
                && self.selection_domain == SelectionDomain::Vertex);
        if show_vertices {
            for projected in projection
                .vertices
                .values()
                .filter(|point| point.inside_view)
            {
                painter.circle_filled(
                    egui::pos2(projected.screen.x, projected.screen.y),
                    1.4,
                    Color32::from_white_alpha(125),
                );
            }
        }
        for handle in &mesh.selection.vertices {
            if let Some(projected) = projection.vertices.get(handle) {
                painter.circle_filled(
                    egui::pos2(projected.screen.x, projected.screen.y),
                    4.0,
                    Color32::from_rgb(255, 145, 35),
                );
            }
        }
        for handle in &mesh.selection.edges {
            if let Some(edge) = mesh.edge(*handle)
                && let (Some(first), Some(second)) = (
                    projection.vertices.get(&edge.vertices[0]),
                    projection.vertices.get(&edge.vertices[1]),
                )
            {
                painter.line_segment(
                    [
                        egui::pos2(first.screen.x, first.screen.y),
                        egui::pos2(second.screen.x, second.screen.y),
                    ],
                    Stroke::new(2.0, Color32::from_rgb(255, 145, 35)),
                );
            }
        }
        let detailed_faces = mesh.selection.faces.len() <= 4_000;
        for handle in &mesh.selection.faces {
            let Some(face) = mesh.face(*handle) else {
                continue;
            };
            let points = face
                .vertices
                .iter()
                .filter_map(|vertex| projection.vertices.get(vertex))
                .map(|point| egui::pos2(point.screen.x, point.screen.y))
                .collect::<Vec<_>>();
            if points.len() != 3 {
                continue;
            }
            if detailed_faces {
                painter.add(egui::Shape::convex_polygon(
                    points,
                    Color32::from_rgba_unmultiplied(255, 125, 25, 72),
                    Stroke::new(1.0, Color32::from_rgb(255, 145, 35)),
                ));
            } else {
                let center = points
                    .iter()
                    .fold(egui::Vec2::ZERO, |sum, point| sum + point.to_vec2())
                    / 3.0;
                painter.circle_filled(
                    egui::pos2(center.x, center.y),
                    1.2,
                    Color32::from_rgba_unmultiplied(255, 145, 35, 150),
                );
            }
        }
        self.paint_active_shape(ui);
        self.paint_gizmo(ui, rectangle);
    }

    fn paint_active_shape(&self, ui: &egui::Ui) {
        let painter = ui.painter();
        let stroke = Stroke::new(2.0, Color32::from_rgb(80, 190, 255));
        if let Some(gesture) = &self.selection_gesture {
            match gesture.tool {
                SelectionTool::Click | SelectionTool::Brush => {
                    painter.circle_stroke(
                        egui::pos2(gesture.current.x, gesture.current.y),
                        gesture.radius,
                        stroke,
                    );
                }
                SelectionTool::Rectangle => {
                    painter.rect_stroke(
                        egui::Rect::from_two_pos(
                            egui::pos2(gesture.start.x, gesture.start.y),
                            egui::pos2(gesture.current.x, gesture.current.y),
                        ),
                        0.0,
                        stroke,
                        egui::StrokeKind::Inside,
                    );
                }
                SelectionTool::Lasso => {
                    let points = gesture
                        .points
                        .iter()
                        .map(|point| egui::pos2(point.x, point.y))
                        .collect::<Vec<_>>();
                    if points.len() >= 2 {
                        painter.add(egui::Shape::line(points, stroke));
                    }
                }
            }
        } else if (self.selection_tool == SelectionTool::Brush
            || self.viewport_tool.sculpt_tool().is_some())
            && let Some(pointer) = ui.input(|input| input.pointer.hover_pos())
            && self
                .viewport_rect
                .is_some_and(|rectangle| rectangle.contains(pointer))
        {
            painter.circle_stroke(pointer, self.brush_radius, stroke);
        }
    }

    fn paint_gizmo(&self, ui: &egui::Ui, rectangle: egui::Rect) {
        if !matches!(
            self.viewport_tool,
            ViewportTool::Move | ViewportTool::Rotate | ViewportTool::Scale
        ) {
            return;
        }
        let Some(mesh) = &self.mesh else {
            return;
        };
        let Some(pivot) = OrbitCamera::selected_center(mesh) else {
            return;
        };
        let painter = ui.painter();
        if self.viewport_tool == ViewportTool::Rotate {
            for (axis, color) in axis_colors() {
                let points = rotation_ring(&self.camera, pivot, axis, rectangle);
                if points.len() >= 2 {
                    painter.add(egui::Shape::line(
                        points
                            .into_iter()
                            .map(|point| egui::pos2(point.x, point.y))
                            .collect(),
                        Stroke::new(2.0, color),
                    ));
                }
            }
            if let Some(center) = self.camera.project(pivot, rectangle) {
                painter.circle_filled(
                    egui::pos2(center.screen.x, center.screen.y),
                    5.0,
                    Color32::WHITE,
                );
            }
            return;
        }
        for (_axis, start, end, color) in gizmo_segments(&self.camera, pivot, rectangle) {
            painter.line_segment(
                [egui::pos2(start.x, start.y), egui::pos2(end.x, end.y)],
                Stroke::new(3.0, color),
            );
            if self.viewport_tool == ViewportTool::Scale {
                painter.rect_filled(
                    egui::Rect::from_center_size(egui::pos2(end.x, end.y), egui::vec2(9.0, 9.0)),
                    1.0,
                    color,
                );
            } else {
                painter.circle_filled(egui::pos2(end.x, end.y), 5.0, color);
            }
        }
        if let Some(center) = self.camera.project(pivot, rectangle) {
            painter.circle_filled(
                egui::pos2(center.screen.x, center.screen.y),
                6.0,
                Color32::WHITE,
            );
        }
    }

    fn hit_test_gizmo(
        &self,
        tool: ViewportTool,
        pointer: Vec2,
        pivot: Vec3,
        rectangle: egui::Rect,
    ) -> Option<GizmoAxis> {
        let center = self.camera.project(pivot, rectangle)?.screen;
        if pointer.distance(center) <= 11.0 {
            return Some(if tool == ViewportTool::Rotate {
                GizmoAxis::View
            } else {
                GizmoAxis::Free
            });
        }
        if tool == ViewportTool::Rotate {
            return axis_colors()
                .into_iter()
                .filter_map(|(axis, _)| {
                    let points = rotation_ring(&self.camera, pivot, axis, rectangle);
                    let distance = polyline_distance(pointer, &points);
                    (distance <= 9.0).then_some((axis, distance))
                })
                .min_by(|(_, first), (_, second)| first.total_cmp(second))
                .map(|(axis, _)| axis);
        }
        gizmo_segments(&self.camera, pivot, rectangle)
            .into_iter()
            .filter_map(|(axis, start, end, _)| {
                let distance = point_segment_distance(pointer, start, end);
                (distance <= 10.0).then_some((axis, distance))
            })
            .min_by(|(_, first), (_, second)| first.total_cmp(second))
            .map(|(axis, _)| axis)
    }

    fn redraw(&mut self, event_loop: &ActiveEventLoop) {
        let Some(window) = self.window.clone() else {
            return;
        };
        let raw_input = match &mut self.egui_state {
            Some(state) => state.take_egui_input(&window),
            None => return,
        };
        let context = self.egui_context.clone();
        let mut actions = Vec::new();
        let mut full_output = context.run_ui(raw_input, |ui| actions.extend(self.draw_ui(ui)));
        if let Some(state) = &mut self.egui_state {
            state.handle_platform_output_with_event_loop(
                &window,
                event_loop,
                full_output.platform_output,
            );
        }
        self.handle_actions(actions);
        let paint_jobs = context.tessellate(full_output.shapes, full_output.pixels_per_point);
        let camera_matrix = self
            .viewport_rect
            .map(|rectangle| self.camera.view_projection(rectangle));
        let view_mode = self.view_mode;
        let show_normals = self.show_normals;
        let show_bounds = self.show_bounds;
        let render_error = if let Some(renderer) = &mut self.renderer {
            renderer.set_view_mode(view_mode);
            renderer.set_overlays(show_normals, show_bounds);
            if let Some(camera_matrix) = camera_matrix {
                renderer.set_camera(camera_matrix);
            }
            renderer.set_mesh_viewport(self.viewport_rect.map(|rectangle| {
                let scale = full_output.pixels_per_point;
                [
                    rectangle.min.x * scale,
                    rectangle.min.y * scale,
                    rectangle.width() * scale,
                    rectangle.height() * scale,
                ]
            }));
            renderer
                .render_egui(
                    &paint_jobs,
                    &full_output.textures_delta,
                    full_output.pixels_per_point,
                )
                .err()
        } else {
            None
        };
        full_output.textures_delta.clear();
        if let Some(error) = render_error {
            error!("frame failed: {error}");
        }
        if full_output
            .viewport_output
            .get(&egui::ViewportId::ROOT)
            .is_some_and(|output| output.repaint_delay.is_zero())
        {
            window.request_redraw();
        }
    }
}

fn path_is_within(path: &std::path::Path, root: &std::path::Path) -> bool {
    let resolved_path = fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf());
    let resolved_root = fs::canonicalize(root).unwrap_or_else(|_| root.to_path_buf());
    let path_text = resolved_path
        .to_string_lossy()
        .replace('\\', "/")
        .trim_end_matches('/')
        .to_ascii_lowercase();
    let root_text = resolved_root
        .to_string_lossy()
        .replace('\\', "/")
        .trim_end_matches('/')
        .to_ascii_lowercase();
    path_text == root_text || path_text.starts_with(format!("{root_text}/").as_str())
}

fn push_latency_sample(samples: &mut VecDeque<f64>, value: f64) {
    if !value.is_finite() || value < 0.0 {
        return;
    }
    if samples.len() == LATENCY_SAMPLE_WINDOW {
        samples.pop_front();
    }
    samples.push_back(value);
}

fn percentile95(samples: &VecDeque<f64>) -> Option<f64> {
    let mut ordered = samples
        .iter()
        .copied()
        .filter(|value| value.is_finite() && *value >= 0.0)
        .collect::<Vec<_>>();
    if ordered.is_empty() {
        return None;
    }
    ordered.sort_by(f64::total_cmp);
    let index = ((ordered.len() as f64 * 0.95).ceil() as usize)
        .saturating_sub(1)
        .min(ordered.len() - 1);
    ordered.get(index).copied()
}

fn center_of_handles(
    mesh: &WorkingMesh,
    handles: &std::collections::HashSet<VertexHandle>,
) -> Option<Vec3> {
    if handles.is_empty() {
        return None;
    }
    let mut total = Vec3::ZERO;
    let mut count = 0usize;
    for (handle, vertex) in mesh.vertices() {
        if handles.contains(&handle) {
            total += Vec3::from_array(vertex.position);
            count = count.saturating_add(1);
        }
    }
    (count > 0).then_some(total / count as f32)
}

fn axis_colors() -> [(GizmoAxis, Color32); 3] {
    [
        (GizmoAxis::X, Color32::from_rgb(235, 72, 72)),
        (GizmoAxis::Y, Color32::from_rgb(92, 210, 92)),
        (GizmoAxis::Z, Color32::from_rgb(75, 135, 245)),
    ]
}

fn gizmo_segments(
    camera: &OrbitCamera,
    pivot: Vec3,
    rectangle: egui::Rect,
) -> Vec<(GizmoAxis, Vec2, Vec2, Color32)> {
    let Some(start) = camera.project(pivot, rectangle).map(|point| point.screen) else {
        return Vec::new();
    };
    let length = camera.world_units_per_pixel(rectangle) * 72.0;
    axis_colors()
        .into_iter()
        .filter_map(|(axis, color)| {
            camera
                .project(pivot + axis.vector(camera) * length, rectangle)
                .map(|end| (axis, start, end.screen, color))
        })
        .collect()
}

fn rotation_ring(
    camera: &OrbitCamera,
    pivot: Vec3,
    axis: GizmoAxis,
    rectangle: egui::Rect,
) -> Vec<Vec2> {
    let radius = camera.world_units_per_pixel(rectangle) * 58.0;
    let (first, second) = match axis {
        GizmoAxis::X => (Vec3::Y, Vec3::Z),
        GizmoAxis::Y => (Vec3::X, Vec3::Z),
        GizmoAxis::Z => (Vec3::X, Vec3::Y),
        GizmoAxis::View => (camera.right(), camera.up()),
        GizmoAxis::Free => return Vec::new(),
    };
    (0..=64)
        .filter_map(|index| {
            let angle = index as f32 / 64.0 * std::f32::consts::TAU;
            let position = pivot + (first * angle.cos() + second * angle.sin()) * radius;
            camera
                .project(position, rectangle)
                .map(|point| point.screen)
        })
        .collect()
}

fn point_segment_distance(point: Vec2, start: Vec2, end: Vec2) -> f32 {
    let segment = end - start;
    if segment.length_squared() <= 1.0e-6 {
        return point.distance(start);
    }
    let amount = ((point - start).dot(segment) / segment.length_squared()).clamp(0.0, 1.0);
    point.distance(start + segment * amount)
}

fn polyline_distance(point: Vec2, points: &[Vec2]) -> f32 {
    points
        .windows(2)
        .map(|segment| point_segment_distance(point, segment[0], segment[1]))
        .fold(f32::INFINITY, f32::min)
}

fn signed_screen_angle(previous: Vec2, current: Vec2) -> f32 {
    if previous.length_squared() <= 1.0e-4 || current.length_squared() <= 1.0e-4 {
        return 0.0;
    }
    previous.perp_dot(current).atan2(previous.dot(current))
}

impl ApplicationHandler for LabApplication {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if self.window.is_some() {
            return;
        }
        let attributes = WindowAttributes::default()
            .with_title("CDMW Rust Mesh Lab")
            .with_inner_size(winit::dpi::LogicalSize::new(1440.0, 900.0));
        let window = match event_loop.create_window(attributes) {
            Ok(window) => Arc::new(window),
            Err(error) => {
                error!("window creation failed: {error}");
                event_loop.exit();
                return;
            }
        };
        let renderer = match pollster::block_on(WindowRenderer::new(window.clone())) {
            Ok(renderer) => renderer,
            Err(error) => {
                error!("renderer creation failed: {error}");
                event_loop.exit();
                return;
            }
        };
        let adapter = renderer.adapter_report();
        self.status = format!("D3D12 adapter: {} ({})", adapter.name, adapter.driver_info);
        let egui_state = egui_winit::State::new(
            self.egui_context.clone(),
            egui::ViewportId::ROOT,
            window.as_ref(),
            Some(window.scale_factor() as f32),
            window.theme(),
            None,
        );
        window.request_redraw();
        self.renderer = Some(renderer);
        self.egui_state = Some(egui_state);
        self.window = Some(window);
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
        if self
            .egui_state
            .as_mut()
            .is_some_and(|state| state.on_window_event(&window, &event).repaint)
        {
            window.request_redraw();
        }
        if self.capture_viewport_pointer_event(&event, window.scale_factor()) {
            window.request_redraw();
        }
        match event {
            WindowEvent::CloseRequested => event_loop.exit(),
            WindowEvent::Resized(size) => {
                self.cancel_active_gesture("Resize cancelled the active gesture");
                self.pointer_events.clear();
                self.raw_primary_captured = false;
                self.raw_orbit_captured = false;
                self.raw_pan_captured = false;
                if let Some(renderer) = &mut self.renderer {
                    renderer.resize(size);
                }
                self.viewport_revision = self.viewport_revision.saturating_add(1);
                self.projection = None;
                window.request_redraw();
            }
            WindowEvent::Focused(false) => {
                self.cancel_active_gesture("Focus loss cancelled the active gesture");
                self.pointer_events.clear();
                self.raw_primary_captured = false;
                self.raw_orbit_captured = false;
                self.raw_pan_captured = false;
            }
            WindowEvent::RedrawRequested => self.redraw(event_loop),
            _ => {}
        }
    }

    fn about_to_wait(&mut self, _event_loop: &ActiveEventLoop) {
        if self.poll_loader()
            && let Some(window) = &self.window
        {
            window.request_redraw();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quarter_circle_gizmo_drag_produces_a_quarter_turn() {
        let angle = signed_screen_angle(Vec2::new(0.0, -10.0), Vec2::new(10.0, 0.0));
        assert!((angle - std::f32::consts::FRAC_PI_2).abs() < 1.0e-6);
    }

    #[test]
    fn latency_window_is_bounded_and_reports_nearest_rank_p95() {
        let mut samples = VecDeque::new();
        for value in 1..=300 {
            push_latency_sample(&mut samples, f64::from(value));
        }
        assert_eq!(samples.len(), LATENCY_SAMPLE_WINDOW);
        assert_eq!(samples.front(), Some(&45.0));
        assert_eq!(percentile95(&samples), Some(288.0));
    }
}
