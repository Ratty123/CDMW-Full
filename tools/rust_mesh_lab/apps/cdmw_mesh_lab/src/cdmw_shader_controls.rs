#![forbid(unsafe_code)]
//! Shader experiments inspector.
//!
//! Every field starts at the number the source material declares, a changed
//! field is an override, and the viewport follows the sliders at once. The
//! host commits the edit shortly after the control is released, so there is
//! no separate Apply step and undo history stays in the host.
use super::*;

/// Quiet time after the last change before the edit is sent to the host.
const COMMIT_DELAY_SECONDS: f64 = 0.12;
/// Quick viewport backdrops for judging translucency; the first is the default.
const VIEWPORT_BACKDROPS: [(&str, Color32); 5] = [
    ("Default", Color32::from_rgb(6, 8, 10)),
    ("Black", Color32::BLACK),
    ("Gray", Color32::from_gray(128)),
    ("White", Color32::WHITE),
    ("Skin tone", Color32::from_rgb(224, 172, 150)),
];
const MASK_KEYS: [&str; 5] = ["transparency_mask", "surface_response_mask", "cutout_mask", "coverage_mapping", "colour_coverage"];

fn numbers_text(numbers: &Value) -> String {
    numbers.as_array().into_iter().flatten().filter_map(Value::as_f64)
        .map(|n| format!("{n:.3}")).collect::<Vec<_>>().join(", ")
}

