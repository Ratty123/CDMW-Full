//! Actual navigation and action-strip interactions across Morph panel presentations.
use super::*;

impl HeadlessUi {
    pub(super) fn open_refit_detail(&mut self, prefix: &str) -> TestResult {
        self.scroll_tool_rail(2_000.0);
        for _ in 0..32 {
            let label = self.output.shapes.iter().find_map(|shape| match &shape.shape {
                egui::Shape::Text(text) if text.galley.job.text.starts_with(prefix)
                    && self.label_rect(&text.galley.job.text).is_some() => Some(text.galley.job.text.clone()),
                _ => None,
            });
            if let Some(label) = label { return self.click(&label); }
            self.scroll_tool_rail(-120.0);
        }
        Err(format!("missing refit section {prefix}").into())
    }

    pub(super) fn refit_scope(&mut self, all: bool) -> TestResult {
        self.reveal("Editing")?;
        let current = self.output.shapes.iter().find_map(|shape| match &shape.shape {
            egui::Shape::Text(text) if text.galley.job.text.starts_with("All bound garments ·")
                || text.galley.job.text.starts_with("Selected garments ·") => Some(text.galley.job.text.clone()),
            _ => None,
        }).ok_or("missing refit scope")?;
        self.choose("Editing", &current, if all { "All bound garments" } else { "Selected garments" })
    }

    pub(super) fn scroll_tool_window(&mut self, label: &str, distance: f32) -> TestResult {
        let area = self.tool_window_rect(label)?;
        let position = egui::pos2(area.center().x, area.top() + (area.height() * 0.4));
        self.frame(vec![Event::PointerMoved(position), wheel_event(distance)]);
        self.settle_layout();
        Ok(())
    }

    pub(super) fn open_morph_shape(&mut self, tab: &str) -> TestResult {
        self.click("Shape")?;
        if self.label_rect("Back to sliders").is_some() {
            self.click("Back to sliders")?;
        }
        self.click(tab)
    }

    pub(super) fn open_morph_sliders(&mut self) -> TestResult {
        self.open_morph_shape("Sliders")
    }

    pub(super) fn open_morph_creator(&mut self, sculpted: bool) -> TestResult {
        self.open_morph_sliders()?;
        self.click("+ Create")?;
        self.click(if sculpted { "Sculpted" } else { "Procedural" })
    }

    pub(super) fn open_morph_saved(&mut self, tab: &str) -> TestResult {
        self.click("Saved")?;
        self.click(tab)
    }
}

fn mixed_refit_ui(selected: &[u32]) -> Result<HeadlessUi, Box<dyn std::error::Error>> {
    let mut ui = super::morph_authoring::authoring_ui()?;
    ui.application.cdmw_state["morph_refit"]["refit"]["garment_settings"] = json!([
        {"submesh_index": 1, "enabled": true, "intensity_percent": 37.0,
         "mode": "surface", "clearance_percent": 0.5, "tightness_percent": 25.0},
        {"submesh_index": 2, "enabled": false, "intensity_percent": 64.0,
         "mode": "rigid_component", "clearance_percent": 1.25, "tightness_percent": 63.0}
    ]);
    ui.application.mesh.as_mut().ok_or("mesh")?.set_selection(Selection {
        submeshes: selected.iter().copied().collect(),
        ..Selection::default()
    })?;
    ui.click("Fit")?;
    Ok(ui)
}

fn refit_arguments(actions: &[UiAction]) -> Value {
    actions.iter().find_map(|action| match action {
        UiAction::CdmwCommand { command: "refit_configure", arguments, .. } => Some(arguments.clone()),
        _ => None,
    }).unwrap_or_else(|| panic!("missing refit_configure: {actions:?}"))
}

fn assert_part_name_hover(ui: &mut HeadlessUi, label: &str, part: u32) -> TestResult {
    let name = ui.reveal(label)?;
    let state = ui.application.cdmw_state.clone();
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?.clone();
    let targets = ui.application.cdmw_refit_region_targets.clone();
    let expected = mesh.faces().filter(|(_, face)| face.submesh == part)
        .flat_map(|(_, face)| face.vertices.iter())
        .map(|handle| mesh.vertex(*handle).unwrap().position).collect::<Vec<_>>();
    ui.last_actions.clear();
    ui.frame(vec![Event::PointerMoved(name.center())]);
    ui.settle_layout();
    assert_eq!(ui.application.cdmw_hovered_part, Some(part), "{label}");
    let (highlighted, overlay) = ui.application.cdmw_part_hover_overlay.as_ref().ok_or("hover overlay")?;
    assert_eq!(*highlighted, part);
    assert_eq!(overlay.positions, expected);
    assert!(!overlay.positions.is_empty());
    let current = ui.application.mesh.as_ref().ok_or("mesh")?;
    assert_eq!(current.selection, mesh.selection);
    assert_eq!(current.selection_revision, mesh.selection_revision);
    assert_eq!(current.structural_fingerprint(), mesh.structural_fingerprint());
    assert_eq!(ui.application.cdmw_state, state);
    assert_eq!(ui.application.cdmw_refit_region_targets, targets);
    assert!(ui.last_actions.is_empty(), "hover dispatched {:?}", ui.last_actions);
    assert!(ui.application.cdmw_pending_request.is_none());
    ui.frame(vec![Event::PointerGone]);
    assert_eq!(ui.application.cdmw_hovered_part, None, "leaving {label}");
    assert!(ui.application.cdmw_part_hover_overlay.is_none());
    Ok(())
}

#[test]
fn workflow_part_name_hover_preserves_selection_and_fit_edits() -> TestResult {
    let mut ui = mixed_refit_ui(&[2])?;
    let root = tempdir()?;
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(root.path().to_path_buf(), "part-hover-ui", 2, 0));
    ui.type_number_in_row("Clearance %", 1.25, "0.75")?;
    ui.open_refit_detail("Choose garments")?;
    assert_part_name_hover(&mut ui, "2 · Sleeve", 1)?;
    assert_part_name_hover(&mut ui, "3 · Plate", 2)?;
    ui.click("Part colors")?;
    assert_part_name_hover(&mut ui, "2 · Sleeve", 1)?;
    assert_eq!(ui.application.cdmw_refit_clearance, 0.75);
    assert!(ui.application.cdmw_refit_settings_dirty.is_dirty());
    assert_part_name_hover(&mut ui, "0: Body", 0)?;
    ui.open_refit_detail("Choose garments")?;
    ui.open_refit_detail("Body region")?;
    assert_part_name_hover(&mut ui, "2 · Sleeve", 1)?;
    ui.open_refit_detail("Body region")?;
    ui.click("Setup")?;
    ui.open_refit_detail("Choose Parts")?;
    assert_part_name_hover(&mut ui, "1 · Body", 0)?;
    ui.click("Fit")?;
    refit_feedback_reply(&mut ui, "Fit to body", false,
        "Fit to body: Part 1 still intersects Part 2 beneath its triangles; previous preview retained")?;
    assert_part_name_hover(&mut ui, "2 · Sleeve", 1)?;
    assert_eq!(ui.application.cdmw_refit_highlight_parts(), vec![1, 2]);
    ui.application.cdmw_refit_feedback = None;
    ui.application.cdmw_state["mesh_islands"] = json!({"fit_parts": [{"index": 1,
        "name": "Sleeve", "islands": [{"faces": [0]}]}]});
    ui.choose("Editing", "Selected garments · 1", "Selected mesh islands")?;
    ui.open_refit_detail("Choose mesh islands")?;
    assert_part_name_hover(&mut ui, "2 · Sleeve", 1)?;
    Ok(())
}

