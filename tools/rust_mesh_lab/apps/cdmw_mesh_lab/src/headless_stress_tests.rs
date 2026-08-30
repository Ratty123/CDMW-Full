use super::headless_tests::{TestResult, projected_domain_point, triangle_application, viewport};
use super::*;
use cdmw_interaction::OperatorState;
use std::time::Instant;

const GESTURES_PER_CASE: usize = 100;
const STRESS_HISTORY_BUDGET_BYTES: usize = 4 * 1024;
const HIGH_RATE_POINTER_SAMPLES: usize = 5_000;

#[derive(Debug, Clone, Copy)]
enum LassoVariant {
    Clockwise,
    CounterClockwise,
    SelfIntersecting,
    RepeatedPoints,
    Tiny,
    Large,
    LeavesViewport,
}

fn all_domain_selection(mesh: &WorkingMesh, domain: SelectionDomain) -> Selection {
    let mut selection = Selection::default();
    match domain {
        SelectionDomain::Vertex => selection
            .vertices
            .extend(mesh.vertices().map(|(handle, _)| handle)),
        SelectionDomain::Edge => selection
            .edges
            .extend(mesh.edges().map(|(handle, _)| handle)),
        SelectionDomain::Face => selection
            .faces
            .extend(mesh.faces().map(|(handle, _)| handle)),
    }
    selection
}

fn seed_selection(
    application: &mut LabApplication,
    domain: SelectionDomain,
    operation: SelectionOperation,
) -> TestResult {
    let selection = if operation == SelectionOperation::Subtract {
        all_domain_selection(application.mesh.as_ref().ok_or("missing mesh")?, domain)
    } else {
        Selection::default()
    };
    application
        .mesh
        .as_mut()
        .ok_or("missing mesh")?
        .set_selection(selection)?;
    application.projection = None;
    Ok(())
}

fn lasso_points(center: Vec2, variant: LassoVariant) -> Vec<Vec2> {
    let offset = |x: f32, y: f32| center + Vec2::new(x, y);
    match variant {
        LassoVariant::Clockwise => vec![
            offset(-16.0, -16.0),
            offset(-16.0, 16.0),
            offset(16.0, 16.0),
            offset(16.0, -16.0),
        ],
        LassoVariant::CounterClockwise => vec![
            offset(-16.0, -16.0),
            offset(16.0, -16.0),
            offset(16.0, 16.0),
            offset(-16.0, 16.0),
        ],
        LassoVariant::SelfIntersecting => vec![
            offset(-20.0, -20.0),
            offset(20.0, 20.0),
            offset(-20.0, 20.0),
            offset(20.0, -20.0),
        ],
        LassoVariant::RepeatedPoints => vec![
            offset(-16.0, -16.0),
            offset(16.0, -16.0),
            offset(16.0, -16.0),
            offset(16.0, 16.0),
            offset(-16.0, 16.0),
            offset(-16.0, -16.0),
        ],
        LassoVariant::Tiny => vec![
            offset(-1.0, -1.0),
            offset(1.0, -1.0),
            offset(1.0, 1.0),
            offset(-1.0, 1.0),
        ],
        LassoVariant::Large => vec![
            offset(-300.0, -300.0),
            offset(300.0, -300.0),
            offset(300.0, 300.0),
            offset(-300.0, 300.0),
        ],
        LassoVariant::LeavesViewport => vec![
            offset(-1_000.0, -1_000.0),
            offset(1_000.0, -1_000.0),
            offset(1_000.0, 1_000.0),
            offset(-1_000.0, 1_000.0),
        ],
    }
}

