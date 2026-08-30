use super::*;
use cdmw_formats::{MeshFormat, decode_mesh};
use cdmw_interaction::{OperatorState, ProjectedHandle};

pub(super) type TestResult = Result<(), Box<dyn std::error::Error>>;

pub(super) fn viewport() -> egui::Rect {
    egui::Rect::from_min_size(egui::pos2(0.0, 0.0), egui::vec2(800.0, 600.0))
}

pub(super) fn triangle_application() -> Result<LabApplication, Box<dyn std::error::Error>> {
    let document = decode_mesh(
        &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
        MeshFormat::Pam,
    )?;
    let mesh = WorkingMesh::from_document(&document)?;
    let mut application = LabApplication::new(None, None);
    application.document = Some(document);
    application.mesh = Some(mesh);
    application.source_label = "headless synthetic triangle".to_owned();
    application.update_viewport_rect(viewport());
    application
        .camera
        .frame_all(application.mesh.as_ref().ok_or("missing working mesh")?);
    Ok(application)
}

pub(super) fn two_lod_application() -> Result<LabApplication, Box<dyn std::error::Error>> {
    let document = decode_mesh(&cdmw_formats::synthetic::two_lod_pac(), MeshFormat::Pac)?;
    let cancellation = cdmw_archive::CancellationToken::default();
    let mut meshes = crate::loader::build_lod_meshes(&document, &cancellation)?.into_iter();
    let mesh = meshes.next().ok_or("missing LOD0 working mesh")?;
    let mut application = LabApplication::new(None, None);
    application.install_loaded_mesh(LoadedMesh {
        path: PathBuf::from("headless-two-lod.pac"),
        document,
        mesh,
        other_lod_meshes: meshes.collect(),
        textures: Vec::new(),
        material_parameters: Vec::new(),
        material_factors: Vec::new(),
    });
    application.update_viewport_rect(viewport());
    Ok(application)
}

pub(super) fn projected_domain_point(
    application: &mut LabApplication,
    domain: SelectionDomain,
) -> Result<Vec2, Box<dyn std::error::Error>> {
    if !application.ensure_projection(viewport()) {
        return Err("projection was not built".into());
    }
    application
        .projection
        .as_ref()
        .ok_or("missing projection")?
        .interaction
        .elements
        .iter()
        .find_map(|element| {
            let matches = matches!(
                (domain, element.handle),
                (SelectionDomain::Vertex, ProjectedHandle::Vertex(_))
                    | (SelectionDomain::Edge, ProjectedHandle::Edge(_))
                    | (SelectionDomain::Face, ProjectedHandle::Face(_))
            );
            matches.then_some(element.position)
        })
        .ok_or_else(|| "missing projected element for selection domain".into())
}

fn run_selection_gesture(
    application: &mut LabApplication,
    domain: SelectionDomain,
    tool: SelectionTool,
) -> TestResult {
    application.viewport_tool = ViewportTool::Select;
    application.selection_domain = domain;
    application.selection_tool = tool;
    application.selection_operation = SelectionOperation::Replace;
    application.selection_visible_only = false;
    application.brush_radius = 24.0;
    let center = projected_domain_point(application, domain)?;
    let start = center + Vec2::new(-12.0, -12.0);
    match tool {
        SelectionTool::Click => application.begin_primary_gesture(viewport(), center),
        SelectionTool::Brush => {
            application.begin_primary_gesture(viewport(), center);
            application.update_primary_gesture(viewport(), center + Vec2::new(2.0, 0.0), true);
        }
        SelectionTool::Rectangle => {
            application.begin_primary_gesture(viewport(), start);
            application.update_primary_gesture(viewport(), center + Vec2::new(12.0, 12.0), true);
        }
        SelectionTool::Lasso => {
            application.begin_primary_gesture(viewport(), start);
            for point in [
                center + Vec2::new(12.0, -12.0),
                center + Vec2::new(12.0, 12.0),
                center + Vec2::new(-12.0, 12.0),
            ] {
                application.update_primary_gesture(viewport(), point, false);
            }
            application.update_primary_gesture(viewport(), start, true);
        }
    }
    if application.selection_gesture.is_none() {
        return Err(format!("{domain:?} {tool:?} did not start").into());
    }
    application.finish_primary_gesture();
    let selection = &application.mesh.as_ref().ok_or("missing mesh")?.selection;
    let selected = match domain {
        SelectionDomain::Vertex => selection.vertices.len(),
        SelectionDomain::Edge => selection.edges.len(),
        SelectionDomain::Face => selection.faces.len(),
    };
    if selected == 0 {
        return Err(format!("{domain:?} {tool:?} selected nothing").into());
    }
    if application.history.undo_len() != 1 {
        return Err(format!("{domain:?} {tool:?} did not create one history entry").into());
    }
    application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .validate()?;
    Ok(())
}

