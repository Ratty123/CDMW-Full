#![forbid(unsafe_code)]
#![recursion_limit = "256"]

mod camera;
mod cdmw_preview;
mod cdmw_session;
mod cdmw_ui;
mod control_contract;
#[cfg(test)]
mod headless_stress_tests;
#[cfg(test)]
mod headless_tests;
#[cfg(test)]
mod headless_ui_tests;
mod loader;
mod preview_core_material;
mod preview_effects;
mod preview_geometry;
#[cfg(all(test, target_os = "windows"))]
mod preview_gpu_tests;
mod preview_loader;
mod viewport;

use anyhow::{Context, Result, bail};
use camera::{OrbitCamera, StandardView};
use cdmw_archive::ArchiveCatalog;
use cdmw_formats::MeshDocument;
use cdmw_interaction::{
    OperatorController, SelectionCommand, SelectionDomain, SelectionOperation, SelectionQuery,
    SelectionQueryStats, SelectionShape, query_selection, selection_after_command,
};
use cdmw_mesh::{
    DrawSnapshot, History, MeshError, Provenance, Selection, VertexHandle, WorkingMesh,
};
use cdmw_render_wgpu::{
    HeadlessFrameStats, HeadlessMaterialCaptureCamera, HeadlessMaterialCaptureOptions,
    HeadlessMaterialCaptureOutput, HeadlessMaterialCaptureRequest, HeadlessMaterialFactors,
    HeadlessMaterialTexture, IntegratedStartupView, MaterialPreviewFactors, ViewMode,
    WindowRenderer,
};
use cdmw_session::{
    CdmwBridge, CdmwTextureResource, HostEvent, LoadedCdmwSessionPackage, PreviewCoreMaterialGraph,
    SessionMaterialPresentation,
};
use cdmw_texture::DdsMetadata;
use egui::{Color32, RichText, Stroke};
use glam::{Quat, Vec2, Vec3};
use loader::{LoadEvent, LoadedMaterialFactors, LoadedMesh, LoadedTexture, Loader};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet, VecDeque};
use std::env;
use std::fs;
use std::io::ErrorKind;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Instant;
use tracing::error;
use viewport::{
    BrushFalloff, EditGesture, FaceSelectionOverlay, GizmoAxis, PointerEventQueue, SculptSymmetry,
    SculptSymmetryMap, SelectionGesture, SelectionTool, ViewportPointerEvent, ViewportProjection,
    ViewportTool, brush_vertex_weights, brush_vertex_weights_unclipped,
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
        .with_writer(std::io::stderr)
        .try_init()
        .ok();
    let options = parse_startup_options()?;
    if let Some(path) = options.control_contract_json {
        control_contract::write_control_contract(&path)?;
        return Ok(());
    }
    if let Some(manifest_path) = options
        .capture_cdmw_session
        .as_ref()
        .or(options.capture_cdmw_preview_session.as_ref())
    {
        if let Some(output_root) = options.capture_audit_output.as_deref() {
            capture_cdmw_audit_session(
                manifest_path,
                output_root,
                options.capture_cdmw_preview_session.is_some(),
                options.capture_audit_full_model_only,
                options.capture_audit_repetitions.unwrap_or(1),
            )?;
        } else {
            let output_path = options
                .capture_output
                .as_deref()
                .context("CDMW capture requires --capture-output <bmp>")?;
            capture_cdmw_session(
                manifest_path,
                output_path,
                options.capture_report_json.as_deref(),
                options.capture_cdmw_preview_session.is_some(),
                options.capture_camera(),
                options.capture_material_index,
            )?;
        }
        return Ok(());
    }
    if let Some(manifest_path) = options.cdmw_preview_session {
        let parent_hwnd = options
            .embedded_parent_hwnd
            .context("--cdmw-preview-session requires --embedded-parent-hwnd <decimal>")?;
        let event_loop = EventLoop::new().context("failed to create the Windows event loop")?;
        event_loop.set_control_flow(ControlFlow::Wait);
        let mut application = cdmw_preview::PreviewApplication::open(
            &manifest_path,
            parent_hwnd,
            event_loop.create_proxy(),
        )?;
        event_loop
            .run_app(&mut application)
            .context("Rust Archive Preview event loop failed")?;
        return Ok(());
    }
    let event_loop = EventLoop::new().context("failed to create the Windows event loop")?;
    event_loop.set_control_flow(ControlFlow::Wait);
    let mut application = if let Some(manifest_path) = options.cdmw_session {
        let (bridge, document) = CdmwBridge::open(&manifest_path).with_context(|| {
            format!(
                "failed to open CDMW Rust session {}",
                manifest_path.display()
            )
        })?;
        LabApplication::new_cdmw(bridge, document, options.embedded_parent_hwnd)?
    } else {
        LabApplication::new(options.mesh_path, options.archive_root)
    };
    event_loop
        .run_app(&mut application)
        .context("Rust Mesh Lab event loop failed")?;
    Ok(())
}

#[derive(Debug, Default)]
struct StartupOptions {
    mesh_path: Option<PathBuf>,
    archive_root: Option<PathBuf>,
    cdmw_session: Option<PathBuf>,
    cdmw_preview_session: Option<PathBuf>,
    capture_cdmw_session: Option<PathBuf>,
    capture_cdmw_preview_session: Option<PathBuf>,
    capture_output: Option<PathBuf>,
    capture_audit_output: Option<PathBuf>,
    capture_audit_full_model_only: bool,
    capture_audit_repetitions: Option<u32>,
    capture_report_json: Option<PathBuf>,
    capture_yaw_degrees: Option<f32>,
    capture_pitch_degrees: Option<f32>,
    capture_material_index: Option<u32>,
    control_contract_json: Option<PathBuf>,
    embedded_parent_hwnd: Option<u64>,
}

fn parse_startup_options() -> Result<StartupOptions> {
    parse_startup_options_from(env::args().skip(1))
}

fn parse_startup_options_from(
    arguments: impl IntoIterator<Item = String>,
) -> Result<StartupOptions> {
    let mut arguments = arguments.into_iter();
    let mut options = StartupOptions::default();
    while let Some(argument) = arguments.next() {
        match argument.as_str() {
            "--mesh" => options.mesh_path = Some(required_path(&mut arguments, "--mesh")?),
            "--archive-root" => {
                options.archive_root = Some(required_path(&mut arguments, "--archive-root")?);
            }
            "--cdmw-session" => {
                options.cdmw_session = Some(required_path(&mut arguments, "--cdmw-session")?);
            }
            "--cdmw-preview-session" => {
                options.cdmw_preview_session =
                    Some(required_path(&mut arguments, "--cdmw-preview-session")?);
            }
            "--capture-cdmw-session" => {
                options.capture_cdmw_session =
                    Some(required_path(&mut arguments, "--capture-cdmw-session")?);
            }
            "--capture-cdmw-preview-session" => {
                options.capture_cdmw_preview_session = Some(required_path(
                    &mut arguments,
                    "--capture-cdmw-preview-session",
                )?);
            }
            "--capture-output" => {
                options.capture_output = Some(required_path(&mut arguments, "--capture-output")?);
            }
            "--capture-audit-output" => {
                options.capture_audit_output =
                    Some(required_path(&mut arguments, "--capture-audit-output")?);
            }
            "--capture-audit-full-model-only" => {
                options.capture_audit_full_model_only = true;
            }
            "--capture-audit-repetitions" => {
                options.capture_audit_repetitions =
                    Some(required_u32(&mut arguments, "--capture-audit-repetitions")?);
            }
            "--capture-report-json" => {
                options.capture_report_json =
                    Some(required_path(&mut arguments, "--capture-report-json")?);
            }
            "--capture-yaw-degrees" => {
                options.capture_yaw_degrees =
                    Some(required_f32(&mut arguments, "--capture-yaw-degrees")?);
            }
            "--capture-pitch-degrees" => {
                options.capture_pitch_degrees =
                    Some(required_f32(&mut arguments, "--capture-pitch-degrees")?);
            }
            "--capture-material-index" => {
                options.capture_material_index =
                    Some(required_u32(&mut arguments, "--capture-material-index")?);
            }
            "--control-contract-json" => {
                options.control_contract_json =
                    Some(required_path(&mut arguments, "--control-contract-json")?);
            }
            "--embedded-parent-hwnd" => {
                let value = arguments
                    .next()
                    .context("--embedded-parent-hwnd requires a decimal HWND")?;
                let hwnd = value
                    .parse::<u64>()
                    .with_context(|| format!("invalid --embedded-parent-hwnd value '{value}'"))?;
                if hwnd == 0 {
                    bail!("--embedded-parent-hwnd must be greater than zero");
                }
                options.embedded_parent_hwnd = Some(hwnd);
            }
            _ => {}
        }
    }
    if options.cdmw_session.is_some()
        && (options.mesh_path.is_some()
            || options.archive_root.is_some()
            || options.capture_cdmw_session.is_some()
            || options.capture_cdmw_preview_session.is_some()
            || options.cdmw_preview_session.is_some())
    {
        bail!("--cdmw-session cannot be combined with standalone or capture options");
    }
    let capture_requested =
        options.capture_cdmw_session.is_some() || options.capture_cdmw_preview_session.is_some();
    if options.capture_cdmw_session.is_some() && options.capture_cdmw_preview_session.is_some() {
        bail!("only one CDMW capture package type may be supplied");
    }
    if capture_requested
        && (options.mesh_path.is_some()
            || options.archive_root.is_some()
            || options.control_contract_json.is_some()
            || options.cdmw_preview_session.is_some())
    {
        bail!("--capture-cdmw-session cannot be combined with windowed or contract options");
    }
    let capture_output_count = usize::from(options.capture_output.is_some())
        + usize::from(options.capture_audit_output.is_some());
    if capture_requested != (capture_output_count == 1) {
        bail!(
            "a CDMW capture package and exactly one of --capture-output or --capture-audit-output must be supplied together"
        );
    }
    if options.capture_report_json.is_some() && options.capture_output.is_none() {
        bail!("--capture-report-json requires --capture-output");
    }
    if options.capture_audit_full_model_only && options.capture_audit_output.is_none() {
        bail!("--capture-audit-full-model-only requires --capture-audit-output");
    }
    if let Some(repetitions) = options.capture_audit_repetitions {
        if options.capture_audit_output.is_none() {
            bail!("--capture-audit-repetitions requires --capture-audit-output");
        }
        if !options.capture_audit_full_model_only {
            bail!("--capture-audit-repetitions requires --capture-audit-full-model-only");
        }
        if !(1..=100).contains(&repetitions) {
            bail!("--capture-audit-repetitions must be within 1..100");
        }
    }
    if options.capture_yaw_degrees.is_some() != options.capture_pitch_degrees.is_some() {
        bail!("--capture-yaw-degrees and --capture-pitch-degrees must be supplied together");
    }
    if (options.capture_yaw_degrees.is_some() || options.capture_material_index.is_some())
        && options.capture_output.is_none()
    {
        bail!("capture camera and material options require --capture-output");
    }
    if options
        .capture_pitch_degrees
        .is_some_and(|value| value.abs() > 89.0)
    {
        bail!("--capture-pitch-degrees must be within -89..89");
    }
    if options.cdmw_preview_session.is_some()
        && (options.mesh_path.is_some()
            || options.archive_root.is_some()
            || options.control_contract_json.is_some())
    {
        bail!("--cdmw-preview-session cannot be combined with standalone or contract options");
    }
    if options.embedded_parent_hwnd.is_some()
        && options.cdmw_session.is_none()
        && options.cdmw_preview_session.is_none()
    {
        bail!("--embedded-parent-hwnd requires --cdmw-session or --cdmw-preview-session");
    }
    if options.cdmw_preview_session.is_some() && options.embedded_parent_hwnd.is_none() {
        bail!("--cdmw-preview-session requires --embedded-parent-hwnd");
    }
    Ok(options)
}

fn required_path(arguments: &mut impl Iterator<Item = String>, option: &str) -> Result<PathBuf> {
    arguments
        .next()
        .filter(|value| !value.trim().is_empty())
        .map(PathBuf::from)
        .with_context(|| format!("{option} requires a path"))
}

fn required_f32(arguments: &mut impl Iterator<Item = String>, option: &str) -> Result<f32> {
    let value = arguments
        .next()
        .with_context(|| format!("{option} requires a number"))?;
    let parsed = value
        .parse::<f32>()
        .with_context(|| format!("invalid {option} value '{value}'"))?;
    if !parsed.is_finite() {
        bail!("{option} must be finite");
    }
    Ok(parsed)
}

fn required_u32(arguments: &mut impl Iterator<Item = String>, option: &str) -> Result<u32> {
    let value = arguments
        .next()
        .with_context(|| format!("{option} requires a non-negative integer"))?;
    value
        .parse::<u32>()
        .with_context(|| format!("invalid {option} value '{value}'"))
}

impl StartupOptions {
    fn capture_camera(&self) -> Option<HeadlessMaterialCaptureCamera> {
        self.capture_yaw_degrees
            .zip(self.capture_pitch_degrees)
            .map(
                |(yaw_degrees, pitch_degrees)| HeadlessMaterialCaptureCamera {
                    yaw_degrees,
                    pitch_degrees,
                },
            )
    }
}

#[derive(Debug, Clone)]
struct CdmwCapturePaths {
    textured: PathBuf,
    base_color: PathBuf,
    part_id: PathBuf,
    report: PathBuf,
}

static CAPTURE_TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Debug)]
struct CdmwCapturePublication {
    final_paths: CdmwCapturePaths,
    temporary_paths: CdmwCapturePaths,
    published_paths: Vec<PathBuf>,
    committed: bool,
}

impl CdmwCapturePublication {
    fn reserve(final_paths: CdmwCapturePaths) -> Result<Self> {
        let mut reserved = Vec::with_capacity(4);
        for final_path in final_paths.iter() {
            if let Err(error) = reject_existing_capture_target(final_path) {
                for path in reserved {
                    let _ = fs::remove_file(path);
                }
                return Err(error);
            }
            match reserve_capture_temporary(final_path) {
                Ok(path) => reserved.push(path),
                Err(error) => {
                    for path in reserved {
                        let _ = fs::remove_file(path);
                    }
                    return Err(error);
                }
            }
        }
        let temporary_paths = CdmwCapturePaths {
            textured: reserved.remove(0),
            base_color: reserved.remove(0),
            part_id: reserved.remove(0),
            report: reserved.remove(0),
        };
        Ok(Self {
            final_paths,
            temporary_paths,
            published_paths: Vec::new(),
            committed: false,
        })
    }

    fn publish(mut self) -> Result<CdmwCapturePaths> {
        for (temporary, final_path) in self.temporary_paths.iter().zip(self.final_paths.iter()) {
            reject_existing_capture_target(final_path)?;
            fs::rename(temporary, final_path).with_context(|| {
                format!(
                    "failed to atomically publish capture {}",
                    final_path.display()
                )
            })?;
            self.published_paths.push(final_path.to_path_buf());
        }
        self.committed = true;
        Ok(self.final_paths.clone())
    }
}

impl Drop for CdmwCapturePublication {
    fn drop(&mut self) {
        for path in self.temporary_paths.iter() {
            let _ = fs::remove_file(path);
        }
        if !self.committed {
            for path in &self.published_paths {
                let _ = fs::remove_file(path);
            }
        }
    }
}

impl CdmwCapturePaths {
    fn iter(&self) -> impl Iterator<Item = &Path> {
        [
            self.textured.as_path(),
            self.base_color.as_path(),
            self.part_id.as_path(),
            self.report.as_path(),
        ]
        .into_iter()
    }
}

fn cdmw_capture_paths(output: &Path, report: Option<&Path>) -> Result<CdmwCapturePaths> {
    if output
        .extension()
        .and_then(|extension| extension.to_str())
        .is_none_or(|extension| !extension.eq_ignore_ascii_case("bmp"))
    {
        bail!("--capture-output must name a .bmp file");
    }
    let stem = output
        .file_stem()
        .and_then(|value| value.to_str())
        .filter(|value| !value.trim().is_empty())
        .context("--capture-output must have a file name")?;
    let parent = output.parent().unwrap_or_else(|| Path::new(""));
    let report = report.map_or_else(
        || parent.join(format!("{stem}-report.json")),
        Path::to_path_buf,
    );
    if report
        .extension()
        .and_then(|extension| extension.to_str())
        .is_none_or(|extension| !extension.eq_ignore_ascii_case("json"))
    {
        bail!("--capture-report-json must name a .json file");
    }
    Ok(CdmwCapturePaths {
        textured: output.to_path_buf(),
        base_color: parent.join(format!("{stem}-base-color.bmp")),
        part_id: parent.join(format!("{stem}-part-id.bmp")),
        report,
    })
}

fn validated_cdmw_capture_paths(
    paths: &CdmwCapturePaths,
    session_root: &Path,
) -> Result<CdmwCapturePaths> {
    let session_root = fs::canonicalize(session_root).with_context(|| {
        format!(
            "failed to canonicalize CDMW session root {}",
            session_root.display()
        )
    })?;
    let mut resolved = Vec::with_capacity(4);
    let mut distinct = HashSet::with_capacity(4);
    for path in paths.iter() {
        let path = canonical_new_capture_target(path, &session_root)?;
        let key = path.to_string_lossy().to_lowercase();
        if !distinct.insert(key) {
            bail!("capture outputs must name four distinct files");
        }
        resolved.push(path);
    }
    Ok(CdmwCapturePaths {
        textured: resolved.remove(0),
        base_color: resolved.remove(0),
        part_id: resolved.remove(0),
        report: resolved.remove(0),
    })
}

fn canonical_new_capture_target(path: &Path, session_root: &Path) -> Result<PathBuf> {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        env::current_dir()
            .context("failed to resolve the current capture directory")?
            .join(path)
    };
    if absolute
        .components()
        .any(|component| matches!(component, std::path::Component::ParentDir))
    {
        bail!(
            "capture output paths cannot contain parent traversal: {}",
            path.display()
        );
    }
    let file_name = absolute
        .file_name()
        .filter(|name| !name.is_empty())
        .context("capture output must have a file name")?
        .to_owned();
    let requested_parent = absolute
        .parent()
        .context("capture output has no parent directory")?;
    let mut existing_parent = requested_parent;
    let mut missing_components = Vec::new();
    while !existing_parent.exists() {
        let name = existing_parent
            .file_name()
            .context("capture output has no existing ancestor")?;
        missing_components.push(name.to_owned());
        existing_parent = existing_parent
            .parent()
            .context("capture output has no existing ancestor")?;
    }
    let mut resolved_parent = fs::canonicalize(existing_parent).with_context(|| {
        format!(
            "failed to canonicalize capture directory {}",
            existing_parent.display()
        )
    })?;
    for component in missing_components.iter().rev() {
        resolved_parent.push(component);
    }
    if resolved_parent == session_root || resolved_parent.starts_with(session_root) {
        bail!(
            "capture outputs must be outside the CDMW session directory {}",
            session_root.display()
        );
    }
    fs::create_dir_all(&resolved_parent).with_context(|| {
        format!(
            "failed to create capture directory {}",
            resolved_parent.display()
        )
    })?;
    resolved_parent = fs::canonicalize(&resolved_parent).with_context(|| {
        format!(
            "failed to canonicalize capture directory {}",
            resolved_parent.display()
        )
    })?;
    if resolved_parent == session_root || resolved_parent.starts_with(session_root) {
        bail!(
            "capture outputs must be outside the CDMW session directory {}",
            session_root.display()
        );
    }
    let target = resolved_parent.join(file_name);
    reject_existing_capture_target(&target)?;
    Ok(target)
}

fn reject_existing_capture_target(path: &Path) -> Result<()> {
    match fs::symlink_metadata(path) {
        Ok(_) => bail!(
            "capture output already exists and will not be overwritten: {}",
            path.display()
        ),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error)
            .with_context(|| format!("failed to inspect capture output {}", path.display())),
    }
}

fn reserve_capture_temporary(final_path: &Path) -> Result<PathBuf> {
    let parent = final_path
        .parent()
        .context("capture output has no parent directory")?;
    let file_name = final_path
        .file_name()
        .and_then(|name| name.to_str())
        .context("capture output file name is not valid Unicode")?;
    for _ in 0..128 {
        let sequence = CAPTURE_TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let temporary = parent.join(format!(
            ".{file_name}.cdmw-capture-{}-{sequence}.tmp",
            std::process::id()
        ));
        match fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
        {
            Ok(_) => return Ok(temporary),
            Err(error) if error.kind() == ErrorKind::AlreadyExists => continue,
            Err(error) => {
                return Err(error).with_context(|| {
                    format!(
                        "failed to reserve capture temporary file {}",
                        temporary.display()
                    )
                });
            }
        }
    }
    bail!(
        "failed to reserve a unique capture temporary beside {}",
        final_path.display()
    )
}

fn frame_stats_json(stats: &HeadlessFrameStats) -> Value {
    json!({
        "non_background_pixels": stats.non_background_pixels,
        "mean_luma_255": stats.mean_luma_255,
        "p05_luma_255": stats.p05_luma_255,
        "p50_luma_255": stats.p50_luma_255,
        "p95_luma_255": stats.p95_luma_255,
        "mean_chroma_255": stats.mean_chroma_255,
        "near_white_percent": stats.near_white_percent,
        "light_pixel_percent": stats.light_pixel_percent,
    })
}

