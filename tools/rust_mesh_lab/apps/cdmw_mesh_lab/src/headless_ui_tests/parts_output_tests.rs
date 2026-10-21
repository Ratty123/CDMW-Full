use super::*;

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
