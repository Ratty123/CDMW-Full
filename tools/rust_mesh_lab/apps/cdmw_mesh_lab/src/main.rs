#![forbid(unsafe_code)]

mod loader;

use anyhow::{Context, Result};
use cdmw_archive::ArchiveCatalog;
use cdmw_formats::MeshDocument;
use cdmw_interaction::{
    InteractionSnapshot, OperatorController, ProjectedElement, ProjectedHandle, SculptTool,
    SelectionDomain, SelectionOperation, SelectionQuery, SelectionShape, apply_selection,
    query_selection,
};
use cdmw_mesh::{History, Selection, WorkingMesh};
use cdmw_render_wgpu::WindowRenderer;
use cdmw_texture::{DdsMetadata, TextureRole};
use egui::{Color32, RichText};
use loader::{LoadEvent, Loader};
use std::collections::HashMap;
use std::env;
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use tracing::error;
use winit::application::ApplicationHandler;
use winit::event::WindowEvent;
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop};
use winit::window::{Window, WindowAttributes, WindowId};

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
    SelectAllVertices,
    SelectAllFaces,
    ClearSelection,
    TranslateX,
    Grab,
    Smooth,
    Inflate,
    Pinch,
    DeleteFaces,
    SubdivideFaces,
    DuplicateFaces,
    Undo,
    Redo,
    ExportObj,
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
    texture_metadata: Option<DdsMetadata>,
    texture_label: Option<String>,
    source_label: String,
    status: String,
    history: History,
    operator: OperatorController,
    selection_domain: SelectionDomain,
    selection_operation: SelectionOperation,
    viewport_rect: Option<egui::Rect>,
    viewport_revision: u64,
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
            texture_metadata: None,
            texture_label: None,
            source_label: "No asset loaded".to_owned(),
            status,
            history: History::new(512 * 1024 * 1024),
            operator: OperatorController::default(),
            selection_domain: SelectionDomain::Vertex,
            selection_operation: SelectionOperation::Replace,
            viewport_rect: None,
            viewport_revision: 1,
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
                        Ok(loaded) => {
                            self.source_label = loaded.path.to_string_lossy().replace('\\', "/");
                            self.status = format!(
                                "Loaded {} vertices and {} faces with {}",
                                loaded.mesh.vertices().count(),
                                loaded.mesh.faces().count(),
                                loaded.document.parser
                            );
                            if let Some(renderer) = &mut self.renderer {
                                renderer.reset_texture();
                                if let Some(texture) = &loaded.texture
                                    && let Err(error) = renderer
                                        .set_dds_texture(&texture.bytes, TextureRole::BaseColor)
                                {
                                    self.status = format!("DDS GPU upload failed: {error}");
                                }
                                if let Err(error) =
                                    renderer.set_snapshot(&loaded.mesh.draw_snapshot())
                                {
                                    self.status = format!("GPU upload failed: {error}");
                                }
                            }
                            if let Some(texture) = &loaded.texture {
                                self.status.push_str(
                                    format!(
                                        " · textured {}×{} {:?}",
                                        texture.metadata.width,
                                        texture.metadata.height,
                                        texture.metadata.format
                                    )
                                    .as_str(),
                                );
                            }
                            self.history = History::new(512 * 1024 * 1024);
                            self.operator = OperatorController::default();
                            self.document = Some(loaded.document);
                            self.mesh = Some(loaded.mesh);
                            self.texture_label =
                                loaded.texture.as_ref().map(|texture| texture.label.clone());
                            self.texture_metadata = loaded.texture.map(|texture| texture.metadata);
                        }
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
                    let vertices = document
                        .lods
                        .iter()
                        .flat_map(|lod| &lod.submeshes)
                        .map(|mesh| mesh.positions.len())
                        .sum::<usize>();
                    let faces = document
                        .lods
                        .iter()
                        .flat_map(|lod| &lod.submeshes)
                        .map(|mesh| mesh.face_count())
                        .sum::<usize>();
                    ui.label(format!("Format: {:?}", document.format));
                    ui.label(format!("LODs: {}", document.lod_count_reported));
                    ui.label(format!("Vertices: {vertices}"));
                    ui.label(format!("Faces: {faces}"));
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
                ui.label("Viewport click selection: X-Ray CPU snapshot");
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
                ui.label(format!(
                    "Selected scope: {selected_vertices} vertices · {selected_faces} faces"
                ));
                ui.separator();
                ui.label(RichText::new("Edit / Sculpt").strong());
                let can_deform = selected_vertices > 0;
                for (label, action) in [
                    ("Move +X", UiAction::TranslateX),
                    ("Grab +Y", UiAction::Grab),
                    ("Smooth", UiAction::Smooth),
                    ("Inflate", UiAction::Inflate),
                    ("Pinch", UiAction::Pinch),
                ] {
                    if ui
                        .add_enabled(can_deform, egui::Button::new(label))
                        .on_disabled_hover_text("Select vertices, edges, faces, or a submesh first")
                        .clicked()
                    {
                        actions.push(action);
                    }
                }
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
            self.viewport_rect = Some(rectangle);
            let response = ui.allocate_rect(rectangle, egui::Sense::click());
            if response.clicked()
                && let Some(position) = response.interact_pointer_pos()
            {
                self.select_from_viewport(rectangle, position);
            }
            self.paint_selection_overlay(ui, rectangle);
            ui.painter().text(
                rectangle.left_top() + egui::vec2(12.0, 12.0),
                egui::Align2::LEFT_TOP,
                "wgpu viewport · D3D12 · material approximation",
                egui::TextStyle::Monospace.resolve(ui.style()),
                Color32::from_gray(180),
            );
        });
        actions
    }

    fn handle_actions(&mut self, actions: Vec<UiAction>) {
        for action in actions {
            match action {
                UiAction::OpenArchive => self.choose_archive(),
                UiAction::OpenMesh => self.choose_mesh(),
                UiAction::QueryArchive => self.query_archive(),
                UiAction::LoadSelectedArchiveEntry => self.load_selected_archive_entry(),
                UiAction::SelectAllVertices => self.select_all_vertices(),
                UiAction::SelectAllFaces => self.select_all_faces(),
                UiAction::ClearSelection => {
                    if let Some(mesh) = &mut self.mesh
                        && let Err(error) = mesh.set_selection(Selection::default())
                    {
                        self.status = error.to_string();
                    }
                }
                UiAction::TranslateX => self.run_translate(glam::Vec3::new(0.05, 0.0, 0.0)),
                UiAction::Grab => self.run_sculpt(SculptTool::Grab),
                UiAction::Smooth => self.run_sculpt(SculptTool::Smooth),
                UiAction::Inflate => self.run_sculpt(SculptTool::Inflate),
                UiAction::Pinch => self.run_sculpt(SculptTool::Pinch),
                UiAction::DeleteFaces => {
                    self.run_topology("Delete faces", |mesh, faces| mesh.delete_faces(faces));
                }
                UiAction::SubdivideFaces => self.run_topology("Subdivide faces", |mesh, faces| {
                    mesh.subdivide_faces(faces).map(|_| ())
                }),
                UiAction::DuplicateFaces => self.run_topology("Duplicate faces", |mesh, faces| {
                    mesh.duplicate_faces(faces).map(|_| ())
                }),
                UiAction::Undo => {
                    if let Some(mesh) = &mut self.mesh
                        && let Err(error) = self.history.undo(mesh)
                    {
                        self.status = error.to_string();
                    }
                }
                UiAction::Redo => {
                    if let Some(mesh) = &mut self.mesh
                        && let Err(error) = self.history.redo(mesh)
                    {
                        self.status = error.to_string();
                    }
                }
                UiAction::ExportObj => self.choose_export(),
            }
        }
        self.publish_mesh_snapshot();
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

    fn run_translate(&mut self, delta: glam::Vec3) {
        let Some(mesh) = &mut self.mesh else {
            return;
        };
        let scope = mesh.selected_vertex_scope();
        let result = (|| {
            let gesture = self.operator.begin(mesh, "Move")?;
            self.operator.translate(mesh, gesture, &scope, delta)?;
            self.operator.confirm(mesh, &mut self.history, gesture)
        })();
        if let Err(error) = result {
            self.status = error.to_string();
        }
    }

    fn run_sculpt(&mut self, tool: SculptTool) {
        let Some(mesh) = &mut self.mesh else {
            return;
        };
        let scope = mesh.selected_vertex_scope();
        let center = if scope.is_empty() {
            glam::Vec3::ZERO
        } else {
            let total = scope.iter().fold(glam::Vec3::ZERO, |sum, handle| {
                mesh.vertex(*handle)
                    .map_or(sum, |vertex| sum + glam::Vec3::from_array(vertex.position))
            });
            total / scope.len() as f32
        };
        let result = (|| {
            let gesture = self.operator.begin(mesh, format!("{tool:?}"))?;
            self.operator.sculpt(
                mesh,
                gesture,
                tool,
                &scope,
                center,
                glam::Vec3::new(0.0, 0.05, 0.0),
                0.1,
            )?;
            self.operator.confirm(mesh, &mut self.history, gesture)
        })();
        if let Err(error) = result {
            self.status = error.to_string();
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
        if let (Some(renderer), Some(mesh)) = (&mut self.renderer, &self.mesh)
            && let Err(error) = renderer.set_snapshot(&mesh.draw_snapshot())
        {
            self.status = format!("GPU update failed: {error}");
        }
    }

    fn select_from_viewport(&mut self, rectangle: egui::Rect, position: egui::Pos2) {
        let Some(snapshot) = self.interaction_snapshot(rectangle) else {
            return;
        };
        let query = SelectionQuery {
            domain: self.selection_domain,
            operation: self.selection_operation,
            visible_only: false,
            shape: SelectionShape::Click {
                point: glam::Vec2::new(position.x, position.y),
                radius: 10.0,
            },
            geometry_revision: snapshot.geometry_revision,
            topology_generation: snapshot.topology_generation,
            camera_revision: snapshot.camera_revision,
            viewport_revision: snapshot.viewport_revision,
        };
        let result = query_selection(&snapshot, &query).and_then(|selection| {
            let mesh = self
                .mesh
                .as_mut()
                .ok_or(cdmw_interaction::InteractionError::InvalidTransition)?;
            apply_selection(mesh, query.operation, selection)
        });
        if let Err(error) = result {
            self.status = format!("Viewport selection failed: {error}");
        }
    }

    fn interaction_snapshot(&self, rectangle: egui::Rect) -> Option<InteractionSnapshot> {
        let mesh = self.mesh.as_ref()?;
        let positions = projected_positions(mesh, rectangle);
        let mut elements = Vec::new();
        for (handle, _) in mesh.vertices() {
            if let Some(position) = positions.get(&handle) {
                elements.push(ProjectedElement {
                    handle: ProjectedHandle::Vertex(handle),
                    position: *position,
                    depth: 0.0,
                    visible: true,
                });
            }
        }
        for (handle, edge) in mesh.edges() {
            let points = edge
                .vertices
                .iter()
                .filter_map(|vertex| positions.get(vertex))
                .copied()
                .collect::<Vec<_>>();
            if points.len() == 2 {
                elements.push(ProjectedElement {
                    handle: ProjectedHandle::Edge(handle),
                    position: (points[0] + points[1]) * 0.5,
                    depth: 0.0,
                    visible: true,
                });
            }
        }
        for (handle, face) in mesh.faces() {
            let points = face
                .vertices
                .iter()
                .filter_map(|vertex| positions.get(vertex))
                .copied()
                .collect::<Vec<_>>();
            if points.len() == 3 {
                elements.push(ProjectedElement {
                    handle: ProjectedHandle::Face(handle),
                    position: (points[0] + points[1] + points[2]) / 3.0,
                    depth: 0.0,
                    visible: true,
                });
            }
        }
        Some(InteractionSnapshot {
            geometry_revision: mesh.geometry_revision,
            topology_generation: mesh.topology_generation,
            camera_revision: 1,
            viewport_revision: self.viewport_revision,
            viewport_size: glam::Vec2::new(rectangle.width(), rectangle.height()),
            elements,
        })
    }

    fn paint_selection_overlay(&self, ui: &egui::Ui, rectangle: egui::Rect) {
        let Some(snapshot) = self.interaction_snapshot(rectangle) else {
            return;
        };
        let Some(mesh) = &self.mesh else {
            return;
        };
        for element in snapshot.elements {
            let selected = match element.handle {
                ProjectedHandle::Vertex(handle) => mesh.selection.vertices.contains(&handle),
                ProjectedHandle::Edge(handle) => mesh.selection.edges.contains(&handle),
                ProjectedHandle::Face(handle) => mesh.selection.faces.contains(&handle),
            };
            let belongs_to_domain = matches!(
                (self.selection_domain, &element.handle),
                (SelectionDomain::Vertex, ProjectedHandle::Vertex(_))
                    | (SelectionDomain::Edge, ProjectedHandle::Edge(_))
                    | (SelectionDomain::Face, ProjectedHandle::Face(_))
            );
            if belongs_to_domain {
                ui.painter().circle_filled(
                    egui::pos2(element.position.x, element.position.y),
                    if selected { 5.0 } else { 2.5 },
                    if selected {
                        Color32::from_rgb(255, 145, 35)
                    } else {
                        Color32::from_white_alpha(155)
                    },
                );
            }
        }
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
        let render_error = if let Some(renderer) = &mut self.renderer {
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

fn projected_positions(
    mesh: &WorkingMesh,
    rectangle: egui::Rect,
) -> HashMap<cdmw_mesh::VertexHandle, glam::Vec2> {
    let mut minimum = glam::Vec3::splat(f32::INFINITY);
    let mut maximum = glam::Vec3::splat(f32::NEG_INFINITY);
    for (_, vertex) in mesh.vertices() {
        let position = glam::Vec3::from_array(vertex.position);
        minimum = minimum.min(position);
        maximum = maximum.max(position);
    }
    let center = (minimum + maximum) * 0.5;
    let extent = (maximum - minimum).max_element().max(1.0e-6);
    mesh.vertices()
        .map(|(handle, vertex)| {
            let normalized = (glam::Vec3::from_array(vertex.position) - center) * (1.8 / extent);
            let screen = glam::Vec2::new(
                rectangle.center().x + normalized.x * rectangle.width() * 0.5,
                rectangle.center().y - normalized.y * rectangle.height() * 0.5,
            );
            (handle, screen)
        })
        .collect()
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
        match event {
            WindowEvent::CloseRequested => event_loop.exit(),
            WindowEvent::Resized(size) => {
                if let Some(renderer) = &mut self.renderer {
                    renderer.resize(size);
                }
                self.viewport_revision = self.viewport_revision.saturating_add(1);
                window.request_redraw();
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
