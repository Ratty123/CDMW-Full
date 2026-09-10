//! No-window tests of the painted controls and the live pointer-capture route.
//!
//! Widget coordinates come from egui's clipped text shapes, not a duplicate UI
//! layout. Actions are collected during the frame and applied afterwards, just
//! like `LabApplication::redraw`. This does not exercise the OS event loop or GPU.

use super::*;
use crate::headless_tests::{
    TestResult, symmetry_application, triangle_application, two_lod_application,
};
use cdmw_interaction::ProjectedHandle;
use egui::{Event, FullOutput, PointerButton, Pos2, Rect};
use std::collections::{HashMap, HashSet};
use tempfile::tempdir;
use winit::event::DeviceId;

struct HeadlessUi {
    application: LabApplication,
    size: egui::Vec2,
    scale_factor: f64,
    output: FullOutput,
    integrated_cdmw: bool,
    last_actions: Vec<UiAction>,
}

fn painted_label_contrast(ui: &HeadlessUi, label: &str) -> Result<f32, Box<dyn std::error::Error>> {
    let text = ui
        .output
        .shapes
        .iter()
        .find_map(|clipped| {
            let egui::Shape::Text(text) = &clipped.shape else {
                return None;
            };
            (text.galley.job.text == label).then_some(text)
        })
        .ok_or_else(|| format!("missing painted label {label}"))?;
    let background = ui
        .rectangle_fills_at(text.visual_bounding_rect().center())
        .last()
        .copied()
        .ok_or("missing button background")?;
    let mut foreground = text
        .override_text_color
        .unwrap_or(text.galley.job.sections[0].format.color);
    if foreground == Color32::PLACEHOLDER {
        foreground = text.fallback_color;
    }
    let opacity = text.opacity_factor * f32::from(foreground.a()) / 255.0;
    let bg = [background.r(), background.g(), background.b()].map(|v| f32::from(v) / 255.0);
    let fg = [foreground.r(), foreground.g(), foreground.b()].map(|v| f32::from(v) / 255.0);
    let blended = std::array::from_fn(|i| fg[i] * opacity + bg[i] * (1.0 - opacity));
    let luminance = |values: [f32; 3]| {
        values
            .into_iter()
            .zip([0.2126, 0.7152, 0.0722])
            .map(|(v, weight)| {
                weight
                    * if v <= 0.04045 {
                        v / 12.92
                    } else {
                        ((v + 0.055) / 1.055).powf(2.4)
                    }
            })
            .sum::<f32>()
    };
    let (a, b) = (luminance(blended), luminance(bg));
    Ok((a.max(b) + 0.05) / (a.min(b) + 0.05))
}

#[test]
#[ignore = "requires current application palettes exported to CDMW_THEME_PALETTES_FILE"]
fn integrated_theme_button_readability_for_supplied_palettes() -> TestResult {
    let palettes: serde_json::Map<String, Value> =
        serde_json::from_slice(&std::fs::read(std::env::var("CDMW_THEME_PALETTES_FILE")?)?)?;
    assert!(!palettes.is_empty(), "no application palettes supplied");
    let mut results = Vec::new();
    for (key, palette) in palettes {
        let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
            triangle_application()?,
            egui::vec2(1480.0, 1050.0),
        );
        ui.application
            .apply_cdmw_theme_payload(&json!({"theme": key, "palette": palette}));
        ui.frame(Vec::new());
        ui.frame(Vec::new());
        ui.click("Select")?;
        ui.click("Face")?;
        ui.frame(vec![Event::PointerMoved(egui::pos2(0.0, 0.0))]);
        for label in [
            "Exact",
            "Select",
            "Face",
            "Visible",
            "Free Edit",
            "Clear Selection",
            "Invert",
        ] {
            let contrast = painted_label_contrast(&ui, label)?;
            assert!(
                contrast >= 4.5,
                "{key}: {label} contrast is {contrast:.2}:1"
            );
            results.push(
                json!({"theme": key, "control": label, "state": "rest", "contrast": contrast}),
            );
        }
        for label in ["Clear Selection", "Select"] {
            let center = ui.reveal(label)?.center();
            for (state, events) in [
                ("hover", vec![Event::PointerMoved(center)]),
                (
                    "pressed",
                    vec![pointer_button(center, PointerButton::Primary, true)],
                ),
            ] {
                ui.frame(events);
                let contrast = painted_label_contrast(&ui, label)?;
                assert!(
                    contrast >= 4.5,
                    "{key}: {label} {state} contrast is {contrast:.2}:1"
                );
                results.push(
                    json!({"theme": key, "control": label, "state": state, "contrast": contrast}),
                );
            }
            ui.frame(vec![pointer_button(center, PointerButton::Primary, false)]);
        }
    }
    let report = std::env::var("CDMW_THEME_READABILITY_REPORT")?;
    std::fs::write(
        report,
        serde_json::to_vec_pretty(&json!({"ok": true, "cases": results}))?,
    )?;
    Ok(())
}

#[test]
#[ignore = "requires an explicitly supplied local mesh and evidence path"]
fn measure_authoring_selection_frames_on_supplied_mesh() -> TestResult {
    let input = std::path::PathBuf::from(std::env::var("CDMW_SELECTION_PROBE_MESH")?);
    let output = std::path::PathBuf::from(std::env::var("CDMW_SELECTION_PROBE_REPORT")?);
    let bytes = std::fs::read(&input)?;
    let document = if input.extension().is_some_and(|ext| ext == "json") {
        serde_json::from_slice(&bytes)?
    } else {
        cdmw_formats::decode_mesh(&bytes, cdmw_formats::MeshFormat::Pac)?
    };
    let mesh = WorkingMesh::from_document(&document)?;
    let faces = mesh.faces().count();
    let vertices = mesh.vertices().count();
    let mut application = LabApplication::new(None, None);
    application.document = Some(document);
    application.mesh = Some(mesh);
    let mut ui =
        HeadlessUi::new_integrated_cdmw_for_controls(application, egui::vec2(1440.0, 900.0));
    let mut results = Vec::new();
    for selected in [false, true] {
        let mesh = ui.application.mesh.as_mut().ok_or("mesh")?;
        mesh.set_selection(Selection {
            faces: if selected {
                mesh.faces().map(|(handle, _)| handle).collect()
            } else {
                HashSet::new()
            },
            ..Selection::default()
        })?;
        for orbit in [false, true] {
            let mut samples = Vec::new();
            for _ in 0..20 {
                if orbit {
                    ui.application.camera.orbit(Vec2::new(1.0, 0.0));
                }
                let started = Instant::now();
                ui.frame(Vec::new());
                let _ = ui
                    .application
                    .egui_context
                    .tessellate(ui.output.shapes.clone(), 1.0);
                samples.push(started.elapsed().as_secs_f64() * 1000.0);
            }
            samples.sort_by(f64::total_cmp);
            results.push(json!({"selected": selected, "orbit": orbit, "median_ms": samples[10], "p95_ms": samples[18]}));
        }
    }
    assert_eq!(std::fs::read(&input)?, bytes);
    let report = json!({"input": input, "faces": faces, "vertices": vertices, "cpu_ui_frames": results, "input_unchanged": true, "gpu_measured": false});
    std::fs::write(output, serde_json::to_vec_pretty(&report)?)?;
    println!("{report}");
    Ok(())
}

impl HeadlessUi {
    fn new(application: LabApplication, size: egui::Vec2) -> Self {
        let mut ui = Self {
            application,
            size,
            scale_factor: 1.0,
            output: FullOutput::default(),
            integrated_cdmw: false,
            last_actions: Vec::new(),
        };
        // egui resolves panel widths and font layout on the first frames.
        ui.frame(Vec::new());
        ui.frame(Vec::new());
        ui
    }

    fn new_integrated_cdmw(mut application: LabApplication, size: egui::Vec2) -> Self {
        application.cdmw_orbit_mode = true;
        application.cdmw_state = json!({
            "base_revision": 0,
            "undo_count": 0,
            "redo_count": 0,
            "history_cursor": 0,
            "history_entries": [],
            "output_policy": "exact_game_asset",
            "output_destination_ready": false,
            "authoring_enabled": true,
            "output_policy_reason": "",
            "geometry_layers": {
                "active_layer_id": "base",
                "clipboard_ready": false,
                "layers": [{"layer_id": "base", "name": "Base", "submesh_indices": [0], "visible": true, "base": true}]
            },
            "morph_refit": {"available_profiles": [], "values": []}
        });
        let mut ui = Self {
            application,
            size,
            scale_factor: 1.0,
            output: FullOutput::default(),
            integrated_cdmw: true,
            last_actions: Vec::new(),
        };
        ui.frame(Vec::new());
        ui.frame(Vec::new());
        ui
    }

    // Control behavior tests explicitly open the surrounding sections. Startup
    // and persistence tests use new_integrated_cdmw to exercise closed defaults.
    fn new_integrated_cdmw_for_controls(application: LabApplication, size: egui::Vec2) -> Self {
        let mut ui = Self::new_integrated_cdmw(application, size);
        for label in ["Viewport", "Selection", "Transform", "Sculpt", "Mesh Data"] {
            ui.click_tool_button(label).expect("open tool section");
        }
        for label in ["Parts", "Geometry Layers", "Action History"] {
            ui.click(label).expect("open inspector section");
        }
        ui.scroll_tool_rail(2_000.0);
        ui.scroll_inspector(2_000.0);
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
            |ui| {
                // Exercise the retained rig implementation directly. There is no product entry point.
                if self.integrated_cdmw
                    && self.application.cdmw_rail_page == Some(CdmwRailPage::RigWeights)
                {
                    egui::Panel::left("retained_rig_test")
                        .exact_size(350.0)
                        .show(ui, |ui| {
                            egui::ScrollArea::vertical().show(ui, |ui| {
                                self.application
                                    .draw_cdmw_rig_weights_page(ui, &mut actions);
                            });
                        });
                }
                actions.extend(if self.integrated_cdmw {
                    self.application.draw_cdmw_ui(ui)
                } else {
                    self.application.draw_ui(ui)
                })
            },
        );
        if !actions.is_empty() {
            self.last_actions.clone_from(&actions);
        }
        self.application.handle_actions(
            actions
                .into_iter()
                .filter(|action| {
                    !matches!(
                        action,
                        UiAction::ChooseCdmwFreeEdit
                            | UiAction::ChooseCdmwMorphPreset { .. }
                            | UiAction::ChooseCdmwRefitMesh { .. }
                    )
                })
                .collect(),
        );
        self.output.textures_delta.clear();
        assert!(self.application.window.is_none());
        assert!(self.application.renderer.is_none());
    }

    fn open_retained_rig_page(&mut self) {
        self.application.cancel_active_gesture("Retained rig test");
        self.application.cdmw_rail_page = Some(CdmwRailPage::RigWeights);
        self.application.viewport_tool = ViewportTool::Select;
        self.application.selection_domain = SelectionDomain::Vertex;
        self.application.cdmw_orbit_mode = false;
        self.frame(Vec::new());
        self.frame(Vec::new());
    }

    fn click_tool_button(&mut self, label: &str) -> TestResult {
        self.scroll_tool_rail(2_000.0);
        self.reveal(label)?;
        let left = self.application.viewport_rect.ok_or("viewport")?.left();
        // A tool name can also be a dropdown value (for example Smooth falloff).
        let row = self
            .output
            .shapes
            .iter()
            .filter_map(|clipped| {
                let egui::Shape::Text(text) = &clipped.shape else {
                    return None;
                };
                let rect = text.visual_bounding_rect();
                (text.galley.job.text == label
                    && rect.right() < left
                    && clipped.clip_rect.right() <= left + 5.0
                    && clipped.clip_rect.contains_rect(rect))
                .then_some(rect)
            })
            .min_by(|a, b| a.top().total_cmp(&b.top()))
            .ok_or("tool row")?;
        self.click_at(row.center());
        self.settle_layout();
        Ok(())
    }

    fn label_rect(&self, label: &str) -> Option<Rect> {
        self.label_rect_where(label, |_| true)
    }

    fn rectangle_fills_at(&self, point: Pos2) -> Vec<Color32> {
        self.output
            .shapes
            .iter()
            .filter_map(|clipped| match &clipped.shape {
                egui::Shape::Rect(shape)
                    if shape.rect.contains(point) && shape.fill != Color32::TRANSPARENT =>
                {
                    Some(shape.fill)
                }
                _ => None,
            })
            .collect()
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

    fn scroll_tool_rail(&mut self, distance: f32) {
        let viewport = self.application.viewport_rect.expect("viewport");
        let position = egui::pos2(viewport.left() * 0.5, self.size.y * 0.5);
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
        if self.integrated_cdmw {
            self.scroll_tool_rail(2_000.0);
            for _ in 0..32 {
                if let Some(rectangle) = self.label_rect(label) {
                    return Ok(rectangle);
                }
                self.scroll_tool_rail(-120.0);
            }
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
        self.settle_layout();
        Ok(())
    }

    fn settle_layout(&mut self) {
        if self.integrated_cdmw {
            for _ in 0..16 {
                self.frame(Vec::new());
            }
        }
    }

    fn click_where(&mut self, label: &str, accepts: impl Fn(Rect) -> bool) -> TestResult {
        self.frame(Vec::new());
        let rectangle = self
            .label_rect_where(label, accepts)
            .ok_or_else(|| format!("missing scoped control {label:?}"))?;
        self.click_at(rectangle.center());
        Ok(())
    }

    fn actions_from_click(
        &mut self,
        label: &str,
    ) -> Result<Vec<UiAction>, Box<dyn std::error::Error>> {
        self.last_actions.clear();
        self.click(label)?;
        Ok(std::mem::take(&mut self.last_actions))
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
        let rectangle = self.application.viewport_rect.ok_or("viewport")?;
        assert!(self.application.ensure_projection(rectangle));
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

fn lod_one_application() -> Result<LabApplication, Box<dyn std::error::Error>> {
    let mut application = two_lod_application()?;
    application.handle_actions(vec![UiAction::SwitchLod(1)]);
    Ok(application)
}

fn two_part_application() -> Result<LabApplication, Box<dyn std::error::Error>> {
    let mut application = triangle_application()?;
    let mut document = application.document.take().ok_or("document")?;
    let first = document
        .lods
        .first_mut()
        .and_then(|lod| lod.submeshes.first_mut())
        .ok_or("first part")?;
    first.name = "Part A".to_owned();
    first.material = "Material A".to_owned();
    let mut second = first.clone();
    second.name = "Part B".to_owned();
    second.material = "Material B".to_owned();
    for position in &mut second.positions {
        position[0] += 3.0;
    }
    document.lods[0].submeshes.push(second);
    let mesh = WorkingMesh::from_document(&document)?;
    application.camera.frame_all(&mesh);
    application.mesh = Some(mesh);
    application.document = Some(document);
    application.projection = None;
    Ok(application)
}

fn overlapping_parts_application() -> Result<LabApplication, Box<dyn std::error::Error>> {
    let mut application = triangle_application()?;
    let mut document = application.document.take().ok_or("document")?;
    let first = document
        .lods
        .first_mut()
        .and_then(|lod| lod.submeshes.first_mut())
        .ok_or("front part")?;
    for position in &mut first.positions {
        position[2] = 0.25;
    }
    let mut second = first.clone();
    second.name = "Back".to_owned();
    for position in &mut second.positions {
        position[2] = -0.25;
    }
    document.lods[0].submeshes.push(second);
    let mesh = WorkingMesh::from_document(&document)?;
    application.camera.frame_all(&mesh);
    application.mesh = Some(mesh);
    application.document = Some(document);
    application.projection = None;
    Ok(application)
}

fn selected_count(
    ui: &HeadlessUi,
    domain: SelectionDomain,
) -> Result<usize, Box<dyn std::error::Error>> {
    let selection = &ui.application.mesh.as_ref().ok_or("mesh")?.selection;
    Ok(match domain {
        SelectionDomain::Vertex => selection.vertices.len(),
        SelectionDomain::Edge => selection.edges.len(),
        SelectionDomain::Face => selection.faces.len(),
    })
}

fn has_mesh_action(actions: &[UiAction], expected: &str) -> bool {
    actions.iter().any(
        |action| matches!(action, UiAction::CdmwMeshAction { action, .. } if *action == expected),
    )
}

fn has_topology_action(actions: &[UiAction], expected: &str) -> bool {
    actions.iter().any(
        |action| matches!(action, UiAction::CdmwTopology { action, .. } if *action == expected),
    )
}

fn has_host_command(actions: &[UiAction], expected: &str) -> bool {
    actions.iter().any(
        |action| matches!(action, UiAction::CdmwCommand { command, .. } if *command == expected),
    )
}

fn parts_actions_from_click(
    ui: &mut HeadlessUi,
    label: &str,
) -> Result<Vec<UiAction>, Box<dyn std::error::Error>> {
    let row = ui.reveal("Duplicate")?;
    ui.last_actions.clear();
    ui.click_where(label, |rect| {
        (rect.center().y - row.center().y).abs() < row.height()
    })?;
    Ok(std::mem::take(&mut ui.last_actions))
}

#[test]
fn integrated_parts_selection_and_actions_use_the_painted_controls() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        overlapping_parts_application()?,
        egui::vec2(1280.0, 900.0),
    );
    let name = ui.application.document.as_ref().ok_or("document")?.lods[0].submeshes[0]
        .name
        .clone();
    ui.application
        .ensure_projection(ui.application.viewport_rect.ok_or("viewport")?);
    assert!(ui.application.projection.is_some());
    ui.click(&format!("0: {name}"))?;
    assert_eq!(ui.application.selected_part_indices(), vec![0]);
    assert!(
        ui.application.projection.is_none(),
        "part selection did not refresh the viewport"
    );
    ui.click("All")?;
    assert_eq!(ui.application.selected_part_indices(), vec![0, 1]);
    ui.click("None")?;
    assert!(ui.application.selected_part_indices().is_empty());
    ui.click_where("Invert", |rect| rect.center().x > 900.0)?;
    assert_eq!(ui.application.selected_part_indices(), vec![0, 1]);
    ui.click(&format!("0: {name}"))?;
    assert_eq!(ui.application.selected_part_indices(), vec![1]);
    // Exact output exposes an actionable route to the supported output policy.
    assert!(!has_host_command(
        &parts_actions_from_click(&mut ui, "Delete")?,
        "topology"
    ));
    ui.click("Enable part edits…")?;
    assert!(ui.label_rect("Output").is_some());
    ui.frame(vec![Event::Key {
        key: egui::Key::Escape,
        physical_key: None,
        pressed: true,
        repeat: false,
        modifiers: egui::Modifiers::default(),
    }]);
    ui.frame(Vec::new());
    assert_eq!(ui.application.selected_part_indices(), vec![1]);
    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    ui.application.cdmw_pending_request = Some(CdmwPendingRequest {
        request_id: 1,
        event: "command_result",
        label: "Select parts".to_owned(),
        origin: Some(CdmwRequestOrigin::Selection),
    });
    assert!(!has_host_command(
        &parts_actions_from_click(&mut ui, "Delete")?,
        "topology"
    ));
    assert!(ui.label_rect("Updating parts…").is_some());
    ui.application.cdmw_pending_request = None;
    let mesh = ui.application.mesh.as_mut().ok_or("mesh")?;
    let mut mixed = mesh.selection.clone();
    mixed.faces.insert(mesh.faces().next().ok_or("face")?.0);
    mesh.set_selection(mixed)?;
    for (label, expected) in [("Duplicate", "duplicate"), ("Delete", "delete")] {
        let actions = parts_actions_from_click(&mut ui, label)?;
        assert!(actions.iter().any(|action| matches!(
            action, UiAction::CdmwCommand { command: "topology", arguments, .. } if arguments["action"] == expected
                && arguments["selection"]["source_indices"] == json!([1])
                && arguments["selection"]["faces_by_submesh"] == json!({}))),
            "{label}: {actions:?}; selected {:?}; busy {}; status {}",
            ui.application.selected_part_indices(), ui.application.cdmw_busy(), ui.application.status);
    }
    ui.click("All")?;
    assert!(!has_host_command(
        &parts_actions_from_click(&mut ui, "Delete")?,
        "topology"
    ));
    assert!(
        ui.label_rect("Keep at least one part when deleting.")
            .is_some()
    );
    ui.click("None")?;
    for label in ["Delete", "Duplicate"] {
        assert!(!has_host_command(
            &parts_actions_from_click(&mut ui, label)?,
            "topology"
        ));
    }
    Ok(())
}

#[test]
fn integrated_parts_visibility_filters_drawing_and_selection_without_changing_geometry()
-> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        overlapping_parts_application()?,
        egui::vec2(1280.0, 900.0),
    );
    let original = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();
    ui.click("1: Back")?;
    ui.click("Visibility")?;
    ui.click("Hide Selected")?;
    assert!(ui.application.selected_part_indices().is_empty());
    assert_eq!(
        ui.application.cdmw_visible_submeshes(),
        Some(HashSet::from([0]))
    );
    let snapshot = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .draw_snapshot_for_submeshes(&HashSet::from([0]));
    assert_eq!(snapshot.indices.len(), 3);
    ui.click("All")?;
    assert_eq!(ui.application.selected_part_indices(), vec![0]);
    ui.click_where("Invert", |rect| rect.center().x > 900.0)?;
    assert!(ui.application.selected_part_indices().is_empty());
    ui.click("1: Back")?;
    assert!(
        ui.application.selected_part_indices().is_empty(),
        "hidden part was selectable"
    );
    // Locate the checkbox from its painted square next to the part label.
    let label = ui.reveal("1: Back")?;
    let checkbox = ui
        .output
        .shapes
        .iter()
        .filter_map(|clipped| match &clipped.shape {
            egui::Shape::Rect(shape)
                if shape.rect.width() < 25.0
                    && shape.rect.height() < 25.0
                    && shape.rect.width() > 8.0
                    && shape.rect.right() < label.left()
                    && (shape.rect.center().y - label.center().y).abs() < 2.0 =>
            {
                Some(shape.rect)
            }
            _ => None,
        })
        .max_by(|a, b| a.right().total_cmp(&b.right()))
        .ok_or("part visibility checkbox")?;
    ui.click_at(checkbox.center());
    assert!(ui.application.cdmw_hidden_parts.is_empty());
    ui.click("1: Back")?;
    ui.click("Visibility")?;
    ui.click("Hide Selected")?;
    ui.click("Visibility")?;
    ui.click("Show All")?;
    assert!(ui.application.cdmw_hidden_parts.is_empty());
    assert_eq!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint(),
        original
    );
    assert_eq!(ui.application.cdmw_transaction_attempts, 0);
    Ok(())
}