#[test]
fn headless_ui_frame_builds_the_complete_app_without_a_window() -> TestResult {
    let mut application = triangle_application()?;
    let context = application.egui_context.clone();
    let input = egui::RawInput {
        screen_rect: Some(egui::Rect::from_min_size(
            egui::Pos2::ZERO,
            egui::vec2(1_440.0, 900.0),
        )),
        ..Default::default()
    };
    let mut output = context.run_ui(input, |ui| {
        let actions = application.draw_ui(ui);
        application.handle_actions(actions);
    });
    assert!(!output.shapes.is_empty());
    assert!(application.viewport_rect.is_some());
    assert!(application.window.is_none());
    assert!(application.renderer.is_none());
    output.textures_delta.clear();
    Ok(())
}

#[test]
fn decoded_lods_switch_headlessly_and_preserve_independent_edit_history() -> TestResult {
    let mut application = two_lod_application()?;
    assert_eq!(application.active_lod_index, 0);
    assert_eq!(application.lod_sessions.len(), 2);
    assert_eq!(
        application
            .mesh
            .as_ref()
            .ok_or("missing active LOD0")?
            .vertices()
            .count(),
        3
    );
    let total_history_budget = application.history.budget_bytes()
        + application
            .lod_sessions
            .iter()
            .flatten()
            .map(|session| session.history.budget_bytes())
            .sum::<usize>();
    assert_eq!(total_history_budget, HISTORY_BUDGET_BYTES);

    application.handle_actions(vec![UiAction::SelectAllFaces, UiAction::DuplicateFaces]);
    let lod_zero_edited = application
        .mesh
        .as_ref()
        .ok_or("missing edited LOD0")?
        .structural_fingerprint();
    assert_eq!(application.history.undo_len(), 2);

    application.handle_actions(vec![UiAction::SwitchLod(1)]);
    assert_eq!(application.active_lod_index, 1);
    let lod_one = application.mesh.as_ref().ok_or("missing active LOD1")?;
    assert_eq!(lod_one.vertices().count(), 4);
    assert_eq!(lod_one.faces().count(), 2);
    assert_eq!(application.history.undo_len(), 0);
    application.handle_actions(vec![UiAction::SelectAllFaces, UiAction::DuplicateFaces]);
    let lod_one_edited = application
        .mesh
        .as_ref()
        .ok_or("missing edited LOD1")?
        .structural_fingerprint();
    assert_eq!(application.history.undo_len(), 2);

    application.handle_actions(vec![UiAction::SwitchLod(0)]);
    assert_eq!(
        application
            .mesh
            .as_ref()
            .ok_or("missing restored LOD0")?
            .structural_fingerprint(),
        lod_zero_edited
    );
    assert_eq!(application.history.undo_len(), 2);
    application.handle_actions(vec![UiAction::Undo]);
    assert_ne!(
        application
            .mesh
            .as_ref()
            .ok_or("missing undone LOD0")?
            .structural_fingerprint(),
        lod_zero_edited
    );
    application.handle_actions(vec![UiAction::Redo]);
    assert_eq!(
        application
            .mesh
            .as_ref()
            .ok_or("missing redone LOD0")?
            .structural_fingerprint(),
        lod_zero_edited
    );

    application.handle_actions(vec![UiAction::SwitchLod(1)]);
    assert_eq!(
        application
            .mesh
            .as_ref()
            .ok_or("missing restored LOD1")?
            .structural_fingerprint(),
        lod_one_edited
    );
    assert_eq!(application.history.undo_len(), 2);

    let context = application.egui_context.clone();
    let mut output = context.run_ui(
        egui::RawInput {
            screen_rect: Some(egui::Rect::from_min_size(
                egui::Pos2::ZERO,
                egui::vec2(1_440.0, 900.0),
            )),
            ..Default::default()
        },
        |ui| {
            let actions = application.draw_ui(ui);
            application.handle_actions(actions);
        },
    );
    assert!(!output.shapes.is_empty());
    assert!(application.window.is_none());
    assert!(application.renderer.is_none());
    output.textures_delta.clear();
    Ok(())
}

