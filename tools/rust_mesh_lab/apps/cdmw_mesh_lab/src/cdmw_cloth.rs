//! Edit existing cloth influence through the host's reversible PAC output path.

use super::*;
use crate::cdmw_ui::{state_bool, state_str, state_u64};

pub(super) struct ClothView {
    pub selected_only: bool,
    pub amount_percent: f64,
    pub use_height: bool,
    pub height: f64,
    pub fade: f64,
    key: Value,
}

impl Default for ClothView {
    fn default() -> Self {
        Self {
            selected_only: false,
            amount_percent: 100.0,
            use_height: false,
            height: 0.0,
            fade: 0.0,
            key: Value::Null,
        }
    }
}

pub(super) struct JiggleView {
    pub selected_only: bool,
    pub use_height: bool,
    pub height: f64,
    key: Value,
}

impl Default for JiggleView {
    fn default() -> Self {
        Self {
            selected_only: true,
            use_height: true,
            height: 0.0,
            key: Value::Null,
        }
    }
}

impl LabApplication {
    pub(super) fn draw_cdmw_cloth_page(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        self.draw_cdmw_cloth_controls(ui, actions);
        ui.separator();
        egui::CollapsingHeader::new("Jiggle (experimental)")
            .default_open(false)
            .show(ui, |ui| self.draw_cdmw_jiggle_controls(ui, actions));
    }

    fn draw_cdmw_cloth_controls(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let cloth = self.cdmw_state["cloth"].clone();
        ui.small("Fixed vertices follow the skeleton. Existing cloth bindings only.");
        if !state_bool(&cloth, "available") {
            ui.label(state_str(&cloth, "reason").unwrap_or("Cloth influence is unavailable."));
            return;
        }
        ui.checkbox(&mut self.cdmw_cloth.selected_only, "Selected parts only");
        let selected = self.selected_part_indices();
        let parts: Vec<Value> = cloth["parts"]
            .as_array()
            .into_iter()
            .flatten()
            .filter(|part| {
                state_bool(part, "included")
                    && (!self.cdmw_cloth.selected_only
                        || selected.contains(&(state_u64(part, "index") as u32)))
            })
            .cloned()
            .collect();
        if parts.is_empty() {
            ui.label("Select an included part with cloth bindings.");
            return;
        }
        let ids: Vec<&str> = parts
            .iter()
            .filter_map(|part| part["id"].as_str())
            .collect();
        let key = json!([
            ids,
            parts.iter().map(|part| &part["rule"]).collect::<Vec<_>>()
        ]);
        let mixed = parts.iter().any(|part| part["rule"] != parts[0]["rule"]);
        if key != self.cdmw_cloth.key {
            self.cdmw_cloth.key = key;
            let rule = if mixed {
                &Value::Null
            } else {
                &parts[0]["rule"]
            };
            self.cdmw_cloth.amount_percent = rule["amount"].as_f64().unwrap_or(1.0) * 100.0;
            self.cdmw_cloth.use_height = rule["fixed_above"].as_f64().is_some();
            let min_y = parts
                .iter()
                .filter_map(|part| part["min_y"].as_f64())
                .fold(f64::INFINITY, f64::min);
            let max_y = parts
                .iter()
                .filter_map(|part| part["max_y"].as_f64())
                .fold(f64::NEG_INFINITY, f64::max);
            self.cdmw_cloth.height = rule["fixed_above"]
                .as_f64()
                .unwrap_or((min_y + max_y) * 0.5);
            self.cdmw_cloth.fade = rule["fade"].as_f64().unwrap_or(0.0);
        }
        ui.small(format!(
            "{} parts · applies to all {} LODs",
            parts.len(),
            state_u64(&cloth, "lod_count")
        ));
        if mixed {
            ui.small("Mixed saved settings. Apply replaces them for these parts.");
        }
        ui.add(
            egui::Slider::new(&mut self.cdmw_cloth.amount_percent, 0.0..=100.0)
                .text("Cloth amount"),
        );
        ui.checkbox(&mut self.cdmw_cloth.use_height, "Fix vertices above height");
        if self.cdmw_cloth.use_height {
            ui.horizontal(|ui| {
                ui.label("Height (Y)");
                ui.add(egui::DragValue::new(&mut self.cdmw_cloth.height).speed(0.01));
            });
            ui.horizontal(|ui| {
                ui.label("Fade below height");
                ui.add(
                    egui::DragValue::new(&mut self.cdmw_cloth.fade)
                        .range(0.0..=f64::MAX)
                        .speed(0.01),
                );
            });
            ui.small("Uses displayed model coordinates. Higher vertices stay fixed; lower vertices move.");
        }
        if ui.button("Apply cloth settings").clicked() {
            actions.push(UiAction::CdmwCommand {
                command: "replacement_cloth",
                arguments: json!({"part_ids": ids, "rule": {
                    "amount": self.cdmw_cloth.amount_percent / 100.0,
                    "fixed_above": self.cdmw_cloth.use_height.then_some(self.cdmw_cloth.height),
                    "fade": if self.cdmw_cloth.use_height { self.cdmw_cloth.fade } else { 0.0 }
                }}),
                label: "Edit cloth influence",
            });
        }
        ui.horizontal_wrapped(|ui| {
            if ui.button("Disable cloth").clicked() {
                actions.push(UiAction::CdmwCommand {
                    command: "replacement_cloth",
                    arguments: json!({"part_ids": ids, "rule": {"amount": 0.0, "fixed_above": null, "fade": 0.0}}),
                    label: "Disable cloth influence",
                });
            }
            if ui.add_enabled(parts.iter().any(|part| !part["rule"].is_null()), egui::Button::new("Restore cloth")).clicked() {
                actions.push(UiAction::CdmwCommand {
                    command: "replacement_cloth",
                    arguments: json!({"part_ids": ids, "reset": true}),
                    label: "Restore cloth influence",
                });
            }
        });
        ui.small("Saved with Build PAC and drafts. Preview simulation remains approximate.");
    }

