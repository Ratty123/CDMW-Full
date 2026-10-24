use super::*;
use super::morph_workflow::part_name_has_viewport_outline;

fn island_hover_point(ui: &HeadlessUi, source_face: u32) -> Result<Pos2, Box<dyn std::error::Error>> {
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    let face = mesh.faces().find(|(_, face)| matches!(face.provenance,
        Provenance::Source { submesh: 0, element } if element == source_face)).ok_or("island face")?.1;
    let centre = face.vertices.iter().map(|handle| Vec3::from(mesh.vertex(*handle).unwrap().position))
        .sum::<Vec3>() / 3.0;
    let point = ui.application.camera.project(centre, ui.application.viewport_rect.ok_or("viewport")?).ok_or("project island")?;
    assert!(point.inside_view);
    Ok(egui::pos2(point.screen.x, point.screen.y))
}

#[test]
fn island_controls_name_hover_highlights_only_that_island_without_editing() -> TestResult {
    for mode in [ViewMode::Solid, ViewMode::PartId] {
        let mut ui = island_ui(egui::vec2(1280.0, 900.0))?;
        crate::cdmw_layout::set_auto_open_parts_on_hover(&ui.application.egui_context, false);
        ui.click("Mesh islands")?;
        ui.click("Island 1 · 1 faces")?;
        ui.application.view_mode = mode;
        ui.application.cdmw_refit_clearance = 0.75;
        ui.application.cdmw_refit_settings_dirty.mark("clearance_percent");
        ui.application.cdmw_refit_region_targets = vec![0];
        let root = tempdir()?;
        ui.application.cdmw_bridge = Some(CdmwBridge::for_test(root.path().to_path_buf(), "island-name-hover", 1, 0));
        let state = ui.application.cdmw_state.clone();
        let mesh = ui.application.mesh.as_ref().ok_or("mesh")?.clone();
        let selection_overlay = ui.application.face_selection_overlay.as_ref().map(|overlay| overlay.positions.clone());
        ui.last_actions.clear();
        // Islands share a parent Part, so changing the hovered island must replace the cache.
        for face in [0, 1, 0] {
            let name = ui.reveal(&format!("Island {} · 1 faces", face + 1))?;
            ui.frame(vec![Event::PointerMoved(name.center())]);
            ui.settle_layout();
            let (target, overlay) = ui.application.cdmw_part_hover_overlay.as_ref().ok_or("island hover overlay")?;
            let expected: Vec<_> = mesh.faces().filter(|(_, item)| matches!(item.provenance,
                Provenance::Source { submesh: 0, element } if element == face))
                .flat_map(|(_, item)| item.vertices.iter()).map(|handle| mesh.vertex(*handle).unwrap().position).collect();
            assert_eq!(target.part, 0);
            assert_eq!(target.island_faces.as_deref(), Some([face].as_slice()));
            assert_eq!(overlay.positions, expected);
            assert_eq!(overlay.positions.len(), 3, "hover tinted another island in this Part");
            assert!(ui.label_rect("Show all islands").is_some());
        }
        let current = ui.application.mesh.as_ref().ok_or("mesh")?;
        assert_eq!(current.selection, mesh.selection);
        assert_eq!(current.selection_revision, mesh.selection_revision);
        assert_eq!(current.structural_fingerprint(), mesh.structural_fingerprint());
        assert_eq!(ui.application.face_selection_overlay.as_ref().map(|overlay| overlay.positions.clone()), selection_overlay);
        assert_eq!(ui.application.cdmw_state, state);
        assert_eq!(ui.application.cdmw_refit_clearance, 0.75);
        assert!(ui.application.cdmw_refit_settings_dirty.is_dirty());
        assert_eq!(ui.application.cdmw_refit_region_targets, vec![0]);
        assert_eq!(ui.application.view_mode, mode);
        assert!(ui.last_actions.is_empty());
        assert!(ui.application.cdmw_pending_request.is_none());
        ui.frame(vec![Event::PointerGone]);
        assert!(ui.application.cdmw_hovered_part.is_none());
        assert!(ui.application.cdmw_part_hover_overlay.is_none());
    }
    Ok(())
}

