#![forbid(unsafe_code)]
use super::*;

impl LabApplication {
    pub(super) fn draw_cdmw_emission(&self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let Some(state) = self.cdmw_state.get("emission") else {
            return;
        };
        egui::CollapsingHeader::new("Glow (experimental)").id_salt("part_emission").show(ui, |ui| {
            let selected = self.selected_part_indices();
            let rows = state["parts"].as_array().into_iter().flatten()
                .filter(|row| row["index"].as_u64().is_some_and(|index| selected.contains(&(index as u32))))
                .collect::<Vec<_>>();
            let ids = rows.iter().map(|row| row["id"].clone()).collect::<Vec<_>>();
            let saved = rows.first().map(|row| &row["emission"]);
            if rows.iter().any(|row| Some(&row["emission"]) != saved) {
                ui.small("Selected parts have different glow settings.");
            }
            let key = egui::Id::new(("emission_values", ids.iter().map(Value::to_string).collect::<Vec<_>>(),
                rows.iter().map(|row| row["emission"].to_string()).collect::<Vec<_>>()));
            let mut values = ui.ctx().data_mut(|data| data.get_temp::<[f32; 13]>(key)).unwrap_or_else(|| {
                let mut v = [1.0, 1.0, 1.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.1, 0.0];
                if let Some(saved) = saved {
                    for i in 0..3 { v[i] = saved["color"][i].as_f64().unwrap_or(1.0) as f32; }
                    v[3] = saved["intensity"].as_f64().unwrap_or(4.0) as f32;
                    if !saved["rgb"].is_null() {
                        v[8] = 1.0;
                        v[9] = saved["rgb"]["intensity"].as_f64().unwrap_or(1.0) as f32;
                        v[10] = saved["rgb"]["reveal"].as_f64().unwrap_or(1.0) as f32;
                        v[11] = saved["rgb"]["softness"].as_f64().unwrap_or(0.1) as f32;
                        v[12] = if saved["rgb"]["inverse"].as_bool().unwrap_or(false) { 1.0 } else { 0.0 };
                    }
                    for (i, name) in ["flow_u", "flow_v", "pulse_frequency", "pulse_minimum"].into_iter().enumerate() {
                        v[4 + i] = saved["animation"][name].as_f64().unwrap_or(0.0) as f32;
                    }
                }
                v
            });
            let available = state["available"].as_bool().unwrap_or(false);
            if !available { ui.small(state["reason"].as_str().unwrap_or("Glow editing is unavailable.")); }
            if ids.is_empty() { ui.small("Select one or more Parts above."); }
            let editing = self.cdmw_state["authoring_enabled"].as_bool().unwrap_or(false)
                && self.cdmw_state["replacement"]["comparison"].as_str().unwrap_or("edit") == "edit";
            ui.add_enabled_ui(available && !ids.is_empty() && !self.cdmw_busy() && editing, |ui| {
                let mut color = [values[0], values[1], values[2]];
                let changed = ui.horizontal(|ui| { ui.label("Glow colour"); ui.color_edit_button_rgb(&mut color).changed() }).inner;
                if changed { values[..3].copy_from_slice(&color); }
                else { color.copy_from_slice(&values[..3]); }
                for (i, (label, maximum)) in [("Strength", 20.0), ("Scroll U", 10.0), ("Scroll V", 10.0),
                    ("Pulse speed", 10.0), ("Pulse floor", 1.0)].into_iter().enumerate() {
                    ui.horizontal(|ui| { ui.label(label);
                        ui.add(egui::Slider::new(&mut values[3 + i], 0.0..=maximum).fixed_decimals(3));
                    });
                }
                ui.small("Zero speed is static. Scroll moves the glow map only; a solid map cannot show movement. Pulse floor is capped by each pixel's glow. Preview timing is approximate.");
                ui.small("Animated glow cannot share a part with translucency. Unsupported source shaders are reported when applying.");
                let mut rgb = values[8] > 0.5;
                ui.checkbox(&mut rgb, "Use RGB glow map");
                values[8] = if rgb { 1.0 } else { 0.0 };
                if rgb {
                    for (index, label, minimum) in [(9, "RGB strength", 0.0), (10, "Reveal", 0.0), (11, "Reveal softness", 0.001)] {
                        ui.horizontal(|ui| { ui.label(label); ui.add(egui::Slider::new(&mut values[index], minimum..=1.0).fixed_decimals(3)); });
                    }
                    let mut inverse = values[12] > 0.5;
                    ui.checkbox(&mut inverse, "Invert reveal mask");
                    values[12] = if inverse { 1.0 } else { 0.0 };
                    ui.small("Requires the source glow map: RGB colours, alpha intensity, red reveal mask. Uses RGB strength. Reveal 0 is off; 1 shows all. Game brightness may differ.");
                }
                ui.horizontal_wrapped(|ui| {
                    if ui.button("Apply glow").clicked() {
                        actions.push(UiAction::CdmwCommand { command: "replacement_emission",
                            arguments: json!({"part_ids": ids, "emission": {"color": color, "intensity": values[3],
                                "animation": {"flow_u": values[4], "flow_v": values[5],
                                    "pulse_frequency": values[6], "pulse_minimum": values[7]},
                                "rgb": rgb.then(|| json!({"intensity": values[9], "reveal": values[10], "softness": values[11], "inverse": values[12] > 0.5}))}}), label: "Edit material glow" });
                    }
                    if ui.add_enabled(rows.iter().any(|row| !row["emission"].is_null()), egui::Button::new("Restore glow")).clicked() {
                        actions.push(UiAction::CdmwCommand { command: "replacement_emission",
                            arguments: json!({"part_ids": ids, "reset": true}), label: "Restore material glow" });
                    }
                });
            });
            ui.ctx().data_mut(|data| data.insert_temp(key, values));
        });
    }
}
