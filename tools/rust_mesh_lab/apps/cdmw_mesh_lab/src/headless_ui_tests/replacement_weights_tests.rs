use super::*;

const NO_CHOICE_WARNING: &str = "Choose how to handle this model's weights before applying.";

fn pending_with_weights(weights: serde_json::Value) -> serde_json::Value {
    json!({
        "available": true, "active": false, "comparison": "edit",
        "rig_export": {"available": true, "reason": ""},
        "parts": [{"index": 0, "id": "stable:0", "name": "Triangle", "included": true}],
        "pending": {"token": "weights", "source": "dragon.fbx",
            "targets": [{"id": "stable:0", "name": "Triangle"}],
            "sources": [{"name": "Dragon", "target": "stable:0"}],
            "weights": weights}
    })
}

fn applied_weights(actions: &[UiAction]) -> Option<serde_json::Value> {
    actions.iter().find_map(|action| match action {
        UiAction::CdmwCommand {
            command: "replacement_apply",
            arguments,
            ..
        } => Some(arguments["weights"].clone()),
        _ => None,
    })
}

#[test]
fn matching_rig_keeps_its_weights_by_default() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1440.0, 980.0),
    );
    ui.application.cdmw_state["replacement"] = pending_with_weights(json!({
        "rigged": true, "default": "preserve",
        "summary": "The imported rig matches the original skeleton, so its weights can be kept.",
        "options": [{"policy": "preserve", "enabled": true, "reason": ""},
                    {"policy": "reduce", "enabled": false, "reason": "No vertex uses more than six bones, so there is nothing to reduce."},
                    {"policy": "transfer", "enabled": true, "reason": ""}]
    }));
    ui.reveal("The imported rig matches the original skeleton, so its weights can be kept.")?;
    assert!(ui.label_rect(NO_CHOICE_WARNING).is_none());
    assert_eq!(
        applied_weights(&ui.actions_from_click("Apply Replacement")?),
        Some(json!("preserve"))
    );
    Ok(())
}

#[test]
fn unkeepable_rig_waits_for_a_choice_and_sends_transfer() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1440.0, 980.0),
    );
    ui.application.cdmw_state["replacement"] = pending_with_weights(json!({
        "rigged": true, "default": "",
        "summary": "The imported weights cannot be kept: bone7 is off.",
        "options": [{"policy": "preserve", "enabled": false, "reason": "bone7 is off."},
                    {"policy": "reduce", "enabled": false, "reason": "No vertex uses more than six bones, so there is nothing to reduce."},
                    {"policy": "transfer", "enabled": true, "reason": ""}]
    }));
    ui.reveal(NO_CHOICE_WARNING)?;
    // Apply is disabled and Keep cannot be picked while no usable choice is made.
    assert_eq!(
        applied_weights(&ui.actions_from_click("Apply Replacement")?),
        None
    );
    ui.click("Keep Imported Weights")?;
    assert_eq!(
        applied_weights(&ui.actions_from_click("Apply Replacement")?),
        None
    );
    ui.click("Transfer from Original")?;
    assert!(ui.label_rect(NO_CHOICE_WARNING).is_none());
    assert_eq!(
        applied_weights(&ui.actions_from_click("Apply Replacement")?),
        Some(json!("transfer"))
    );
    Ok(())
}

#[test]
fn unrigged_import_sends_no_weights_choice() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1440.0, 980.0),
    );
    ui.application.cdmw_state["replacement"] = pending_with_weights(json!({"rigged": false}));
    let actions = ui.actions_from_click("Apply Replacement")?;
    assert!(actions.iter().any(|action| matches!(action,
        UiAction::CdmwCommand { command: "replacement_apply", arguments, .. } if arguments.get("weights").is_none())));
    assert!(ui.label_rect("Keep Imported Weights").is_none());
    Ok(())
}

#[test]
fn export_rig_glb_asks_for_a_folder_only_when_a_skeleton_is_attached() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1440.0, 980.0),
    );
    ui.application.cdmw_state["replacement"] = json!({
        "available": true, "comparison": "edit", "rig_export": {"available": true, "reason": ""},
        "parts": [{"index": 0, "id": "stable:0", "name": "Triangle", "included": true}]
    });
    assert!(
        ui.actions_from_click("Export Rig GLB…")?
            .iter()
            .any(|action| matches!(action, UiAction::ChooseCdmwRigExport))
    );
    ui.application.cdmw_state["replacement"]["rig_export"] =
        json!({"available": false, "reason": "No matching PAB skeleton."});
    assert!(
        !ui.actions_from_click("Export Rig GLB…")?
            .iter()
            .any(|action| matches!(action, UiAction::ChooseCdmwRigExport))
    );
    Ok(())
}

#[test]
fn last_import_weight_notes_are_listed_under_the_parts() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1440.0, 980.0),
    );
    ui.application.cdmw_state["replacement"] = json!({
        "available": true, "active": true, "comparison": "edit",
        "weight_notes": ["Skin weights target 0 (Triangle): transferred 3 vertices."],
        "parts": [{"index": 0, "id": "stable:0", "name": "Triangle", "included": true}]
    });
    ui.click("Weights from the last import")?;
    ui.reveal("Skin weights target 0 (Triangle): transferred 3 vertices.")?;
    Ok(())
}