#[test]
fn integrated_parts_rows_stay_compact_with_long_names_and_materials() -> TestResult {
    let mut application = overlapping_parts_application()?;
    for (index, part) in application.document.as_mut().ok_or("document")?.lods[0]
        .submeshes
        .iter_mut()
        .enumerate()
    {
        part.name = format!("cd_phm_00_long_part_name_{index}_{}", "damian_".repeat(8));
        part.material = "CD_PHW_00_Long_Material_Name".repeat(4);
    }
    let mut ui =
        HeadlessUi::new_integrated_cdmw_for_controls(application, egui::vec2(1000.0, 650.0));
    ui.frame(Vec::new());
    let rows = ui
        .output
        .shapes
        .iter()
        .filter_map(|clipped| match &clipped.shape {
            egui::Shape::Text(text)
                if text.galley.job.text.starts_with("0: cd_phm_")
                    || text.galley.job.text.starts_with("1: cd_phm_") =>
            {
                assert_eq!(
                    text.galley.rows.len(),
                    1,
                    "part name wrapped into multiple rows"
                );
                assert!(text.visual_bounding_rect().right() <= ui.size.x);
                Some(text.visual_bounding_rect())
            }
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(rows.len(), 2);
    assert!((rows[1].center().y - rows[0].center().y).abs() <= 28.0);
    Ok(())
}

#[test]
fn integrated_parts_visibility_follows_surviving_parts_and_respects_layers() -> TestResult {
    let root = tempdir()?;
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        overlapping_parts_application()?,
        egui::vec2(1280.0, 900.0),
    );
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(
        root.path().to_path_buf(),
        "parts",
        1,
        0,
    ));
    let original = ui.application.document.clone().ok_or("document")?;
    ui.application.cdmw_state["geometry_layers"]["layers"] = json!([
        {"submesh_indices": [0], "base": true, "visible": true},
        {"submesh_indices": [1], "base": false, "visible": false},
    ]);
    ui.application.set_cdmw_part_visibility(vec![0], false);
    assert_eq!(
        ui.application.cdmw_visible_submeshes(),
        Some(HashSet::new())
    );
    ui.application.set_cdmw_part_visibility(vec![0], true);
    assert_eq!(
        ui.application.cdmw_visible_submeshes(),
        Some(HashSet::from([0]))
    );
    ui.application.cdmw_state["geometry_layers"]["layers"][1]["visible"] = json!(true);
    ui.application.set_cdmw_part_visibility(vec![1], false);
    let mut changed = original.clone();
    changed.lods[0].submeshes.remove(0);
    ui.application.install_cdmw_document(changed)?;
    assert_eq!(ui.application.cdmw_hidden_parts, HashSet::from([0]));
    ui.application.install_cdmw_document(original)?;
    assert_eq!(ui.application.cdmw_hidden_parts, HashSet::from([1]));
    assert_eq!(ui.application.cdmw_transaction_attempts, 0);
    Ok(())
}

#[test]
fn integrated_cdmw_layout_keeps_product_surfaces_reachable_across_sizes() -> TestResult {
    for size in [
        egui::vec2(1_440.0, 900.0),
        egui::vec2(1_000.0, 650.0),
        egui::vec2(800.0, 1_200.0),
    ] {
        let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(triangle_application()?, size);
        for label in [
            "Mesh Editor",
            "Finish Edit Mesh",
            "Viewport",
            "Tools",
            "Selection",
            "Transform",
            "Sculpt",
            "Mesh Data",
            "Select",
            "Move",
            "Rotate",
            "Scale",
            "Grab",
            "Smooth",
            "Inflate",
            "Pinch",
            "Topology",
            "Cleanup",
            "Normals & Tangents",
            "UV",
            "Morph & Refit",
            "Parts",
            "Geometry Layers",
            "Action History",
            "Navigation",
            "Views",
            "Orbit",
        ] {
            assert!(ui.reveal(label).is_ok(), "missing {label:?} at {size:?}");
        }
        let viewport = ui.application.viewport_rect.ok_or("viewport")?;
        assert!(
            viewport.width() > 100.0,
            "viewport too narrow at {size:?}: {viewport:?}"
        );
        assert!(
            viewport.height() > 100.0,
            "viewport too short at {size:?}: {viewport:?}"
        );
    }
    Ok(())
}

#[test]
fn integrated_wide_layout_compacts_chrome_and_groups_tool_rows() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_440.0, 900.0),
    );

    assert!(ui.label_rect("Game / Mod output").is_none());

    let header_y = ui
        .label_rect("Mesh Editor")
        .ok_or("Mesh Editor")?
        .center()
        .y;
    for label in [
        "Clear Selection",
        "Select All",
        "History",
        "Finish Edit Mesh",
    ] {
        let y = ui.label_rect(label).ok_or(label)?.center().y;
        assert!(
            (y - header_y).abs() < 6.0,
            "{label} is not in the compact header"
        );
    }

    let footer_y = ui.label_rect("Navigation").ok_or("Navigation")?.center().y;
    for label in ["Views", "Ready"] {
        let y = ui.label_rect(label).ok_or(label)?.center().y;
        assert!(
            (y - footer_y).abs() < 6.0,
            "{label} is not in the compact footer"
        );
    }

    for labels in [
        ["Move", "Rotate", "Scale"],
        ["Grab", "Smooth", ""],
        ["Inflate", "Pinch", ""],
    ] {
        let first_y = ui.label_rect(labels[0]).ok_or(labels[0])?.center().y;
        for label in labels.into_iter().filter(|label| !label.is_empty()) {
            let y = ui.label_rect(label).ok_or(label)?.center().y;
            assert!(
                (y - first_y).abs() < 2.0,
                "{label} is not grouped with its tool row"
            );
        }
    }

    assert!(
        ui.label_rect("Morph & Refit").is_some(),
        "the complete collapsed tool index should be visible without scrolling at 900 points"
    );
    let viewport = ui.application.viewport_rect.ok_or("viewport")?;
    assert!(
        viewport.height() > 800.0,
        "wide chrome leaves too little viewport height: {viewport:?}"
    );

    ui.application.apply_cdmw_theme_payload(&json!({
        "variant": "dark",
        "density": "comfortable",
        "font_point_size": 18.0,
        "data_font_point_size": 16.0,
        "palette": {}
    }));
    ui.frame(Vec::new());
    ui.frame(Vec::new());
    let themed_header_y = ui
        .label_rect("Mesh Editor")
        .ok_or("themed Mesh Editor")?
        .center()
        .y;
    let themed_finish_y = ui
        .label_rect("Finish Edit Mesh")
        .ok_or("Finish Edit Mesh was clipped by the large comfortable theme")?
        .center()
        .y;
    assert!((themed_finish_y - themed_header_y).abs() < 8.0);
    let themed_controls_y = ui
        .label_rect("Clear Selection")
        .ok_or("Clear Selection was clipped by the large comfortable theme")?
        .center()
        .y;
    let themed_history_y = ui
        .label_rect("History")
        .ok_or("History was clipped by the large comfortable theme")?
        .center()
        .y;
    assert!((themed_history_y - themed_controls_y).abs() < 8.0);
    assert!(
        themed_controls_y > themed_header_y + 8.0,
        "large themed controls should use the readable two-row fallback"
    );
    Ok(())
}

#[test]
fn integrated_selection_display_camera_history_and_output_controls_change_real_state_or_route()
-> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_440.0, 980.0),
    );
    ui.click("Select")?;

    for (label, expected) in [
        ("Edge", SelectionDomain::Edge),
        ("Face", SelectionDomain::Face),
        ("Vertex", SelectionDomain::Vertex),
    ] {
        ui.click(label)?;
        assert_eq!(ui.application.selection_domain, expected);
    }
    for (current, next, expected) in [
        ("Click", "Brush", SelectionTool::Brush),
        ("Brush", "Rectangle", SelectionTool::Rectangle),
        ("Rectangle", "Lasso", SelectionTool::Lasso),
        ("Lasso", "Click", SelectionTool::Click),
    ] {
        ui.choose("Shape", current, next)?;
        assert_eq!(ui.application.selection_tool, expected);
    }
    for (current, next, expected) in [
        ("Replace", "Add", SelectionOperation::Add),
        ("Add", "Subtract", SelectionOperation::Subtract),
        ("Subtract", "Toggle", SelectionOperation::Toggle),
        ("Toggle", "Replace", SelectionOperation::Replace),
    ] {
        ui.choose("Operation", current, next)?;
        assert_eq!(ui.application.selection_operation, expected);
    }
    ui.click("X-Ray")?;
    assert!(!ui.application.selection_visible_only);
    let viewport = ui.application.viewport_rect.ok_or("viewport")?;
    ui.click_where("Visible", |rectangle| {
        rectangle.center().x < viewport.left()
    })?;
    assert!(ui.application.selection_visible_only);

    ui.application.cdmw_textured_mode_available = true;
    ui.application.cdmw_textured_mode_reason.clear();
    ui.frame(Vec::new());
    for (current, next, expected) in [
        ("Faces (No Textures)", "Faces + Wire", ViewMode::SolidWire),
        ("Faces + Wire", "Wire", ViewMode::Wireframe),
        ("Wire", "Vertices", ViewMode::Vertices),
        ("Vertices", "Wire + Vertices", ViewMode::WireVertices),
        ("Wire + Vertices", "X-Ray", ViewMode::XRay),
        ("X-Ray", "Solid (Textured)", ViewMode::TexturedSolid),
    ] {
        ui.choose("Display", current, next)?;
        assert_eq!(ui.application.view_mode, expected);
    }
    ui.click("Normals")?;
    ui.click("Bounds")?;
    ui.click("Screen grid (overlay)")?;
    assert!(ui.application.show_normals);
    assert!(ui.application.show_bounds);
    assert!(ui.application.egui_context.data_mut(|data| {
        data.get_temp::<bool>(egui::Id::new("cdmw_screen_grid_visible"))
            .unwrap_or(false)
    }));

    ui.application.overlay_wire_width = 5.0;
    ui.application.overlay_vertex_size = 8.0;
    ui.application.deformation_heatmap_enabled = false;
    ui.click("Overlay appearance")?;
    ui.click("Reset appearance")?;
    assert_eq!(ui.application.overlay_wire_width, 1.2);
    assert_eq!(ui.application.overlay_vertex_size, 2.5);
    assert!(ui.application.deformation_heatmap_enabled);

    let mut camera_revision = ui.application.camera.revision();
    for label in ["Front", "Back", "Top", "Left", "Right", "Bottom"] {
        ui.click(label)?;
        assert!(
            ui.application.camera.revision() > camera_revision,
            "{label}"
        );
        camera_revision = ui.application.camera.revision();
    }
    for label in ["Yaw -15°", "Yaw +15°", "Fit"] {
        ui.click(label)?;
        assert!(
            ui.application.camera.revision() > camera_revision,
            "{label}"
        );
        camera_revision = ui.application.camera.revision();
    }
    ui.click("Orbit")?;
    assert!(ui.application.cdmw_orbit_mode);
    assert!(ui.application.cdmw_rail_page.is_none());

    ui.application.cdmw_state["undo_count"] = json!(1);
    ui.application.cdmw_state["redo_count"] = json!(1);
    ui.application.cdmw_state["history_cursor"] = json!(1);
    ui.application.cdmw_state["history_entries"] = json!(["Move", "Inflate"]);
    ui.frame(Vec::new());
    assert!(
        ui.actions_from_click("Undo")?
            .iter()
            .any(|action| matches!(action, UiAction::Undo))
    );
    assert!(
        ui.actions_from_click("Redo")?
            .iter()
            .any(|action| matches!(action, UiAction::Redo))
    );
    assert!(ui.reveal("● Move").is_ok());
    assert!(ui.reveal("○ Inflate").is_ok());

    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    ui.application.cdmw_state["output_destination_ready"] = json!(true);
    ui.frame(Vec::new());
    assert!(has_host_command(
        &ui.actions_from_click("Export Free Edit Package")?,
        "export_free_edit"
    ));
    assert!(has_host_command(
        &ui.actions_from_click("Exact")?,
        "configure_output_policy"
    ));

    ui.application.cdmw_host_connected = true;
    ui.frame(Vec::new());
    let finish = ui.actions_from_click("Finish Edit Mesh")?;
    assert!(
        finish
            .iter()
            .any(|action| matches!(action, UiAction::FinishCdmw))
    );
    Ok(())
}

