//! Reversible correction comparison and compatible saved fitting setups.
use super::*;

fn fitting_setup_targets(state: &Value, recipe_id: &str, selected: &[u32]) -> Option<Vec<u32>> {
    let record = state.get("matching_recipe_garments")?.as_array()?.iter()
        .find(|record| record.get(0).and_then(Value::as_str) == Some(recipe_id))?;
    let garments = record.get(1)?.as_array()?.iter()
        .map(|part| part.as_u64().and_then(|part| u32::try_from(part).ok()))
        .collect::<Option<Vec<_>>>()?;
    if garments.is_empty() {
        return None;
    }
    if selected.is_empty() {
        return Some(Vec::new());
    }
    let targets = selected.iter().copied().filter(|part| garments.contains(part)).collect::<Vec<_>>();
    // An empty explicit intersection must never acquire the host's apply-all meaning.
    (!targets.is_empty()).then_some(targets)
}

impl LabApplication {
    pub(super) fn draw_cdmw_correction_comparison(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        state: &Value,
    ) {
        let mut enabled = state.get("corrections_enabled").and_then(Value::as_bool).unwrap_or(true);
        let has_corrections = state.get("definitions").and_then(Value::as_array).is_some_and(|definitions| {
            definitions.iter().any(|definition| !value_u32_list(definition, "garment_correction_submesh_indices").is_empty())
        });
        if !has_corrections && enabled {
            return;
        }
        let ready = state_bool(&self.cdmw_state, "authoring_enabled")
            && !state_bool(state, "authoring_baseline_ready")
            && !state_str(state, "correction_definition_id").is_some_and(|id| !id.is_empty());
        if ui.add_enabled(ready, egui::Checkbox::new(&mut enabled,
            crate::localization::tr("Show outfit corrections")))
            .on_hover_text(crate::localization::tr(
                "Compare the fitted outfit with its saved corrections hidden. The body shape and saved corrections are retained.",
            )).changed()
        {
            actions.push(UiAction::CdmwCommand {
                command: "morph_set_corrections_enabled",
                arguments: json!({"enabled": enabled}),
                label: "Compare outfit corrections",
            });
        }
    }

    pub(super) fn draw_cdmw_correction_comparison_banner(
        &mut self,
        root_ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
    ) {
        if !self.cdmw_morph_comparison_active() {
            return;
        }
        egui::Panel::top("cdmw-correction-comparison")
            .show(root_ui, |ui| {
                ui.horizontal_wrapped(|ui| {
                    ui.colored_label(Color32::from_rgb(245, 190, 75), crate::localization::tr(
                        "Showing the fit without saved corrections. Turn corrections back on to continue editing or finish.",
                    ));
                    if ui.add_enabled(!self.cdmw_busy() && state_bool(&self.cdmw_state, "authoring_enabled"),
                        Button::new(crate::localization::tr("Resume editing"))).clicked() {
                        actions.push(UiAction::CdmwCommand {
                            command: "morph_set_corrections_enabled",
                            arguments: json!({"enabled": true}),
                            label: "Restore outfit corrections",
                        });
                    }
                });
            });
    }

    pub(super) fn draw_cdmw_matching_setups(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        state: &Value,
    ) {
        let authoring = state_bool(&self.cdmw_state, "authoring_enabled");
        let pending = state_bool(state, "authoring_baseline_ready")
            || state_str(state, "correction_definition_id").is_some_and(|id| !id.is_empty());
        let garments = value_u32_list(state.get("refit").unwrap_or(&Value::Null), "garment_submesh_indices");
        let selected = self.selected_part_indices();
        let recipes = pair_list(state, "matching_recipes");
        ui.separator();
        ui.label(RichText::new(crate::localization::tr("Matching fitting setups")).strong());
        ui.small(crate::localization::tr(
            "Saved setups appear here when their body and garment identities match the loaded meshes.",
        ));
        let save_ready = authoring && !pending && !self.cdmw_morph_comparison_active()
            && !state_str(state, "profile_id").unwrap_or("").is_empty()
            && !garments.is_empty() && !self.cdmw_morph_preset_name.trim().is_empty();
        if ui.add_enabled(save_ready, Button::new(crate::localization::tr("Save reusable fitting setup")))
            .on_hover_text(crate::localization::tr("Use the preset name above to save this setup for these meshes."))
            .clicked()
        {
            actions.push(UiAction::CdmwCommand {
                command: "morph_save_setup",
                arguments: json!({"name": self.cdmw_morph_preset_name.trim()}),
                label: "Save reusable fitting setup",
            });
        }
        let ready = authoring && !pending && !self.cdmw_morph_comparison_active()
            && !recipes.is_empty();
        let caption = ui.label(crate::localization::tr("Saved setup"));
        ui.add_enabled_ui(ready, |ui| {
            ComboBox::from_id_salt("morph-matching-setup")
                .width(ui.available_width()).truncate()
                .selected_text(crate::localization::tr("Choose matching setup"))
                .show_ui(ui, |ui| {
                    for (recipe_id, name) in &recipes {
                        let targets = fitting_setup_targets(state, recipe_id, &selected);
                        if ui.add_enabled_ui(targets.is_some(), |ui| ui.selectable_label(false, name))
                            .inner.on_disabled_hover_text(crate::localization::tr(if selected.is_empty() {
                                "No matching saved setups for the loaded meshes."
                            } else {
                                "Selected garment parts are absent from this fitting recipe."
                            })).clicked()
                            && let Some(targets) = targets
                        {
                            actions.push(UiAction::CdmwCommand {
                                command: "morph_apply_setup",
                                arguments: json!({"recipe_id": recipe_id, "garment_submesh_indices": targets}),
                                label: "Apply matching fitting setup",
                            });
                        }
                    }
                }).response.labelled_by(caption.id);
        });
        ui.small(crate::localization::tr(if recipes.is_empty() {
            "No matching saved setups for the loaded meshes."
        } else if selected.is_empty() {
            "Applies to all matching garment Parts."
        } else {
            "Applies to the selected matching garment Parts."
        }));
    }
}