fn capture_cdmw_session(
    manifest_path: &Path,
    output_path: &Path,
    report_path: Option<&Path>,
    preview_package: bool,
    camera: Option<HeadlessMaterialCaptureCamera>,
    isolated_material_index: Option<u32>,
) -> Result<()> {
    let requested_paths = cdmw_capture_paths(output_path, report_path)?;
    let loaded = if preview_package {
        LoadedCdmwSessionPackage::load_preview(manifest_path)
    } else {
        LoadedCdmwSessionPackage::load(manifest_path)
    };
    let mut package = loaded.with_context(|| {
        format!(
            "failed to load CDMW Rust capture package {}",
            manifest_path.display()
        )
    })?;
    let paths = validated_cdmw_capture_paths(&requested_paths, package.root())?;
    let publication = CdmwCapturePublication::reserve(paths.clone())?;
    let temporary_paths = &publication.temporary_paths;
    let source_lod_index = package.source_lod_index();
    let lod_count = package.document().lods.len();
    let snapshot = WorkingMesh::from_document_lod(package.document(), source_lod_index)
        .with_context(|| format!("capture could not create LOD{source_lod_index}"))?
        .draw_snapshot();
    let session_id = package.manifest().session_id.clone();
    let process_generation = package.manifest().process_generation;
    let source_path = package
        .manifest()
        .source
        .get("path")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned();
    let textures = package.take_textures();
    let presentations = package.take_material_presentations();
    let owned_factors = presentations
        .iter()
        .map(|presentation| {
            (
                cdmw_material_preview_factors(presentation),
                cdmw_material_ownership(presentation, lod_count),
            )
        })
        .collect::<Vec<_>>();
    let texture_uploads = textures
        .iter()
        .map(|texture| HeadlessMaterialTexture {
            bytes: &texture.bytes,
            role: texture.role,
            material_indices_by_lod: &texture.material_indices_by_lod,
        })
        .collect::<Vec<_>>();
    let factor_uploads = owned_factors
        .iter()
        .map(|(factors, ownership)| HeadlessMaterialFactors {
            factors: *factors,
            material_indices_by_lod: ownership,
        })
        .collect::<Vec<_>>();
    let report = pollster::block_on(cdmw_render_wgpu::run_headless_material_capture(
        &snapshot,
        &texture_uploads,
        &factor_uploads,
        HeadlessMaterialCaptureOptions {
            lod_index: source_lod_index,
            camera,
            isolated_material_index,
            ..HeadlessMaterialCaptureOptions::default()
        },
        HeadlessMaterialCaptureOutput {
            textured_bmp: &temporary_paths.textured,
            base_color_bmp: &temporary_paths.base_color,
            part_id_bmp: &temporary_paths.part_id,
            normal_map: None,
            material_response: None,
            layer_mask: None,
        },
    ))
    .context("CDMW Rust material capture failed")?;
    let owners = report
        .owner_coverage
        .iter()
        .map(|owner| {
            json!({
                "material_index": owner.material_index,
                "part_id": owner.part_id,
                "pixel_count": owner.pixel_count,
                "frame_percent": owner.frame_percent,
                "textured_mean_luma_255": owner.textured_mean_luma_255,
                "textured_mean_chroma_255": owner.textured_mean_chroma_255,
                "base_color_mean_luma_255": owner.base_color_mean_luma_255,
                "base_color_mean_chroma_255": owner.base_color_mean_chroma_255,
            })
        })
        .collect::<Vec<_>>();
    let payload = json!({
        "schema": if preview_package {
            "cdmw_rust_preview_material_capture_v1"
        } else {
            "cdmw_rust_mesh_material_capture_v1"
        },
        "renderer": "wgpu_d3d12_rust",
        "session_id": session_id,
        "process_generation": process_generation,
        "source_path": source_path,
        "source_lod_index": source_lod_index,
        "adapter": {
            "name": report.adapter.name,
            "backend": report.adapter.backend,
            "device_type": report.adapter.device_type,
            "driver": report.adapter.driver,
            "driver_info": report.adapter.driver_info,
        },
        "quality": {
            "sample_count": report.sample_count,
            "anisotropy_clamp": report.anisotropy_clamp,
        },
        "dimensions": [report.width, report.height],
        "camera": {
            "yaw_degrees": report.camera_yaw_degrees,
            "pitch_degrees": report.camera_pitch_degrees,
            "mapping": "cdmw_rust_orbit_perspective_v1",
        },
        "isolated_material_index": report.isolated_material_index,
        "dds_textures_uploaded": report.dds_textures_uploaded,
        "texture_bound_materials": report.texture_bound_materials,
        "active_material_bindings": report.active_material_bindings,
        "material_ranges_rendered": report.material_ranges_rendered,
        "frames": {
            "textured": frame_stats_json(&report.textured),
            "base_color": frame_stats_json(&report.base_color),
            "part_id": frame_stats_json(&report.part_id),
        },
        "owner_coverage": owners,
        "outputs": {
            "textured_bmp": paths.textured.display().to_string(),
            "base_color_bmp": paths.base_color.display().to_string(),
            "part_id_bmp": paths.part_id.display().to_string(),
            "report_json": paths.report.display().to_string(),
        }
    });
    fs::write(
        &temporary_paths.report,
        serde_json::to_vec_pretty(&payload)?,
    )
    .with_context(|| {
        format!(
            "failed to write capture report temporary {}",
            temporary_paths.report.display()
        )
    })?;
    let paths = publication.publish()?;
    eprintln!(
        "CDMW Rust material capture wrote {} and {}",
        paths.textured.display(),
        paths.report.display()
    );
    Ok(())
}

const MATERIAL_AUDIT_VIEWS: [(&str, f32, f32); 6] = [
    ("front", 0.0, 0.0),
    ("three-quarter-front", -35.0, 20.0),
    ("side", 90.0, 0.0),
    ("back", 180.0, 0.0),
    ("slightly-above", -35.0, -28.0),
    ("slightly-below", -35.0, 28.0),
];
const MATERIAL_AUDIT_REGION_VIEWS: [(&str, f32, f32); 2] =
    [("front", 0.0, 0.0), ("oblique", -35.0, 20.0)];

#[derive(Debug)]
struct MaterialAuditCapturePaths {
    repetition_index: u32,
    capture_kind: &'static str,
    name: String,
    requested_yaw_degrees: f32,
    requested_pitch_degrees: f32,
    camera: HeadlessMaterialCaptureCamera,
    material_index: Option<u32>,
    textured: PathBuf,
    base_color: PathBuf,
    part_id: PathBuf,
    normal_map: PathBuf,
    material_response: PathBuf,
    layer_mask: PathBuf,
}

fn capture_cdmw_audit_session(
    manifest_path: &Path,
    output_root: &Path,
    preview_package: bool,
    full_model_only: bool,
    repetitions: u32,
) -> Result<()> {
    let audit_started = Instant::now();
    let loaded = if preview_package {
        LoadedCdmwSessionPackage::load_preview(manifest_path)
    } else {
        LoadedCdmwSessionPackage::load(manifest_path)
    };
    let mut package = loaded.with_context(|| {
        format!(
            "failed to load CDMW Rust audit package {}",
            manifest_path.display()
        )
    })?;
    let package_load_complete_ms = audit_started.elapsed().as_secs_f64() * 1_000.0;
    let output_root = create_material_audit_root(output_root, package.root())?;
    let source_lod_index = package.source_lod_index();
    let lod_count = package.document().lods.len();
    let snapshot = WorkingMesh::from_document_lod(package.document(), source_lod_index)
        .with_context(|| format!("audit capture could not create LOD{source_lod_index}"))?
        .draw_snapshot();
    let session_id = package.manifest().session_id.clone();
    let process_generation = package.manifest().process_generation;
    let source_path = package
        .manifest()
        .source
        .get("path")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned();
    let source_dds_metrics = material_audit_source_dds_metrics(
        package.manifest().preview_core_material_graph.as_ref(),
        package.material_composition_metrics(),
    );
    let material_indices = snapshot
        .triangle_materials
        .iter()
        .copied()
        .collect::<BTreeSet<_>>();
    if material_indices.is_empty() {
        bail!("CDMW Rust audit package has no material-owned triangles");
    }
    let base_camera = material_audit_base_camera(&snapshot);
    let textures = package.take_textures();
    let mut runtime_dds_metrics = material_audit_runtime_dds_metrics(&textures)?;
    let expected_physical_upload_count = runtime_dds_metrics
        .get("resource_count")
        .and_then(Value::as_u64)
        .context("runtime DDS metrics omitted the physical upload count")?;
    let presentations = package.take_material_presentations();
    let owned_factors = presentations
        .iter()
        .map(|presentation| {
            (
                cdmw_material_preview_factors(presentation),
                cdmw_material_ownership(presentation, lod_count),
            )
        })
        .collect::<Vec<_>>();
    let texture_uploads = textures
        .iter()
        .map(|texture| HeadlessMaterialTexture {
            bytes: &texture.bytes,
            role: texture.role,
            material_indices_by_lod: &texture.material_indices_by_lod,
        })
        .collect::<Vec<_>>();
    let factor_uploads = owned_factors
        .iter()
        .map(|(factors, ownership)| HeadlessMaterialFactors {
            factors: *factors,
            material_indices_by_lod: ownership,
        })
        .collect::<Vec<_>>();
    let mut capture_paths = Vec::new();
    for repetition_index in 0..repetitions {
        let repetition_root = if repetitions == 1 {
            output_root.clone()
        } else {
            output_root
                .join("warm-repetitions")
                .join(format!("repetition-{:03}", repetition_index + 1))
        };
        for (name, yaw_degrees, pitch_degrees) in MATERIAL_AUDIT_VIEWS {
            capture_paths.push(material_audit_paths(
                &repetition_root.join("full-model"),
                "full_model",
                name,
                base_camera,
                yaw_degrees,
                pitch_degrees,
                None,
                repetition_index,
            ));
        }
    }
    if !full_model_only {
        for material_index in material_indices.iter().copied() {
            let material_root = output_root
                .join("material-regions")
                .join(format!("material-{material_index:04}"));
            for (name, yaw_degrees, pitch_degrees) in MATERIAL_AUDIT_REGION_VIEWS {
                capture_paths.push(material_audit_paths(
                    &material_root,
                    "material_region",
                    name,
                    base_camera,
                    yaw_degrees,
                    pitch_degrees,
                    Some(material_index),
                    0,
                ));
            }
        }
    }
    for paths in &capture_paths {
        fs::create_dir_all(
            paths
                .textured
                .parent()
                .context("material audit capture path has no parent")?,
        )?;
    }
    let requests = capture_paths
        .iter()
        .map(|paths| {
            let isolated_region = paths.material_index.is_some();
            HeadlessMaterialCaptureRequest {
                options: HeadlessMaterialCaptureOptions {
                    width: 768,
                    height: 768,
                    lod_index: source_lod_index,
                    camera: Some(paths.camera),
                    isolated_material_index: paths.material_index,
                },
                output: HeadlessMaterialCaptureOutput {
                    textured_bmp: &paths.textured,
                    base_color_bmp: &paths.base_color,
                    part_id_bmp: &paths.part_id,
                    normal_map: isolated_region.then_some(paths.normal_map.as_path()),
                    material_response: isolated_region.then_some(paths.material_response.as_path()),
                    layer_mask: isolated_region.then_some(paths.layer_mask.as_path()),
                },
            }
        })
        .collect::<Vec<_>>();
    let renderer_start_offset_ms = audit_started.elapsed().as_secs_f64() * 1_000.0;
    let renderer_started = Instant::now();
    let reports = pollster::block_on(cdmw_render_wgpu::run_headless_material_capture_batch(
        &snapshot,
        &texture_uploads,
        &factor_uploads,
        &requests,
    ))
    .context("CDMW Rust material audit capture failed")?;
    let physical_uploads_conserved = reports
        .iter()
        .all(|report| u64::from(report.dds_textures_uploaded) == expected_physical_upload_count);
    if let Some(metrics) = runtime_dds_metrics.as_object_mut() {
        metrics.insert(
            "renderer_reported_upload_count".to_owned(),
            json!(
                reports
                    .first()
                    .map_or(0, |report| report.dds_textures_uploaded)
            ),
        );
        metrics.insert(
            "renderer_uploads_match_unique_binaries".to_owned(),
            json!(physical_uploads_conserved),
        );
    }
    let captures = capture_paths
        .iter()
        .zip(reports.iter())
        .map(|(paths, report)| material_audit_capture_json(paths, report, &output_root))
        .collect::<Result<Vec<_>>>()?;
    let full_model_report_count = usize::try_from(repetitions)
        .ok()
        .and_then(|count| count.checked_mul(MATERIAL_AUDIT_VIEWS.len()))
        .context("material audit repetition count overflowed")?;
    let warm_repetition_wall_ms = reports[..full_model_report_count]
        .chunks(MATERIAL_AUDIT_VIEWS.len())
        .map(|reports| reports.iter().map(|report| report.wall_ms).sum::<f64>())
        .collect::<Vec<_>>();
    let manifest_bytes = fs::read(manifest_path).with_context(|| {
        format!(
            "failed to hash CDMW Rust audit manifest {}",
            manifest_path.display()
        )
    })?;
    let adapter = reports
        .first()
        .map(|report| {
            json!({
                "name": report.adapter.name,
                "backend": report.adapter.backend,
                "device_type": report.adapter.device_type,
                "driver": report.adapter.driver,
                "driver_info": report.adapter.driver_info,
            })
        })
        .unwrap_or(Value::Null);
    let first_report = reports
        .first()
        .context("CDMW Rust material audit produced no capture reports")?;
    let renderer_device_ready_ms = renderer_start_offset_ms + first_report.renderer_device_ready_ms;
    let texture_resources_ready_ms =
        renderer_start_offset_ms + first_report.texture_resources_ready_ms;
    let first_textured_frame_ms = renderer_start_offset_ms + first_report.first_textured_frame_ms;
    let audit_completion_ms = audit_started.elapsed().as_secs_f64() * 1_000.0;
    let payload = json!({
        "schema": "cdmw_rust_material_audit_capture_v2",
        "compatible_schemas": ["cdmw_rust_material_audit_capture_v1"],
        "ok": true,
        "renderer": "wgpu_d3d12_rust",
        "preview_package": preview_package,
        "session_id": session_id,
        "process_generation": process_generation,
        "source_path": source_path,
        "source_lod_index": source_lod_index,
        "source_manifest": {
            "path": manifest_path.display().to_string(),
            "bytes": manifest_bytes.len(),
            "sha256": format!("{:x}", Sha256::digest(&manifest_bytes)),
        },
        "camera_mapping": "cdmw_integrated_startup_relative_perspective_v1",
        "base_camera": {
            "yaw_degrees": base_camera.yaw.to_degrees(),
            "pitch_degrees": base_camera.pitch.to_degrees(),
        },
        "fixed_full_model_view_count": MATERIAL_AUDIT_VIEWS.len(),
        "repetition_count": repetitions,
        "material_indices": material_indices,
        "full_model_only": full_model_only,
        "material_region_view_count": if full_model_only { 0 } else { MATERIAL_AUDIT_REGION_VIEWS.len() },
        "capture_count": captures.len(),
        "warm_cache_proof": {
            "schema": "cdmw_rust_warm_material_capture_v1",
            "valid": repetitions > 1 && full_model_only,
            "package_load_count": 1,
            "renderer_device_count": 1,
            "renderer_batch_count": 1,
            "texture_upload_pass_count": 1,
            "dds_textures_uploaded_once_for_repetition_set": physical_uploads_conserved,
            "package_reloads_between_repetitions": 0,
            "resource_reloads_between_repetitions": 0,
            "full_model_views_per_repetition": MATERIAL_AUDIT_VIEWS.len(),
            "per_repetition_wall_ms": warm_repetition_wall_ms,
        },
        "dds_resources_uploaded_once_for_capture_set": physical_uploads_conserved,
        "source_dds": source_dds_metrics,
        "runtime_dds": runtime_dds_metrics,
        "adapter": adapter,
        "phase_timings": {
            "schema": "cdmw_rust_material_capture_phase_timings_v1",
            "package_load_complete_ms": package_load_complete_ms,
            "renderer_device_ready_ms": renderer_device_ready_ms,
            "texture_resources_ready_ms": texture_resources_ready_ms,
            "first_textured_frame_ms": first_textured_frame_ms,
            "audit_completion_ms": audit_completion_ms,
        },
        "wall_ms": renderer_started.elapsed().as_secs_f64() * 1_000.0,
        "captures": captures,
    });
    let report_path = output_root.join("audit-report.json");
    fs::write(&report_path, serde_json::to_vec_pretty(&payload)?).with_context(|| {
        format!(
            "failed to write material audit report {}",
            report_path.display()
        )
    })?;
    eprintln!(
        "CDMW Rust material audit wrote {} captures to {}",
        requests.len(),
        output_root.display()
    );
    Ok(())
}

fn material_audit_source_dds_metrics(
    graph: Option<&PreviewCoreMaterialGraph>,
    measured: &crate::preview_core_material::PreviewCoreMaterialCompositionMetrics,
) -> Value {
    let Some(graph) = graph else {
        return json!({
            "available": false,
            "each_source_binary_decoded_at_most_once": false,
        });
    };
    let each_source_binary_decoded_at_most_once = measured.source_dds_decode_count
        <= measured.unique_source_dds_count
        && u64::try_from(measured.decoded_source_sha256.len())
            .is_ok_and(|count| count == measured.source_dds_decode_count)
        && measured
            .decoded_source_sha256
            .iter()
            .collect::<BTreeSet<_>>()
            .len()
            == measured.decoded_source_sha256.len();
    let full_decode_complete = graph.quality != "full"
        || measured.source_dds_decode_count == measured.unique_source_dds_count;
    json!({
        "available": true,
        "quality": graph.quality,
        "logical_texture_reference_count": graph.source_edge_count,
        "unique_source_dds_count": graph.unique_resource_count,
        "copied_source_dds_count": graph.copied_resource_count,
        "unique_source_dds_bytes": graph.unique_resource_bytes,
        "reused_logical_reference_count": graph.source_edge_count.saturating_sub(graph.unique_resource_count),
        "decode_cache_key": "sha256",
        "measurement": "actual_rust_source_dds_decode_events_v1",
        "observed_source_reference_count": measured.source_reference_count,
        "observed_unique_source_dds_count": measured.unique_source_dds_count,
        "observed_source_dds_decode_count": measured.source_dds_decode_count,
        "decoded_source_bytes": measured.decoded_source_bytes,
        "decoded_rgba8_bytes": measured.decoded_rgba8_bytes,
        "decoded_source_sha256": measured.decoded_source_sha256,
        "each_source_binary_decoded_at_most_once": each_source_binary_decoded_at_most_once,
        "full_source_decode_complete": full_decode_complete,
    })
}

fn material_audit_runtime_dds_metrics(resources: &[CdmwTextureResource]) -> Result<Value> {
    let mut logical_keys = BTreeMap::<(String, String), usize>::new();
    let mut binaries = BTreeMap::<String, (usize, usize)>::new();
    let mut logical_resource_bytes = 0_u64;
    for resource in resources {
        let sha256 = format!("{:x}", Sha256::digest(&resource.bytes));
        let role = format!("{:?}", resource.role);
        *logical_keys.entry((sha256.clone(), role)).or_default() += 1;
        let payload_bytes = resource
            .bytes
            .len()
            .checked_sub(resource.metadata.payload_offset)
            .context("runtime DDS payload offset exceeds its binary length")?;
        binaries
            .entry(sha256)
            .or_insert((resource.bytes.len(), payload_bytes));
        logical_resource_bytes = logical_resource_bytes
            .checked_add(u64::try_from(resource.bytes.len())?)
            .context("runtime DDS byte count overflow")?;
    }
    let logical_duplicate_binding_count = logical_keys
        .values()
        .map(|count| count.saturating_sub(1))
        .sum::<usize>();
    let unique_binary_bytes = binaries.values().try_fold(0_u64, |total, (bytes, _)| {
        total
            .checked_add(u64::try_from(*bytes)?)
            .context("unique runtime DDS byte count overflow")
    })?;
    let reported_gpu_resident_bytes =
        binaries
            .values()
            .try_fold(0_u64, |total, (_, payload_bytes)| {
                total
                    .checked_add(u64::try_from(*payload_bytes)?)
                    .context("runtime GPU-resident DDS byte count overflow")
            })?;
    Ok(json!({
        "resource_count": binaries.len(),
        "logical_resource_count": resources.len(),
        "logical_binding_key_count": logical_keys.len(),
        "logical_duplicate_binding_count": logical_duplicate_binding_count,
        "unique_upload_key_count": binaries.len(),
        "duplicate_upload_key_count": 0,
        "unique_binary_count": binaries.len(),
        "reused_logical_resource_count": resources.len().saturating_sub(binaries.len()),
        "logical_resource_bytes": logical_resource_bytes,
        "uploaded_resource_bytes": unique_binary_bytes,
        "reported_gpu_resident_bytes": reported_gpu_resident_bytes,
        "unique_binary_bytes": unique_binary_bytes,
        "upload_key": "dds_sha256",
        "role_specific_sampling_views_share_one_physical_upload": true,
        "no_duplicate_upload_keys": true,
    }))
}

fn create_material_audit_root(output_root: &Path, session_root: &Path) -> Result<PathBuf> {
    if output_root
        .components()
        .any(|component| matches!(component, std::path::Component::ParentDir))
    {
        bail!(
            "material audit output cannot contain parent traversal: {}",
            output_root.display()
        );
    }
    let absolute = if output_root.is_absolute() {
        output_root.to_path_buf()
    } else {
        env::current_dir()
            .context("failed to resolve current material audit directory")?
            .join(output_root)
    };
    if absolute.exists() {
        bail!(
            "material audit output already exists; refusing replacement: {}",
            absolute.display()
        );
    }
    let parent = absolute
        .parent()
        .context("material audit output has no parent directory")?;
    fs::create_dir_all(parent)?;
    let parent = fs::canonicalize(parent)?;
    let name = absolute
        .file_name()
        .context("material audit output has no directory name")?;
    let resolved = parent.join(name);
    let session_root = fs::canonicalize(session_root)?;
    if resolved.starts_with(&session_root) {
        bail!("material audit evidence must be outside the source package");
    }
    fs::create_dir(&resolved)?;
    Ok(resolved)
}

fn material_audit_base_camera(snapshot: &DrawSnapshot) -> IntegratedStartupView {
    let mut minimum = Vec3::splat(f32::INFINITY);
    let mut maximum = Vec3::splat(f32::NEG_INFINITY);
    let mut found = false;
    for position in snapshot.positions.iter().copied().map(Vec3::from_array) {
        if position.is_finite() {
            minimum = minimum.min(position);
            maximum = maximum.max(position);
            found = true;
        }
    }
    cdmw_render_wgpu::integrated_startup_view(if found { maximum - minimum } else { Vec3::ONE })
}