#[test]
fn workflow_part_name_hover_clears_and_respects_visible_geometry() -> TestResult {
    let mut ui = mixed_refit_ui(&[2])?;
    let root = tempdir()?;
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(root.path().to_path_buf(), "part-hover-ui", 2, 0));
    ui.open_refit_detail("Choose garments")?;
    let name = ui.reveal("2 · Sleeve")?;
    ui.frame(vec![Event::PointerMoved(name.center())]);
    ui.settle_layout();
    assert_eq!(ui.application.cdmw_part_hover_overlay.as_ref().map(|(part, _)| *part), Some(1));
    // Moving straight to another name must replace the cached geometry.
    let other = ui.reveal("3 · Plate")?;
    ui.frame(vec![Event::PointerMoved(other.center())]);
    ui.settle_layout();
    assert_eq!(ui.application.cdmw_part_hover_overlay.as_ref().map(|(part, _)| *part), Some(2));
    ui.frame(vec![Event::PointerMoved(ui.application.viewport_rect.ok_or("viewport")?.center())]);
    assert!(ui.application.cdmw_part_hover_overlay.is_none());
    // Hidden Parts and hidden Geometry Layers stay hidden on hover.
    ui.application.cdmw_hidden_parts.insert(1);
    ui.frame(vec![Event::PointerMoved(name.center())]);
    ui.settle_layout();
    assert!(ui.application.cdmw_part_hover_overlay.is_none());
    assert!(ui.application.cdmw_hidden_parts.contains(&1));
    ui.application.cdmw_hidden_parts.clear();
    ui.application.cdmw_state["geometry_layers"]["layers"].as_array_mut().ok_or("layers")?.push(
        json!({"layer_id": "sleeve", "name": "Sleeve layer", "submesh_indices": [1], "visible": false, "base": false}));
    ui.frame(Vec::new());
    assert!(ui.application.cdmw_part_hover_overlay.is_none());
    ui.application.cdmw_state["geometry_layers"]["layers"][1]["visible"] = json!(true);
    ui.frame(Vec::new());
    assert!(ui.application.cdmw_part_hover_overlay.is_some());
    // Rebuilding the visible mesh excludes hidden islands from the hover buffer.
    let faces = ui.application.mesh.as_ref().ok_or("mesh")?.faces()
        .filter_map(|(handle, face)| (face.submesh == 1).then_some(handle)).collect();
    ui.application.mesh.as_mut().ok_or("mesh")?.set_viewport_hidden_faces(faces)?;
    ui.application.invalidate_cdmw_part_hover_overlay();
    ui.frame(Vec::new());
    assert!(ui.application.cdmw_part_hover_overlay.as_ref().ok_or("hover")?.1.positions.is_empty());
    ui.application.cdmw_state["replacement"]["comparison"] = json!("source");
    ui.frame(Vec::new());
    assert!(ui.application.cdmw_part_hover_overlay.is_none());
    ui.application.cdmw_state["replacement"]["comparison"] = json!("edit");
    ui.frame(Vec::new());
    assert!(ui.application.cdmw_part_hover_overlay.is_some());
    // A closed page stops contributing hover targets.
    ui.click("Shape")?;
    assert!(ui.application.cdmw_part_hover_overlay.is_none());
    assert_eq!(ui.application.selected_part_indices(), vec![2]);
    assert!(ui.application.cdmw_pending_request.is_none());
    Ok(())
}

fn part_name_has_viewport_outline(ui: &HeadlessUi, label: &str) -> bool {
    let Some(name) = ui.label_rect(label) else { return false; };
    let colour = Color32::from(egui::Rgba::from_rgb(0.15, 0.85, 1.0));
    ui.output.shapes.iter().any(|shape| matches!(&shape.shape,
        egui::Shape::Rect(rect) if rect.stroke.color == colour && rect.stroke.width == 2.0
            && rect.rect.contains(name.center()) && shape.clip_rect.contains(name.center())))
}

fn viewport_part_point(ui: &HeadlessUi, part: u32) -> Result<Pos2, Box<dyn std::error::Error>> {
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    let face = mesh.faces().find(|(_, face)| face.submesh == part).ok_or("Part face")?.1;
    let centre = face.vertices.iter().map(|handle| Vec3::from(mesh.vertex(*handle).unwrap().position))
        .sum::<Vec3>() / 3.0;
    let rectangle = ui.application.viewport_rect.ok_or("viewport")?;
    let point = ui.application.camera.project(centre, rectangle).ok_or("project Part")?;
    assert!(point.inside_view, "Part {part} must be visible in the viewport");
    Ok(egui::pos2(point.screen.x, point.screen.y))
}

fn assert_viewport_part_name_hover(ui: &mut HeadlessUi, part: u32, names: &[&str]) -> TestResult {
    let point = viewport_part_point(ui, part)?;
    let state = ui.application.cdmw_state.clone();
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?.clone();
    let targets = ui.application.cdmw_refit_region_targets.clone();
    ui.last_actions.clear();
    ui.frame(vec![Event::PointerMoved(point)]);
    ui.settle_layout();
    assert_eq!(ui.application.cdmw_viewport_hovered_part, Some(part));
    for name in names { assert!(part_name_has_viewport_outline(ui, name), "missing outline: {name}"); }
    let current = ui.application.mesh.as_ref().ok_or("mesh")?;
    assert_eq!(current.selection, mesh.selection);
    assert_eq!(current.selection_revision, mesh.selection_revision);
    assert_eq!(current.structural_fingerprint(), mesh.structural_fingerprint());
    assert_eq!(ui.application.cdmw_state, state);
    assert_eq!(ui.application.cdmw_refit_region_targets, targets);
    assert!(ui.application.cdmw_hovered_part.is_none());
    assert!(ui.application.cdmw_part_hover_overlay.is_none());
    assert!(ui.last_actions.is_empty());
    assert!(ui.application.cdmw_pending_request.is_none());
    ui.frame(vec![Event::PointerGone]);
    assert!(ui.application.cdmw_viewport_hovered_part.is_none());
    for name in names { assert!(!part_name_has_viewport_outline(ui, name), "stale outline: {name}"); }
    Ok(())
}

#[test]
fn workflow_viewport_part_hover_identifies_names_without_selection_or_fit_changes() -> TestResult {
    let mut ui = mixed_refit_ui(&[2])?;
    let root = tempdir()?;
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(root.path().to_path_buf(), "viewport-part-hover", 2, 0));
    ui.application.camera.frame_all_in_viewport(ui.application.mesh.as_ref().ok_or("mesh")?,
        ui.application.viewport_rect.ok_or("viewport")?);
    ui.type_number_in_row("Clearance %", 1.25, "0.75")?;
    ui.open_refit_detail("Choose garments")?;
    assert_viewport_part_name_hover(&mut ui, 1, &["2 · Sleeve", "1: Sleeve"])?;
    let cached = ui.application.projection.as_ref().ok_or("projection")?.interaction.depth_triangles.as_ptr();
    assert_viewport_part_name_hover(&mut ui, 2, &["3 · Plate", "2: Plate"])?;
    assert_eq!(ui.application.projection.as_ref().ok_or("projection")?.interaction.depth_triangles.as_ptr(), cached,
        "moving the pointer must reuse the picking cache");
    ui.click("Part colors")?;
    assert_viewport_part_name_hover(&mut ui, 1, &["2 · Sleeve", "1: Sleeve"])?;
    assert_eq!(ui.application.cdmw_refit_clearance, 0.75);
    assert!(ui.application.cdmw_refit_settings_dirty.is_dirty());
    // A popup owns hover feedback until it closes.
    ui.click("Selected garments · 1")?;
    assert!(ui.application.egui_context.any_popup_open());
    ui.frame(vec![Event::PointerMoved(viewport_part_point(&ui, 1)?)]);
    assert!(ui.application.cdmw_viewport_hovered_part.is_none());
    ui.frame(vec![key_event(egui::Key::Escape, true), key_event(egui::Key::Escape, false)]);
    ui.open_refit_detail("Choose garments")?;
    ui.open_refit_detail("Body region")?;
    assert_viewport_part_name_hover(&mut ui, 1, &["2 · Sleeve"])?;
    ui.open_refit_detail("Body region")?;
    ui.click("Setup")?;
    ui.open_refit_detail("Choose Parts")?;
    assert_viewport_part_name_hover(&mut ui, 0, &["1 · Body", "0: Body"])?;
    ui.click("Fit")?;
    refit_feedback_reply(&mut ui, "Fit to body", false,
        "Fit to body: Part 1 still intersects Part 2 beneath its triangles; previous preview retained")?;
    assert_viewport_part_name_hover(&mut ui, 1, &["2 · Sleeve"])?;
    assert_eq!(ui.application.cdmw_refit_highlight_parts(), vec![1, 2]);
    ui.application.cdmw_refit_feedback = None;
    ui.application.cdmw_state["mesh_islands"] = json!({"fit_parts": [{"index": 1,
        "name": "Sleeve", "islands": [{"faces": [0]}]}]});
    ui.choose("Editing", "Selected garments · 1", "Selected mesh islands")?;
    ui.open_refit_detail("Choose mesh islands")?;
    assert_viewport_part_name_hover(&mut ui, 1, &["2 · Sleeve"])?;
    Ok(())
}