#[test]
fn island_controls_name_hover_clears_and_respects_visibility_and_comparison() -> TestResult {
    let mut ui = island_ui(egui::vec2(1280.0, 900.0))?;
    ui.click("Mesh islands")?;
    ui.settle_layout();
    let root = tempdir()?;
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(root.path().to_path_buf(), "island-name-visibility", 1, 0));
    let name = ui.reveal("Island 2 · 1 faces")?;
    ui.frame(vec![Event::PointerMoved(name.center())]);
    ui.settle_layout();
    assert_eq!(ui.application.cdmw_part_hover_overlay.as_ref().ok_or("hover")?.1.positions.len(), 3);
    // Keep the pointer still while the current fitting shape changes.
    let mesh = ui.application.mesh.as_mut().ok_or("mesh")?;
    let positions = mesh.vertices().map(|(handle, vertex)|
        (handle, [vertex.position[0], vertex.position[1] + 0.5, vertex.position[2]])).collect();
    mesh.apply_positions(&positions)?;
    let expected: Vec<_> = mesh.faces().filter(|(_, face)| matches!(face.provenance,
        Provenance::Source { submesh: 0, element: 1 })).flat_map(|(_, face)| face.vertices.iter())
        .map(|handle| mesh.vertex(*handle).unwrap().position).collect();
    ui.frame(Vec::new());
    assert_eq!(ui.application.cdmw_part_hover_overlay.as_ref().ok_or("updated hover")?.1.positions, expected);
    // Hiding another island must not enlarge the hover to the rest of its Part.
    ui.application.set_island_visibility(0, vec![0], false);
    ui.frame(Vec::new());
    assert_eq!(ui.application.cdmw_part_hover_overlay.as_ref().ok_or("visible hover")?.1.positions, expected);
    ui.application.set_island_visibility(0, vec![1], false);
    ui.frame(Vec::new());
    assert!(ui.application.cdmw_part_hover_overlay.is_none());
    assert_eq!(ui.application.mesh.as_ref().ok_or("mesh")?.viewport_hidden_faces().len(), 2);
    ui.application.set_island_visibility(0, vec![1], true);
    ui.frame(Vec::new());
    ui.settle_layout();
    assert_eq!(ui.application.cdmw_part_hover_overlay.as_ref().ok_or("restored hover")?.1.positions, expected);
    ui.application.cdmw_hidden_parts.insert(0);
    ui.frame(Vec::new());
    assert!(ui.application.cdmw_part_hover_overlay.as_ref().is_none_or(|(_, overlay)| overlay.positions.is_empty()));
    assert!(ui.application.cdmw_hidden_parts.contains(&0));
    ui.application.cdmw_hidden_parts.clear();
    ui.application.cdmw_state["replacement"]["comparison"] = json!("output");
    ui.frame(Vec::new());
    assert!(ui.application.cdmw_part_hover_overlay.is_none());
    ui.application.cdmw_state["replacement"]["comparison"] = json!("edit");
    ui.frame(Vec::new());
    ui.settle_layout();
    assert!(ui.application.cdmw_part_hover_overlay.is_some());
    let other_control = ui.reveal("Show all islands")?;
    ui.frame(vec![Event::PointerMoved(other_control.center())]);
    assert!(ui.application.cdmw_part_hover_overlay.is_none());
    ui.frame(vec![Event::PointerMoved(name.center())]);
    assert!(ui.application.cdmw_part_hover_overlay.is_some());
    ui.click("Parts")?;
    assert!(ui.application.cdmw_part_hover_overlay.is_none());
    Ok(())
}