    fn draw_cdmw_jiggle_controls(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let jiggle = self.cdmw_state["jiggle"].clone();
        ui.small("Reported on Damiane. Verify other models in-game. Strength is not decoded.");
        if !state_bool(&jiggle, "available") {
            ui.label(state_str(&jiggle, "reason").unwrap_or("Jiggle editing is unavailable."));
            return;
        }
        ui.checkbox(&mut self.cdmw_jiggle.selected_only, "Selected parts");
        let selected = self.selected_part_indices();
        let parts: Vec<Value> = jiggle["parts"]
            .as_array()
            .into_iter()
            .flatten()
            .filter(|part| {
                state_bool(part, "included")
                    && (!self.cdmw_jiggle.selected_only
                        || selected.contains(&(state_u64(part, "index") as u32)))
            })
            .cloned()
            .collect();
        if parts.is_empty() {
            ui.label("Select an included part with editable jiggle data.");
            return;
        }
        let ids: Vec<&str> = parts.iter().filter_map(|part| part["id"].as_str()).collect();
        let key = json!([ids, parts.iter().map(|part| &part["rule"]).collect::<Vec<_>>()]);
        let mixed = parts.iter().any(|part| part["rule"] != parts[0]["rule"]);
        let min_y = parts.iter().filter_map(|part| part["min_y"].as_f64()).fold(f64::INFINITY, f64::min);
        let max_y = parts.iter().filter_map(|part| part["max_y"].as_f64()).fold(f64::NEG_INFINITY, f64::max);
        if key != self.cdmw_jiggle.key {
            self.cdmw_jiggle.key = key;
            let rule = if mixed { &Value::Null } else { &parts[0]["rule"] };
            self.cdmw_jiggle.use_height = rule.is_null() || rule["below_y"].as_f64().is_some();
            self.cdmw_jiggle.height = rule["below_y"].as_f64().unwrap_or((min_y + max_y) * 0.5);
        }
        ui.small(format!("{} parts · applies to all {} LODs", parts.len(), state_u64(&jiggle, "lod_count")));
        if mixed {
            ui.small("Mixed saved settings. Disable replaces them for these parts.");
        }
        ui.checkbox(&mut self.cdmw_jiggle.use_height, "Only below height");
        if self.cdmw_jiggle.use_height {
            ui.horizontal(|ui| {
                ui.label("Below Y");
                ui.add(egui::DragValue::new(&mut self.cdmw_jiggle.height).speed(0.01));
            });
            ui.small(format!("Source height range: {min_y:.3} to {max_y:.3}"));
            ui.small("Uses displayed model coordinates. Choose the waist height for this model.");
        }
        ui.horizontal_wrapped(|ui| {
            if ui.button("Disable jiggle").clicked() {
                actions.push(UiAction::CdmwCommand {
                    command: "replacement_jiggle",
                    arguments: json!({"part_ids": ids, "rule": {
                        "below_y": self.cdmw_jiggle.use_height.then_some(self.cdmw_jiggle.height)
                    }}),
                    label: "Disable jiggle",
                });
            }
            if ui.add_enabled(parts.iter().any(|part| !part["rule"].is_null()), egui::Button::new("Restore original jiggle")).clicked() {
                actions.push(UiAction::CdmwCommand {
                    command: "replacement_jiggle",
                    arguments: json!({"part_ids": ids, "reset": true}),
                    label: "Restore original jiggle",
                });
            }
        });
        ui.small("Saved with Build PAC and drafts. Jiggle is not simulated in this preview.");
    }
}