#[test]
fn workflow_viewport_part_hover_uses_front_surfaces_and_respects_visibility_and_drags() -> TestResult {
    let mut application = overlapping_parts_application()?;
    application.camera.set_standard_view(StandardView::Back);
    application.mesh.as_mut().ok_or("mesh")?.set_selection(Selection {
        submeshes: HashSet::from([1]), ..Selection::default()
    })?;
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(application, egui::vec2(1440.0, 1200.0));
    let root = tempdir()?;
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(root.path().to_path_buf(), "viewport-part-hover", 2, 0));
    ui.application.camera.frame_all_in_viewport(ui.application.mesh.as_ref().ok_or("mesh")?,
        ui.application.viewport_rect.ok_or("viewport")?);
    let point = viewport_part_point(&ui, 0)?;
    ui.last_actions.clear();
    ui.frame(vec![Event::PointerMoved(point)]);
    ui.settle_layout();
    assert_eq!(ui.application.cdmw_viewport_hovered_part, Some(0));
    ui.application.camera.set_standard_view(StandardView::Front);
    ui.frame(vec![Event::PointerMoved(viewport_part_point(&ui, 1)?)]);
    assert_eq!(ui.application.cdmw_viewport_hovered_part, Some(1));
    ui.application.camera.set_standard_view(StandardView::Back);
    ui.frame(vec![Event::PointerMoved(point)]);
    assert_eq!(ui.application.cdmw_viewport_hovered_part, Some(0));
    // Hover ignores vertex/edge selection domains and X-ray's rear selection policy.
    ui.application.selection_domain = SelectionDomain::Edge;
    ui.application.selection_visible_only = false;
    ui.application.view_mode = ViewMode::XRay;
    ui.frame(Vec::new());
    assert_eq!(ui.application.cdmw_viewport_hovered_part, Some(0));
    ui.application.handle_actions(vec![UiAction::SetPartVisibility { indices: vec![0], visible: false }]);
    ui.frame(Vec::new());
    assert_eq!(ui.application.cdmw_viewport_hovered_part, Some(1));
    assert!(part_name_has_viewport_outline(&ui, "1: Back"));
    ui.application.handle_actions(vec![UiAction::SetPartVisibility { indices: vec![0], visible: true }]);
    ui.frame(Vec::new());
    assert_eq!(ui.application.cdmw_viewport_hovered_part, Some(0));
    let source_faces = ui.application.mesh.as_ref().ok_or("mesh")?.faces().filter_map(|(_, face)| match face.provenance {
        Provenance::Source { submesh: 0, element } => Some(element), _ => None,
    }).collect();
    ui.application.handle_actions(vec![UiAction::SetIslandVisibility { part: 0, faces: source_faces, visible: false }]);
    ui.frame(Vec::new());
    assert_eq!(ui.application.cdmw_viewport_hovered_part, Some(1));
    ui.application.cdmw_state["geometry_layers"]["layers"].as_array_mut().ok_or("layers")?.push(
        json!({"layer_id": "back", "name": "Back", "submesh_indices": [1], "visible": false, "base": false}));
    ui.frame(Vec::new());
    assert!(ui.application.cdmw_viewport_hovered_part.is_none());
    ui.application.cdmw_state["geometry_layers"]["layers"][1]["visible"] = json!(true);
    ui.frame(Vec::new());
    assert_eq!(ui.application.cdmw_viewport_hovered_part, Some(1));
    ui.frame(vec![Event::PointerButton { pos: point, button: PointerButton::Secondary, pressed: true,
        modifiers: egui::Modifiers::NONE }]);
    assert!(ui.application.cdmw_viewport_hovered_part.is_none());
    assert!(!part_name_has_viewport_outline(&ui, "1: Back"));
    ui.frame(vec![Event::PointerButton { pos: point, button: PointerButton::Secondary, pressed: false,
        modifiers: egui::Modifiers::NONE }]);
    ui.settle_layout();
    assert_eq!(ui.application.cdmw_viewport_hovered_part, Some(1));
    ui.application.cdmw_state["morph_refit"]["corrections_enabled"] = json!(false);
    ui.frame(Vec::new());
    assert!(ui.application.cdmw_viewport_hovered_part.is_none());
    ui.application.cdmw_state["morph_refit"]["corrections_enabled"] = json!(true);
    let empty = ui.application.viewport_rect.ok_or("viewport")?.right_bottom() - egui::vec2(4.0, 4.0);
    ui.frame(vec![Event::PointerMoved(empty)]);
    assert!(ui.application.cdmw_viewport_hovered_part.is_none());
    assert_eq!(ui.application.selected_part_indices(), vec![1]);
    assert!(ui.last_actions.is_empty());
    assert!(ui.application.cdmw_pending_request.is_none());
    Ok(())
}

fn long_part_hover_ui() -> Result<HeadlessUi, Box<dyn std::error::Error>> {
    let mut ui = mixed_refit_ui(&[2])?;
    let document = Arc::make_mut(ui.application.document.as_mut().ok_or("document")?);
    let template = document.lods[0].submeshes[2].clone();
    for index in 3..60 {
        let mut piece = template.clone();
        piece.name = format!("Piece {index}");
        for position in &mut piece.positions { position[0] += (index - 2) as f32 * 3.0; }
        document.lods[0].submeshes.push(piece);
    }
    let mut mesh = WorkingMesh::from_document(document)?;
    mesh.set_selection(Selection { submeshes: HashSet::from([2]), ..Selection::default() })?;
    ui.application.mesh = Some(mesh);
    ui.application.projection = None;
    let refit = &mut ui.application.cdmw_state["morph_refit"]["refit"];
    refit["garment_submesh_indices"] = json!((1..60).collect::<Vec<u32>>());
    for index in 3..60 {
        refit["garment_settings"].as_array_mut().ok_or("garment settings")?.push(json!({
            "submesh_index": index, "enabled": true, "mode": "surface", "intensity_percent": 100.0,
            "clearance_percent": 0.1, "tightness_percent": 0.0 }));
    }
    ui.size = egui::vec2(1280.0, 800.0);
    ui.settle_layout();
    ui.type_number_in_row("Clearance %", 1.25, "0.75")?;
    ui.open_refit_detail("Choose garments")?;
    ui.application.camera.frame_all_in_viewport(ui.application.mesh.as_ref().ok_or("mesh")?,
        ui.application.viewport_rect.ok_or("viewport")?);
    ui.frame(Vec::new());
    Ok(ui)
}

#[test]
fn workflow_viewport_part_hover_scrolls_open_lists_and_keeps_selection_and_fit_edits() -> TestResult {
    let mut ui = long_part_hover_ui()?;
    let root = tempdir()?;
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(root.path().to_path_buf(), "hover-scroll", 2, 0));
    ui.scroll_tool_rail(-50_000.0);
    ui.scroll_inspector(-50_000.0);
    assert!(ui.label_rect("2 · Sleeve").is_none());
    assert!(ui.label_rect("1: Sleeve").is_none());
    let state = ui.application.cdmw_state.clone();
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?.clone();
    ui.last_actions.clear();
    ui.frame(vec![Event::PointerMoved(viewport_part_point(&ui, 1)?)]);
    ui.settle_layout();
    for name in ["2 · Sleeve", "1: Sleeve"] {
        assert!(part_name_has_viewport_outline(&ui, name), "offscreen name was not revealed: {name}");
    }
    let before = (ui.label_rect("2 · Sleeve"), ui.label_rect("1: Sleeve"));
    ui.settle_layout();
    assert_eq!((ui.label_rect("2 · Sleeve"), ui.label_rect("1: Sleeve")), before,
        "holding the pointer still must not keep repositioning the lists");
    assert!(ui.label_rect("60 · Piece 59").is_none());
    assert!(ui.label_rect("59: Piece 59").is_none());
    ui.frame(vec![Event::PointerMoved(viewport_part_point(&ui, 59)?)]);
    ui.settle_layout();
    for name in ["60 · Piece 59", "59: Piece 59"] {
        assert!(part_name_has_viewport_outline(&ui, name), "new hovered Part was not revealed: {name}");
    }
    assert_eq!(ui.application.cdmw_state, state);
    let current = ui.application.mesh.as_ref().ok_or("mesh")?;
    assert_eq!(current.selection, mesh.selection);
    assert_eq!(current.selection_revision, mesh.selection_revision);
    assert_eq!(current.structural_fingerprint(), mesh.structural_fingerprint());
    assert_eq!(ui.application.cdmw_refit_clearance, 0.75);
    assert!(ui.application.cdmw_refit_settings_dirty.is_dirty());
    assert!(ui.last_actions.is_empty());
    assert!(ui.application.cdmw_pending_request.is_none());
    Ok(())
}