fn run_lasso_once(
    application: &mut LabApplication,
    domain: SelectionDomain,
    visible_only: bool,
    operation: SelectionOperation,
    variant: LassoVariant,
) -> TestResult {
    seed_selection(application, domain, operation)?;
    application.viewport_tool = ViewportTool::Select;
    application.selection_tool = SelectionTool::Lasso;
    application.selection_domain = domain;
    application.selection_visible_only = visible_only;
    application.selection_operation = operation;
    let center = projected_domain_point(application, domain)?;
    let points = lasso_points(center, variant);
    let before_selection = application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .selection
        .clone();
    let before_history = application.history.undo_len();
    application.begin_primary_gesture(viewport(), points[0]);
    if application.selection_gesture.is_none() {
        return Err(
            format!("{domain:?}/{visible_only}/{operation:?}/{variant:?} did not start").into(),
        );
    }
    for (index, point) in points.iter().copied().enumerate().skip(1) {
        application.update_primary_gesture(viewport(), point, index + 1 == points.len());
    }
    application.finish_primary_gesture();
    assert!(application.selection_gesture.is_none());
    let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
    let changed = mesh.selection != before_selection;
    assert_eq!(
        application.history.undo_len(),
        before_history + usize::from(changed),
        "{domain:?}/{visible_only}/{operation:?}/{variant:?} history mismatch"
    );
    assert!(application.history.retained_bytes() <= application.history.budget_bytes());
    assert!(application.selection_latency_ms.len() <= LATENCY_SAMPLE_WINDOW);
    assert_eq!(application.operator.state(), OperatorState::Idle);
    mesh.validate()?;
    Ok(())
}

#[test]
#[ignore = "explicit long-running no-window interaction stress gate"]
fn lasso_stress_covers_every_domain_depth_operation_and_shape() -> TestResult {
    let started = Instant::now();
    let domains = [
        SelectionDomain::Vertex,
        SelectionDomain::Edge,
        SelectionDomain::Face,
    ];
    let operations = [
        SelectionOperation::Replace,
        SelectionOperation::Add,
        SelectionOperation::Subtract,
        SelectionOperation::Toggle,
    ];
    let variants = [
        LassoVariant::Clockwise,
        LassoVariant::CounterClockwise,
        LassoVariant::SelfIntersecting,
        LassoVariant::RepeatedPoints,
        LassoVariant::Tiny,
        LassoVariant::Large,
        LassoVariant::LeavesViewport,
    ];
    let mut total = 0_usize;
    for domain in domains {
        let mut application = triangle_application()?;
        for visible_only in [true, false] {
            for operation in operations {
                for variant in variants {
                    application.history = History::new(4 * 1024 * 1024);
                    for _ in 0..GESTURES_PER_CASE {
                        run_lasso_once(&mut application, domain, visible_only, operation, variant)?;
                        total += 1;
                    }
                }
            }
        }
    }
    assert_eq!(total, 16_800);
    eprintln!(
        "headless lasso stress: {total} gestures in {:.2} ms",
        started.elapsed().as_secs_f64() * 1_000.0
    );
    Ok(())
}

fn sculpt_stroke(
    application: &mut LabApplication,
    tool: ViewportTool,
    samples: usize,
    commit: bool,
    direction: f32,
) -> TestResult {
    application.viewport_tool = tool;
    application.brush_radius = 2_000.0;
    application.brush_strength = 0.05;
    let start = projected_domain_point(application, SelectionDomain::Vertex)?;
    let before_fingerprint = application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .structural_fingerprint();
    let before_selection = application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .selection
        .clone();
    let before_history = application.history.undo_len();
    let before_retained = application.history.retained_bytes();
    application.begin_primary_gesture(viewport(), start);
    if application.edit_gesture.is_none() {
        return Err(format!("{tool:?} did not start: {}", application.status).into());
    }
    for sample in 1..=samples.max(1) {
        let progress = sample as f32 / samples.max(1) as f32;
        application.update_primary_gesture(
            viewport(),
            start + Vec2::new(progress * 20.0 * direction, progress * -8.0 * direction),
            sample == samples,
        );
    }
    if commit {
        application.finish_primary_gesture();
        assert!(application.status.contains("committed"));
        assert_ne!(
            application
                .mesh
                .as_ref()
                .ok_or("missing mesh")?
                .structural_fingerprint(),
            before_fingerprint,
            "{tool:?} committed a no-op stroke"
        );
    } else {
        application.cancel_active_gesture("stress cancellation");
        let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
        assert_eq!(mesh.structural_fingerprint(), before_fingerprint);
        assert_eq!(mesh.selection, before_selection);
        assert_eq!(application.history.undo_len(), before_history);
        assert_eq!(application.history.retained_bytes(), before_retained);
    }
    assert!(application.edit_gesture.is_none());
    assert_eq!(application.operator.state(), OperatorState::Idle);
    assert!(application.history.retained_bytes() <= application.history.budget_bytes());
    assert!(application.edit_latency_ms.len() <= LATENCY_SAMPLE_WINDOW);
    application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .validate()?;
    Ok(())
}

