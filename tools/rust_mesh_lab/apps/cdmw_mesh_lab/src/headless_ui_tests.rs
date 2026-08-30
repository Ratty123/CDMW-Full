//! No-window tests of the painted controls and the live pointer-capture route.
//!
//! Widget coordinates come from egui's clipped text shapes, not a duplicate UI
//! layout. Actions are collected during the frame and applied afterwards, just
//! like `LabApplication::redraw`. This does not exercise the OS event loop or GPU.

use super::*;
use crate::headless_tests::{TestResult, triangle_application, two_lod_application};
use cdmw_interaction::ProjectedHandle;
use egui::{Event, FullOutput, PointerButton, Pos2, Rect};
use winit::event::DeviceId;

struct HeadlessUi {
    application: LabApplication,
    size: egui::Vec2,
    scale_factor: f64,
    output: FullOutput,
}

impl HeadlessUi {
    fn new(application: LabApplication, size: egui::Vec2) -> Self {
        let mut ui = Self {
            application,
            size,
            scale_factor: 1.0,
            output: FullOutput::default(),
        };
        // egui resolves panel widths and font layout on the first frames.
        ui.frame(Vec::new());
        ui.frame(Vec::new());
        ui
    }

    fn frame(&mut self, events: Vec<Event>) {
        for event in &events {
            let window_event = match event {
                Event::PointerMoved(position) => Some(WindowEvent::CursorMoved {
                    device_id: DeviceId::dummy(),
                    position: winit::dpi::PhysicalPosition::new(
                        f64::from(position.x) * self.scale_factor,
                        f64::from(position.y) * self.scale_factor,
                    ),
                }),
                Event::PointerButton {
                    button, pressed, ..
                } => Some(WindowEvent::MouseInput {
                    device_id: DeviceId::dummy(),
                    state: if *pressed {
                        ElementState::Pressed
                    } else {
                        ElementState::Released
                    },
                    button: match button {
                        PointerButton::Primary => MouseButton::Left,
                        PointerButton::Secondary => MouseButton::Right,
                        PointerButton::Middle => MouseButton::Middle,
                        _ => panic!("unsupported test pointer button"),
                    },
                }),
                _ => None,
            };
            if let Some(window_event) = window_event {
                self.application
                    .capture_viewport_pointer_event(&window_event, self.scale_factor);
            }
        }
        let context = self.application.egui_context.clone();
        let mut actions = Vec::new();
        self.output = context.run_ui(
            egui::RawInput {
                screen_rect: Some(Rect::from_min_size(Pos2::ZERO, self.size)),
                events,
                ..Default::default()
            },
            |ui| actions.extend(self.application.draw_ui(ui)),
        );
        self.application.handle_actions(actions);
        self.output.textures_delta.clear();
        assert!(self.application.window.is_none());
        assert!(self.application.renderer.is_none());
    }

    fn label_rect(&self, label: &str) -> Option<Rect> {
        self.label_rect_where(label, |_| true)
    }

    fn label_rect_where(&self, label: &str, accepts: impl Fn(Rect) -> bool) -> Option<Rect> {
        let screen = Rect::from_min_size(Pos2::ZERO, self.size);
        self.output.shapes.iter().rev().find_map(|clipped| {
            let egui::Shape::Text(text) = &clipped.shape else {
                return None;
            };
            let rectangle = text.visual_bounding_rect();
            (text.galley.job.text == label
                && clipped.clip_rect.contains_rect(rectangle)
                && screen.contains_rect(rectangle)
                && accepts(rectangle))
            .then_some(rectangle)
        })
    }

    fn scroll_inspector(&mut self, distance: f32) {
        let viewport = self.application.viewport_rect.expect("viewport");
        let position = egui::pos2((viewport.right() + self.size.x) * 0.5, self.size.y * 0.5);
        self.frame(vec![Event::PointerMoved(position), wheel_event(distance)]);
        for _ in 0..8 {
            self.frame(Vec::new());
        }
    }

    fn reveal(&mut self, label: &str) -> Result<Rect, Box<dyn std::error::Error>> {
        self.frame(Vec::new());
        if let Some(rectangle) = self.label_rect(label) {
            return Ok(rectangle);
        }
        self.scroll_inspector(2_000.0);
        for _ in 0..24 {
            if let Some(rectangle) = self.label_rect(label) {
                return Ok(rectangle);
            }
            self.scroll_inspector(-120.0);
        }
        Err(format!(
            "inspector control {label:?} is unreachable at {:?}",
            self.size
        )
        .into())
    }

    fn click_at(&mut self, position: Pos2) {
        self.frame(vec![Event::PointerMoved(position)]);
        self.frame(vec![pointer_button(position, PointerButton::Primary, true)]);
        self.frame(vec![pointer_button(
            position,
            PointerButton::Primary,
            false,
        )]);
        self.frame(Vec::new());
    }

    fn click(&mut self, label: &str) -> TestResult {
        let position = self.reveal(label)?.center();
        self.click_at(position);
        Ok(())
    }