fn material_audit_paths(
    root: &Path,
    capture_kind: &'static str,
    name: &str,
    base_camera: IntegratedStartupView,
    requested_yaw_degrees: f32,
    requested_pitch_degrees: f32,
    material_index: Option<u32>,
    repetition_index: u32,
) -> MaterialAuditCapturePaths {
    let camera = HeadlessMaterialCaptureCamera {
        yaw_degrees: base_camera.yaw.to_degrees() + requested_yaw_degrees,
        pitch_degrees: (base_camera.pitch.to_degrees() + requested_pitch_degrees)
            .clamp(-89.0, 89.0),
    };
    MaterialAuditCapturePaths {
        repetition_index,
        capture_kind,
        name: name.to_owned(),
        requested_yaw_degrees,
        requested_pitch_degrees,
        camera,
        material_index,
        textured: root.join(format!("{name}.png")),
        base_color: root.join(format!("{name}-base-color.png")),
        part_id: root.join(format!("{name}-part-id.png")),
        normal_map: root.join(format!("{name}-normal-map.png")),
        material_response: root.join(format!("{name}-material-response.png")),
        layer_mask: root.join(format!("{name}-layer-mask.png")),
    }
}

fn material_audit_capture_json(
    paths: &MaterialAuditCapturePaths,
    report: &cdmw_render_wgpu::HeadlessMaterialCaptureReport,
    output_root: &Path,
) -> Result<Value> {
    let owners = report
        .owner_coverage
        .iter()
        .map(|owner| {
            json!({
                "material_index": owner.material_index,
                "part_id": owner.part_id,
                "pixel_count": owner.pixel_count,
                "frame_percent": owner.frame_percent,
                "textured_mean_luma_255": owner.textured_mean_luma_255,
                "textured_mean_chroma_255": owner.textured_mean_chroma_255,
                "base_color_mean_luma_255": owner.base_color_mean_luma_255,
                "base_color_mean_chroma_255": owner.base_color_mean_chroma_255,
            })
        })
        .collect::<Vec<_>>();
    let normal_map_output = report
        .normal_map
        .as_ref()
        .map(|_| material_audit_file_evidence(&paths.normal_map, output_root))
        .transpose()?;
    let material_response_output = report
        .material_response
        .as_ref()
        .map(|_| material_audit_file_evidence(&paths.material_response, output_root))
        .transpose()?;
    let layer_mask_output = report
        .layer_mask
        .as_ref()
        .map(|_| material_audit_file_evidence(&paths.layer_mask, output_root))
        .transpose()?;
    Ok(json!({
        "name": paths.name,
        "capture_kind": paths.capture_kind,
        "repetition_index": paths.repetition_index,
        "material_index": report.isolated_material_index,
        "yaw": paths.requested_yaw_degrees,
        "pitch": paths.requested_pitch_degrees,
        "renderer_yaw": report.camera_yaw_degrees,
        "renderer_pitch": report.camera_pitch_degrees,
        "camera_mapping": "cdmw_integrated_startup_relative_perspective_v1",
        "dimensions": [report.width, report.height],
        "dds_textures_uploaded": report.dds_textures_uploaded,
        "active_material_bindings": report.active_material_bindings,
        "material_ranges_rendered": report.material_ranges_rendered,
        "renderer_device_ready_ms": report.renderer_device_ready_ms,
        "texture_resources_ready_ms": report.texture_resources_ready_ms,
        "first_textured_frame_ms": report.first_textured_frame_ms,
        "wall_ms": report.wall_ms,
        "frames": {
            "textured": frame_stats_json(&report.textured),
            "base_color": frame_stats_json(&report.base_color),
            "part_id": frame_stats_json(&report.part_id),
            "normal_map": report.normal_map.as_ref().map(frame_stats_json),
            "material_response": report.material_response.as_ref().map(frame_stats_json),
            "layer_mask": report.layer_mask.as_ref().map(frame_stats_json),
        },
        "owner_coverage": owners,
        "outputs": {
            "textured": material_audit_file_evidence(&paths.textured, output_root)?,
            "base_color": material_audit_file_evidence(&paths.base_color, output_root)?,
            "part_id": material_audit_file_evidence(&paths.part_id, output_root)?,
            "normal_map": normal_map_output,
            "material_response": material_response_output,
            "layer_mask": layer_mask_output,
        },
    }))
}

fn material_audit_file_evidence(path: &Path, output_root: &Path) -> Result<Value> {
    let bytes = fs::read(path)
        .with_context(|| format!("failed to read material audit capture {}", path.display()))?;
    let relative = path
        .strip_prefix(output_root)
        .map_err(|_| anyhow::anyhow!("material audit capture escaped its output root"))?
        .to_string_lossy()
        .replace('\\', "/");
    Ok(json!({
        "path": relative,
        "bytes": bytes.len(),
        "sha256": format!("{:x}", Sha256::digest(&bytes)),
    }))
}

#[derive(Debug, Clone)]
enum UiAction {
    OpenArchive,
    OpenMesh,
    QueryArchive,
    LoadSelectedArchiveEntry,
    SwitchLod(usize),
    SelectAllVertices,
    SelectAllEdges,
    SelectAllFaces,
    SelectLinked(SelectionDomain),
    GrowSelection(SelectionDomain),
    ShrinkSelection(SelectionDomain),
    InvertSelection(SelectionDomain),
    ClearSelection,
    FrameAll,
    FrameSelected,
    StandardView(StandardView),
    DeleteFaces,
    SubdivideEdges,
    SubdivideFaces,
    DuplicateFaces,
    DuplicateFacesToNewSubmesh,
    ExtrudeFaces,
    InsetFaces,
    Undo,
    Redo,
    ExportObj,
    ChooseCdmwImportPackage,
    FinishCdmw,
    OrbitMode,
    OrbitYaw(f32),
    Nudge(Vec3),
    RotateStep {
        axis: Vec3,
        degrees: f32,
    },
    ScaleStep(Vec3),
    CdmwCommand {
        command: &'static str,
        arguments: Value,
        label: &'static str,
    },
    CdmwMeshAction {
        action: &'static str,
        label: &'static str,
        params: Value,
    },
    CdmwTopology {
        action: &'static str,
        label: &'static str,
        params: Value,
    },
    SetPartSelection(Vec<u32>),
}

fn cdmw_import_editable_package_action(path: &Path) -> UiAction {
    UiAction::CdmwCommand {
        command: "import_editable_package",
        arguments: json!({"path": path.to_string_lossy()}),
        label: "Import editable package",
    }
}

