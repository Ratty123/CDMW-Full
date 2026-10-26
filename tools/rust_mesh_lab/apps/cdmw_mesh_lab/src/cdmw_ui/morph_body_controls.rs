//! Coordinated body controls retain independent detailed slider values.
use super::*;

impl LabApplication {
    pub(super) fn draw_cdmw_body_controls(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        state: &Value,
    ) {
        let authoring = state_bool(&self.cdmw_state, "authoring_enabled");
        let pending = state_bool(state, "authoring_baseline_ready")
            || state_str(state, "correction_definition_id").is_some_and(|id| !id.is_empty());
        let macros = state.get("macro_definitions").and_then(Value::as_array)
            .cloned().unwrap_or_default();
        let values = pair_number_list(state, "macro_values");
        ui.push_id("morph-body-controls", |ui| {
            if macros.is_empty() {
                let unavailable = "Assign a supported body and reset or bake its preview before creating body controls.";
                let ready = authoring && !pending && !state_bool(state, "unbaked")
                    && state_bool(state, "body_controls_available");
                if let Some(reason) = state_str(state, "body_controls_reason").filter(|reason| !reason.trim().is_empty()) {
                    ui.weak(crate::localization::tr(reason));
                } else if !ready {
                    // Say why the page's only action is unavailable without requiring a hover.
                    ui.weak(crate::localization::tr(unavailable));
                }
                if ui.add_enabled(
                    ready,
                    cdmw_primary_button(ui, crate::localization::tr("Create body controls"), ready),
                ).on_disabled_hover_text(crate::localization::tr(unavailable)).clicked() {
                    actions.push(UiAction::CdmwCommand {
                        command: "morph_generate_body_controls",
                        arguments: json!({}),
                        label: "Create body controls",
                    });
                }
                return;
            }
            ui.add_enabled_ui(authoring && !pending, |ui| {
                for definition in &macros {
                    let Some(macro_id) = state_str(definition, "macro_id").filter(|id| !id.is_empty()) else {
                        continue;
                    };
                    let label = state_str(definition, "label").unwrap_or(macro_id);
                    let description = state_str(definition, "description").unwrap_or("");
                    let minimum = definition.get("min_percent").and_then(Value::as_f64)
                        .filter(|value| value.is_finite()).unwrap_or(-100.0);
                    let maximum = definition.get("max_percent").and_then(Value::as_f64)
                        .filter(|value| value.is_finite() && *value > minimum).unwrap_or(100.0);
                    let host_value = values.iter().find(|(id, _)| id == macro_id)
                        .map(|(_, value)| *value).unwrap_or(0.0);
                    let draft_id = format!("macro:{macro_id}");
                    let mut value = self.cdmw_morph_value_drafts.get(&draft_id)
                        .copied().unwrap_or(host_value);
                    let response = ui.push_id(("body-macro", macro_id), |ui| {
                        ui.add(numeric::slider(&mut value, minimum..=maximum)
                            .text(crate::localization::tr(label)))
                            .on_hover_text(crate::localization::tr(description))
                    }).inner;
                    let commit = stage_cdmw_morph_value(
                        &mut self.cdmw_morph_value_drafts,
                        &draft_id,
                        value,
                        response.changed(),
                        response.is_pointer_button_down_on() || response.has_focus(),
                        response.drag_stopped() || response.lost_focus(),
                    );
                    if let Some(value) = commit {
                        actions.push(UiAction::CdmwCommand {
                            command: "morph_set_macro",
                            arguments: json!({"macro_id": macro_id, "value": value, "phase": "end"}),
                            label: "Change body control",
                        });
                    }
                }
                if ui.add_enabled(
                    values.iter().any(|(_, value)| value.abs() > f64::EPSILON),
                    Button::new(crate::localization::tr("Reset body controls")),
                ).clicked() {
                    actions.push(UiAction::CdmwCommand {
                        command: "morph_reset_macros",
                        arguments: json!({}),
                        label: "Reset body controls",
                    });
                }
            });
        });
    }

