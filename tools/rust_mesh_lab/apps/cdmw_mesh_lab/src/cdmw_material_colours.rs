#![forbid(unsafe_code)]
use super::*;

/// `#RRGGBB` to bytes; anything else is None.
pub(crate) fn parse_hex_rgb(text: &str) -> Option<[u8; 3]> {
    let digits = text.strip_prefix('#')?;
    if digits.len() != 6 || !digits.is_ascii() {
        return None;
    }
    let byte = |at: usize| u8::from_str_radix(&digits[at..at + 2], 16).ok();
    Some([byte(0)?, byte(2)?, byte(4)?])
}

pub(crate) fn hex_rgb(colour: [u8; 3]) -> String {
    format!("#{:02X}{:02X}{:02X}", colour[0], colour[1], colour[2])
}

impl LabApplication {
    /// The colour rows a part's PAC material already declares (tints, wear tints,
    /// dyes), edited in place. Draws the section and says whether it is open.
    pub(super) fn draw_cdmw_material_colours(&self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) -> bool {
        let Some(state) = self.cdmw_state.get("material_colours") else {
            return false;
        };
        crate::localization::collapsing("Material colours").id_salt("part_material_colours").show(ui, |ui| {
            let selected = self.selected_part_indices();
            let rows = state["parts"].as_array().into_iter().flatten()
                .filter(|row| row["index"].as_u64().is_some_and(|index| selected.contains(&(index as u32))))
                .collect::<Vec<_>>();
            let ids = rows.iter().map(|row| row["id"].clone()).collect::<Vec<_>>();
            let available = state["available"].as_bool().unwrap_or(false);
            if !available {
                ui.small(crate::localization::tr(state["reason"].as_str().unwrap_or("Material colours are unavailable.")));
            }
            if ids.is_empty() {
                ui.small(crate::localization::tr("Open Parts above, select one or more, then choose Back to Inspector."));
                return;
            }
            let material = rows[0]["material"].as_str().unwrap_or("");
            if rows.iter().any(|row| row["material"].as_str().unwrap_or("") != material) {
                ui.small(crate::localization::tr(
                    "The selected parts use different materials. Select parts that share one material to change its colours."));
                return;
            }
            let colour_rows = rows[0]["rows"].as_array().cloned().unwrap_or_default();
            if colour_rows.is_empty() {
                ui.small(crate::localization::tr("This material declares no colours to change."));
                return;
            }
            let blocked = rows.iter().find_map(|row| row["blocked"].as_str().filter(|text| !text.is_empty()));
            if let Some(reason) = blocked {
                ui.small(crate::localization::tr(reason));
            }
            let shared = rows[0]["shared"].as_array().map_or(1, Vec::len);
            ui.small(crate::localization::tr(
                "Changes the colours this material already declares, such as the tints its colour mask applies. \
                 Each colour keeps its strength (alpha). Build Mod writes them into the mod's material file."));
            if shared > ids.len() {
                ui.small(crate::localization::tr(format!(
                    "{shared} parts use this material; all of them change together.")));
            }
            let saved = rows[0]["material_colours"].clone();
            let key = egui::Id::new(("material_colour_values", ids.iter().map(Value::to_string).collect::<Vec<_>>(),
                saved.to_string()));
            let original = |row: &Value| parse_hex_rgb(row["original"].as_str().unwrap_or("")).unwrap_or([255, 255, 255]);
            let mut pending: Value = ui.ctx().data_mut(|data| data.get_temp::<Value>(key)).unwrap_or_else(|| {
                let mut values = serde_json::Map::new();
                for row in &colour_rows {
                    let name = row["name"].as_str().unwrap_or("");
                    let shown = saved[name].as_str().and_then(parse_hex_rgb).unwrap_or_else(|| original(row));
                    values.insert(name.to_owned(), json!(hex_rgb(shown)));
                }
                Value::Object(values)
            });
            let editing = self.cdmw_state["authoring_enabled"].as_bool().unwrap_or(false)
                && self.cdmw_state["replacement"]["comparison"].as_str().unwrap_or("edit") == "edit";
            ui.add_enabled_ui(available && blocked.is_none() && !self.cdmw_busy() && editing, |ui| {
                egui::Grid::new("material_colour_rows").num_columns(3).show(ui, |ui| {
                    for row in &colour_rows {
                        let name = row["name"].as_str().unwrap_or("");
                        let source = original(row);
                        let mut colour = pending[name].as_str().and_then(parse_hex_rgb).unwrap_or(source);
                        let changed = colour != source;
                        let caption = crate::localization::tr(row["label"].as_str().unwrap_or(name));
                        let caption = if changed {
                            // A plain ASCII marker: it must survive every interface font.
                            egui::RichText::new(format!("{caption} *")).strong().color(ui.visuals().warn_fg_color)
                        } else {
                            egui::RichText::new(caption)
                        };
                        let hex = hex_rgb(source);
                        let alpha = row["alpha"].as_u64().unwrap_or(255);
                        ui.label(caption).on_hover_text(format!("{name}\n{}", crate::localization::tr(format!(
                            "Original: {hex}. Strength (alpha): {alpha} of 255."))));
                        if ui.color_edit_button_srgb(&mut colour).changed() {
                            pending[name] = json!(hex_rgb(colour));
                        }
                        ui.horizontal(|ui| {
                            ui.small(hex_rgb(colour));
                            if changed && ui.small_button(crate::localization::tr("Original"))
                                .on_hover_text(crate::localization::tr("Return this colour to the source material's.")).clicked() {
                                pending[name] = json!(hex_rgb(source));
                            }
                        });
                        ui.end_row();
                    }
                });
                let edits = colour_rows.iter().filter_map(|row| {
                    let name = row["name"].as_str()?;
                    let colour = pending[name].as_str().and_then(parse_hex_rgb)?;
                    (colour != original(row)).then(|| (name.to_owned(), json!(hex_rgb(colour))))
                }).collect::<serde_json::Map<String, Value>>();
                let unchanged = Value::Object(edits.clone()) == if saved.is_null() { json!({}) } else { saved.clone() };
                ui.horizontal_wrapped(|ui| {
                    if ui.add_enabled(!unchanged, egui::Button::new(crate::localization::tr("Apply colours")))
                        .on_hover_text(crate::localization::tr("Shows the new colours in the preview and records one Undo step.")).clicked() {
                        actions.push(if edits.is_empty() {
                            UiAction::CdmwCommand { command: "replacement_material_colours",
                                arguments: json!({"part_ids": ids, "reset": true}), label: "Restore material colours" }
                        } else {
                            UiAction::CdmwCommand { command: "replacement_material_colours",
                                arguments: json!({"part_ids": ids, "colours": edits}), label: "Edit material colours" }
                        });
                    }
                    if ui.add_enabled(rows.iter().any(|row| !row["material_colours"].is_null()),
                            egui::Button::new(crate::localization::tr("Restore original colours"))).clicked() {
                        actions.push(UiAction::CdmwCommand { command: "replacement_material_colours",
                            arguments: json!({"part_ids": ids, "reset": true}), label: "Restore material colours" });
                    }
                });
            });
            ui.ctx().data_mut(|data| data.insert_temp(key, pending));
        })
        .openness
            > 0.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hex_colours_round_trip_and_refuse_other_text() {
        assert_eq!(parse_hex_rgb("#F7c6AC"), Some([0xF7, 0xC6, 0xAC]));
        assert_eq!(hex_rgb([0xF7, 0xC6, 0xAC]), "#F7C6AC");
        for text in ["F7C6AC", "#F7C6ACFF", "#F7C6A", "#G7C6AC", "#ÿÿÿ"] {
            assert_eq!(parse_hex_rgb(text), None, "{text}");
        }
    }
}
