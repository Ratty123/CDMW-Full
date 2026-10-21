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