    pub(super) fn draw_cdmw_side_controls(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        state: &Value,
    ) {
        let Some(pairs) = state.get("side_pairs").and_then(Value::as_array)
            .filter(|pairs| !pairs.is_empty()) else {
            ui.weak(crate::localization::tr("No paired sliders in this profile."));
            return;
        };
        let ready = state_bool(&self.cdmw_state, "authoring_enabled")
            && !state_bool(state, "authoring_baseline_ready")
            && state_str(state, "correction_definition_id").is_none_or(|id| id.is_empty());
        let manual = pair_number_list(state, "manual_values");
        let mode_id = egui::Id::new(("morph-side-mode", state_str(state, "profile_id").unwrap_or("")));
        let mut side = ui.data_mut(|data| data.get_temp::<String>(mode_id)).unwrap_or_else(|| "both".into());
        ui.push_id("morph-side-controls", |ui| {
            ui.add_enabled_ui(ready, |ui| {
                let mut linked = state_bool(state, "symmetry_enabled");
                if ui.checkbox(&mut linked, crate::localization::tr("Link sides"))
                    .on_hover_text(crate::localization::tr("Linking shows matching sides and retains your independent values.")).changed() {
                    actions.push(UiAction::CdmwCommand {
                        command: "morph_set_symmetry",
                        arguments: json!({"enabled": linked}),
                        label: "Change linked side preview",
                    });
                }
                let side_label = ui.label(crate::localization::tr("Edit side"));
                ComboBox::from_id_salt("morph-side-target")
                    .selected_text(crate::localization::tr(match side.as_str() {
                        "left" => "Left", "right" => "Right", _ => "Both",
                    }))
                    .show_ui(ui, |ui| {
                        for (id, label) in [("both", "Both"), ("left", "Left"), ("right", "Right")] {
                            ui.selectable_value(&mut side, id.into(), crate::localization::tr(label));
                        }
                    }).response.labelled_by(side_label.id);
                for pair in pairs {
                    let Some(pair_id) = state_str(pair, "pair_id").filter(|id| !id.is_empty()) else {
                        continue;
                    };
                    let left_id = state_str(pair, "left_definition_id").unwrap_or("");
                    let right_id = state_str(pair, "right_definition_id").unwrap_or("");
                    let Some((_, left)) = manual.iter().find(|(id, _)| id == left_id) else { continue; };
                    let Some((_, right)) = manual.iter().find(|(id, _)| id == right_id) else { continue; };
                    let (host_value, minimum_key, maximum_key) = match side.as_str() {
                        "left" => (*left, "min_percent", "max_percent"),
                        "right" => (*right, "min_percent", "max_percent"),
                        _ => ((*left + *right) * 0.5, "both_min_percent", "both_max_percent"),
                    };
                    let Some(minimum) = pair.get(minimum_key).and_then(Value::as_f64).filter(|v| v.is_finite()) else { continue; };
                    let Some(maximum) = pair.get(maximum_key).and_then(Value::as_f64)
                        .filter(|v| v.is_finite() && *v >= minimum) else { continue; };
                    let label = state_str(pair, "label").unwrap_or(pair_id);
                    let draft_id = format!("pair:{pair_id}:{side}");
                    let mut value = self.cdmw_morph_value_drafts.get(&draft_id)
                        .copied().unwrap_or(host_value);
                    let response = ui.push_id(("body-side", pair_id, side.as_str()), |ui| {
                        ui.add_enabled(minimum < maximum, numeric::slider(&mut value, minimum..=maximum)
                            .text(crate::localization::tr(label)))
                    }).inner;
                    let commit = stage_cdmw_morph_value(
                        &mut self.cdmw_morph_value_drafts,
                        &draft_id,
                        value,
                        response.changed(),
                        response.is_pointer_button_down_on() || response.has_focus(),
                        response.drag_stopped() || response.lost_focus(),
                    );
                    if let Some(value) = commit && ready {
                        actions.push(UiAction::CdmwCommand {
                            command: "morph_set_side_value",
                            arguments: json!({"pair_id": pair_id, "side": side, "value": value, "phase": "end"}),
                            label: "Change body side adjustment",
                        });
                    }
                }
            });
        });
        ui.data_mut(|data| data.insert_temp(mode_id, side));
    }
}