#[test]
fn island_controls_viewport_hover_keeps_the_tab_and_identifies_the_matching_island() -> TestResult {
    for automatic in [true, false] {
        let mut ui = island_ui(egui::vec2(1280.0, 900.0))?;
        crate::cdmw_layout::set_auto_open_parts_on_hover(&ui.application.egui_context, automatic);
        ui.click("Mesh islands")?;
        ui.application.camera.frame_all_in_viewport(ui.application.mesh.as_ref().ok_or("mesh")?,
            ui.application.viewport_rect.ok_or("viewport")?);
        let root = tempdir()?;
        ui.application.cdmw_bridge = Some(CdmwBridge::for_test(root.path().to_path_buf(), "island-hover", 1, 0));
        let state = ui.application.cdmw_state.clone();
        let mesh = ui.application.mesh.as_ref().ok_or("mesh")?.clone();
        ui.last_actions.clear();
        for source_face in [0, 1] {
            ui.frame(vec![Event::PointerMoved(island_hover_point(&ui, source_face)?)]);
            ui.settle_layout();
            assert!(ui.label_rect("Show all islands").is_some(), "hover switched away from Mesh islands");
            assert!(part_name_has_viewport_outline(&ui, &format!("Island {} · 1 faces", source_face + 1)));
            assert!(!part_name_has_viewport_outline(&ui, &format!("Island {} · 1 faces", 2 - source_face)));
        }
        ui.frame(vec![Event::PointerGone]);
        assert!(!part_name_has_viewport_outline(&ui, "Island 2 · 1 faces"));
        assert_eq!(ui.application.cdmw_state, state);
        let current = ui.application.mesh.as_ref().ok_or("mesh")?;
        assert_eq!(current.selection, mesh.selection);
        assert_eq!(current.selection_revision, mesh.selection_revision);
        assert_eq!(current.structural_fingerprint(), mesh.structural_fingerprint());
        assert!(ui.last_actions.is_empty());
        assert!(ui.application.cdmw_pending_request.is_none());
        // Reopening the Inspector on hover must also retain the last chosen tab.
        ui.click("Back to Inspector")?;
        ui.frame(vec![Event::PointerMoved(island_hover_point(&ui, 1)?)]);
        ui.settle_layout();
        assert_eq!(ui.label_rect("Show all islands").is_some(), automatic);
        if !automatic { continue; }
        ui.frame(vec![Event::PointerMoved(island_hover_point(&ui, 1)?)]);
        ui.settle_layout();
        assert!(part_name_has_viewport_outline(&ui, "Island 2 · 1 faces"));
    }
    Ok(())
}

#[test]
fn island_controls_viewport_hover_scrolls_between_islands_in_the_same_part() -> TestResult {
    let mut ui = island_ui(egui::vec2(1280.0, 800.0))?;
    let document = Arc::make_mut(ui.application.document.as_mut().ok_or("document")?);
    let part = &mut document.lods[0].submeshes[0];
    let positions = part.positions[..3].to_vec();
    let normals = part.normals[..3].to_vec();
    let uvs = part.uvs[..3].to_vec();
    part.positions = (0..70).flat_map(|index| positions.iter().map(move |p| [p[0] + index as f32 * 3.0, p[1], p[2]])).collect();
    part.normals = (0..70).flat_map(|_| normals.clone()).collect();
    part.uvs = (0..70).flat_map(|_| uvs.clone()).collect();
    part.source_vertex_indices = (0..210).collect();
    part.indices = (0..210).collect();
    ui.application.mesh = Some(WorkingMesh::from_document(document)?);
    ui.application.projection = None;
    ui.application.cdmw_state["mesh_islands"]["parts"][0]["islands"] = json!(
        (0..70).map(|face| json!({"faces":[face],"included":true})).collect::<Vec<_>>());
    ui.click("Mesh islands")?;
    ui.application.camera.frame_all_in_viewport(ui.application.mesh.as_ref().ok_or("mesh")?,
        ui.application.viewport_rect.ok_or("viewport")?);
    ui.scroll_inspector(-50_000.0);
    ui.settle_layout();
    assert!(ui.label_rect("Island 1 · 1 faces").is_none());
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?.clone();
    ui.last_actions.clear();
    for face in [0, 69] {
        ui.frame(vec![Event::PointerMoved(island_hover_point(&ui, face)?)]);
        ui.settle_layout();
        assert!(part_name_has_viewport_outline(&ui, &format!("Island {} · 1 faces", face + 1)));
    }
    let before = ui.label_rect("Island 70 · 1 faces");
    ui.frame(vec![Event::PointerMoved(island_hover_point(&ui, 0)?)]);
    ui.frame(vec![Event::PointerMoved(island_hover_point(&ui, 69)?)]);
    ui.settle_layout();
    assert_eq!(ui.label_rect("Island 70 · 1 faces"), before, "moving to another island must cancel the old target");
    ui.frame(vec![Event::PointerMoved(island_hover_point(&ui, 0)?)]);
    ui.frame(vec![Event::PointerGone]);
    ui.settle_layout();
    assert_eq!(ui.label_rect("Island 70 · 1 faces"), before, "leaving must cancel pending island scrolling");
    assert!(ui.application.cdmw_part_name_scroll.is_none());
    let current = ui.application.mesh.as_ref().ok_or("mesh")?;
    assert_eq!(current.selection, mesh.selection);
    assert_eq!(current.selection_revision, mesh.selection_revision);
    assert!(ui.last_actions.is_empty());
    Ok(())
}