/// The factor vector the viewport draws for `value` on one part: the host's
/// base vector for that family with the overridden fields' lanes replaced.
/// Lanes follow the catalogue: four header lanes, then each field in order.
pub(crate) fn shader_live_factors(row: &Value, family: &Value, value: &Value) -> Option<[f32; 32]> {
    if MASK_KEYS.iter().any(|key| !value[*key].is_null()) {
        return None; // Painted masks need the host's textures.
    }
    let base = row["preview_base"][family["shader"].as_str()?].as_array()?;
    if base.len() != 32 {
        return None;
    }
    let mut factors = [0.0_f32; 32];
    for (lane, number) in factors.iter_mut().zip(base) {
        *lane = number.as_f64()? as f32;
    }
    let mut lane = 4_usize;
    for field in family["fields"].as_array()? {
        let width = field["default"].as_array()?.len();
        if let Some(numbers) = value["values"][field["name"].as_str()?].as_array()
            && numbers.len() == width
        {
            let (minimum, maximum) = (field["minimum"].as_f64().unwrap_or(0.0), field["maximum"].as_f64().unwrap_or(1.0));
            for (offset, number) in numbers.iter().enumerate() {
                *factors.get_mut(lane + offset)? = number.as_f64()?.clamp(minimum, maximum) as f32;
            }
        }
        lane += width;
    }
    Some(factors)
}

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
            let key = egui::Id::new(("shader_control_values", self.cdmw_shader_panel_epoch,
                ids.iter().map(Value::to_string).collect::<Vec<_>>(),
                rows.iter().map(|row| row["shader_controls"].to_string()).collect::<Vec<_>>()));
            let is_static = state["static"].as_bool().unwrap_or(false);
            let families = state["catalogue"].as_array().into_iter().flatten()
                .filter(|family| (family["shader"] == "Dissolve" || family["shader"] == "Translucent") == is_static).collect::<Vec<_>>();
            let unavailable_reason = |shader: &str| -> Option<String> {
                rows.iter().find_map(|row| {
                    let reason = row["shader_options"][shader].as_str()
                        .unwrap_or("Source material information is unavailable; shader experiments are disabled.");
                    (!reason.is_empty()).then(|| format!("{}: {reason}", row["name"].as_str().unwrap_or("Part")))
                })
            };
            // A material that already uses one of these shaders opens on its own numbers.
            let source_shader = rows.first().and_then(|row| row["source_shader"].as_str()).unwrap_or("");
            let source_family = families.iter()
                .find(|family| family["shader"] == source_shader && unavailable_reason(source_shader).is_none())
                .and_then(|family| family["shader"].as_str()).unwrap_or("");
            let baseline = if saved.is_null() { json!({"shader": source_family, "values": {}}) } else { saved.clone() };
            let mut value = ui.ctx().data_mut(|data| data.get_temp::<Value>(key)).unwrap_or_else(|| baseline.clone());
            let before = value.clone();
            let available = state["available"].as_bool().unwrap_or(false);
            if !available { ui.small(crate::localization::tr(state["reason"].as_str().unwrap_or("Shader controls are unavailable."))); }
            if ids.is_empty() { ui.small(crate::localization::tr("Open Parts above, select one or more, then choose Back to Inspector.")); }
            if rows.iter().any(|row| row["shader_controls"] != saved) {
                ui.small(crate::localization::tr("Selected parts have different shader settings. Applying replaces their explicit overrides."));
            }
            for row in &rows {
                if let Some(shader) = row["source_shader"].as_str().filter(|text| !text.is_empty()) {
                    ui.small(crate::localization::tr(format!("Source shader: {shader}.")));
                }
                if let Some(note) = row["diagnostic"].as_str().filter(|text| !text.is_empty()) {
                    ui.small(crate::localization::tr(format!("{}: {note}", row["name"].as_str().unwrap_or("Part"))));
                }
            }
            // Model variants can declare different numbers for the same part.
            let variants = rows.first().and_then(|row| row["authored"].as_array()).cloned().unwrap_or_default();
            let variant_key = key.with("variant");
            let mut variant = ui.ctx().data_mut(|data| data.get_temp::<usize>(variant_key)).unwrap_or(0).min(variants.len().saturating_sub(1));
            let editing = self.cdmw_state["authoring_enabled"].as_bool().unwrap_or(false)
                && self.cdmw_state["replacement"]["comparison"].as_str().unwrap_or("edit") == "edit";
            let enabled = available && editing && !self.cdmw_busy() && !ids.is_empty();
            let mut reason = None;
            ui.add_enabled_ui(enabled, |ui| {
                let mut shader = value["shader"].as_str().unwrap_or("").to_owned();
                let chosen = shader.clone();
                let label = families.iter().find(|f| f["shader"] == shader)
                    .and_then(|f| f["label"].as_str()).unwrap_or("Keep source shader");
                egui::ComboBox::from_id_salt("shader_experiment_family").selected_text(crate::localization::tr(label)).show_ui(ui, |ui| {
                    if ui.add(egui::Button::selectable(shader.is_empty(), crate::localization::tr("Keep source shader")))
                        .on_hover_text(crate::localization::tr("Use the material exactly as the source declares it.")).clicked() {
                        shader.clear();
                    }
                    for family in &families {
                        let name = family["shader"].as_str().unwrap_or("");
                        let reason = unavailable_reason(name);
                        let label = crate::localization::tr(family["label"].as_str().unwrap_or(""));
                        let response = ui.add_enabled(reason.is_none(), egui::Button::selectable(shader == name, label));
                        if response.clicked() { shader = name.to_owned(); }
                        response.on_hover_text(crate::localization::tr(family["note"].as_str().unwrap_or("")))
                            .on_disabled_hover_text(crate::localization::tr(reason.as_deref().unwrap_or("")));
                    }
                }).response.on_hover_text(crate::localization::tr(families.iter().find(|f| f["shader"] == shader)
                    .and_then(|f| f["note"].as_str()).unwrap_or("")));
                if shader != chosen { value = json!({"shader": shader, "values": {}}); }
                reason = if shader.is_empty() { None } else { unavailable_reason(&shader) };
                if let Some(note) = &reason { ui.small(crate::localization::tr(note)); }
                ui.add_enabled_ui(reason.is_none(), |ui| {
                if let Some(family) = families.iter().find(|f| f["shader"] == shader) {
                    let presets = family["presets"].as_array().cloned().unwrap_or_default();
                    if !presets.is_empty() {
                        egui::ComboBox::from_id_salt("shader_experiment_preset")
                            .selected_text(crate::localization::tr("Choose a preset")).show_ui(ui, |ui| {
                            for preset in &presets {
                                let label = crate::localization::tr(preset["label"].as_str().unwrap_or(""));
                                if ui.add(egui::Button::selectable(false, label)).clicked() {
                                    value["values"] = preset["values"].clone();
                                }
                            }
                        }).response.on_hover_text(crate::localization::tr(
                            "Numbers taken from shipped materials and released mods. Choosing one replaces this part's changed values."));
                    }
                    if variants.len() > 1 {
                        egui::ComboBox::from_id_salt("shader_experiment_variant")
                            .selected_text(crate::localization::tr(format!("Model variant {}", variant + 1))).show_ui(ui, |ui| {
                            for index in 0..variants.len() {
                                if ui.add(egui::Button::selectable(variant == index,
                                    crate::localization::tr(format!("Model variant {}", index + 1)))).clicked() {
                                    variant = index;
                                }
                            }
                        }).response.on_hover_text(crate::localization::tr(
                            "This part's source material differs between model variants. Original values are shown for the chosen variant; an edit applies to all of them."));
                    }
                    let authored = variants.get(variant).map(|row| &row["fields"][shader.as_str()]);
                    for field in family["fields"].as_array().into_iter().flatten() {
                        let Some(name) = field["name"].as_str() else { continue; };
                        let declared = authored.map(|fields| &fields[name]).filter(|numbers| numbers.is_array());
                        let original = declared.unwrap_or(&field["default"]).clone();
                        let overridden = value["values"][name].is_array();
                        let mut numbers = if overridden { value["values"][name].clone() } else { original.clone() };
                        let mut edited = false;
                        let mut restore = false;
                        ui.vertical(|ui| {
                            ui.horizontal(|ui| {
                                let caption = crate::localization::tr(field["label"].as_str().unwrap_or(name));
                                let caption = if overridden {
                                    // A plain ASCII marker: it must survive every interface font.
                                    egui::RichText::new(format!("{caption} *")).strong().color(ui.visuals().warn_fg_color)
                                } else { egui::RichText::new(caption) };
                                ui.label(caption).on_hover_text(format!("{}\n{name} · {}–{}",
                                    crate::localization::tr(field["note"].as_str().unwrap_or("Changed values are previewed at once and saved when you release the control.")),
                                    field["minimum"].as_f64().unwrap_or(0.0), field["maximum"].as_f64().unwrap_or(1.0)));
                                if overridden && ui.small_button(crate::localization::tr("Original"))
                                    .on_hover_text(crate::localization::tr("Return this value to the source material's.")).clicked() {
                                    restore = true;
                                }
                            });
                            if let Some(values) = numbers.as_array_mut() {
                                for number in values {
                                    let old = number.as_f64().unwrap_or(0.0);
                                    let mut n = old;
                                    let integer = field["integer"].as_bool().unwrap_or(false);
                                    let mut slider = crate::cdmw_ui::numeric::slider(&mut n,
                                        field["minimum"].as_f64().unwrap_or(0.0)..=field["maximum"].as_f64().unwrap_or(1.0))
                                        .fixed_decimals(if integer { 0 } else { 4 });
                                    if integer { slider = slider.step_by(1.0); }
                                    ui.add(slider);
                                    let n = if integer { n.round() } else { n };
                                    if (n - old).abs() > 1e-9 {
                                        edited = true;
                                        *number = json!(n);
                                    }
                                }
                            }
                            ui.small(crate::localization::tr(if declared.is_some() {
                                format!("Original: {}", numbers_text(&original))
                            } else {
                                format!("Not set by this material. Default: {}", numbers_text(&original))
                            }));
                        });
                        if restore {
                            if let Some(values) = value["values"].as_object_mut() { values.remove(name); }
                        } else if edited {
                            value["values"][name] = numbers;
                        }
                    }
                    let textures = variants.get(variant).and_then(|row| row["textures"].as_object()).cloned().unwrap_or_default();
                    if !textures.is_empty() {
                        crate::localization::collapsing("Source textures").id_salt("shader_source_textures").show(ui, |ui| {
                            for (parameter, path) in &textures {
                                let path = path.as_str().unwrap_or("");
                                ui.small(format!("{parameter}: {}", path.rsplit('/').next().unwrap_or(path))).on_hover_text(path);
                            }
                        });
                    }
                }
                });
                if ui.add_enabled(any_saved, egui::Button::new(crate::localization::tr("Restore shader controls")))
                    .on_hover_text(crate::localization::tr("Remove every shader change from the selected parts.")).clicked() {
                    actions.push(UiAction::CdmwCommand { command: "replacement_shader_controls",
                        arguments: json!({"part_ids": ids, "reset": true}), label: "Restore shader controls" });
                }
            });
            // See-through cloth is judged against what is behind it.
            ui.horizontal_wrapped(|ui| {
                ui.small(crate::localization::tr("Background"));
                for (label, colour) in VIEWPORT_BACKDROPS {
                    let chosen = self.viewport_background_colour == colour;
                    if ui.add(egui::Button::selectable(chosen, crate::localization::tr(label)).small()).clicked() {
                        actions.push(UiAction::SetViewportBackground(colour));
                    }
                }
            });
            // Live preview: the renderer takes the new numbers without the host.
            let now = ui.input(|input| input.time);
            let changed_key = key.with("changed-at");
            if value != before {
                ui.ctx().data_mut(|data| data.insert_temp(changed_key, now));
                let family = families.iter().find(|family| family["shader"] == value["shader"]);
                let preview = rows.iter().filter_map(|row| {
                    let part = u32::try_from(row["index"].as_u64()?).ok()?;
                    Some((part, family.and_then(|family| shader_live_factors(row, family, &value))))
                }).collect::<Vec<_>>();
                if !preview.is_empty() { actions.push(UiAction::CdmwShaderPreview(preview)); }
            }
            // Commit once the control has rested, so one drag is one undo step.
            let sent_key = key.with("sent");
            let sent = ui.ctx().data_mut(|data| data.get_temp::<Value>(sent_key));
            if value != baseline && sent.as_ref() != Some(&value) && enabled && reason.is_none() {
                let changed_at = ui.ctx().data_mut(|data| data.get_temp::<f64>(changed_key)).unwrap_or(now);
                if now - changed_at >= COMMIT_DELAY_SECONDS && !ui.input(|input| input.pointer.any_down()) {
                    let unchanged_source = value["shader"].as_str().unwrap_or("").is_empty()
                        || (value["shader"] == source_family && value["values"].as_object().is_some_and(|values| values.is_empty())
                            && MASK_KEYS.iter().all(|mask| value[*mask].is_null()));
                    if !unchanged_source {
                        actions.push(UiAction::CdmwCommand { command: "replacement_shader_controls",
                            arguments: json!({"part_ids": ids, "shader_controls": value}), label: "Edit shader controls" });
                    } else if any_saved {
                        actions.push(UiAction::CdmwCommand { command: "replacement_shader_controls",
                            arguments: json!({"part_ids": ids, "reset": true}), label: "Restore shader controls" });
                    }
                    ui.ctx().data_mut(|data| data.insert_temp(sent_key, value.clone()));
                } else {
                    ui.ctx().request_repaint_after(std::time::Duration::from_secs_f64(COMMIT_DELAY_SECONDS));
                }
            }
            ui.ctx().data_mut(|data| {
                data.insert_temp(key, value);
                data.insert_temp(variant_key, variant);
            });
        });
    }
}