#[test]
fn integrated_overlay_colours_normal_preview_and_uv_checker_have_perceptible_state() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_360.0, 940.0),
    );

    ui.application.overlay_wire_colour = Color32::from_rgb(255, 220, 0);
    ui.application.overlay_vertex_colour = Color32::from_rgb(12, 34, 56);
    assert_eq!(
        renderer_colour(ui.application.overlay_wire_colour),
        [1.0, 220.0 / 255.0, 0.0, 1.0]
    );
    assert_eq!(
        renderer_colour(ui.application.overlay_vertex_colour),
        [12.0 / 255.0, 34.0 / 255.0, 56.0 / 255.0, 1.0]
    );

    ui.click("Select All")?;
    ui.click("Normals & Tangents")?;
    ui.application.show_normals = false;
    ui.click("Recalculate Normals")?;
    assert!(ui.application.show_normals);
    ui.application.cdmw_normals_feedback =
        Some("Recalculate Normals made no change: normals already match".to_owned());
    ui.frame(Vec::new());
    ui.reveal("Result: Recalculate Normals made no change: normals already match")?;

    ui.click("UV")?;
    ui.click("Show UV Checker")?;
    assert_eq!(ui.application.view_mode, ViewMode::UvChecker);
    ui.application.cdmw_uv_feedback = Some("Move UV completed · shadow revision 3".to_owned());
    ui.frame(Vec::new());
    ui.reveal("Result: Move UV completed · shadow revision 3")?;
    Ok(())
}

#[test]
fn integrated_rotate_scale_and_numeric_controls_are_real_undoable_edits() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_280.0, 900.0),
    );
    ui.click("Select All")?;
    let baseline = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();

    ui.click("Rotate")?;
    assert_eq!(ui.application.viewport_tool, ViewportTool::Rotate);
    ui.click("Rotate X")?;
    let rotated = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();
    assert_ne!(baseline, rotated);

    ui.click("Scale")?;
    assert_eq!(ui.application.viewport_tool, ViewportTool::Scale);
    ui.click("Scale Uniform")?;
    let scaled = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();
    assert_ne!(rotated, scaled);
    assert_eq!(ui.application.history.undo_len(), 3);
    ui.application.mesh.as_ref().ok_or("mesh")?.validate()?;
    Ok(())
}

#[test]
fn integrated_blender_lite_pages_dispatch_typed_mesh_and_weight_commands() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_360.0, 940.0),
    );
    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    ui.application.cdmw_state["skeleton"] = json!({
        "skinned": true,
        "source_weights_available": true,
        "weighted_vertex_count": 3,
        "unnormalized_vertex_count": 1,
        "selected_bone_index": 0,
        "weight_edit_capability": {"enabled": true, "reason": "", "exact_pac_only": true, "eligible_submesh_indices": [0], "palette_size": 1},
        "bones": [{"index": 0, "name": "Root", "parent_index": -1}]
    });
    ui.click("Select All")?;

    ui.click("Cleanup")?;
    ui.click("Remove Doubles")?;
    assert!(ui.last_actions.iter().any(|action| matches!(
        action,
        UiAction::CdmwMeshAction {
            action: "remove_doubles",
            ..
        }
    )));

    ui.click("Normals & Tangents")?;
    ui.click("Recalculate Normals")?;
    assert!(ui.last_actions.iter().any(|action| matches!(
        action,
        UiAction::CdmwMeshAction {
            action: "recalculate_normals",
            ..
        }
    )));

    ui.click("UV")?;
    ui.click("Planar Project")?;
    assert!(ui.last_actions.iter().any(|action| matches!(
        action,
        UiAction::CdmwMeshAction {
            action: "uv_transform",
            params,
            ..
        } if params.get("projection").and_then(Value::as_str) == Some("planar")
    )));

    ui.open_retained_rig_page();
    ui.click("Weight +")?;
    assert!(ui.last_actions.iter().any(|action| matches!(
        action,
        UiAction::CdmwCommand {
            command: "rig_adjust_weight",
            arguments,
            ..
        } if arguments.get("delta").and_then(Value::as_f64).is_some_and(|value| value > 0.0)
    )));
    Ok(())
}

#[test]
fn integrated_cleanup_normals_and_uv_controls_all_dispatch_their_typed_actions() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_440.0, 980.0),
    );
    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    ui.click("Select All")?;

    ui.click("Cleanup")?;
    for (label, expected) in [
        ("Remove Doubles", "remove_doubles"),
        ("Delete Loose Vertices", "delete_loose_vertices"),
        ("Compact Orphans", "compact_orphans"),
        ("Repair Winding", "fix_winding"),
        ("Fill Holes", "fill_holes"),
        ("Mirror X", "mirror"),
        ("Mirror Y", "mirror"),
        ("Mirror Z", "mirror"),
    ] {
        let actions = ui.actions_from_click(label)?;
        assert!(
            has_mesh_action(&actions, expected),
            "{label} did not dispatch {expected}: {actions:?}"
        );
    }

    ui.click("Normals & Tangents")?;
    for (label, expected) in [
        ("Recalculate Normals", "recalculate_normals"),
        ("Generate Tangents", "generate_tangents"),
        ("Flip Normals", "flip_normals"),
        ("Sharpen Normals", "sharpen_normals"),
        ("Soften Normals", "soften_normals"),
        ("Weighted Normals", "weighted_normals"),
        ("Copy Source Normals", "copy_normals"),
    ] {
        let actions = ui.actions_from_click(label)?;
        assert!(
            has_mesh_action(&actions, expected),
            "{label} did not dispatch {expected}: {actions:?}"
        );
    }

    ui.click("UV")?;
    for label in [
        "U-",
        "U+",
        "V-",
        "V+",
        "Scale UV",
        "Flip U",
        "Flip V",
        "Rotate 90°",
        "Normalize Island",
        "Normalize to 0-1",
        "Align U",
        "Align V",
        "Planar Project",
        "Box Project",
        "Cylindrical Project",
        "Auto Unwrap",
        "Pack Islands",
        "Snap to Grid",
    ] {
        let actions = ui.actions_from_click(label)?;
        assert!(
            has_mesh_action(&actions, "uv_transform"),
            "{label} did not dispatch uv_transform: {actions:?}"
        );
    }
    ui.application.cdmw_uv_pixel_width = 2_048;
    ui.application.cdmw_uv_pixel_height = 1_024;
    let pixel_snap = ui.actions_from_click("Snap Pixels")?;
    assert!(pixel_snap.iter().any(|action| matches!(
        action,
        UiAction::CdmwMeshAction {
            action: "uv_transform",
            params,
            ..
        } if params.get("texture_size") == Some(&json!([2048, 1024]))
    )));
    Ok(())
}

#[test]
fn integrated_every_topology_button_dispatches_a_supported_typed_action() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_440.0, 980.0),
    );
    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    ui.click("Topology")?;

    for (domain, controls) in [
        (
            SelectionDomain::Vertex,
            vec![
                ("Delete Selection", "delete"),
                ("Duplicate Selection", "duplicate"),
                ("Split", "split"),
                ("Dissolve", "dissolve"),
                ("Merge", "merge"),
                ("Weld", "weld"),
            ],
        ),
        (
            SelectionDomain::Edge,
            vec![
                ("Loop Cut", "loop_cut"),
                ("Edge Split", "edge_split"),
                ("Bridge", "bridge"),
                ("Fill", "fill"),
                ("Extrude Edges", "extrude"),
            ],
        ),
        (
            SelectionDomain::Face,
            vec![
                ("Subdivide", "subdivide"),
                ("Refine Smooth", "refine_smooth"),
                ("Separate", "separate"),
                ("Extrude Faces", "extrude"),
                ("Inset", "inset"),
            ],
        ),
    ] {
        ui.application.selection_domain = domain;
        ui.application.handle_actions(vec![match domain {
            SelectionDomain::Vertex => UiAction::SelectAllVertices,
            SelectionDomain::Edge => UiAction::SelectAllEdges,
            SelectionDomain::Face => UiAction::SelectAllFaces,
        }]);
        ui.frame(Vec::new());
        for (label, expected) in controls {
            let actions = ui.actions_from_click(label)?;
            assert!(
                has_topology_action(&actions, expected),
                "{label} did not dispatch {expected}: {actions:?}"
            );
        }
    }

    ui.application.selection_domain = SelectionDomain::Face;
    ui.application
        .handle_actions(vec![UiAction::SelectAllFaces]);
    ui.click("Select")?;
    let actions = ui.actions_from_click("Create Part")?;
    assert!(has_topology_action(&actions, "separate"));
    Ok(())
}

#[test]
fn integrated_rig_weight_commands_bind_the_live_vertex_selection() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_280.0, 900.0),
    );
    ui.click("Select All")?;
    let arguments = ui
        .application
        .cdmw_command_arguments("rig_adjust_weight", json!({"delta": 0.1}))
        .map_err(|_| "rig command arguments")?;
    let selected = arguments
        .get("selection")
        .and_then(|selection| selection.get("vertices_by_submesh"))
        .and_then(|vertices| vertices.get("0"))
        .and_then(Value::as_array)
        .ok_or("rig selection")?;
    assert_eq!(selected.len(), 3);
    assert_eq!(arguments["delta"], json!(0.1));
    Ok(())
}

#[test]
fn integrated_topology_controls_dispatch_the_painted_parameter_values() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_360.0, 940.0),
    );
    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    ui.application.selection_domain = SelectionDomain::Face;
    ui.application.extrude_distance = 0.375;
    ui.application.cdmw_extrude_axis = "x".to_owned();
    ui.click("Select All")?;
    ui.click("Topology")?;
    ui.click("Extrude Faces")?;
    assert!(ui.last_actions.iter().any(|action| matches!(
        action,
        UiAction::CdmwTopology {
            action: "extrude",
            params,
            ..
        } if params.get("offset") == Some(&json!([0.375, 0.0, 0.0]))
    )));

    ui.application.selection_domain = SelectionDomain::Edge;
    ui.application.cdmw_loop_cut_count = 3;
    ui.application.cdmw_loop_cut_factor = 0.25;
    ui.click("Select All")?;
    ui.click("Extrude Edges")?;
    assert!(ui.last_actions.iter().any(|action| matches!(
        action,
        UiAction::CdmwTopology {
            action: "extrude",
            label: "Extrude edges",
            params,
        } if params.get("offset") == Some(&json!([0.375, 0.0, 0.0]))
    )));
    ui.click("Loop Cut")?;
    assert!(ui.last_actions.iter().any(|action| matches!(
        action,
        UiAction::CdmwTopology {
            action: "loop_cut",
            params,
            ..
        } if params.get("cuts") == Some(&json!(3))
            && params.get("factor") == Some(&json!(0.25))
    )));
    Ok(())
}

#[test]
fn integrated_rig_controls_require_explicit_vertices_and_can_restore_source_weights() -> TestResult
{
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_360.0, 940.0),
    );
    ui.application.cdmw_state["skeleton"] = json!({
        "skinned": true,
        "source_weights_available": true,
        "weighted_vertex_count": 3,
        "selected_bone_index": 0,
        "weight_edit_capability": {"enabled": true, "reason": "", "exact_pac_only": true, "eligible_submesh_indices": [0], "palette_size": 1},
        "bones": [{"index": 0, "name": "Root", "parent_index": -1}]
    });
    ui.application.selection_domain = SelectionDomain::Edge;
    ui.click("Select All")?;
    assert!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .selection
            .vertices
            .is_empty()
    );
    ui.open_retained_rig_page();
    ui.last_actions.clear();
    ui.click("Weight +")?;
    assert!(!ui.last_actions.iter().any(|action| matches!(
        action,
        UiAction::CdmwCommand {
            command: "rig_adjust_weight",
            ..
        }
    )));

    ui.application.cdmw_state["skeleton"]["skinned"] = json!(false);
    ui.application.selection_domain = SelectionDomain::Vertex;
    ui.click("Select All")?;
    ui.last_actions.clear();
    ui.click("Transfer from Original")?;
    assert!(ui.last_actions.iter().any(|action| matches!(
        action,
        UiAction::CdmwCommand {
            command: "rig_transfer_weights",
            ..
        }
    )));
    Ok(())
}

#[test]
fn integrated_weight_controls_follow_the_host_output_capability() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_360.0, 940.0),
    );
    ui.application.cdmw_state["skeleton"] = json!({
        "skinned": true,
        "source_weights_available": true,
        "weighted_vertex_count": 3,
        "selected_bone_index": 0,
        "weight_edit_capability": {
            "enabled": false,
            "reason": "Skin weights require an exact PAC LOD0 output route.",
            "exact_pac_only": true,
            "eligible_submesh_indices": [],
            "palette_size": 0
        },
        "bones": [{"index": 0, "name": "Root", "parent_index": -1}]
    });
    ui.click("Select All")?;
    ui.open_retained_rig_page();
    ui.reveal("No named rig attached")?;
    ui.reveal("Skin weights require an exact PAC LOD0 output route.")?;
    ui.last_actions.clear();
    ui.click("Weight +")?;
    assert!(ui.last_actions.is_empty());

    ui.application.cdmw_state["skeleton"]["weight_edit_capability"] = json!({
        "enabled": true,
        "reason": "",
        "exact_pac_only": true,
        "eligible_submesh_indices": [1],
        "palette_size": 2
    });
    ui.frame(Vec::new());
    ui.reveal(
        "The explicit selection includes vertices or Parts outside the exact-safe skin-weight subset",
    )?;
    ui.last_actions.clear();
    ui.click("Weight +")?;
    assert!(ui.last_actions.is_empty());

    ui.application.cdmw_state["skeleton"]["weight_edit_capability"] = json!({
        "enabled": true,
        "reason": "",
        "exact_pac_only": true,
        "eligible_submesh_indices": [0],
        "palette_size": 2
    });
    ui.frame(Vec::new());
    ui.reveal("Weight editing ready")?;
    ui.last_actions.clear();
    ui.click("Weight +")?;
    assert!(ui.last_actions.iter().any(|action| matches!(
        action,
        UiAction::CdmwCommand {
            command: "rig_adjust_weight",
            ..
        }
    )));
    Ok(())
}

#[test]
fn integrated_bone_overlay_requires_complete_hierarchy_and_paints_selected_weights() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_360.0, 940.0),
    );
    ui.application.cdmw_state["skeleton"] = json!({
        "available": true,
        "skinned": true,
        "source_weights_available": true,
        "weighted_vertex_count": 3,
        "unnormalized_vertex_count": 0,
        "selected_bone_index": 0,
        "bone_count": 2,
        "skeleton_bone_count": 2,
        "bones_truncated": false,
        "skeleton_parse_warning": "",
        "bones": [
            {"index": 0, "name": "Root", "parent_index": -1, "position": [0.0, 0.0, 0.0]},
            {"index": 1, "name": "Spine", "parent_index": 0, "position": [0.0, 1.0, 0.0]}
        ],
        "selected_weights_truncated": false,
        "selected_vertex_weights": [{
            "submesh_index": 0,
            "vertex_index": 2,
            "influences": [[0, 0.75], [1, 0.25]],
            "selected_bone_weight": 0.75,
            "total_weight": 1.0,
            "invalid": false
        }]
    });
    ui.application.refresh_cdmw_skeleton_overlay();
    assert_eq!(ui.application.skeleton_overlay_lines.len(), 2);
    ui.click("Bones")?;
    assert!(ui.application.show_bones);
    let state = ui.application.cdmw_state.clone();
    let mut document = ui.application.document.clone().ok_or("document")?;
    document.lods[0].submeshes[0].positions[0][0] += 0.2;
    ui.application
        .install_validated_cdmw_state(state, Some(document))?;
    assert!(
        ui.application.show_bones,
        "a geometry result must preserve the Bones toggle"
    );
    assert_eq!(ui.application.skeleton_overlay_lines.len(), 2);
    let selection_revision = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .selection_revision;
    let mut state = ui.application.cdmw_state.clone();
    state["skeleton"]["selected_bone_index"] = json!(1);
    ui.application.install_validated_cdmw_state(state, None)?;
    assert!(ui.application.show_bones);
    assert_eq!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .selection_revision,
        selection_revision
    );
    ui.open_retained_rig_page();
    ui.click("Selected vertex weights")?;
    ui.reveal("SM 0 · V 2 · Root 0.750, Spine 0.250 · Σ 1.000")?;

    ui.application.cdmw_state["skeleton"]["selected_vertex_weights"] = json!([{
        "submesh_index": 0,
        "vertex_index": 2,
        "influences": [],
        "influences_resolved": false,
        "influence_slots": [[3, 0.75], [7, 0.25]],
        "influence_labels": [["Slot 3", 0.75], ["Slot 7", 0.25]],
        "selected_bone_weight": 0.0,
        "total_weight": 1.0,
        "invalid": false
    }]);
    ui.frame(Vec::new());
    ui.reveal("SM 0 · V 2 · Slot 3 0.750, Slot 7 0.250 · Σ 1.000")?;
    assert!(
        ui.label_rect("SM 0 · V 2 · Bone 3 0.750, Bone 7 0.250 · Σ 1.000")
            .is_none()
    );

    ui.application.cdmw_state["skeleton"]["bones_truncated"] = json!(true);
    ui.application.refresh_cdmw_skeleton_overlay();
    ui.frame(Vec::new());
    assert!(ui.application.skeleton_overlay_lines.is_empty());
    assert!(!ui.application.show_bones);
    assert!(
        ui.application
            .cdmw_skeleton_overlay_reason
            .contains("truncated")
    );
    Ok(())
}

#[test]
fn integrated_geometry_layer_visibility_dispatches_the_typed_host_command() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_360.0, 940.0),
    );
    ui.application.cdmw_state["geometry_layers"] = json!({
        "revision": 4,
        "active_layer_id": "detail",
        "clipboard_ready": false,
        "layers": [
            {"layer_id": "base", "name": "Base", "submesh_indices": [0], "visible": true, "base": true},
            {"layer_id": "detail", "name": "Detail", "submesh_indices": [], "visible": true, "base": false}
        ]
    });
    ui.frame(Vec::new());
    let viewport = ui.application.viewport_rect.ok_or("viewport")?;
    let visibility = ui
        .label_rect_where("Visible", |rectangle| {
            rectangle.center().x > viewport.right()
        })
        .ok_or("geometry layer visibility control")?;
    ui.click_at(visibility.center());
    assert!(ui.last_actions.iter().any(|action| matches!(
        action,
        UiAction::CdmwCommand {
            command: "layer_visibility",
            arguments,
            label: "Hide geometry layer",
        } if arguments == &json!({"layer_id": "detail", "visible": false})
    )));
    Ok(())
}

