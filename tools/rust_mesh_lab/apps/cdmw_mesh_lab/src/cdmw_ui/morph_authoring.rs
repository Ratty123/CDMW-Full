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
        ui.separator();
        ui.strong(crate::localization::tr("Follow controls"))
            .on_hover_text(crate::localization::tr(
                "Select garment vertices, faces or a whole Part to control how strongly they follow the body.",
            ));
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
    }

    pub(super) fn draw_cdmw_refit_garment_parts(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        state: &Value,
    ) {
        let garments = value_u32_list(state.get("refit").unwrap_or(&Value::Null), "garment_submesh_indices");
        let selected = self.selected_part_indices();
        let visible = self.cdmw_visible_submeshes();
        self.cdmw_refit_region_targets.retain(|part| garments.contains(part));
        ui.strong(crate::localization::tr("Garment parts"));
        ui.small(crate::localization::tr("Click a name to edit strength; check Region to limit where it follows."));
        ui.push_id("refit-garment-parts", |ui| {
            for part in &garments {
                ui.push_id(part, |ui| {
                    ui.horizontal(|ui| {
                        let mut checked = self.cdmw_refit_region_targets.contains(part);
                        if ui.checkbox(&mut checked, crate::localization::tr("Region"))
                            .on_hover_text(crate::localization::tr("Choose garments for the body-region buttons below. Your body selection is kept."))
                            .changed()
                        {
                            if checked {
                                self.cdmw_refit_region_targets.push(*part);
                                self.cdmw_refit_region_targets.sort_unstable();
                            } else {
                                self.cdmw_refit_region_targets.retain(|candidate| candidate != part);
                            }
                        }
                        let name = self.cdmw_morph_part_names(&[*part]);
                        let active = selected.contains(part);
                        if ui.add_enabled(
                            visible.as_ref().is_none_or(|visible| visible.contains(part)),
                            Button::selectable(active, &name).truncate(),
                        )
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
            }
            ui.strong(crate::localization::tr("Allowed body region"))
                .on_hover_text(crate::localization::tr("Check garments, select the body faces they may follow, then apply the region."));
            let targets = self.cdmw_refit_region_targets.clone();
            let ready = state_bool(&self.cdmw_state, "authoring_enabled")
                && !state_str(state, "correction_definition_id").is_some_and(|id| !id.is_empty())
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
            && !state_str(state, "correction_definition_id").is_some_and(|id| !id.is_empty())
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
