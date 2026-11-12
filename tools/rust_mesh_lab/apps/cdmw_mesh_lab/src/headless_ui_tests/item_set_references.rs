use super::*;

#[test]
fn editable_item_set_groups_keep_view_and_include_independent() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        two_part_application()?,
        egui::vec2(1440.0, 1080.0),
    );
    ui.application.cdmw_state["archive_refit_assets"] = json!([
        {"path": "upper.pac", "part_indices": [0]}, {"path": "lower.pac", "part_indices": [1]}]);
    ui.application.cdmw_state["replacement"] = json!({
        "available": false, "item_set": true, "comparison": "edit",
        "groups": [{"id": "upper", "name": "upper.pac"}, {"id": "lower", "name": "lower.pac"}],
        "parts": [{"id": "upper:0", "index": 0, "asset_id": "upper", "included": true},
                  {"id": "lower:0", "index": 1, "asset_id": "lower", "included": true}]
    });
    ui.settle_layout();
    ui.reveal("upper.pac")?;
    ui.reveal("lower.pac")?;
    assert!(!ui.application.cdmw_has_archive_refit());
    let before = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();
    let view = ui.list_checkbox_rect("lower.pac", "View")?;
    ui.click_at(view.center());
    assert!(ui.application.cdmw_hidden_parts.contains(&1));
    assert!(!has_host_command(&ui.last_actions, "replacement_include"));
    ui.click_at(view.center());
    let include = ui.list_checkbox_rect("lower.pac", "Include")?;
    ui.click_at(include.center());
    assert!(ui.last_actions.iter().any(|action| matches!(action,
        UiAction::CdmwCommand { command: "replacement_include", arguments, .. }
        if arguments["part_ids"] == json!(["lower:0"]) && arguments["included"] == false)));
    assert_eq!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint(),
        before
    );
    Ok(())
}

#[test]
fn reference_pieces_inspector_switch_and_view_do_not_edit_geometry() -> TestResult {
    let root = tempdir()?;
    let mut application = triangle_application()?;
    let snapshot = application.mesh.as_ref().ok_or("mesh")?.draw_snapshot();
    application.cdmw_reference_pieces = vec![crate::cdmw_session::LoadedReferencePiece {
        index: 1,
        name: "lower.pac".into(),
        visible: true,
        part_count: 1,
        snapshot: snapshot.clone(),
        textures: Vec::new(),
        material_presentations: Vec::new(),
    }];
    let mut bridge = CdmwBridge::for_test(root.path().to_owned(), "set", 1, 0);
    bridge.set_reference_files_for_test(vec!["upper.pac".into(), "lower.pac".into()]);
    let messages = bridge.capture_messages_for_test();
    application.cdmw_bridge = Some(bridge);
    let mut ui = HeadlessUi::new_integrated_cdmw(application, egui::vec2(1440.0, 1080.0));
    ui.settle_layout();
    ui.click("Reference pieces")?;
    ui.reveal("lower.pac")?;
    ui.click("View")?;
    assert!(!ui.application.cdmw_reference_pieces[0].visible);
    ui.click("View")?;
    assert!(ui.application.cdmw_reference_pieces[0].visible);
    assert_eq!(
        ui.application.mesh.as_ref().ok_or("mesh")?.draw_snapshot(),
        snapshot
    );
    // No edit went to CDMW; the editor's command list (P12) is the only message.
    assert!(
        messages
            .try_iter()
            .all(|message| message["event"] == "commands_state")
    );
    ui.click("Switch editable piece")?;
    ui.click("lower.pac")?;
    assert!(
        ui.last_actions
            .iter()
            .any(|action| matches!(action, UiAction::SwitchItemPiece(1)))
    );
    // The UI harness records actions; the application's handler sends the owned index.
    ui.application
        .handle_actions(vec![UiAction::SwitchItemPiece(1)]);
    let message = messages.recv_timeout(std::time::Duration::from_secs(1))?;
    assert_eq!(message["event"], "switch_item_piece");
    assert_eq!(message["index"], 1);
    assert_eq!(message["session_id"], "set");
    Ok(())
}