#[test]
fn island_controls_viewport_hover_uses_the_frontmost_visible_island() -> TestResult {
    let mut ui = island_ui(egui::vec2(1280.0, 900.0))?;
    let document = Arc::make_mut(ui.application.document.as_mut().ok_or("document")?);
    for position in &mut document.lods[0].submeshes[0].positions[3..] {
        position[0] -= 3.0;
        position[2] += 0.5;
    }
    ui.application.mesh = Some(WorkingMesh::from_document(document)?);
    ui.application.projection = None;
    ui.application.camera.set_standard_view(StandardView::Back);
    ui.click("Mesh islands")?;
    ui.application.camera.frame_all_in_viewport(ui.application.mesh.as_ref().ok_or("mesh")?,
        ui.application.viewport_rect.ok_or("viewport")?);
    ui.application.view_mode = ViewMode::XRay;
    ui.application.selection_domain = SelectionDomain::Edge;
    ui.frame(vec![Event::PointerMoved(island_hover_point(&ui, 0)?)]);
    ui.settle_layout();
    assert!(part_name_has_viewport_outline(&ui, "Island 2 · 1 faces"));
    assert!(!part_name_has_viewport_outline(&ui, "Island 1 · 1 faces"));
    ui.application.set_island_visibility(0, vec![1], false);
    ui.frame(Vec::new());
    ui.settle_layout();
    assert!(part_name_has_viewport_outline(&ui, "Island 1 · 1 faces"));
    assert!(!part_name_has_viewport_outline(&ui, "Island 2 · 1 faces"));
    let point = island_hover_point(&ui, 0)?;
    ui.frame(vec![Event::PointerButton { pos: point, button: PointerButton::Secondary,
        pressed: true, modifiers: egui::Modifiers::NONE }]);
    assert!(!part_name_has_viewport_outline(&ui, "Island 1 · 1 faces"));
    Ok(())
}

