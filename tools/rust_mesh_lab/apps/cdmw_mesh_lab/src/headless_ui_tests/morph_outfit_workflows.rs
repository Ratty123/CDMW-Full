//! Actual egui interactions for correction comparison and saved fitting setups.
use super::*;

fn outfit_ui() -> Result<HeadlessUi, Box<dyn std::error::Error>> {
    let mut ui = super::morph_authoring::authoring_ui()?;
    let state = &mut ui.application.cdmw_state["morph_refit"];
    state["corrections_enabled"] = json!(true);
    state["definitions"][0]["garment_correction_submesh_indices"] = json!([1, 2]);
    state["matching_recipes"] = json!([["setup-stable-identity", "Sleeve and plate fit"]]);
    state["matching_recipe_garments"] = json!([["setup-stable-identity", [1, 2]]]);
    ui.application.cdmw_morph_preset_name = "Studio outfit".into();
    ui.frame(Vec::new());
    Ok(ui)
}

fn select_parts(ui: &mut HeadlessUi, parts: &[u32]) -> TestResult {
    ui.application.mesh.as_mut().ok_or("mesh")?.set_selection(Selection {
        submeshes: parts.iter().copied().collect(), ..Selection::default()
    })?;
    ui.frame(Vec::new());
    Ok(())
}

fn command_arguments(actions: &[UiAction], expected: &str) -> Value {
    actions.iter().find_map(|action| match action {
        UiAction::CdmwCommand { command, arguments, .. } if *command == expected => Some(arguments.clone()),
        _ => None,
    }).unwrap_or_else(|| panic!("missing {expected}: {actions:?}"))
}

#[test]
fn correction_reset_targets_only_selected_corrected_bound_garments() -> TestResult {
    let mut ui = outfit_ui()?;
    ui.open_morph_sliders()?;
    assert!(ui.actions_from_click("Reset selected outfit correction")?.is_empty());
    select_parts(&mut ui, &[0, 2])?;
    let reset = ui.actions_from_click("Reset selected outfit correction")?;
    assert_eq!(command_arguments(&reset, "morph_reset_correction"), json!({
        "definition_id": "body-shape", "garment_submesh_indices": [2],
    }));
    ui.application.cdmw_state["morph_refit"]["definitions"][0]["garment_correction_submesh_indices"] = json!([1]);
    ui.frame(Vec::new());
    assert!(ui.actions_from_click("Reset selected outfit correction")?.is_empty());
    select_parts(&mut ui, &[1, 2])?;
    let reset = ui.actions_from_click("Reset selected outfit correction")?;
    assert_eq!(command_arguments(&reset, "morph_reset_correction"), json!({
        "definition_id": "body-shape", "garment_submesh_indices": [1],
    }));
    Ok(())
}

#[test]
fn correction_comparison_preserves_authoring_policy_and_keeps_restore_and_history_available() -> TestResult {
    let mut ui = outfit_ui()?;
    select_parts(&mut ui, &[2])?;
    ui.open_morph_sliders()?;
    let hide = ui.actions_from_click("Show outfit corrections")?;
    assert_eq!(command_arguments(&hide, "morph_set_corrections_enabled"), json!({"enabled": false}));
    let output_policy = ui.application.cdmw_state["output_policy"].clone();
    ui.application.cdmw_state["morph_refit"]["corrections_enabled"] = json!(false);
    ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(true);
    ui.application.cdmw_state["undo_count"] = json!(1);
    ui.application.cdmw_state["redo_count"] = json!(1);
    ui.application.cdmw_host_connected = true;
    ui.frame(Vec::new());
    ui.reveal("Showing the fit without saved corrections. Turn corrections back on to continue editing or finish.")?;
    for label in ["Edit outfit correction", "Reset selected outfit correction", "Reset", "Bake", "Finish Edit Mesh"] {
        assert!(ui.actions_from_click(label)?.is_empty(), "{label} must be disabled during comparison");
    }
    assert!(ui.actions_from_click("Undo")?.iter().any(|action| matches!(action, UiAction::Undo)));
    assert!(ui.actions_from_click("Redo")?.iter().any(|action| matches!(action, UiAction::Redo)));
    assert_eq!(ui.application.cdmw_state["authoring_enabled"], json!(true));
    assert_eq!(ui.application.cdmw_state["output_policy"], output_policy);
    let resume = ui.actions_from_click("Resume editing")?;
    assert_eq!(command_arguments(&resume, "morph_set_corrections_enabled"), json!({"enabled": true}));
    let show = ui.actions_from_click("Show outfit corrections")?;
    assert_eq!(command_arguments(&show, "morph_set_corrections_enabled"), json!({"enabled": true}));
    Ok(())
}

#[test]
fn correction_comparison_allows_selection_but_blocks_keyboard_and_pointer_edits() -> TestResult {
    let mut ui = outfit_ui()?;
    ui.application.cdmw_state["morph_refit"]["corrections_enabled"] = json!(false);
    ui.application.selection_domain = SelectionDomain::Vertex;
    ui.frame(Vec::new());
    ui.click("Setup")?;
    ui.click("Choose Parts")?;
    ui.click("Open Selection tool")?;
    let selection = ui.actions_from_click("Select All")?;
    assert!(selection.iter().any(|action| matches!(action, UiAction::SelectAllVertices)));
    assert!(!ui.application.mesh.as_ref().ok_or("mesh")?.selection.vertices.is_empty());
    let before = ui.application.mesh.as_ref().ok_or("mesh")?.draw_snapshot();
    ui.application.handle_actions(vec![UiAction::Nudge(Vec3::X), UiAction::FinishCdmw]);
    assert_eq!(ui.application.mesh.as_ref().ok_or("mesh")?.draw_snapshot(), before);
    assert!(!ui.application.cdmw_exit_requested);
    ui.application.cdmw_orbit_mode = false;
    ui.application.viewport_tool = ViewportTool::Move;
    ui.application.begin_primary_gesture(crate::headless_tests::viewport(), Vec2::ZERO);
    assert!(ui.application.edit_gesture.is_none());
    assert!(UiAction::CdmwHistoryCursor { cursor: 0, revision: 1 }.allowed_during_morph_comparison());
    assert!(UiAction::CdmwCommand {
        command: "replacement_cancel", arguments: json!({}), label: "Cancel import",
    }.allowed_during_morph_comparison());
    Ok(())
}

