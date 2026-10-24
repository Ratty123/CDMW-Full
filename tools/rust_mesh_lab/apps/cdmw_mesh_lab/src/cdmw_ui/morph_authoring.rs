//! Authored body shapes and selective garment fitting in the existing host workflow.
use super::*;

impl LabApplication {
    pub(super) fn draw_cdmw_authored_morph(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        state: &Value,
    ) {
        let authoring = state_bool(&self.cdmw_state, "authoring_enabled");
        let unbaked = state_bool(state, "unbaked");
        let baseline_ready = state_bool(state, "authoring_baseline_ready");
        let correction_id = state_str(state, "correction_definition_id").unwrap_or("");
        let correcting = !correction_id.is_empty();
        let body = value_u32_list(state, "driver_submesh_indices");
        ui.push_id("morph-authored", |ui| {
            ui.weak(crate::localization::tr("Capture → sculpt → save"))
                .on_hover_text(crate::localization::tr("Capture the body base, shape the body with the editing tools, then save the result as a slider. Keep the body's topology unchanged."));
            ui.horizontal_wrapped(|ui| {
                if ui.add_enabled(
                    authoring && !unbaked && !correcting && !body.is_empty(),
                    Button::new(crate::localization::tr(if baseline_ready { "Recapture body base" } else { "Capture body base" })),
                ).on_disabled_hover_text(crate::localization::tr(
                    "Assign a body and reset or bake the current preview before capturing its base.",
                )).clicked() {
                    actions.push(UiAction::CdmwCommand {
                        command: "morph_capture_baseline",
                        arguments: json!({"submesh_indices": body}),
                        label: "Capture body base",
                    });
                }
            });
            ui.label(crate::localization::tr("Profile name"));
            ui.add(egui::TextEdit::singleline(&mut self.cdmw_morph_profile_name).desired_width(ui.available_width()));
            ui.label(crate::localization::tr("Sculpted slider name"));
            ui.add(egui::TextEdit::singleline(&mut self.cdmw_morph_definition_label).desired_width(ui.available_width()));
        });
    }

    pub(super) fn draw_cdmw_authored_morph_save(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>, state: &Value) {
        let authoring = state_bool(&self.cdmw_state, "authoring_enabled");
        let baseline_ready = state_bool(state, "authoring_baseline_ready");
        let correcting = state_str(state, "correction_definition_id").is_some_and(|id| !id.is_empty());
        let profile_id = state_str(state, "profile_id").unwrap_or("");
        ui.horizontal_wrapped(|ui| {
            let ready = authoring
                && baseline_ready
                && !correcting
                && !self.cdmw_morph_profile_name.trim().is_empty()
                && !self.cdmw_morph_definition_label.trim().is_empty();
            if ui.add_enabled(ready, Button::new(crate::localization::tr("Save slider"))).clicked() {
                let name = self.cdmw_morph_profile_name.trim().to_owned();
                let label = self.cdmw_morph_definition_label.trim().to_owned();
                actions.push(UiAction::CdmwCommand {
                    command: "morph_capture_authored",
                    arguments: json!({
                        "definition": {
                            "profile_id": if profile_id.is_empty() { stable_ui_id("profile", &name) } else { profile_id.to_owned() },
                            "profile_name": name,
                            "definition_id": stable_ui_id("morph", &label),
                            "label": label,
                            "category": "Authored",
                            "min_percent": 0.0,
                            "max_percent": 100.0,
                            "default_percent": 0.0
                        }
                    }),
                    label: "Save sculpted body slider",
                });
            }
            if baseline_ready && ui.add_enabled(
                authoring && !correcting,
                Button::new(crate::localization::tr("Discard base")),
            ).on_hover_text(crate::localization::tr("Keeps the current geometry and discards the saved slider base.")).clicked() {
                actions.push(UiAction::CdmwCommand {
                    command: "morph_cancel_baseline",
                    arguments: json!({}),
                    label: "Discard captured body base",
                });
            }
        });
    }