#[test]
fn integrated_exact_cleanup_and_layer_locks_show_actionable_reasons_then_enable_in_free_edit()
-> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_440.0, 980.0),
    );

    ui.click("Cleanup")?;
    ui.reveal(
        "Cleanup is locked by Exact output. Choose Free Edit under Output to allow topology repair.",
    )?;
    assert!(!has_mesh_action(
        &ui.actions_from_click("Remove Doubles")?,
        "remove_doubles"
    ));

    ui.application
        .handle_actions(vec![UiAction::SetPartSelection(vec![0])]);
    ui.frame(Vec::new());
    ui.reveal(
        "Adding geometry needs Free Edit: export a new OBJ package to a folder.",
    )?;
    assert!(!has_host_command(
        &ui.actions_from_click("Copy Selection")?,
        "layer_copy"
    ));

    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    ui.frame(Vec::new());
    ui.reveal("Ready to copy · 0 selected element(s) · 1 selected Part(s)")?;
    assert!(has_host_command(
        &ui.actions_from_click("Copy Selection")?,
        "layer_copy"
    ));

    ui.application.cdmw_state["geometry_layers"]["clipboard_ready"] = json!(true);
    ui.frame(Vec::new());
    assert!(has_host_command(
        &ui.actions_from_click("Paste New Layer")?,
        "layer_paste"
    ));
    Ok(())
}

#[test]
fn integrated_geometry_layer_controls_dispatch_and_invalid_empty_copy_or_rename_stay_disabled()
-> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_440.0, 980.0),
    );
    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    ui.application.cdmw_state["geometry_layers"] = json!({
        "revision": 4,
        "active_layer_id": "detail",
        "clipboard_ready": true,
        "layers": [
            {"layer_id": "base", "name": "Base", "submesh_indices": [0], "visible": true, "base": true},
            {"layer_id": "detail", "name": "Detail", "submesh_indices": [0], "visible": true, "base": false},
            {"layer_id": "detail-2", "name": "Detail Two", "submesh_indices": [], "visible": true, "base": false}
        ]
    });
    ui.frame(Vec::new());
    let viewport = ui.application.viewport_rect.ok_or("viewport")?;

    ui.last_actions.clear();
    ui.click_where("Detail Two", |rectangle| {
        rectangle.center().x > viewport.right()
    })?;
    assert!(has_host_command(&ui.last_actions, "layer_activate"));

    ui.last_actions.clear();
    let detail = ui
        .label_rect_where("Detail", |rectangle| {
            rectangle.center().x > viewport.right()
        })
        .ok_or("detail layer row")?;
    ui.click_where("Visible", |rectangle| {
        rectangle.center().x > viewport.right()
            && (rectangle.center().y - detail.center().y).abs() < detail.height()
    })?;
    assert!(has_host_command(&ui.last_actions, "layer_visibility"));

    ui.last_actions.clear();
    ui.click_where("Paste New Layer", |rectangle| {
        rectangle.center().x > viewport.right()
    })?;
    assert!(has_host_command(&ui.last_actions, "layer_paste"));

    for (label, command) in [
        ("Rename", "layer_rename"),
        ("Up", "layer_move"),
        ("Down", "layer_move"),
        ("Delete", "layer_delete"),
    ] {
        ui.last_actions.clear();
        ui.click_where(label, |rectangle| rectangle.center().x > viewport.right())?;
        assert!(
            has_host_command(&ui.last_actions, command),
            "{label} did not dispatch {command}: {:?}",
            ui.last_actions
        );
    }

    ui.last_actions.clear();
    ui.click_where("Copy Selection", |rectangle| {
        rectangle.center().x > viewport.right()
    })?;
    assert!(
        ui.last_actions.is_empty(),
        "Copy must stay disabled until an explicit mesh or Part selection exists"
    );

    ui.application.selection_domain = SelectionDomain::Face;
    ui.application
        .handle_actions(vec![UiAction::SelectAllFaces]);
    ui.frame(Vec::new());
    ui.last_actions.clear();
    ui.click_where("Copy Selection", |rectangle| {
        rectangle.center().x > viewport.right()
    })?;
    assert!(has_host_command(&ui.last_actions, "layer_copy"));

    ui.application.cdmw_layer_name.clear();
    ui.frame(Vec::new());
    ui.last_actions.clear();
    ui.click_where("Rename", |rectangle| {
        rectangle.center().x > viewport.right()
    })?;
    assert!(
        ui.last_actions.is_empty(),
        "Rename must stay disabled until the new name is non-empty"
    );
    Ok(())
}

#[test]
fn integrated_morph_part_picker_shows_all_rows_without_nested_scrolling() -> TestResult {
    let mut app = triangle_application()?;
    let document = app.document.as_mut().ok_or("document")?;
    let part = document.lods[0].submeshes[0].clone();
    document.lods[0].submeshes = (0..6)
        .map(|index| {
            let mut part = part.clone();
            part.name =
                format!("cd_phm_00_body_part_{index:02}_a_very_long_mesh_and_material_identifier");
            part
        })
        .collect();
    let names = document.lods[0]
        .submeshes
        .iter()
        .enumerate()
        .map(|(index, part)| format!("{} · {}", index + 1, part.name))
        .collect::<Vec<_>>();
    app.mesh = Some(WorkingMesh::from_document(document)?);
    let mut ui = HeadlessUi::new_integrated_cdmw(app, egui::vec2(1440.0, 980.0));
    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    ui.application.cdmw_state["geometry_layers"]["layers"][0]["submesh_indices"] =
        json!([0, 1, 2, 3, 4, 5]);
    ui.click("Morph & Refit")?;
    ui.click("Meshes & selection")?;
    ui.click("Choose Parts")?;
    for _ in 0..16 {
        ui.frame(Vec::new());
    }
    let right = ui.application.viewport_rect.ok_or("viewport")?.left();
    for name in &names {
        let row = ui
            .label_rect(name)
            .ok_or_else(|| format!("Part row needs scrolling: {name}"))?;
        assert!(row.right() <= right, "Part row exceeds the rail: {row:?}");
        assert!(
            row.height()
                <= ui
                    .application
                    .egui_context
                    .style_of(ui.application.egui_context.theme())
                    .spacing
                    .interact_size
                    .y
                    + 4.0,
            "Part row wraps to multiple lines: {row:?}"
        );
    }
    ui.click(&names[5])?;
    assert_eq!(ui.application.selected_part_indices(), vec![5]);
    Ok(())
}

#[test]
fn integrated_sections_start_closed_and_morph_selection_returns_to_saved_sections() -> TestResult {
    let mut ui =
        HeadlessUi::new_integrated_cdmw(two_part_application()?, egui::vec2(1440.0, 980.0));
    for hidden in [
        "Display",
        "Select",
        "Move",
        "Visibility",
        "Add as Body...",
        "Deform",
        "Game / Mod output",
    ] {
        assert!(
            ui.label_rect(hidden).is_none(),
            "initial section exposed {hidden}"
        );
    }
    ui.click("Morph & Refit")?;
    for section in [
        "Meshes & selection",
        "Profiles & presets",
        "Shape sliders",
        "Create / edit sliders",
        "Refit clothing & armor",
    ] {
        ui.reveal(section)?;
    }
    assert!(ui.label_rect("Add as Body...").is_none());
    ui.click("Meshes & selection")?;
    assert!(ui.label_rect("Enable Free Edit...").is_none());
    assert!(has_host_command(
        &ui.actions_from_click("Set as body")?,
        "refit_set_driver"
    ));
    ui.click("Choose Parts")?;
    ui.click("2 · Part B")?;
    assert_eq!(ui.application.selected_part_indices(), vec![1]);
    ui.frame(Vec::new());
    ui.reveal("2 · Part B")?;
    assert!(ui.label_rect("Adding meshes requires Free Edit.").is_none());
    assert!(ui.actions_from_click("Add as Armor...")?.iter().any(
        |action| matches!(action, UiAction::ChooseCdmwRefitMesh { role } if *role == "armor")
    ));
    ui.click("Open Selection tool")?;
    assert_eq!(ui.application.cdmw_rail_page, Some(CdmwRailPage::Select));
    assert_eq!(ui.application.viewport_tool, ViewportTool::Select);
    assert!(!ui.application.cdmw_orbit_mode);
    ui.reveal("Shape")?;
    ui.click_tool_button("Morph & Refit")?;
    ui.reveal("Add as Armor...")?;
    ui.reveal("2 · Part B")?;
    assert!(
        ui.label_rect("Load Preset...").is_none(),
        "closed preset section reopened"
    );
    assert!(ui.label_rect("Pick region").is_none());
    assert!(ui.label_rect("Frame scope").is_none());
    assert_eq!(ui.application.selected_part_indices(), vec![1]);
    ui.click_tool_button("Morph & Refit")?;
    ui.click_tool_button("Morph & Refit")?;
    ui.reveal("2 · Part B")?;
    Ok(())
}

#[test]
fn integrated_tool_buttons_toggle_and_sections_collapse_without_geometry_changes() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1440.0, 980.0),
    );
    let before = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .vertices()
        .map(|(_, v)| v.position)
        .collect::<Vec<_>>();
    assert!(ui.label_rect("Rig & Weights").is_none());
    for (label, page) in [
        ("Select", CdmwRailPage::Select),
        ("Move", CdmwRailPage::Move),
        ("Rotate", CdmwRailPage::Rotate),
        ("Scale", CdmwRailPage::Scale),
        ("Grab", CdmwRailPage::Grab),
        ("Smooth", CdmwRailPage::Smooth),
        ("Inflate", CdmwRailPage::Inflate),
        ("Pinch", CdmwRailPage::Pinch),
        ("Topology", CdmwRailPage::Topology),
        ("Cleanup", CdmwRailPage::Cleanup),
        ("Normals & Tangents", CdmwRailPage::Normals),
        ("UV", CdmwRailPage::Uv),
        ("Morph & Refit", CdmwRailPage::MorphRefit),
    ] {
        ui.click_tool_button(label)?;
        assert_eq!(ui.application.cdmw_rail_page, Some(page));
        ui.click_tool_button(label)?;
        assert_eq!(ui.application.cdmw_rail_page, None, "{label}");
        assert!(ui.application.cdmw_orbit_mode);
    }
    for (heading, child) in [
        ("Viewport", "Display"),
        ("Selection", "Select"),
        ("Transform", "Move"),
        ("Sculpt", "Grab"),
        ("Mesh Data", "Topology"),
        ("Parts", "Visibility"),
    ] {
        if heading == "Parts" {
            ui.click(heading)?;
        } else {
            ui.click_tool_button(heading)?;
        }
        for _ in 0..16 {
            ui.frame(Vec::new());
        }
        assert!(
            ui.label_rect(child).is_none(),
            "{heading} did not collapse {child}"
        );
        if heading == "Parts" {
            ui.click(heading)?;
        } else {
            ui.click_tool_button(heading)?;
        }
        ui.reveal(child)?;
    }
    assert_eq!(
        before,
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .vertices()
            .map(|(_, v)| v.position)
            .collect::<Vec<_>>()
    );
    Ok(())
}

#[test]
fn integrated_morph_loaders_selection_and_sections_have_real_actions() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        two_part_application()?,
        egui::vec2(1440.0, 980.0),
    );
    ui.click("Morph & Refit")?;
    ui.click("Meshes & selection")?;
    ui.click("Choose Parts")?;
    ui.click("Profiles & presets")?;
    assert!(ui.label_rect("Enable Free Edit...").is_none());
    ui.frame(Vec::new());
    assert!(
        ui.actions_from_click("Add as Body...")?
            .iter()
            .any(|a| matches!(a, UiAction::ChooseCdmwRefitMesh { role: "body" }))
    );
    assert!(
        ui.actions_from_click("Add as Armor...")?
            .iter()
            .any(|a| matches!(a, UiAction::ChooseCdmwRefitMesh { role: "armor" }))
    );
    assert!(
        ui.actions_from_click("Load Preset...")?
            .iter()
            .any(|a| matches!(a, UiAction::ChooseCdmwMorphPreset { save: false }))
    );
    ui.click("1 · Part A")?;
    assert_eq!(ui.application.selected_part_indices(), vec![0]);
    ui.click("Open Selection tool")?;
    assert_eq!(ui.application.viewport_tool, ViewportTool::Select);
    assert_eq!(ui.application.cdmw_rail_page, Some(CdmwRailPage::Select));
    ui.click_tool_button("Morph & Refit")?;
    ui.application.cdmw_state["morph_refit"]["profile_id"] = json!("body");
    ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(true);
    ui.application.cdmw_state["morph_refit"]["topology_blocked"] = json!(true);
    ui.frame(Vec::new());
    ui.reveal("Fit / shape preview · Reset or Bake when finished.")?;
    assert!(ui.actions_from_click("Add as Armor...")?.is_empty());
    assert!(
        ui.actions_from_click("Export Preset...")?
            .iter()
            .any(|a| matches!(a, UiAction::ChooseCdmwMorphPreset { save: true }))
    );
    ui.click("Refit clothing & armor")?;
    assert!(!has_host_command(
        &ui.actions_from_click("Set body from selection")?,
        "refit_set_driver"
    ));
    ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(false);
    ui.application.cdmw_state["morph_refit"]["driver_submesh_indices"] = json!([0]);
    ui.frame(Vec::new());
    assert!(!has_host_command(
        &ui.actions_from_click("Bind selected garments")?,
        "refit_bind"
    ));
    for heading in [
        "Meshes & selection",
        "Profiles & presets",
        "Shape sliders",
        "Create / edit sliders",
        "Refit clothing & armor",
    ] {
        ui.click(heading)?;
    }
    assert_eq!(
        ui.application.cdmw_rail_page,
        Some(CdmwRailPage::MorphRefit)
    );
    Ok(())
}

#[test]
fn integrated_refit_controls_hydrate_existing_garment_settings_before_apply() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_440.0, 980.0),
    );
    ui.application.cdmw_state["morph_refit"] = json!({
        "profile_id": "owned-profile",
        "state_revision": 7,
        "available_profiles": [["owned-profile", "Owned Profile"]],
        "values": [],
        "driver_submesh_indices": [0],
        "refit": {
            "driver_submesh_indices": [0],
            "garment_submesh_indices": [0],
            "garment_settings": [{
                "submesh_index": 0,
                "enabled": false,
                "intensity_percent": 50.0,
                "mode": "rigid",
                "clearance_percent": 1.25
            }]
        }
    });
    ui.application
        .mesh
        .as_mut()
        .ok_or("mesh")?
        .selection
        .submeshes
        .insert(0);

    ui.click("Morph & Refit")?;
    ui.click("Refit clothing & armor")?;
    ui.frame(Vec::new());
    assert!(!ui.application.cdmw_refit_enabled);
    assert_eq!(ui.application.cdmw_refit_intensity, 50.0);
    assert_eq!(ui.application.cdmw_refit_mode, "rigid");
    assert_eq!(ui.application.cdmw_refit_clearance, 1.25);
    assert!(!ui.application.cdmw_refit_hydration_key.is_empty());

    ui.last_actions.clear();
    ui.click("Apply to Selected Garments")?;
    assert!(ui.last_actions.iter().any(|action| matches!(
        action,
        UiAction::CdmwCommand {
            command: "refit_configure",
            arguments,
            ..
        } if arguments.get("submesh_indices") == Some(&json!([0]))
            && arguments.get("enabled") == Some(&json!(false))
            && arguments.get("intensity_percent") == Some(&json!(50.0))
            && arguments.get("mode") == Some(&json!("rigid"))
            && arguments.get("clearance_percent") == Some(&json!(1.25))
    )));
    Ok(())
}

#[test]
fn integrated_refit_fit_to_body_dispatches_without_body_sliders_or_part_selection() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_440.0, 980.0),
    );
    ui.application.cdmw_state["morph_refit"] = json!({
        "profile_id": "owned-profile",
        "state_revision": 7,
        "available_profiles": [["owned-profile", "Owned Profile"]],
        "values": [],
        "definitions": [],
        "driver_submesh_indices": [0],
        "refit": {"garment_submesh_indices": [1, 2], "garment_settings": []}
    });
    ui.click("Morph & Refit")?;
    ui.click("Refit clothing & armor")?;
    for clearance in [0.0, 1.25] {
        ui.application.cdmw_refit_clearance = clearance;
        ui.application.cdmw_refit_intensity = 0.0;
        ui.application.cdmw_refit_mode = "rigid".to_owned();
        ui.application.cdmw_refit_enabled = false;
        ui.application.cdmw_refit_settings_dirty = true;
        let actions = ui.actions_from_click("Fit to body")?;
        assert!(actions.iter().any(|action| matches!(
            action,
            UiAction::CdmwCommand { command: "refit_configure", arguments, .. }
                if arguments["submesh_indices"] == json!([1, 2])
                    && arguments["enabled"] == json!(true)
                    && arguments["intensity_percent"] == json!(100.0)
                    && arguments["mode"] == json!("surface")
                    && (arguments["clearance_percent"].as_f64().unwrap_or(0.0)
                        - f64::from(clearance.max(0.1))).abs() < 1.0e-6
        )));
        assert_eq!(ui.application.cdmw_refit_clearance, clearance.max(0.1));
    }
    Ok(())
}

#[test]
fn integrated_refit_selects_loaded_garments_before_they_are_bound() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        two_part_application()?,
        egui::vec2(1440.0, 980.0),
    );
    ui.application.cdmw_state["morph_refit"] = json!({
        "profile_id": "body", "driver_submesh_indices": [0],
        "refit": {"garment_submesh_indices": []},
    });
    ui.click("Morph & Refit")?;
    ui.click("Meshes & selection")?;
    assert!(ui.label_rect("Use loaded mesh as body").is_none());
    assert!(
        ui.reveal("MIXED")
            .is_ok()
    );
    ui.click("Meshes & selection")?;
    ui.click("Refit clothing & armor")?;
    ui.click("Select garments")?;
    assert_eq!(ui.application.selected_part_indices(), vec![1]);
    assert!(has_host_command(
        &ui.actions_from_click("Bind selected garments")?,
        "refit_bind",
    ));
    ui.click("Select body")?;
    assert_eq!(ui.application.selected_part_indices(), vec![0]);
    assert!(!has_host_command(
        &ui.actions_from_click("Bind selected garments")?,
        "refit_bind",
    ));
    Ok(())
}

