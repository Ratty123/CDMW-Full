use super::*;

fn history_ui(cursor: usize) -> Result<HeadlessUi, Box<dyn std::error::Error>> {
    let mut ui = HeadlessUi::new_integrated_cdmw(triangle_application()?, egui::vec2(1400.0, 1000.0));
    ui.application.cdmw_state["history_entries"] = json!([
        {"action":"jiggle", "label":"Set jiggle contribution"},
        {"action":"jiggle", "label":"Set jiggle contribution"},
        {"action":"select", "label":"Select"}
    ]);
    ui.application.cdmw_state["history_cursor"] = json!(cursor);
    ui.application.cdmw_state["undo_count"] = json!(cursor);
    ui.application.cdmw_state["redo_count"] = json!(3 - cursor);
    ui.click("Action History")?;
    Ok(ui)
}

fn right_click(ui: &mut HeadlessUi, label: &str) -> TestResult {
    let position = ui.reveal(label)?.center();
    ui.frame(vec![Event::PointerMoved(position)]);
    ui.frame(vec![pointer_button(position, PointerButton::Secondary, true)]);
    ui.frame(vec![pointer_button(position, PointerButton::Secondary, false)]);
    ui.settle_layout();
    Ok(())
}

#[test]
fn action_history_selects_duplicate_labels_without_editing_and_undoes_from_context_menu() -> TestResult {
    let mut ui = history_ui(3)?;
    let geometry = ui.application.mesh.as_ref().unwrap().geometry_revision;
    let selection = ui.application.mesh.as_ref().unwrap().selection.clone();
    assert!(ui.actions_from_click("● 2. Set jiggle contribution")?.is_empty());
    assert_eq!(ui.application.cdmw_history.selected, Some(1));
    assert_eq!(ui.application.mesh.as_ref().unwrap().geometry_revision, geometry);
    assert_eq!(ui.application.mesh.as_ref().unwrap().selection, selection);
    right_click(&mut ui, "● 1. Set jiggle contribution")?;
    assert_eq!(ui.application.cdmw_history.selected, Some(0));
    assert!(ui.label_rect("Restore through here").is_none());
    let actions = ui.actions_from_click("Undo from here")?;
    assert!(matches!(actions.as_slice(), [UiAction::CdmwHistoryCursor { cursor: 0, revision: 0 }]));
    Ok(())
}

#[test]
fn action_history_restores_through_undone_entry_and_blocks_unconfirmed_requests() -> TestResult {
    let mut ui = history_ui(1)?;
    right_click(&mut ui, "○ 3. Select")?;
    assert!(ui.label_rect("Undo from here").is_none());
    let actions = ui.actions_from_click("Restore through here")?;
    assert!(matches!(actions.as_slice(), [UiAction::CdmwHistoryCursor { cursor: 3, revision: 0 }]));

    ui.application.cdmw_pending_request = Some(CdmwPendingRequest {
        request_id: 2, event: "command_result", label: "Select".into(), origin: Some(CdmwRequestOrigin::Selection),
    });
    right_click(&mut ui, "○ 2. Set jiggle contribution")?;
    assert!(ui.actions_from_click("Restore through here")?.is_empty());
    Ok(())
}