    fn choose(&mut self, label: &str, current: &str, next: &str) -> TestResult {
        let row = self.reveal(label)?;
        let selected = self
            .label_rect_where(current, |rectangle| {
                (rectangle.center().y - row.center().y).abs() < row.height()
            })
            .ok_or_else(|| format!("missing current value {current:?} beside {label:?}"))?;
        self.click_at(selected.center());
        let option = self
            .label_rect(next)
            .ok_or_else(|| format!("missing open-menu option {next:?}"))?;
        self.click_at(option.center());
        Ok(())
    }

    fn projected_point(
        &mut self,
        domain: SelectionDomain,
    ) -> Result<Vec2, Box<dyn std::error::Error>> {
        self.frame(Vec::new());
        self.application
            .projection
            .as_ref()
            .ok_or("projection")?
            .interaction
            .elements
            .iter()
            .find_map(|element| {
                matches!(
                    (domain, element.handle),
                    (SelectionDomain::Vertex, ProjectedHandle::Vertex(_))
                        | (SelectionDomain::Edge, ProjectedHandle::Edge(_))
                        | (SelectionDomain::Face, ProjectedHandle::Face(_))
                )
                .then_some(element.position)
            })
            .ok_or_else(|| "missing projected selection candidate".into())
    }

    fn drag(&mut self, points: &[Vec2], button: PointerButton) {
        let start = egui::pos2(points[0].x, points[0].y);
        let end = points.last().expect("drag points");
        let mut events = vec![
            Event::PointerMoved(start),
            pointer_button(start, button, true),
        ];
        events.extend(
            points[1..]
                .iter()
                .map(|point| Event::PointerMoved(egui::pos2(point.x, point.y))),
        );
        events.push(pointer_button(egui::pos2(end.x, end.y), button, false));
        // A complete fast drag may arrive before one redraw. The live bounded
        // queue must retain both endpoints and all meaningful intermediate input.
        self.frame(events);
        self.frame(Vec::new());
    }
}

fn pointer_button(position: Pos2, button: PointerButton, pressed: bool) -> Event {
    Event::PointerButton {
        pos: position,
        button,
        pressed,
        modifiers: egui::Modifiers::NONE,
    }
}

#[test]
fn inspector_edit_controls_remain_reachable_in_short_windows() -> TestResult {
    for size in [egui::vec2(1_280.0, 720.0), egui::vec2(1_000.0, 600.0)] {
        let mut ui = HeadlessUi::new(two_lod_application()?, size);
        ui.click("All Faces")?;
        let baseline = ui
            .application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint();
        ui.click("Pinch")?;
        assert_eq!(ui.application.viewport_tool, ViewportTool::Pinch);
        ui.click("Duplicate")?;
        let edited = ui
            .application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint();
        assert_ne!(edited, baseline);
        ui.click("Undo")?;
        assert_eq!(
            ui.application
                .mesh
                .as_ref()
                .ok_or("mesh")?
                .structural_fingerprint(),
            baseline
        );
        ui.click("Redo")?;
        assert_eq!(
            ui.application
                .mesh
                .as_ref()
                .ok_or("mesh")?
                .structural_fingerprint(),
            edited
        );
        ui.reveal("Export Neutral OBJ…")?;
        assert_eq!(ui.application.history.undo_len(), 1);
        assert!(!ui.application.raw_primary_captured);
        assert!(ui.application.selection_gesture.is_none());
        assert!(ui.application.edit_gesture.is_none());
    }
    Ok(())
}

#[test]
fn painted_menus_route_preview_camera_selection_and_lod_controls() -> TestResult {
    let mut ui = HeadlessUi::new(two_lod_application()?, egui::vec2(1_440.0, 900.0));
    for mode in [
        ViewMode::Wireframe,
        ViewMode::Vertices,
        ViewMode::WireVertices,
        ViewMode::XRay,
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
    ] {
        let current = ui.application.view_mode.label();
        ui.choose("Preview mode", current, mode.label())?;
        assert_eq!(ui.application.view_mode, mode);
    }
    ui.click("Normals")?;
    ui.click("Bounds")?;
    assert!(ui.application.show_normals && ui.application.show_bounds);
    ui.click("Normals")?;
    ui.click("Bounds")?;
    assert!(!ui.application.show_normals && !ui.application.show_bounds);

    for label in [
        "Front",
        "Back",
        "Left",
        "Right",
        "Top",
        "Bottom",
        "Frame All",
    ] {
        let before = ui.application.camera.revision();
        ui.click(label)?;
        assert!(ui.application.camera.revision() > before, "{label}");
    }
    ui.click("All Vertices")?;
    let before = ui.application.camera.revision();
    ui.click("Frame Selected")?;
    assert!(ui.application.camera.revision() > before);
    for (label, domain) in [
        ("Vertex", SelectionDomain::Vertex),
        ("Edge", SelectionDomain::Edge),
        ("Face", SelectionDomain::Face),
    ] {
        ui.click(label)?;
        assert_eq!(ui.application.selection_domain, domain);
    }
    for tool in [
        SelectionTool::Brush,
        SelectionTool::Rectangle,
        SelectionTool::Lasso,
        SelectionTool::Click,
    ] {
        ui.click(tool.label())?;
        assert_eq!(ui.application.viewport_tool, ViewportTool::Select);
        assert_eq!(ui.application.selection_tool, tool);
    }
    for operation in [
        SelectionOperation::Add,
        SelectionOperation::Subtract,
        SelectionOperation::Toggle,
        SelectionOperation::Replace,
    ] {
        let current = format!("{:?}", ui.application.selection_operation);
        ui.choose("Click operation", &current, &format!("{operation:?}"))?;
        assert_eq!(ui.application.selection_operation, operation);
    }
    ui.click("X-Ray")?;
    assert!(!ui.application.selection_visible_only);
    ui.click("Visible")?;
    assert!(ui.application.selection_visible_only);
    ui.click("Clear")?;
    assert!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .selected_vertex_scope()
            .is_empty()
    );

    ui.choose("Editable LOD", "LOD 0", "LOD 1 · 4 vertices · 2 faces")?;
    assert_eq!(ui.application.active_lod_index, 1);
    assert_eq!(
        ui.application.mesh.as_ref().ok_or("mesh")?.faces().count(),
        2
    );
    ui.choose("Editable LOD", "LOD 1", "LOD 0 · 3 vertices · 1 faces")?;
    assert_eq!(ui.application.active_lod_index, 0);
    assert_eq!(
        ui.application.mesh.as_ref().ok_or("mesh")?.faces().count(),
        1
    );
    assert!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .selected_vertex_scope()
            .is_empty()
    );
    assert!(!ui.application.raw_primary_captured);
    Ok(())
}

