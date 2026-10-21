//! Real egui interactions for authored sliders and selective garment fitting.
//! The harness collects typed host commands and intercepts file picker actions.
use super::*;

pub(super) fn authoring_ui() -> Result<HeadlessUi, Box<dyn std::error::Error>> {
    let mut application = two_part_application()?;
    let document = Arc::make_mut(application.document.as_mut().ok_or("document")?);
    document.lods[0].submeshes[0].name = "Body".into();
    document.lods[0].submeshes[1].name = "Sleeve".into();
    let mut plate = document.lods[0].submeshes[1].clone();
    plate.name = "Plate".into();
    for position in &mut plate.positions {
        position[0] += 3.0;
    }
    document.lods[0].submeshes.push(plate);
    application.mesh = Some(WorkingMesh::from_document(document)?);
    application.projection = None;
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        application, egui::vec2(1_440.0, 2_000.0),
    );
    ui.application.cdmw_state["morph_refit"] = json!({
        "profile_id": "authored-body",
        "state_revision": 1,
        "available_profiles": [["authored-body", "Body profile"]],
        "available_presets": [],
        "driver_submesh_indices": [0],
        "authoring_baseline_ready": false,
        "correction_definition_id": "",
        "unbaked": false,
        "definitions": [{
            "definition_id": "body-shape",
            "label": "Body shape",
            "category": "Authored",
            "source_kind": "authored",
            "min_percent": 0.0,
            "max_percent": 100.0,
            "default_percent": 0.0
        }],
        "values": [["body-shape", 0.0]],
        "refit": {
            "driver_submesh_indices": [0],
            "garment_submesh_indices": [1, 2],
            "garment_settings": [
                {"submesh_index": 1, "enabled": true, "intensity_percent": 100.0, "mode": "surface", "clearance_percent": 0.0, "tightness_percent": 0.0},
                {"submesh_index": 2, "enabled": true, "intensity_percent": 100.0, "mode": "surface", "clearance_percent": 0.0, "tightness_percent": 0.0}
            ]
        }
    });
    ui.click("Morph & Refit")?;
    Ok(ui)
}

fn select_authoring_parts(ui: &mut HeadlessUi, parts: &[u32]) -> TestResult {
    ui.application.mesh.as_mut().ok_or("mesh")?.set_selection(Selection {
        submeshes: parts.iter().copied().collect(),
        ..Selection::default()
    })?;
    ui.frame(Vec::new());
    Ok(())
}

fn select_authoring_element(
    ui: &mut HeadlessUi, part: u32, domain: SelectionDomain,
) -> TestResult {
    let mesh = ui.application.mesh.as_mut().ok_or("mesh")?;
    let handles = mesh.element_handles_for_submeshes(&HashSet::from([part]));
    let mut selection = Selection::default();
    match domain {
        SelectionDomain::Vertex => {
            selection.vertices.insert(*handles.vertices.iter().next().ok_or("part vertex")?);
        }
        SelectionDomain::Face => {
            selection.faces.insert(*handles.faces.iter().next().ok_or("part face")?);
        }
        SelectionDomain::Edge => return Err("unused authoring selection domain".into()),
    }
    mesh.set_selection(selection)?;
    ui.frame(Vec::new());
    Ok(())
}

fn command_arguments(actions: &[UiAction], expected: &str) -> Value {
    actions.iter().find_map(|action| match action {
        UiAction::CdmwCommand { command, arguments, .. } if *command == expected => Some(arguments.clone()),
        _ => None,
    }).unwrap_or_else(|| panic!("missing {expected}: {actions:?}"))
}

fn replace_authoring_text(ui: &mut HeadlessUi, current: &str, replacement: &str) -> TestResult {
    ui.click(current)?;
    let modifiers = egui::Modifiers { ctrl: true, command: true, ..egui::Modifiers::NONE };
    ui.frame(vec![
        Event::Key {
            key: egui::Key::A, physical_key: None, pressed: true, repeat: false, modifiers,
        },
        Event::Key {
            key: egui::Key::A, physical_key: None, pressed: false, repeat: false, modifiers,
        },
        Event::Text(replacement.into()),
    ]);
    ui.frame(vec![key_event(egui::Key::Enter, true)]);
    ui.frame(vec![key_event(egui::Key::Enter, false)]);
    Ok(())
}