#[test]
fn integrated_refit_offers_loading_when_only_the_body_is_present() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1440.0, 980.0),
    );
    ui.application.cdmw_state["morph_refit"] = json!({
        "profile_id": "body", "driver_submesh_indices": [0],
        "refit": {"garment_submesh_indices": []},
    });
    ui.click("Morph & Refit")?;
    ui.click("Refit clothing & armor")?;
    assert!(ui.label_rect("Select garments").is_none());
    assert!(ui.actions_from_click("Load armor...")?.iter().any(
        |action| matches!(action, UiAction::ChooseCdmwRefitMesh { role } if *role == "armor")
    ));
    ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(true);
    ui.frame(Vec::new());
    assert!(ui.actions_from_click("Load armor...")?.is_empty());
    Ok(())
}

#[test]
fn integrated_refit_unassigned_body_does_not_select_every_part_or_show_inert_settings() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        two_part_application()?, egui::vec2(1440.0, 980.0),
    );
    ui.application.cdmw_state["morph_refit"] = json!({
        "profile_id": "existing", "driver_submesh_indices": [],
        "refit": {"garment_submesh_indices": []},
    });
    ui.application.cdmw_state["archive_refit_assets"] = json!([
        {"path": "body.pac", "role": "loaded", "part_indices": [0]},
        {"path": "coat.pac", "role": "armor", "part_indices": [1]},
    ]);
    ui.click("Morph & Refit")?;
    ui.click("Refit clothing & armor")?;
    let selection = ui.application.selected_part_indices();
    ui.click("Select garments")?;
    assert_eq!(ui.application.selected_part_indices(), selection);
    assert!(ui.label_rect("Refit enabled").is_none());
    ui.reveal("Next: set a body in Meshes & selection.")?;
    ui.click("Meshes & selection")?;
    ui.reveal("body.pac")?;
    let armor_name = ui.label_rect("coat.pac").ok_or("missing armor asset")?;
    let button = ui.label_rect_where("Set as body", |rect| rect.bottom() < armor_name.top())
        .ok_or("missing body asset assignment")?;
    ui.click_at(button.center());
    assert!(ui.last_actions.iter().any(|action| matches!(action,
        UiAction::CdmwCommand {command: "refit_set_driver", arguments, ..}
        if arguments.get("submesh_indices") == Some(&json!([0]))
    )));
    Ok(())
}

#[test]
fn integrated_archive_refit_free_edit_is_blocked_before_the_folder_picker() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        two_part_application()?, egui::vec2(1440.0, 980.0),
    );
    ui.application.cdmw_state["archive_refit_assets"] = json!([
        {"path": "body.pac", "role": "loaded", "part_indices": [0]},
        {"path": "coat.pac", "role": "armor", "part_indices": [1]},
    ]);
    ui.click("Display")?;
    assert!(!ui.actions_from_click("Free Edit")?.iter().any(
        |action| matches!(action, UiAction::ChooseCdmwFreeEdit)
    ));
    // A direct action route also returns before opening a native folder dialog.
    ui.application.choose_cdmw_free_edit();
    assert!(ui.application.status.contains("Archive Refit"));
    ui.reveal("Archive Refit · fixed geometry")?;
    assert!(ui.actions_from_click("Copy Selection")?.is_empty());
    Ok(())
}

#[test]
fn integrated_refit_create_body_slider_selects_the_driver_and_opens_the_creator() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        two_part_application()?, egui::vec2(1440.0, 980.0),
    );
    ui.application.cdmw_state["morph_refit"] = json!({
        "profile_id": "body", "driver_submesh_indices": [0], "definitions": [],
        "refit": {"garment_submesh_indices": [1]},
    });
    ui.application.handle_actions(vec![UiAction::SetPartSelection(vec![1])]);
    ui.click("Morph & Refit")?;
    ui.click("Refit clothing & armor")?;
    ui.click("Create body slider")?;
    assert_eq!(ui.application.selected_part_indices(), vec![0]);
    assert!(
        ui.label_rect("Slider label").is_some(),
        "The creator must scroll into view without manual navigation"
    );
    Ok(())
}

#[test]
fn integrated_refit_apply_never_broadens_an_empty_selection_to_all_garments() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_440.0, 980.0),
    );
    ui.application.cdmw_state["morph_refit"] = json!({
        "profile_id": "owned-profile",
        "state_revision": 7,
        "available_profiles": [["owned-profile", "Owned Profile"]],
        "values": [],
        "driver_submesh_indices": [0],
        "refit": {
            "driver_submesh_indices": [0],
            "garment_submesh_indices": [0],
            "garment_settings": []
        }
    });
    ui.click("Morph & Refit")?;
    ui.click("Refit clothing & armor")?;

    ui.last_actions.clear();
    ui.click("Apply to Selected Garments")?;
    assert!(
        !has_host_command(&ui.last_actions, "refit_configure"),
        "an empty selection must not silently target every bound garment"
    );

    let all = ui.actions_from_click("Apply to All Bound Garments")?;
    assert!(all.iter().any(|action| matches!(
        action,
        UiAction::CdmwCommand {
            command: "refit_configure",
            arguments,
            ..
        } if arguments.get("submesh_indices") == Some(&json!([0]))
    )));
    Ok(())
}

#[test]
fn integrated_morph_refit_controls_all_dispatch_typed_host_commands() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_440.0, 2_000.0),
    );
    ui.application.cdmw_state["morph_refit"] = json!({
        "profile_id": "profile-1",
        "preset_id": "preset-1",
        "state_revision": 7,
        "available_profiles": [
            ["profile-1", "Profile One"],
            ["profile-2", "Profile Two"]
        ],
        "available_presets": [
            ["preset-1", "Preset One"],
            ["preset-2", "Preset Two"]
        ],
        "definitions": [{
            "definition_id": "morph-a",
            "label": "Waist Width",
            "category": "Body",
            "min_percent": -25.0,
            "max_percent": 75.0,
            "default_percent": 10.0,
            "rule": {"kind": "radius", "axis": "x", "amount": 0.25}
        }],
        "values": [["morph-a", 25.0]],
        "unbaked": false,
        "driver_submesh_indices": [0],
        "refit": {
            "driver_submesh_indices": [0],
            "garment_submesh_indices": [0],
            "garment_settings": [{
                "submesh_index": 0,
                "enabled": true,
                "intensity_percent": 100.0,
                "mode": "surface",
                "clearance_percent": 0.0
            }]
        }
    });
    ui.application
        .mesh
        .as_mut()
        .ok_or("mesh")?
        .selection
        .submeshes
        .insert(0);
    ui.click("Morph & Refit")?;
    ui.click("Refit clothing & armor")?;
    ui.click("Profiles & presets")?;
    ui.click("Shape sliders")?;
    ui.reveal("Waist Width")?;
    ui.reveal("Body · 1 Parts")?;
    ui.reveal("Bound · 1 Parts")?;

    ui.click("Create / edit sliders")?;
    ui.application.cdmw_morph_rule = "twist".to_owned();
    ui.application.cdmw_morph_axis = "z".to_owned();
    ui.application.cdmw_morph_amount = 0.35;
    ui.application.cdmw_morph_feather = 4;
    ui.application.cdmw_morph_falloff = "linear".to_owned();
    ui.application.cdmw_morph_mirror_mode = "x".to_owned();
    let create = ui.actions_from_click("Add Slider")?;
    assert!(create.iter().any(|action| matches!(
        action,
        UiAction::CdmwCommand {
            command: "morph_create",
            arguments,
            ..
        } if arguments["definition"]["rule"] == json!("twist")
            && arguments["definition"]["axis"] == json!("z")
            && arguments["definition"]["amount"]
                .as_f64()
                .is_some_and(|value| (value - 0.35).abs() < 1.0e-5)
            && arguments["definition"]["feather"] == json!(4)
            && arguments["definition"]["falloff"] == json!("linear")
            && arguments["definition"]["mirror_mode"] == json!("x")
    )));

    ui.click("Create / edit sliders")?;
    assert!(ui.label_rect("Add Slider").is_none());
    ui.click("Edit slider")?;
    assert_eq!(ui.application.cdmw_morph_definition_edit_id, "morph-a");
    assert_eq!(ui.application.cdmw_morph_definition_label, "Waist Width");
    assert_eq!(ui.application.cdmw_morph_rule, "radius");
    assert_eq!(ui.application.cdmw_morph_axis, "x");
    let update = ui.actions_from_click("Update Slider")?;
    assert!(update.iter().any(|action| matches!(
        action,
        UiAction::CdmwCommand {
            command: "morph_create",
            arguments,
            ..
        } if arguments["definition"]["source_definition_id"] == json!("morph-a")
            && arguments["definition"]["preserve_selection"] == json!(true)
            && arguments["definition"]["category"] == json!("Body")
            && arguments["definition"]["min_percent"] == json!(-25.0)
            && arguments["definition"]["max_percent"] == json!(75.0)
            && arguments["definition"]["default_percent"] == json!(10.0)
    )));
    ui.click("Replace scope with current selection")?;
    let replace_scope = ui.actions_from_click("Update Slider")?;
    assert!(replace_scope.iter().any(|action| matches!(
        action,
        UiAction::CdmwCommand {
            command: "morph_create",
            arguments,
            ..
        } if arguments["definition"]["source_definition_id"] == json!("morph-a")
            && arguments["definition"]["preserve_selection"] == json!(false)
    )));
    let delete = ui.actions_from_click("Delete slider")?;
    assert!(delete.iter().any(|action| matches!(
        action,
        UiAction::CdmwCommand {
            command: "morph_delete_definition",
            arguments,
            ..
        } if arguments.get("definition_id") == Some(&json!("morph-a"))
    )));

    ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(true);
    ui.frame(Vec::new());

    for (label, command) in [
        ("Save Profile", "morph_save_profile"),
        ("Delete Profile", "morph_delete_profile"),
        ("Save Preset", "morph_save_preset"),
        ("Delete Preset", "morph_delete_preset"),
        ("Reset", "morph_reset"),
        ("Bake", "morph_bake"),
        ("Clear Refit", "refit_clear"),
        ("Apply to Selected Garments", "refit_configure"),
        ("Apply to All Bound Garments", "refit_configure"),
    ] {
        let actions = ui.actions_from_click(label)?;
        assert!(
            has_host_command(&actions, command),
            "{label} did not dispatch {command}: {actions:?}"
        );
    }

    ui.last_actions.clear();
    ui.choose("Profile", "Profile One", "Profile Two")?;
    assert!(has_host_command(&ui.last_actions, "morph_activate"));

    ui.last_actions.clear();
    ui.choose("Saved preset", "Preset One", "Preset Two")?;
    assert!(has_host_command(&ui.last_actions, "morph_apply_preset"));

    ui.last_actions.clear();
    assert!(ui.label_rect("Current values").is_none());

    ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(false);
    ui.application.cdmw_state["morph_refit"]["driver_submesh_indices"] = json!([1]);
    ui.application.cdmw_state["morph_refit"]["refit"]["garment_submesh_indices"] = json!([]);
    ui.frame(Vec::new());
    assert!(has_host_command(
        &ui.actions_from_click("Set body from selection")?,
        "refit_set_driver"
    ));
    assert!(has_host_command(
        &ui.actions_from_click("Bind selected garments")?,
        "refit_bind"
    ));
    ui.application.cdmw_morph_preset_name.clear();
    ui.frame(Vec::new());
    let actions = ui.actions_from_click("Save Preset")?;
    assert!(
        actions.is_empty(),
        "Save Preset must stay disabled until its name is non-empty"
    );
    Ok(())
}

#[test]
fn integrated_rig_controls_all_dispatch_and_bind_the_explicit_vertex_selection() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_440.0, 980.0),
    );
    ui.application.cdmw_state["skeleton"] = json!({
        "skinned": true,
        "source_weights_available": true,
        "weighted_vertex_count": 3,
        "selected_bone_index": 0,
        "weight_edit_capability": {
            "enabled": true,
            "reason": "",
            "exact_pac_only": true,
            "eligible_submesh_indices": [0],
            "palette_size": 2
        },
        "bones": [
            {"index": 0, "name": "Root", "parent_index": -1},
            {"index": 1, "name": "Spine", "parent_index": 0}
        ]
    });
    ui.click("Select All")?;
    ui.open_retained_rig_page();

    ui.last_actions.clear();
    ui.choose("Active bone", "0: Root", "1: Spine")?;
    assert!(has_host_command(&ui.last_actions, "rig_select_bone"));

    for (label, command) in [
        ("Weight -", "rig_adjust_weight"),
        ("Weight +", "rig_adjust_weight"),
        ("Normalize Weights", "rig_normalize_weights"),
        ("Transfer from Original", "rig_transfer_weights"),
    ] {
        let actions = ui.actions_from_click(label)?;
        assert!(
            has_host_command(&actions, command),
            "{label} did not dispatch {command}: {actions:?}"
        );
        let arguments = actions.iter().find_map(|action| match action {
            UiAction::CdmwCommand { arguments, .. } => Some(arguments),
            _ => None,
        });
        if command != "rig_select_bone" {
            assert!(
                arguments.is_some_and(|value| value.get("selection").is_none()),
                "the UI action must leave live-selection injection to the shared command router"
            );
        }
    }

    let routed = ui
        .application
        .cdmw_command_arguments("rig_normalize_weights", json!({}))
        .map_err(|error| format!("rig selection routing failed: {error}"))?;
    assert_eq!(
        routed["selection"]["vertices_by_submesh"]["0"]
            .as_array()
            .map(Vec::len),
        Some(3)
    );
    Ok(())
}

#[test]
fn integrated_rig_inspection_links_names_search_frame_weights_and_selection() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1440.0, 980.0),
    );
    ui.application.source_label = "character/model/character_body.pac".to_owned();
    ui.application.cdmw_state["skeleton"] = json!({
        "available": true, "skinned": true, "weighted_vertex_count": 3,
        "source_weights_available": true,
        "weight_edit_capability": {"enabled": true, "reason": "", "palette_size": 3, "eligible_submesh_indices": [0]},
        "skeleton_source": "character/rig/character.pab", "selected_bone_index": 0,
        "bone_count": 3, "skeleton_bone_count": 3, "bones_truncated": false,
        "bones": [
            {"index": 0, "name": "Hip", "parent_index": -1, "position": [0.0, 0.0, 0.0], "child_count": 1},
            {"index": 1, "name": "Thigh", "parent_name": "Hip", "parent_index": 0, "position": [0.5, 0.5, 0.0], "child_count": 1},
            {"index": 2, "name": "Knee", "parent_name": "Thigh", "parent_index": 1, "position": [1.0, 0.0, 0.0], "child_count": 0}
        ],
        "parts": [{"index": 0, "name": "Body", "vertex_count": 3, "weighted_vertex_count": 3, "skinned": true}]
    });
    ui.application.cdmw_state["rig_influence"] = json!({
        "bone_index": 0, "available": true, "reason": "", "vertex_count": 2,
        "parts": [{"submesh_index": 0, "weights": [[0, 0.25], [1, 1.0]]}]
    });
    ui.application.refresh_cdmw_skeleton_overlay();
    let geometry = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .geometry_revision;
    let selection = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .selection
        .clone();
    ui.open_retained_rig_page();
    ui.reveal("character_body.pac")?;
    ui.reveal("Rig loaded")?;
    ui.reveal("character.pab")?;
    ui.reveal("2 influenced vertices · 1 part")?;
    assert_eq!(ui.application.cdmw_rig.positions.len(), 3);
    assert_ne!(
        ui.application.cdmw_rig.colours[0],
        ui.application.cdmw_rig.colours[1]
    );
    assert_eq!(
        ui.application.mesh.as_ref().ok_or("mesh")?.selection,
        selection
    );
    ui.click("Frame influence")?;
    assert_eq!(
        ui.application.mesh.as_ref().ok_or("mesh")?.selection,
        selection
    );
    ui.click("Weight colours")?;
    assert!(ui.application.cdmw_rig.positions.is_empty());
    ui.click("Weight colours")?;
    assert_eq!(ui.application.cdmw_rig.positions.len(), 3);
    ui.click("Skeleton")?;
    assert!(ui.application.show_bones);

    ui.click("0: Hip")?;
    ui.click("Search bones")?;
    ui.frame(vec![Event::Text("knee".to_owned())]);
    assert!(ui.label_rect("1: Thigh").is_none());
    ui.last_actions.clear();
    ui.click("2: Knee")?;
    assert!(has_host_command(&ui.last_actions, "rig_select_bone"));
    ui.application.cdmw_state["skeleton"]["selected_bone_index"] = json!(2);
    ui.application.cdmw_state["rig_influence"]["bone_index"] = json!(2);
    ui.application.refresh_cdmw_skeleton_overlay();
    ui.frame(Vec::new());
    ui.click("Frame bone")?;
    ui.reveal("Knee · Bone 2")?;
    assert_eq!(
        ui.application.mesh.as_ref().ok_or("mesh")?.selection,
        selection
    );
    let button = ui.reveal("Select influenced vertices")?.center();
    ui.frame(vec![Event::PointerMoved(egui::pos2(1.0, 1.0))]);
    let normal = ui.rectangle_fills_at(button);
    ui.frame(vec![Event::PointerMoved(button)]);
    let hovered = ui.rectangle_fills_at(button);
    ui.frame(vec![pointer_button(button, PointerButton::Primary, true)]);
    let pressed = ui.rectangle_fills_at(button);
    assert_ne!(normal, hovered, "influence selection needs hover feedback");
    assert_ne!(
        hovered, pressed,
        "influence selection needs pressed feedback"
    );
    ui.frame(vec![
        Event::PointerMoved(egui::pos2(1.0, 1.0)),
        pointer_button(egui::pos2(1.0, 1.0), PointerButton::Primary, false),
    ]);
    ui.click("Select influenced vertices")?;
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    assert_eq!(mesh.selection.vertices.len(), 2);
    assert!(mesh.selection.submeshes.is_empty());
    assert_eq!(mesh.geometry_revision, geometry);
    assert_eq!(ui.application.selection_domain, SelectionDomain::Vertex);

    let root = tempdir()?;
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(
        root.path().to_path_buf(),
        "rig-hidden-parts",
        1,
        0,
    ));
    ui.application.cdmw_state["geometry_layers"]["layers"][0]["base"] = json!(false);
    ui.application.cdmw_state["geometry_layers"]["layers"][0]["visible"] = json!(false);
    ui.frame(Vec::new());
    assert!(ui.application.cdmw_rig.positions.is_empty());
    assert!(ui.application.rig_influenced_vertices().is_empty());
    ui.reveal("2 influenced vertices are in hidden Parts")?;
    assert!(
        ui.actions_from_click("Select influenced vertices")?
            .is_empty()
    );
    ui.application.cdmw_state["skeleton"]["bones"][2]["position"] = json!([1000.0, 0.0, 0.0]);
    ui.application.refresh_cdmw_skeleton_overlay();
    ui.reveal("Knee · outside view · Frame bone")?;
    Ok(())
}

