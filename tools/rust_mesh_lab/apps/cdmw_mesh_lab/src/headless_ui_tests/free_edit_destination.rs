use super::*;

#[test]
fn integrated_free_edit_destination_can_be_chosen_for_an_imported_mesh() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1440.0, 980.0),
    );
    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    ui.application.cdmw_state["output_destination"] = json!("");
    ui.application.cdmw_state["output_destination_ready"] = json!(false);
    ui.application.cdmw_state["output_policy_reason"] =
        json!("Choose a writable output folder before editing this imported mesh.");
    ui.click("Display")?;
    ui.reveal("Choose a writable output folder before editing this imported mesh.")?;

    let actions = ui.actions_from_click("Choose output folder...")?;
    assert!(
        actions
            .iter()
            .any(|action| matches!(action, UiAction::ChooseCdmwFreeEdit))
    );
    assert!(!has_host_command(&actions, "export_free_edit"));
    assert_eq!(ui.application.cdmw_state["output_destination"], json!(""));
    assert!(!has_host_command(
        &ui.actions_from_click("Export Free Edit Package")?,
        "export_free_edit"
    ));
    Ok(())
}

#[test]
fn integrated_free_edit_destination_can_be_changed_without_switching_output_mode() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1440.0, 980.0),
    );
    let destination = "C:/mods/helmet-package";
    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    ui.application.cdmw_state["output_destination"] = json!(destination);
    ui.application.cdmw_state["output_destination_ready"] = json!(true);
    ui.click("Display")?;
    ui.reveal(destination)?;

    let actions = ui.actions_from_click("Change output folder...")?;
    assert!(
        actions
            .iter()
            .any(|action| matches!(action, UiAction::ChooseCdmwFreeEdit))
    );
    assert!(!has_host_command(&actions, "configure_output_policy"));
    assert!(!has_host_command(&actions, "export_free_edit"));
    assert_eq!(
        ui.application.cdmw_state["output_policy"],
        json!("free_edit_rebuild")
    );
    assert_eq!(
        ui.application.cdmw_state["output_destination"],
        json!(destination)
    );
    assert!(has_host_command(
        &ui.actions_from_click("Export Free Edit Package")?,
        "export_free_edit"
    ));
    Ok(())
}

#[test]
fn output_chip_names_the_route_and_opens_its_own_section() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw(triangle_application()?, egui::vec2(1440.0, 980.0));
    // Viewport keeps display settings only.
    ui.click_tool_button("Viewport")?;
    ui.reveal("Display")?;
    assert!(ui.label_rect("Free Edit").is_none());
    assert!(ui.label_rect("Open Package in CDMW...").is_none());
    ui.click("Output: Exact")?;
    let status = ui.reveal("Protected game-asset output")?;
    let viewport = ui.application.viewport_rect.ok_or("viewport")?;
    assert!(status.right() < viewport.left(), "the chip opens the rail's Output section");
    ui.reveal("Free Edit")?;
    ui.reveal("Open Package in CDMW...")?;

    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    ui.frame(Vec::new());
    ui.reveal("Output: Free Edit")?;
    // With the tool rail collapsed, the chip opens Output as a floating panel.
    ui.click_sidebar("Collapse Tools")?;
    ui.click("Output: Free Edit")?;
    let window = ui.tool_window_rect("Output")?;
    let status = ui.reveal("Choose a writable package folder")?;
    assert!(window.contains_rect(status));
    assert!(ui.last_actions.iter().all(|action| !matches!(action, UiAction::CdmwCommand { .. })),
        "opening Output must not change the route: {:?}", ui.last_actions);
    Ok(())
}

#[test]
fn output_stays_reachable_in_a_read_only_session() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw(triangle_application()?, egui::vec2(1440.0, 980.0));
    ui.application.cdmw_state["authoring_enabled"] = json!(false);
    ui.application.cdmw_state["output_policy"] = json!("unavailable");
    ui.frame(Vec::new());
    ui.click_sidebar("Collapse Tools")?;
    ui.click_sidebar("Output")?;
    ui.reveal("Read-only until an authoring output is selected")?;
    let actions = ui.actions_from_click("Exact")?;
    assert!(actions.iter().any(|action| matches!(action,
        UiAction::CdmwCommand { command: "configure_output_policy", arguments, .. }
            if arguments["policy"] == "exact_game_asset")));
    // Importing a package still waits for an authoring route.
    assert!(ui.actions_from_click("Open Package in CDMW...")?.is_empty());
    Ok(())
}