#[test]
fn control_selected_shapes_and_domains_receive_coalesced_pointer_drags() -> TestResult {
    for (label, domain) in [
        ("Vertex", SelectionDomain::Vertex),
        ("Edge", SelectionDomain::Edge),
        ("Face", SelectionDomain::Face),
    ] {
        for tool in [
            SelectionTool::Click,
            SelectionTool::Brush,
            SelectionTool::Rectangle,
            SelectionTool::Lasso,
        ] {
            for visible in [true, false] {
                let mut ui = HeadlessUi::new(triangle_application()?, egui::vec2(1_280.0, 900.0));
                ui.scale_factor = 1.5;
                ui.click(label)?;
                ui.click(tool.label())?;
                ui.click(if visible { "Visible" } else { "X-Ray" })?;
                let center = ui.projected_point(domain)?;
                let points = match tool {
                    SelectionTool::Click => vec![center, center],
                    SelectionTool::Brush => {
                        vec![center + Vec2::new(-8.0, 0.0), center + Vec2::new(8.0, 0.0)]
                    }
                    SelectionTool::Rectangle => {
                        vec![center - Vec2::splat(12.0), center + Vec2::splat(12.0)]
                    }
                    SelectionTool::Lasso => vec![
                        center - Vec2::splat(12.0),
                        center + Vec2::new(12.0, -12.0),
                        center + Vec2::splat(12.0),
                        center + Vec2::new(-12.0, 12.0),
                        center - Vec2::splat(12.0),
                    ],
                };
                ui.drag(&points, PointerButton::Primary);
                let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
                let count = match domain {
                    SelectionDomain::Vertex => mesh.selection.vertices.len(),
                    SelectionDomain::Edge => mesh.selection.edges.len(),
                    SelectionDomain::Face => mesh.selection.faces.len(),
                };
                assert!(
                    count > 0,
                    "{domain:?} {tool:?} visible={visible}: {}",
                    ui.application.status
                );
                assert_eq!(ui.application.history.undo_len(), 1);
                assert!(!ui.application.raw_primary_captured);
                assert!(ui.application.selection_gesture.is_none());
                mesh.validate()?;
            }
        }
    }
    Ok(())
}

#[test]
fn topology_buttons_round_trip_the_painted_selection() -> TestResult {
    for (label, expected_faces) in [("Delete", 0), ("Subdivide", 4), ("Duplicate", 2)] {
        let mut ui = HeadlessUi::new(triangle_application()?, egui::vec2(1_280.0, 720.0));
        ui.click("All Faces")?;
        let baseline = ui
            .application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint();
        let selection = ui
            .application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .selection
            .clone();
        ui.click(label)?;
        assert_eq!(
            ui.application.mesh.as_ref().ok_or("mesh")?.faces().count(),
            expected_faces
        );
        let edited = ui
            .application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint();
        assert_ne!(baseline, edited);
        ui.click("Undo")?;
        assert_eq!(
            ui.application
                .mesh
                .as_ref()
                .ok_or("mesh")?
                .structural_fingerprint(),
            baseline
        );
        assert_eq!(
            ui.application.mesh.as_ref().ok_or("mesh")?.selection,
            selection
        );
        ui.click("Redo")?;
        assert_eq!(
            ui.application
                .mesh
                .as_ref()
                .ok_or("mesh")?
                .structural_fingerprint(),
            edited
        );
        ui.application.mesh.as_ref().ok_or("mesh")?.validate()?;
    }
    Ok(())
}