#[test]
fn workflow_viewport_part_hover_scroll_cancels_stale_targets_and_yields_to_manual_scrolling() -> TestResult {
    let mut ui = long_part_hover_ui()?;
    let root = tempdir()?;
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(root.path().to_path_buf(), "hover-scroll", 2, 0));
    ui.reveal("2 · Sleeve")?;
    ui.reveal("1: Sleeve")?;
    let first = viewport_part_point(&ui, 1)?;
    let last = viewport_part_point(&ui, 59)?;
    assert!(ui.label_rect("60 · Piece 59").is_none());
    assert!(ui.label_rect("59: Piece 59").is_none());
    let before = (ui.label_rect("2 · Sleeve"), ui.label_rect("1: Sleeve"));
    ui.last_actions.clear();
    ui.frame(vec![Event::PointerMoved(last)]);
    ui.frame(vec![Event::PointerGone]);
    ui.settle_layout();
    assert!(ui.application.cdmw_part_name_scroll.is_none());
    assert_eq!((ui.label_rect("2 · Sleeve"), ui.label_rect("1: Sleeve")), before);
    ui.frame(vec![Event::PointerMoved(last)]);
    ui.frame(vec![Event::PointerMoved(first)]);
    ui.settle_layout();
    assert_eq!((ui.label_rect("2 · Sleeve"), ui.label_rect("1: Sleeve")), before);
    assert!(ui.label_rect("59: Piece 59").is_none());
    ui.frame(vec![Event::PointerMoved(last)]);
    ui.frame(vec![Event::PointerButton { pos: last, button: PointerButton::Secondary,
        pressed: true, modifiers: egui::Modifiers::NONE }]);
    ui.settle_layout();
    assert!(ui.application.cdmw_part_name_scroll.is_none());
    assert_eq!((ui.label_rect("2 · Sleeve"), ui.label_rect("1: Sleeve")), before);
    ui.frame(vec![Event::PointerButton { pos: last, button: PointerButton::Secondary,
        pressed: false, modifiers: egui::Modifiers::NONE }, Event::PointerMoved(first)]);
    ui.settle_layout();
    ui.frame(vec![Event::PointerMoved(last)]);
    ui.scroll_inspector(-50_000.0);
    assert!(ui.application.cdmw_part_name_scroll.is_none());
    assert!(ui.label_rect("59: Piece 59").is_some());
    assert_eq!(ui.label_rect("2 · Sleeve"), before.0, "manual Inspector scrolling must not move the fitting list");
    let manual = ui.label_rect("59: Piece 59");
    ui.settle_layout();
    assert_eq!(ui.label_rect("59: Piece 59"), manual);
    ui.open_refit_detail("Choose garments")?;
    ui.click("Back to Inspector")?;
    ui.frame(vec![Event::PointerMoved(last)]);
    ui.settle_layout();
    assert!(ui.label_rect("Back to Inspector").is_some(), "viewport hover must reopen the Parts list");
    assert!(part_name_has_viewport_outline(&ui, "59: Piece 59"));
    assert!(ui.label_rect("60 · Piece 59").is_none(), "closed garment list must stay closed");
    assert_eq!(ui.application.selected_part_indices(), vec![2]);
    assert!(ui.last_actions.is_empty());
    assert!(ui.application.cdmw_pending_request.is_none());
    Ok(())
}

#[test]
fn workflow_viewport_part_hover_opens_closed_parts_and_keeps_selection_and_fit_edits() -> TestResult {
    for closed in ["Inspector", "Collapsed", "Mesh islands"] {
        let mut ui = long_part_hover_ui()?;
        let root = tempdir()?;
        ui.application.cdmw_bridge = Some(CdmwBridge::for_test(root.path().to_path_buf(), "hover-open", 2, 0));
        ui.open_refit_detail("Choose garments")?;
        if closed == "Mesh islands" {
            ui.click("Mesh islands")?;
        } else {
            ui.click("Back to Inspector")?;
            if closed == "Collapsed" {
                let collapse = ui.sidebar_button("Collapse Inspector").ok_or("collapse")?;
                ui.click_at(collapse.rect.center());
                ui.settle_layout();
                assert!(ui.sidebar_button("Expand Inspector").is_some());
            }
            assert!(ui.application.cdmw_part_name_rows.is_empty(), "all Part name lists must start closed");
        }
        let state = ui.application.cdmw_state.clone();
        let mesh = ui.application.mesh.as_ref().ok_or("mesh")?.clone();
        let targets = ui.application.cdmw_refit_region_targets.clone();
        ui.last_actions.clear();
        ui.frame(vec![Event::PointerMoved(viewport_part_point(&ui, 59)?)]);
        ui.frame(Vec::new());
        assert!(ui.label_rect("Back to Inspector").is_some(), "Parts did not open from {closed}");
        // Expanding the sidebar changes the viewport size. Continue hovering
        // the same surface at its current projected position.
        ui.frame(vec![Event::PointerMoved(viewport_part_point(&ui, 59)?)]);
        ui.settle_layout();
        assert!(part_name_has_viewport_outline(&ui, "59: Piece 59"), "Part not revealed from {closed}");
        assert!(ui.label_rect("60 · Piece 59").is_none(), "collapsed fitting sections must stay closed");
        assert_eq!(ui.application.cdmw_state, state);
        let current = ui.application.mesh.as_ref().ok_or("mesh")?;
        assert_eq!(current.selection, mesh.selection);
        assert_eq!(current.selection_revision, mesh.selection_revision);
        assert_eq!(current.structural_fingerprint(), mesh.structural_fingerprint());
        assert_eq!(ui.application.cdmw_refit_region_targets, targets);
        assert_eq!(ui.application.cdmw_refit_clearance, 0.75);
        assert!(ui.application.cdmw_refit_settings_dirty.is_dirty());
        assert!(ui.last_actions.is_empty());
        assert!(ui.application.cdmw_pending_request.is_none());
        ui.click("Back to Inspector")?;
        ui.settle_layout();
        assert!(ui.label_rect("Back to Inspector").is_none(), "closing from the Inspector must remain possible");
    }
    Ok(())
}

#[test]
fn workflow_viewport_part_hover_leaves_closed_parts_alone_over_empty_space_and_during_drags() -> TestResult {
    let mut ui = mixed_refit_ui(&[2])?;
    ui.click("Back to Inspector")?;
    ui.application.camera.frame_all_in_viewport(ui.application.mesh.as_ref().ok_or("mesh")?,
        ui.application.viewport_rect.ok_or("viewport")?);
    let empty = ui.application.viewport_rect.ok_or("viewport")?.right_bottom() - egui::vec2(4.0, 4.0);
    ui.frame(vec![Event::PointerMoved(empty)]);
    ui.settle_layout();
    assert!(ui.label_rect("Back to Inspector").is_none());
    let point = viewport_part_point(&ui, 1)?;
    ui.frame(vec![Event::PointerMoved(point), Event::PointerButton { pos: point,
        button: PointerButton::Secondary, pressed: true, modifiers: egui::Modifiers::NONE }]);
    ui.settle_layout();
    assert!(ui.label_rect("Back to Inspector").is_none());
    ui.frame(vec![Event::PointerButton { pos: point, button: PointerButton::Secondary,
        pressed: false, modifiers: egui::Modifiers::NONE }, Event::PointerGone]);
    ui.settle_layout();
    assert!(ui.label_rect("Back to Inspector").is_none());
    assert_eq!(ui.application.selected_part_indices(), vec![2]);
    assert!(ui.application.cdmw_pending_request.is_none());
    Ok(())
}

#[test]
fn workflow_viewport_part_hover_scroll_keeps_a_visible_warning_name_in_place() -> TestResult {
    let mut ui = long_part_hover_ui()?;
    ui.application.egui_context.global_style_mut(|style| style.scroll_animation = egui::style::ScrollAnimation::none());
    refit_feedback_reply(&mut ui, "Fit to body", false,
        "Fit to body: Part 1 still intersects Part 2 beneath its triangles; previous preview retained")?;
    let before = ui.label_rect("2 · Sleeve").ok_or("visible warning name")?;
    ui.frame(vec![Event::PointerMoved(viewport_part_point(&ui, 1)?)]);
    ui.settle_layout();
    assert!(part_name_has_viewport_outline(&ui, "2 · Sleeve"));
    assert_eq!(ui.label_rect("2 · Sleeve"), Some(before),
        "a second offscreen name for the same Part must not scroll past the visible warning");
    assert_eq!(ui.application.cdmw_refit_highlight_parts(), vec![1, 2]);
    assert_eq!(ui.application.selected_part_indices(), vec![2]);
    assert_eq!(ui.application.cdmw_refit_clearance, 0.75);
    assert!(ui.application.cdmw_refit_settings_dirty.is_dirty());
    assert!(ui.application.cdmw_pending_request.is_none());
    Ok(())
}

#[test]
fn workflow_part_colours_toggle_restores_display_and_preserves_fit_edits() -> TestResult {
    let mut ui = mixed_refit_ui(&[1])?;
    let root = tempdir()?;
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(root.path().to_path_buf(), "part-colours-ui", 2, 0));
    ui.application.view_mode = ViewMode::SolidWire;
    ui.type_number_in_row("Clearance %", 0.5, "0.75")?;
    let state = ui.application.cdmw_state.clone();
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?.clone();
    assert!(ui.actions_from_click("Part colors")?.is_empty());
    assert_eq!(ui.application.view_mode, ViewMode::PartId);
    assert!(ui.application.cdmw_part_colours_active());
    assert!(ui.application.cdmw_part_colours_applied);
    for tab in ["Shape", "Saved", "Setup", "Fit"] {
        ui.click(tab)?;
        assert_eq!(ui.application.view_mode, ViewMode::PartId);
        ui.reveal("Part colors")?;
    }
    assert!(ui.actions_from_click("Part colors")?.is_empty());
    assert_eq!(ui.application.view_mode, ViewMode::SolidWire);
    assert!(!ui.application.cdmw_part_colours_applied);
    assert_eq!(ui.application.cdmw_state, state);
    let current = ui.application.mesh.as_ref().ok_or("mesh")?;
    assert_eq!(current.structural_fingerprint(), mesh.structural_fingerprint());
    assert_eq!(current.selection, mesh.selection);
    assert_eq!(ui.application.cdmw_refit_clearance, 0.75);
    assert!(ui.application.cdmw_refit_settings_dirty.is_dirty());
    Ok(())
}