#[test]
fn authored_capture_discard_and_typed_slider_save_dispatch_exact_commands() -> TestResult {
    let mut ui = authoring_ui()?;
    select_authoring_parts(&mut ui, &[1])?;
    ui.open_morph_creator(true)?;
    let capture = ui.actions_from_click("Capture body base")?;
    assert_eq!(command_arguments(&capture, "morph_capture_baseline"), json!({"submesh_indices": [0]}));
    assert!(ui.label_rect("Save slider").is_none());

    ui.application.cdmw_state["morph_refit"]["authoring_baseline_ready"] = json!(true);
    ui.application.cdmw_morph_definition_label = "Draft shape".into();
    ui.frame(Vec::new());
    replace_authoring_text(&mut ui, "Body profile", "Athletic body")?;
    replace_authoring_text(&mut ui, "Draft shape", "Athletic fit")?;
    let save = ui.actions_from_click("Save slider")?;
    assert_eq!(command_arguments(&save, "morph_capture_authored"), json!({
        "definition": {
            "profile_id": "authored-body",
            "profile_name": "Athletic body",
            "definition_id": "morph-athletic-fit",
            "label": "Athletic fit",
            "category": "Authored",
            "min_percent": 0.0,
            "max_percent": 100.0,
            "default_percent": 0.0
        }
    }));
    let discard = ui.actions_from_click("Discard base")?;
    assert_eq!(command_arguments(&discard, "morph_cancel_baseline"), json!({}));
    ui.application.cdmw_state["morph_refit"]["authoring_baseline_ready"] = json!(false);
    ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(true);
    ui.frame(Vec::new());
    assert!(ui.actions_from_click("Capture body base")?.is_empty());
    ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(false);
    ui.application.cdmw_state["morph_refit"]["driver_submesh_indices"] = json!([]);
    ui.frame(Vec::new());
    assert!(ui.actions_from_click("Capture body base")?.is_empty());
    Ok(())
}

#[test]
fn correction_start_save_and_cancel_use_explicit_selected_garments() -> TestResult {
    let mut ui = authoring_ui()?;
    ui.open_morph_sliders()?;
    assert!(ui.actions_from_click("Edit outfit correction")?.is_empty());
    select_authoring_parts(&mut ui, &[0, 2])?;
    let begin = ui.actions_from_click("Edit outfit correction")?;
    assert_eq!(command_arguments(&begin, "morph_begin_correction"), json!({
        "definition_id": "body-shape", "garment_submesh_indices": [2],
    }));
    ui.application.cdmw_state["morph_refit"]["correction_definition_id"] = json!("body-shape");
    ui.frame(Vec::new());
    let save = ui.actions_from_click("Save correction")?;
    assert_eq!(command_arguments(&save, "morph_save_correction"), json!({}));
    let cancel = ui.actions_from_click("Cancel")?;
    assert_eq!(command_arguments(&cancel, "morph_cancel_correction"), json!({}));
    assert!(ui.actions_from_click("Edit outfit correction")?.is_empty());
    ui.open_morph_creator(true)?;
    assert!(ui.actions_from_click("Capture body base")?.is_empty());
    Ok(())
}

#[test]
fn garment_influence_controls_keep_vertex_scope_and_type_fractional_weights() -> TestResult {
    let mut ui = authoring_ui()?;
    ui.click("Fit")?;
    ui.open_refit_detail("Local influence")?;
    assert!(ui.actions_from_click("Set selected influence")?.is_empty());
    select_authoring_element(&mut ui, 1, SelectionDomain::Vertex)?;
    ui.type_number_in_row("Selected influence", 100.0, "37.5")?;
    let set = ui.actions_from_click("Set selected influence")?;
    assert_eq!(command_arguments(&set, "morph_set_influence"), json!({
        "weight": 0.375, "garment_submesh_indices": [],
    }));
    for (label, weight) in [("Protect selection", 0.0), ("Restore selected influence", 1.0)] {
        let actions = ui.actions_from_click(label)?;
        assert_eq!(command_arguments(&actions, "morph_set_influence"), json!({
            "weight": weight, "garment_submesh_indices": [],
        }));
    }
    assert!(ui.actions_from_click("Clear masks on selected garments")?.is_empty());
    select_authoring_parts(&mut ui, &[1, 2])?;
    let clear = ui.actions_from_click("Clear masks on selected garments")?;
    assert_eq!(command_arguments(&clear, "morph_clear_influence"), json!({"garment_submesh_indices": [1, 2]}));
    Ok(())
}

fn toggle_region_target(ui: &mut HeadlessUi, garment: &str) -> TestResult {
    ui.click(garment)
}