    pub(super) fn draw_cdmw_refit_follow_controls(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        state: &Value,
    ) {
        let garments = value_u32_list(state.get("refit").unwrap_or(&Value::Null), "garment_submesh_indices");
        if garments.is_empty() {
            return;
        }
        let authoring = state_bool(&self.cdmw_state, "authoring_enabled");
        let editing_correction = state_str(state, "correction_definition_id").is_some_and(|id| !id.is_empty());
        let selected = self.selected_part_indices();
        let selected_garments: Vec<u32> = selected.into_iter().filter(|part| garments.contains(part)).collect();
        let has_selection = self.selected_counts().total() > 0 || !selected_garments.is_empty();
        let masked = state.get("refit").and_then(|refit| refit.get("garment_settings"))
            .and_then(Value::as_array).into_iter().flatten()
            .filter(|row| state_bool(row, "has_vertex_mask")).count();
        let summary = if masked == 0 { crate::localization::tr("No mask") }
            else { crate::localization::tr(format!("{} masked Parts", masked)) };
        let title = format!("{} · {summary}", crate::localization::tr("Local influence"));
        cdmw_section(ui, "refit-local-influence", &title, None, |ui| {
            if selected_garments.is_empty() {
                let counts = self.selected_counts();
                ui.horizontal_wrapped(|ui| {
                    for (label, count) in [("Vertices", counts.vertices), ("Edges", counts.edges), ("Faces", counts.faces)] {
                        ui.weak(format!("{}: {count}", crate::localization::tr(label)));
                    }
                });
            } else {
                ui.weak(crate::localization::tr(format!("{} garment Parts selected", selected_garments.len())));
            }
            if ui.button(crate::localization::tr("Open Selection tool")).clicked() {
                self.cancel_active_gesture("Open garment influence selection");
                self.open_cdmw_tool_settings(ui.ctx(), CdmwRailPage::Select);
            }
            ui.push_id("refit-follow-controls", |ui| {
                ui.add(numeric::slider(&mut self.cdmw_refit_vertex_weight, 0.0..=100.0).text(crate::localization::tr("Selected influence")))
                    .on_hover_text(crate::localization::tr(
                        "0% protects vertices; 100% follows fully. Rigid components require one influence across each connected piece.",
                    ));
                ui.add_enabled_ui(authoring && !editing_correction && has_selection, |ui| {
                    ui.horizontal_wrapped(|ui| {
                        if ui.button(crate::localization::tr("Set selected influence")).clicked() {
                            actions.push(UiAction::CdmwCommand {
                                command: "morph_set_influence",
                                arguments: json!({"weight": self.cdmw_refit_vertex_weight / 100.0, "garment_submesh_indices": selected_garments}),
                                label: "Set garment vertex influence",
                            });
                        }
                        if ui.button(crate::localization::tr("Protect selection")).clicked() {
                            actions.push(UiAction::CdmwCommand {
                                command: "morph_set_influence",
                                arguments: json!({"weight": 0.0, "garment_submesh_indices": selected_garments}),
                                label: "Protect selected garment vertices",
                            });
                        }
                        if ui.button(crate::localization::tr("Restore selected influence")).clicked() {
                            actions.push(UiAction::CdmwCommand {
                                command: "morph_set_influence",
                                arguments: json!({"weight": 1.0, "garment_submesh_indices": selected_garments}),
                                label: "Restore selected garment vertex influence",
                            });
                        }
                    });
                });
                if ui.add_enabled(
                    authoring && !editing_correction && !selected_garments.is_empty(),
                    Button::new(crate::localization::tr("Clear masks on selected garments")),
                ).clicked() {
                    actions.push(UiAction::CdmwCommand {
                        command: "morph_clear_influence",
                        arguments: json!({"garment_submesh_indices": selected_garments}),
                        label: "Clear garment influence masks",
                    });
                }
            });
        });
    }