#[test]
fn workflow_part_colour_swatches_match_the_viewport_and_follow_the_mode() -> TestResult {
    fn swatch(ui: &HeadlessUi, label: &str, part: u32) -> Result<egui::Rect, Box<dyn std::error::Error>> {
        let text = ui.label_rect(label).ok_or_else(|| format!("missing Part label {label}"))?;
        let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
        let snapshot = mesh.draw_snapshot();
        let colours = viewport::part_colour_snapshot(mesh, None, &snapshot);
        let colour = mesh.faces().zip(snapshot.indices.chunks_exact(3))
            .find(|((_, face), _)| face.submesh == part)
            .map(|(_, triangle)| colours[triangle[0] as usize]).ok_or("Part colour")?;
        let expected = Color32::from(egui::Rgba::from_rgb(colour[0], colour[1], colour[2]));
        ui.output.shapes.iter().find_map(|shape| match &shape.shape {
            egui::Shape::Rect(swatch) if swatch.fill == expected
                && (swatch.rect.size() - egui::vec2(10.0, 10.0)).length() < 1.0 => {
                let rect = swatch.rect;
                (shape.clip_rect.intersects(rect) && (rect.center().y - text.center().y).abs() < 3.0
                    && rect.right() <= text.left() && text.left() - rect.right() < 12.0).then_some(rect)
            }
            _ => None,
        }).ok_or_else(|| {
            let nearby = ui.output.shapes.iter().filter_map(|shape| match &shape.shape {
                egui::Shape::Rect(rect) if (rect.rect.center().y - text.center().y).abs() < 3.0 =>
                    Some((rect.rect, rect.fill)),
                _ => None,
            }).take(8).collect::<Vec<_>>();
            format!("missing matching swatch beside {label}: text={text:?}, expected={expected:?}, nearby={nearby:?}").into()
        })
    }
    let mut ui = mixed_refit_ui(&[2])?;
    let root = tempdir()?;
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(root.path().to_path_buf(), "part-swatch-ui", 2, 0));
    ui.open_refit_detail("Choose garments")?;
    ui.reveal("2 · Sleeve")?;
    assert!(swatch(&ui, "2 · Sleeve", 1).is_err());
    ui.click("Part colors")?;
    ui.reveal("2 · Sleeve")?;
    swatch(&ui, "2 · Sleeve", 1)?;
    swatch(&ui, "3 · Plate", 2)?;
    swatch(&ui, "0: Body", 0)?;
    ui.click("Setup")?;
    ui.open_refit_detail("Choose Parts")?;
    ui.reveal("1 · Body")?;
    swatch(&ui, "1 · Body", 0)?;
    ui.click("Fit")?;
    refit_feedback_reply(&mut ui, "Fit to body", false,
        "Fit to body: Part 1 still intersects Part 2 beneath its triangles; previous preview retained")?;
    ui.reveal("2 · Sleeve")?;
    let badge = swatch(&ui, "2 · Sleeve", 1)?;
    let root = tempdir()?;
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(root.path().to_path_buf(), "refit-feedback-ui", 2, 0));
    ui.click_at(badge.center());
    assert_eq!(ui.application.selected_part_indices(), vec![1]);
    refit_feedback_reply(&mut ui, "Select parts", true, "")?;
    ui.click("Part colors")?;
    ui.reveal("2 · Sleeve")?;
    assert!(swatch(&ui, "2 · Sleeve", 1).is_err());
    Ok(())
}

#[test]
fn workflow_part_colours_distinguish_shared_materials_and_stay_stable_when_hidden() -> TestResult {
    let ui = super::morph_authoring::authoring_ui()?;
    let mut mesh = ui.application.mesh.as_ref().ok_or("mesh")?.clone();
    let original = mesh.structural_fingerprint();
    let snapshot = mesh.draw_snapshot();
    let colours = viewport::part_colour_snapshot(&mesh, None, &snapshot);
    let mut by_part = HashMap::new();
    for ((_, face), triangle) in mesh.faces().zip(snapshot.indices.chunks_exact(3)) {
        let colour = colours[triangle[0] as usize];
        assert!(triangle.iter().all(|index| colours[*index as usize] == colour));
        assert!(by_part.insert(face.submesh, (colour, face.material))
            .is_none_or(|previous| previous == (colour, face.material)));
    }
    assert_ne!(by_part[&1].0, by_part[&2].0);
    let faces = mesh.faces().filter(|(_, face)| face.submesh == 1).map(|(handle, _)| handle).collect();
    let generated = mesh.duplicate_faces_to_new_submesh(&faces)?;
    let hidden = mesh.faces().filter(|(_, face)| face.submesh == 0).map(|(handle, _)| handle).collect();
    mesh.set_viewport_hidden_faces(hidden)?;
    let visible = HashSet::from([0, 2, 3]);
    let snapshot = mesh.draw_snapshot_for_submeshes(&visible);
    let colours = viewport::part_colour_snapshot(&mesh, Some(&visible), &snapshot);
    assert_eq!(colours.len(), snapshot.positions.len());
    let elements = mesh.element_handles_for_submeshes(&visible);
    for ((handle, face), triangle) in mesh.faces().filter(|(handle, _)| elements.faces.contains(handle))
        .zip(snapshot.indices.chunks_exact(3))
    {
        let colour = colours[triangle[0] as usize];
        assert!(triangle.iter().all(|index| colours[*index as usize] == colour));
        assert_ne!(face.submesh, 0, "hidden islands stay hidden");
        if face.submesh == 2 { assert_eq!(colour, by_part[&2].0); }
        if generated.contains(&handle) {
            assert_ne!(colour, by_part[&1].0);
            assert_eq!(face.material, by_part[&1].1, "new and original Parts share a material");
        }
    }
    assert_eq!(ui.application.mesh.as_ref().ok_or("mesh")?.structural_fingerprint(), original);
    Ok(())
}

fn refit_feedback_reply(ui: &mut HeadlessUi, label: &'static str, ok: bool, error: &str) -> TestResult {
    let root = tempdir()?;
    let revision = ui.application.cdmw_state["base_revision"].as_u64().unwrap_or(0);
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(
        root.path().to_path_buf(), "refit-feedback-ui", 2, revision,
    ));
    let selection = ok && label == "Select parts";
    ui.application.cdmw_pending_request = Some(CdmwPendingRequest {
        request_id: 1, event: "command_result", label: label.to_owned(),
        origin: selection.then_some(CdmwRequestOrigin::Selection),
    });
    let mut state = ui.application.cdmw_state.clone();
    state["session_id"] = json!("refit-feedback-ui");
    let reply_revision = revision + u64::from(selection);
    state["base_revision"] = json!(reply_revision);
    if selection {
        // State snapshots refresh this watermark even for selection-only commands.
        let morph_revision = state["morph_refit"]["state_revision"].as_u64().unwrap_or(0);
        state["morph_refit"]["state_revision"] = json!(morph_revision + 1);
    }
    state["selection"] = json!({
        "vertices_by_submesh": {}, "edges_by_submesh": {}, "faces_by_submesh": {},
        "source_indices": ui.application.selected_part_indices(),
    });
    ui.application.handle_cdmw_result("command_result", 1, reply_revision, ok,
        json!({"state": state, "result": {"status": "noop"}}), error);
    assert!(ui.application.cdmw_pending_request.is_none(), "{}", ui.application.status);
    ui.settle_layout();
    Ok(())
}

#[test]
fn workflow_refit_refusal_shows_targeted_guidance_and_expandable_details() -> TestResult {
    for (error, protected, reason, hint) in [
        ("mesh-editor-session-json: inline status error: Fit to body: Part 1 still intersects Part 2 beneath its triangles; previous preview retained",
            false, "Garment layers overlap.", "Try 0.1% Clearance or lower Tightness, then Apply."),
        ("Fit to body: Part 1, triangle 224 would contain a spike, inverted or collapsed triangle after conforming (orientation -0.688139); previous preview retained",
            false, "Fitting would fold or damage the mesh.", "Lower Tightness, then Apply. Keep loose trim at 0%."),
        ("Fit to body: Part 1, vertex 12 cannot clear the body with its current protection mask or geometry (gap -0.001, requested 0.000)",
            true, "Garment intersects the body.", "Reduce local protection or adjust the garment position, then retry."),
        ("Fit to body: Part 1, vertex 12 cannot clear the body with its current protection mask or geometry (gap -0.001, requested 0.000)",
            false, "Garment intersects the body.", "Try 0.1% Clearance or lower Tightness, then Apply."),
    ] {
        let mut ui = mixed_refit_ui(&[1])?;
        ui.application.cdmw_state["morph_refit"]["refit"]["garment_settings"][0]["clearance_percent"] = json!(0.0);
        ui.application.cdmw_state["morph_refit"]["refit"]["garment_settings"][0]["has_vertex_mask"] = json!(protected);
        ui.type_number_in_row("Tightness %", 25.0, "64")?;
        ui.size = egui::vec2(1000.0, 700.0);
        ui.settle_layout();
        ui.scroll_tool_rail(-2_000.0);
        let settings = ui.application.cdmw_state["morph_refit"]["refit"].clone();
        let mesh = ui.application.mesh.as_ref().ok_or("mesh")?.structural_fingerprint();
        refit_feedback_reply(&mut ui, "Apply garment refit settings", false, error)?;
        assert!(ui.label_rect("Fit blocked · preview kept").is_some(), "refusal should reveal its guidance");
        ui.reveal(reason)?;
        ui.reveal(hint)?;
        ui.reveal("2 · Sleeve")?;
        if error.contains("Part 2") { ui.reveal("3 · Plate")?; }
        assert!(ui.label_rect(error).is_none(), "raw error should be collapsed");
        ui.click("Fit details")?;
        ui.reveal(error)?;
        assert_eq!(ui.application.cdmw_state["morph_refit"]["refit"], settings);
        assert_eq!(ui.application.mesh.as_ref().ok_or("mesh")?.structural_fingerprint(), mesh);
        assert_eq!(ui.application.cdmw_refit_tightness, 64.0);
        assert!(ui.application.cdmw_refit_settings_dirty.is_dirty());
    }
    Ok(())
}

