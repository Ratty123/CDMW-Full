use super::*;

#[test]
fn parts_layout_keeps_names_clear_and_view_include_independent() -> TestResult {
    let name = "CD_PHM_00_Mask_Belt_0105_01_01_01";
    let title = format!("0: {name}");
    for (size, font, density) in [
        (egui::vec2(1440.0, 1080.0), 11.0, "normal"),
        (egui::vec2(1000.0, 900.0), 18.0, "comfortable"),
    ] {
        let mut application = two_part_application()?;
        Arc::make_mut(application.document.as_mut().ok_or("document")?)
            .lods[0].submeshes[0].name = name.into();
        let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(application, size);
        ui.application.apply_cdmw_theme_payload(&json!({"font_point_size": font, "density": density}));
        ui.application.cdmw_state["replacement"] = json!({
            "available": true, "comparison": "edit", "parts": [
                {"index": 0, "id": "owned:0", "included": true},
                {"index": 1, "id": "owned:1", "included": true}
            ]
        });
        ui.application.cdmw_state["physics"] = json!({"parts": [
            {"index": 0, "name": name, "kind": "cloth", "guide_counts": [3],
                "vertex_counts": [3], "jiggle_counts": [1]},
            {"index": 1, "name": "Part B", "kind": "jiggle", "vertex_counts": [3],
                "jiggle_counts": [2]}
        ]});
        ui.settle_layout();
        let before = ui.application.mesh.as_ref().ok_or("mesh")?.structural_fingerprint();
        let view = ui.list_checkbox_rect(&title, "View")?;
        let include = ui.list_checkbox_rect(&title, "Include")?;
        let first = ui.reveal(&title)?;
        let second = ui.reveal("1: Part B")?;
        assert!(view.right() < include.left());
        assert!((view.center().y - first.center().y).abs() < 3.0);
        assert!(second.top() - first.top() <= if font > 11.0 { 48.0 } else { 32.0 },
            "rows are no longer compact at {font}: {first:?}, {second:?}");
        let badge = ui.label_rect("Cloth + jiggle").ok_or("physics badge")?;
        assert!(badge.left() > first.right(), "physics overlapped the name");
        assert!(badge.right() < view.left(), "physics overlapped View");
        ui.click(&title)?;
        assert_eq!(ui.application.selected_part_indices(), vec![0]);
        ui.last_actions.clear();
        ui.click_at(view.center());
        assert!(ui.application.cdmw_hidden_parts.contains(&0));
        assert!(!has_host_command(&ui.last_actions, "replacement_include"));
        ui.click_at(view.center());
        assert!(ui.application.cdmw_hidden_parts.is_empty());
        ui.last_actions.clear();
        ui.click_at(include.center());
        assert!(ui.last_actions.iter().any(|action| matches!(action,
            UiAction::CdmwCommand { command: "replacement_include", arguments, .. }
            if arguments == &json!({"part_ids": ["owned:0"], "included": false}))));
        assert!(ui.application.cdmw_hidden_parts.is_empty());
        ui.click(&title)?;
        ui.click("1: Part B")?;
        assert_eq!(ui.application.selected_part_indices(), vec![0, 1]);
        let physics = ui.reveal("Detected physics")?;
        let islands = ui.label_rect("Mesh islands").ok_or("islands before physics")?;
        assert!(physics.top() > islands.bottom());
        assert!(ui.label_rect("Physics: Cloth + jiggle").is_none());
        ui.click("Detected physics")?;
        ui.reveal("Physics: Cloth + jiggle")?;
        ui.reveal("Physics: Jiggle contribution")?;
        assert_eq!(ui.application.mesh.as_ref().ok_or("mesh")?.structural_fingerprint(), before);
        assert_eq!(ui.application.selected_part_indices(), vec![0, 1]);
    }
    Ok(())
}

#[test]
fn parts_delete_guidance_offers_free_edit_without_deleting_the_selection() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        two_part_application()?,
        egui::vec2(1440.0, 1080.0),
    );
    ui.click("0: Part A")?;
    let before = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();
    let actions = parts_actions_from_click(&mut ui, "Delete")?;
    assert!(!has_host_command(&actions, "topology"));
    ui.settle_layout();
    ui.reveal("Delete unavailable")?;
    ui.reveal("Deleting whole parts requires Free Edit. To remove a part from the exported PAC, untick Include instead.")?;
    assert_eq!(ui.application.selected_part_indices(), vec![0]);
    assert_eq!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint(),
        before
    );
    let actions = ui.actions_from_click("Choose Free Edit...")?;
    assert!(
        actions
            .iter()
            .any(|action| matches!(action, UiAction::ChooseCdmwFreeEdit))
    );
    assert!(!has_host_command(&actions, "topology"));
    assert!(ui.label_rect("Delete unavailable").is_none());
    Ok(())
}