    pub(super) fn draw_cdmw_refit_garment_parts(
        &mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>, state: &Value,
    ) {
        let garments = value_u32_list(state.get("refit").unwrap_or(&Value::Null), "garment_submesh_indices");
        let selected = self.selected_part_indices();
        let visible = self.cdmw_visible_submeshes();
        let settings = state.get("refit").and_then(|refit| refit.get("garment_settings"))
            .and_then(Value::as_array);
        ui.horizontal_wrapped(|ui| {
            if ui.button(crate::localization::tr("Select garments")).clicked() {
                actions.push(UiAction::SetPartSelection(garments.clone()));
            }
            if ui.button(crate::localization::tr("Clear selection")).clicked() {
                actions.push(UiAction::SetPartSelection(Vec::new()));
            }
        });
        for part in &garments {
            ui.push_id(part, |ui| {
                ui.horizontal(|ui| {
                    let setting = settings.and_then(|rows| rows.iter().find(|row| {
                        row.get("submesh_index").and_then(Value::as_u64) == Some(u64::from(*part))
                    }));
                    let mode = setting.and_then(|row| state_str(row, "mode")).unwrap_or("surface");
                    let enabled = setting.and_then(|row| row.get("enabled")).and_then(Value::as_bool).unwrap_or(true);
                    let label = if !enabled { "Skip" } else { match mode {
                        "rigid_component" => "Rigid component", "rigid" => "Offset follow", _ => "Flexible",
                    }};
                    // Reserve the summary first so even long names leave it visible.
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.weak(crate::localization::tr(label));
                        let name = self.cdmw_morph_part_names(&[*part]);
                        let active = selected.contains(part);
                        let row = ui.add_enabled(
                            visible.as_ref().is_none_or(|visible| visible.contains(part)),
                            Button::selectable(active, self.cdmw_part_name_atoms(*part, &name)).truncate(),
                        );
                        self.track_cdmw_part_hover(ui, *part, &row);
                        if row
                            .on_hover_text(&name)
                            .on_hover_text(crate::localization::tr("Click to highlight this garment and edit its strength. Ctrl-click to select several."))
                            .on_disabled_hover_text(crate::localization::tr("Show this Part in the Parts inspector before selecting it"))
                            .clicked()
                        {
                            let mut next = if ui.input(|input| input.modifiers.command || input.modifiers.ctrl) {
                                selected.clone()
                            } else {
                                Vec::new()
                            };
                            if next.contains(part) {
                                next.retain(|candidate| candidate != part);
                            } else {
                                next.push(*part);
                            }
                            next.sort_unstable();
                            actions.push(UiAction::SetPartSelection(next));
                        }
                    });
                });
            });
        }
    }

    pub(super) fn draw_cdmw_refit_island_parts(
        &mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>, state: &Value,
    ) {
        let garments = value_u32_list(&state["refit"], "garment_submesh_indices");
        let selected = self.selected_refit_islands(&garments);
        let visible = self.cdmw_visible_submeshes();
        let rows = self.cdmw_state["mesh_islands"]["fit_parts"].as_array().cloned().unwrap_or_default();
        let faces_of = |island: &Value| value_u32_list(island, "faces");
        ui.horizontal_wrapped(|ui| {
            if ui.button(crate::localization::tr("Select islands")).clicked() {
                let islands = rows.iter().filter_map(|row| Some((row["index"].as_u64()? as u32, row["islands"].as_array()?)))
                    .filter(|(part, _)| garments.contains(part))
                    .flat_map(|(part, groups)| groups.iter().map(move |island| (part, faces_of(island))))
                    .collect();
                actions.push(UiAction::SelectIslands(islands));
            }
            if ui.button(crate::localization::tr("Clear selection")).clicked() {
                actions.push(UiAction::SelectIslands(Vec::new()));
            }
        });
        for row in rows {
            let Some(part) = row["index"].as_u64().map(|index| index as u32) else { continue; };
            if !garments.contains(&part) { continue; }
            let parent = state["refit"]["garment_settings"].as_array().into_iter().flatten()
                .find(|setting| setting["submesh_index"].as_u64() == Some(u64::from(part)));
            ui.push_id(("fit-islands", part), |ui| {
                let heading = ui.add(egui::AtomLayout::new(self.cdmw_part_name_atoms(part,
                    RichText::new(self.cdmw_morph_part_names(&[part])).strong())));
                self.track_cdmw_part_hover(ui, part, &heading);
                for (index, island) in row["islands"].as_array().into_iter().flatten().enumerate() {
                    let faces = faces_of(island);
                    let override_setting = parent.and_then(|parent| parent["island_settings"].as_array())
                        .and_then(|settings| settings.iter().find(|setting| setting["face_indices"] == json!(faces)));
                    let setting = override_setting.or(parent);
                    let label = if setting.and_then(|s| s["enabled"].as_bool()) == Some(false) { "Skip" }
                        else { match setting.and_then(|s| s["mode"].as_str()).unwrap_or("surface") {
                            "rigid_component" => "Rigid component", "rigid" => "Offset follow", _ => "Flexible",
                        }};
                    ui.push_id(index, |ui| ui.horizontal(|ui| {
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            ui.weak(crate::localization::tr(if override_setting.is_some() { "Custom" } else { "Inherited" }));
                            ui.weak(crate::localization::tr(label));
                            let title = crate::localization::tr(format!("Island {} · {} faces", index+1, faces.len()));
                            let active = selected.contains(&(part, faces.clone()));
                            let response = ui.add_enabled(visible.as_ref().is_none_or(|visible| visible.contains(&part)),
                                Button::selectable(active, self.cdmw_island_name_atoms(part, &faces, &title)).truncate())
                                .on_hover_text(&title)
                                .on_hover_text(crate::localization::tr("Ctrl-click to select several islands. Inherited settings follow the Part."));
                            self.track_cdmw_island_name(ui, part, faces.clone(), &response);
                            if response.clicked() {
                                let target = (part, faces);
                                let mut next = if ui.input(|input| input.modifiers.command || input.modifiers.ctrl) {
                                    selected.clone()
                                } else { Vec::new() };
                                if active { next.retain(|candidate| candidate != &target); } else { next.push(target); }
                                actions.push(UiAction::SelectIslands(next));
                            }
                        });
                    }));
                }
            });
        }
    }

    pub(super) fn draw_cdmw_refit_body_region(
        &mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>, state: &Value, edit_targets: &[u32],
    ) {
        let refit = state.get("refit").unwrap_or(&Value::Null);
        let garments = value_u32_list(refit, "garment_submesh_indices");
        self.cdmw_refit_region_targets.retain(|part| garments.contains(part));
        // The host serializes garment_regions as [garment_index, regions] pairs.
        let restricted = refit.get("garment_regions").and_then(Value::as_array).into_iter().flatten()
            .filter(|pair| pair.get(1).and_then(Value::as_array).is_some_and(|regions| !regions.is_empty())).count();
        let summary = if restricted == 0 { crate::localization::tr("Whole body") }
            else { crate::localization::tr(format!("{} restricted Parts", restricted)) };
        let title = format!("{} · {summary}", crate::localization::tr("Body region"));
        cdmw_section(ui, "refit-body-region", &title, None, |ui| {
            ui.weak(crate::localization::tr("Choose target garments, then select the body faces they may follow."));
            if ui.add_enabled(!edit_targets.is_empty(), Button::new(crate::localization::tr("Use editing targets")))
                .on_hover_text(crate::localization::tr("Capture the garments from Editing without changing the viewport selection.")).clicked()
            { self.cdmw_refit_region_targets = edit_targets.to_vec(); }
            for part in &garments {
                let mut checked = self.cdmw_refit_region_targets.contains(part);
                let name = self.cdmw_morph_part_names(&[*part]);
                let row = ui.scope(|ui| {
                    ui.style_mut().wrap_mode = Some(egui::TextWrapMode::Truncate);
                    ui.checkbox(&mut checked, self.cdmw_part_name_atoms(*part, &name))
                }).inner;
                self.track_cdmw_part_hover(ui, *part, &row);
                if row.on_hover_text(&name)
                    .on_hover_text(crate::localization::tr("Choose garments for the body-region buttons below. Your body selection is kept.")).changed()
                {
                    if checked { self.cdmw_refit_region_targets.push(*part); self.cdmw_refit_region_targets.sort_unstable(); }
                    else { self.cdmw_refit_region_targets.retain(|candidate| candidate != part); }
                }
            }
            ui.weak(crate::localization::tr(format!("{} target garments", self.cdmw_refit_region_targets.len())));
            ui.horizontal_wrapped(|ui| {
                let body = value_u32_list(state, "driver_submesh_indices");
                if ui.add_enabled(!body.is_empty(), Button::new(crate::localization::tr("Select body"))).clicked() {
                    actions.push(UiAction::SetPartSelection(body));
                }
                if ui.button(crate::localization::tr("Open Selection tool")).clicked() {
                    self.cancel_active_gesture("Open body region selection");
                    self.open_cdmw_tool_settings(ui.ctx(), CdmwRailPage::Select);
                }
            });
            if state_bool(state, "unbaked") {
                ui.weak(crate::localization::tr("Reset or Bake before changing the body region."));
            }
            let targets = self.cdmw_refit_region_targets.clone();
            let ready = state_bool(&self.cdmw_state, "authoring_enabled")
                && state_str(state, "correction_definition_id").is_none_or(|id| id.is_empty())
                && !state_bool(state, "unbaked") && !targets.is_empty();
            ui.horizontal_wrapped(|ui| {
                let help = if state_bool(state, "unbaked") {
                    "Region changes require a neutral fit. Other garments keep their bindings."
                } else {
                    "Check garments, select the body faces they may follow, then apply the region."
                };
                if ui.add_enabled(
                    ready && self.selected_counts().total() > 0,
                    Button::new(crate::localization::tr("Use selected body region")),
                )
                    .on_disabled_hover_text(crate::localization::tr(help))
                    .clicked()
                {
                    actions.push(UiAction::CdmwCommand {
                        command: "morph_set_driver_region",
                        arguments: json!({"garment_submesh_indices": targets}),
                        label: "Constrain garment binding to body region",
                    });
                }
                if ui.add_enabled(ready, Button::new(crate::localization::tr("Use whole body")))
                    .on_disabled_hover_text(crate::localization::tr(help))
                    .clicked()
                {
                    actions.push(UiAction::CdmwCommand {
                        command: "morph_clear_driver_region",
                        arguments: json!({"garment_submesh_indices": targets}),
                        label: "Clear selected garment body regions",
                    });
                }
            });
        });
    }

    pub(super) fn draw_cdmw_morph_correction_button(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        state: &Value,
        definition_id: &str,
    ) {
        let garments = value_u32_list(state.get("refit").unwrap_or(&Value::Null), "garment_submesh_indices");
        let targets: Vec<u32> = self.selected_part_indices().into_iter()
            .filter(|part| garments.contains(part)).collect();
        let corrected = state.get("definitions").and_then(Value::as_array)
            .and_then(|definitions| definitions.iter().find(|definition| state_str(definition, "definition_id") == Some(definition_id)))
            .map(|definition| value_u32_list(definition, "garment_correction_submesh_indices"))
            .unwrap_or_default();
        let reset_targets: Vec<u32> = targets.iter().copied().filter(|part| corrected.contains(part)).collect();
        let ready = state_bool(&self.cdmw_state, "authoring_enabled")
            && !state_bool(state, "authoring_baseline_ready")
            && state_str(state, "correction_definition_id").is_none_or(|id| id.is_empty())
            && !self.cdmw_morph_comparison_active()
            && !targets.is_empty();
        ui.push_id(("morph-correction", definition_id), |ui| {
            if ui.add_enabled(ready, Button::new(crate::localization::tr("Edit outfit correction")))
                .on_hover_text(crate::localization::tr(
                    "Set this slider to 100%, sculpt the selected garments, then save the correction. Other sliders are set to zero.",
                ))
                .on_disabled_hover_text(crate::localization::tr(
                    "Select bound garment Parts and finish any pending sculpted slider or correction first.",
                ))
                .clicked()
            {
                actions.push(UiAction::CdmwCommand {
                    command: "morph_begin_correction",
                    arguments: json!({"definition_id": definition_id, "garment_submesh_indices": targets}),
                    label: "Edit per-slider outfit correction",
                });
            }
            if !corrected.is_empty() && ui.add_enabled(ready && !reset_targets.is_empty(),
                Button::new(crate::localization::tr("Reset selected outfit correction")))
                .on_hover_text(crate::localization::tr(
                    "Remove this slider's saved correction only from the selected corrected garments. Other corrections and the body shape are retained.",
                )).clicked()
            {
                actions.push(UiAction::CdmwCommand {
                    command: "morph_reset_correction",
                    arguments: json!({"definition_id": definition_id, "garment_submesh_indices": reset_targets}),
                    label: "Reset selected outfit correction",
                });
            }
        });
    }

    pub(super) fn draw_cdmw_refit_recipe(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        state: &Value,
    ) {
        let authoring = state_bool(&self.cdmw_state, "authoring_enabled");
        let profile = state_str(state, "profile_id").unwrap_or("");
        let garments = value_u32_list(state.get("refit").unwrap_or(&Value::Null), "garment_submesh_indices");
        let pending = state_bool(state, "authoring_baseline_ready")
            || state_str(state, "correction_definition_id").is_some_and(|id| !id.is_empty());
        ui.horizontal_wrapped(|ui| {
            if ui.add_enabled(
                authoring && !pending && !profile.is_empty() && !garments.is_empty()
                    && !self.cdmw_morph_preset_name.trim().is_empty(),
                Button::new(crate::localization::tr("Save fitting setup...")),
            ).clicked() {
                actions.push(UiAction::ChooseCdmwRefitRecipe { save: true });
            }
            if ui.add_enabled(
                authoring && !pending && !state_bool(state, "unbaked"),
                Button::new(crate::localization::tr("Load fitting setup...")),
            ).clicked() {
                actions.push(UiAction::ChooseCdmwRefitRecipe { save: false });
            }
        });
        self.draw_cdmw_matching_setups(ui, actions, state);
    }
}