#[test]
fn integrated_read_only_session_disables_import_and_morph_creation_without_selection() -> TestResult
{
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_360.0, 940.0),
    );
    ui.application.cdmw_state["authoring_enabled"] = json!(false);
    ui.last_actions.clear();
    ui.click("Open Package in CDMW...")?;
    assert!(
        !ui.last_actions
            .iter()
            .any(|action| matches!(action, UiAction::ChooseCdmwImportPackage))
    );

    ui.application.cdmw_state["authoring_enabled"] = json!(true);
    ui.click("Morph & Refit")?;
    ui.click("Create / edit sliders")?;
    ui.last_actions.clear();
    ui.click("Add Slider")?;
    assert!(!ui.last_actions.iter().any(|action| matches!(
        action,
        UiAction::CdmwCommand {
            command: "morph_create",
            ..
        }
    )));
    Ok(())
}

#[test]
fn integrated_parts_delete_routes_explicit_part_deletion_and_import_has_a_typed_route() -> TestResult
{
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        overlapping_parts_application()?,
        egui::vec2(1_440.0, 900.0),
    );
    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    assert!(ui.reveal("Open Package in CDMW...").is_ok());

    ui.click("1: Back")?;
    assert_eq!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .selection
            .submeshes,
        HashSet::from([1])
    );
    let duplicate = ui.reveal("Duplicate")?;
    let part_delete = ui
        .label_rect_where("Delete", |rectangle| {
            (rectangle.center().y - duplicate.center().y).abs() < duplicate.height()
        })
        .ok_or("parts Delete button")?;
    ui.click_at(part_delete.center());
    assert!(ui.last_actions.iter().any(|action| matches!(
        action,
        UiAction::CdmwCommand { command: "topology", arguments, .. }
            if arguments["action"] == "delete"
                && arguments["params"]["delete_parts"] == true
                && arguments["selection"]["source_indices"] == json!([1])
    )));

    let package = Path::new(r"C:\owned\editable-package");
    match cdmw_import_editable_package_action(package) {
        UiAction::CdmwCommand {
            command,
            arguments,
            label,
        } => {
            assert_eq!(command, "import_editable_package");
            assert_eq!(arguments["path"], package.to_string_lossy().as_ref());
            assert_eq!(label, "Import editable package");
        }
        action => panic!("unexpected import action: {action:?}"),
    }
    Ok(())
}

#[test]
fn integrated_part_row_highlights_and_move_changes_only_that_part() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        two_part_application()?,
        egui::vec2(1_440.0, 900.0),
    );
    let stale_part_b_vertex = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .vertices()
        .find_map(|(handle, vertex)| {
            matches!(vertex.provenance, Provenance::Source { submesh: 1, .. }).then_some(handle)
        })
        .ok_or("Part B vertex")?;
    ui.application
        .mesh
        .as_mut()
        .ok_or("mesh")?
        .selection
        .vertices
        .insert(stale_part_b_vertex);

    ui.click("0: Part A")?;
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    assert_eq!(mesh.selection.submeshes, HashSet::from([0]));
    assert!(mesh.selection.vertices.is_empty());
    assert!(mesh.selection.edges.is_empty());
    assert!(mesh.selection.faces.is_empty());
    assert_eq!(ui.application.history.undo_len(), 0);

    let highlighted = &ui
        .application
        .face_selection_overlay
        .as_ref()
        .ok_or("face highlight")?
        .positions;
    let expected = mesh
        .faces()
        .filter(|(_, face)| face.submesh == 0)
        .flat_map(|(_, face)| face.vertices.iter())
        .map(|handle| mesh.vertex(*handle).expect("face vertex").position)
        .collect::<Vec<_>>();
    assert_eq!(
        highlighted, &expected,
        "the selected Part must send only its own faces to the GPU"
    );

    let baseline = mesh
        .vertices()
        .map(|(handle, vertex)| (handle, vertex.position))
        .collect::<HashMap<_, _>>();
    ui.click("Move")?;
    let rectangle = ui.application.viewport_rect.ok_or("viewport")?;
    let pivot = OrbitCamera::selected_center(ui.application.mesh.as_ref().ok_or("mesh")?)
        .ok_or("selected Part pivot")?;
    let center = ui
        .application
        .camera
        .project(pivot, rectangle)
        .ok_or("projected Part pivot")?
        .screen;
    ui.drag(
        &[center, center + Vec2::new(24.0, -9.0)],
        PointerButton::Primary,
    );

    let mesh = ui.application.mesh.as_ref().ok_or("moved mesh")?;
    let mut moved_part_vertices = 0;
    for (handle, vertex) in mesh.vertices() {
        let before = baseline.get(&handle).ok_or("baseline vertex")?;
        match vertex.provenance {
            Provenance::Source { submesh: 0, .. } => {
                assert_ne!(&vertex.position, before);
                moved_part_vertices += 1;
            }
            Provenance::Source { submesh: 1, .. } => assert_eq!(&vertex.position, before),
            Provenance::Source { submesh, .. } => {
                return Err(format!("unexpected part {submesh}").into());
            }
            Provenance::Generated { .. } => return Err("unexpected generated vertex".into()),
        }
    }
    assert_eq!(moved_part_vertices, 3);
    assert_eq!(ui.application.history.undo_len(), 1);
    assert!(!ui.application.status.contains("rolled back"));
    Ok(())
}

#[test]
fn integrated_face_brush_keeps_a_bent_pointer_path_within_one_frame() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1440.0, 900.0),
    );
    ui.application.cdmw_orbit_mode = false;
    ui.application.viewport_tool = ViewportTool::Select;
    ui.application.selection_tool = SelectionTool::Brush;
    ui.application.selection_domain = SelectionDomain::Face;
    ui.application.brush_radius = 4.0;
    let rectangle = ui.application.viewport_rect.ok_or("viewport")?;
    assert!(ui.application.ensure_projection(rectangle));
    let center = ui
        .application
        .projection
        .as_ref()
        .ok_or("projection")?
        .interaction
        .elements
        .iter()
        .find_map(|element| {
            matches!(element.handle, ProjectedHandle::Face(_)).then_some(element.position)
        })
        .ok_or("projected face")?;
    let start = egui::pos2(center.x - 30.0, center.y - 30.0);
    let end = egui::pos2(center.x + 30.0, center.y - 30.0);
    ui.frame(vec![
        Event::PointerMoved(start),
        Event::PointerButton {
            pos: start,
            button: PointerButton::Primary,
            pressed: true,
            modifiers: Default::default(),
        },
        Event::PointerMoved(egui::pos2(center.x, center.y)),
        Event::PointerMoved(end),
        Event::PointerButton {
            pos: end,
            button: PointerButton::Primary,
            pressed: false,
            modifiers: Default::default(),
        },
    ]);
    assert_eq!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .selection
            .faces
            .len(),
        1
    );
    assert_eq!(ui.application.history.undo_len(), 1);
    assert_eq!(
        ui.application
            .face_selection_overlay
            .as_ref()
            .ok_or("highlight")?
            .positions
            .len(),
        3
    );
    Ok(())
}

#[test]
fn integrated_face_highlights_reuse_geometry_when_the_camera_moves() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1440.0, 900.0),
    );
    assert!(
        ui.application.projection.is_none(),
        "navigation must not build a picking index"
    );
    let mesh = ui.application.mesh.as_mut().ok_or("mesh")?;
    mesh.set_selection(Selection {
        faces: mesh.faces().map(|(handle, _)| handle).collect(),
        ..Default::default()
    })?;
    ui.frame(Vec::new());
    let positions = &ui
        .application
        .face_selection_overlay
        .as_ref()
        .ok_or("highlight")?
        .positions;
    assert_eq!(positions.len(), 3);
    let buffer = positions.as_ptr();
    ui.application.camera.orbit(Vec2::new(25.0, 5.0));
    ui.frame(Vec::new());
    assert!(ui.application.projection.is_none());
    assert_eq!(
        ui.application
            .face_selection_overlay
            .as_ref()
            .ok_or("highlight")?
            .positions
            .as_ptr(),
        buffer
    );
    ui.application
        .mesh
        .as_mut()
        .ok_or("mesh")?
        .set_selection(Selection::default())?;
    ui.frame(Vec::new());
    assert!(
        ui.application
            .face_selection_overlay
            .as_ref()
            .ok_or("highlight")?
            .positions
            .is_empty()
    );
    Ok(())
}

#[test]
fn integrated_textured_mode_paints_its_disabled_reason_until_an_owned_upload_succeeds() -> TestResult
{
    let mut missing = triangle_application()?;
    missing.cdmw_texture_package_reason =
        "Archive Browser preview package no longer contains its DDS payload".to_owned();
    missing.record_cdmw_texture_uploads(0, 0, 0, None);
    let ui = HeadlessUi::new_integrated_cdmw_for_controls(missing, egui::vec2(1_440.0, 900.0));
    assert!(
        ui.application
            .cdmw_textured_mode_reason
            .contains("Archive Browser preview package")
    );
    assert!(
        ui.label_rect(&ui.application.cdmw_textured_mode_reason)
            .is_some(),
        "the package-specific texture reason was not painted"
    );

    let mut unavailable = triangle_application()?;
    unavailable.view_mode = ViewMode::TexturedSolid;
    unavailable.record_cdmw_texture_uploads(1, 0, 0, Some("DDS upload validation failed"));
    let ui = HeadlessUi::new_integrated_cdmw_for_controls(unavailable, egui::vec2(1_440.0, 900.0));
    assert_eq!(ui.application.view_mode, ViewMode::Solid);
    assert!(
        ui.label_rect(&ui.application.cdmw_textured_mode_reason)
            .is_some(),
        "the unavailable Textured mode reason was not painted"
    );

    let mut available = triangle_application()?;
    available.view_mode = ViewMode::TexturedSolid;
    available.record_cdmw_texture_uploads(1, 1, 1, None);
    let ui = HeadlessUi::new_integrated_cdmw_for_controls(available, egui::vec2(1_440.0, 900.0));
    assert!(ui.application.cdmw_textured_mode_available);
    assert_eq!(ui.application.view_mode, ViewMode::TexturedSolid);
    assert!(ui.application.cdmw_textured_mode_reason.is_empty());
    Ok(())
}

#[test]
fn integrated_deformation_colours_are_enabled_and_user_toggleable() -> TestResult {
    let application = triangle_application()?;
    let mut ui =
        HeadlessUi::new_integrated_cdmw_for_controls(application, egui::vec2(1_440.0, 900.0));
    assert!(ui.application.deformation_heatmap_enabled);
    ui.click("Persistent edit colours")?;
    assert!(!ui.application.deformation_heatmap_enabled);
    ui.click("Persistent edit colours")?;
    assert!(ui.application.deformation_heatmap_enabled);
    Ok(())
}

#[test]
fn integrated_deformation_colours_keep_the_loaded_baseline_across_strokes_and_toggle() -> TestResult
{
    let application = triangle_application()?;
    let baseline_positions = application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .draw_snapshot()
        .positions;
    let mut ui =
        HeadlessUi::new_integrated_cdmw_for_controls(application, egui::vec2(1_280.0, 900.0));
    ui.click("Inflate")?;
    let point = ui.projected_point(SelectionDomain::Vertex)?;
    let mut previous_fingerprint = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();

    for (stroke_index, offset) in [Vec2::new(14.0, -7.0), Vec2::new(20.0, -10.0)]
        .into_iter()
        .enumerate()
    {
        ui.drag(
            &[point + Vec2::new(5.0, -3.0), point + offset],
            PointerButton::Primary,
        );
        let current_fingerprint = ui
            .application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint();
        assert_ne!(
            current_fingerprint,
            previous_fingerprint,
            "brush stroke {} did not produce a new edit",
            stroke_index + 1
        );
        assert_eq!(ui.application.history.undo_len(), stroke_index + 1);
        previous_fingerprint = current_fingerprint;
        assert_eq!(
            ui.application
                .deformation_reference
                .as_ref()
                .ok_or("deformation reference")?
                .mesh
                .draw_snapshot()
                .positions,
            baseline_positions,
            "a later brush stroke replaced the loaded deformation baseline"
        );
    }

    ui.click("Persistent edit colours")?;
    ui.click("Persistent edit colours")?;
    assert_eq!(
        ui.application
            .deformation_reference
            .as_ref()
            .ok_or("deformation reference")?
            .mesh
            .draw_snapshot()
            .positions,
        baseline_positions,
        "hiding and restoring edit colours replaced the loaded deformation baseline"
    );
    Ok(())
}

#[test]
fn viewport_selection_overlay_is_depth_filtered_until_xray_is_explicit() -> TestResult {
    let mut ui = HeadlessUi::new(overlapping_parts_application()?, egui::vec2(1_280.0, 900.0));
    let base_vertex_colour = ui.application.overlay_vertex_colour;
    assert_eq!(
        ui.output
            .shapes
            .iter()
            .filter(
                |clipped| matches!(&clipped.shape, egui::Shape::Circle(circle)
                if circle.fill == base_vertex_colour)
            )
            .count(),
        0,
        "wgpu point display was duplicated by an egui all-vertex overlay"
    );

    let vertices = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .vertices()
        .map(|(handle, _)| handle)
        .collect();
    ui.application
        .mesh
        .as_mut()
        .ok_or("mesh")?
        .set_selection(Selection {
            vertices,
            ..Selection::default()
        })?;
    let selected_circle_count = |ui: &HeadlessUi| {
        let colour = ui.application.overlay_selection_colour;
        ui.output
            .shapes
            .iter()
            .filter(|clipped| {
                matches!(&clipped.shape, egui::Shape::Circle(circle)
                if circle.fill == colour
                    && (circle.radius - (ui.application.overlay_vertex_size + 1.5).max(2.0)).abs()
                        < 0.01)
            })
            .count()
    };

    ui.application.selection_visible_only = true;
    ui.application.view_mode = ViewMode::Solid;
    ui.frame(Vec::new());
    assert_eq!(selected_circle_count(&ui), 3);

    ui.application.selection_visible_only = false;
    ui.frame(Vec::new());
    assert_eq!(selected_circle_count(&ui), 6);

    ui.application.selection_visible_only = true;
    ui.application.view_mode = ViewMode::XRay;
    ui.frame(Vec::new());
    assert_eq!(selected_circle_count(&ui), 6);
    Ok(())
}

#[test]
fn integrated_panel_scroll_cannot_zoom_or_interrupt_the_next_selection_click() -> TestResult {
    for tool_rail in [true, false] {
        let mut ui =
            HeadlessUi::new_integrated_cdmw(triangle_application()?, egui::vec2(1_280.0, 900.0));
        ui.click("Selection")?;
        ui.click("Select")?;
        let viewport = ui.application.viewport_rect.ok_or("viewport")?;
        let point = ui.projected_point(SelectionDomain::Vertex)?;
        let camera_revision = ui.application.camera.revision();
        let panel_x = if tool_rail {
            viewport.left() * 0.5
        } else {
            (viewport.right() + ui.size.x) * 0.5
        };
        ui.frame(vec![
            Event::PointerMoved(egui::pos2(panel_x, ui.size.y * 0.5)),
            wheel_event(-240.0),
        ]);
        // Move into the viewport before the panel's scroll smoothing finishes.
        ui.click_at(egui::pos2(point.x, point.y));
        assert_eq!(ui.application.camera.revision(), camera_revision);
        assert!(
            !ui.application
                .mesh
                .as_ref()
                .ok_or("mesh")?
                .selection
                .vertices
                .is_empty()
        );
    }
    Ok(())
}