fn run_high_rate_pointer_stroke(tool: ViewportTool) -> TestResult {
    let mut application = triangle_application()?;
    application.history = History::new(STRESS_HISTORY_BUDGET_BYTES);
    application.viewport_tool = tool;
    application.brush_radius = 2_000.0;
    application.brush_strength = 0.05;
    let start = projected_domain_point(&mut application, SelectionDomain::Vertex)?;
    application
        .pointer_events
        .push(ViewportPointerEvent::PrimaryPressed(start));
    for sample in 1..=HIGH_RATE_POINTER_SAMPLES {
        let progress = sample as f32 / HIGH_RATE_POINTER_SAMPLES as f32;
        application
            .pointer_events
            .push(ViewportPointerEvent::PrimaryMoved(
                start + Vec2::new(progress * 40.0, progress * -12.0),
            ));
    }
    let release = start + Vec2::new(40.0, -12.0);
    application
        .pointer_events
        .push(ViewportPointerEvent::PrimaryReleased(release));
    let events = application.pointer_events.drain().collect::<Vec<_>>();
    assert!(events.len() <= 4_096);
    assert_eq!(
        events.first(),
        Some(&ViewportPointerEvent::PrimaryPressed(start))
    );
    assert_eq!(
        events.last(),
        Some(&ViewportPointerEvent::PrimaryReleased(release))
    );
    for event in events {
        match event {
            ViewportPointerEvent::PrimaryPressed(point) => {
                application.begin_primary_gesture(viewport(), point)
            }
            ViewportPointerEvent::PrimaryMoved(point) => {
                application.update_primary_gesture(viewport(), point, false)
            }
            ViewportPointerEvent::PrimaryReleased(point) => {
                application.update_primary_gesture(viewport(), point, true);
                application.finish_primary_gesture();
            }
            ViewportPointerEvent::Orbit(_) | ViewportPointerEvent::Pan(_) => {
                return Err("unexpected camera event in sculpt stroke".into());
            }
        }
    }
    assert_eq!(application.operator.state(), OperatorState::Idle);
    assert_eq!(application.history.undo_len(), 1);
    application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .validate()?;
    Ok(())
}

fn run_sculpt_interruptions(tool: ViewportTool, next_tool: ViewportTool) -> TestResult {
    let mut application = triangle_application()?;
    application.history = History::new(STRESS_HISTORY_BUDGET_BYTES);
    application.viewport_tool = tool;
    application.brush_radius = 2_000.0;
    application.brush_strength = 0.05;
    let start = projected_domain_point(&mut application, SelectionDomain::Vertex)?;
    application.begin_primary_gesture(viewport(), start);
    application.update_primary_gesture(viewport(), start + Vec2::new(4.0, -2.0), false);
    application.viewport_tool = next_tool;
    application.view_mode = ViewMode::XRay;
    application.update_primary_gesture(viewport(), start + Vec2::new(8.0, -4.0), true);
    application.finish_primary_gesture();
    assert_eq!(application.operator.state(), OperatorState::Idle);
    assert_eq!(application.viewport_tool, next_tool);
    assert_eq!(application.view_mode, ViewMode::XRay);

    application.viewport_tool = tool;
    let start = projected_domain_point(&mut application, SelectionDomain::Vertex)?;
    let before = application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .structural_fingerprint();
    application.begin_primary_gesture(viewport(), start);
    application.update_primary_gesture(viewport(), start + Vec2::new(6.0, 0.0), false);
    application.update_viewport_rect(egui::Rect::from_min_size(
        egui::Pos2::ZERO,
        egui::vec2(480.0, 900.0),
    ));
    assert_eq!(
        application
            .mesh
            .as_ref()
            .ok_or("missing mesh")?
            .structural_fingerprint(),
        before
    );
    assert_eq!(application.operator.state(), OperatorState::Idle);

    application.update_viewport_rect(viewport());
    let start = projected_domain_point(&mut application, SelectionDomain::Vertex)?;
    let before = application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .structural_fingerprint();
    application.begin_primary_gesture(viewport(), start);
    application.update_primary_gesture(viewport(), start + Vec2::new(6.0, 0.0), false);
    application.raw_primary_captured = true;
    application
        .pointer_events
        .push(ViewportPointerEvent::PrimaryMoved(start + Vec2::X));
    application.cancel_active_gesture("focus loss cancelled the active gesture");
    application.pointer_events.clear();
    application.raw_primary_captured = false;
    application.raw_orbit_captured = false;
    application.raw_pan_captured = false;
    assert_eq!(
        application
            .mesh
            .as_ref()
            .ok_or("missing mesh")?
            .structural_fingerprint(),
        before
    );
    assert_eq!(application.operator.state(), OperatorState::Idle);
    assert_eq!(application.pointer_events.drain().count(), 0);
    Ok(())
}

