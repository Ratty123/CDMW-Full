use super::*;

fn new_item_session() -> Result<HeadlessUi, Box<dyn std::error::Error>> {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(triangle_application()?, egui::vec2(1440.0, 980.0));
    ui.application.cdmw_state["output_policy"] = json!("free_edit_rebuild");
    ui.application.cdmw_state["output_destination"] = json!("C:/temp/cdmw-new-item-edits/abc");
    ui.application.cdmw_state["output_destination_ready"] = json!(true);
    ui.application.cdmw_state["handoff_target"] = json!("new_item");
    ui.frame(Vec::new());
    ui.frame(Vec::new());
    Ok(ui)
}

#[test]
fn create_new_item_session_names_the_way_back_and_hides_free_edit_output() -> TestResult {
    let mut ui = new_item_session()?;
    for label in [
        "Finish and return to Create New Item",
        "Editing a model for Create New Item",
        "1 Split into parts",
        "2 Paint cloth",
        "Output: Create New Item",
    ] {
        assert!(ui.label_rect(label).is_some(), "missing {label}");
    }
    assert!(ui.label_rect("Finish Edit Mesh").is_none());
    ui.reveal("Finish sends the edited model back to Create New Item, which builds the item and its package.")?;
    for hidden in ["Export Free Edit Package", "Change output folder...", "Open Package in CDMW...", "C:/temp/cdmw-new-item-edits/abc"] {
        assert!(ui.label_rect(hidden).is_none(), "{hidden} shown");
    }
    Ok(())
}

#[test]
fn create_new_item_banner_opens_the_cloth_and_select_pages() -> TestResult {
    let mut ui = new_item_session()?;
    ui.click("2 Paint cloth")?;
    assert_eq!(ui.application.cdmw_rail_page, Some(CdmwRailPage::Cloth));
    ui.click("1 Split into parts")?;
    assert_eq!(ui.application.cdmw_rail_page, Some(CdmwRailPage::Select));
    Ok(())
}

#[test]
fn create_new_item_session_refuses_tangents_that_the_build_would_drop() -> TestResult {
    let mut ui = new_item_session()?;
    ui.click("Select All")?;
    ui.click("Normals & Tangents")?;
    ui.reveal("Generate Tangents")?;
    assert!(ui.actions_from_click("Generate Tangents")?.is_empty());
    assert!(!ui.actions_from_click("Recalculate Normals")?.is_empty());
    Ok(())
}

#[test]
fn an_ordinary_session_keeps_finish_edit_mesh_and_its_output_choices() -> TestResult {
    let mut ui = new_item_session()?;
    ui.application.cdmw_state["handoff_target"] = json!("");
    ui.frame(Vec::new());
    ui.frame(Vec::new());
    assert!(ui.label_rect("Finish Edit Mesh").is_some());
    assert!(ui.label_rect("Editing a model for Create New Item").is_none());
    assert!(ui.label_rect("Finish and return to Create New Item").is_none());
    ui.reveal("Export Free Edit Package")?;
    Ok(())
}
