//! Actual navigation and action-strip interactions across Morph panel presentations.
use super::*;

impl HeadlessUi {
    pub(super) fn scroll_tool_window(&mut self, label: &str, distance: f32) -> TestResult {
        let area = self.tool_window_rect(label)?;
        let position = egui::pos2(area.center().x, area.top() + (area.height() * 0.4));
        self.frame(vec![Event::PointerMoved(position), wheel_event(distance)]);
        self.settle_layout();
        Ok(())
    }

    pub(super) fn open_morph_shape(&mut self, tab: &str) -> TestResult {
        self.click("Shape")?;
        if self.label_rect("Back to sliders").is_some() {
            self.click("Back to sliders")?;
        }
        self.click(tab)
    }

    pub(super) fn open_morph_sliders(&mut self) -> TestResult {
        self.open_morph_shape("Sliders")
    }

    pub(super) fn open_morph_creator(&mut self, sculpted: bool) -> TestResult {
        self.open_morph_sliders()?;
        self.click("+ Create")?;
        self.click(if sculpted { "Sculpted" } else { "Procedural" })
    }

    pub(super) fn open_morph_saved(&mut self, tab: &str) -> TestResult {
        self.click("Saved")?;
        self.click(tab)
    }
}

#[test]
fn workflow_tabs_show_only_the_selected_task_and_keep_drafts() -> TestResult {
    let mut ui = super::morph_authoring::authoring_ui()?;
    ui.reveal("Add as Body...")?;
    assert!(ui.label_rect("Fit to body").is_none());
    ui.click("Fit")?;
    ui.reveal("Fit to body")?;
    assert!(ui.label_rect("Add as Body...").is_none());
    ui.type_number_in_row("Clearance %", 0.0, "1.375")?;
    ui.open_morph_creator(false)?;
    ui.application.cdmw_morph_definition_label = "Retained slider".into();
    ui.reveal("Rule")?;
    ui.open_morph_saved("Fitting setups")?;
    ui.reveal("Load fitting setup...")?;
    assert!(ui.label_rect("Load Preset...").is_none());
    ui.click("Fit")?;
    assert_eq!(ui.application.cdmw_refit_clearance, 1.375);
    assert!(ui.application.cdmw_refit_settings_dirty);
    ui.click("Shape")?;
    ui.reveal("Retained slider")?;
    ui.click_tool_button("Morph & Refit")?;
    ui.click_tool_button("Morph & Refit")?;
    ui.reveal("Retained slider")?;
    Ok(())
}

#[test]
fn workflow_actions_stay_visible_across_tabs_and_panel_presentations() -> TestResult {
    for presentation in ["expanded", "pinned", "floating"] {
        let mut ui = super::morph_authoring::authoring_ui()?;
        ui.size = egui::vec2(1000.0, 650.0);
        ui.application.apply_cdmw_theme_payload(&json!({"font_point_size":18.0,"density":"comfortable"}));
        ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(true);
        ui.settle_layout();
        if presentation != "expanded" {
            ui.click_sidebar("Collapse Tools")?;
            ui.click_sidebar("Morph & Refit")?;
            if presentation == "pinned" {
                ui.click_sidebar("Pin Morph & Refit settings")?;
            }
        }
        for tab in ["Setup", "Fit", "Shape", "Saved"] {
            ui.click(tab)?;
            for delta in [-2_000.0, 2_000.0] {
                if presentation == "floating" {
                    ui.scroll_tool_window("Morph & Refit", delta)?;
                } else {
                    ui.scroll_tool_rail(delta);
                }
                for label in ["Reset", "Bake"] {
                    let rect = ui.label_rect(label).ok_or_else(|| format!("{presentation}/{tab}: {label} scrolled away"))?;
                    assert!(rect.bottom() <= ui.size.y, "{presentation}: footer outside window");
                }
            }
            assert!(has_host_command(&ui.actions_from_click("Bake")?, "morph_bake"));
        }
        ui.application.cdmw_state["morph_refit"]["correction_definition_id"] = json!("body-shape");
        ui.frame(Vec::new());
        ui.click("Setup")?;
        assert!(ui.label_rect("Bake").is_none());
        assert!(has_host_command(&ui.actions_from_click("Save correction")?, "morph_save_correction"));
        assert!(has_host_command(&ui.actions_from_click("Cancel")?, "morph_cancel_correction"));
        ui.application.cdmw_state["morph_refit"]["correction_definition_id"] = json!("");
        ui.application.cdmw_state["morph_refit"]["authoring_baseline_ready"] = json!(true);
        ui.settle_layout();
        for label in ["Save slider", "Discard base"] {
            let rect = ui.label_rect(label).ok_or_else(|| format!("{presentation}: missing {label}"))?;
            assert!(rect.bottom() <= ui.size.y, "{presentation}: pending slider footer outside window");
        }
    }
    Ok(())
}

#[test]
fn workflow_pending_slider_can_be_reopened_and_footer_observes_authoring_policy() -> TestResult {
    let mut ui = super::morph_authoring::authoring_ui()?;
    ui.open_morph_creator(true)?;
    ui.application.cdmw_state["morph_refit"]["authoring_baseline_ready"] = json!(true);
    ui.application.cdmw_morph_definition_label = "Pending shape".into();
    ui.frame(Vec::new());
    ui.click("Setup")?;
    assert!(ui.actions_from_click("Add as Armor...")?.is_empty());
    ui.click("Choose Parts")?;
    ui.click("2 · Sleeve")?;
    assert_eq!(ui.application.selected_part_indices(), vec![1]);
    ui.open_morph_creator(true)?;
    ui.reveal("Pending shape")?;
    ui.open_morph_saved("Profiles")?;
    assert!(ui.actions_from_click("Save Profile")?.is_empty());
    assert!(has_host_command(&ui.actions_from_click("Save slider")?, "morph_capture_authored"));
    ui.application.cdmw_state["authoring_enabled"] = json!(false);
    ui.frame(Vec::new());
    assert!(ui.actions_from_click("Save slider")?.is_empty());
    assert!(ui.actions_from_click("Discard base")?.is_empty());
    ui.application.cdmw_state["morph_refit"]["authoring_baseline_ready"] = json!(false);
    ui.application.cdmw_state["morph_refit"]["unbaked"] = json!(true);
    ui.frame(Vec::new());
    assert!(ui.actions_from_click("Bake")?.is_empty());
    assert!(ui.actions_from_click("Reset")?.is_empty());
    ui.application.cdmw_state["authoring_enabled"] = json!(true);
    ui.application.cdmw_state["morph_refit"]["available"] = json!(false);
    ui.frame(Vec::new());
    assert!(ui.actions_from_click("Bake")?.is_empty());
    assert!(ui.actions_from_click("Reset")?.is_empty());
    Ok(())
}
