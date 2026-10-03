#![forbid(unsafe_code)]
use super::*;

impl LabApplication {
    pub(super) fn draw_cdmw_shader_controls(&self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let Some(state) = self.cdmw_state.get("shader_controls") else { return; };
        crate::localization::collapsing("Shader experiments").id_salt("shader_controls").show(ui, |ui| {
            let selected = self.selected_part_indices();
            let rows = state["parts"].as_array().into_iter().flatten()
                .filter(|row| row["index"].as_u64().is_some_and(|i| selected.contains(&(i as u32))))
                .collect::<Vec<_>>();
            let ids = rows.iter().map(|row| row["id"].clone()).collect::<Vec<_>>();
            let saved = rows.first().map(|row| row["shader_controls"].clone()).unwrap_or(Value::Null);
            let any_saved = rows.iter().any(|row| !row["shader_controls"].is_null());
            let key = egui::Id::new(("shader_control_values", ids.iter().map(Value::to_string).collect::<Vec<_>>(),
                rows.iter().map(|row| row["shader_controls"].to_string()).collect::<Vec<_>>()));
            let is_static = state["static"].as_bool().unwrap_or(false);
            let families = state["catalogue"].as_array().into_iter().flatten()
                .filter(|family| (family["shader"] == "Dissolve") == is_static).collect::<Vec<_>>();
            let mut value = ui.ctx().data_mut(|data| data.get_temp::<Value>(key)).unwrap_or_else(|| {
                if saved.is_null() {
                    json!({"shader": families.first().map(|f| &f["shader"]), "values": {}})
                } else { saved.clone() }
            });
            let available = state["available"].as_bool().unwrap_or(false);
            if !available { ui.small(crate::localization::tr(state["reason"].as_str().unwrap_or("Shader controls are unavailable."))); }
            if ids.is_empty() { ui.small(crate::localization::tr("Select one or more Parts above.")); }
            if rows.iter().any(|row| row["shader_controls"] != saved) {
                ui.small(crate::localization::tr("Selected parts have different shader settings. Applying replaces their explicit overrides."));
            }
            for row in &rows {
                if let Some(note) = row["diagnostic"].as_str().filter(|text| !text.is_empty()) {
                    ui.small(crate::localization::tr(format!("{}: {note}", row["name"].as_str().unwrap_or("Part"))));
                }
            }
            let editing = self.cdmw_state["authoring_enabled"].as_bool().unwrap_or(false)
                && self.cdmw_state["replacement"]["comparison"].as_str().unwrap_or("edit") == "edit";
            ui.add_enabled_ui(available && editing && !self.cdmw_busy() && !ids.is_empty(), |ui| {
                let mut shader = value["shader"].as_str().unwrap_or("").to_owned();
                let before = shader.clone();
                let label = families.iter().find(|f| f["shader"] == shader)
                    .and_then(|f| f["label"].as_str()).unwrap_or("Choose experiment");
                egui::ComboBox::from_id_salt("shader_experiment_family").selected_text(crate::localization::tr(label)).show_ui(ui, |ui| {
                    for family in &families {
                        ui.selectable_value(&mut shader, family["shader"].as_str().unwrap_or("").to_owned(),
                                            crate::localization::tr(family["label"].as_str().unwrap_or("")))
                            .on_hover_text(crate::localization::tr(family["note"].as_str().unwrap_or("")));
                    }
                }).response.on_hover_text(crate::localization::tr(families.iter().find(|f| f["shader"] == shader)
                    .and_then(|f| f["note"].as_str()).unwrap_or("")));
                if shader != before { value = json!({"shader": shader, "values": {}}); }
                if let Some(family) = families.iter().find(|f| f["shader"] == shader) {
                    for field in family["fields"].as_array().into_iter().flatten() {
                        let Some(name) = field["name"].as_str() else { continue; };
                        let mut enabled = !value["values"][name].is_null();
                        ui.vertical(|ui| {
                            ui.checkbox(&mut enabled, crate::localization::tr(field["label"].as_str().unwrap_or(name)))
                                .on_hover_text(crate::localization::tr("Unchecked fields retain authored values. Compatibility is checked when applying."));
                            let mut numbers = if value["values"][name].is_array() { value["values"][name].clone() } else { field["default"].clone() };
                            ui.add_enabled_ui(enabled, |ui| {
                                if let Some(values) = numbers.as_array_mut() {
                                    for number in values {
                                        let mut n = number.as_f64().unwrap_or(0.0);
                                        let integer = field["integer"].as_bool().unwrap_or(false);
                                        let mut slider = crate::cdmw_ui::numeric::slider(&mut n,
                                            field["minimum"].as_f64().unwrap_or(0.0)..=field["maximum"].as_f64().unwrap_or(1.0))
                                            .fixed_decimals(if integer { 0 } else { 4 });
                                        if integer { slider = slider.step_by(1.0); }
                                        ui.add(slider);
                                        *number = json!(if integer { n.round() } else { n });
                                    }
                                }
                            });
                            if enabled { value["values"][name] = numbers; }
                            else if let Some(values) = value["values"].as_object_mut() { values.remove(name); }
                        });
                    }
                }
                ui.horizontal_wrapped(|ui| {
                    if ui.button(crate::localization::tr("Apply shader controls"))
                        .on_hover_text(crate::localization::tr("These controls preserve the source maps. Game shader activation, shadows and timing still require an in-game test.")).clicked() {
                        actions.push(UiAction::CdmwCommand { command: "replacement_shader_controls",
                            arguments: json!({"part_ids": ids, "shader_controls": value}), label: "Edit shader controls" });
                    }
                    if ui.add_enabled(any_saved, egui::Button::new(crate::localization::tr("Restore shader controls"))).clicked() {
                        actions.push(UiAction::CdmwCommand { command: "replacement_shader_controls",
                            arguments: json!({"part_ids": ids, "reset": true}), label: "Restore shader controls" });
                    }
                });
            });
            ui.ctx().data_mut(|data| data.insert_temp(key, value));
        });
    }
}