#[test]
fn parts_delete_shortcut_explains_exact_and_routes_explicit_free_edit_part_deletion() -> TestResult
{
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        two_part_application()?,
        egui::vec2(1440.0, 1080.0),
    );
    ui.click("0: Part A")?;
    ui.frame(vec![key_event(egui::Key::Delete, true)]);
    ui.frame(vec![key_event(egui::Key::Delete, false)]);
    ui.settle_layout();
    ui.reveal("Delete unavailable")?;
    ui.click("Close")?;
    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    ui.last_actions.clear();
    ui.frame(vec![key_event(egui::Key::Delete, true)]);
    ui.frame(vec![key_event(egui::Key::Delete, false)]);
    assert!(ui.last_actions.iter().any(|action| matches!(action,
        UiAction::CdmwCommand { command: "topology", arguments, .. }
        if arguments["action"] == "delete" && arguments["params"]["delete_parts"] == true
            && arguments["selection"]["source_indices"] == json!([0])
            && arguments["selection"]["faces_by_submesh"] == json!({}))));
    Ok(())
}

#[test]
fn parts_delete_shortcut_keeps_supported_vertex_deletion_in_exact_output() -> TestResult {
    let mut application = triangle_application()?;
    let mesh = application.mesh.as_mut().ok_or("mesh")?;
    let vertex = mesh.vertices().next().ok_or("vertex")?.0;
    mesh.set_selection(Selection {
        vertices: HashSet::from([vertex]),
        ..Selection::default()
    })?;
    let mut ui =
        HeadlessUi::new_integrated_cdmw_for_controls(application, egui::vec2(1440.0, 1080.0));
    ui.frame(vec![key_event(egui::Key::Delete, true)]);
    ui.frame(vec![key_event(egui::Key::Delete, false)]);
    assert!(has_topology_action(&ui.last_actions, "delete"));
    assert!(ui.label_rect("Delete unavailable").is_none());
    assert_eq!(
        ui.application.cdmw_state["output_policy"],
        "exact_game_asset"
    );
    Ok(())
}

#[test]
fn parts_delete_guidance_keeps_last_part_and_preserves_modal_keyboard_ownership() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        two_part_application()?,
        egui::vec2(1440.0, 1080.0),
    );
    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    ui.click("All")?;
    assert!(!has_host_command(
        &parts_actions_from_click(&mut ui, "Delete")?,
        "topology"
    ));
    ui.settle_layout();
    ui.reveal("Keep at least one part when deleting")?;
    ui.last_actions.clear();
    ui.frame(vec![key_event(egui::Key::Delete, true)]);
    ui.frame(vec![key_event(egui::Key::Delete, false)]);
    assert!(!has_host_command(&ui.last_actions, "topology"));
    ui.frame(vec![key_event(egui::Key::Escape, true)]);
    ui.frame(vec![key_event(egui::Key::Escape, false)]);
    ui.settle_layout();
    assert!(ui.label_rect("Delete unavailable").is_none());
    assert_eq!(ui.application.selected_part_indices(), vec![0, 1]);
    Ok(())
}

#[test]
fn parts_delete_shortcut_leaves_focused_text_editing_in_charge() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1440.0, 1080.0),
    );
    let context = ui.application.egui_context.clone();
    let mut text = "abc".to_owned();
    let mut actions = Vec::new();
    for frame in 0..3 {
        let events = match frame {
            1 => vec![key_event(egui::Key::Delete, true)],
            2 => vec![key_event(egui::Key::Delete, false)],
            _ => vec![],
        };
        let mut output = context.run_ui(
            egui::RawInput {
                screen_rect: Some(Rect::from_min_size(Pos2::ZERO, ui.size)),
                events,
                ..Default::default()
            },
            |root| {
                let response = root.add(
                    egui::TextEdit::singleline(&mut text)
                        .id(egui::Id::new("owned-delete-text"))
                        .cursor_at_end(false),
                );
                if frame == 0 {
                    response.request_focus();
                }
                actions.extend(ui.application.draw_cdmw_ui(root));
            },
        );
        output.textures_delta.clear();
    }
    assert_eq!(text, "bc");
    assert!(!has_topology_action(&actions, "delete"));
    assert!(!has_host_command(&actions, "topology"));
    ui.settle_layout();
    assert!(ui.label_rect("Delete unavailable").is_none());
    Ok(())
}