#[test]
fn lod_working_mesh_preparation_honors_cancellation() -> TestResult {
    let document = decode_mesh(&cdmw_formats::synthetic::two_lod_pac(), MeshFormat::Pac)?;
    let cancellation = cdmw_archive::CancellationToken::default();
    cancellation.cancel();
    assert!(crate::loader::build_lod_meshes(&document, &cancellation).is_err());
    Ok(())
}

#[test]
fn lod_switch_rolls_back_an_active_edit_before_parking_the_session() -> TestResult {
    let mut application = two_lod_application()?;
    application.select_all_vertices();
    application.viewport_tool = ViewportTool::Move;
    let mesh = application.mesh.as_ref().ok_or("missing LOD0")?;
    let before = mesh.structural_fingerprint();
    let selection_before = mesh.selection.clone();
    let pivot = OrbitCamera::selected_center(mesh).ok_or("missing selection pivot")?;
    let center = application
        .camera
        .project(pivot, viewport())
        .ok_or("missing projected pivot")?
        .screen;
    application.begin_primary_gesture(viewport(), center);
    application.update_primary_gesture(viewport(), center + Vec2::new(25.0, 0.0), false);
    assert_ne!(
        application
            .mesh
            .as_ref()
            .ok_or("missing edited LOD0")?
            .structural_fingerprint(),
        before
    );
    application.handle_actions(vec![UiAction::SwitchLod(1), UiAction::SwitchLod(0)]);
    let restored = application.mesh.as_ref().ok_or("missing restored LOD0")?;
    assert_eq!(restored.structural_fingerprint(), before);
    assert_eq!(restored.selection, selection_before);
    assert_eq!(application.history.undo_len(), 0);
    assert_eq!(application.operator.state(), OperatorState::Idle);
    assert!(application.edit_gesture.is_none());
    assert!(application.selection_gesture.is_none());
    assert!(!application.raw_primary_captured);
    Ok(())
}

#[test]
fn every_selection_domain_and_shape_runs_through_the_app_headlessly() -> TestResult {
    for domain in [
        SelectionDomain::Vertex,
        SelectionDomain::Edge,
        SelectionDomain::Face,
    ] {
        for tool in [
            SelectionTool::Click,
            SelectionTool::Brush,
            SelectionTool::Rectangle,
            SelectionTool::Lasso,
        ] {
            run_selection_gesture(&mut triangle_application()?, domain, tool)?;
        }
    }
    Ok(())
}

#[test]
fn visible_and_xray_selection_use_their_distinct_query_paths() -> TestResult {
    let mut visible = triangle_application()?;
    visible.selection_domain = SelectionDomain::Face;
    visible.selection_tool = SelectionTool::Click;
    visible.selection_visible_only = true;
    let point = projected_domain_point(&mut visible, SelectionDomain::Face)?;
    visible.begin_primary_gesture(viewport(), point);
    visible.finish_primary_gesture();
    let visible_stats = visible
        .last_selection_stats
        .ok_or("missing visible stats")?;
    assert!(visible_stats.depth_triangles_inspected > 0);

    let mut xray = triangle_application()?;
    xray.selection_domain = SelectionDomain::Face;
    xray.selection_tool = SelectionTool::Click;
    xray.selection_visible_only = false;
    let point = projected_domain_point(&mut xray, SelectionDomain::Face)?;
    xray.begin_primary_gesture(viewport(), point);
    xray.finish_primary_gesture();
    let xray_stats = xray.last_selection_stats.ok_or("missing X-Ray stats")?;
    assert_eq!(xray_stats.depth_triangles_inspected, 0);
    Ok(())
}