#[test]
fn integrated_selection_release_keeps_side_text_stable_and_blocks_pending_edits() -> TestResult {
    let root = tempdir()?;
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_280.0, 900.0),
    );
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(
        root.path().to_path_buf(),
        "selection-paint-session",
        1,
        0,
    ));
    ui.click("Select")?;
    let side_text = |ui: &HeadlessUi| {
        ["Viewport", "Parts"].map(|label| {
            ui.output.shapes.iter().find_map(|clipped| {
                let egui::Shape::Text(text) = &clipped.shape else {
                    return None;
                };
                (text.galley.job.text == label).then_some((
                    text.fallback_color,
                    text.override_text_color,
                    text.opacity_factor,
                ))
            })
        })
    };
    let before = side_text(&ui);
    assert!(before.iter().all(Option::is_some));
    let point = ui.projected_point(SelectionDomain::Vertex)?;
    ui.click_at(egui::pos2(point.x, point.y));
    ui.frame(Vec::new());
    assert!(ui.application.cdmw_busy());
    assert_eq!(
        side_text(&ui),
        before,
        "selection release dimmed the side text"
    );

    let selected = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .selection
        .vertices
        .clone();
    assert!(!selected.is_empty());
    ui.click("Clear Selection")?;
    assert_eq!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .selection
            .vertices,
        selected
    );
    let fingerprint = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();
    ui.click("Inflate")?;
    ui.drag(
        &[point, point + Vec2::new(18.0, -8.0)],
        PointerButton::Primary,
    );
    assert_eq!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint(),
        fingerprint,
        "a new gesture edited the mesh before the selection acknowledgement"
    );
    assert!(ui.application.cdmw_busy());
    ui.application.cdmw_pending_request = None;
    ui.frame(Vec::new());
    assert_eq!(side_text(&ui), before);
    Ok(())
}

#[test]
fn integrated_selection_settles_to_selected_and_inflate_needs_no_selection() -> TestResult {
    let mut selection_ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_280.0, 900.0),
    );
    selection_ui.click("Select")?;
    let point = selection_ui.projected_point(SelectionDomain::Vertex)?;
    selection_ui.click_at(egui::pos2(point.x, point.y));
    assert!(
        !selection_ui
            .application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .selection
            .vertices
            .is_empty()
    );
    selection_ui.frame(Vec::new());
    assert!(selection_ui.label_rect("Selected").is_some());
    assert!(selection_ui.application.selection_gesture.is_none());

    let mut inflate_ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_280.0, 900.0),
    );
    let selection = &inflate_ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .selection;
    assert!(
        selection.vertices.is_empty()
            && selection.edges.is_empty()
            && selection.faces.is_empty()
            && selection.submeshes.is_empty()
    );
    inflate_ui.click("Inflate")?;
    let point = inflate_ui.projected_point(SelectionDomain::Vertex)?;
    let baseline = inflate_ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();
    inflate_ui.drag(
        &[point + Vec2::new(5.0, -3.0), point + Vec2::new(14.0, -7.0)],
        PointerButton::Primary,
    );
    assert_ne!(
        inflate_ui
            .application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint(),
        baseline,
        "Inflate without a selection did not edit the painted brush area: {}",
        inflate_ui.application.status
    );
    Ok(())
}

#[test]
fn integrated_every_transform_and_sculpt_tool_edits_and_queues_one_shadow_transaction() -> TestResult
{
    for tool in [
        ViewportTool::Move,
        ViewportTool::Rotate,
        ViewportTool::Scale,
        ViewportTool::Grab,
        ViewportTool::Smooth,
        ViewportTool::Inflate,
        ViewportTool::Pinch,
    ] {
        let root = tempdir()?;
        let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
            triangle_application()?,
            egui::vec2(1_280.0, 900.0),
        );
        let needs_selection = tool.sculpt_tool().is_none();
        if needs_selection {
            ui.click("Select All")?;
        }
        ui.application.cdmw_bridge = Some(CdmwBridge::for_test(
            root.path().to_path_buf(),
            &format!("integrated-{tool:?}"),
            1,
            0,
        ));
        ui.click(tool.label())?;
        assert_eq!(ui.application.viewport_tool, tool);
        assert!(!ui.application.cdmw_orbit_mode);

        let rectangle = ui.application.viewport_rect.ok_or("viewport")?;
        let baseline = ui
            .application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint();
        let (start, end) = if tool == ViewportTool::Rotate {
            let pivot = OrbitCamera::selected_center(ui.application.mesh.as_ref().ok_or("mesh")?)
                .ok_or("pivot")?;
            let ring = rotation_ring(&ui.application.camera, pivot, GizmoAxis::Z, rectangle);
            (ring[0], ring[ring.len() / 4])
        } else if tool.sculpt_tool().is_some() {
            let point = ui.projected_point(SelectionDomain::Vertex)?;
            (point + Vec2::new(6.0, -3.0), point + Vec2::new(18.0, -9.0))
        } else {
            let pivot = OrbitCamera::selected_center(ui.application.mesh.as_ref().ok_or("mesh")?)
                .ok_or("pivot")?;
            let center = ui
                .application
                .camera
                .project(pivot, rectangle)
                .ok_or("projected pivot")?
                .screen;
            (center, center + Vec2::new(20.0, -8.0))
        };
        ui.drag(&[start, end], PointerButton::Primary);

        assert_ne!(
            ui.application
                .mesh
                .as_ref()
                .ok_or("mesh")?
                .structural_fingerprint(),
            baseline,
            "{tool:?} did not edit: {}",
            ui.application.status
        );
        assert_eq!(
            ui.application.history.undo_len(),
            usize::from(needs_selection) + 1,
            "{tool:?}"
        );
        assert_eq!(ui.application.cdmw_transaction_attempts, 1, "{tool:?}");
        assert!(matches!(
            ui.application.cdmw_pending_request,
            Some(CdmwPendingRequest {
                event: "transaction_result",
                ..
            })
        ));
        assert!(
            !ui.application.status.contains("rolled back"),
            "{tool:?}: {}",
            ui.application.status
        );
        ui.application.mesh.as_ref().ok_or("mesh")?.validate()?;
    }
    Ok(())
}

#[test]
fn resampling_brushes_keep_prior_edits_when_the_pointer_leaves_the_surface() -> TestResult {
    for tool in [
        ViewportTool::Smooth,
        ViewportTool::Inflate,
        ViewportTool::Pinch,
    ] {
        let mut ui = HeadlessUi::new(triangle_application()?, egui::vec2(1_280.0, 900.0));
        ui.click(tool.label())?;
        ui.application.brush_radius = 18.0;
        ui.frame(Vec::new());
        let surface = ui.projected_point(SelectionDomain::Vertex)? + Vec2::new(8.0, -4.0);
        let rectangle = ui.application.viewport_rect.ok_or("viewport")?;
        let off_surface = Vec2::new(rectangle.left() + 4.0, rectangle.top() + 4.0);
        assert!(
            ui.application
                .projection
                .as_ref()
                .ok_or("projection")?
                .vertices
                .values()
                .all(|vertex| vertex.screen.distance(off_surface) > ui.application.brush_radius)
        );
        let baseline = ui
            .application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint();
        let start = egui::pos2(surface.x, surface.y);
        ui.frame(vec![
            Event::PointerMoved(start),
            pointer_button(start, PointerButton::Primary, true),
        ]);
        let valid_edit = ui
            .application
            .mesh
            .as_ref()
            .ok_or("edited mesh")?
            .structural_fingerprint();
        assert_ne!(
            valid_edit, baseline,
            "{tool:?} did not apply its valid sample"
        );

        ui.frame(vec![Event::PointerMoved(egui::pos2(
            off_surface.x,
            off_surface.y,
        ))]);
        assert!(
            ui.application.edit_gesture.is_some(),
            "{tool:?} rolled back"
        );
        assert_eq!(
            ui.application
                .mesh
                .as_ref()
                .ok_or("mesh")?
                .structural_fingerprint(),
            valid_edit,
            "{tool:?} changed or discarded the prior valid sample"
        );
        assert!(!ui.application.status.contains("invalid coordinates"));
        assert!(!ui.application.status.contains("rolled back"));

        ui.frame(vec![pointer_button(
            egui::pos2(off_surface.x, off_surface.y),
            PointerButton::Primary,
            false,
        )]);
        assert!(ui.application.edit_gesture.is_none());
        assert_eq!(ui.application.history.undo_len(), 1, "{tool:?}");
        assert_eq!(
            ui.application
                .mesh
                .as_ref()
                .ok_or("mesh")?
                .structural_fingerprint(),
            valid_edit,
            "{tool:?} did not commit the prior samples"
        );
    }
    Ok(())
}

#[test]
fn integrated_painted_symmetry_control_drives_one_mirrored_grab_stroke() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        symmetry_application()?,
        egui::vec2(1_280.0, 900.0),
    );
    ui.click("Grab")?;
    ui.choose("Symmetry", "Off", "X")?;
    assert_eq!(ui.application.sculpt_symmetry, SculptSymmetry::X);
    ui.application.brush_radius = 40.0;
    ui.frame(Vec::new());
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    let left = mesh
        .vertices()
        .find_map(|(handle, vertex)| (vertex.position == [-1.0, 0.0, 0.0]).then_some(handle))
        .ok_or("left")?;
    let right = mesh
        .vertices()
        .find_map(|(handle, vertex)| (vertex.position == [1.0, 0.0, 0.0]).then_some(handle))
        .ok_or("right")?;
    let unmatched = mesh
        .vertices()
        .find_map(|(handle, vertex)| (vertex.position == [2.0, 2.0, 0.0]).then_some(handle))
        .ok_or("unmatched")?;
    let before = mesh
        .vertices()
        .map(|(handle, vertex)| (handle, Vec3::from_array(vertex.position)))
        .collect::<HashMap<_, _>>();
    let rectangle = ui.application.viewport_rect.ok_or("viewport")?;
    let point = ui
        .application
        .camera
        .project(before[&left], rectangle)
        .ok_or("projected left")?
        .screen;
    ui.drag(
        &[point, point + Vec2::new(18.0, -7.0)],
        PointerButton::Primary,
    );
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    let left_delta = Vec3::from_array(mesh.vertex(left).ok_or("left")?.position) - before[&left];
    let right_delta =
        Vec3::from_array(mesh.vertex(right).ok_or("right")?.position) - before[&right];
    assert!((right_delta.x + left_delta.x).abs() < 1.0e-5);
    assert!((right_delta.y - left_delta.y).abs() < 1.0e-5);
    assert!((right_delta.z - left_delta.z).abs() < 1.0e-5);
    assert_eq!(
        Vec3::from_array(mesh.vertex(unmatched).ok_or("unmatched")?.position),
        before[&unmatched]
    );
    assert_eq!(ui.application.history.undo_len(), 1);
    assert!(ui.label_rect("Symmetry").is_some());
    Ok(())
}

#[test]
fn integrated_controls_paint_hover_pressed_selected_disabled_progress_and_failure() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_280.0, 900.0),
    );
    let inflate = ui.reveal("Inflate")?;
    let center = inflate.center();
    ui.frame(vec![Event::PointerMoved(center)]);
    let hovered = ui.rectangle_fills_at(center);
    ui.frame(vec![pointer_button(center, PointerButton::Primary, true)]);
    let pressed = ui.rectangle_fills_at(center);
    assert_ne!(
        hovered, pressed,
        "Inflate hover and pressed feedback are identical"
    );
    ui.frame(vec![pointer_button(center, PointerButton::Primary, false)]);
    ui.frame(Vec::new());
    assert_eq!(ui.application.cdmw_rail_page, Some(CdmwRailPage::Inflate));
    assert_eq!(ui.application.viewport_tool, ViewportTool::Inflate);
    assert!(!ui.application.cdmw_orbit_mode);

    ui.application.cdmw_pending_request = Some(CdmwPendingRequest {
        request_id: 10,
        event: "command_result",
        label: "Slow topology".to_owned(),
        origin: None,
    });
    ui.application.status = "Slow topology in progress".to_owned();
    ui.frame(Vec::new());
    assert!(ui.label_rect("Slow topology in progress").is_some());
    let select = ui.reveal("Select")?;
    ui.click_at(select.center());
    assert_eq!(
        ui.application.cdmw_rail_page,
        Some(CdmwRailPage::Inflate),
        "dependent tool changed while progress disabled it"
    );

    ui.application.cdmw_pending_request = None;
    ui.application.status = "Finish rejected: exact protected bytes changed".to_owned();
    ui.frame(Vec::new());
    assert!(
        ui.label_rect("Finish rejected: exact protected bytes changed")
            .is_some(),
        "failure reason is not visibly painted"
    );
    assert!(!ui.application.cdmw_host_connected);
    let finish = ui.reveal("Finish Edit Mesh")?;
    ui.click_at(finish.center());
    assert!(ui.application.cdmw_pending_request.is_none());
    Ok(())
}

#[test]
fn pending_integrated_viewport_blocks_primary_edits_but_keeps_pointer_camera_live() -> TestResult {
    let root = tempdir()?;
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1_280.0, 900.0),
    );
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(
        root.path().to_path_buf(),
        "pointer-camera-session",
        1,
        0,
    ));
    ui.application.cdmw_orbit_mode = false;
    ui.application.viewport_tool = ViewportTool::Inflate;
    ui.application.cdmw_pending_request = Some(CdmwPendingRequest {
        request_id: 12,
        event: "command_result",
        label: "Slow topology".to_owned(),
        origin: None,
    });
    ui.frame(Vec::new());
    let point = ui.projected_point(SelectionDomain::Vertex)?;
    let baseline = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();

    ui.drag(
        &[point, point + Vec2::new(18.0, -8.0)],
        PointerButton::Primary,
    );
    assert_eq!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint(),
        baseline
    );
    assert!(ui.application.selection_gesture.is_none());
    assert!(ui.application.edit_gesture.is_none());

    let camera_revision = ui.application.camera.revision();
    ui.drag(
        &[point, point + Vec2::new(24.0, 6.0)],
        PointerButton::Secondary,
    );
    assert!(ui.application.camera.revision() > camera_revision);
    assert_eq!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint(),
        baseline
    );
    assert!(ui.application.cdmw_pending_request.is_some());
    Ok(())
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
        assert_eq!(ui.application.history.undo_len(), 2);
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
fn painted_bones_toggle_and_inspector_require_a_decoded_pab_hierarchy() -> TestResult {
    let document = cdmw_formats::decode_mesh(
        &cdmw_formats::synthetic::two_lod_pac(),
        cdmw_formats::MeshFormat::Pac,
    )?;
    let cancellation = cdmw_archive::CancellationToken::default();
    let mut meshes = crate::loader::build_lod_meshes(&document, &cancellation)?.into_iter();
    let mesh = meshes.next().ok_or("missing LOD0 working mesh")?;
    let skeleton = cdmw_formats::decode_pab(&cdmw_formats::synthetic::two_bone_pab())?;
    let mut application = LabApplication::new(None, None);
    application.install_loaded_mesh(crate::loader::LoadedMesh {
        path: PathBuf::from("character/model/cd_phw_00_body.pac"),
        document,
        mesh,
        other_lod_meshes: meshes.collect(),
        textures: Vec::new(),
        material_parameters: Vec::new(),
        material_factors: Vec::new(),
        skeleton: Some(crate::loader::LoadedSkeleton {
            label: "character/model/cd_phw_00.pab".to_owned(),
            document: skeleton,
            resolution_method: cdmw_asset_graph::ResolutionMethod::ProvenFamilyRule,
            archive_compression: Some(cdmw_archive::CompressionOutcome::Stored),
        }),
    });

    let mut ui = HeadlessUi::new(application, egui::vec2(1_280.0, 900.0));
    assert!(ui.reveal("Resolved skeleton context").is_ok());
    assert!(ui.reveal("character/model/cd_phw_00.pab").is_ok());
    assert!(
        ui.reveal("2 bones · 1 roots · depth 1 · 1 overlay segments")
            .is_ok()
    );
    ui.click("Bone hierarchy (2)")?;
    assert!(
        ui.reveal("#1 Spine · hash 11111112 · parent #0 Root · bind 0.0000, 1.0000, 0.0000")
            .is_ok()
    );
    assert!(!ui.application.show_bones);
    ui.click("Bones")?;
    assert!(ui.application.show_bones);
    ui.click("Bones")?;
    assert!(!ui.application.show_bones);
    Ok(())
}