#[test]
fn workflow_refit_guidance_survives_selection_and_clears_after_fit_or_reset() -> TestResult {
    for success in ["Fit to body", "Apply garment refit settings", "Reset morph"] {
        let mut ui = mixed_refit_ui(&[1])?;
        refit_feedback_reply(&mut ui, "Fit to body", false,
            "Fit to body: Part 1 cannot clear Part 2 beneath its triangles; previous preview retained")?;
        ui.reveal("Increase Clearance or lower Tightness, then Apply.")?;
        refit_feedback_reply(&mut ui, "Select parts", true, "")?;
        ui.reveal("Fit blocked · preview kept")?;
        refit_feedback_reply(&mut ui, success, true, "")?;
        assert!(ui.application.cdmw_refit_feedback.is_none());
        assert!(ui.label_rect("Fit blocked · preview kept").is_none());
    }
    let mut ui = mixed_refit_ui(&[1])?;
    refit_feedback_reply(&mut ui, "Apply garment refit settings", false, "Host connection unavailable")?;
    assert!(ui.application.cdmw_refit_feedback.is_none());
    assert!(ui.application.status.contains("Host connection unavailable"));
    refit_feedback_reply(&mut ui, "Fit to body", false,
        "Fit to body: Part 1 still intersects Part 2 beneath its triangles")?;
    ui.application.cdmw_state["morph_refit"]["state_revision"] = json!(12);
    refit_feedback_reply(&mut ui, "Select parts", true, "")?;
    assert!(ui.application.cdmw_refit_feedback.is_none());
    Ok(())
}

#[test]
fn workflow_refit_warning_highlights_without_selecting_and_selects_from_the_warning() -> TestResult {
    for (button, expected) in [
        ("Select affected parts", vec![1, 2]), ("2 · Sleeve", vec![1]), ("3 · Plate", vec![2]),
    ] {
        let mut ui = mixed_refit_ui(&[0])?;
        refit_feedback_reply(&mut ui, "Fit to body", false,
            "Fit to body: Part 1 still intersects Part 2 beneath its triangles; previous preview retained")?;
        assert_eq!(ui.application.selected_part_indices(), vec![0]);
        assert_eq!(ui.application.cdmw_refit_highlight_parts(), vec![1, 2]);
        ui.application.refresh_cdmw_refit_overlay();
        let before = ui.application.mesh.as_ref().ok_or("mesh")?.structural_fingerprint();
        ui.reveal(button)?;
        let actions = ui.actions_from_click(button)?;
        assert!(actions.iter().any(|action| matches!(action,
            UiAction::SetPartSelection(parts) if parts == &expected)), "{actions:?}");
        // Keep the real selection-command bridge alive after delivering the refusal.
        let root = tempdir()?;
        let revision = ui.application.cdmw_state["base_revision"].as_u64().unwrap_or(0);
        ui.application.cdmw_bridge = Some(CdmwBridge::for_test(root.path().to_path_buf(), "refit-feedback-ui", 2, revision));
        ui.application.handle_actions(actions);
        assert_eq!(ui.application.selected_part_indices(), expected);
        assert_eq!(ui.application.cdmw_pending_request.as_ref().map(|request| &request.origin),
            Some(&Some(CdmwRequestOrigin::Selection)));
        assert_eq!(ui.application.mesh.as_ref().ok_or("mesh")?.structural_fingerprint(), before);
        refit_feedback_reply(&mut ui, "Select parts", true, "")?;
        assert_eq!(ui.application.cdmw_refit_highlight_parts(), vec![1, 2]);
        ui.reveal("Fit blocked · preview kept")?;
    }
    Ok(())
}

#[test]
fn workflow_refit_warning_highlight_obeys_toggle_visibility_and_preview_lifetime() -> TestResult {
    let mut ui = mixed_refit_ui(&[0])?;
    refit_feedback_reply(&mut ui, "Fit to body", false,
        "Fit to body: Parts 1, 2 cannot preserve their garment layer separation")?;
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    let sleeve = &ui.application.document.as_ref().ok_or("document")?.lods[0].submeshes[1];
    let expected = sleeve.indices.iter().map(|index| sleeve.positions[*index as usize]).collect::<Vec<_>>();
    let colour = [1.0, 0.35, 0.06, 0.45];
    let overlay = FaceSelectionOverlay::build_for_parts(mesh, Some(HashSet::from([0, 1])), colour, &[1, 2]);
    assert_eq!(overlay.positions, expected);
    assert!(!overlay.positions.is_empty());
    let sleeve_faces = mesh.faces().filter(|(_, face)| face.submesh == 1).map(|(handle, _)| handle).collect();
    ui.application.mesh.as_mut().ok_or("mesh")?.set_viewport_hidden_faces(sleeve_faces)?;
    assert!(FaceSelectionOverlay::build_for_parts(ui.application.mesh.as_ref().ok_or("mesh")?,
        Some(HashSet::from([0, 1])), colour, &[1, 2]).positions.is_empty());
    ui.click("Highlight in viewport")?;
    assert!(ui.application.cdmw_refit_highlight_parts().is_empty());
    assert_eq!(ui.application.selected_part_indices(), vec![0]);
    ui.click("Highlight in viewport")?;
    assert_eq!(ui.application.cdmw_refit_highlight_parts(), vec![1, 2]);
    ui.application.set_cdmw_part_visibility(vec![2], false);
    let actions = ui.actions_from_click("Select affected parts")?;
    assert!(actions.iter().any(|action| matches!(action,
        UiAction::SetPartVisibility { indices, visible: true } if indices == &[1, 2])));
    ui.application.cdmw_bridge = None;
    ui.application.handle_actions(actions);
    assert!(!ui.application.cdmw_hidden_parts.contains(&2));
    assert_eq!(ui.application.selected_part_indices(), vec![1, 2]);
    ui.application.active_lod_index += 1;
    assert!(ui.application.cdmw_refit_highlight_parts().is_empty());
    ui.application.refresh_cdmw_refit_overlay();
    Ok(())
}

#[test]
fn workflow_refit_warning_never_selects_unknown_parts_or_guesses_missing_locations() -> TestResult {
    for error in ["Fit to body: clearance displacement solve did not converge",
        "Fit to body: Part 999, triangle 1 would collapse; previous preview retained"] {
        let mut ui = mixed_refit_ui(&[0])?;
        refit_feedback_reply(&mut ui, "Fit to body", false, error)?;
        assert!(ui.application.cdmw_refit_highlight_parts().is_empty());
        assert!(ui.label_rect("Select affected parts").is_none());
        assert_eq!(ui.application.selected_part_indices(), vec![0]);
    }
    Ok(())
}

#[test]
fn workflow_refit_fresh_tightness_shows_the_default_and_can_explicitly_choose_zero() -> TestResult {
    let mut ui = mixed_refit_ui(&[1])?;
    ui.application.cdmw_state["morph_refit"]["refit"]["garment_settings"][0]["tightness_percent"] = json!(0.0);
    ui.application.cdmw_state["morph_refit"]["refit"]["garment_settings"][0]["tightness_initialized"] = json!(false);
    ui.application.cdmw_state["morph_refit"]["state_revision"] = json!(2);
    ui.frame(Vec::new());
    assert_eq!(ui.application.cdmw_refit_tightness, 100.0);
    ui.type_number_in_row("Tightness %", 100.0, "0")?;
    assert_eq!(refit_arguments(&ui.actions_from_click("Apply to Selected Garments")?), json!({
        "submesh_indices": [1], "tightness_percent": 0.0,
    }));

    for initialized in [Some(true), None] {
        let mut saved = mixed_refit_ui(&[1])?;
        let settings = &mut saved.application.cdmw_state["morph_refit"]["refit"]["garment_settings"][0];
        settings["tightness_percent"] = json!(0.0);
        if let Some(initialized) = initialized {
            settings["tightness_initialized"] = json!(initialized);
        } else {
            settings.as_object_mut().ok_or("settings")?.remove("tightness_initialized");
        }
        saved.application.cdmw_state["morph_refit"]["state_revision"] = json!(2);
        saved.frame(Vec::new());
        assert_eq!(saved.application.cdmw_refit_tightness, 0.0);
        assert!(!has_host_command(&saved.actions_from_click("Apply to Selected Garments")?, "refit_configure"));
    }
    Ok(())
}