#[test]
fn camera_modes_and_resize_are_headless_and_aspect_safe() -> TestResult {
    let mut application = triangle_application()?;
    for view in [
        StandardView::Front,
        StandardView::Back,
        StandardView::Left,
        StandardView::Right,
        StandardView::Top,
        StandardView::Bottom,
    ] {
        let before = application.camera.revision();
        application.handle_actions(vec![UiAction::StandardView(view)]);
        assert!(application.camera.revision() > before);
    }
    let before = application.camera.revision();
    application.camera.orbit(Vec2::new(18.0, -9.0));
    application.camera.pan(Vec2::new(7.0, 5.0), viewport());
    application.camera.zoom(120.0);
    assert!(application.camera.revision() >= before + 3);

    application.handle_actions(vec![UiAction::FrameAll]);
    let camera = application.camera.clone();
    for rectangle in [
        egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(1_200.0, 400.0)),
        egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(400.0, 1_200.0)),
    ] {
        let target = camera.target();
        let origin = camera
            .project(target, rectangle)
            .ok_or("origin projection")?;
        let x = camera
            .project(target + camera.right() * 0.25, rectangle)
            .ok_or("X projection")?;
        let y = camera
            .project(target + camera.up() * 0.25, rectangle)
            .ok_or("Y projection")?;
        let x_pixels = x.screen.distance(origin.screen);
        let y_pixels = y.screen.distance(origin.screen);
        assert!((x_pixels - y_pixels).abs() <= x_pixels.max(y_pixels) * 0.001);
        application.update_viewport_rect(rectangle);
        assert!(application.ensure_projection(rectangle));
        assert_eq!(
            application
                .projection
                .as_ref()
                .ok_or("projection")?
                .rectangle,
            rectangle
        );
    }

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
        application.view_mode = mode;
        assert!(!application.view_mode.label().is_empty());
    }
    application.show_normals = true;
    application.show_bounds = true;
    assert!(application.show_normals && application.show_bounds);
    Ok(())
}

fn run_edit_tool(tool: ViewportTool) -> TestResult {
    let mut application = triangle_application()?;
    application.select_all_vertices();
    application.viewport_tool = tool;
    application.brush_radius = 2_000.0;
    let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
    let before = mesh.structural_fingerprint();
    let selection_before = mesh.selection.clone();
    let pivot = OrbitCamera::selected_center(mesh).ok_or("missing selection pivot")?;
    let center = application
        .camera
        .project(pivot, viewport())
        .ok_or("missing projected pivot")?
        .screen;
    let (start, end) = if tool == ViewportTool::Rotate {
        let ring = rotation_ring(&application.camera, pivot, GizmoAxis::Z, viewport());
        (
            *ring.first().ok_or("missing rotation ring")?,
            *ring.get(ring.len() / 4).ok_or("short rotation ring")?,
        )
    } else if tool.sculpt_tool().is_some() {
        let point = projected_domain_point(&mut application, SelectionDomain::Vertex)?;
        (point, point + Vec2::new(20.0, -8.0))
    } else {
        (center, center + Vec2::new(20.0, -8.0))
    };
    application.begin_primary_gesture(viewport(), start);
    if application.edit_gesture.is_none() {
        return Err(format!("{tool:?} did not start").into());
    }
    application.update_primary_gesture(viewport(), end, true);
    application.finish_primary_gesture();
    let changed = application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .structural_fingerprint();
    if changed == before {
        return Err(format!("{tool:?} did not change the mesh").into());
    }
    assert_eq!(application.history.undo_len(), 1);
    assert_eq!(
        application.mesh.as_ref().ok_or("missing mesh")?.selection,
        selection_before
    );
    application.handle_actions(vec![UiAction::Undo]);
    assert_eq!(
        application
            .mesh
            .as_ref()
            .ok_or("missing mesh")?
            .structural_fingerprint(),
        before
    );
    application.handle_actions(vec![UiAction::Redo]);
    assert_eq!(
        application
            .mesh
            .as_ref()
            .ok_or("missing mesh")?
            .structural_fingerprint(),
        changed
    );
    application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .validate()?;
    Ok(())
}

#[test]
fn every_transform_and_sculpt_tool_round_trips_headlessly() -> TestResult {
    for tool in [
        ViewportTool::Move,
        ViewportTool::Rotate,
        ViewportTool::Scale,
        ViewportTool::Grab,
        ViewportTool::Smooth,
        ViewportTool::Inflate,
        ViewportTool::Pinch,
    ] {
        run_edit_tool(tool)?;
    }
    Ok(())
}