impl UiAction {
    fn allowed_while_cdmw_pending(&self) -> bool {
        matches!(
            self,
            Self::FrameAll
                | Self::FrameSelected
                | Self::StandardView(_)
                | Self::OrbitMode
                | Self::OrbitYaw(_)
        )
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CdmwRailPage {
    Select,
    Move,
    Rotate,
    Scale,
    Grab,
    Smooth,
    Inflate,
    Pinch,
    Topology,
    Cleanup,
    Normals,
    Uv,
    RigWeights,
    MorphRefit,
}

struct LodSession {
    mesh: WorkingMesh,
    history: History,
}

struct TextureInspectorEntry {
    label: String,
    metadata: DdsMetadata,
    provenance: String,
    ownership: String,
}

struct MaterialParameterInspectorEntry {
    label: String,
    value: String,
    provenance: String,
    ownership: String,
    preview: String,
}

struct MaterialFactorInspectorEntry {
    summary: String,
    provenance: String,
    ownership: String,
}

struct SkeletonInspectorEntry {
    label: String,
    parser: String,
    provenance: String,
    bone_count: usize,
    root_count: usize,
    maximum_depth: u32,
    segment_count: usize,
    tail_byte_count: u64,
    bones: Vec<String>,
}

#[derive(Debug, Clone, PartialEq)]
struct CdmwSkeletonOverlay {
    bone_count: usize,
    lines: Vec<[f32; 3]>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct CdmwPendingRequest {
    request_id: u64,
    event: &'static str,
    label: String,
    origin: Option<CdmwRequestOrigin>,
}

enum CdmwLocalEdit {
    Selection(String),
    Geometry(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum CdmwRequestOrigin {
    Normals,
    Uv,
    MorphValue(String),
}

#[derive(Debug, Default, PartialEq, Eq)]
struct CdmwResultFeedback {
    status: Option<String>,
    diagnostics: Vec<String>,
}

fn cdmw_result_feedback(payload: &Value) -> CdmwResultFeedback {
    fn append_diagnostics(value: Option<&Value>, output: &mut Vec<String>) {
        let Some(values) = value
            .and_then(|entry| entry.get("diagnostics"))
            .and_then(Value::as_array)
        else {
            return;
        };
        for message in values.iter().filter_map(Value::as_str) {
            let message = message.trim();
            if !message.is_empty() && !output.iter().any(|known| known == message) {
                output.push(message.to_owned());
            }
        }
    }

    let result = payload.get("result");
    let state = payload.get("state").unwrap_or(payload);
    let operation_feedback = state.get("operation_feedback");
    let status = result
        .and_then(|value| value.get("status"))
        .and_then(Value::as_str)
        .or_else(|| {
            operation_feedback
                .and_then(|value| value.get("status"))
                .and_then(Value::as_str)
        })
        .map(|value| value.trim().to_ascii_lowercase())
        .filter(|value| !value.is_empty());
    let mut diagnostics = Vec::new();
    append_diagnostics(result, &mut diagnostics);
    append_diagnostics(operation_feedback, &mut diagnostics);
    CdmwResultFeedback {
        status,
        diagnostics,
    }
}

fn cdmw_request_origin(command: &str, arguments: &Value) -> Option<CdmwRequestOrigin> {
    if command == "morph_set_value" {
        return arguments
            .get("definition_id")
            .and_then(Value::as_str)
            .filter(|definition_id| !definition_id.trim().is_empty())
            .map(|definition_id| CdmwRequestOrigin::MorphValue(definition_id.to_owned()));
    }
    if command != "mesh_action" {
        return None;
    }
    match arguments.get("action").and_then(Value::as_str) {
        Some("uv_transform") => Some(CdmwRequestOrigin::Uv),
        Some(
            "recalculate_normals"
            | "generate_tangents"
            | "flip_normals"
            | "sharpen_normals"
            | "soften_normals"
            | "weighted_normals"
            | "copy_normals",
        ) => Some(CdmwRequestOrigin::Normals),
        _ => None,
    }
}

fn stage_cdmw_morph_value(
    drafts: &mut HashMap<String, f64>,
    definition_id: &str,
    value: f64,
    changed: bool,
    interaction_active: bool,
    interaction_finished: bool,
) -> Option<f64> {
    if changed {
        drafts.insert(definition_id.to_owned(), value);
    }
    (interaction_finished || (changed && !interaction_active))
        .then(|| drafts.get(definition_id).copied().unwrap_or(value))
}

fn format_material_ownership(material_indices_by_lod: &[Vec<u32>]) -> String {
    let ownership = material_indices_by_lod
        .iter()
        .enumerate()
        .filter(|(_, materials)| !materials.is_empty())
        .map(|(lod, materials)| {
            format!(
                "LOD{lod}: {}",
                materials
                    .iter()
                    .map(u32::to_string)
                    .collect::<Vec<_>>()
                    .join(", ")
            )
        })
        .collect::<Vec<_>>()
        .join(" · ");
    if ownership.is_empty() {
        "unresolved".to_owned()
    } else {
        ownership
    }
}

fn same_source_part(previous: &cdmw_formats::Submesh, next: &cdmw_formats::Submesh) -> bool {
    previous.name == next.name
        && previous.material == next.material
        && previous.source_range == next.source_range
        && previous.vertex_stride == next.vertex_stride
        && previous.layout == next.layout
}

fn remap_texture_ownership(
    textures: &[LoadedTexture],
    previous_document: &MeshDocument,
    next_document: &MeshDocument,
) -> Vec<LoadedTexture> {
    textures
        .iter()
        .cloned()
        .map(|mut texture| {
            let remapped = next_document
                .lods
                .iter()
                .enumerate()
                .map(|(lod_index, next_lod)| {
                    let Some(previous_lod) = previous_document.lods.get(lod_index) else {
                        return Vec::new();
                    };
                    let Some(previous_owners) = texture.material_indices_by_lod.get(lod_index)
                    else {
                        return Vec::new();
                    };
                    let mut owners =
                        previous_owners
                            .iter()
                            .filter_map(|previous_index| {
                                let previous_index = usize::try_from(*previous_index).ok()?;
                                let previous_part = previous_lod.submeshes.get(previous_index)?;
                                if previous_lod
                                    .submeshes
                                    .iter()
                                    .filter(|candidate| same_source_part(previous_part, candidate))
                                    .count()
                                    != 1
                                {
                                    return None;
                                }
                                let mut matches = next_lod.submeshes.iter().enumerate().filter(
                                    |(_, candidate)| same_source_part(previous_part, candidate),
                                );
                                let (next_index, _) = matches.next()?;
                                if matches.next().is_some() {
                                    return None;
                                }
                                u32::try_from(next_index).ok()
                            })
                            .collect::<Vec<_>>();
                    owners.sort_unstable();
                    owners.dedup();
                    owners
                })
                .collect();
            texture.material_indices_by_lod = remapped;
            texture
        })
        .collect()
}

fn format_pass_count(passes: u32) -> String {
    format!("{passes} {}", if passes == 1 { "pass" } else { "passes" })
}

struct PersistentDeformationReference {
    mesh: WorkingMesh,
    visible_submeshes: Option<HashSet<u32>>,
    positions: Vec<[f32; 3]>,
}

impl PersistentDeformationReference {
    fn new(mesh: WorkingMesh) -> Self {
        let positions = mesh.draw_snapshot().positions;
        Self {
            mesh,
            visible_submeshes: None,
            positions,
        }
    }

    fn matches_loaded_mesh(&self, mesh: &WorkingMesh) -> bool {
        let reference = self.mesh.draw_snapshot();
        let candidate = mesh.draw_snapshot();
        reference.positions.len() == candidate.positions.len()
            && reference.indices == candidate.indices
            && reference.triangle_materials == candidate.triangle_materials
            && self
                .mesh
                .faces()
                .map(|(_, face)| (face.submesh, face.material, face.provenance))
                .eq(mesh
                    .faces()
                    .map(|(_, face)| (face.submesh, face.material, face.provenance)))
            && self
                .mesh
                .vertices()
                .map(|(_, vertex)| vertex.provenance)
                .eq(mesh.vertices().map(|(_, vertex)| vertex.provenance))
    }

    fn positions_for_snapshot(
        &mut self,
        visible_submeshes: Option<&HashSet<u32>>,
        snapshot: &DrawSnapshot,
    ) -> Option<&[[f32; 3]]> {
        if self.mesh.topology_generation != snapshot.topology_generation {
            return None;
        }
        if self.visible_submeshes.as_ref() != visible_submeshes {
            self.positions = visible_submeshes
                .map_or_else(
                    || self.mesh.draw_snapshot(),
                    |visible| self.mesh.draw_snapshot_for_submeshes(visible),
                )
                .positions;
            self.visible_submeshes = visible_submeshes.cloned();
        }
        (self.positions.len() == snapshot.positions.len()).then_some(self.positions.as_slice())
    }
}

fn deformation_reference_for_snapshot<'a>(
    enabled: bool,
    reference: Option<&'a mut PersistentDeformationReference>,
    visible_submeshes: Option<&HashSet<u32>>,
    snapshot: &DrawSnapshot,
) -> Option<&'a [[f32; 3]]> {
    if !enabled {
        return None;
    }
    reference?.positions_for_snapshot(visible_submeshes, snapshot)
}

fn cdmw_material_ownership(
    presentation: &SessionMaterialPresentation,
    lod_count: usize,
) -> Vec<Vec<u32>> {
    let mut ownership = vec![Vec::new(); lod_count];
    if let Some(materials) = usize::try_from(presentation.lod_index)
        .ok()
        .and_then(|lod_index| ownership.get_mut(lod_index))
    {
        materials.push(presentation.material_index);
    }
    ownership
}

fn cdmw_material_preview_factors(
    presentation: &SessionMaterialPresentation,
) -> MaterialPreviewFactors {
    MaterialPreviewFactors {
        emissive_color: presentation.emissive_color,
        emissive_intensity: presentation.emissive_intensity,
        roughness: presentation.roughness,
        metalness: presentation.metalness,
        specular: presentation.specular,
        height_scale: presentation.height_scale,
        texture_tint: presentation.texture_tint,
        base_tint_strength: presentation.base_tint_strength,
        alpha_cutoff: if presentation.alpha_mode == "cutout" {
            presentation.alpha_cutoff
        } else {
            None
        },
        alpha_blend: Some(presentation.alpha_mode == "blend"),
        opacity: presentation.opacity,
        gltf_metallic_roughness: Some(presentation.gltf_metallic_roughness),
        hair_anisotropy: Some(presentation.hair_anisotropy),
        layer_mask_channel: None,
        category_code: Some(presentation.category_code),
        category_confidence: Some(presentation.category_confidence),
        normal_y_inverted: Some(presentation.normal_y_inverted),
        texture_flip_vertical: Some(presentation.texture_flip_vertical),
        skin_detail_scale: presentation.skin_detail_scale,
        skin_detail_opacity: presentation.skin_detail_opacity,
    }
}

fn loaded_cdmw_material_factor(
    presentation: &SessionMaterialPresentation,
    lod_count: usize,
) -> LoadedMaterialFactors {
    LoadedMaterialFactors {
        sidecar_label: format!(
            "CDMW {} material contract · {} · {} alpha · slot {}{}",
            presentation.material_category,
            presentation.shader_family,
            presentation.alpha_mode,
            presentation.material_slot_index,
            if presentation.double_sided {
                " · double-sided"
            } else {
                ""
            }
        ),
        emissive_color: presentation.emissive_color,
        emissive_intensity: presentation.emissive_intensity,
        roughness: presentation.roughness,
        metalness: presentation.metalness,
        specular: presentation.specular,
        height_scale: presentation.height_scale,
        texture_tint: presentation.texture_tint,
        base_tint_strength: presentation.base_tint_strength,
        alpha_cutoff: if presentation.alpha_mode == "cutout" {
            presentation.alpha_cutoff
        } else {
            None
        },
        alpha_blend: Some(presentation.alpha_mode == "blend"),
        opacity: presentation.opacity,
        gltf_metallic_roughness: Some(presentation.gltf_metallic_roughness),
        hair_anisotropy: Some(presentation.hair_anisotropy),
        layer_mask_channel: None,
        skin_detail_scale: presentation.skin_detail_scale,
        skin_detail_opacity: presentation.skin_detail_opacity,
        material_indices_by_lod: cdmw_material_ownership(presentation, lod_count),
    }
}

fn add_cdmw_material_presentations(
    renderer: &mut WindowRenderer,
    presentations: &[SessionMaterialPresentation],
    lod_count: usize,
) -> Result<usize> {
    let mut uploaded = 0_usize;
    for presentation in presentations {
        let ownership = cdmw_material_ownership(presentation, lod_count);
        renderer
            .add_material_factors(cdmw_material_preview_factors(presentation), &ownership)
            .with_context(|| {
                format!(
                    "CDMW LOD{} material {} presentation could not be installed",
                    presentation.lod_index, presentation.material_index
                )
            })?;
        uploaded = uploaded.saturating_add(1);
    }
    Ok(uploaded)
}

struct LabApplication {
    window: Option<Arc<Window>>,
    embedded_parent_hwnd: Option<u64>,
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
    texture_entries: Vec<TextureInspectorEntry>,
    material_parameter_entries: Vec<MaterialParameterInspectorEntry>,
    material_factor_entries: Vec<MaterialFactorInspectorEntry>,
    cdmw_texture_resources: Vec<LoadedTexture>,
    cdmw_material_presentations: Vec<SessionMaterialPresentation>,
    cdmw_uploaded_texture_count: usize,
    cdmw_textured_mode_available: bool,
    cdmw_textured_mode_reason: String,
    cdmw_texture_package_reason: String,
    skeleton_entry: Option<SkeletonInspectorEntry>,
    skeleton_overlay_lines: Vec<[f32; 3]>,
    cdmw_skeleton_overlay_reason: String,
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
    show_bones: bool,
    deformation_heatmap_enabled: bool,
    deformation_heatmap_applied: bool,
    deformation_reference: Option<PersistentDeformationReference>,
    overlay_wire_colour: Color32,
    overlay_vertex_colour: Color32,
    overlay_selection_colour: Color32,
    overlay_live_selection_colour: Color32,
    viewport_background_colour: Color32,
    viewport_grid_colour: Color32,
    overlay_wire_width: f32,
    overlay_vertex_size: f32,
    viewport_tool: ViewportTool,
    selection_tool: SelectionTool,
    brush_radius: f32,
    brush_strength: f32,
    brush_falloff: BrushFalloff,
    sculpt_symmetry: SculptSymmetry,
    smooth_iterations: u32,
    transform_translate_step: f32,
    transform_rotate_step: f32,
    transform_scale_factor: f32,
    extrude_distance: f32,
    cdmw_extrude_axis: String,
    inset_amount: f32,
    selection_gesture: Option<SelectionGesture>,
    edit_gesture: Option<EditGesture>,
    projection: Option<ViewportProjection>,
    face_selection_overlay: Option<FaceSelectionOverlay>,
    selected_counts_cache: std::cell::Cell<Option<((u64, u64), cdmw_ui::SelectedCounts)>>,
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
    cdmw_bridge: Option<CdmwBridge>,
    cdmw_state: Value,
    cdmw_pending_request: Option<CdmwPendingRequest>,
    cdmw_normals_feedback: Option<String>,
    cdmw_uv_feedback: Option<String>,
    cdmw_morph_value_drafts: HashMap<String, f64>,
    cdmw_host_connected: bool,
    cdmw_orbit_mode: bool,
    cdmw_rail_page: Option<CdmwRailPage>,
    cdmw_layer_name: String,
    cdmw_morph_profile_name: String,
    cdmw_morph_definition_label: String,
    cdmw_morph_definition_edit_id: String,
    cdmw_morph_replace_selection_on_edit: bool,
    cdmw_morph_rule: String,
    cdmw_morph_axis: String,
    cdmw_morph_amount: f32,
    cdmw_morph_feather: u32,
    cdmw_morph_falloff: String,
    cdmw_morph_mirror_mode: String,
    cdmw_morph_preset_name: String,
    cdmw_refit_enabled: bool,
    cdmw_refit_intensity: f32,
    cdmw_refit_mode: String,
    cdmw_refit_clearance: f32,
    cdmw_refit_hydration_key: String,
    cdmw_refit_settings_dirty: bool,
    cdmw_cleanup_merge_distance: f32,
    cdmw_loop_cut_count: u32,
    cdmw_loop_cut_factor: f32,
    cdmw_refine_strength: f32,
    cdmw_refine_iterations: u32,
    cdmw_weld_distance: f32,
    cdmw_uv_offset_step: f32,
    cdmw_uv_scale_factor: f32,
    cdmw_uv_pixel_width: u32,
    cdmw_uv_pixel_height: u32,
    cdmw_weight_step: f32,
    cdmw_exit_requested: bool,
    cdmw_finish_accepted: bool,
    #[cfg(test)]
    cdmw_transaction_attempts: usize,
    #[cfg(test)]
    material_reload_count: usize,
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
            embedded_parent_hwnd: None,
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
            texture_entries: Vec::new(),
            material_parameter_entries: Vec::new(),
            material_factor_entries: Vec::new(),
            cdmw_texture_resources: Vec::new(),
            cdmw_material_presentations: Vec::new(),
            cdmw_uploaded_texture_count: 0,
            cdmw_textured_mode_available: false,
            cdmw_textured_mode_reason:
                "Solid (Textured) is unavailable because no usable DDS material texture has been uploaded."
                    .to_owned(),
            cdmw_texture_package_reason: String::new(),
            skeleton_entry: None,
            skeleton_overlay_lines: Vec::new(),
            cdmw_skeleton_overlay_reason: "No complete skeleton hierarchy is available".to_owned(),
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
            show_bones: false,
            deformation_heatmap_enabled: true,
            deformation_heatmap_applied: true,
            deformation_reference: None,
            overlay_wire_colour: Color32::from_rgb(105, 125, 155),
            overlay_vertex_colour: Color32::from_gray(205),
            overlay_selection_colour: Color32::from_rgb(255, 145, 35),
            overlay_live_selection_colour: Color32::from_rgb(80, 190, 255),
            viewport_background_colour: Color32::from_rgb(6, 8, 10),
            viewport_grid_colour: Color32::from_rgb(42, 48, 58),
            overlay_wire_width: 1.2,
            overlay_vertex_size: 2.5,
            viewport_tool: ViewportTool::Select,
            selection_tool: SelectionTool::Click,
            brush_radius: 48.0,
            brush_strength: 0.18,
            brush_falloff: BrushFalloff::Smooth,
            sculpt_symmetry: SculptSymmetry::Off,
            smooth_iterations: 1,
            transform_translate_step: 0.02,
            transform_rotate_step: 15.0,
            transform_scale_factor: 1.1,
            extrude_distance: 0.02,
            cdmw_extrude_axis: "z".to_owned(),
            inset_amount: 0.15,
            selection_gesture: None,
            edit_gesture: None,
            projection: None,
            face_selection_overlay: None,
            selected_counts_cache: std::cell::Cell::new(None),
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
            cdmw_bridge: None,
            cdmw_state: Value::Null,
            cdmw_pending_request: None,
            cdmw_normals_feedback: None,
            cdmw_uv_feedback: None,
            cdmw_morph_value_drafts: HashMap::new(),
            cdmw_host_connected: false,
            cdmw_orbit_mode: false,
            cdmw_rail_page: None,
            cdmw_layer_name: "Rust Layer".to_owned(),
            cdmw_morph_profile_name: "Rust Morph Profile".to_owned(),
            cdmw_morph_definition_label: "Rust Morph".to_owned(),
            cdmw_morph_definition_edit_id: String::new(),
            cdmw_morph_replace_selection_on_edit: false,
            cdmw_morph_rule: "volume".to_owned(),
            cdmw_morph_axis: "y".to_owned(),
            cdmw_morph_amount: 0.1,
            cdmw_morph_feather: 2,
            cdmw_morph_falloff: "smooth".to_owned(),
            cdmw_morph_mirror_mode: "off".to_owned(),
            cdmw_morph_preset_name: "Rust Preset".to_owned(),
            cdmw_refit_enabled: true,
            cdmw_refit_intensity: 100.0,
            cdmw_refit_mode: "surface".to_owned(),
            cdmw_refit_clearance: 0.0,
            cdmw_refit_hydration_key: String::new(),
            cdmw_refit_settings_dirty: false,
            cdmw_cleanup_merge_distance: 0.0001,
            cdmw_loop_cut_count: 1,
            cdmw_loop_cut_factor: 0.5,
            cdmw_refine_strength: 0.5,
            cdmw_refine_iterations: 2,
            cdmw_weld_distance: 0.0001,
            cdmw_uv_offset_step: 0.05,
            cdmw_uv_scale_factor: 1.1,
            cdmw_uv_pixel_width: 1024,
            cdmw_uv_pixel_height: 1024,
            cdmw_weight_step: 0.1,
            cdmw_exit_requested: false,
            cdmw_finish_accepted: false,
            #[cfg(test)]
            cdmw_transaction_attempts: 0,
            #[cfg(test)]
            material_reload_count: 0,
        }
    }

    fn new_cdmw(
        mut bridge: CdmwBridge,
        document: MeshDocument,
        embedded_parent_hwnd: Option<u64>,
    ) -> Result<Self> {
        let source_lod_index = bridge.source_lod_index();
        let source_path = bridge
            .manifest()
            .source
            .get("path")
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .map_or_else(|| PathBuf::from("cdmw-shadow.pac"), PathBuf::from);
        let mesh = WorkingMesh::from_document(&document)
            .context("CDMW authoring document could not create LOD0")?;
        let other_lod_meshes = (1..document.lods.len())
            .map(|index| {
                WorkingMesh::from_document_lod(&document, index)
                    .with_context(|| format!("CDMW authoring document could not create LOD{index}"))
            })
            .collect::<Result<Vec<_>>>()?;
        let initial_state = bridge.manifest().state.clone();
        let authoritative_base_revision = bridge.manifest().base_revision;
        let output_policy = bridge
            .manifest()
            .output_policy
            .get("policy")
            .and_then(Value::as_str)
            .unwrap_or("exact_game_asset")
            .to_owned();
        let initial_shadow_revision = bridge.shadow_revision();
        let cdmw_texture_package_reason = bridge
            .manifest()
            .texture_status
            .get("reason")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .trim()
            .to_owned();
        let cdmw_texture_resources = bridge
            .take_textures()
            .into_iter()
            .map(|texture| LoadedTexture {
                requested_reference: texture.label.clone(),
                label: texture.label,
                metadata: texture.metadata,
                bytes: texture.bytes,
                role: texture.role,
                parameter_name: None,
                sidecar_label: Some("CDMW isolated authoring package".to_owned()),
                resolution_method: cdmw_asset_graph::ResolutionMethod::ExplicitVirtualPath,
                archive_compression: None,
                material_indices_by_lod: texture.material_indices_by_lod,
            })
            .collect::<Vec<_>>();
        let cdmw_material_presentations = bridge.take_material_presentations();
        let cdmw_material_factors = cdmw_material_presentations
            .iter()
            .map(|presentation| loaded_cdmw_material_factor(presentation, document.lods.len()))
            .collect::<Vec<_>>();
        let mut application = Self::new(None, None);
        application.embedded_parent_hwnd = embedded_parent_hwnd;
        application.install_loaded_mesh(LoadedMesh {
            path: source_path,
            document,
            mesh,
            other_lod_meshes,
            textures: cdmw_texture_resources.clone(),
            material_parameters: Vec::new(),
            material_factors: cdmw_material_factors,
            skeleton: None,
        });
        if source_lod_index != 0 {
            application.switch_lod(source_lod_index);
            if application.active_lod_index != source_lod_index {
                anyhow::bail!("CDMW source LOD {source_lod_index} could not be activated");
            }
        }
        if let Some(mesh) = &application.mesh {
            application.camera.frame_integrated_startup(mesh);
        }
        application.cdmw_state = initial_state;
        application.cdmw_bridge = Some(bridge);
        application.cdmw_texture_resources = cdmw_texture_resources;
        application.cdmw_material_presentations = cdmw_material_presentations;
        application.cdmw_texture_package_reason = cdmw_texture_package_reason;
        application.refresh_cdmw_skeleton_overlay();
        application.apply_cdmw_theme();
        application.cdmw_orbit_mode = true;
        application.status = format!(
            "CDMW shadow session loaded · Orbit mode · {output_policy} · base {authoritative_base_revision} · shadow {initial_shadow_revision} · edits are isolated until Finish Edit Mesh"
        );
        application.apply_cdmw_selection_state(true);
        Ok(application)
    }

    fn cdmw_mode(&self) -> bool {
        self.cdmw_bridge.is_some()
    }

    fn record_cdmw_texture_uploads(
        &mut self,
        resource_count: usize,
        uploaded_texture_count: usize,
        bound_material_count: usize,
        warning: Option<&str>,
    ) {
        self.cdmw_uploaded_texture_count = uploaded_texture_count;
        self.cdmw_textured_mode_available = uploaded_texture_count > 0 && bound_material_count > 0;
        self.cdmw_textured_mode_reason = if self.cdmw_textured_mode_available {
            String::new()
        } else if resource_count == 0 {
            if self.cdmw_texture_package_reason.is_empty() {
                "Solid (Textured) is unavailable because this session has no resolved DDS material texture."
                    .to_owned()
            } else {
                format!(
                    "Solid (Textured) is unavailable: {}",
                    self.cdmw_texture_package_reason
                )
            }
        } else if uploaded_texture_count == 0 {
            warning.map_or_else(
                || {
                    "Solid (Textured) is unavailable because no DDS material texture could be uploaded."
                        .to_owned()
                },
                |reason| {
                    format!(
                        "Solid (Textured) is unavailable because no DDS material texture could be uploaded: {reason}"
                    )
                },
            )
        } else {
            warning.map_or_else(
                || {
                    "Solid (Textured) is unavailable because uploaded textures have no unambiguous owner in this mesh revision."
                        .to_owned()
                },
                |reason| {
                    format!(
                        "Solid (Textured) is unavailable because uploaded textures could not bind to this mesh revision: {reason}"
                    )
                },
            )
        };
        if !self.cdmw_textured_mode_available && self.view_mode == ViewMode::TexturedSolid {
            self.view_mode = ViewMode::Solid;
        }
    }

    fn cdmw_visible_submeshes(&self) -> Option<HashSet<u32>> {
        if !self.cdmw_mode() {
            return None;
        }
        let expected = self.mesh.as_ref()?.submesh_indices();
        let layers = self
            .cdmw_state
            .get("geometry_layers")?
            .get("layers")?
            .as_array()?;
        if layers.is_empty() {
            return None;
        }
        let mut assigned = HashSet::new();
        let mut visible = HashSet::new();
        for layer in layers {
            let indices = layer.get("submesh_indices")?.as_array()?;
            let parsed = indices
                .iter()
                .map(|value| value.as_u64().and_then(|index| u32::try_from(index).ok()))
                .collect::<Option<Vec<_>>>()?;
            for index in &parsed {
                if !expected.contains(index) || !assigned.insert(*index) {
                    return None;
                }
            }
            if layer.get("base").and_then(Value::as_bool) == Some(true)
                || layer.get("visible").and_then(Value::as_bool) == Some(true)
            {
                visible.extend(parsed);
            }
        }
        (assigned == expected).then_some(visible)
    }

    fn refresh_cdmw_skeleton_overlay(&mut self) {
        match parse_cdmw_skeleton_overlay(&self.cdmw_state) {
            Ok(overlay) => {
                self.skeleton_overlay_lines = overlay.lines;
                self.cdmw_skeleton_overlay_reason = format!(
                    "{} complete bones · {} hierarchy segments",
                    overlay.bone_count,
                    self.skeleton_overlay_lines.len() / 2
                );
            }
            Err(reason) => {
                self.skeleton_overlay_lines.clear();
                self.cdmw_skeleton_overlay_reason = reason;
                self.show_bones = false;
            }
        }
        if let Some(renderer) = &mut self.renderer
            && let Err(error) = renderer.set_skeleton_lines(&self.skeleton_overlay_lines)
        {
            self.show_bones = false;
            self.status = format!("Skeleton overlay upload failed: {error}");
        }
    }

    fn cdmw_busy(&self) -> bool {
        self.cdmw_pending_request.is_some()
    }

    fn submit_cdmw_local_edit(&mut self, edit: CdmwLocalEdit) {
        match edit {
            CdmwLocalEdit::Geometry(label) => self.submit_cdmw_transaction(&label),
            CdmwLocalEdit::Selection(label) => {
                let Some(mesh) = &self.mesh else {
                    return;
                };
                match cdmw_session::selection_payload(mesh) {
                    Ok(selection) => self.submit_cdmw_command(
                        "select",
                        json!({"selection": selection, "operation": "replace"}),
                        &label,
                    ),
                    Err(error) => self.status = format!("Could not map selection: {error}"),
                }
            }
        }
    }

    fn submit_cdmw_transaction(&mut self, label: &str) {
        if self.cdmw_busy() {
            self.status = "Finish the pending CDMW operation before editing again".to_owned();
            return;
        }
        #[cfg(test)]
        {
            self.cdmw_transaction_attempts = self.cdmw_transaction_attempts.saturating_add(1);
        }
        let result = match (&mut self.cdmw_bridge, &self.document, &self.mesh) {
            (Some(bridge), Some(document), Some(mesh)) => {
                bridge.submit_transaction(document, mesh, label)
            }
            _ => return,
        };
        match result {
            Ok(request_id) => {
                self.cdmw_pending_request = Some(CdmwPendingRequest {
                    request_id,
                    event: "transaction_result",
                    label: label.to_owned(),
                    origin: None,
                });
                self.status = format!("Recording {label} in the isolated CDMW shadow history…");
            }
            Err(error) => self.status = format!("Could not queue Rust edit transaction: {error}"),
        }
    }

    fn submit_cdmw_command(&mut self, command: &str, arguments: Value, label: &str) {
        if self.cdmw_busy() {
            self.status = "Finish the pending CDMW operation before starting another".to_owned();
            return;
        }
        let origin = cdmw_request_origin(command, &arguments);
        let arguments = match self.cdmw_command_arguments(command, arguments) {
            Ok(arguments) => arguments,
            Err(error) => {
                self.status = format!("Could not queue {label}: {error}");
                return;
            }
        };
        let Some(bridge) = &mut self.cdmw_bridge else {
            return;
        };
        match bridge.submit_command(command, arguments) {
            Ok(request_id) => {
                self.cdmw_pending_request = Some(CdmwPendingRequest {
                    request_id,
                    event: "command_result",
                    label: label.to_owned(),
                    origin,
                });
                self.status = format!("{label}…");
            }
            Err(error) => self.status = format!("Could not queue {label}: {error}"),
        }
    }

    fn cdmw_command_arguments(&self, command: &str, arguments: Value) -> Result<Value, String> {
        if !matches!(
            command,
            "rig_adjust_weight" | "rig_normalize_weights" | "rig_transfer_weights"
        ) {
            return Ok(arguments);
        }
        let selection = self
            .mesh
            .as_ref()
            .map_or_else(|| Ok(json!({})), cdmw_session::selection_payload)
            .map_err(|error| format!("could not map the rig-weight selection: {error}"))?;
        let mut object = arguments
            .as_object()
            .cloned()
            .ok_or_else(|| "command arguments must be an object".to_owned())?;
        object.insert("selection".to_owned(), selection);
        Ok(Value::Object(object))
    }

    fn submit_cdmw_topology(&mut self, action: &'static str, label: &str, params: Value) {
        let selection = self
            .mesh
            .as_ref()
            .map_or_else(|| Ok(json!({})), cdmw_session::selection_payload);
        match selection {
            Ok(selection) => self.submit_cdmw_command(
                "topology",
                json!({
                    "action": action,
                    "selection": selection,
                    "params": params,
                    "label": label
                }),
                label,
            ),
            Err(error) => self.status = format!("Could not map topology selection: {error}"),
        }
    }

    fn submit_cdmw_mesh_action(&mut self, action: &'static str, label: &str, params: Value) {
        let selection = self
            .mesh
            .as_ref()
            .map_or_else(|| Ok(json!({})), cdmw_session::selection_payload);
        match selection {
            Ok(selection) => self.submit_cdmw_command(
                "mesh_action",
                json!({
                    "action": action,
                    "selection": selection,
                    "params": params,
                    "label": label
                }),
                label,
            ),
            Err(error) => self.status = format!("Could not map mesh action selection: {error}"),
        }
    }

    fn submit_cdmw_finish(&mut self) {
        if self.cdmw_busy() {
            self.status =
                "Finish Edit Mesh is waiting for the current shadow transaction".to_owned();
            return;
        }
        let Some(bridge) = &mut self.cdmw_bridge else {
            return;
        };
        match bridge.submit_finish() {
            Ok(request_id) => {
                self.cdmw_pending_request = Some(CdmwPendingRequest {
                    request_id,
                    event: "finish_result",
                    label: "Finish Edit Mesh".to_owned(),
                    origin: None,
                });
                self.status = "Validating the complete shadow snapshot in CDMW…".to_owned();
            }
            Err(error) => self.status = format!("Could not request Finish Edit Mesh: {error}"),
        }
    }

    fn poll_cdmw(&mut self) -> bool {
        let events = self
            .cdmw_bridge
            .as_mut()
            .map(CdmwBridge::poll)
            .unwrap_or_default();
        let changed = !events.is_empty();
        for event in events {
            self.handle_cdmw_host_event(event);
        }
        changed
    }

    fn handle_cdmw_host_event(&mut self, event: HostEvent) {
        match event {
            HostEvent::Hello | HostEvent::Ready => {
                self.cdmw_host_connected = true;
                self.status =
                    "CDMW connected · Rust edits remain isolated until Finish Edit Mesh".to_owned();
            }
            HostEvent::StateSnapshot(state) => {
                if self.cdmw_busy() {
                    self.handle_cdmw_host_event(HostEvent::Fatal(
                        "host state snapshot arrived while a request was pending".to_owned(),
                    ));
                    return;
                }
                self.apply_cdmw_state(state);
            }
            HostEvent::Theme(theme) => {
                self.apply_cdmw_theme_payload(&theme);
            }
            HostEvent::Result {
                event,
                request_id,
                base_revision,
                ok,
                payload,
                error,
            } => self.handle_cdmw_result(&event, request_id, base_revision, ok, payload, &error),
            HostEvent::Cancel(reason) => {
                self.status = reason;
                self.cdmw_exit_requested = true;
            }
            HostEvent::Fatal(message) => {
                self.status = format!("CDMW protocol failure: {message}");
                if let Some(bridge) = &mut self.cdmw_bridge {
                    let _ = bridge.cancel("Rust protocol failure");
                }
                self.cdmw_exit_requested = true;
            }
        }
    }

    fn handle_cdmw_result(
        &mut self,
        event: &str,
        request_id: u64,
        base_revision: u64,
        ok: bool,
        payload: Value,
        error: &str,
    ) {
        let Some(pending) = self.cdmw_pending_request.as_ref() else {
            self.handle_cdmw_host_event(HostEvent::Fatal(format!(
                "unexpected {event} for request {request_id}"
            )));
            return;
        };
        let prepared = match self.cdmw_bridge.as_ref().map(|bridge| {
            bridge.prepare_host_result(
                pending.event,
                pending.request_id,
                event,
                request_id,
                base_revision,
                ok,
                &payload,
            )
        }) {
            Some(Ok(prepared)) => prepared,
            Some(Err(error)) => {
                self.handle_cdmw_host_event(HostEvent::Fatal(error.to_string()));
                return;
            }
            None => {
                self.handle_cdmw_host_event(HostEvent::Fatal(
                    "host result arrived without an active CDMW bridge".to_owned(),
                ));
                return;
            }
        };
        let label = pending.label.clone();
        let origin = pending.origin.clone();
        let feedback = cdmw_result_feedback(&payload);
        let (revision, state, document) = prepared.into_parts();
        if let Some(state) = state
            && let Err(error) = self.install_validated_cdmw_state(state, document)
        {
            self.handle_cdmw_host_event(HostEvent::Fatal(error.to_string()));
            return;
        }
        if let Some(bridge) = &mut self.cdmw_bridge
            && let Err(error) = bridge.accept_prepared_revision(revision)
        {
            self.handle_cdmw_host_event(HostEvent::Fatal(error.to_string()));
            return;
        }
        self.cdmw_pending_request.take();
        if let Some(CdmwRequestOrigin::MorphValue(definition_id)) = &origin {
            self.cdmw_morph_value_drafts.remove(definition_id);
        }
        if label == "Apply garment refit settings" {
            self.cdmw_refit_settings_dirty = false;
            self.cdmw_refit_hydration_key.clear();
        }
        if !ok {
            self.status = format!("{label} rejected: {}", error.trim());
            self.remember_cdmw_page_feedback(origin.as_ref());
            return;
        }
        if matches!(
            label.as_str(),
            "Update morph slider"
                | "Delete morph slider"
                | "Activate morph profile"
                | "Delete morph profile"
        ) {
            self.cdmw_morph_definition_edit_id.clear();
            self.cdmw_morph_replace_selection_on_edit = false;
        }
        if event == "finish_result" {
            self.cdmw_finish_accepted = true;
            self.cdmw_exit_requested = true;
            self.status = "Finish Edit Mesh accepted by CDMW".to_owned();
            return;
        }
        let diagnostic = feedback.diagnostics.join("; ");
        if feedback.status.as_deref() == Some("noop") {
            self.status = if diagnostic.is_empty() {
                format!("{label} made no change")
            } else {
                format!("{label} made no change: {diagnostic}")
            };
        } else if diagnostic.is_empty() {
            self.status = format!("{} completed · shadow revision {base_revision}", label);
        } else {
            self.status =
                format!("{label} completed · {diagnostic} · shadow revision {base_revision}");
        }
        self.remember_cdmw_page_feedback(origin.as_ref());
    }

    fn remember_cdmw_page_feedback(&mut self, origin: Option<&CdmwRequestOrigin>) {
        match origin {
            Some(CdmwRequestOrigin::Normals) => {
                self.cdmw_normals_feedback = Some(self.status.clone());
            }
            Some(CdmwRequestOrigin::Uv) => {
                self.cdmw_uv_feedback = Some(self.status.clone());
            }
            Some(CdmwRequestOrigin::MorphValue(_)) | None => {}
        }
    }

    fn apply_cdmw_state(&mut self, state: Value) {
        self.cdmw_morph_value_drafts.clear();
        let prepared = match self
            .cdmw_bridge
            .as_ref()
            .map(|bridge| bridge.prepare_state_snapshot(state))
        {
            Some(Ok(prepared)) => prepared,
            Some(Err(error)) => {
                self.handle_cdmw_host_event(HostEvent::Fatal(error.to_string()));
                return;
            }
            None => {
                self.handle_cdmw_host_event(HostEvent::Fatal(
                    "host state arrived without an active CDMW bridge".to_owned(),
                ));
                return;
            }
        };
        let (revision, state, document) = prepared.into_parts();
        let result = state
            .ok_or_else(|| anyhow::anyhow!("host state snapshot was empty"))
            .and_then(|state| self.install_validated_cdmw_state(state, document));
        if let Err(error) = result {
            self.handle_cdmw_host_event(HostEvent::Fatal(error.to_string()));
            return;
        }
        if let Some(bridge) = &mut self.cdmw_bridge
            && let Err(error) = bridge.accept_prepared_revision(revision)
        {
            self.handle_cdmw_host_event(HostEvent::Fatal(error.to_string()));
        }
    }

    fn install_validated_cdmw_state(
        &mut self,
        state: Value,
        document: Option<MeshDocument>,
    ) -> Result<()> {
        let previous_visibility = self.cdmw_visible_submeshes();
        let previous_state = std::mem::replace(&mut self.cdmw_state, state);
        let result = if let Some(document) = document {
            self.install_cdmw_document(document)
        } else {
            self.apply_cdmw_selection_state(
                previous_visibility != self.cdmw_visible_submeshes()
                    || previous_state.get("selection") != self.cdmw_state.get("selection"),
            );
            Ok(())
        };
        if result.is_err() {
            self.cdmw_state = previous_state;
        } else {
            self.refresh_cdmw_skeleton_overlay();
        }
        result
    }

    fn install_cdmw_document(&mut self, document: MeshDocument) -> Result<()> {
        let path = PathBuf::from(&self.source_label);
        let camera = self.camera.clone();
        let orbit_mode = self.cdmw_orbit_mode;
        let rail_page = self.cdmw_rail_page;
        let viewport_tool = self.viewport_tool;
        let show_bones = self.show_bones;
        let active_lod_index = self.active_lod_index;
        let textures = self.document.as_ref().map_or_else(
            || self.cdmw_texture_resources.clone(),
            |previous_document| {
                remap_texture_ownership(&self.cdmw_texture_resources, previous_document, &document)
            },
        );
        // These resources come from this session's immutable texture payloads;
        // remapping only changes their owners. Preserve GPU resources when the
        // ownership and LOD shape are unchanged and the previous upload succeeded.
        let reuse_materials = self.document.as_ref().is_some_and(|previous| {
            previous.lods.len() == document.lods.len()
                && previous
                    .lods
                    .iter()
                    .zip(&document.lods)
                    .all(|(before, after)| {
                        before.submeshes.len() == after.submeshes.len()
                            && before
                                .submeshes
                                .iter()
                                .zip(&after.submeshes)
                                .all(|(before, after)| same_source_part(before, after))
                    })
                && self.cdmw_uploaded_texture_count == textures.len()
                && textures
                    .iter()
                    .zip(&self.cdmw_texture_resources)
                    .all(|(next, previous)| {
                        next.material_indices_by_lod == previous.material_indices_by_lod
                    })
        });
        let mesh = WorkingMesh::from_document(&document).context("invalid CDMW LOD0 state")?;
        let other_lod_meshes = (1..document.lods.len())
            .map(|index| {
                WorkingMesh::from_document_lod(&document, index)
                    .with_context(|| format!("invalid CDMW LOD{index} state"))
            })
            .collect::<Result<Vec<_>>>()?;
        let material_factors = self
            .cdmw_material_presentations
            .iter()
            .map(|presentation| loaded_cdmw_material_factor(presentation, document.lods.len()))
            .collect::<Vec<_>>();
        self.install_loaded_mesh_with_materials(
            LoadedMesh {
                path,
                document,
                mesh,
                other_lod_meshes,
                textures: textures.clone(),
                material_parameters: Vec::new(),
                material_factors,
                skeleton: None,
            },
            reuse_materials,
        );
        self.cdmw_texture_resources = textures;
        if let Some(renderer) = &mut self.renderer {
            if !reuse_materials {
                add_cdmw_material_presentations(
                    renderer,
                    &self.cdmw_material_presentations,
                    self.document
                        .as_ref()
                        .map_or(0, |document| document.lods.len()),
                )?;
            }
            renderer
                .set_material_lod(active_lod_index)
                .context("CDMW material presentation LOD could not be restored")?;
        }
        if active_lod_index != 0 {
            self.switch_lod(active_lod_index);
            if self.active_lod_index != active_lod_index {
                anyhow::bail!("invalid CDMW source LOD {active_lod_index} state");
            }
        }
        self.camera = camera;
        self.cdmw_orbit_mode = orbit_mode;
        self.cdmw_rail_page = rail_page;
        self.viewport_tool = viewport_tool;
        self.show_bones = show_bones;
        self.apply_cdmw_selection_state(true);
        Ok(())
    }

    fn apply_cdmw_selection_state(&mut self, force_snapshot: bool) {
        let visible_submeshes = self.cdmw_visible_submeshes();
        let Some(mesh) = &mut self.mesh else {
            return;
        };
        let selection_value = self
            .cdmw_state
            .get("selection")
            .cloned()
            .unwrap_or(Value::Null);
        if selection_value.is_null() {
            return;
        }
        let vertices = index_map(&selection_value, "vertices_by_submesh");
        let faces = index_map(&selection_value, "faces_by_submesh");
        let edges = edge_map(&selection_value, "edges_by_submesh");
        let mut selection = Selection::default();
        for (handle, vertex) in mesh.vertices() {
            if let Provenance::Source { submesh, element } = vertex.provenance
                && vertices
                    .get(&submesh)
                    .is_some_and(|values| values.contains(&element))
            {
                selection.vertices.insert(handle);
            }
        }
        for (handle, face) in mesh.faces() {
            if let Provenance::Source { element, .. } = face.provenance
                && faces
                    .get(&face.submesh)
                    .is_some_and(|values| values.contains(&element))
            {
                selection.faces.insert(handle);
            }
        }
        for (handle, edge) in mesh.edges() {
            let endpoints = edge.vertices.map(|vertex_handle| {
                mesh.vertex(vertex_handle)
                    .and_then(|vertex| match vertex.provenance {
                        Provenance::Source { submesh, element } => Some((submesh, element)),
                        Provenance::Generated { .. } => None,
                    })
            });
            if let [Some(first), Some(second)] = endpoints
                && first.0 == second.0
                && edges.get(&first.0).is_some_and(|values| {
                    values.contains(&(first.1.min(second.1), first.1.max(second.1)))
                })
            {
                selection.edges.insert(handle);
            }
        }
        selection.submeshes.extend(
            selection_value
                .get("source_indices")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(Value::as_u64)
                .filter_map(|value| u32::try_from(value).ok()),
        );
        if let Some(visible_submeshes) = &visible_submeshes {
            let visible = mesh.element_handles_for_submeshes(visible_submeshes);
            selection
                .vertices
                .retain(|handle| visible.vertices.contains(handle));
            selection
                .edges
                .retain(|handle| visible.edges.contains(handle));
            selection
                .faces
                .retain(|handle| visible.faces.contains(handle));
            selection
                .submeshes
                .retain(|submesh| visible_submeshes.contains(submesh));
        }
        let selection_changed = mesh.selection != selection;
        if selection_changed {
            let _ = mesh.set_selection(selection);
        }
        if selection_changed || force_snapshot {
            self.publish_mesh_snapshot();
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
        self.install_loaded_mesh_with_materials(loaded, false);
    }

    fn install_loaded_mesh_with_materials(&mut self, loaded: LoadedMesh, reuse_materials: bool) {
        let LoadedMesh {
            path,
            document,
            mesh,
            other_lod_meshes,
            textures,
            material_parameters,
            material_factors,
            skeleton,
        } = loaded;
        let editable_lod_count = other_lod_meshes.len().saturating_add(1);
        let texture_resource_count = textures.len();
        let renderer_available = self.renderer.is_some();
        let cdmw_mode = self.cdmw_mode();
        let preserve_deformation_reference = cdmw_mode
            && self
                .deformation_reference
                .as_ref()
                .is_some_and(|reference| reference.matches_loaded_mesh(&mesh));
        if !preserve_deformation_reference {
            self.deformation_reference = Some(PersistentDeformationReference::new(mesh.clone()));
        }
        debug_assert_eq!(editable_lod_count, document.lods.len());
        let per_lod_history_budget = HISTORY_BUDGET_BYTES / editable_lod_count.max(1);

        self.source_label = path.to_string_lossy().replace('\\', "/");
        self.status = format!(
            "Loaded {} vertices and {} faces with {}",
            mesh.vertices().count(),
            mesh.faces().count(),
            document.parser
        );
        if let Some(rectangle) = self.viewport_rect {
            self.camera.frame_all_in_viewport(&mesh, rectangle);
        } else {
            self.camera.frame_all(&mesh);
        }
        self.projection = None;
        self.selection_gesture = None;
        self.edit_gesture = None;
        self.pointer_events.clear();
        self.raw_primary_captured = false;
        self.raw_orbit_captured = false;
        self.raw_pan_captured = false;
        self.show_bones = false;
        let skeleton_lines = skeleton
            .as_ref()
            .map(|loaded| loaded.document.line_vertices())
            .unwrap_or_default();
        self.skeleton_overlay_lines.clone_from(&skeleton_lines);
        let skeleton_entry = skeleton.as_ref().map(|loaded| {
            let mut provenance = format!("Resolved via {:?}", loaded.resolution_method);
            if let Some(compression) = loaded.archive_compression {
                provenance.push_str(&format!(" · Archive decode {compression:?}"));
            }
            let bones = loaded
                .document
                .bones
                .iter()
                .map(|bone| {
                    let name = if bone.name.trim().is_empty() {
                        format!("hash {:08X}", bone.name_hash)
                    } else {
                        format!("{} · hash {:08X}", bone.name, bone.name_hash)
                    };
                    let parent = bone.parent_index.map_or_else(
                        || "root".to_owned(),
                        |index| {
                            loaded.document.bones.get(index as usize).map_or_else(
                                || format!("parent #{index}"),
                                |parent| format!("parent #{index} {}", parent.name),
                            )
                        },
                    );
                    let position = bone.bind_position();
                    format!(
                        "#{} {name} · {parent} · bind {:.4}, {:.4}, {:.4}",
                        bone.index, position[0], position[1], position[2]
                    )
                })
                .collect();
            SkeletonInspectorEntry {
                label: loaded.label.clone(),
                parser: loaded.document.parser.clone(),
                provenance,
                bone_count: loaded.document.bones.len(),
                root_count: loaded.document.root_indices.len(),
                maximum_depth: loaded.document.maximum_depth,
                segment_count: skeleton_lines.len() / 2,
                tail_byte_count: loaded.document.tail_byte_count,
                bones,
            }
        });
        let texture_entries = textures
            .iter()
            .map(|texture| {
                let mut parts = vec![
                    format!("Role {:?}", texture.role),
                    format!("Reference {}", texture.requested_reference),
                    format!("Resolved via {:?}", texture.resolution_method),
                ];
                if let Some(parameter) = &texture.parameter_name {
                    parts.push(format!("Parameter {parameter}"));
                }
                if let Some(sidecar) = &texture.sidecar_label {
                    parts.push(format!("Sidecar {sidecar}"));
                }
                if let Some(compression) = texture.archive_compression {
                    let label = match compression {
                        cdmw_archive::CompressionOutcome::Stored => "Stored",
                        cdmw_archive::CompressionOutcome::PartialRaw => "Partial raw",
                        cdmw_archive::CompressionOutcome::PartialDds => "Partial DDS",
                        cdmw_archive::CompressionOutcome::SparseDds => "Sparse DDS",
                        cdmw_archive::CompressionOutcome::Lz4 => "LZ4",
                    };
                    parts.push(format!("Archive decode {label}"));
                }
                let ownership = format_material_ownership(&texture.material_indices_by_lod);
                TextureInspectorEntry {
                    label: texture.label.clone(),
                    metadata: texture.metadata.clone(),
                    provenance: parts.join(" · "),
                    ownership,
                }
            })
            .collect::<Vec<_>>();
        let material_parameter_entries = material_parameters
            .iter()
            .map(|loaded| {
                let parameter = &loaded.parameter;
                let owner = if !parameter.submesh_name.trim().is_empty() {
                    format!("Submesh {}", parameter.submesh_name)
                } else if !parameter.material_name.trim().is_empty() {
                    format!("Material {}", parameter.material_name)
                } else {
                    "Unnamed owner".to_owned()
                };
                let preview = loaded.preview_semantic.map_or_else(
                    || "Preserved; not sampled by the current material approximation".to_owned(),
                    |semantic| {
                        if semantic.starts_with("Emissive") {
                            format!(
                                "{semantic} candidate; sampled only for non-conflicting ownership with a bound emissive texture"
                            )
                        } else {
                            format!(
                                "{semantic} candidate; sampled only for non-conflicting material ownership"
                            )
                        }
                    },
                );
                MaterialParameterInspectorEntry {
                    label: format!(
                        "{} · {:?}",
                        parameter.parameter_name, parameter.kind
                    ),
                    value: parameter
                        .raw_value
                        .clone()
                        .unwrap_or_else(|| "(no explicit value)".to_owned()),
                    provenance: format!(
                        "{owner} · Wrapper {} · Confidence {:?} · Sidecar {}",
                        parameter.wrapper_type, parameter.confidence, loaded.sidecar_label
                    ),
                    ownership: format_material_ownership(&loaded.material_indices_by_lod),
                    preview,
                }
            })
            .collect::<Vec<_>>();
        let material_factor_entries = material_factors
            .iter()
            .map(|factors| {
                let mut parts = Vec::new();
                if let Some(color) = factors.emissive_color {
                    parts.push(format!(
                        "emissive color {:.3}, {:.3}, {:.3}",
                        color[0], color[1], color[2]
                    ));
                }
                if let Some(value) = factors.emissive_intensity {
                    parts.push(format!("emissive intensity {value:.3}"));
                }
                if let Some(value) = factors.roughness {
                    parts.push(format!("roughness {value:.3}"));
                }
                if let Some(value) = factors.metalness {
                    parts.push(format!("metalness {value:.3}"));
                }
                if let Some(value) = factors.specular {
                    parts.push(format!("specular {value:.3}"));
                }
                if let Some(value) = factors.height_scale {
                    parts.push(format!("height scale {value:.3}"));
                }
                if let Some(value) = factors.alpha_cutoff {
                    let mode = if value > 0.0 { "enabled" } else { "disabled" };
                    parts.push(format!("alpha cutout {mode} · cutoff {value:.3}"));
                }
                if factors.hair_anisotropy == Some(true) {
                    parts.push("hair Flow family qualified".to_owned());
                }
                if let Some(channel) = factors.layer_mask_channel {
                    let label = match channel {
                        0 => "R",
                        1 => "G",
                        2 => "B",
                        3 => "A",
                        _ => "invalid",
                    };
                    parts.push(format!("layer mask channel {label}"));
                }
                MaterialFactorInspectorEntry {
                    summary: parts.join(" · "),
                    provenance: format!(
                        "Sidecar preview factors · {} · non-conflicting material ownership; emissive fields require a bound emissive texture, hair anisotropy requires both Flow and a proven hair/fur family, and the layer-mask selector affects only a bound Layer Mask diagnostic",
                        factors.sidecar_label
                    ),
                    ownership: format_material_ownership(&factors.material_indices_by_lod),
                }
            })
            .collect::<Vec<_>>();
        let mut texture_upload_count = if reuse_materials {
            self.cdmw_uploaded_texture_count
        } else {
            0
        };
        let mut material_factor_count = 0_usize;
        let mut bound_material_count = 0_usize;
        let mut gpu_errors = Vec::new();
        if let Some(renderer) = &mut self.renderer {
            if !reuse_materials {
                renderer.reset_texture();
                #[cfg(test)]
                {
                    self.material_reload_count += 1;
                }
            }
            renderer.set_view_mode(self.view_mode);
            if let Some(rectangle) = self.viewport_rect {
                renderer.set_camera(self.camera.view_projection(rectangle));
            }
            for texture in textures.iter().filter(|_| !reuse_materials) {
                match renderer.add_dds_texture(
                    &texture.bytes,
                    texture.role,
                    &texture.material_indices_by_lod,
                ) {
                    Ok(()) => texture_upload_count = texture_upload_count.saturating_add(1),
                    Err(error) => gpu_errors.push(error.to_string()),
                }
            }
            for factors in material_factors.iter().filter(|_| !reuse_materials) {
                match renderer.add_material_factors(
                    MaterialPreviewFactors {
                        emissive_color: factors.emissive_color,
                        emissive_intensity: factors.emissive_intensity,
                        roughness: factors.roughness,
                        metalness: factors.metalness,
                        specular: factors.specular,
                        height_scale: factors.height_scale,
                        texture_tint: factors.texture_tint,
                        base_tint_strength: factors.base_tint_strength,
                        alpha_cutoff: factors.alpha_cutoff,
                        alpha_blend: factors.alpha_blend,
                        opacity: factors.opacity,
                        gltf_metallic_roughness: factors.gltf_metallic_roughness,
                        hair_anisotropy: factors.hair_anisotropy,
                        layer_mask_channel: factors.layer_mask_channel,
                        skin_detail_scale: factors.skin_detail_scale,
                        skin_detail_opacity: factors.skin_detail_opacity,
                        ..MaterialPreviewFactors::default()
                    },
                    &factors.material_indices_by_lod,
                ) {
                    Ok(()) => material_factor_count = material_factor_count.saturating_add(1),
                    Err(error) => gpu_errors.push(error.to_string()),
                }
            }
            match renderer.set_material_lod(0) {
                Ok(count) => bound_material_count = count,
                Err(error) => gpu_errors.push(error.to_string()),
            }
            let snapshot = mesh.draw_snapshot();
            let deformation_reference = deformation_reference_for_snapshot(
                self.deformation_heatmap_enabled,
                self.deformation_reference.as_mut(),
                None,
                &snapshot,
            );
            if let Err(error) =
                renderer.set_snapshot_with_deformation(&snapshot, deformation_reference)
            {
                gpu_errors.push(format!("mesh upload failed: {error}"));
            }
            if let Err(error) = renderer.set_skeleton_lines(&skeleton_lines) {
                gpu_errors.push(format!("skeleton overlay upload failed: {error}"));
            }
        }
        if self.cdmw_mode() && renderer_available {
            self.record_cdmw_texture_uploads(
                texture_resource_count,
                texture_upload_count,
                bound_material_count,
                gpu_errors.first().map(String::as_str),
            );
        }
        if texture_upload_count > 0 {
            self.status.push_str(&format!(
                " · {texture_upload_count} material texture(s) uploaded for {bound_material_count} LOD0 material range(s)"
            ));
        }
        if material_factor_count > 0 {
            self.status.push_str(&format!(
                " · {material_factor_count} material preview factor set(s) prepared"
            ));
        }
        if let Some(entry) = &skeleton_entry {
            self.status.push_str(&format!(
                " · {} PAB bone(s) resolved for hierarchy context",
                entry.bone_count
            ));
        }
        if let Some(error) = gpu_errors.first() {
            self.status.push_str(&format!(
                " · GPU warning: {error}{}",
                if gpu_errors.len() > 1 {
                    format!(" (+{} more)", gpu_errors.len() - 1)
                } else {
                    String::new()
                }
            ));
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
        self.texture_entries = texture_entries;
        self.material_parameter_entries = material_parameter_entries;
        self.material_factor_entries = material_factor_entries;
        self.skeleton_entry = skeleton_entry;
    }

    fn draw_ui(&mut self, root_ui: &mut egui::Ui) -> Vec<UiAction> {
        if self.cdmw_mode() {
            return self.draw_cdmw_ui(root_ui);
        }
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
                egui::ScrollArea::vertical().show(ui, |ui| {
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
                    ui.label("Renderer: approximate material preview (not Crimson Desert shader parity)");
                    for warning in &document.warnings {
                        ui.colored_label(Color32::YELLOW, warning);
                    }
                    if let Some(skeleton) = &self.skeleton_entry {
                        ui.separator();
                        ui.label(RichText::new("Resolved skeleton context").strong());
                        ui.label(&skeleton.label);
                        ui.label(format!(
                            "{} bones · {} roots · depth {} · {} overlay segments",
                            skeleton.bone_count,
                            skeleton.root_count,
                            skeleton.maximum_depth,
                            skeleton.segment_count
                        ));
                        ui.label(format!(
                            "Parser {} · {} trailing bytes",
                            skeleton.parser, skeleton.tail_byte_count
                        ));
                        ui.label(&skeleton.provenance);
                        ui.label("Read-only hierarchy context; PAC palette/skin binding is still unresolved");
                        egui::CollapsingHeader::new(format!(
                            "Bone hierarchy ({})",
                            skeleton.bones.len()
                        ))
                        .default_open(false)
                        .show(ui, |ui| {
                            for bone in &skeleton.bones {
                                ui.label(bone);
                            }
                        });
                    }
                    if !self.texture_entries.is_empty() {
                        ui.separator();
                        ui.label(RichText::new("Resolved material textures").strong());
                        for (index, texture) in self.texture_entries.iter().enumerate() {
                            if index > 0 {
                                ui.add_space(4.0);
                            }
                            ui.label(&texture.label);
                            ui.label(format!(
                                "{} × {} · {:?} · {:?} · {} mip(s)",
                                texture.metadata.width,
                                texture.metadata.height,
                                texture.metadata.format,
                                texture.metadata.color_space,
                                texture.metadata.mip_count
                            ));
                            ui.label(&texture.provenance);
                            ui.label(format!("Material ranges {}", texture.ownership));
                        }
                    }
                    if !self.material_factor_entries.is_empty() {
                        ui.separator();
                        ui.label(RichText::new("Prepared material factors").strong());
                        for entry in &self.material_factor_entries {
                            ui.label(&entry.summary);
                            ui.label(&entry.provenance);
                            ui.label(format!("Material ranges {}", entry.ownership));
                        }
                    }
                    if !self.material_parameter_entries.is_empty() {
                        ui.separator();
                        egui::CollapsingHeader::new(format!(
                            "Preserved material parameters ({})",
                            self.material_parameter_entries.len()
                        ))
                        .default_open(false)
                        .show(ui, |ui| {
                            for entry in &self.material_parameter_entries {
                                ui.label(&entry.label);
                                ui.label(format!("Value {}", entry.value));
                                ui.label(&entry.provenance);
                                ui.label(format!("Material ranges {}", entry.ownership));
                                ui.label(&entry.preview);
                                ui.add_space(4.0);
                            }
                        });
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
                    .height(360.0)
                    .selected_text(self.view_mode.label())
                    .show_ui(ui, |ui| {
                        for mode in [
                            ViewMode::TexturedSolid,
                            ViewMode::GameOutdoor,
                            ViewMode::BaseColor,
                            ViewMode::NormalMap,
                            ViewMode::UvChecker,
                            ViewMode::BaseAlpha,
                            ViewMode::PartId,
                            ViewMode::MaterialResponse,
                            ViewMode::LayerMask,
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
                    let bones_available = self
                        .skeleton_entry
                        .as_ref()
                        .is_some_and(|skeleton| skeleton.segment_count > 0);
                    ui.add_enabled(
                        bones_available,
                        egui::Checkbox::new(&mut self.show_bones, "Bones"),
                    )
                    .on_disabled_hover_text(if self.skeleton_entry.is_some() {
                        "The decoded skeleton has no parent-child segments to draw"
                    } else {
                        "Bones requires an exact or unambiguous proven-family PAB companion"
                    });
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
                let active_selection_count = match self.selection_domain {
                    SelectionDomain::Vertex => self
                        .mesh
                        .as_ref()
                        .map_or(0, |mesh| mesh.selection.vertices.len()),
                    SelectionDomain::Edge => selected_edges,
                    SelectionDomain::Face => selected_faces,
                };
                ui.horizontal_wrapped(|ui| {
                    if ui
                        .add_enabled(has_mesh, egui::Button::new("All Vertices"))
                        .on_disabled_hover_text("Load a mesh first")
                        .clicked()
                    {
                        actions.push(UiAction::SelectAllVertices);
                    }
                    if ui
                        .add_enabled(has_mesh, egui::Button::new("All Edges"))
                        .on_disabled_hover_text("Load a mesh first")
                        .clicked()
                    {
                        actions.push(UiAction::SelectAllEdges);
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
                ui.horizontal(|ui| {
                    if ui
                        .add_enabled(active_selection_count > 0, egui::Button::new("Linked"))
                        .on_disabled_hover_text("Select an element in the active domain first")
                        .clicked()
                    {
                        actions.push(UiAction::SelectLinked(self.selection_domain));
                    }
                    if ui
                        .add_enabled(active_selection_count > 0, egui::Button::new("Grow"))
                        .on_disabled_hover_text("Select an element in the active domain first")
                        .clicked()
                    {
                        actions.push(UiAction::GrowSelection(self.selection_domain));
                    }
                    if ui
                        .add_enabled(active_selection_count > 0, egui::Button::new("Shrink"))
                        .on_disabled_hover_text("Select an element in the active domain first")
                        .clicked()
                    {
                        actions.push(UiAction::ShrinkSelection(self.selection_domain));
                    }
                    if ui
                        .add_enabled(has_mesh, egui::Button::new("Invert"))
                        .on_disabled_hover_text("Load a mesh first")
                        .clicked()
                    {
                        actions.push(UiAction::InvertSelection(self.selection_domain));
                    }
                });
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
                    if self.viewport_tool != ViewportTool::Grab {
                        ui.add(
                            egui::Slider::new(&mut self.brush_strength, 0.01..=1.0)
                                .text("Strength"),
                        );
                    }
                    egui::ComboBox::from_label("Falloff")
                        .selected_text(self.brush_falloff.label())
                        .show_ui(ui, |ui| {
                            for falloff in [
                                BrushFalloff::Smooth,
                                BrushFalloff::Linear,
                                BrushFalloff::Constant,
                            ] {
                                ui.selectable_value(
                                    &mut self.brush_falloff,
                                    falloff,
                                    falloff.label(),
                                );
                            }
                        });
                    if self.viewport_tool == ViewportTool::Smooth {
                        egui::ComboBox::from_label("Smooth passes")
                            .selected_text(format_pass_count(self.smooth_iterations))
                            .show_ui(ui, |ui| {
                                for passes in 1..=8 {
                                    ui.selectable_value(
                                        &mut self.smooth_iterations,
                                        passes,
                                        format_pass_count(passes),
                                    );
                                }
                            });
                    }
                }
                ui.label("Drag the gizmo for transforms; drag over the surface for sculpt tools. Esc cancels the active gesture.");
                ui.horizontal(|ui| {
                    ui.label("Extrude distance");
                    ui.add(
                        egui::DragValue::new(&mut self.extrude_distance)
                            .speed(0.001)
                            .range(0.000_01..=1_000_000.0)
                            .max_decimals(6),
                    )
                    .on_hover_text("Positive distance along the selected faces' vertex normals");
                });
                ui.horizontal(|ui| {
                    ui.label("Inset amount");
                    ui.add(
                        egui::DragValue::new(&mut self.inset_amount)
                            .speed(0.01)
                            .range(0.01..=0.95)
                            .max_decimals(3),
                    )
                    .on_hover_text(
                        "Fraction from each source corner toward that face's center; faces inset individually",
                    );
                });
                ui.horizontal_wrapped(|ui| {
                    if ui
                        .add_enabled(selected_edges > 0, egui::Button::new("Subdivide Edges"))
                        .on_disabled_hover_text("Select one or more edges first")
                        .clicked()
                    {
                        actions.push(UiAction::SubdivideEdges);
                    }
                    for (label, action) in [
                        ("Delete", UiAction::DeleteFaces),
                        ("Subdivide", UiAction::SubdivideFaces),
                        ("Duplicate", UiAction::DuplicateFaces),
                        (
                            "Duplicate as New Part",
                            UiAction::DuplicateFacesToNewSubmesh,
                        ),
                        ("Extrude", UiAction::ExtrudeFaces),
                        ("Inset Individual", UiAction::InsetFaces),
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
                    "wgpu viewport · D3D12 · {} · {} · material approximation",
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
        let mut cdmw_transaction = None;
        for action in actions {
            if self.cdmw_mode()
                && (self.cdmw_busy() || cdmw_transaction.is_some())
                && !action.allowed_while_cdmw_pending()
            {
                self.status =
                    "Wait for the current CDMW shadow transaction before another edit".to_owned();
                continue;
            }
            match action {
                UiAction::OpenArchive => self.choose_archive(),
                UiAction::OpenMesh => self.choose_mesh(),
                UiAction::QueryArchive => self.query_archive(),
                UiAction::LoadSelectedArchiveEntry => self.load_selected_archive_entry(),
                UiAction::SwitchLod(index) => self.switch_lod(index),
                UiAction::SelectAllVertices => {
                    self.selection_domain = SelectionDomain::Vertex;
                    self.run_selection_command(
                        "Select all vertices",
                        SelectionDomain::Vertex,
                        SelectionCommand::SelectAll,
                    );
                    cdmw_transaction =
                        Some(CdmwLocalEdit::Selection("Select all vertices".to_owned()));
                }
                UiAction::SelectAllEdges => {
                    self.selection_domain = SelectionDomain::Edge;
                    self.run_selection_command(
                        "Select all edges",
                        SelectionDomain::Edge,
                        SelectionCommand::SelectAll,
                    );
                    cdmw_transaction =
                        Some(CdmwLocalEdit::Selection("Select all edges".to_owned()));
                }
                UiAction::SelectAllFaces => {
                    self.selection_domain = SelectionDomain::Face;
                    self.run_selection_command(
                        "Select all faces",
                        SelectionDomain::Face,
                        SelectionCommand::SelectAll,
                    );
                    cdmw_transaction =
                        Some(CdmwLocalEdit::Selection("Select all faces".to_owned()));
                }
                UiAction::SelectLinked(domain) => {
                    self.selection_domain = domain;
                    self.run_selection_command(
                        &format!("Select linked {domain:?} component"),
                        domain,
                        SelectionCommand::SelectLinked,
                    );
                    cdmw_transaction = Some(CdmwLocalEdit::Selection(format!(
                        "Select linked {domain:?}"
                    )));
                }
                UiAction::GrowSelection(domain) => {
                    self.selection_domain = domain;
                    self.run_selection_command(
                        &format!("Grow {domain:?} selection"),
                        domain,
                        SelectionCommand::Grow,
                    );
                    cdmw_transaction = Some(CdmwLocalEdit::Selection(format!(
                        "Grow {domain:?} selection"
                    )));
                }
                UiAction::ShrinkSelection(domain) => {
                    self.selection_domain = domain;
                    self.run_selection_command(
                        &format!("Shrink {domain:?} selection"),
                        domain,
                        SelectionCommand::Shrink,
                    );
                    cdmw_transaction = Some(CdmwLocalEdit::Selection(format!(
                        "Shrink {domain:?} selection"
                    )));
                }
                UiAction::InvertSelection(domain) => {
                    self.selection_domain = domain;
                    self.run_selection_command(
                        &format!("Invert {domain:?} selection"),
                        domain,
                        SelectionCommand::Invert,
                    );
                    cdmw_transaction = Some(CdmwLocalEdit::Selection(format!(
                        "Invert {domain:?} selection"
                    )));
                }
                UiAction::ClearSelection => {
                    self.run_selection_command(
                        "Clear selection",
                        self.selection_domain,
                        SelectionCommand::Clear,
                    );
                    cdmw_transaction = Some(CdmwLocalEdit::Selection("Clear selection".to_owned()));
                }
                UiAction::FrameAll => {
                    if let Some(mesh) = &self.mesh {
                        if let Some(rectangle) = self.viewport_rect {
                            self.camera.frame_all_in_viewport(mesh, rectangle);
                        } else {
                            self.camera.frame_all(mesh);
                        }
                        self.projection = None;
                        self.status = "Camera framed the complete mesh".to_owned();
                    }
                }
                UiAction::FrameSelected => {
                    if let Some(mesh) = &self.mesh {
                        if let Some(rectangle) = self.viewport_rect {
                            self.camera.frame_selected_in_viewport(mesh, rectangle);
                        } else {
                            self.camera.frame_selected(mesh);
                        }
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
                    if self.cdmw_mode() {
                        self.submit_cdmw_topology("delete", "Delete selection", json!({}));
                    } else {
                        self.run_topology("Delete faces", |mesh, faces| mesh.delete_faces(faces));
                        publish_mesh = true;
                    }
                }
                UiAction::SubdivideEdges => {
                    if self.cdmw_mode() {
                        self.submit_cdmw_topology("edge_split", "Subdivide edges", json!({}));
                    } else {
                        self.run_edge_topology("Subdivide edges", |mesh, edges| {
                            mesh.subdivide_edges(edges).map(|_| ())
                        });
                        publish_mesh = true;
                    }
                }
                UiAction::SubdivideFaces => {
                    if self.cdmw_mode() {
                        self.submit_cdmw_topology("subdivide", "Subdivide faces", json!({}));
                    } else {
                        self.run_topology("Subdivide faces", |mesh, faces| {
                            publish_mesh = true;
                            mesh.subdivide_faces(faces).map(|_| ())
                        });
                    }
                }
                UiAction::DuplicateFaces => {
                    if self.cdmw_mode() {
                        self.submit_cdmw_topology("duplicate", "Duplicate faces", json!({}));
                    } else {
                        self.run_topology("Duplicate faces", |mesh, faces| {
                            publish_mesh = true;
                            mesh.duplicate_faces(faces).map(|_| ())
                        });
                    }
                }
                UiAction::DuplicateFacesToNewSubmesh => {
                    if self.cdmw_mode() {
                        self.submit_cdmw_topology(
                            "separate",
                            "Duplicate faces as new part",
                            json!({}),
                        );
                    } else {
                        self.run_topology("Duplicate faces as new part", |mesh, faces| {
                            publish_mesh = true;
                            mesh.duplicate_faces_to_new_submesh(faces).map(|_| ())
                        });
                    }
                }
                UiAction::ExtrudeFaces => {
                    let distance = self.extrude_distance;
                    if self.cdmw_mode() {
                        self.submit_cdmw_topology(
                            "extrude",
                            "Extrude faces",
                            json!({"distance": distance}),
                        );
                    } else {
                        self.run_topology("Extrude faces", |mesh, faces| {
                            publish_mesh = true;
                            mesh.extrude_faces(faces, distance).map(|_| ())
                        });
                    }
                }
                UiAction::InsetFaces => {
                    let amount = self.inset_amount;
                    if self.cdmw_mode() {
                        self.submit_cdmw_topology(
                            "inset",
                            "Inset faces individually",
                            json!({"amount": amount}),
                        );
                    } else {
                        self.run_topology("Inset faces individually", |mesh, faces| {
                            publish_mesh = true;
                            mesh.inset_faces(faces, amount).map(|_| ())
                        });
                    }
                }
                UiAction::Undo => {
                    if self.cdmw_mode() {
                        self.submit_cdmw_command("undo", json!({}), "Undo");
                    } else if let Some(mesh) = &mut self.mesh {
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
                    if self.cdmw_mode() {
                        self.submit_cdmw_command("redo", json!({}), "Redo");
                    } else if let Some(mesh) = &mut self.mesh {
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
                UiAction::ChooseCdmwImportPackage => self.choose_cdmw_import_package(),
                UiAction::FinishCdmw => self.submit_cdmw_finish(),
                UiAction::OrbitMode => {
                    self.cdmw_orbit_mode = true;
                    self.cdmw_rail_page = None;
                    self.status = "Orbit mode · edit tools are inactive".to_owned();
                }
                UiAction::OrbitYaw(degrees) => {
                    self.camera
                        .orbit(Vec2::new(-degrees.to_radians() / 0.008, 0.0));
                    self.projection = None;
                    self.status = format!("Camera yaw changed by {degrees:+.0}°");
                }
                UiAction::Nudge(delta) => {
                    let result = (|| {
                        let mesh = self.mesh.as_mut().ok_or(MeshError::EmptyOperation)?;
                        let handles = mesh.selected_vertex_scope();
                        if handles.is_empty() {
                            return Err(MeshError::EmptyOperation);
                        }
                        let gesture_id = self
                            .operator
                            .begin(mesh, "Axis move")
                            .map_err(|_| MeshError::EmptyOperation)?;
                        if self
                            .operator
                            .translate(mesh, gesture_id, &handles, delta)
                            .is_err()
                        {
                            let _ = self.operator.cancel(mesh, gesture_id);
                            return Err(MeshError::EmptyOperation);
                        }
                        self.operator
                            .confirm(mesh, &mut self.history, gesture_id)
                            .map_err(|_| MeshError::EmptyOperation)
                    })();
                    match result {
                        Ok(()) => {
                            cdmw_transaction =
                                Some(CdmwLocalEdit::Geometry("Axis move".to_owned()));
                            self.projection = None;
                        }
                        Err(error) => self.status = format!("Axis move failed: {error}"),
                    }
                }
                UiAction::RotateStep { axis, degrees } => {
                    let result = (|| {
                        let mesh = self.mesh.as_mut().ok_or(MeshError::EmptyOperation)?;
                        let handles = mesh.selected_vertex_scope();
                        let pivot =
                            center_of_handles(mesh, &handles).ok_or(MeshError::EmptyOperation)?;
                        if handles.is_empty() || axis.length_squared() <= f32::EPSILON {
                            return Err(MeshError::EmptyOperation);
                        }
                        let gesture_id = self
                            .operator
                            .begin(mesh, "Axis rotate")
                            .map_err(|_| MeshError::EmptyOperation)?;
                        if self
                            .operator
                            .rotate(
                                mesh,
                                gesture_id,
                                &handles,
                                pivot,
                                Quat::from_axis_angle(axis.normalize(), degrees.to_radians()),
                            )
                            .is_err()
                        {
                            let _ = self.operator.cancel(mesh, gesture_id);
                            return Err(MeshError::EmptyOperation);
                        }
                        self.operator
                            .confirm(mesh, &mut self.history, gesture_id)
                            .map_err(|_| MeshError::EmptyOperation)
                    })();
                    match result {
                        Ok(()) => {
                            cdmw_transaction =
                                Some(CdmwLocalEdit::Geometry("Axis rotate".to_owned()));
                            self.projection = None;
                        }
                        Err(error) => self.status = format!("Axis rotate failed: {error}"),
                    }
                }
                UiAction::ScaleStep(scale) => {
                    let result = (|| {
                        let mesh = self.mesh.as_mut().ok_or(MeshError::EmptyOperation)?;
                        let handles = mesh.selected_vertex_scope();
                        let pivot =
                            center_of_handles(mesh, &handles).ok_or(MeshError::EmptyOperation)?;
                        if handles.is_empty() || scale.x <= 0.0 || scale.y <= 0.0 || scale.z <= 0.0
                        {
                            return Err(MeshError::EmptyOperation);
                        }
                        let gesture_id = self
                            .operator
                            .begin(mesh, "Axis scale")
                            .map_err(|_| MeshError::EmptyOperation)?;
                        if self
                            .operator
                            .scale(mesh, gesture_id, &handles, pivot, scale)
                            .is_err()
                        {
                            let _ = self.operator.cancel(mesh, gesture_id);
                            return Err(MeshError::EmptyOperation);
                        }
                        self.operator
                            .confirm(mesh, &mut self.history, gesture_id)
                            .map_err(|_| MeshError::EmptyOperation)
                    })();
                    match result {
                        Ok(()) => {
                            cdmw_transaction =
                                Some(CdmwLocalEdit::Geometry("Axis scale".to_owned()));
                            self.projection = None;
                        }
                        Err(error) => self.status = format!("Axis scale failed: {error}"),
                    }
                }
                UiAction::CdmwCommand {
                    command,
                    arguments,
                    label,
                } => self.submit_cdmw_command(command, arguments, label),
                UiAction::CdmwMeshAction {
                    action,
                    label,
                    params,
                } => self.submit_cdmw_mesh_action(action, label, params),
                UiAction::CdmwTopology {
                    action,
                    label,
                    params,
                } => self.submit_cdmw_topology(action, label, params),
                UiAction::SetPartSelection(indices) => {
                    let visible_submeshes = self.cdmw_visible_submeshes();
                    if let Some(mesh) = &mut self.mesh {
                        let selection = Selection {
                            submeshes: indices
                                .into_iter()
                                .filter(|index| {
                                    visible_submeshes
                                        .as_ref()
                                        .is_none_or(|visible| visible.contains(index))
                                })
                                .collect(),
                            ..Selection::default()
                        };
                        match mesh.set_selection(selection) {
                            Ok(()) => {
                                cdmw_transaction =
                                    Some(CdmwLocalEdit::Selection("Select parts".to_owned()))
                            }
                            Err(error) => {
                                self.status = format!("Part selection failed: {error}");
                            }
                        }
                    }
                }
            }
        }
        if publish_mesh {
            self.publish_mesh_snapshot();
        }
        if self.cdmw_mode()
            && let Some(label) = cdmw_transaction
        {
            self.submit_cdmw_local_edit(label);
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
        self.deformation_reference = self
            .mesh
            .as_ref()
            .cloned()
            .map(PersistentDeformationReference::new);
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
        let renderer_available = self.renderer.is_some();
        let mut bound_material_count = 0_usize;
        let mut texture_warning = None;
        if let Some(renderer) = &mut self.renderer {
            match renderer.set_material_lod(target_index) {
                Ok(count) => {
                    bound_material_count = count;
                    if count > 0 {
                        self.status
                            .push_str(&format!(" · {count} material range(s) textured"));
                    }
                }
                Err(error) => {
                    texture_warning = Some(error.to_string());
                    self.status
                        .push_str(&format!(" · texture binding warning: {error}"));
                }
            }
        }
        if self.cdmw_mode() && renderer_available {
            self.record_cdmw_texture_uploads(
                self.cdmw_texture_resources.len(),
                self.cdmw_uploaded_texture_count,
                bound_material_count,
                texture_warning.as_deref(),
            );
        }
        self.publish_mesh_snapshot();
    }

    fn run_selection_command(
        &mut self,
        label: &str,
        domain: SelectionDomain,
        command: SelectionCommand,
    ) {
        let visible_submeshes = self.cdmw_visible_submeshes();
        let result = (|| -> Result<bool, MeshError> {
            let mesh = self.mesh.as_mut().ok_or(MeshError::EmptyOperation)?;
            let mut next = selection_after_command(mesh, domain, command);
            if let Some(visible_submeshes) = &visible_submeshes {
                let visible = mesh.element_handles_for_submeshes(visible_submeshes);
                next.vertices
                    .retain(|handle| visible.vertices.contains(handle));
                next.edges.retain(|handle| visible.edges.contains(handle));
                next.faces.retain(|handle| visible.faces.contains(handle));
                next.submeshes
                    .retain(|submesh| visible_submeshes.contains(submesh));
            }
            if mesh.selection == next {
                return Ok(false);
            }
            let before = mesh.clone();
            mesh.set_selection(next)?;
            if let Err(error) = self.history.commit(label, before.clone(), mesh) {
                *mesh = before;
                return Err(error);
            }
            Ok(true)
        })();
        self.status = match result {
            Ok(true) => format!("{label} committed as one undo entry"),
            Ok(false) => format!("{label} made no change"),
            Err(error) => format!("{label} failed: {error}"),
        };
    }

    #[cfg(test)]
    fn select_all_vertices(&mut self) {
        if let Some(mesh) = &mut self.mesh {
            let selection =
                selection_after_command(mesh, SelectionDomain::Vertex, SelectionCommand::SelectAll);
            if let Err(error) = mesh.set_selection(selection) {
                self.status = error.to_string();
            }
        }
    }

    #[cfg(test)]
    fn select_all_faces(&mut self) {
        if let Some(mesh) = &mut self.mesh {
            let selection =
                selection_after_command(mesh, SelectionDomain::Face, SelectionCommand::SelectAll);
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

    fn choose_cdmw_import_package(&mut self) {
        let Some(path) = rfd::FileDialog::new()
            .set_title("Choose an editable mesh package")
            .pick_folder()
        else {
            return;
        };
        self.handle_actions(vec![cdmw_import_editable_package_action(&path)]);
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

    fn run_edge_topology(
        &mut self,
        label: &str,
        operation: impl FnOnce(
            &mut WorkingMesh,
            &std::collections::HashSet<cdmw_mesh::EdgeHandle>,
        ) -> Result<(), cdmw_mesh::MeshError>,
    ) {
        let Some(mesh) = &mut self.mesh else {
            return;
        };
        let edges = mesh.selection.edges.clone();
        let before = mesh.clone();
        match operation(mesh, &edges).and_then(|()| self.history.commit(label, before, mesh)) {
            Ok(()) => self.status = format!("{label} committed as one undo entry"),
            Err(error) => self.status = error.to_string(),
        }
    }

    fn ensure_deformation_reference(&mut self) {
        let Some(mesh) = self.mesh.as_ref() else {
            self.deformation_reference = None;
            return;
        };
        let needs_reset = self
            .deformation_reference
            .as_ref()
            .is_none_or(|reference| reference.mesh.topology_generation != mesh.topology_generation);
        if needs_reset {
            self.deformation_reference = Some(PersistentDeformationReference::new(mesh.clone()));
        }
    }

    fn publish_mesh_snapshot(&mut self) {
        self.face_selection_overlay = None;
        self.selected_counts_cache.set(None);
        if let Some(renderer) = &mut self.renderer {
            let _ = renderer.set_face_selection(&[], [0.0; 4]);
        }
        self.projection = None;
        self.ensure_deformation_reference();
        let visible_submeshes = self.cdmw_visible_submeshes();
        let snapshot = self.mesh.as_ref().map(|mesh| {
            visible_submeshes.as_ref().map_or_else(
                || mesh.draw_snapshot(),
                |visible| mesh.draw_snapshot_for_submeshes(visible),
            )
        });
        let deformation_reference = snapshot.as_ref().and_then(|snapshot| {
            deformation_reference_for_snapshot(
                self.deformation_heatmap_enabled,
                self.deformation_reference.as_mut(),
                visible_submeshes.as_ref(),
                snapshot,
            )
        });
        if let (Some(renderer), Some(snapshot)) = (&mut self.renderer, snapshot)
            && let Err(error) = if self.edit_gesture.is_some() {
                renderer.set_snapshot_with_deformation_interactive(&snapshot, deformation_reference)
            } else {
                renderer.set_snapshot_with_deformation(&snapshot, deformation_reference)
            }
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
        let first_viewport = self.viewport_rect.is_none();
        self.viewport_rect = Some(rectangle);
        self.viewport_revision = self.viewport_revision.saturating_add(1);
        self.projection = None;
        if first_viewport && let Some(mesh) = &self.mesh {
            self.camera.frame_all_in_viewport(mesh, rectangle);
        }
    }

    fn ensure_projection(&mut self, rectangle: egui::Rect) -> bool {
        let visible_submeshes = self.cdmw_visible_submeshes();
        let Some(mesh) = &self.mesh else {
            self.projection = None;
            return false;
        };
        let matches = self.projection.as_ref().is_some_and(|projection| {
            visible_submeshes.as_ref().map_or_else(
                || projection.matches(mesh, &self.camera, rectangle, self.viewport_revision),
                |visible| {
                    projection.matches_for_submeshes(
                        mesh,
                        &self.camera,
                        rectangle,
                        self.viewport_revision,
                        visible,
                    )
                },
            )
        });
        if !matches {
            self.projection = Some(visible_submeshes.as_ref().map_or_else(
                || ViewportProjection::build(mesh, &self.camera, rectangle, self.viewport_revision),
                |visible| {
                    ViewportProjection::build_for_submeshes(
                        mesh,
                        &self.camera,
                        rectangle,
                        self.viewport_revision,
                        visible,
                    )
                },
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
                    if self.viewport_tool == ViewportTool::Select
                        && matches!(
                            self.selection_tool,
                            SelectionTool::Lasso | SelectionTool::Brush
                        )
                    {
                        self.pointer_events.push_primary_path_point(next);
                    } else {
                        self.pointer_events
                            .push(ViewportPointerEvent::PrimaryMoved(next));
                    }
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
        let edit_gesture_before = self.edit_gesture.is_some();
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
        let edit_gesture_finished = edit_gesture_before && self.edit_gesture.is_none();
        if geometry_before != geometry_after || edit_gesture_finished {
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
                    self.camera.frame_all_in_viewport(mesh, rectangle);
                } else {
                    self.camera.frame_selected_in_viewport(mesh, rectangle);
                }
                self.projection = None;
            }
        }

        // Raw viewport pointer events already request a redraw. Keeping a gesture open does not
        // animate anything by itself, so an unconditional repaint loop only competes with brush
        // projection and GPU uploads while the pointer is stationary.
    }

    fn begin_primary_gesture(&mut self, rectangle: egui::Rect, point: Vec2) {
        if self.mesh.is_none() || self.selection_gesture.is_some() || self.edit_gesture.is_some() {
            return;
        }
        if self.cdmw_mode() && (self.cdmw_busy() || self.cdmw_orbit_mode) {
            self.status = if self.cdmw_busy() {
                "The current shadow operation must finish before another gesture starts".to_owned()
            } else {
                "Choose Select, Move, Rotate, Scale, Grab, Smooth, Inflate, or Pinch to edit"
                    .to_owned()
            };
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
        self.ensure_deformation_reference();
        let Some(mesh) = &self.mesh else {
            return;
        };
        let selected_handles = mesh.selected_vertex_scope();
        let pivot = OrbitCamera::selected_center(mesh).unwrap_or_else(|| self.camera.target());
        let mut symmetry_map = SculptSymmetryMap::build(mesh, SculptSymmetry::Off);
        let mut symmetry_primary_weights = HashMap::new();
        let mut symmetry_mirrored_weights = HashMap::new();
        let mut symmetry_plane_weights = HashMap::new();
        let (axis, handles, sculpt_weights) = if matches!(
            self.viewport_tool,
            ViewportTool::Move | ViewportTool::Rotate | ViewportTool::Scale
        ) {
            if selected_handles.is_empty() {
                self.status =
                    "Select vertices, edges, faces, or Parts before transforming".to_owned();
                return;
            }
            let Some(axis) = self.hit_test_gizmo(self.viewport_tool, point, pivot, rectangle)
            else {
                self.status = "Drag a visible gizmo axis, ring, or center handle".to_owned();
                return;
            };
            (axis, selected_handles, Default::default())
        } else {
            symmetry_map = SculptSymmetryMap::build(mesh, self.sculpt_symmetry);
            let source_weights = self
                .projection
                .as_ref()
                .and_then(|projection| {
                    if self.sculpt_symmetry == SculptSymmetry::Off {
                        brush_vertex_weights(
                            mesh,
                            projection,
                            point,
                            self.brush_radius,
                            true,
                            self.brush_falloff,
                        )
                    } else {
                        brush_vertex_weights_unclipped(
                            projection,
                            point,
                            self.brush_radius,
                            true,
                            self.brush_falloff,
                        )
                    }
                    .ok()
                })
                .unwrap_or_default();
            let expanded = symmetry_map.expand_weights(mesh, &source_weights);
            symmetry_primary_weights = expanded.primary;
            symmetry_mirrored_weights = expanded.mirrored;
            symmetry_plane_weights = expanded.plane;
            let sculpt_weights = expanded.combined;
            let handles = sculpt_weights
                .keys()
                .copied()
                .collect::<std::collections::HashSet<_>>();
            if handles.is_empty() {
                self.status = if self.sculpt_symmetry == SculptSymmetry::Off {
                    "The sculpt brush has no eligible vertices here".to_owned()
                } else {
                    format!(
                        "{} symmetry has no paired eligible vertices here · {} unmatched vertices remain untouched",
                        self.sculpt_symmetry.label(),
                        symmetry_map.unmatched_vertices()
                    )
                };
                return;
            }
            (GizmoAxis::Free, handles, sculpt_weights)
        };
        let symmetry_status = if self.sculpt_symmetry != SculptSymmetry::Off
            && self.viewport_tool.sculpt_tool().is_some()
        {
            format!(
                " · {} symmetry: {} mirrored, {} on plane, {} unmatched untouched",
                self.sculpt_symmetry.label(),
                symmetry_map.paired_vertices(),
                symmetry_map.plane_vertices(),
                symmetry_map.unmatched_vertices()
            )
        } else {
            String::new()
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
            sculpt_weights,
            symmetry_map,
            symmetry_primary_weights,
            symmetry_mirrored_weights,
            symmetry_plane_weights,
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
            "{} preview · release to commit · Esc cancels{}",
            self.viewport_tool.label(),
            symmetry_status
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
                    if gesture.symmetry_map.mode == SculptSymmetry::Off {
                        self.operator.sculpt_weighted(
                            mesh,
                            gesture.gesture_id,
                            cdmw_interaction::SculptTool::Grab,
                            &gesture.sculpt_weights,
                            gesture.pivot,
                            delta,
                            1.0,
                        )
                    } else {
                        sculpt_weighted_if_any(
                            &self.operator,
                            mesh,
                            gesture.gesture_id,
                            cdmw_interaction::SculptTool::Grab,
                            &gesture.symmetry_primary_weights,
                            gesture.pivot,
                            delta,
                            1.0,
                        )?;
                        sculpt_weighted_if_any(
                            &self.operator,
                            mesh,
                            gesture.gesture_id,
                            cdmw_interaction::SculptTool::Grab,
                            &gesture.symmetry_mirrored_weights,
                            gesture.symmetry_map.mode.reflect_point(gesture.pivot),
                            gesture.symmetry_map.mode.reflect_point(delta),
                            1.0,
                        )?;
                        sculpt_weighted_if_any(
                            &self.operator,
                            mesh,
                            gesture.gesture_id,
                            cdmw_interaction::SculptTool::Grab,
                            &gesture.symmetry_plane_weights,
                            gesture.symmetry_map.mode.plane_vector(gesture.pivot),
                            gesture.symmetry_map.mode.plane_vector(delta),
                            1.0,
                        )?;
                        Ok(())
                    }
                }
                ViewportTool::Smooth | ViewportTool::Inflate | ViewportTool::Pinch => {
                    if let Some(projection) = &self.projection {
                        let source_weights = if gesture.symmetry_map.mode == SculptSymmetry::Off {
                            brush_vertex_weights(
                                mesh,
                                projection,
                                point,
                                self.brush_radius,
                                true,
                                self.brush_falloff,
                            )
                        } else {
                            brush_vertex_weights_unclipped(
                                projection,
                                point,
                                self.brush_radius,
                                true,
                                self.brush_falloff,
                            )
                        }?;
                        let expanded = gesture.symmetry_map.expand_weights(mesh, &source_weights);
                        // Leaving the editable surface during an otherwise valid stroke is a
                        // normal no-hit sample, not malformed pointer input. Keep every prior
                        // deformation in this gesture and wait for the next eligible sample.
                        if expanded.combined.is_empty() {
                            return Ok(());
                        }
                        gesture.sculpt_weights = expanded.combined;
                        gesture.symmetry_primary_weights = expanded.primary;
                        gesture.symmetry_mirrored_weights = expanded.mirrored;
                        gesture.symmetry_plane_weights = expanded.plane;
                        gesture.handles = gesture.sculpt_weights.keys().copied().collect();
                    }
                    gesture.pivot = center_of_handles(mesh, &gesture.handles)
                        .ok_or(cdmw_interaction::InteractionError::InvalidShape)?;
                    if gesture.tool == ViewportTool::Pinch {
                        gesture.pivot = self
                            .camera
                            .point_on_view_plane(point, gesture.pivot, rectangle)
                            .ok_or(cdmw_interaction::InteractionError::InvalidShape)?;
                    }
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
                    let passes = if tool == cdmw_interaction::SculptTool::Smooth {
                        self.smooth_iterations
                    } else {
                        1
                    };
                    for _ in 0..passes {
                        if tool == cdmw_interaction::SculptTool::Pinch
                            && gesture.symmetry_map.mode != SculptSymmetry::Off
                        {
                            sculpt_weighted_if_any(
                                &self.operator,
                                mesh,
                                gesture.gesture_id,
                                tool,
                                &gesture.symmetry_primary_weights,
                                gesture.pivot,
                                Vec3::ZERO,
                                strength,
                            )?;
                            sculpt_weighted_if_any(
                                &self.operator,
                                mesh,
                                gesture.gesture_id,
                                tool,
                                &gesture.symmetry_mirrored_weights,
                                gesture.symmetry_map.mode.reflect_point(gesture.pivot),
                                Vec3::ZERO,
                                strength,
                            )?;
                            sculpt_weighted_if_any(
                                &self.operator,
                                mesh,
                                gesture.gesture_id,
                                tool,
                                &gesture.symmetry_plane_weights,
                                gesture.symmetry_map.mode.plane_vector(gesture.pivot),
                                Vec3::ZERO,
                                strength,
                            )?;
                        } else {
                            self.operator.sculpt_weighted(
                                mesh,
                                gesture.gesture_id,
                                tool,
                                &gesture.sculpt_weights,
                                gesture.pivot,
                                Vec3::ZERO,
                                strength,
                            )?;
                        }
                    }
                    Ok(())
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
        let mut cdmw_transaction = None;
        if let Some(gesture) = self.selection_gesture.take() {
            let result = self
                .mesh
                .as_ref()
                .map_or(Ok(false), |mesh| gesture.commit(mesh, &mut self.history));
            self.status = match result {
                Ok(true) => {
                    let label = format!("{} selection", self.selection_tool.label());
                    cdmw_transaction = Some(CdmwLocalEdit::Selection(label));
                    format!(
                        "{} selection committed as one undo entry",
                        self.selection_tool.label()
                    )
                }
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
                Ok(()) => {
                    cdmw_transaction =
                        Some(CdmwLocalEdit::Geometry(gesture.tool.label().to_owned()));
                    format!("{} committed as one undo entry", gesture.tool.label())
                }
                Err(error) => format!("Tool commit failed: {error}"),
            };
        }
        if self.cdmw_mode()
            && let Some(label) = cdmw_transaction
        {
            self.submit_cdmw_local_edit(label);
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

    fn refresh_face_selection_overlay(&mut self) {
        let visible = self.cdmw_visible_submeshes();
        let mut colour = renderer_colour(self.overlay_selection_colour);
        colour[3] = 72.0 / 255.0;
        let Some(mesh) = &self.mesh else {
            self.face_selection_overlay = None;
            if let Some(renderer) = &mut self.renderer {
                let _ = renderer.set_face_selection(&[], colour);
            }
            return;
        };
        if self
            .face_selection_overlay
            .as_ref()
            .is_none_or(|overlay| !overlay.matches(mesh, &visible, colour))
        {
            self.face_selection_overlay = Some(FaceSelectionOverlay::build(mesh, visible, colour));
        }
        if let (Some(renderer), Some(overlay)) =
            (&mut self.renderer, &mut self.face_selection_overlay)
        {
            renderer.set_face_selection_xray(
                !self.selection_visible_only || self.view_mode == ViewMode::XRay,
            );
            if !overlay.uploaded {
                match renderer.set_face_selection(&overlay.positions, colour) {
                    Ok(()) => overlay.uploaded = true,
                    Err(error) => self.status = format!("Selection highlight failed: {error}"),
                }
            }
        }
    }

    fn paint_viewport_overlay(&mut self, ui: &egui::Ui, rectangle: egui::Rect) {
        self.refresh_face_selection_overlay();
        // Face highlights use GPU depth; a CPU projection is only needed for vertex/edge
        // markers and actual picking, never for ordinary camera navigation or face display.
        if self.mesh.as_ref().is_none_or(|mesh| {
            mesh.selection.vertices.is_empty() && mesh.selection.edges.is_empty()
        }) {
            self.paint_active_shape(ui);
            self.paint_gizmo(ui, rectangle);
            return;
        }
        if !self.ensure_projection(rectangle) {
            return;
        }
        let (Some(mesh), Some(projection)) = (&self.mesh, &self.projection) else {
            return;
        };
        let painter = ui.painter();
        // Wireframe and point display are rendered by the depth-tested wgpu pipelines. Painting
        // the same base geometry again in egui made every rear edge/vertex look permanently
        // X-rayed. Egui owns the vertex/edge markers and gesture guides.
        let selection_xray = !self.selection_visible_only || self.view_mode == ViewMode::XRay;
        let mut depth_visible = Selection::default();
        if !selection_xray {
            let query_domain = |domain| {
                query_selection(
                    &projection.interaction,
                    &SelectionQuery {
                        domain,
                        operation: SelectionOperation::Replace,
                        visible_only: true,
                        shape: SelectionShape::Rectangle {
                            minimum: Vec2::new(rectangle.left(), rectangle.top()),
                            maximum: Vec2::new(rectangle.right(), rectangle.bottom()),
                        },
                        geometry_revision: projection.interaction.geometry_revision,
                        topology_generation: projection.interaction.topology_generation,
                        camera_revision: projection.interaction.camera_revision,
                        viewport_revision: projection.interaction.viewport_revision,
                    },
                )
                .unwrap_or_default()
            };
            if !mesh.selection.vertices.is_empty() {
                depth_visible.vertices = query_domain(SelectionDomain::Vertex).vertices;
            }
            if !mesh.selection.edges.is_empty() {
                depth_visible.edges = query_domain(SelectionDomain::Edge).edges;
            }
        }
        for handle in mesh
            .selection
            .vertices
            .iter()
            .filter(|handle| selection_xray || depth_visible.vertices.contains(handle))
        {
            if let Some(projected) = projection.vertices.get(handle) {
                painter.circle_filled(
                    egui::pos2(projected.screen.x, projected.screen.y),
                    (self.overlay_vertex_size + 1.5).max(2.0),
                    self.overlay_selection_colour,
                );
            }
        }
        for handle in mesh
            .selection
            .edges
            .iter()
            .filter(|handle| selection_xray || depth_visible.edges.contains(handle))
        {
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
                    Stroke::new(
                        (self.overlay_wire_width + 0.8).max(1.0),
                        self.overlay_selection_colour,
                    ),
                );
            }
        }
        self.paint_active_shape(ui);
        self.paint_gizmo(ui, rectangle);
    }

    fn paint_active_shape(&self, ui: &egui::Ui) {
        let painter = ui.painter();
        let stroke = Stroke::new(2.0, self.overlay_live_selection_colour);
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
        if self.deformation_heatmap_applied != self.deformation_heatmap_enabled {
            self.deformation_heatmap_applied = self.deformation_heatmap_enabled;
            self.publish_mesh_snapshot();
        }
        let paint_jobs = context.tessellate(full_output.shapes, full_output.pixels_per_point);
        let camera_matrix = self
            .viewport_rect
            .map(|rectangle| self.camera.view_projection(rectangle));
        let view_mode = self.view_mode;
        let show_normals = self.show_normals;
        let show_bounds = self.show_bounds;
        let show_bones = self.show_bones;
        let background = self.viewport_background_colour;
        let wire_colour = renderer_colour(self.overlay_wire_colour);
        let point_colour = renderer_colour(self.overlay_vertex_colour);
        let render_error = if let Some(renderer) = &mut self.renderer {
            renderer.set_view_mode(view_mode);
            renderer.set_overlays(show_normals, show_bounds);
            renderer.set_overlay_colours(wire_colour, point_colour);
            renderer.set_bone_overlay(show_bones);
            renderer.set_clear_colour([
                f32::from(background.r()) / 255.0,
                f32::from(background.g()) / 255.0,
                f32::from(background.b()) / 255.0,
                1.0,
            ]);
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

fn parse_cdmw_skeleton_overlay(state: &Value) -> Result<CdmwSkeletonOverlay, String> {
    let skeleton = state
        .get("skeleton")
        .and_then(Value::as_object)
        .ok_or_else(|| "No skeleton hierarchy is present in this authoring session".to_owned())?;
    if skeleton.get("available").and_then(Value::as_bool) != Some(true) {
        return Err("The host did not provide an editable skeleton hierarchy".to_owned());
    }
    if skeleton.get("bones_truncated").and_then(Value::as_bool) != Some(false) {
        return Err("The skeleton hierarchy is truncated, so its overlay is disabled".to_owned());
    }
    if skeleton
        .get("skeleton_parse_warning")
        .and_then(Value::as_str)
        .is_some_and(|warning| !warning.trim().is_empty())
    {
        return Err("The skeleton parser reported an incomplete hierarchy".to_owned());
    }
    let bone_count = skeleton
        .get("bone_count")
        .and_then(Value::as_u64)
        .and_then(|count| usize::try_from(count).ok())
        .filter(|count| *count > 0 && *count <= 4_096)
        .ok_or_else(|| "The skeleton hierarchy has no bounded bone count".to_owned())?;
    let linked_count = skeleton
        .get("skeleton_bone_count")
        .and_then(Value::as_u64)
        .and_then(|count| usize::try_from(count).ok())
        .ok_or_else(|| "No complete linked skeleton hierarchy is available".to_owned())?;
    let bones = skeleton
        .get("bones")
        .and_then(Value::as_array)
        .ok_or_else(|| "The skeleton hierarchy omitted its bone rows".to_owned())?;
    if linked_count != bone_count || bones.len() != bone_count {
        return Err("The skeleton hierarchy bone counts do not match".to_owned());
    }

    let mut positions = vec![None; bone_count];
    let mut parents = vec![None; bone_count];
    for bone in bones {
        let index = bone
            .get("index")
            .and_then(Value::as_u64)
            .and_then(|value| usize::try_from(value).ok())
            .filter(|index| *index < bone_count)
            .ok_or_else(|| "The skeleton hierarchy contains an invalid bone index".to_owned())?;
        if positions[index].is_some() {
            return Err("The skeleton hierarchy contains a duplicate bone index".to_owned());
        }
        let coordinates = bone
            .get("position")
            .and_then(Value::as_array)
            .filter(|values| values.len() == 3)
            .ok_or_else(|| {
                "The skeleton hierarchy contains an incomplete bone position".to_owned()
            })?;
        let mut position = [0.0_f32; 3];
        for (target, value) in position.iter_mut().zip(coordinates) {
            let coordinate = value
                .as_f64()
                .filter(|coordinate| coordinate.is_finite())
                .ok_or_else(|| {
                    "The skeleton hierarchy contains a non-finite bone position".to_owned()
                })? as f32;
            if !coordinate.is_finite() {
                return Err(
                    "The skeleton hierarchy contains an out-of-range bone position".to_owned(),
                );
            }
            *target = coordinate;
        }
        let parent = bone
            .get("parent_index")
            .and_then(Value::as_i64)
            .ok_or_else(|| "The skeleton hierarchy omitted a parent index".to_owned())?;
        parents[index] = if parent < 0 {
            None
        } else {
            let parent = usize::try_from(parent)
                .ok()
                .filter(|parent| *parent < bone_count && *parent != index)
                .ok_or_else(|| {
                    "The skeleton hierarchy contains an invalid parent index".to_owned()
                })?;
            Some(parent)
        };
        positions[index] = Some(position);
    }
    if positions.iter().any(Option::is_none) || parents.iter().all(Option::is_some) {
        return Err("The skeleton hierarchy is incomplete or has no root".to_owned());
    }
    for start in 0..bone_count {
        let mut visited = HashSet::new();
        let mut current = Some(start);
        while let Some(index) = current {
            if !visited.insert(index) {
                return Err("The skeleton hierarchy contains a parent cycle".to_owned());
            }
            current = parents[index];
        }
    }
    let positions = positions
        .into_iter()
        .collect::<Option<Vec<_>>>()
        .ok_or_else(|| "The skeleton hierarchy omitted a bone position".to_owned())?;
    let mut lines = Vec::with_capacity(bone_count.saturating_sub(1).saturating_mul(2));
    for (index, parent) in parents.into_iter().enumerate() {
        if let Some(parent) = parent {
            lines.push(positions[parent]);
            lines.push(positions[index]);
        }
    }
    if lines.is_empty() {
        return Err("The skeleton hierarchy has no parent-child segments to draw".to_owned());
    }
    Ok(CdmwSkeletonOverlay { bone_count, lines })
}

fn index_map(value: &Value, key: &str) -> HashMap<u32, HashSet<u32>> {
    value
        .get(key)
        .and_then(Value::as_object)
        .into_iter()
        .flatten()
        .filter_map(|(submesh, values)| {
            let submesh = submesh.parse::<u32>().ok()?;
            let indices = values
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(Value::as_u64)
                .filter_map(|item| u32::try_from(item).ok())
                .collect::<HashSet<_>>();
            Some((submesh, indices))
        })
        .collect()
}

fn edge_map(value: &Value, key: &str) -> HashMap<u32, HashSet<(u32, u32)>> {
    value
        .get(key)
        .and_then(Value::as_object)
        .into_iter()
        .flatten()
        .filter_map(|(submesh, values)| {
            let submesh = submesh.parse::<u32>().ok()?;
            let edges = values
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(Value::as_array)
                .filter_map(|edge| {
                    let first = u32::try_from(edge.first()?.as_u64()?).ok()?;
                    let second = u32::try_from(edge.get(1)?.as_u64()?).ok()?;
                    Some((first.min(second), first.max(second)))
                })
                .collect::<HashSet<_>>();
            Some((submesh, edges))
        })
        .collect()
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

fn sculpt_weighted_if_any(
    operator: &OperatorController,
    mesh: &mut WorkingMesh,
    gesture_id: u64,
    tool: cdmw_interaction::SculptTool,
    weights: &HashMap<VertexHandle, f32>,
    center: Vec3,
    delta: Vec3,
    strength: f32,
) -> Result<(), cdmw_interaction::InteractionError> {
    if weights.is_empty() {
        return Ok(());
    }
    operator.sculpt_weighted(mesh, gesture_id, tool, weights, center, delta, strength)
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

fn renderer_colour(colour: Color32) -> [f32; 4] {
    [
        f32::from(colour.r()) / 255.0,
        f32::from(colour.g()) / 255.0,
        f32::from(colour.b()) / 255.0,
        f32::from(colour.a()) / 255.0,
    ]
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
        let mut attributes = WindowAttributes::default()
            .with_title(if self.cdmw_mode() {
                "CDMW — Mesh Editor"
            } else {
                "CDMW Rust Mesh Lab"
            })
            .with_inner_size(winit::dpi::LogicalSize::new(1440.0, 900.0));
        if let Some(parent_hwnd) = self.embedded_parent_hwnd {
            attributes = match cdmw_win32_embed::with_parent_window(
                attributes.with_decorations(false).with_visible(false),
                parent_hwnd,
            ) {
                Ok(attributes) => attributes,
                Err(error) => {
                    error!("embedded parent window is invalid: {error}");
                    event_loop.exit();
                    return;
                }
            };
        }
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
        let quality = renderer.quality_report();
        self.status = format!(
            "D3D12 adapter: {} ({}) · {}x AA · {}x texture filtering",
            adapter.name, adapter.driver_info, quality.sample_count, quality.anisotropy_clamp,
        );
        let mut renderer = renderer;
        let mut texture_upload_count = 0_usize;
        let mut bound_material_count = 0_usize;
        let mut texture_warning = None;
        if !self.cdmw_texture_resources.is_empty() || !self.cdmw_material_presentations.is_empty() {
            renderer.reset_texture();
            for texture in &self.cdmw_texture_resources {
                match renderer.add_dds_texture(
                    &texture.bytes,
                    texture.role,
                    &texture.material_indices_by_lod,
                ) {
                    Ok(()) => texture_upload_count = texture_upload_count.saturating_add(1),
                    Err(error) => {
                        texture_warning.get_or_insert_with(|| error.to_string());
                    }
                }
            }
            if let Err(error) = add_cdmw_material_presentations(
                &mut renderer,
                &self.cdmw_material_presentations,
                self.document
                    .as_ref()
                    .map_or(0, |document| document.lods.len()),
            ) {
                texture_warning.get_or_insert_with(|| error.to_string());
            }
            match renderer.set_material_lod(self.active_lod_index) {
                Ok(count) => bound_material_count = count,
                Err(error) => {
                    texture_warning.get_or_insert_with(|| error.to_string());
                }
            }
        }
        if self.cdmw_mode() {
            self.record_cdmw_texture_uploads(
                self.cdmw_texture_resources.len(),
                texture_upload_count,
                bound_material_count,
                texture_warning.as_deref(),
            );
        }
        if let Some(mesh) = &self.mesh {
            let visible_submeshes = self.cdmw_visible_submeshes();
            let snapshot = visible_submeshes.as_ref().map_or_else(
                || mesh.draw_snapshot(),
                |visible| mesh.draw_snapshot_for_submeshes(visible),
            );
            let deformation_reference = deformation_reference_for_snapshot(
                self.deformation_heatmap_enabled,
                self.deformation_reference.as_mut(),
                visible_submeshes.as_ref(),
                &snapshot,
            );
            if let Err(error) =
                renderer.set_snapshot_with_deformation(&snapshot, deformation_reference)
            {
                self.status = format!("CDMW mesh upload failed: {error}");
            }
        }
        if let Err(error) = renderer.set_skeleton_lines(&self.skeleton_overlay_lines) {
            self.show_bones = false;
            self.status = format!("Skeleton overlay upload failed: {error}");
        }
        let egui_state = egui_winit::State::new(
            self.egui_context.clone(),
            egui::ViewportId::ROOT,
            window.as_ref(),
            Some(window.scale_factor() as f32),
            window.theme(),
            None,
        );
        window.request_redraw();
        let child_hwnd = cdmw_win32_embed::window_hwnd(window.as_ref()).unwrap_or(0);
        self.renderer = Some(renderer);
        self.egui_state = Some(egui_state);
        self.window = Some(window);
        if let Some(bridge) = &self.cdmw_bridge {
            if let Err(error) =
                bridge.announce_ready(child_hwnd, self.embedded_parent_hwnd.unwrap_or(0))
            {
                self.status = format!("CDMW handshake failed: {error}");
                self.cdmw_exit_requested = true;
            } else {
                self.status = format!(
                    "D3D12 adapter: {} ({}) · {}x AA · {}x texture filtering · waiting for CDMW · {texture_upload_count} texture(s) ready{}",
                    adapter.name,
                    adapter.driver_info,
                    quality.sample_count,
                    quality.anisotropy_clamp,
                    texture_warning
                        .as_ref()
                        .map_or_else(String::new, |warning| format!(
                            " · texture warning: {warning}"
                        ))
                );
            }
        }
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
            WindowEvent::CloseRequested => {
                if let Some(bridge) = &mut self.cdmw_bridge
                    && !self.cdmw_finish_accepted
                {
                    let _ = bridge.cancel("Mesh Editor window closed");
                }
                event_loop.exit();
            }
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

    fn about_to_wait(&mut self, event_loop: &ActiveEventLoop) {
        let changed = self.poll_loader() | self.poll_cdmw();
        if changed && let Some(window) = &self.window {
            window.request_redraw();
        }
        if self.cdmw_exit_requested {
            event_loop.exit();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn z_elongated_document() -> MeshDocument {
        let positions = vec![[-0.20, -0.04, -1.0], [0.20, -0.04, 1.0], [0.0, 0.04, 1.0]];
        MeshDocument {
            format: cdmw_formats::MeshFormat::Pac,
            source_sha256: String::new(),
            parser: "integrated-camera-test".to_owned(),
            lod_count_reported: 1,
            lods: vec![cdmw_formats::MeshLod {
                level: 0,
                submeshes: vec![cdmw_formats::Submesh {
                    name: "sword".to_owned(),
                    material: "sword".to_owned(),
                    normals: vec![[0.0, 0.0, 1.0]; positions.len()],
                    uvs: vec![[0.0, 0.0]; positions.len()],
                    source_vertex_indices: vec![0, 1, 2],
                    positions,
                    indices: vec![0, 1, 2],
                    source_range: cdmw_formats::SourceRange {
                        offset: 0,
                        length: 0,
                    },
                    vertex_stride: 0,
                    layout: "integrated-camera-test".to_owned(),
                }],
            }],
            warnings: Vec::new(),
            structural_fingerprint: String::new(),
        }
    }

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

    #[test]
    fn embedded_parent_hwnd_requires_and_accepts_cdmw_session_mode() {
        let options = parse_startup_options_from(
            [
                "--cdmw-session",
                "session.json",
                "--embedded-parent-hwnd",
                "4242",
            ]
            .into_iter()
            .map(str::to_owned),
        )
        .unwrap_or_else(|error| panic!("embedded options failed: {error}"));
        assert_eq!(options.cdmw_session, Some(PathBuf::from("session.json")));
        assert_eq!(options.embedded_parent_hwnd, Some(4242));

        let standalone = parse_startup_options_from(
            ["--embedded-parent-hwnd", "4242"]
                .into_iter()
                .map(str::to_owned),
        );
        assert!(standalone.is_err());
    }

    #[test]
    fn preview_capture_cli_is_exclusive_and_requires_an_output() {
        let options = parse_startup_options_from(
            [
                "--capture-cdmw-preview-session",
                "manifest.json",
                "--capture-output",
                "preview.bmp",
                "--capture-report-json",
                "preview.json",
                "--capture-yaw-degrees",
                "-35",
                "--capture-pitch-degrees",
                "20",
                "--capture-material-index",
                "7",
            ]
            .into_iter()
            .map(str::to_owned),
        )
        .unwrap_or_else(|error| panic!("preview capture options failed: {error}"));
        assert_eq!(
            options.capture_cdmw_preview_session,
            Some(PathBuf::from("manifest.json"))
        );
        assert_eq!(options.capture_output, Some(PathBuf::from("preview.bmp")));
        assert_eq!(
            options.capture_camera(),
            Some(HeadlessMaterialCaptureCamera {
                yaw_degrees: -35.0,
                pitch_degrees: 20.0,
            })
        );
        assert_eq!(options.capture_material_index, Some(7));

        let missing_output = parse_startup_options_from(
            ["--capture-cdmw-preview-session", "manifest.json"]
                .into_iter()
                .map(str::to_owned),
        );
        assert!(missing_output.is_err());

        let conflicting = parse_startup_options_from(
            [
                "--capture-cdmw-session",
                "editor.json",
                "--capture-cdmw-preview-session",
                "preview.json",
                "--capture-output",
                "capture.bmp",
            ]
            .into_iter()
            .map(str::to_owned),
        );
        assert!(conflicting.is_err());

        let incomplete_camera = parse_startup_options_from(
            [
                "--capture-cdmw-preview-session",
                "manifest.json",
                "--capture-output",
                "preview.bmp",
                "--capture-yaw-degrees",
                "0",
            ]
            .into_iter()
            .map(str::to_owned),
        );
        assert!(incomplete_camera.is_err());

        let audit = parse_startup_options_from(
            [
                "--capture-cdmw-preview-session",
                "manifest.json",
                "--capture-audit-output",
                "audit-evidence",
                "--capture-audit-full-model-only",
                "--capture-audit-repetitions",
                "20",
            ]
            .into_iter()
            .map(str::to_owned),
        )
        .unwrap_or_else(|error| panic!("audit capture options failed: {error}"));
        assert_eq!(
            audit.capture_audit_output,
            Some(PathBuf::from("audit-evidence"))
        );
        assert!(audit.capture_audit_full_model_only);
        assert_eq!(audit.capture_audit_repetitions, Some(20));

        let orphaned_full_model_only = parse_startup_options_from(
            ["--capture-audit-full-model-only"]
                .into_iter()
                .map(str::to_owned),
        );
        assert!(orphaned_full_model_only.is_err());

        let orphaned_repetitions = parse_startup_options_from(
            ["--capture-audit-repetitions", "20"]
                .into_iter()
                .map(str::to_owned),
        );
        assert!(orphaned_repetitions.is_err());

        let repetitions_with_regions = parse_startup_options_from(
            [
                "--capture-cdmw-preview-session",
                "manifest.json",
                "--capture-audit-output",
                "audit-evidence",
                "--capture-audit-repetitions",
                "20",
            ]
            .into_iter()
            .map(str::to_owned),
        );
        assert!(repetitions_with_regions.is_err());

        let zero_repetitions = parse_startup_options_from(
            [
                "--capture-cdmw-preview-session",
                "manifest.json",
                "--capture-audit-output",
                "audit-evidence",
                "--capture-audit-full-model-only",
                "--capture-audit-repetitions",
                "0",
            ]
            .into_iter()
            .map(str::to_owned),
        );
        assert!(zero_repetitions.is_err());

        let conflicting_outputs = parse_startup_options_from(
            [
                "--capture-cdmw-preview-session",
                "manifest.json",
                "--capture-output",
                "preview.bmp",
                "--capture-audit-output",
                "audit-evidence",
            ]
            .into_iter()
            .map(str::to_owned),
        );
        assert!(conflicting_outputs.is_err());
    }

    #[test]
    fn integrated_session_applies_the_startup_broadside_camera() {
        let root = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir failed: {error}"));
        let bridge = CdmwBridge::for_test(root.path().to_path_buf(), "camera-session", 1, 0);

        let mut application = LabApplication::new_cdmw(bridge, z_elongated_document(), None)
            .unwrap_or_else(|error| panic!("integrated application failed: {error}"));

        assert!(application.cdmw_mode());
        assert!(application.camera.forward().x.abs() > 0.75);
        assert!(application.camera.forward().y.abs() > 0.40);
        assert!(application.camera.forward().z.abs() < 1.0e-5);
        let viewport = egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(1_600.0, 600.0));
        application.update_viewport_rect(viewport);
        let projected = application
            .mesh
            .as_ref()
            .unwrap_or_else(|| panic!("integrated mesh missing"))
            .vertices()
            .map(|(_, vertex)| {
                application
                    .camera
                    .project(Vec3::from_array(vertex.position), viewport)
                    .unwrap_or_else(|| panic!("integrated weapon point did not project"))
            })
            .collect::<Vec<_>>();
        assert!(projected.iter().all(|point| point.inside_view));
        let minimum_x = projected
            .iter()
            .map(|point| point.screen.x)
            .fold(f32::INFINITY, f32::min);
        let maximum_x = projected
            .iter()
            .map(|point| point.screen.x)
            .fold(f32::NEG_INFINITY, f32::max);
        assert!(maximum_x - minimum_x > viewport.width() * 0.75);
    }

    #[test]
    fn material_audit_angles_are_relative_to_the_integrated_broadside_camera() {
        let snapshot = WorkingMesh::from_document_lod(&z_elongated_document(), 0)
            .expect("elongated audit mesh")
            .draw_snapshot();
        let base = material_audit_base_camera(&snapshot);
        let front = material_audit_paths(
            Path::new("audit"),
            "full_model",
            "front",
            base,
            0.0,
            0.0,
            None,
            0,
        );
        assert!((front.camera.yaw_degrees - 90.0).abs() < 1.0e-4);
        assert!((front.camera.pitch_degrees + 35.0).abs() < 1.0e-4);
        let oblique = material_audit_paths(
            Path::new("audit"),
            "material_region",
            "oblique",
            base,
            -35.0,
            20.0,
            Some(2),
            0,
        );
        assert!((oblique.camera.yaw_degrees - 55.0).abs() < 1.0e-4);
        assert!((oblique.camera.pitch_degrees + 15.0).abs() < 1.0e-4);
        assert_eq!(oblique.material_index, Some(2));
    }

    #[test]
    fn material_audit_reports_source_reuse_and_rejects_duplicate_runtime_upload_keys() {
        let source = material_audit_source_dds_metrics(
            Some(&PreviewCoreMaterialGraph {
                schema_version: 1,
                graph_version: 4,
                semantics_version: 10,
                quality: "full".to_owned(),
                resources_included: true,
                source_edge_count: 9,
                unique_resource_count: 3,
                copied_resource_count: 3,
                unique_resource_bytes: 512,
                materials: Vec::new(),
            }),
            &crate::preview_core_material::PreviewCoreMaterialCompositionMetrics {
                source_reference_count: 9,
                unique_source_dds_count: 3,
                source_dds_decode_count: 3,
                decoded_source_bytes: 512,
                decoded_rgba8_bytes: 768,
                decoded_source_sha256: vec!["a".repeat(64), "b".repeat(64), "c".repeat(64)],
            },
        );
        assert_eq!(source["reused_logical_reference_count"], 6);
        assert_eq!(source["each_source_binary_decoded_at_most_once"], true);
        assert_eq!(source["full_source_decode_complete"], true);
        assert_eq!(source["observed_source_dds_decode_count"], 3);

        let bytes = cdmw_texture::synthetic::rgba8_checker_dds();
        let resource = |role| CdmwTextureResource {
            label: format!("{role:?}"),
            metadata: cdmw_texture::inspect_dds(&bytes, role).expect("DDS metadata"),
            bytes: bytes.clone(),
            role,
            material_indices_by_lod: vec![vec![0]],
        };
        let distinct_interpretations = [
            resource(cdmw_texture::TextureRole::BaseColor),
            resource(cdmw_texture::TextureRole::LayerMask),
        ];
        let metrics = material_audit_runtime_dds_metrics(&distinct_interpretations)
            .expect("distinct role interpretations");
        assert_eq!(metrics["logical_resource_count"], 2);
        assert_eq!(metrics["resource_count"], 1);
        assert_eq!(metrics["unique_upload_key_count"], 1);
        assert_eq!(metrics["unique_binary_count"], 1);
        assert_eq!(metrics["reused_logical_resource_count"], 1);
        assert_eq!(metrics["upload_key"], "dds_sha256");
        assert_eq!(metrics["no_duplicate_upload_keys"], true);

        let duplicate = [
            resource(cdmw_texture::TextureRole::BaseColor),
            resource(cdmw_texture::TextureRole::BaseColor),
        ];
        let duplicate_metrics =
            material_audit_runtime_dds_metrics(&duplicate).expect("shared physical upload");
        assert_eq!(duplicate_metrics["resource_count"], 1);
        assert_eq!(duplicate_metrics["logical_duplicate_binding_count"], 1);
    }
}