#[test]
fn camera_input_and_inspector_scrolling_keep_distinct_pointer_ownership() -> TestResult {
    for scale in [1.0, 1.5, 2.0] {
        let mut ui = HeadlessUi::new(two_lod_application()?, egui::vec2(1_280.0, 720.0));
        ui.scale_factor = scale;
        let rectangle = ui.application.viewport_rect.ok_or("viewport")?;
        let center = Vec2::new(rectangle.center().x, rectangle.center().y);
        for button in [PointerButton::Secondary, PointerButton::Middle] {
            let before = ui.application.camera.revision();
            ui.drag(&[center, center + Vec2::new(30.0, -15.0)], button);
            assert!(ui.application.camera.revision() > before);
            assert!(!ui.application.raw_orbit_captured);
            assert!(!ui.application.raw_pan_captured);
        }
        let before = ui.application.camera.eye();
        ui.frame(vec![Event::PointerMoved(rectangle.center())]);
        ui.frame(vec![wheel_event(120.0)]);
        for _ in 0..16 {
            ui.frame(Vec::new());
        }
        assert_ne!(ui.application.camera.eye(), before);
        let before = ui.application.camera.revision();
        ui.frame(vec![
            key_event(egui::Key::F, true),
            key_event(egui::Key::F, false),
        ]);
        assert!(ui.application.camera.revision() > before);

        // Scrolling the tools must not zoom or start a mesh gesture underneath.
        let before = ui.application.camera.view_projection(rectangle);
        ui.scroll_inspector(-240.0);
        ui.scroll_inspector(240.0);
        assert_eq!(ui.application.camera.view_projection(rectangle), before);
        assert_eq!(ui.application.history.undo_len(), 0);
        assert!(ui.application.selection_gesture.is_none());
        assert!(ui.application.edit_gesture.is_none());
    }
    Ok(())
}

#[test]
fn resized_ui_frames_keep_projection_and_controls_inside_the_window() -> TestResult {
    let mut ui = HeadlessUi::new(two_lod_application()?, egui::vec2(1_440.0, 900.0));
    for size in [
        egui::vec2(1_920.0, 600.0),
        egui::vec2(800.0, 1_200.0),
        egui::vec2(1_000.0, 600.0),
    ] {
        ui.size = size;
        ui.frame(Vec::new());
        ui.frame(Vec::new());
        let rectangle = ui.application.viewport_rect.ok_or("viewport")?;
        assert!(Rect::from_min_size(Pos2::ZERO, size).contains_rect(rectangle));
        assert!(rectangle.width() > 0.0 && rectangle.height() > 0.0);
        let camera = &ui.application.camera;
        let center = camera.project(camera.target(), rectangle).ok_or("center")?;
        let right = camera
            .project(camera.target() + camera.right() * 0.25, rectangle)
            .ok_or("right")?;
        let up = camera
            .project(camera.target() + camera.up() * 0.25, rectangle)
            .ok_or("up")?;
        let x_pixels = right.screen.distance(center.screen);
        let y_pixels = up.screen.distance(center.screen);
        assert!((x_pixels - y_pixels).abs() < x_pixels.max(y_pixels) * 0.001);
        assert_eq!(
            ui.application
                .projection
                .as_ref()
                .ok_or("projection")?
                .rectangle,
            rectangle
        );
        ui.click("Grab")?;
        assert_eq!(ui.application.viewport_tool, ViewportTool::Grab);
        ui.reveal("Export Neutral OBJ…")?;
    }
    Ok(())
}

#[test]
fn tool_buttons_and_pointer_drags_produce_edits_and_exact_history() -> TestResult {
    for tool in [
        ViewportTool::Move,
        ViewportTool::Rotate,
        ViewportTool::Scale,
        ViewportTool::Grab,
        ViewportTool::Smooth,
        ViewportTool::Inflate,
        ViewportTool::Pinch,
    ] {
        let mut ui = HeadlessUi::new(triangle_application()?, egui::vec2(1_280.0, 900.0));
        ui.click("All Vertices")?;
        ui.click(tool.label())?;
        assert_eq!(ui.application.viewport_tool, tool);
        let rectangle = ui.application.viewport_rect.ok_or("viewport")?;
        let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
        let baseline = mesh.structural_fingerprint();
        let selection = mesh.selection.clone();
        let pivot = OrbitCamera::selected_center(mesh).ok_or("pivot")?;
        let center = ui
            .application
            .camera
            .project(pivot, rectangle)
            .ok_or("center")?
            .screen;
        if tool.sculpt_tool().is_none() {
            assert!(
                ui.output.shapes.iter().any(|clipped| {
                    matches!(&clipped.shape, egui::Shape::Circle(circle)
                    if circle.fill == Color32::WHITE
                        && circle.center.distance(egui::pos2(center.x, center.y)) < 0.1)
                }),
                "{tool:?} did not paint its center gizmo"
            );
        }
        let (start, end) = if tool == ViewportTool::Rotate {
            let ring = rotation_ring(&ui.application.camera, pivot, GizmoAxis::Z, rectangle);
            (ring[0], ring[ring.len() / 4])
        } else if tool.sculpt_tool().is_some() {
            let point = ui.projected_point(SelectionDomain::Vertex)?;
            (point + Vec2::new(8.0, -4.0), point + Vec2::new(18.0, -9.0))
        } else {
            (center, center + Vec2::new(20.0, -8.0))
        };
        ui.drag(&[start, end], PointerButton::Primary);
        let edited = ui
            .application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint();
        assert_ne!(
            edited, baseline,
            "{tool:?} did not edit: {}",
            ui.application.status
        );
        assert_eq!(ui.application.history.undo_len(), 1, "{tool:?}");
        assert!(ui.application.edit_gesture.is_none());
        ui.click("Undo")?;
        assert_eq!(
            ui.application
                .mesh
                .as_ref()
                .ok_or("mesh")?
                .structural_fingerprint(),
            baseline
        );
        assert_eq!(
            ui.application.mesh.as_ref().ok_or("mesh")?.selection,
            selection
        );
        ui.click("Redo")?;
        assert_eq!(
            ui.application
                .mesh
                .as_ref()
                .ok_or("mesh")?
                .structural_fingerprint(),
            edited
        );
        ui.application.mesh.as_ref().ok_or("mesh")?.validate()?;
    }
    Ok(())
}