#[test]
fn island_controls_keep_compact_columns_at_larger_text_sizes() -> TestResult {
    let name = "CD_PHM_00_Mask_Belt_0105_01_01_01";
    for (size, font, density) in [
        (egui::vec2(1440.0, 1080.0), 11.0, "normal"),
        (egui::vec2(1000.0, 900.0), 18.0, "comfortable"),
    ] {
        let mut ui = island_ui(size)?;
        ui.application.apply_cdmw_theme_payload(&json!({"font_point_size": font, "density": density}));
        ui.application.cdmw_state["mesh_islands"]["parts"][0]["name"] = json!(name);
        ui.settle_layout();
        ui.click("Mesh islands")?;
        let island = ui.reveal("Island 1 · 1 faces")?;
        let part = ui.label_rect(name).ok_or("part name above island")?;
        assert!(island.top() > part.bottom());
        let view = ui.list_checkbox_rect("Island 1 · 1 faces", "View")?;
        let include = ui.list_checkbox_rect("Island 1 · 1 faces", "Include")?;
        assert!(view.right() < include.left());
        assert!((view.center().y - island.center().y).abs() < 3.0);
        ui.click("Island 1 · 1 faces")?;
        assert_eq!(ui.application.mesh.as_ref().ok_or("mesh")?.selection.faces.len(), 1);
        ui.last_actions.clear();
        ui.click_at(include.center());
        assert!(ui.last_actions.iter().any(|action| matches!(action,
            UiAction::CdmwCommand { command: "replacement_islands", arguments, .. }
            if arguments == &json!({"part_id":"owned:0","faces":[0],"included":false}))));
        ui.click_at(view.center());
        assert_eq!(ui.application.mesh.as_ref().ok_or("mesh")?.viewport_hidden_faces().len(), 1);
    }
    Ok(())
}

#[test]
fn island_controls_survive_host_reload_and_clip_restored_selection() -> TestResult {
    let root = tempdir()?;
    let mut ui = island_ui(egui::vec2(1280.0, 900.0))?;
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(
        root.path().to_path_buf(),
        "islands",
        1,
        0,
    ));
    ui.application.set_island_visibility(0, vec![1], false);
    let original = ui.application.document.as_deref().cloned().ok_or("document")?;
    ui.application.cdmw_state["selection"] =
        json!({"source_indices":[], "faces_by_submesh":{"0":[0,1]}});
    ui.application.install_cdmw_document(original.clone())?;
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    assert_eq!(mesh.viewport_hidden_faces().len(), 1);
    assert_eq!(
        mesh.selection.faces.len(),
        1,
        "host restored selection into hidden geometry"
    );
    ui.application.cdmw_state["replacement"]["comparison"] = json!("output");
    let mut output = original.clone();
    output.lods[0].submeshes[0].indices.truncate(3);
    ui.application.install_cdmw_document(output)?;
    assert!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .viewport_hidden_faces()
            .is_empty()
    );
    assert_eq!(
        ui.application.cdmw_hidden_islands.len(),
        1,
        "comparison discarded edit visibility"
    );
    ui.application.cdmw_state["replacement"]["comparison"] = json!("edit");
    ui.application.install_cdmw_document(original)?;
    assert_eq!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .viewport_hidden_faces()
            .len(),
        1
    );
    Ok(())
}

fn island_ui(size: egui::Vec2) -> Result<HeadlessUi, Box<dyn std::error::Error>> {
    let mut application = triangle_application()?;
    let document = Arc::make_mut(application.document.as_mut().ok_or("document")?);
    let part = &mut document.lods[0].submeshes[0];
    part.name = "Skull and horns".into();
    let positions = part
        .positions
        .iter()
        .map(|p| [p[0] + 3.0, p[1], p[2]])
        .collect::<Vec<_>>();
    part.positions.extend(positions);
    part.normals.extend(part.normals.clone());
    part.uvs.extend(part.uvs.clone());
    part.source_vertex_indices.extend([3, 4, 5]);
    part.indices.extend([3, 4, 5]);
    application.mesh = Some(WorkingMesh::from_document(document)?);
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(application, size);
    ui.application.cdmw_state["replacement"] =
        json!({"available":true,"comparison":"edit","parts":[]});
    ui.application.cdmw_state["mesh_islands"] = json!({"parts":[{"index":0,"part_id":"owned:0","name":"Skull and horns",
        "available":true,"reason":"","islands":[{"faces":[0],"included":true},{"faces":[1],"included":true}]}]});
    ui.settle_layout();
    Ok(ui)
}