#[test]
fn saved_setups_dispatch_the_name_and_explicit_selected_garment_scope() -> TestResult {
    let mut ui = outfit_ui()?;
    select_parts(&mut ui, &[0, 2])?;
    ui.open_morph_saved("Fitting setups")?;
    let save = ui.actions_from_click("Save reusable fitting setup")?;
    assert_eq!(command_arguments(&save, "morph_save_setup"), json!({"name": "Studio outfit"}));
    ui.last_actions.clear();
    ui.choose("Saved setup", "Choose matching setup", "Sleeve and plate fit")?;
    assert_eq!(command_arguments(&ui.last_actions, "morph_apply_setup"), json!({
        "recipe_id": "setup-stable-identity", "garment_submesh_indices": [2],
    }));
    select_parts(&mut ui, &[])?;
    ui.last_actions.clear();
    ui.choose("Saved setup", "Choose matching setup", "Sleeve and plate fit")?;
    assert_eq!(command_arguments(&ui.last_actions, "morph_apply_setup"), json!({
        "recipe_id": "setup-stable-identity", "garment_submesh_indices": [],
    }));
    Ok(())
}

#[test]
fn saved_setup_matching_and_pending_authoring_gates_are_enforced() -> TestResult {
    let mut ui = outfit_ui()?;
    ui.open_morph_saved("Fitting setups")?;
    ui.application.cdmw_state["morph_refit"]["authoring_baseline_ready"] = json!(true);
    ui.frame(Vec::new());
    ui.click("Choose matching setup")?;
    assert!(ui.label_rect("Sleeve and plate fit").is_none());
    assert!(ui.actions_from_click("Save reusable fitting setup")?.is_empty());
    ui.application.cdmw_state["morph_refit"]["authoring_baseline_ready"] = json!(false);
    ui.application.cdmw_state["morph_refit"]["matching_recipes"] = json!([]);
    ui.frame(Vec::new());
    ui.reveal("No matching saved setups for the loaded meshes.")?;
    ui.click("Choose matching setup")?;
    assert!(ui.label_rect("Sleeve and plate fit").is_none());
    Ok(())
}

#[test]
fn matching_saved_setup_applies_during_an_active_unbaked_preview() -> TestResult {
    let mut ui = outfit_ui()?;
    select_parts(&mut ui, &[2])?;
    ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(true);
    ui.application.cdmw_state["morph_refit"]["values"] = json!([["body-shape", 42.5]]);
    ui.frame(Vec::new());
    ui.open_morph_saved("Fitting setups")?;
    let save = ui.actions_from_click("Save reusable fitting setup")?;
    assert_eq!(command_arguments(&save, "morph_save_setup"), json!({"name": "Studio outfit"}));
    ui.last_actions.clear();
    ui.choose("Saved setup", "Choose matching setup", "Sleeve and plate fit")?;
    assert_eq!(command_arguments(&ui.last_actions, "morph_apply_setup"), json!({
        "recipe_id": "setup-stable-identity", "garment_submesh_indices": [2],
    }));
    assert_eq!(ui.application.cdmw_state["morph_refit"]["values"], json!([["body-shape", 42.5]]));
    assert_eq!(ui.application.cdmw_state["morph_refit"]["unbaked"], json!(true));
    Ok(())
}

#[test]
fn saved_setup_keeps_selected_recipe_garments_without_current_bindings() -> TestResult {
    for current_garments in [json!([]), json!([1])] {
        let mut ui = outfit_ui()?;
        let state = &mut ui.application.cdmw_state["morph_refit"];
        state["profile_id"] = json!("");
        state["driver_submesh_indices"] = json!([]);
        state["refit"]["garment_submesh_indices"] = current_garments;
        select_parts(&mut ui, &[0, 2])?;
        ui.open_morph_saved("Fitting setups")?;
        ui.last_actions.clear();
        ui.choose("Saved setup", "Choose matching setup", "Sleeve and plate fit")?;
        assert_eq!(command_arguments(&ui.last_actions, "morph_apply_setup"), json!({
            "recipe_id": "setup-stable-identity", "garment_submesh_indices": [2],
        }));
    }
    Ok(())
}

#[test]
fn saved_setup_never_widens_an_unmatched_selection_to_all_garments() -> TestResult {
    let mut ui = outfit_ui()?;
    select_parts(&mut ui, &[0])?;
    ui.open_morph_saved("Fitting setups")?;
    ui.last_actions.clear();
    ui.choose("Saved setup", "Choose matching setup", "Sleeve and plate fit")?;
    assert!(ui.last_actions.is_empty());
    Ok(())
}

#[test]
fn saved_setup_requires_its_verified_garment_roles_before_application() -> TestResult {
    let mut ui = outfit_ui()?;
    ui.application.cdmw_state["morph_refit"]["matching_recipe_garments"] = json!([]);
    select_parts(&mut ui, &[])?;
    ui.open_morph_saved("Fitting setups")?;
    ui.last_actions.clear();
    ui.choose("Saved setup", "Choose matching setup", "Sleeve and plate fit")?;
    assert!(ui.last_actions.is_empty());
    Ok(())
}