#[test]
fn escape_and_layout_resize_cancel_input_driven_edits_exactly() -> TestResult {
    for resize in [false, true] {
        let mut ui = HeadlessUi::new(triangle_application()?, egui::vec2(1_280.0, 900.0));
        ui.click("All Vertices")?;
        ui.click("Move")?;
        let rectangle = ui.application.viewport_rect.ok_or("viewport")?;
        let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
        let baseline = mesh.structural_fingerprint();
        let selection = mesh.selection.clone();
        let pivot = OrbitCamera::selected_center(mesh).ok_or("pivot")?;
        let point = ui
            .application
            .camera
            .project(pivot, rectangle)
            .ok_or("projected pivot")?
            .screen;
        let start = egui::pos2(point.x, point.y);
        let end = start + egui::vec2(20.0, -8.0);
        ui.frame(vec![
            Event::PointerMoved(start),
            pointer_button(start, PointerButton::Primary, true),
        ]);
        ui.frame(vec![Event::PointerMoved(end)]);
        assert!(ui.application.edit_gesture.is_some());
        assert_ne!(
            ui.application
                .mesh
                .as_ref()
                .ok_or("mesh")?
                .structural_fingerprint(),
            baseline
        );
        if resize {
            ui.size = egui::vec2(1_000.0, 600.0);
            ui.frame(Vec::new());
        } else {
            ui.frame(vec![
                key_event(egui::Key::Escape, true),
                key_event(egui::Key::Escape, false),
            ]);
        }
        ui.frame(vec![pointer_button(end, PointerButton::Primary, false)]);
        assert!(ui.application.edit_gesture.is_none());
        assert_eq!(ui.application.history.undo_len(), 0);
        assert_eq!(
            ui.application
                .mesh
                .as_ref()
                .ok_or("mesh")?
                .structural_fingerprint(),
            baseline
        );
        assert_eq!(
            ui.application.mesh.as_ref().ok_or("mesh")?.selection,
            selection
        );
        assert!(!ui.application.raw_primary_captured);
    }
    Ok(())
}

#[test]
fn pinch_moves_only_the_selected_vertex_toward_the_painted_brush_center() -> TestResult {
    let mut ui = HeadlessUi::new(triangle_application()?, egui::vec2(1_280.0, 900.0));
    ui.click("Vertex")?;
    ui.click("Click")?;
    let point = ui.projected_point(SelectionDomain::Vertex)?;
    ui.drag(&[point, point], PointerButton::Primary);
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    assert_eq!(mesh.selection.vertices.len(), 1);
    let selected = *mesh
        .selection
        .vertices
        .iter()
        .next()
        .ok_or("selected vertex")?;
    let baseline = mesh.structural_fingerprint();
    let positions = mesh
        .vertices()
        .map(|(handle, vertex)| (handle, vertex.position))
        .collect::<Vec<_>>();
    ui.click("Pinch")?;
    let center = point + Vec2::new(12.0, -6.0);
    let pointer = egui::pos2(center.x, center.y);
    ui.frame(vec![
        Event::PointerMoved(pointer),
        pointer_button(pointer, PointerButton::Primary, true),
    ]);
    assert!(ui.application.edit_gesture.is_some());
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    let edited = mesh.structural_fingerprint();
    assert_ne!(edited, baseline);
    for (handle, position) in positions {
        if handle != selected {
            assert_eq!(mesh.vertex(handle).ok_or("vertex")?.position, position);
        }
    }
    let rectangle = ui.application.viewport_rect.ok_or("viewport")?;
    let edited_point = ui
        .application
        .camera
        .project(
            Vec3::from_array(mesh.vertex(selected).ok_or("selected vertex")?.position),
            rectangle,
        )
        .ok_or("edited projection")?
        .screen;
    assert!(edited_point.distance(center) < point.distance(center));
    assert!(
        ui.output.shapes.iter().any(|clipped| {
            matches!(&clipped.shape, egui::Shape::Circle(circle)
            if (circle.radius - ui.application.brush_radius).abs() < 0.01
                && circle.center.distance(pointer) < 0.01
                && circle.stroke.color == Color32::from_rgb(80, 190, 255))
        }),
        "the brush circle is missing from the egui draw output"
    );
    // Releasing at the already-sampled point must not apply Pinch a second time.
    ui.frame(vec![pointer_button(pointer, PointerButton::Primary, false)]);
    assert_eq!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint(),
        edited
    );
    assert_eq!(ui.application.history.undo_len(), 2); // selection, then Pinch
    ui.click("Undo")?;
    assert_eq!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint(),
        baseline
    );
    Ok(())
}