#[test]
fn island_controls_use_separate_tabs_and_return_to_inspector_tools() -> TestResult {
    let mut ui = island_ui(egui::vec2(1280.0, 900.0))?;
    for key in ["translucency", "emission", "shader_controls"] {
        ui.application.cdmw_state[key] = json!({"available": false, "parts": []});
    }
    ui.settle_layout();
    ui.reveal("Mesh islands")?;
    assert!(ui.label_rect("Show all islands").is_none());
    assert!(ui.label_rect("Island 1 · 1 faces").is_none());
    ui.click("Back to Inspector")?;
    assert!(ui.label_rect("Mesh islands").is_none());
    for (heading, control) in [
        ("Translucency (experimental)", "Apply translucency"),
        ("Glow (experimental)", "Apply glow"),
        ("Shader experiments", "Apply shader controls"),
    ] {
        ui.click(heading)?;
        ui.reveal(control)?;
        assert!(ui.label_rect("Mesh islands").is_none());
        ui.click(heading)?;
    }
    ui.click("Parts")?;
    ui.reveal("Mesh islands")?;
    assert!(ui.label_rect("Show all islands").is_none());
    ui.click("Mesh islands")?;
    ui.reveal("Island 1 · 1 faces")?;
    ui.click("Parts")?;
    assert!(ui.label_rect("Island 1 · 1 faces").is_none());
    Ok(())
}

#[test]
fn island_controls_select_isolate_and_restore_without_export_edits() -> TestResult {
    let mut ui = island_ui(egui::vec2(1440.0, 1080.0))?;
    let before = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();
    ui.click("Mesh islands")?;
    ui.click("Island 1 · 1 faces")?;
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    assert!(mesh.selection.submeshes.is_empty());
    assert_eq!(mesh.selection.faces.len(), 1);
    assert_eq!(mesh.selected_vertex_scope().len(), 3);
    ui.click("Isolate")?;
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    let visible = ui
        .application
        .cdmw_visible_submeshes()
        .ok_or("visibility")?;
    let handles = mesh.element_handles_for_submeshes(&visible);
    assert_eq!(handles.faces.len(), 1);
    assert_eq!(handles.vertices.len(), 3);
    let filtered = mesh.draw_snapshot_for_submeshes(&visible);
    assert_eq!(filtered.indices.len(), 3);
    assert_eq!(
        mesh.draw_snapshot().indices.len(),
        6,
        "viewport mask changed authored geometry"
    );
    assert_eq!(mesh.structural_fingerprint(), before);
    // Both depth-aware and X-ray picking receive the same filtered projection.
    ui.application
        .ensure_projection(ui.application.viewport_rect.ok_or("viewport")?);
    assert_eq!(
        ui.application
            .projection
            .as_ref()
            .ok_or("projection")?
            .interaction
            .depth_triangles
            .len(),
        1
    );
    ui.click("Show all islands")?;
    assert!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .viewport_hidden_faces()
            .is_empty()
    );
    assert_eq!(ui.application.cdmw_transaction_attempts, 0);
    Ok(())
}

#[test]
fn island_controls_dispatch_exact_mod_mask_and_preserve_deformation_alignment() -> TestResult {
    let mut ui = island_ui(egui::vec2(1280.0, 900.0))?;
    ui.click("Mesh islands")?;
    ui.last_actions.clear();
    let checkbox = ui.list_checkbox_rect("Island 1 · 1 faces", "Include")?;
    ui.click_at(checkbox.center());
    let actions = std::mem::take(&mut ui.last_actions);
    assert!(actions.iter().any(|action| matches!(action,
        UiAction::CdmwCommand { command:"replacement_islands", arguments, .. }
        if arguments == &json!({"part_id":"owned:0","faces":[0],"included":false}))));
    ui.application.ensure_deformation_reference();
    ui.application.set_island_visibility(0, vec![0], false);
    let visible = ui.application.cdmw_visible_submeshes().ok_or("visible")?;
    let snapshot = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .draw_snapshot_for_submeshes(&visible);
    let reference = ui
        .application
        .deformation_reference
        .as_mut()
        .ok_or("reference")?;
    assert_eq!(
        reference
            .positions_for_snapshot(Some(&visible), &snapshot)
            .ok_or("positions")?,
        snapshot.positions
    );
    // Topology replacement cannot accidentally hide faces with reused ordinals.
    Arc::make_mut(ui.application.document.as_mut().ok_or("document")?).lods[0].submeshes[0]
        .indices
        .swap(0, 1);
    ui.application.sync_island_visibility();
    assert!(ui.application.cdmw_hidden_islands.is_empty());
    Ok(())
}