#[test]
#[ignore = "explicit long-running no-window interaction stress gate"]
fn sculpt_stress_covers_commit_cancel_rate_and_interruptions() -> TestResult {
    let started = Instant::now();
    let tools = [
        ViewportTool::Grab,
        ViewportTool::Smooth,
        ViewportTool::Inflate,
        ViewportTool::Pinch,
    ];
    for (index, tool) in tools.iter().copied().enumerate() {
        let mut committed = triangle_application()?;
        committed.history = History::new(STRESS_HISTORY_BUDGET_BYTES);
        for iteration in 0..GESTURES_PER_CASE {
            let direction = if iteration % 2 == 0 { 1.0 } else { -1.0 };
            sculpt_stroke(&mut committed, tool, 2, true, direction)?;
        }
        assert!(committed.history.undo_len() < GESTURES_PER_CASE);

        let mut cancelled = triangle_application()?;
        cancelled.history = History::new(STRESS_HISTORY_BUDGET_BYTES);
        for iteration in 0..GESTURES_PER_CASE {
            let direction = if iteration % 2 == 0 { 1.0 } else { -1.0 };
            sculpt_stroke(&mut cancelled, tool, 2, false, direction)?;
        }
        assert_eq!(cancelled.history.undo_len(), 0);

        let mut long_stroke = triangle_application()?;
        long_stroke.history = History::new(STRESS_HISTORY_BUDGET_BYTES);
        sculpt_stroke(&mut long_stroke, tool, 2_048, true, 1.0)?;
        run_high_rate_pointer_stroke(tool)?;
        run_sculpt_interruptions(tool, tools[(index + 1) % tools.len()])?;
    }
    eprintln!(
        "headless sculpt stress: {} committed, {} cancelled, four long/high-rate/interruption groups in {:.2} ms",
        tools.len() * GESTURES_PER_CASE,
        tools.len() * GESTURES_PER_CASE,
        started.elapsed().as_secs_f64() * 1_000.0
    );
    Ok(())
}