#[test]
fn workflow_refit_mixed_clearance_dispatches_only_changed_fields_to_selected_or_all() -> TestResult {
    for (selected, button, expected) in [
        (vec![1, 2], "Apply to Selected Garments", vec![1, 2]),
        (vec![1], "Apply to Selected Garments", vec![1]),
        (vec![1], "Apply to All Bound Garments", vec![1, 2]),
        (vec![], "Apply to All Bound Garments", vec![1, 2]),
    ] {
        let mut ui = mixed_refit_ui(&selected)?;
        ui.refit_scope(button == "Apply to All Bound Garments")?;
        assert!(!has_host_command(&ui.actions_from_click(button)?, "refit_configure"));
        if expected.len() != 1 {
            ui.reveal("Use displayed clearance")?;
        }
        ui.type_number_in_row("Clearance %", 0.5, "0.75")?;
        // A resident refresh must update untouched fields without adding them
        // to the outgoing patch or discarding the user's clearance edit.
        ui.application.cdmw_state["morph_refit"]["state_revision"] = json!(2);
        ui.application.cdmw_state["morph_refit"]["refit"]["garment_settings"][0]["intensity_percent"] = json!(48.0);
        ui.frame(Vec::new());
        assert_eq!(ui.application.cdmw_refit_clearance, 0.75);
        assert_eq!(ui.application.cdmw_refit_intensity, 48.0);
        assert_eq!(refit_arguments(&ui.actions_from_click(button)?), json!({
            "submesh_indices": expected, "clearance_percent": 0.75,
        }));
    }
    Ok(())
}

#[test]
fn workflow_refit_mixed_values_require_an_explicit_field_choice() -> TestResult {
    for (button, field, value) in [
        ("Use displayed following", "intensity_percent", json!(37.0)),
        ("Use displayed tightness", "tightness_percent", json!(25.0)),
        ("Use displayed clearance", "clearance_percent", json!(0.5)),
    ] {
        let mut ui = mixed_refit_ui(&[1, 2])?;
        if field == "intensity_percent" { ui.open_refit_detail("Follow body shape")?; }
        ui.click(button)?;
        let mut expected = json!({"submesh_indices": [1, 2]});
        expected[field] = value;
        assert_eq!(refit_arguments(&ui.actions_from_click("Apply to Selected Garments")?), expected);
    }
    let mut ui = mixed_refit_ui(&[1, 2])?;
    let mode = ui.reveal("Fit as")?;
    ui.click_where("Mixed", |rect| (rect.center().y - mode.center().y).abs() < 20.0)?;
    // Surface is already the first Part's value. Clicking it must still
    // explicitly resolve the mixed selection to Surface.
    ui.click("Flexible")?;
    assert_eq!(refit_arguments(&ui.actions_from_click("Apply to Selected Garments")?),
        json!({"submesh_indices": [1, 2], "mode": "surface"}));
    let mut ui = mixed_refit_ui(&[1, 2])?;
    ui.click("Refit enabled")?;
    assert_eq!(refit_arguments(&ui.actions_from_click("Apply to Selected Garments")?),
        json!({"submesh_indices": [1, 2], "enabled": true}));
    Ok(())
}

#[test]
fn workflow_refit_selection_change_discards_draft_even_when_first_part_is_unchanged() -> TestResult {
    let mut ui = mixed_refit_ui(&[1])?;
    ui.type_number_in_row("Clearance %", 0.5, "0.75")?;
    assert!(ui.application.cdmw_refit_settings_dirty.is_dirty());
    ui.application.mesh.as_mut().ok_or("mesh")?.set_selection(Selection {
        submeshes: [1, 2].into_iter().collect(),
        ..Selection::default()
    })?;
    ui.frame(Vec::new());
    assert!(!ui.application.cdmw_refit_settings_dirty.is_dirty());
    assert_eq!(ui.application.cdmw_refit_clearance, 0.5);
    ui.reveal("Use displayed clearance")?;
    assert!(!has_host_command(&ui.actions_from_click("Apply to Selected Garments")?, "refit_configure"));
    Ok(())
}

#[test]
fn workflow_tabs_show_only_the_selected_task_and_keep_drafts() -> TestResult {
    let mut ui = super::morph_authoring::authoring_ui()?;
    ui.reveal("Load body...")?;
    assert!(ui.label_rect("Fit all enabled garments").is_none());
    ui.click("Fit")?;
    ui.reveal("Fit all enabled garments")?;
    assert!(ui.label_rect("Load body...").is_none());
    ui.type_number_in_row("Clearance %", 0.0, "1.375")?;
    ui.open_morph_creator(false)?;
    ui.application.cdmw_morph_definition_label = "Retained slider".into();
    ui.reveal("Rule")?;
    ui.open_morph_saved("Fitting setups")?;
    ui.reveal("Load fitting setup...")?;
    assert!(ui.label_rect("Load Preset...").is_none());
    ui.click("Fit")?;
    assert_eq!(ui.application.cdmw_refit_clearance, 1.375);
    assert!(ui.application.cdmw_refit_settings_dirty.is_dirty());
    ui.click("Shape")?;
    ui.reveal("Retained slider")?;
    ui.click_tool_button("Morph & Refit")?;
    ui.click_tool_button("Morph & Refit")?;
    ui.reveal("Retained slider")?;
    Ok(())
}

#[test]
fn workflow_actions_stay_visible_across_tabs_and_panel_presentations() -> TestResult {
    for presentation in ["expanded", "pinned", "floating"] {
        let mut ui = super::morph_authoring::authoring_ui()?;
        ui.size = egui::vec2(1000.0, 650.0);
        ui.application.apply_cdmw_theme_payload(&json!({"font_point_size":18.0,"density":"comfortable"}));
        ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(true);
        ui.settle_layout();
        if presentation != "expanded" {
            ui.click_sidebar("Collapse Tools")?;
            ui.click_sidebar("Morph & Refit")?;
            if presentation == "pinned" {
                ui.click_sidebar("Pin Morph & Refit settings")?;
            }
        }
        for tab in ["Setup", "Fit", "Shape", "Saved"] {
            ui.click(tab)?;
            for delta in [-2_000.0, 2_000.0] {
                if presentation == "floating" {
                    ui.scroll_tool_window("Morph & Refit", delta)?;
                } else {
                    ui.scroll_tool_rail(delta);
                }
                for label in ["Reset", "Bake"] {
                    let rect = ui.label_rect(label).ok_or_else(|| format!("{presentation}/{tab}: {label} scrolled away"))?;
                    assert!(rect.bottom() <= ui.size.y, "{presentation}: footer outside window");
                }
            }
            assert!(has_host_command(&ui.actions_from_click("Bake")?, "morph_bake"));
        }
        ui.application.cdmw_state["morph_refit"]["correction_definition_id"] = json!("body-shape");
        ui.frame(Vec::new());
        ui.click("Setup")?;
        assert!(ui.label_rect("Bake").is_none());
        assert!(has_host_command(&ui.actions_from_click("Save correction")?, "morph_save_correction"));
        assert!(has_host_command(&ui.actions_from_click("Cancel")?, "morph_cancel_correction"));
        ui.application.cdmw_state["morph_refit"]["correction_definition_id"] = json!("");
        ui.application.cdmw_state["morph_refit"]["authoring_baseline_ready"] = json!(true);
        ui.settle_layout();
        for label in ["Save slider", "Discard base"] {
            let rect = ui.label_rect(label).ok_or_else(|| format!("{presentation}: missing {label}"))?;
            assert!(rect.bottom() <= ui.size.y, "{presentation}: pending slider footer outside window");
        }
    }
    Ok(())
}