#[test]
fn garment_fit_choices_use_the_single_scoped_editor_and_preserve_skip() -> TestResult {
    let mut ui = authoring_ui()?;
    ui.click("Fit")?;
    assert!(ui.label_rect("2 · Sleeve").is_none());
    let fit = ui.reveal("Fit all enabled garments")?;
    assert!(fit.bottom() < ui.reveal("Adjust garments")?.top());
    ui.click("Review parts")?;
    ui.click("3 · Plate")?;
    ui.choose("Fit as", "Flexible", "Rigid component")?;
    let rigid = ui.actions_from_click("Apply to Selected Garments")?;
    assert_eq!(command_arguments(&rigid, "refit_configure"),
        json!({"submesh_indices": [2], "mode": "rigid_component"}));
    ui.application.cdmw_state["morph_refit"]["refit"]["garment_settings"][1]["mode"] = json!("rigid_component");
    ui.application.cdmw_refit_settings_dirty = Default::default();
    ui.frame(Vec::new());
    ui.choose("Fit as", "Rigid component", "Skip")?;
    let skip = ui.actions_from_click("Apply to Selected Garments")?;
    assert_eq!(command_arguments(&skip, "refit_configure"), json!({"submesh_indices": [2], "enabled": false}));
    ui.application.cdmw_state["morph_refit"]["refit"]["garment_settings"][1]["enabled"] = json!(false);
    ui.application.cdmw_refit_settings_dirty = Default::default();
    ui.frame(Vec::new());
    ui.reveal("Skip")?;
    ui.choose("Fit as", "Skip", "Flexible")?;
    let flexible = ui.actions_from_click("Apply to Selected Garments")?;
    assert_eq!(command_arguments(&flexible, "refit_configure"),
        json!({"submesh_indices": [2], "enabled": true, "mode": "surface"}));
    ui.application.cdmw_refit_settings_dirty = Default::default();
    assert_eq!(command_arguments(&ui.actions_from_click("Fit all enabled garments")?, "refit_fit_to_body"), json!({}));
    Ok(())
}

#[test]
fn fit_waits_for_pending_settings_and_legacy_offset_mode_is_not_labelled_rigid() -> TestResult {
    let mut ui = authoring_ui()?;
    ui.application.cdmw_state["morph_refit"]["refit"]["garment_settings"][1]["mode"] = json!("rigid");
    select_authoring_parts(&mut ui, &[2])?;
    ui.click("Fit")?;
    ui.choose("Fit as", "Offset follow", "Rigid component")?;
    assert!(ui.actions_from_click("Fit all enabled garments")?.is_empty());
    assert_eq!(command_arguments(&ui.actions_from_click("Apply to Selected Garments")?, "refit_configure"),
        json!({"submesh_indices": [2], "mode": "rigid_component"}));
    Ok(())
}

#[test]
fn fit_garment_names_highlight_parts_and_scope_strength_in_compact_sections() -> TestResult {
    let mut ui = authoring_ui()?;
    ui.application.cdmw_state["morph_refit"]["refit"]["garment_settings"][0]["intensity_percent"] = json!(37.5);
    ui.application.cdmw_state["morph_refit"]["refit"]["garment_settings"][1]["intensity_percent"] = json!(125.0);
    ui.click("Fit")?;
    ui.open_refit_detail("Body region")?;
    ui.open_refit_detail("Body region")?;
    ui.click("Review parts")?;
    ui.click("2 · Sleeve")?;
    assert_eq!(ui.application.selected_part_indices(), vec![1]);
    assert_eq!(ui.application.cdmw_refit_intensity, 37.5);
    assert!(ui.application.cdmw_refit_region_targets.is_empty());

    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    let expected = mesh.faces()
        .filter(|(_, face)| face.submesh == 1)
        .flat_map(|(_, face)| face.vertices.iter())
        .map(|handle| mesh.vertex(*handle).expect("face vertex").position)
        .collect::<Vec<_>>();
    assert!(!expected.is_empty());
    assert_eq!(ui.application.face_selection_overlay.as_ref().ok_or("garment highlight")?.positions, expected);
    ui.open_refit_detail("Follow body shape")?;
    ui.type_number_in_row("Body-shape following %", 37.5, "42.5")?;
    assert_eq!(command_arguments(&ui.actions_from_click("Apply to Selected Garments")?, "refit_configure"),
        json!({"submesh_indices": [1], "intensity_percent": 42.5}));

    ui.click("3 · Plate")?;
    assert_eq!(ui.application.selected_part_indices(), vec![2]);
    assert_eq!(ui.application.cdmw_refit_intensity, 125.0);
    let position = ui.reveal("2 · Sleeve")?.center();
    let modifiers = egui::Modifiers { ctrl: true, command: true, ..egui::Modifiers::NONE };
    ui.frame(vec![Event::PointerMoved(position), Event::ModifiersChanged(modifiers)]);
    for pressed in [true, false] {
        ui.frame(vec![Event::PointerButton { pos: position, button: PointerButton::Primary, pressed, modifiers }]);
    }
    ui.frame(vec![Event::ModifiersChanged(egui::Modifiers::NONE)]);
    assert_eq!(ui.application.selected_part_indices(), vec![1, 2]);
    ui.open_refit_detail("Local influence")?;
    ui.type_number_in_row("Selected influence", 100.0, "50")?;
    assert_eq!(command_arguments(&ui.actions_from_click("Set selected influence")?, "morph_set_influence"),
        json!({"garment_submesh_indices": [1, 2], "weight": 0.5}));
    Ok(())
}

