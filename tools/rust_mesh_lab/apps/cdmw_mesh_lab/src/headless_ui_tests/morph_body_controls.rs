//! Event-driven checks for coordinated controls and retained detailed values.
use super::*;

fn controls_ui() -> Result<HeadlessUi, Box<dyn std::error::Error>> {
    let mut ui = super::morph_authoring::authoring_ui()?;
    let state = &mut ui.application.cdmw_state["morph_refit"];
    state["manual_values"] = json!([["body-shape", 17.5]]);
    state["values"] = json!([["body-shape", 42.5]]);
    state["macro_values"] = json!([["waist_shape", 25.0]]);
    state["macro_definitions"] = json!([{
        "macro_id": "waist_shape",
        "label": "Waist shape",
        "description": "Coordinate the waist and nearby torso regions.",
        "min_percent": -100.0,
        "max_percent": 100.0,
        "contributions": [["body-shape", 1.0]]
    }]);
    ui.frame(Vec::new());
    Ok(ui)
}

fn command_arguments(actions: &[UiAction], expected: &str) -> Value {
    actions.iter().find_map(|action| match action {
        UiAction::CdmwCommand { command, arguments, .. } if *command == expected => Some(arguments.clone()),
        _ => None,
    }).unwrap_or_else(|| panic!("missing {expected}: {actions:?}"))
}

#[test]
fn typed_body_control_submits_independent_macro_and_keeps_manual_values() -> TestResult {
    let mut ui = controls_ui()?;
    ui.click("Body controls")?;
    ui.last_actions.clear();
    ui.type_number_in_row("Waist shape", 25.0, "37.125")?;
    assert_eq!(command_arguments(&ui.last_actions, "morph_set_macro"), json!({
        "macro_id": "waist_shape", "value": 37.125, "phase": "end",
    }));
    assert_eq!(ui.application.cdmw_morph_value_drafts.get("macro:waist_shape"), Some(&37.125));
    assert!(!ui.application.cdmw_morph_value_drafts.contains_key("definition:body-shape"));
    assert_eq!(ui.application.cdmw_state["morph_refit"]["manual_values"], json!([["body-shape", 17.5]]));
    let reset = ui.actions_from_click("Reset body controls")?;
    assert_eq!(command_arguments(&reset, "morph_reset_macros"), json!({}));
    assert!(!reset.iter().any(|action| matches!(action,
        UiAction::CdmwCommand { command: "morph_reset", .. })));
    Ok(())
}

#[test]
fn detailed_slider_shows_manual_input_and_the_combined_preview() -> TestResult {
    let mut ui = controls_ui()?;
    ui.click("Shape sliders")?;
    ui.reveal("Preview value: 42.500%")?;
    ui.last_actions.clear();
    ui.type_number_in_row("Body shape", 17.5, "21.25")?;
    assert_eq!(command_arguments(&ui.last_actions, "morph_set_value"), json!({
        "definition_id": "body-shape", "value": 21.25, "phase": "end",
    }));
    assert_eq!(ui.application.cdmw_state["morph_refit"]["macro_values"], json!([["waist_shape", 25.0]]));
    Ok(())
}

#[test]
fn body_controls_observe_read_only_and_pending_authoring_gates() -> TestResult {
    let mut ui = controls_ui()?;
    ui.click("Body controls")?;
    for (authoring, pending) in [(false, false), (true, true)] {
        ui.application.cdmw_state["authoring_enabled"] = json!(authoring);
        ui.application.cdmw_state["morph_refit"]["authoring_baseline_ready"] = json!(pending);
        ui.frame(Vec::new());
        assert!(ui.actions_from_click("Reset body controls")?.is_empty());
        ui.last_actions.clear();
        ui.type_number_in_row("Waist shape", 25.0, "80")?;
        assert!(ui.last_actions.is_empty());
        assert!(!ui.application.cdmw_morph_value_drafts.contains_key("macro:waist_shape"));
    }
    Ok(())
}

#[test]
fn body_control_creation_uses_resolved_body_availability_and_neutral_preview() -> TestResult {
    let mut ui = super::morph_authoring::authoring_ui()?;
    ui.application.cdmw_state["morph_refit"]["body_controls_available"] = json!(true);
    ui.frame(Vec::new());
    ui.click("Body controls")?;
    let create = ui.actions_from_click("Create body controls")?;
    assert_eq!(command_arguments(&create, "morph_generate_body_controls"), json!({}));
    ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(true);
    ui.frame(Vec::new());
    assert!(ui.actions_from_click("Create body controls")?.is_empty());
    ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(false);
    ui.application.cdmw_state["morph_refit"]["body_controls_available"] = json!(false);
    ui.application.cdmw_state["morph_refit"]["body_controls_reason"] = json!("Assign a supported body first.");
    ui.frame(Vec::new());
    ui.reveal("Assign a supported body first.")?;
    assert!(ui.actions_from_click("Create body controls")?.is_empty());
    Ok(())
}