#[test]
fn parts_delete_guidance_keeps_refit_and_replacement_outputs_protected() -> TestResult {
    for (policy, refit_assets) in [
        ("exact_game_asset", json!([{"label": "Owned armor PAC"}])),
        ("replacement_game_asset", json!([])),
    ] {
        let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
            two_part_application()?,
            egui::vec2(1440.0, 1080.0),
        );
        ui.application.cdmw_state["output_policy"] = json!(policy);
        ui.application.cdmw_state["archive_refit_assets"] = refit_assets;
        ui.click("0: Part A")?;
        assert!(!has_host_command(
            &parts_actions_from_click(&mut ui, "Delete")?,
            "topology"
        ));
        ui.settle_layout();
        ui.reveal("Finish Mesh, then choose Continue editing modified mesh before deleting whole parts. Use Include in the new session to remove parts from game output.")?;
        assert!(ui.label_rect("Choose Free Edit...").is_none());
        assert_eq!(ui.application.cdmw_state["output_policy"], policy);
        assert_eq!(ui.application.selected_part_indices(), vec![0]);
    }
    Ok(())
}

#[test]
fn parts_panel_uses_available_height_and_keeps_scroll_and_selection_across_tabs() -> TestResult {
    fn visible_rows(ui: &HeadlessUi) -> Vec<(String, Rect)> {
        ui.output.shapes.iter().filter_map(|clipped| match &clipped.shape {
            egui::Shape::Text(text) if text.galley.job.text.contains(": Component ")
                && clipped.clip_rect.contains_rect(text.visual_bounding_rect())
                && text.visual_bounding_rect().bottom() <= ui.size.y =>
                Some((text.galley.job.text.clone(), text.visual_bounding_rect())),
            _ => None,
        }).collect()
    }
    for (size, font, density) in [
        (egui::vec2(1440.0, 1080.0), 11.0, "normal"),
        (egui::vec2(1000.0, 900.0), 18.0, "comfortable"),
        (egui::vec2(800.0, 1200.0), 11.0, "normal"),
    ] {
        let mut application = two_part_application()?;
        let document = Arc::make_mut(application.document.as_mut().ok_or("document")?);
        let template = document.lods[0].submeshes[0].clone();
        document.lods[0].submeshes = (0..80).map(|index| {
            let mut part = template.clone();
            part.name = format!("Component {index:02}");
            part
        }).collect();
        application.mesh = Some(WorkingMesh::from_document(document)?);
        let mut ui = HeadlessUi::new_integrated_cdmw(application, size);
        ui.application.apply_cdmw_theme_payload(&json!({"font_point_size": font, "density": density}));
        ui.settle_layout();
        ui.click("Parts")?;
        ui.click("0: Component 00")?;
        let tabs = ui.label_rect("Mesh islands").ok_or("tabs")?;
        let all = ui.label_rect("All").ok_or("selection toolbar")?;
        let before = visible_rows(&ui);
        // The color options and Open Parts on hover take two rows above the list.
        assert!(before.len() >= if font > 11.0 { 6 } else { 18 }, "too few rows at {size:?}: {}", before.len());
        let bottom = before.last().ok_or("rows")?.1.bottom();
        assert!(bottom > ui.application.viewport_rect.ok_or("viewport")?.bottom() - 70.0,
            "list does not use available height: bottom {bottom}, size {size:?}");
        ui.scroll_inspector(-350.0);
        ui.settle_layout();
        let scrolled = visible_rows(&ui);
        assert_ne!(before[0].0, scrolled[0].0, "list did not scroll");
        assert_eq!(ui.label_rect("Mesh islands"), Some(tabs));
        assert_eq!(ui.label_rect("All"), Some(all));
        ui.click("Mesh islands")?;
        ui.reveal("Select a part, then an island to move, scale or edit it.")?;
        ui.click("Parts")?;
        assert_eq!(visible_rows(&ui), scrolled, "Parts scroll changed between tabs");
        assert_eq!(ui.application.selected_part_indices(), vec![0]);
        ui.click("Back to Inspector")?;
        ui.reveal("Geometry Layers")?;
        ui.click("Parts")?;
        assert_eq!(visible_rows(&ui), scrolled, "Parts scroll changed after reopening");
        let collapse = ui.sidebar_button("Collapse Inspector").ok_or("collapse")?;
        ui.click_at(collapse.rect.center());
        ui.settle_layout();
        let expand = ui.sidebar_button("Expand Inspector").ok_or("expand")?;
        ui.click_at(expand.rect.center());
        ui.settle_layout();
        assert_eq!(visible_rows(&ui), scrolled, "Parts scroll changed after collapsing the panel");
        assert_eq!(ui.application.selected_part_indices(), vec![0]);
        assert!(ui.application.viewport_rect.ok_or("viewport")?.width() >= 100.0);
    }
    Ok(())
}