#[test]
fn disabled_edit_controls_do_not_activate_or_change_the_mesh() -> TestResult {
    let mut ui = HeadlessUi::new(triangle_application()?, egui::vec2(1_280.0, 720.0));
    let baseline = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();
    for label in [
        "Move",
        "Rotate",
        "Scale",
        "Delete",
        "Subdivide",
        "Duplicate",
    ] {
        ui.click(label)?;
        assert_eq!(ui.application.viewport_tool, ViewportTool::Select);
        assert_eq!(
            ui.application
                .mesh
                .as_ref()
                .ok_or("mesh")?
                .structural_fingerprint(),
            baseline
        );
        assert_eq!(ui.application.history.undo_len(), 0);
    }
    Ok(())
}

fn wheel_event(distance: f32) -> Event {
    Event::MouseWheel {
        unit: egui::MouseWheelUnit::Point,
        delta: egui::vec2(0.0, distance),
        phase: egui::TouchPhase::Move,
        modifiers: egui::Modifiers::NONE,
    }
}

fn key_event(key: egui::Key, pressed: bool) -> Event {
    Event::Key {
        key,
        physical_key: None,
        pressed,
        repeat: false,
        modifiers: egui::Modifiers::NONE,
    }
}

#[test]
fn dense_face_selection_uses_a_fill_without_radiating_triangle_outlines() -> TestResult {
    let mut application = triangle_application()?;
    for _ in 0..4 {
        let selected = if application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .selection
            .faces
            .is_empty()
        {
            application
                .mesh
                .as_ref()
                .ok_or("mesh")?
                .faces()
                .map(|(handle, _)| handle)
                .collect()
        } else {
            application
                .mesh
                .as_ref()
                .ok_or("mesh")?
                .selection
                .faces
                .clone()
        };
        application
            .mesh
            .as_mut()
            .ok_or("mesh")?
            .subdivide_faces(&selected)?;
    }
    assert_eq!(
        application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .selection
            .faces
            .len(),
        256
    );
    let ui = HeadlessUi::new(application, egui::vec2(1_280.0, 720.0));
    let face_paths = ui
        .output
        .shapes
        .iter()
        .filter_map(|clipped| match &clipped.shape {
            egui::Shape::Path(path)
                if path.closed
                    && path.points.len() == 3
                    && path.fill == Color32::from_rgba_unmultiplied(255, 125, 25, 72) =>
            {
                Some(path)
            }
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(face_paths.len(), 256);
    assert!(face_paths.iter().all(|path| path.fill.a() > 0));
    assert!(face_paths.iter().all(|path| path.stroke.width == 0.0));
    Ok(())
}

#[test]
fn inspector_paints_loaded_texture_relationship_provenance() -> TestResult {
    let document = cdmw_formats::decode_mesh(
        &cdmw_formats::synthetic::triangle_pam("fallback.dds"),
        cdmw_formats::MeshFormat::Pam,
    )?;
    let mesh = WorkingMesh::from_document(&document)?;
    let base_bytes = cdmw_texture::synthetic::rgba8_checker_dds();
    let base_metadata =
        cdmw_texture::inspect_dds(&base_bytes, cdmw_texture::TextureRole::BaseColor)?;
    let glossiness_bytes = cdmw_texture::synthetic::rgba8_checker_dds();
    let glossiness_metadata =
        cdmw_texture::inspect_dds(&glossiness_bytes, cdmw_texture::TextureRole::Glossiness)?;
    let flow_bytes = cdmw_texture::synthetic::rgba8_checker_dds();
    let flow_metadata = cdmw_texture::inspect_dds(&flow_bytes, cdmw_texture::TextureRole::Flow)?;
    let layer_mask_bytes = cdmw_texture::synthetic::rgba8_checker_dds();
    let layer_mask_metadata =
        cdmw_texture::inspect_dds(&layer_mask_bytes, cdmw_texture::TextureRole::LayerMask)?;
    let mut application = LabApplication::new(None, None);
    application.install_loaded_mesh(crate::loader::LoadedMesh {
        path: PathBuf::from("character/model/body.pam"),
        document,
        mesh,
        other_lod_meshes: Vec::new(),
        textures: vec![
            crate::loader::LoadedTexture {
                label: "character/texture/body.dds".to_owned(),
                metadata: base_metadata,
                bytes: base_bytes,
                role: cdmw_texture::TextureRole::BaseColor,
                requested_reference: "character/texture/body.dds".to_owned(),
                parameter_name: Some("_baseColorTexture".to_owned()),
                sidecar_label: Some("character/modelproperty/body.pam_xml".to_owned()),
                resolution_method: cdmw_asset_graph::ResolutionMethod::ExplicitVirtualPath,
                archive_compression: Some(cdmw_archive::CompressionOutcome::PartialDds),
                material_indices_by_lod: vec![vec![0]],
            },
            crate::loader::LoadedTexture {
                label: "character/texture/body_gloss.dds".to_owned(),
                metadata: glossiness_metadata,
                bytes: glossiness_bytes,
                role: cdmw_texture::TextureRole::Glossiness,
                requested_reference: "character/texture/body_gloss.dds".to_owned(),
                parameter_name: Some("_glossinessTexture".to_owned()),
                sidecar_label: Some("character/modelproperty/body.pam_xml".to_owned()),
                resolution_method: cdmw_asset_graph::ResolutionMethod::ExplicitVirtualPath,
                archive_compression: Some(cdmw_archive::CompressionOutcome::Stored),
                material_indices_by_lod: vec![vec![0]],
            },
            crate::loader::LoadedTexture {
                label: "character/texture/body_f.dds".to_owned(),
                metadata: flow_metadata,
                bytes: flow_bytes,
                role: cdmw_texture::TextureRole::Flow,
                requested_reference: "character/texture/body_f.dds".to_owned(),
                parameter_name: Some("_flowTexture".to_owned()),
                sidecar_label: Some("character/modelproperty/body.pam_xml".to_owned()),
                resolution_method: cdmw_asset_graph::ResolutionMethod::ExplicitVirtualPath,
                archive_compression: Some(cdmw_archive::CompressionOutcome::Stored),
                material_indices_by_lod: vec![vec![0]],
            },
            crate::loader::LoadedTexture {
                label: "character/texture/body_mg.dds".to_owned(),
                metadata: layer_mask_metadata,
                bytes: layer_mask_bytes,
                role: cdmw_texture::TextureRole::LayerMask,
                requested_reference: "character/texture/body_mg.dds".to_owned(),
                parameter_name: Some("_detailMaskTexture".to_owned()),
                sidecar_label: Some("character/modelproperty/body.pam_xml".to_owned()),
                resolution_method: cdmw_asset_graph::ResolutionMethod::ExplicitVirtualPath,
                archive_compression: Some(cdmw_archive::CompressionOutcome::Stored),
                material_indices_by_lod: vec![vec![0]],
            },
        ],
        material_parameters: vec![
            crate::loader::LoadedMaterialParameter {
                sidecar_label: "character/modelproperty/body.pam_xml".to_owned(),
                parameter: cdmw_texture::MaterialParameter {
                    wrapper_type: "SkinnedMeshMaterialWrapper".to_owned(),
                    submesh_name: "triangle".to_owned(),
                    material_name: "material".to_owned(),
                    parameter_type: "MaterialParameterFloat".to_owned(),
                    parameter_name: "_screenSpaceDisplacementScale".to_owned(),
                    raw_value: Some("0.09".to_owned()),
                    attributes: vec![("_value".to_owned(), "0.09".to_owned())],
                    kind: cdmw_texture::MaterialParameterKind::Float,
                    confidence: cdmw_texture::MaterialParameterConfidence::Explicit,
                },
                material_indices_by_lod: vec![vec![0]],
                preview_semantic: Some("Height scale"),
            },
            crate::loader::LoadedMaterialParameter {
                sidecar_label: "character/modelproperty/body.pam_xml".to_owned(),
                parameter: cdmw_texture::MaterialParameter {
                    wrapper_type: "SkinnedMeshMaterialWrapper".to_owned(),
                    submesh_name: "triangle".to_owned(),
                    material_name: "material".to_owned(),
                    parameter_type: "MaterialParameterColor".to_owned(),
                    parameter_name: "_emissiveColor".to_owned(),
                    raw_value: Some("#204060ff".to_owned()),
                    attributes: vec![("_value".to_owned(), "#204060ff".to_owned())],
                    kind: cdmw_texture::MaterialParameterKind::Color,
                    confidence: cdmw_texture::MaterialParameterConfidence::Explicit,
                },
                material_indices_by_lod: vec![vec![0]],
                preview_semantic: Some("Emissive color"),
            },
            crate::loader::LoadedMaterialParameter {
                sidecar_label: "character/modelproperty/body.pam_xml".to_owned(),
                parameter: cdmw_texture::MaterialParameter {
                    wrapper_type: "SkinnedMeshMaterialWrapper".to_owned(),
                    submesh_name: "triangle".to_owned(),
                    material_name: "material".to_owned(),
                    parameter_type: "MaterialParameterFloat".to_owned(),
                    parameter_name: "_roughness".to_owned(),
                    raw_value: Some("0.75".to_owned()),
                    attributes: vec![("_value".to_owned(), "0.75".to_owned())],
                    kind: cdmw_texture::MaterialParameterKind::Float,
                    confidence: cdmw_texture::MaterialParameterConfidence::Explicit,
                },
                material_indices_by_lod: vec![vec![0]],
                preview_semantic: Some("Roughness factor"),
            },
            crate::loader::LoadedMaterialParameter {
                sidecar_label: "character/modelproperty/body.pam_xml".to_owned(),
                parameter: cdmw_texture::MaterialParameter {
                    wrapper_type: "SkinnedMeshMaterialWrapper".to_owned(),
                    submesh_name: "triangle".to_owned(),
                    material_name: "material".to_owned(),
                    parameter_type: "MaterialParameterBoolean".to_owned(),
                    parameter_name: "_alphaTest".to_owned(),
                    raw_value: Some("true".to_owned()),
                    attributes: vec![("_value".to_owned(), "true".to_owned())],
                    kind: cdmw_texture::MaterialParameterKind::Boolean,
                    confidence: cdmw_texture::MaterialParameterConfidence::Explicit,
                },
                material_indices_by_lod: vec![vec![0]],
                preview_semantic: Some("Alpha cutout"),
            },
        ],
        material_factors: vec![crate::loader::LoadedMaterialFactors {
            sidecar_label: "character/modelproperty/body.pam_xml".to_owned(),
            emissive_color: Some([32.0 / 255.0, 64.0 / 255.0, 96.0 / 255.0]),
            emissive_intensity: Some(2.5),
            roughness: Some(0.75),
            metalness: Some(0.5),
            specular: Some(0.9),
            height_scale: Some(0.09),
            alpha_cutoff: Some(0.08),
            hair_anisotropy: Some(true),
            layer_mask_channel: Some(2),
            material_indices_by_lod: vec![vec![0]],
        }],
    });
    let mut ui = HeadlessUi::new(application, egui::vec2(1_280.0, 900.0));
    assert!(ui.reveal("Resolved material textures").is_ok());
    assert!(ui.reveal("character/texture/body.dds").is_ok());
    assert!(
        ui.reveal(
            "Role BaseColor · Reference character/texture/body.dds · Resolved via ExplicitVirtualPath · Parameter _baseColorTexture · Sidecar character/modelproperty/body.pam_xml · Archive decode Partial DDS"
        )
        .is_ok()
    );
    assert!(ui.reveal("Material ranges LOD0: 0").is_ok());
    assert!(ui.reveal("character/texture/body_gloss.dds").is_ok());
    assert!(
        ui.reveal(
            "Role Glossiness · Reference character/texture/body_gloss.dds · Resolved via ExplicitVirtualPath · Parameter _glossinessTexture · Sidecar character/modelproperty/body.pam_xml · Archive decode Stored"
        )
        .is_ok()
    );
    assert!(ui.reveal("character/texture/body_f.dds").is_ok());
    assert!(
        ui.reveal(
            "Role Flow · Reference character/texture/body_f.dds · Resolved via ExplicitVirtualPath · Parameter _flowTexture · Sidecar character/modelproperty/body.pam_xml · Archive decode Stored"
        )
        .is_ok()
    );
    assert!(
        ui.reveal("Renderer: approximate material preview (not Crimson Desert shader parity)")
            .is_ok()
    );
    assert!(ui.reveal("character/texture/body_mg.dds").is_ok());
    assert!(
        ui.reveal(
            "Role LayerMask · Reference character/texture/body_mg.dds · Resolved via ExplicitVirtualPath · Parameter _detailMaskTexture · Sidecar character/modelproperty/body.pam_xml · Archive decode Stored"
        )
        .is_ok()
    );
    assert!(ui.reveal("Prepared material factors").is_ok());
    assert!(
        ui.reveal(
            "emissive color 0.125, 0.251, 0.376 · emissive intensity 2.500 · roughness 0.750 · metalness 0.500 · specular 0.900 · height scale 0.090 · alpha cutout enabled · cutoff 0.080 · hair Flow family qualified · layer mask channel B"
        )
            .is_ok()
    );
    assert!(ui.reveal("Preserved material parameters (4)").is_ok());
    ui.click("Preserved material parameters (4)")?;
    assert!(ui.reveal("_emissiveColor · Color").is_ok());
    assert!(ui.reveal("Value #204060ff").is_ok());
    assert!(
        ui.reveal(
            "Emissive color candidate; sampled only for non-conflicting ownership with a bound emissive texture"
        )
        .is_ok()
    );
    assert!(ui.reveal("_roughness · Float").is_ok());
    assert!(
        ui.reveal(
            "Roughness factor candidate; sampled only for non-conflicting material ownership"
        )
        .is_ok()
    );
    assert!(ui.reveal("_screenSpaceDisplacementScale · Float").is_ok());
    assert!(
        ui.reveal("Height scale candidate; sampled only for non-conflicting material ownership")
            .is_ok()
    );
    assert!(ui.reveal("_alphaTest · Boolean").is_ok());
    assert!(
        ui.reveal("Alpha cutout candidate; sampled only for non-conflicting material ownership")
            .is_ok()
    );
    Ok(())
}