#[test]
fn body_region_targets_remain_explicit_when_viewport_selection_changes() -> TestResult {
    let mut ui = authoring_ui()?;
    ui.click("Fit")?;
    ui.open_refit_detail("Body region")?;
    select_authoring_element(&mut ui, 0, SelectionDomain::Face)?;
    let body_faces = ui.application.mesh.as_ref().ok_or("mesh")?.selection.faces.clone();
    assert!(ui.actions_from_click("Use selected body region")?.is_empty());
    toggle_region_target(&mut ui, "2 · Sleeve")?;
    assert_eq!(ui.application.cdmw_refit_region_targets, vec![1]);
    assert!(ui.application.selected_part_indices().is_empty());
    assert_eq!(ui.application.mesh.as_ref().ok_or("mesh")?.selection.faces, body_faces);
    let scoped = ui.actions_from_click("Use selected body region")?;
    assert_eq!(command_arguments(&scoped, "morph_set_driver_region"), json!({"garment_submesh_indices": [1]}));

    select_authoring_parts(&mut ui, &[])?;
    assert_eq!(ui.application.cdmw_refit_region_targets, vec![1]);
    assert!(ui.actions_from_click("Use selected body region")?.is_empty());
    let clear = ui.actions_from_click("Use whole body")?;
    assert_eq!(command_arguments(&clear, "morph_clear_driver_region"), json!({"garment_submesh_indices": [1]}));
    select_authoring_element(&mut ui, 0, SelectionDomain::Face)?;
    toggle_region_target(&mut ui, "3 · Plate")?;
    toggle_region_target(&mut ui, "2 · Sleeve")?;
    let plate = ui.actions_from_click("Use selected body region")?;
    assert_eq!(command_arguments(&plate, "morph_set_driver_region"), json!({"garment_submesh_indices": [2]}));
    ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(true);
    ui.frame(Vec::new());
    assert!(ui.actions_from_click("Use selected body region")?.is_empty());
    assert!(ui.actions_from_click("Use whole body")?.is_empty());
    Ok(())
}

#[test]
fn rigid_component_combo_dispatches_mode_with_typed_intensity() -> TestResult {
    let mut ui = authoring_ui()?;
    select_authoring_parts(&mut ui, &[2])?;
    ui.click("Fit")?;
    ui.choose("Fit as", "Flexible", "Rigid component")?;
    ui.open_refit_detail("Follow body shape")?;
    ui.type_number_in_row("Body-shape following %", 100.0, "175")?;
    assert_eq!(ui.application.cdmw_refit_mode, "rigid_component");
    let apply = ui.actions_from_click("Apply to Selected Garments")?;
    assert_eq!(command_arguments(&apply, "refit_configure"), json!({
        "submesh_indices": [2], "intensity_percent": 175.0, "mode": "rigid_component",
    }));
    Ok(())
}

#[test]
fn fitting_setup_pickers_dispatch_and_observe_pending_authoring_gates() -> TestResult {
    let mut ui = authoring_ui()?;
    ui.open_morph_saved("Fitting setups")?;
    let save = ui.actions_from_click("Save fitting setup...")?;
    assert!(save.iter().any(|action| matches!(action, UiAction::ChooseCdmwRefitRecipe { save: true })));
    let load = ui.actions_from_click("Load fitting setup...")?;
    assert!(load.iter().any(|action| matches!(action, UiAction::ChooseCdmwRefitRecipe { save: false })));
    ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(true);
    ui.frame(Vec::new());
    assert!(ui.actions_from_click("Load fitting setup...")?.is_empty());
    assert!(ui.actions_from_click("Save fitting setup...")?.iter().any(
        |action| matches!(action, UiAction::ChooseCdmwRefitRecipe { save: true }),
    ));
    ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(false);
    ui.application.cdmw_state["morph_refit"]["authoring_baseline_ready"] = json!(true);
    ui.frame(Vec::new());
    assert!(ui.actions_from_click("Save fitting setup...")?.is_empty());
    assert!(ui.actions_from_click("Load fitting setup...")?.is_empty());
    Ok(())
}