#[test]
fn painted_topology_selection_commands_are_exact_and_undoable() -> TestResult {
    let mut vertex_application = lod_one_application()?;
    let corner = {
        let mesh = vertex_application.mesh.as_ref().ok_or("vertex mesh")?;
        mesh.vertices()
            .map(|(handle, _)| handle)
            .find(|handle| {
                mesh.vertex_neighbors(*handle)
                    .is_some_and(|neighbors| neighbors.len() == 2)
            })
            .ok_or("quad corner")?
    };
    vertex_application
        .mesh
        .as_mut()
        .ok_or("vertex mesh")?
        .set_selection(Selection {
            vertices: [corner].into_iter().collect(),
            ..Selection::default()
        })?;
    let vertex_baseline = vertex_application
        .mesh
        .as_ref()
        .ok_or("vertex mesh")?
        .structural_fingerprint();
    let mut vertex_ui = HeadlessUi::new(vertex_application, egui::vec2(1_280.0, 720.0));
    vertex_ui.click("Grow")?;
    assert_eq!(selected_count(&vertex_ui, SelectionDomain::Vertex)?, 3);
    assert_eq!(vertex_ui.application.history.undo_len(), 1);
    vertex_ui.click("Undo")?;
    let vertex_mesh = vertex_ui.application.mesh.as_ref().ok_or("vertex mesh")?;
    assert_eq!(vertex_mesh.selection.vertices.len(), 1);
    assert!(vertex_mesh.selection.vertices.contains(&corner));
    vertex_ui.click("Redo")?;
    vertex_ui.click("Shrink")?;
    let vertex_mesh = vertex_ui.application.mesh.as_ref().ok_or("vertex mesh")?;
    assert_eq!(vertex_mesh.selection.vertices.len(), 1);
    assert!(vertex_mesh.selection.vertices.contains(&corner));
    vertex_ui.click("Invert")?;
    let vertex_mesh = vertex_ui.application.mesh.as_ref().ok_or("vertex mesh")?;
    assert_eq!(vertex_mesh.selection.vertices.len(), 3);
    assert!(!vertex_mesh.selection.vertices.contains(&corner));
    assert_eq!(vertex_mesh.structural_fingerprint(), vertex_baseline);
    assert_eq!(vertex_ui.application.history.undo_len(), 3);

    let mut edge_ui = HeadlessUi::new(lod_one_application()?, egui::vec2(1_280.0, 720.0));
    edge_ui.click("All Edges")?;
    assert_eq!(edge_ui.application.selection_domain, SelectionDomain::Edge);
    let edge_mesh = edge_ui.application.mesh.as_ref().ok_or("edge mesh")?;
    assert_eq!(selected_count(&edge_ui, SelectionDomain::Edge)?, 5);
    assert!(edge_mesh.selection.vertices.is_empty() && edge_mesh.selection.faces.is_empty());
    assert_eq!(edge_ui.application.history.undo_len(), 1);
    edge_ui.click("Invert")?;
    assert_eq!(selected_count(&edge_ui, SelectionDomain::Edge)?, 0);
    edge_ui.click("Undo")?;
    assert_eq!(selected_count(&edge_ui, SelectionDomain::Edge)?, 5);
    edge_ui.click("Clear")?;
    assert_eq!(selected_count(&edge_ui, SelectionDomain::Edge)?, 0);
    assert_eq!(edge_ui.application.history.undo_len(), 2);
    edge_ui.click("Undo")?;
    assert_eq!(selected_count(&edge_ui, SelectionDomain::Edge)?, 5);

    let mut face_application = lod_one_application()?;
    let face = face_application
        .mesh
        .as_ref()
        .ok_or("face mesh")?
        .faces()
        .next()
        .map(|(handle, _)| handle)
        .ok_or("face")?;
    face_application
        .mesh
        .as_mut()
        .ok_or("face mesh")?
        .set_selection(Selection {
            faces: [face].into_iter().collect(),
            ..Selection::default()
        })?;
    let mut face_ui = HeadlessUi::new(face_application, egui::vec2(1_280.0, 720.0));
    face_ui.click("Face")?;
    face_ui.click("Grow")?;
    assert_eq!(selected_count(&face_ui, SelectionDomain::Face)?, 2);
    face_ui.click("Grow")?;
    assert_eq!(face_ui.application.history.undo_len(), 1);
    face_ui.click("Undo")?;
    face_ui.click("Shrink")?;
    assert_eq!(selected_count(&face_ui, SelectionDomain::Face)?, 0);
    assert_eq!(face_ui.application.history.undo_len(), 1);
    Ok(())
}

#[test]
fn painted_select_linked_stays_inside_the_seeded_component_and_is_undoable() -> TestResult {
    for (label, domain, expected_count) in [
        ("Vertex", SelectionDomain::Vertex, 4),
        ("Edge", SelectionDomain::Edge, 5),
        ("Face", SelectionDomain::Face, 2),
    ] {
        let mut application = lod_one_application()?;
        let mesh = application.mesh.as_mut().ok_or("mesh")?;
        let source_vertices = mesh
            .vertices()
            .map(|(handle, _)| handle)
            .collect::<HashSet<_>>();
        let source_faces = mesh
            .faces()
            .map(|(handle, _)| handle)
            .collect::<HashSet<_>>();
        mesh.duplicate_faces(&source_faces)?;
        let seed = match domain {
            SelectionDomain::Vertex => Selection {
                vertices: HashSet::from([*source_vertices.iter().next().ok_or("source vertex")?]),
                ..Selection::default()
            },
            SelectionDomain::Edge => {
                let edge = mesh
                    .edges()
                    .find(|(_, edge)| {
                        edge.vertices
                            .iter()
                            .all(|vertex| source_vertices.contains(vertex))
                    })
                    .map(|(handle, _)| handle)
                    .ok_or("source edge")?;
                Selection {
                    edges: HashSet::from([edge]),
                    ..Selection::default()
                }
            }
            SelectionDomain::Face => Selection {
                faces: HashSet::from([*source_faces.iter().next().ok_or("source face")?]),
                ..Selection::default()
            },
        };
        mesh.set_selection(seed.clone())?;
        let baseline = mesh.structural_fingerprint();
        let mut ui = HeadlessUi::new(application, egui::vec2(1_280.0, 720.0));
        ui.click(label)?;
        ui.click("Linked")?;
        assert_eq!(selected_count(&ui, domain)?, expected_count);
        assert_eq!(ui.application.history.undo_len(), 1);
        let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
        assert_eq!(mesh.structural_fingerprint(), baseline);
        match domain {
            SelectionDomain::Vertex => assert_eq!(mesh.selection.vertices, source_vertices),
            SelectionDomain::Edge => assert!(mesh.selection.edges.iter().all(|handle| {
                mesh.edge(*handle).is_some_and(|edge| {
                    edge.vertices
                        .iter()
                        .all(|vertex| source_vertices.contains(vertex))
                })
            })),
            SelectionDomain::Face => assert_eq!(mesh.selection.faces, source_faces),
        }
        ui.click("Undo")?;
        assert_eq!(ui.application.mesh.as_ref().ok_or("mesh")?.selection, seed);
        ui.click("Redo")?;
        assert_eq!(selected_count(&ui, domain)?, expected_count);
        ui.click("Linked")?;
        assert_eq!(ui.application.history.undo_len(), 1);
        assert!(ui.application.status.contains("made no change"));
    }
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
    for (label, expected_faces, expected_new_submesh) in [
        ("Delete", 0, None),
        ("Subdivide", 4, None),
        ("Duplicate", 2, None),
        ("Duplicate as New Part", 2, Some(1)),
        ("Extrude", 7, None),
        ("Inset Individual", 7, None),
    ] {
        let mut ui = HeadlessUi::new(triangle_application()?, egui::vec2(1_280.0, 720.0));
        if label == "Extrude" {
            ui.application.extrude_distance = 0.25;
        } else if label == "Inset Individual" {
            ui.application.inset_amount = 0.25;
        }
        ui.click("All Faces")?;
        let source_vertices = ui
            .application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .vertices()
            .map(|(handle, vertex)| (handle, vertex.clone()))
            .collect::<HashMap<_, _>>();
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
        let source_face = if matches!(label, "Extrude" | "Inset Individual") {
            let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
            let handle = *selection.faces.iter().next().ok_or("selected face")?;
            Some(mesh.face(handle).cloned().ok_or("selected face")?)
        } else {
            None
        };
        ui.click(label)?;
        assert_eq!(
            ui.application.mesh.as_ref().ok_or("mesh")?.faces().count(),
            expected_faces
        );
        if let Some(expected_submesh) = expected_new_submesh {
            let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
            assert!(mesh.selection.faces.iter().all(|handle| {
                mesh.face(*handle)
                    .is_some_and(|face| face.submesh == expected_submesh && face.material == 0)
            }));
        }
        if matches!(label, "Extrude" | "Inset Individual") {
            let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
            for (handle, source) in &source_vertices {
                assert_eq!(mesh.vertex(*handle), Some(source));
            }
            assert_eq!(mesh.selection.faces.len(), 1);
        }
        if label == "Extrude" {
            let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
            let cap = mesh
                .face(*mesh.selection.faces.iter().next().ok_or("cap")?)
                .ok_or("cap")?;
            for (source_handle, cap_handle) in source_face
                .as_ref()
                .ok_or("source face")?
                .vertices
                .into_iter()
                .zip(cap.vertices)
            {
                let source = source_vertices.get(&source_handle).ok_or("source vertex")?;
                let direction = Vec3::from_array(source.normal)
                    .try_normalize()
                    .ok_or("source normal")?;
                let cap_vertex = mesh.vertex(cap_handle).ok_or("cap vertex")?;
                assert_eq!(
                    Vec3::from_array(cap_vertex.position),
                    Vec3::from_array(source.position) + direction * 0.25
                );
            }
        }
        if label == "Inset Individual" {
            let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
            let source_face = source_face.as_ref().ok_or("source face")?;
            let centroid = source_face
                .vertices
                .iter()
                .map(|handle| {
                    source_vertices
                        .get(handle)
                        .map(|vertex| Vec3::from_array(vertex.position))
                        .ok_or("source vertex")
                })
                .collect::<Result<Vec<_>, _>>()?
                .into_iter()
                .sum::<Vec3>()
                / 3.0;
            let cap = mesh
                .face(*mesh.selection.faces.iter().next().ok_or("cap")?)
                .ok_or("cap")?;
            for (source_handle, cap_handle) in source_face.vertices.into_iter().zip(cap.vertices) {
                let source = source_vertices.get(&source_handle).ok_or("source vertex")?;
                let cap_vertex = mesh.vertex(cap_handle).ok_or("cap vertex")?;
                assert_eq!(
                    Vec3::from_array(cap_vertex.position),
                    Vec3::from_array(source.position).lerp(centroid, 0.25)
                );
            }
        }
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
        if let Some(expected_submesh) = expected_new_submesh {
            let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
            assert!(mesh.selection.faces.iter().all(|handle| {
                mesh.face(*handle)
                    .is_some_and(|face| face.submesh == expected_submesh && face.material == 0)
            }));
        }
        ui.application.mesh.as_ref().ok_or("mesh")?.validate()?;
    }

    let mut ui = HeadlessUi::new(triangle_application()?, egui::vec2(1_280.0, 720.0));
    ui.click("All Edges")?;
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
    assert_eq!(selection.edges.len(), 3);
    ui.click("Subdivide Edges")?;
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    let edited = mesh.structural_fingerprint();
    assert_ne!(baseline, edited);
    assert_eq!(mesh.faces().count(), 4);
    assert_eq!(mesh.selection.edges.len(), 6);
    assert_eq!(ui.application.selection_domain, SelectionDomain::Edge);
    ui.click("Undo")?;
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    assert_eq!(mesh.structural_fingerprint(), baseline);
    assert_eq!(mesh.selection, selection);
    ui.click("Redo")?;
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    assert_eq!(mesh.structural_fingerprint(), edited);
    assert_eq!(mesh.selection.edges.len(), 6);
    mesh.validate()?;
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
        // Interaction builds the projection lazily for the current viewport.
        assert!(ui.application.ensure_projection(rectangle));
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
        assert_eq!(ui.application.history.undo_len(), 2, "{tool:?}");
        assert!(ui.application.edit_gesture.is_none());
        assert!(
            ui.application.deformation_reference.is_some(),
            "{tool:?} did not retain its preview-only deformation reference"
        );
        assert_eq!(
            ui.application
                .deformation_reference
                .as_ref()
                .map(|reference| reference.mesh.topology_generation),
            ui.application
                .mesh
                .as_ref()
                .map(|mesh| mesh.topology_generation),
            "{tool:?} retained a reference from another topology"
        );
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
        assert_eq!(ui.application.history.undo_len(), 1);
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

fn total_edge_length(mesh: &WorkingMesh) -> Result<f32, Box<dyn std::error::Error>> {
    mesh.edges().try_fold(0.0, |total, (_, edge)| {
        let first = Vec3::from_array(
            mesh.vertex(edge.vertices[0])
                .ok_or("missing first edge vertex")?
                .position,
        );
        let second = Vec3::from_array(
            mesh.vertex(edge.vertices[1])
                .ok_or("missing second edge vertex")?
                .position,
        );
        Ok(total + first.distance(second))
    })
}

fn run_painted_smooth(passes: u32) -> Result<(f32, f32), Box<dyn std::error::Error>> {
    let mut ui = HeadlessUi::new(triangle_application()?, egui::vec2(1_280.0, 900.0));
    ui.click("Smooth")?;
    ui.choose("Falloff", "Smooth", "Linear")?;
    if passes != 1 {
        ui.choose("Smooth passes", "1 pass", &format_pass_count(passes))?;
    }
    assert_eq!(ui.application.brush_falloff, BrushFalloff::Linear);
    assert_eq!(ui.application.smooth_iterations, passes);
    ui.application.camera.zoom(-1_000.0);
    ui.application.projection = None;
    ui.application.brush_radius = 200.0;
    ui.frame(Vec::new());
    let point = ui.projected_point(SelectionDomain::Vertex)?;
    let pointer = egui::pos2(point.x, point.y);
    let baseline = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();
    let baseline_length = total_edge_length(ui.application.mesh.as_ref().ok_or("mesh")?)?;
    ui.frame(vec![
        Event::PointerMoved(pointer),
        pointer_button(pointer, PointerButton::Primary, true),
    ]);
    let gesture = ui
        .application
        .edit_gesture
        .as_ref()
        .ok_or("smooth gesture")?;
    assert!(gesture.sculpt_weights.len() > 1);
    assert!(
        gesture
            .sculpt_weights
            .values()
            .any(|weight| *weight > 0.0 && *weight < 1.0)
    );
    assert!(
        gesture
            .sculpt_weights
            .values()
            .any(|weight| (*weight - 1.0).abs() < f32::EPSILON)
    );
    ui.frame(vec![pointer_button(pointer, PointerButton::Primary, false)]);
    let edited = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();
    assert_ne!(edited, baseline);
    assert_eq!(ui.application.history.undo_len(), 1);
    let edited_length = total_edge_length(ui.application.mesh.as_ref().ok_or("mesh")?)?;
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
    Ok((baseline_length, edited_length))
}

#[test]
fn sculpt_falloff_and_smooth_passes_are_painted_weighted_and_undoable() -> TestResult {
    let (baseline_length, one_pass_length) = run_painted_smooth(1)?;
    let (four_pass_baseline, four_pass_length) = run_painted_smooth(4)?;
    assert!((four_pass_baseline - baseline_length).abs() < 1.0e-6);
    assert!(one_pass_length < baseline_length);
    assert!(four_pass_length < one_pass_length);
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
        "Linked",
        "Subdivide Edges",
        "Duplicate as New Part",
        "Extrude",
        "Inset Individual",
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
    for _ in 0..6 {
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
        4096
    );
    let ui = HeadlessUi::new(application, egui::vec2(1_280.0, 720.0));
    let selection_colour = ui.application.overlay_selection_colour;
    let face_fill = Color32::from_rgba_unmultiplied(
        selection_colour.r(),
        selection_colour.g(),
        selection_colour.b(),
        72,
    );
    let face_meshes = ui
        .output
        .shapes
        .iter()
        .filter_map(|clipped| match &clipped.shape {
            egui::Shape::Mesh(mesh)
                if !mesh.vertices.is_empty()
                    && mesh.vertices.iter().all(|vertex| vertex.color == face_fill) =>
            {
                Some(mesh)
            }
            _ => None,
        })
        .collect::<Vec<_>>();
    assert!(
        face_meshes.is_empty(),
        "faces must not bypass mesh depth through egui"
    );
    let positions = &ui
        .application
        .face_selection_overlay
        .as_ref()
        .ok_or("face highlight")?
        .positions;
    assert_eq!(
        positions.len(),
        4096 * 3,
        "large selections must retain every filled face"
    );
    assert!(positions.iter().flatten().all(|value| value.is_finite()));
    assert!(ui.output.shapes.iter().all(|clipped| {
        !matches!(&clipped.shape, egui::Shape::LineSegment { stroke, .. }
            if stroke.color == selection_colour)
    }));
    assert!(ui.output.shapes.iter().all(|clipped| {
        !matches!(&clipped.shape, egui::Shape::Path(path)
            if path.closed
                && (path.fill == face_fill
                    || path.stroke.color
                        == egui::epaint::ColorMode::Solid(selection_colour)))
    }));
    Ok(())
}

#[test]
fn sparse_face_selection_uses_depth_geometry_without_mitered_screen_edges() -> TestResult {
    let mut application = triangle_application()?;
    let face = application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .faces()
        .next()
        .map(|(handle, _)| handle)
        .ok_or("face")?;
    application
        .mesh
        .as_mut()
        .ok_or("mesh")?
        .set_selection(Selection {
            faces: HashSet::from([face]),
            ..Selection::default()
        })?;
    let ui = HeadlessUi::new(application, egui::vec2(1_280.0, 720.0));
    let selection_colour = ui.application.overlay_selection_colour;
    let face_fill = Color32::from_rgba_unmultiplied(
        selection_colour.r(),
        selection_colour.g(),
        selection_colour.b(),
        72,
    );
    let fill_triangles = ui
        .output
        .shapes
        .iter()
        .filter_map(|clipped| match &clipped.shape {
            egui::Shape::Mesh(mesh)
                if !mesh.vertices.is_empty()
                    && mesh.vertices.iter().all(|vertex| vertex.color == face_fill) =>
            {
                Some(mesh.triangles().count())
            }
            _ => None,
        })
        .sum::<usize>();
    let independent_edges = ui
        .output
        .shapes
        .iter()
        .filter(|clipped| {
            matches!(&clipped.shape, egui::Shape::LineSegment { stroke, .. }
                if stroke.color == selection_colour
                    && (stroke.width - ui.application.overlay_wire_width).abs() < 0.01)
        })
        .count();
    assert_eq!(fill_triangles, 0);
    assert_eq!(independent_edges, 0);
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    let expected = mesh
        .face(face)
        .ok_or("selected face")?
        .vertices
        .iter()
        .map(|handle| mesh.vertex(*handle).expect("face vertex").position)
        .collect::<Vec<_>>();
    assert_eq!(
        ui.application
            .face_selection_overlay
            .as_ref()
            .ok_or("face highlight")?
            .positions,
        expected
    );
    assert!(ui.output.shapes.iter().all(|clipped| {
        !matches!(&clipped.shape, egui::Shape::Path(path)
            if path.closed
                && (path.fill == face_fill
                    || path.stroke.color
                        == egui::epaint::ColorMode::Solid(selection_colour)))
    }));
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
            texture_tint: None,
            base_tint_strength: None,
            alpha_cutoff: Some(0.08),
            alpha_blend: None,
            opacity: None,
            gltf_metallic_roughness: None,
            hair_anisotropy: Some(true),
            layer_mask_channel: Some(2),
            skin_detail_scale: None,
            skin_detail_opacity: None,
            material_indices_by_lod: vec![vec![0]],
        }],
        skeleton: None,
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
