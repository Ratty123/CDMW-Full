use super::*;

#[test]
fn integrated_replacement_free_edit_explains_output_and_preserves_disabled_import() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1440.0, 980.0),
    );
    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    ui.application.cdmw_state["replacement"] = json!({
        "available": false, "active": false, "comparison": "edit", "blocked_by": "",
        "reason": "Free Edit exports OBJ geometry without rig weights. Import Replacement requires an original game mesh with Exact output.",
        "parts": [{"index": 0, "id": "stable:0", "name": "Triangle", "included": true}]
    });
    ui.reveal("Free Edit exports OBJ geometry without rig weights. Import Replacement requires an original game mesh with Exact output.")?;
    ui.reveal("For an original PAC, PAM or PAMLOD, choose Exact under Output. For an imported model, open its game target from Archive Browser in Mesh Editor, then import the replacement.")?;
    assert!(ui.actions_from_click("Import Replacement…")?.is_empty());
    assert!(ui.label_rect("Entire Mesh").is_none());
    assert_eq!(
        ui.application.cdmw_state["output_policy"],
        "free_edit_rebuild"
    );

    let actions = ui.actions_from_click("Exact")?;
    assert!(actions.iter().any(|action| matches!(action,
        UiAction::CdmwCommand { command: "configure_output_policy", arguments, .. }
            if arguments["policy"] == "exact_game_asset"
    )));
    Ok(())
}