#[test]
fn island_controls_explain_disabled_mod_and_reenable_after_host_update() -> TestResult {
    let mut ui = island_ui(egui::vec2(1440.0, 1080.0))?;
    let reason = "Finish Morph & Refit, then choose Continue editing modified mesh to change island inclusion.";
    ui.application.cdmw_state["mesh_islands"]["parts"][0]["available"] = json!(false);
    ui.application.cdmw_state["mesh_islands"]["parts"][0]["reason"] = json!(reason);
    ui.click("Mesh islands")?;
    ui.reveal(reason)?;
    ui.last_actions.clear();
    let checkbox = ui.list_checkbox_rect("Island 1 · 1 faces", "Include")?;
    ui.click_at(checkbox.center());
    assert!(!ui.last_actions.iter().any(|action| matches!(
        action,
        UiAction::CdmwCommand {
            command: "replacement_islands",
            ..
        }
    )));
    let checkbox = ui.list_checkbox_rect("Island 1 · 1 faces", "View")?;
    ui.click_at(checkbox.center());
    assert_eq!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .viewport_hidden_faces()
            .len(),
        1,
        "the Mod restriction disabled independent viewport controls"
    );

    ui.application.cdmw_state["mesh_islands"]["parts"][0]["available"] = json!(true);
    ui.application.cdmw_state["mesh_islands"]["parts"][0]["reason"] = json!("");
    ui.settle_layout();
    assert!(ui.label_rect(reason).is_none());
    ui.last_actions.clear();
    let checkbox = ui.list_checkbox_rect("Island 1 · 1 faces", "Include")?;
    ui.click_at(checkbox.center());
    assert!(ui.last_actions.iter().any(|action| matches!(action,
        UiAction::CdmwCommand { command:"replacement_islands", arguments, .. }
        if arguments == &json!({"part_id":"owned:0","faces":[0],"included":false}))));
    Ok(())
}

#[test]
fn island_tab_uses_full_height_and_remembers_its_own_scroll() -> TestResult {
    let mut ui = island_ui(egui::vec2(1280.0, 900.0))?;
    ui.application.cdmw_state["mesh_islands"]["parts"][0]["islands"] = json!(
        (0..80).map(|_| json!({"faces": [0], "included": true})).collect::<Vec<_>>()
    );
    ui.click("Mesh islands")?;
    let show = ui.label_rect("Show all islands").ok_or("show all")?;
    let visible = |ui: &HeadlessUi| ui.output.shapes.iter().filter_map(|clipped| match &clipped.shape {
        egui::Shape::Text(text) if text.galley.job.text.starts_with("Island ")
            && clipped.clip_rect.contains_rect(text.visual_bounding_rect())
            && text.visual_bounding_rect().bottom() <= ui.size.y =>
                Some((text.galley.job.text.clone(), text.visual_bounding_rect())),
        _ => None,
    }).collect::<Vec<_>>();
    let initial = visible(&ui);
    assert!(initial.len() > 20, "island list remains capped: {} rows", initial.len());
    assert!(initial.last().ok_or("rows")?.1.bottom() > ui.application.viewport_rect.ok_or("viewport")?.bottom() - 50.0);
    ui.scroll_inspector(-300.0);
    ui.settle_layout();
    let scrolled = visible(&ui);
    assert_ne!(initial[0].0, scrolled[0].0);
    assert_eq!(ui.label_rect("Show all islands"), Some(show));
    ui.click("Parts")?;
    ui.click("Mesh islands")?;
    assert_eq!(visible(&ui), scrolled);
    ui.click("Back to Inspector")?;
    ui.click("Parts")?;
    assert_eq!(visible(&ui), scrolled, "reopening did not restore the active island tab");
    Ok(())
}