fn run_mixed_session() -> Result<(String, usize, usize), Box<dyn std::error::Error>> {
    let mut application = triangle_application()?;
    application.history = History::new(STRESS_HISTORY_BUDGET_BYTES);
    for index in 0..1_000 {
        match index % 14 {
            0 => run_lasso_once(
                &mut application,
                SelectionDomain::Vertex,
                index % 24 == 0,
                SelectionOperation::Toggle,
                LassoVariant::Clockwise,
            )?,
            1 => {
                application.viewport_tool = ViewportTool::Select;
                application.selection_domain = SelectionDomain::Edge;
                application.selection_tool = SelectionTool::Brush;
                application.selection_operation = SelectionOperation::Replace;
                application.selection_visible_only = false;
                application.brush_radius = 24.0;
                let point = projected_domain_point(&mut application, SelectionDomain::Edge)?;
                application.begin_primary_gesture(viewport(), point);
                application.update_primary_gesture(viewport(), point + Vec2::X, true);
                application.finish_primary_gesture();
            }
            2 => {
                application.viewport_tool = ViewportTool::Select;
                application.selection_domain = SelectionDomain::Face;
                application.selection_tool = SelectionTool::Rectangle;
                application.selection_operation = SelectionOperation::Toggle;
                application.selection_visible_only = true;
                let point = projected_domain_point(&mut application, SelectionDomain::Face)?;
                application.begin_primary_gesture(viewport(), point - Vec2::splat(12.0));
                application.update_primary_gesture(viewport(), point + Vec2::splat(12.0), true);
                application.finish_primary_gesture();
            }
            3 => sculpt_stroke(
                &mut application,
                ViewportTool::Grab,
                2,
                true,
                if index % 24 < 12 { 1.0 } else { -1.0 },
            )?,
            4 => sculpt_stroke(&mut application, ViewportTool::Smooth, 2, false, 1.0)?,
            5 => sculpt_stroke(&mut application, ViewportTool::Inflate, 2, true, 1.0)?,
            6 => sculpt_stroke(&mut application, ViewportTool::Pinch, 2, false, 1.0)?,
            7..=9 => {
                application.select_all_faces();
                let action = match index % 14 {
                    7 => UiAction::DuplicateFaces,
                    8 => UiAction::SubdivideFaces,
                    _ => UiAction::DeleteFaces,
                };
                let before = application
                    .mesh
                    .as_ref()
                    .ok_or("missing mesh")?
                    .structural_fingerprint();
                application.handle_actions(vec![action]);
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
                application.handle_actions(vec![UiAction::Undo]);
            }
            10 => {
                application.select_all_faces();
                let before = application
                    .mesh
                    .as_ref()
                    .ok_or("missing mesh")?
                    .structural_fingerprint();
                application.handle_actions(vec![UiAction::DuplicateFacesToNewSubmesh]);
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
                application.handle_actions(vec![UiAction::Undo]);
            }
            11 => {
                application.handle_actions(vec![UiAction::SelectAllEdges]);
                let before = application
                    .mesh
                    .as_ref()
                    .ok_or("missing mesh")?
                    .structural_fingerprint();
                application.handle_actions(vec![UiAction::SubdivideEdges]);
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
                application.handle_actions(vec![UiAction::Undo]);
            }
            12 => {
                application.viewport_tool = ViewportTool::Grab;
                application.brush_radius = 2_000.0;
                let point = projected_domain_point(&mut application, SelectionDomain::Vertex)?;
                let before = application
                    .mesh
                    .as_ref()
                    .ok_or("missing mesh")?
                    .structural_fingerprint();
                application.begin_primary_gesture(viewport(), point);
                application.update_primary_gesture(viewport(), point + Vec2::X * 4.0, false);
                application.cancel_active_gesture("camera orbit took pointer ownership");
                application.camera.orbit(Vec2::new(0.25, -0.125));
                application.projection = None;
                assert_eq!(
                    application
                        .mesh
                        .as_ref()
                        .ok_or("missing mesh")?
                        .structural_fingerprint(),
                    before
                );
            }
            _ => {
                application.handle_actions(vec![UiAction::FrameAll]);
                application
                    .camera
                    .zoom(if index % 24 == 11 { 1.0 } else { -1.0 });
                application.projection = None;
            }
        }
        assert!(application.selection_gesture.is_none());
        assert!(application.edit_gesture.is_none());
        assert_eq!(application.operator.state(), OperatorState::Idle);
        assert!(application.history.retained_bytes() <= application.history.budget_bytes());
        assert!(application.selection_latency_ms.len() <= LATENCY_SAMPLE_WINDOW);
        assert!(application.edit_latency_ms.len() <= LATENCY_SAMPLE_WINDOW);
        application
            .mesh
            .as_ref()
            .ok_or("missing mesh")?
            .validate()?;
    }
    let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
    Ok((
        mesh.structural_fingerprint(),
        application.history.undo_len(),
        application.history.retained_bytes(),
    ))
}

#[test]
#[ignore = "explicit long-running no-window interaction stress gate"]
fn one_thousand_mixed_app_gestures_are_deterministic_and_bounded() -> TestResult {
    let started = Instant::now();
    let first = run_mixed_session()?;
    let second = run_mixed_session()?;
    assert_eq!(first, second);
    eprintln!(
        "headless mixed stress: two deterministic 1,000-gesture sessions in {:.2} ms",
        started.elapsed().as_secs_f64() * 1_000.0
    );
    Ok(())
}