#[test]
fn macro_request_acknowledgements_target_only_their_own_draft() {
    assert_eq!(cdmw_request_origin("morph_set_macro", &json!({
        "macro_id": "waist_shape", "value": 25.0, "phase": "end",
    })), Some(CdmwRequestOrigin::MorphValue("macro:waist_shape".into())));
    assert_eq!(cdmw_request_origin("morph_set_value", &json!({
        "definition_id": "body-shape", "value": 17.5,
    })), Some(CdmwRequestOrigin::MorphValue("definition:body-shape".into())));
    assert_ne!(
        cdmw_request_origin("morph_set_macro", &json!({"macro_id": "waist_shape"})),
        cdmw_request_origin("morph_set_value", &json!({"definition_id": "macro:waist_shape"})),
    );
    assert!(cdmw_request_origin("morph_set_macro", &json!({"macro_id": " "})).is_none());
}

fn side_controls_ui() -> Result<HeadlessUi, Box<dyn std::error::Error>> {
    let mut ui = controls_ui()?;
    let state = &mut ui.application.cdmw_state["morph_refit"];
    state["manual_values"] = json!([["shoulder-left", 20.0], ["shoulder-right", 50.0]]);
    state["values"] = state["manual_values"].clone();
    state["symmetry_enabled"] = json!(false);
    state["side_pairs"] = json!([{
        "pair_id": "shoulder-size", "label": "Shoulder size",
        "left_definition_id": "shoulder-left", "right_definition_id": "shoulder-right",
        "min_percent": -100.0, "max_percent": 100.0,
        "both_min_percent": -85.0, "both_max_percent": 85.0
    }]);
    ui.frame(Vec::new());
    ui.click("Side adjustments")?;
    Ok(ui)
}

#[test]
fn paired_adjustments_target_both_left_and_right_without_rewriting_manual_state() -> TestResult {
    let mut ui = side_controls_ui()?;
    let original = ui.application.cdmw_state["morph_refit"]["manual_values"].clone();
    ui.last_actions.clear();
    ui.type_number_in_row("Shoulder size", 35.0, "99")?;
    assert_eq!(command_arguments(&ui.last_actions, "morph_set_side_value"), json!({
        "pair_id": "shoulder-size", "side": "both", "value": 85.0, "phase": "end",
    }));
    ui.choose("Edit side", "Both", "Left")?;
    ui.last_actions.clear();
    ui.type_number_in_row("Shoulder size", 20.0, "12.5")?;
    assert_eq!(command_arguments(&ui.last_actions, "morph_set_side_value"), json!({
        "pair_id": "shoulder-size", "side": "left", "value": 12.5, "phase": "end",
    }));
    ui.choose("Edit side", "Left", "Right")?;
    ui.last_actions.clear();
    ui.type_number_in_row("Shoulder size", 50.0, "-6.25")?;
    assert_eq!(command_arguments(&ui.last_actions, "morph_set_side_value"), json!({
        "pair_id": "shoulder-size", "side": "right", "value": -6.25, "phase": "end",
    }));
    assert_eq!(ui.application.cdmw_state["morph_refit"]["manual_values"], original);
    assert_eq!(cdmw_request_origin("morph_set_side_value", &ui.last_actions.iter().find_map(|a| match a {
        UiAction::CdmwCommand { arguments, .. } => Some(arguments.clone()), _ => None,
    }).ok_or("side command")?), Some(CdmwRequestOrigin::MorphValue("pair:shoulder-size:right".into())));
    Ok(())
}

#[test]
fn linking_sides_is_reversible_and_observes_authoring_gates() -> TestResult {
    let mut ui = side_controls_ui()?;
    let link = ui.actions_from_click("Link sides")?;
    assert_eq!(command_arguments(&link, "morph_set_symmetry"), json!({"enabled": true}));
    ui.application.cdmw_state["morph_refit"]["symmetry_enabled"] = json!(true);
    ui.frame(Vec::new());
    let unlink = ui.actions_from_click("Link sides")?;
    assert_eq!(command_arguments(&unlink, "morph_set_symmetry"), json!({"enabled": false}));
    assert_eq!(ui.application.cdmw_state["morph_refit"]["manual_values"], json!([
        ["shoulder-left", 20.0], ["shoulder-right", 50.0],
    ]));
    ui.application.cdmw_state["morph_refit"]["correction_definition_id"] = json!("body-shape");
    ui.frame(Vec::new());
    assert!(ui.actions_from_click("Link sides")?.is_empty());
    ui.last_actions.clear();
    ui.type_number_in_row("Shoulder size", 35.0, "65")?;
    assert!(ui.last_actions.is_empty());
    Ok(())
}

#[test]
fn unchanged_body_control_focus_does_not_swallow_reset() -> TestResult {
    let root = tempdir()?;
    let mut ui = controls_ui()?;
    ui.click("Body controls")?;
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(
        root.path().to_path_buf(), "macro-focus-reset", 1, 0,
    ));
    let value = ui.output.shapes.iter().find_map(|shape| match &shape.shape {
        egui::Shape::Text(text) if text.galley.job.text.parse::<f64>() == Ok(25.0) =>
            Some(text.visual_bounding_rect().center()),
        _ => None,
    }).ok_or("macro number")?;
    ui.click_at(value);
    assert!(ui.application.cdmw_pending_request.is_none());
    ui.click("Reset body controls")?;
    assert_eq!(ui.application.cdmw_pending_request.as_ref().map(|request| request.label.as_str()),
        Some("Reset body controls"), "{:?}", ui.last_actions);
    Ok(())
}