#[test]
fn app_cancellation_restores_the_exact_working_state() -> TestResult {
    let mut application = triangle_application()?;
    application.select_all_vertices();
    application.viewport_tool = ViewportTool::Move;
    let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
    let before = mesh.structural_fingerprint();
    let selection_before = mesh.selection.clone();
    let pivot = OrbitCamera::selected_center(mesh).ok_or("missing selection pivot")?;
    let center = application
        .camera
        .project(pivot, viewport())
        .ok_or("missing projected pivot")?
        .screen;
    application.begin_primary_gesture(viewport(), center);
    application.update_primary_gesture(viewport(), center + Vec2::new(25.0, 0.0), false);
    assert_ne!(
        application
            .mesh
            .as_ref()
            .ok_or("missing mesh")?
            .structural_fingerprint(),
        before
    );
    application.cancel_active_gesture("headless cancellation");
    let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
    assert_eq!(mesh.structural_fingerprint(), before);
    assert_eq!(mesh.selection, selection_before);
    assert_eq!(application.history.undo_len(), 0);
    assert_eq!(application.operator.state(), OperatorState::Idle);
    Ok(())
}

#[test]
fn every_topology_action_round_trips_geometry_and_selection() -> TestResult {
    for action in [
        UiAction::DuplicateFaces,
        UiAction::SubdivideFaces,
        UiAction::DeleteFaces,
    ] {
        let mut application = triangle_application()?;
        application.select_all_faces();
        let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
        let before = mesh.structural_fingerprint();
        let selection_before = mesh.selection.clone();
        application.handle_actions(vec![action]);
        let changed = application
            .mesh
            .as_ref()
            .ok_or("missing mesh")?
            .structural_fingerprint();
        assert_ne!(changed, before);
        assert_eq!(application.history.undo_len(), 1);
        application.handle_actions(vec![UiAction::Undo]);
        let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
        assert_eq!(mesh.structural_fingerprint(), before);
        assert_eq!(mesh.selection, selection_before);
        application.handle_actions(vec![UiAction::Redo]);
        let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
        assert_eq!(mesh.structural_fingerprint(), changed);
        mesh.validate()?;
    }
    Ok(())
}

#[test]
#[ignore = "requires a local Direct3D 12 adapter"]
fn offscreen_d3d12_renders_every_mode_without_a_window() -> TestResult {
    let application = triangle_application()?;
    let snapshot = application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .draw_snapshot();
    let report = pollster::block_on(cdmw_render_wgpu::run_headless_render_smoke(&snapshot))?;
    assert_eq!(report.adapter.backend, "Dx12");
    assert_eq!(report.modes_rendered, 15);
    assert_eq!(report.viewport_sizes_rendered, 3);
    assert_eq!(report.frames_rendered, 73);
    assert_eq!(report.dds_textures_uploaded, 15);
    assert_eq!(report.sampled_material_roles, 13);
    assert_eq!(report.material_ranges_rendered, 2);
    assert!(report.composed_material_pixels_changed > 0);
    assert!(report.emissive_factor_pixels_changed > 0);
    assert!(report.roughness_factor_pixels_changed > 0);
    assert!(report.metalness_factor_pixels_changed > 0);
    assert!(report.specular_factor_pixels_changed > 0);
    assert!(report.specular_texture_pixels_changed > 0);
    assert_eq!(report.dielectric_specular_pixels_changed, 0);
    assert!(report.glossiness_texture_pixels_changed > 0);
    assert_eq!(report.dielectric_glossiness_pixels_changed, 0);
    assert!(report.height_texture_pixels_changed > 0);
    assert_eq!(report.disabled_height_pixels_changed, 0);
    assert!(report.hair_flow_pixels_changed > 0);
    assert_eq!(report.non_hair_flow_pixels_changed, 0);
    assert!(report.layer_mask_pixels_changed > 0);
    assert!(report.layer_mask_channel_pixels_changed > 0);
    assert_eq!(report.part_id_colors_rendered, 2);
    assert!(report.outdoor_lighting_pixels_changed > 0);
    assert!(report.opacity_cutout_pixels_removed > 0);
    assert_eq!(report.opaque_opacity_pixels_changed, 0);
    assert!(report.non_background_pixels > 0);
    Ok(())
}