#[test]
fn workflow_pending_slider_can_be_reopened_and_footer_observes_authoring_policy() -> TestResult {
    let mut ui = super::morph_authoring::authoring_ui()?;
    ui.open_morph_creator(true)?;
    ui.application.cdmw_state["morph_refit"]["authoring_baseline_ready"] = json!(true);
    ui.application.cdmw_morph_definition_label = "Pending shape".into();
    ui.frame(Vec::new());
    ui.click("Setup")?;
    assert!(ui.actions_from_click("Load garments...")?.is_empty());
    ui.click("Choose Parts")?;
    ui.click("2 · Sleeve")?;
    assert_eq!(ui.application.selected_part_indices(), vec![1]);
    ui.open_morph_creator(true)?;
    ui.reveal("Pending shape")?;
    ui.open_morph_saved("Profiles")?;
    assert!(ui.actions_from_click("Save Profile")?.is_empty());
    assert!(has_host_command(&ui.actions_from_click("Save slider")?, "morph_capture_authored"));
    ui.application.cdmw_state["authoring_enabled"] = json!(false);
    ui.frame(Vec::new());
    assert!(ui.actions_from_click("Save slider")?.is_empty());
    assert!(ui.actions_from_click("Discard base")?.is_empty());
    ui.application.cdmw_state["morph_refit"]["authoring_baseline_ready"] = json!(false);
    ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(true);
    ui.frame(Vec::new());
    assert!(ui.actions_from_click("Bake")?.is_empty());
    assert!(ui.actions_from_click("Reset")?.is_empty());
    ui.application.cdmw_state["authoring_enabled"] = json!(true);
    ui.application.cdmw_state["morph_refit"]["available"] = json!(false);
    ui.frame(Vec::new());
    assert!(ui.actions_from_click("Bake")?.is_empty());
    assert!(ui.actions_from_click("Reset")?.is_empty());
    Ok(())
}

#[test]
fn workflow_compact_sections_keep_order_captured_targets_and_active_summaries() -> TestResult {
    let mut ui = super::morph_authoring::authoring_ui()?;
    let body = ui.reveal("1 · Body")?;
    let garments = ui.reveal("2 · Garments")?;
    let binding = ui.reveal("3 · Bind to body")?;
    assert!(body.bottom() < garments.top() && garments.bottom() < binding.top());
    assert!(ui.label_rect("Set body from selection").is_none());
    ui.click("Continue to Fit")?;
    let fit = ui.reveal("Fit all enabled garments")?;
    assert!(fit.bottom() < ui.reveal("Adjust garments")?.top());
    assert!(ui.label_rect("Selected influence").is_none());
    assert!(ui.label_rect("Use selected body region").is_none());
    assert!(ui.label_rect("Body-shape following %").is_none());
    ui.click("Review parts")?;
    ui.click("3 · Plate")?;
    ui.open_refit_detail("Body region")?;
    ui.click("Use editing targets")?;
    assert_eq!(ui.application.cdmw_refit_region_targets, vec![2]);
    ui.click("Select body")?;
    assert_eq!(ui.application.selected_part_indices(), vec![0]);
    assert_eq!(ui.application.cdmw_refit_region_targets, vec![2]);
    // A body selection must never silently broaden garment settings to all.
    assert!(ui.actions_from_click("Apply to Selected Garments")?.is_empty());
    ui.application.cdmw_state["morph_refit"]["refit"]["garment_regions"] =
        json!([[2, [{"submesh_index": 0, "vertex_count": 3}]]]);
    ui.application.cdmw_state["morph_refit"]["refit"]["garment_settings"][1]["has_vertex_mask"] = json!(true);
    ui.frame(Vec::new());
    ui.open_refit_detail("Body region")?;
    ui.reveal("Body region · 1 restricted Parts")?;
    ui.reveal("Local influence · 1 masked Parts")?;
    assert!(ui.label_rect("Use selected body region").is_none());
    assert!(ui.label_rect("Selected influence").is_none());
    ui.click("Setup")?;
    ui.click("Fit")?;
    assert_eq!(ui.application.cdmw_refit_region_targets, vec![2]);
    Ok(())
}

#[test]
fn workflow_compact_fit_long_names_and_scope_stay_inside_narrow_panels() -> TestResult {
    for presentation in ["expanded", "pinned", "floating"] {
        let mut ui = super::morph_authoring::authoring_ui()?;
        ui.size = egui::vec2(1000.0, 750.0);
        ui.application.apply_cdmw_theme_payload(&json!({"font_point_size": 18.0, "density": "comfortable"}));
        Arc::make_mut(ui.application.document.as_mut().ok_or("document")?).lods[0].submeshes[2].name =
            "CD_PHM_00_Vest_Acc_0013_long_material_and_part_name".into();
        ui.settle_layout();
        if presentation != "expanded" {
            ui.click_sidebar("Collapse Tools")?;
            ui.click_sidebar("Morph & Refit")?;
            if presentation == "pinned" { ui.click_sidebar("Pin Morph & Refit settings")?; }
        }
        ui.settle_layout();
        let setup = ui.reveal("Setup")?;
        ui.click_where("Fit", |rect| (rect.center().y - setup.center().y).abs() < setup.height())?;
        ui.click("Review parts")?;
        if presentation == "floating" { ui.scroll_tool_window("Morph & Refit", -200.0)?; }
        else { ui.scroll_tool_rail(-200.0); }
        let right = if presentation == "floating" { ui.tool_window_rect("Morph & Refit")?.right() }
            else { ui.application.viewport_rect.ok_or("viewport")?.left() };
        for clipped in &ui.output.shapes {
            if let egui::Shape::Text(text) = &clipped.shape {
                let rect = text.visual_bounding_rect();
                if clipped.clip_rect.width() > 100.0 && clipped.clip_rect.right() <= right + 5.0
                    && rect.intersects(clipped.clip_rect) {
                    assert!(rect.right() <= clipped.clip_rect.right() + 1.0,
                        "{presentation}: {:?} clips horizontally", text.galley.job.text);
                }
            }
        }
    }
    Ok(())
}

#[test]
fn workflow_compact_sections_localize_and_dispatch_in_every_builtin_language() -> TestResult {
    let resources = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../../cdmw/resources/localization");
    for code in ["en", "de", "es-ES", "es-419", "fr", "it", "pt-BR", "pl", "ru", "tr", "ja", "ko", "zh-Hans", "zh-Hant"] {
        let mut ui = super::morph_authoring::authoring_ui()?;
        let catalog: Value = serde_json::from_slice(&std::fs::read(resources.join(format!("{code}.json")))?)?;
        let translations = &catalog["translations"];
        ui.application.apply_cdmw_theme_payload(&json!({"language": code, "translations": translations}));
        ui.settle_layout();
        for source in ["1 · Body", "2 · Garments", "3 · Bind to body"] {
            let text = translations[source].as_str().ok_or("missing section translation")?;
            ui.reveal(text)?;
            if code != "en" { assert_ne!(text, source, "{code}: untranslated {source}"); }
        }
        ui.click(translations["Continue to Fit"].as_str().ok_or("continue translation")?)?;
        for source in ["Fit the outfit", "Adjust garments", "Choose garments"] {
            ui.reveal(translations[source].as_str().ok_or("missing fit translation")?)?;
        }
        let actions = ui.actions_from_click(translations["Fit all enabled garments"].as_str().ok_or("fit translation")?)?;
        assert!(has_host_command(&actions, "refit_fit_to_body"), "{code}: translated fitting action failed");
    }
    Ok(())
}

#[test]
fn workflow_setup_selects_garment_parts_even_without_an_archive_asset_row() -> TestResult {
    let mut ui = super::morph_authoring::authoring_ui()?;
    ui.application.cdmw_state["morph_refit"]["refit"]["garment_submesh_indices"] = json!([]);
    ui.application.cdmw_state["archive_refit_assets"] = json!([
        {"path": "body.pac", "part_indices": [0]},
        {"path": "garment.pac", "part_indices": [1]}
    ]);
    ui.frame(Vec::new());
    ui.click("Select garments")?;
    assert_eq!(ui.application.selected_part_indices(), vec![1, 2]);
    let actions = ui.actions_from_click("Bind selected garments")?;
    assert!(actions.iter().any(|action| matches!(action,
        UiAction::CdmwCommand { command: "refit_bind", arguments, .. }
        if arguments == &json!({"submesh_indices": [1, 2]})
    )));
    Ok(())
}

#[test]
fn restore_fitting_shape_actions_stay_visible_for_a_large_selection() -> TestResult {
    let mut ui = super::morph_authoring::authoring_ui()?;
    ui.size = egui::vec2(1000.0, 650.0);
    ui.application.apply_cdmw_theme_payload(&json!({"font_point_size":18.0,"density":"comfortable"}));
    let state = &mut ui.application.cdmw_state["morph_refit"];
    state["shape_restore_source"] = json!("matching-unbaked.pac");
    state["shape_restore_sha256"] = json!("a".repeat(64));
    state["shape_restore_vertex_count"] = json!(3000);
    state["shape_restore_scope"] = json!((0..80).map(|i| json!([i, "selected garment", 1])).collect::<Vec<_>>());
    ui.settle_layout();
    for tab in ["Setup", "Fit", "Shape", "Saved"] {
        ui.click(tab)?;
        for label in ["Apply", "Cancel"] {
            let rect = ui.label_rect(label).ok_or("restoration action is hidden")?;
            assert!(rect.bottom() <= ui.size.y, "{tab}: restoration action outside window");
        }
    }
    assert!(has_host_command(&ui.actions_from_click("Apply")?, "refit_restore_shape_apply"));
    assert!(has_host_command(&ui.actions_from_click("Cancel")?, "refit_restore_shape_cancel"));
    assert!(ui.actions_from_click("Finish Edit Mesh")?.is_empty());
    Ok(())
}
