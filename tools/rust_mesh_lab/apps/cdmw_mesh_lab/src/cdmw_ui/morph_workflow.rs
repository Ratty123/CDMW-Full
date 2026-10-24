//! Navigation and persistent actions for the Morph & Refit workflow.
use super::*;

#[derive(Clone, Copy, Default, PartialEq)]
enum MorphTab {
    #[default]
    Setup,
    Fit,
    Shape,
    Saved,
}
#[derive(Clone, Copy, Default, PartialEq)]
enum ShapeTab {
    #[default]
    Body,
    Sides,
    Sliders,
}
#[derive(Clone, Copy, Default, PartialEq)]
enum SavedTab {
    #[default]
    Profiles,
    Presets,
    FittingSetups,
}

#[derive(Clone, Copy, Default)]
struct MorphWorkflow {
    tab: MorphTab,
    shape: ShapeTab,
    saved: SavedTab,
    create: bool,
    sculpted: bool,
}

impl LabApplication {
    pub(super) fn draw_cdmw_morph_page(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let state = self
            .cdmw_state
            .get("morph_refit")
            .cloned()
            .unwrap_or(Value::Null);
        if state.get("available").and_then(Value::as_bool) == Some(false) {
            self.draw_cdmw_part_hover_option(ui);
            ui.colored_label(
                REFIT_ARMOR_COLOUR,
                crate::localization::tr(
                    state_str(&state, "reason").unwrap_or("Morph runtime unavailable"),
                ),
            );
            return;
        }
        let profile_id = state_str(&state, "profile_id").unwrap_or("");
        if self.cdmw_morph_hydrated_profile != profile_id {
            if let Some((_, name)) = pair_list(&state, "available_profiles")
                .into_iter()
                .find(|(id, _)| id == profile_id)
            {
                self.cdmw_morph_profile_name = name;
            }
            self.cdmw_morph_hydrated_profile = profile_id.to_owned();
        }
        let id = egui::Id::new("cdmw-morph-workflow");
        let mut workflow = ui
            .data_mut(|data| data.get_temp::<MorphWorkflow>(id))
            .unwrap_or_default();
        ui.horizontal_wrapped(|ui| {
            for (tab, label) in [
                (MorphTab::Setup, "Setup"),
                (MorphTab::Fit, "Fit"),
                (MorphTab::Shape, "Shape"),
                (MorphTab::Saved, "Saved"),
            ] {
                ui.selectable_value(&mut workflow.tab, tab, crate::localization::tr(label));
            }
        });
        ui.horizontal_wrapped(|ui| {
            let mut part_colours = self.view_mode == ViewMode::PartId && !self.cdmw_island_colours;
            if ui.checkbox(&mut part_colours, crate::localization::tr("Part colors"))
                .on_hover_text(crate::localization::tr("Give each Part a different color to see overlaps. Display only; fitting and exports stay unchanged."))
                .changed()
            {
                self.set_cdmw_display_mode(if part_colours { ViewMode::PartId }
                    else { self.cdmw_part_colours_previous_mode });
            }
            self.draw_cdmw_island_colour_option(ui);
        });
        self.draw_cdmw_part_hover_option(ui);
        ui.separator();
        if let Some(failure) = state_str(&state, "failure").filter(|value| !value.trim().is_empty())
        {
            ui.colored_label(
                Color32::from_rgb(245, 105, 105),
                crate::localization::tr(failure),
            );
        }
        if !state_str(&state, "shape_restore_source").unwrap_or("").is_empty() {
            ui.label(state_str(&state, "shape_restore_source").unwrap_or(""))
                .on_hover_text(state_str(&state, "shape_restore_sha256").unwrap_or(""));
            ui.strong(crate::localization::tr("Selected geometry"));
            for row in state["shape_restore_scope"].as_array().into_iter().flatten() {
                if let (Some(part), Some(name), Some(islands)) = (row[0].as_u64(), row[1].as_str(), row[2].as_u64()) {
                    ui.label(crate::localization::tr(if islands == 0 { format!("Part {part}: {name}") }
                        else { format!("Part {part}: {name} · {islands} selected islands") }));
                }
            }
            ui.data_mut(|data| data.insert_temp(id, workflow));
            return;
        }
        let pending = state_bool(&state, "authoring_baseline_ready")
            || !state_str(&state, "shape_restore_source").unwrap_or("").is_empty()
            || state_str(&state, "correction_definition_id").is_some_and(|id| !id.is_empty())
            || self.cdmw_morph_comparison_active();
        let body = value_u32_list(&state, "driver_submesh_indices");
        let garments = value_u32_list(state.get("refit").unwrap_or(&Value::Null), "garment_submesh_indices");
        if matches!(workflow.tab, MorphTab::Setup | MorphTab::Fit) {
            self.draw_cdmw_refit_roles(ui, &body, &garments);
        }
        match workflow.tab {
            MorphTab::Setup => {
                self.draw_cdmw_morph_meshes(ui, actions, &state);
                ui.separator();
                ui.add_enabled_ui(!pending, |ui| {
                    if self.draw_cdmw_refit_setup(ui, actions, &state) {
                        workflow.tab = MorphTab::Fit;
                    }
                });
            }
            MorphTab::Fit => {
                ui.add_enabled_ui(!pending, |ui| {
                    if self.draw_cdmw_refit_section(ui, actions, &state) {
                        workflow.tab = MorphTab::Setup;
                    }
                });
            }
            MorphTab::Shape => {
                let has_definitions = state.get("definitions").and_then(Value::as_array)
                    .is_some_and(|definitions| !definitions.is_empty());
                if !workflow.create && !garments.is_empty() && !has_definitions
                    && ui.add_enabled(!pending && !state_bool(&state, "unbaked"),
                        Button::new(crate::localization::tr("Create body slider")))
                        .on_hover_text(crate::localization::tr("Select the body and open the slider creator. The bound garments will follow.")).clicked()
                {
                    actions.push(UiAction::SetPartSelection(body.clone()));
                    self.cdmw_morph_definition_edit_id.clear();
                    workflow.create = true;
                    workflow.sculpted = false;
                }
                if workflow.create {
                    if ui
                        .button(crate::localization::tr("Back to sliders"))
                        .clicked()
                    {
                        workflow.create = false;
                        workflow.shape = ShapeTab::Sliders;
                    }
                    ui.horizontal_wrapped(|ui| {
                        ui.selectable_value(
                            &mut workflow.sculpted,
                            false,
                            crate::localization::tr("Procedural"),
                        );
                        ui.selectable_value(
                            &mut workflow.sculpted,
                            true,
                            crate::localization::tr("Sculpted"),
                        );
                    });
                    ui.separator();
                    if workflow.sculpted {
                        ui.add_enabled_ui(!self.cdmw_morph_comparison_active(), |ui| {
                            self.draw_cdmw_authored_morph(ui, actions, &state);
                        });
                    } else {
                        ui.add_enabled_ui(!pending, |ui| {
                            self.draw_cdmw_procedural_slider(ui, actions, &state, &mut workflow);
                        });
                    }
                } else {
                    ui.horizontal_wrapped(|ui| {
                        for (tab, label) in [
                            (ShapeTab::Body, "Body"),
                            (ShapeTab::Sides, "Sides"),
                            (ShapeTab::Sliders, "Sliders"),
                        ] {
                            ui.selectable_value(
                                &mut workflow.shape,
                                tab,
                                crate::localization::tr(label),
                            );
                        }
                    });
                    ui.separator();
                    if workflow.shape == ShapeTab::Sliders
                        && ui.button(crate::localization::tr("+ Create")).clicked()
                    {
                        if !pending {
                            self.cdmw_morph_definition_edit_id.clear();
                            self.cdmw_morph_replace_selection_on_edit = false;
                        }
                        workflow.create = true;
                        workflow.sculpted = state_bool(&state, "authoring_baseline_ready");
                    }
                    ui.add_enabled_ui(!pending, |ui| match workflow.shape {
                        ShapeTab::Body => self.draw_cdmw_body_controls(ui, actions, &state),
                        ShapeTab::Sides => self.draw_cdmw_side_controls(ui, actions, &state),
                        ShapeTab::Sliders => {
                            if self.draw_cdmw_shape_sliders(ui, actions, &state) {
                                workflow.create = true;
                                workflow.sculpted = false;
                            }
                        }
                    });
                }
            }
            MorphTab::Saved => {
                ui.horizontal_wrapped(|ui| {
                    for (tab, label) in [
                        (SavedTab::Profiles, "Profiles"),
                        (SavedTab::Presets, "Presets"),
                        (SavedTab::FittingSetups, "Fitting setups"),
                    ] {
                        ui.selectable_value(
                            &mut workflow.saved,
                            tab,
                            crate::localization::tr(label),
                        );
                    }
                });
                ui.separator();
                ui.add_enabled_ui(!pending, |ui| match workflow.saved {
                    SavedTab::Profiles => self.draw_cdmw_saved_profiles(ui, actions, &state),
                    SavedTab::Presets => self.draw_cdmw_saved_presets(ui, actions, &state),
                    SavedTab::FittingSetups => {
                        ui.label(crate::localization::tr("Setup name"));
                        ui.add(
                            egui::TextEdit::singleline(&mut self.cdmw_morph_preset_name)
                                .desired_width(ui.available_width()),
                        );
                        self.draw_cdmw_refit_recipe(ui, actions, &state);
                    }
                });
            }
        }
        ui.data_mut(|data| data.insert_temp(id, workflow));
    }

    // Kept outside the scroll area in the expanded, pinned and floating panels.
    pub(super) fn cdmw_morph_footer_height(&self, ui: &egui::Ui) -> f32 {
        ui.data_mut(|data| data.get_temp::<f32>(ui.id().with("morph-footer-height")))
            .unwrap_or(ui.spacing().interact_size.y * 4.0 + 16.0)
    }

    pub(super) fn draw_cdmw_morph_footer(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
    ) {
        let state = self
            .cdmw_state
            .get("morph_refit")
            .cloned()
            .unwrap_or(Value::Null);
        let authoring = state_bool(&self.cdmw_state, "authoring_enabled");
        let available = state.get("available").and_then(Value::as_bool) != Some(false);
        let enabled = authoring && available && !self.cdmw_show_busy_controls();
        let previous_height = self.cdmw_morph_footer_height(ui);
        let footer = ui.push_id("cdmw-morph-footer", |ui| {
            ui.separator();
            ui.add_enabled_ui(enabled, |ui| {
                self.draw_cdmw_correction_comparison(ui, actions, &state);
                ui.add_enabled_ui(!self.cdmw_morph_comparison_active(), |ui| {
                    if state_str(&state, "shape_restore_source").is_some_and(|name| !name.is_empty()) {
                        ui.colored_label(REFIT_READY_COLOUR, crate::localization::tr("Restore preview"));
                        ui.weak(crate::localization::tr(format!("{} vertices",
                            state["shape_restore_vertex_count"].as_u64().unwrap_or(0))))
                            .on_hover_text(crate::localization::tr("Exclusions, materials, UVs, skin and fitting settings are retained. Apply adds one undoable edit."));
                        ui.horizontal_wrapped(|ui| {
                            if ui.button(crate::localization::tr("Apply")).clicked() {
                                actions.push(UiAction::CdmwCommand { command: "refit_restore_shape_apply", arguments: json!({}), label: "Apply restored fitting shape" });
                            }
                            if ui.button(crate::localization::tr("Cancel")).clicked() {
                                actions.push(UiAction::CdmwCommand { command: "refit_restore_shape_cancel", arguments: json!({}), label: "Cancel fitting shape restoration" });
                            }
                        });
                    } else if state_str(&state, "correction_definition_id").is_some_and(|id| !id.is_empty()) {
                        ui.colored_label(REFIT_READY_COLOUR, crate::localization::tr("Outfit correction"));
                        ui.horizontal_wrapped(|ui| {
                            if ui.button(crate::localization::tr("Save correction")).clicked() {
                                actions.push(UiAction::CdmwCommand { command: "morph_save_correction", arguments: json!({}), label: "Save outfit correction" });
                            }
                            if ui.button(crate::localization::tr("Cancel")).on_hover_text(crate::localization::tr("Discard all shape edits made while editing this correction and restore the previous slider values.")).clicked() {
                                actions.push(UiAction::CdmwCommand { command: "morph_cancel_correction", arguments: json!({}), label: "Cancel outfit correction" });
                            }
                        });
                    } else if state_bool(&state, "authoring_baseline_ready") {
                        ui.colored_label(REFIT_READY_COLOUR, crate::localization::tr("Body base captured"));
                        self.draw_cdmw_authored_morph_save(ui, actions, &state);
                    } else {
                        ui.weak(crate::localization::tr(if state_bool(&state, "unbaked") { "Preview active" } else { "No pending preview" }));
                        ui.horizontal_wrapped(|ui| {
                            if ui.add_enabled(!state_str(&state, "profile_id").unwrap_or("").is_empty(), Button::new(crate::localization::tr("Reset")))
                                .on_hover_text(crate::localization::tr("Clear the preview and return to the saved base.")).clicked() {
                                actions.push(UiAction::CdmwCommand { command: "morph_reset", arguments: json!({}), label: "Reset morph" });
                            }
                            if ui.add_enabled(state_bool(&state, "unbaked"), Button::new(crate::localization::tr("Bake")))
                                .on_hover_text(crate::localization::tr("Keep the current geometry as the new base.")).clicked() {
                                actions.push(UiAction::CdmwCommand { command: "morph_bake", arguments: json!({}), label: "Bake morph" });
                            }
                        });
                    }
                });
            });
        });
        let height = footer.response.rect.height() + ui.spacing().item_spacing.y;
        ui.data_mut(|data| data.insert_temp(ui.id().with("morph-footer-height"), height));
        if (height - previous_height).abs() > 0.5 {
            ui.ctx().request_repaint();
        }
    }

    fn draw_cdmw_saved_profiles(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        state: &Value,
    ) {
        let profile_id = state_str(state, "profile_id").unwrap_or("");
        let profiles = pair_list(state, "available_profiles");
        let profile_label = ui.label(crate::localization::tr("Profile"));
        ComboBox::from_id_salt("Profile")
            .width(ui.available_width())
            .truncate()
            .selected_text(
                profiles
                    .iter()
                    .find(|(id, _)| id == profile_id)
                    .map(|(_, name)| name.clone())
                    .unwrap_or_else(|| crate::localization::tr("No active profile")),
            )
            .show_ui(ui, |ui| {
                for (id, name) in profiles {
                    if ui.selectable_label(id == profile_id, name).clicked() {
                        actions.push(UiAction::CdmwCommand {
                            command: "morph_activate",
                            arguments: json!({"profile_id": id}),
                            label: "Activate morph profile",
                        });
                    }
                }
            })
            .response
            .labelled_by(profile_label.id);
        ui.horizontal_wrapped(|ui| {
            if ui
                .add_enabled(
                    !profile_id.is_empty(),
                    Button::new(crate::localization::tr("Save Profile")),
                )
                .clicked()
            {
                actions.push(UiAction::CdmwCommand {
                    command: "morph_save_profile",
                    arguments: json!({}),
                    label: "Save morph profile",
                });
            }
            if ui
                .add_enabled(
                    !profile_id.is_empty(),
                    Button::new(crate::localization::tr("Delete Profile")),
                )
                .clicked()
            {
                actions.push(UiAction::CdmwCommand {
                    command: "morph_delete_profile",
                    arguments: json!({"profile_id": profile_id}),
                    label: "Delete morph profile",
                });
            }
        });
    }

    fn draw_cdmw_saved_presets(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        state: &Value,
    ) {
        let profile_id = state_str(state, "profile_id").unwrap_or("");
        let authoring = state_bool(&self.cdmw_state, "authoring_enabled");
        let morph_unbaked = state_bool(state, "unbaked");
        let preset_id = state.get("preset_id").and_then(Value::as_str).unwrap_or("");
        let presets = pair_list(state, "available_presets");
        ui.add_enabled_ui(!profile_id.is_empty(), |ui| {
            let preset_label = ui.label(crate::localization::tr("Saved preset"));
            ComboBox::from_id_salt("Saved preset")
                .width(ui.available_width())
                .truncate()
                .selected_text(
                    presets
                        .iter()
                        .find(|(id, _)| id == preset_id)
                        .map(|(_, name)| name.clone())
                        .unwrap_or_else(|| crate::localization::tr("Current values")),
                )
                .show_ui(ui, |ui| {
                    for (id, name) in presets {
                        if ui.selectable_label(id == preset_id, name).clicked() {
                            actions.push(UiAction::CdmwCommand {
                                command: "morph_apply_preset",
                                arguments: json!({"preset_id": id}),
                                label: "Apply morph preset",
                            });
                        }
                    }
                })
                .response
                .labelled_by(preset_label.id);
        });
        ui.label(crate::localization::tr("Preset name"));
        ui.horizontal_wrapped(|ui| {
            ui.add(
                egui::TextEdit::singleline(&mut self.cdmw_morph_preset_name)
                    .desired_width(ui.available_width()),
            );
            if ui
                .add_enabled(
                    !profile_id.is_empty() && !self.cdmw_morph_preset_name.trim().is_empty(),
                    Button::new(crate::localization::tr("Save Preset")),
                )
                .on_disabled_hover_text(crate::localization::tr(
                    "Activate a profile and enter a non-empty preset name",
                ))
                .clicked()
            {
                let name = self.cdmw_morph_preset_name.trim().to_owned();
                actions.push(UiAction::CdmwCommand {
                    command: "morph_save_preset",
                    arguments: json!({
                        "preset_id": stable_ui_id("preset", &name),
                        "name": name
                    }),
                    label: "Save morph preset",
                });
            }
            if ui
                .add_enabled(
                    !preset_id.is_empty(),
                    Button::new(crate::localization::tr("Delete Preset")),
                )
                .clicked()
            {
                actions.push(UiAction::CdmwCommand {
                    command: "morph_delete_preset",
                    arguments: json!({"preset_id": preset_id}),
                    label: "Delete morph preset",
                });
            }
        });
        ui.horizontal_wrapped(|ui| {
            if ui
                .add_enabled(
                    authoring && !morph_unbaked,
                    Button::new(crate::localization::tr("Load Preset...")),
                )
                .clicked()
            {
                actions.push(UiAction::ChooseCdmwMorphPreset { save: false });
            }
            if ui
                .add_enabled(
                    !profile_id.is_empty() && !self.cdmw_morph_preset_name.trim().is_empty(),
                    Button::new(crate::localization::tr("Export Preset...")),
                )
                .clicked()
            {
                actions.push(UiAction::ChooseCdmwMorphPreset { save: true });
            }
        });
    }

    fn draw_cdmw_shape_sliders(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        state: &Value,
    ) -> bool {
        let profile_id = state_str(state, "profile_id").unwrap_or("");
        let profiles = pair_list(state, "available_profiles");
        let active_profile_name = profiles
            .iter()
            .find(|(id, _)| id == profile_id)
            .map(|(_, name)| name.clone())
            .unwrap_or_default();
        let definitions = state
            .get("definitions")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let authoring = state_bool(&self.cdmw_state, "authoring_enabled");
        let morph_unbaked = state_bool(state, "unbaked");
        let mut reveal_authoring = false;
        if definitions.is_empty() {
            ui.weak(crate::localization::tr(
                "Create a slider or load a preset to begin.",
            ));
        }
        let values = pair_number_list(
            state,
            if state.get("manual_values").is_some() {
                "manual_values"
            } else {
                "values"
            },
        );
        let effective_values = pair_number_list(state, "values");
        for (definition_id, host_value) in values {
            let definition = definitions
                .iter()
                .find(|candidate| state_str(candidate, "definition_id") == Some(&definition_id));
            let label = definition
                .and_then(|candidate| state_str(candidate, "label"))
                .filter(|label| !label.trim().is_empty())
                .unwrap_or(&definition_id)
                .to_owned();
            let minimum = definition
                .and_then(|candidate| candidate.get("min_percent"))
                .and_then(Value::as_f64)
                .filter(|value| value.is_finite())
                .unwrap_or(-100.0);
            let maximum = definition
                .and_then(|candidate| candidate.get("max_percent"))
                .and_then(Value::as_f64)
                .filter(|value| value.is_finite() && *value > minimum)
                .unwrap_or(100.0);
            let authored = definition.and_then(|candidate| state_str(candidate, "source_kind"))
                == Some("authored");
            let rule = definition
                .and_then(|candidate| candidate.get("rule"))
                .cloned()
                .unwrap_or(Value::Null);
            let rule_name = state_str(&rule, "kind").unwrap_or("stored").to_owned();
            let rule_axis = state_str(&rule, "axis").unwrap_or("-").to_owned();
            let rule_amount = rule
                .get("amount")
                .and_then(Value::as_f64)
                .filter(|amount| amount.is_finite())
                .unwrap_or(0.0);
            let rule_feather = rule
                .get("feather")
                .and_then(Value::as_u64)
                .unwrap_or(2)
                .min(64) as u32;
            let rule_falloff = state_str(&rule, "falloff").unwrap_or("smooth").to_owned();
            let mirror_mode = definition
                .and_then(|candidate| state_str(candidate, "mirror_mode"))
                .unwrap_or("off")
                .to_owned();
            let draft_id = format!("definition:{definition_id}");
            let mut value = self
                .cdmw_morph_value_drafts
                .get(&draft_id)
                .copied()
                .unwrap_or(host_value);
            let response = ui
            .add(crate::cdmw_ui::numeric::slider(&mut value, minimum..=maximum).text(crate::localization::tr(&label)))
            .on_hover_text(crate::localization::tr(if authored {
                "Stored sculpted shape. 100% reproduces the captured body target.".to_owned()
            } else {
                format!("Stored {rule_name} rule · axis {rule_axis} · 100% strength {rule_amount:.3}")
            }));
            let commit = stage_cdmw_morph_value(
                &mut self.cdmw_morph_value_drafts,
                &draft_id,
                value,
                response.changed(),
                response.is_pointer_button_down_on() || response.has_focus(),
                response.drag_stopped() || response.lost_focus(),
            );
            if let Some((_, effective_value)) = effective_values
                .iter()
                .find(|(id, _)| id == &definition_id)
                .filter(|(_, effective)| (*effective - host_value).abs() > 0.000_001)
            {
                ui.small(crate::localization::tr(format!(
                    "Preview value: {effective_value:.3}%"
                )));
            }
            ui.push_id(("morph-definition-actions", &definition_id), |ui| {
                ui.horizontal_wrapped(|ui| {
                    if ui.add_enabled(!authored, Button::new(crate::localization::tr("Edit slider")))
                        .on_disabled_hover_text(crate::localization::tr("Sculpted sliders store a captured shape. Capture a new target to replace the shape."))
                        .clicked() {
                        reveal_authoring = true;
                        self.cdmw_morph_definition_edit_id = definition_id.clone();
                        self.cdmw_morph_replace_selection_on_edit = false;
                        self.cdmw_morph_definition_label = label.clone();
                        self.cdmw_morph_rule = rule_name.clone();
                        self.cdmw_morph_axis = rule_axis.clone();
                        self.cdmw_morph_amount = rule_amount as f32;
                        self.cdmw_morph_feather = rule_feather;
                        self.cdmw_morph_falloff = rule_falloff.clone();
                        self.cdmw_morph_mirror_mode = mirror_mode.clone();
                        if !active_profile_name.is_empty() {
                            self.cdmw_morph_profile_name = active_profile_name.clone();
                        }
                    }
                    if ui
                        .add_enabled(authoring && !morph_unbaked, Button::new(crate::localization::tr("Delete slider")))
                        .on_disabled_hover_text(crate::localization::tr(if !authoring {
                            "This session is read-only"
                        } else {
                            "Reset or Bake the current Morph preview before deleting a slider"
                        }))
                        .clicked()
                    {
                        actions.push(UiAction::CdmwCommand {
                            command: "morph_delete_definition",
                            arguments: json!({"definition_id": definition_id.clone()}),
                            label: "Delete morph slider",
                        });
                    }
                });
            });
            self.draw_cdmw_morph_correction_button(ui, actions, state, &definition_id);
            if let Some(value) = commit {
                actions.push(UiAction::CdmwCommand {
                command: "morph_set_value",
                arguments: json!({"definition_id": definition_id, "value": value, "phase": "end"}),
                label: "Change morph value",
            });
            }
        }
        reveal_authoring
    }

    fn draw_cdmw_procedural_slider(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        state: &Value,
        workflow: &mut MorphWorkflow,
    ) {
        let profile_id = state_str(state, "profile_id").unwrap_or("");
        let profiles = pair_list(state, "available_profiles");
        let active_profile_name = profiles
            .iter()
            .find(|(id, _)| id == profile_id)
            .map(|(_, name)| name.clone())
            .unwrap_or_default();
        let definitions = state
            .get("definitions")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let authoring = state_bool(&self.cdmw_state, "authoring_enabled");
        let morph_unbaked = state_bool(state, "unbaked");
        let has_mesh_selection =
            self.selected_counts().total() > 0 || !self.selected_part_indices().is_empty();
        ui.small(crate::localization::tr(if has_mesh_selection {
            "New sliders use the current selection."
        } else {
            "Select a Part or region before creating a slider."
        }));
        ui.label(crate::localization::tr("Profile name"));
        ui.add(
            egui::TextEdit::singleline(&mut self.cdmw_morph_profile_name)
                .desired_width(ui.available_width()),
        );
        ui.label(crate::localization::tr("Slider label"));
        ui.add(
            egui::TextEdit::singleline(&mut self.cdmw_morph_definition_label)
                .desired_width(ui.available_width()),
        );
        let editing_definition = !self.cdmw_morph_definition_edit_id.is_empty();
        if editing_definition {
            ui.horizontal_wrapped(|ui| {
                ui.colored_label(
                    Color32::from_rgb(105, 205, 135),
                    crate::localization::tr(format!(
                        "Editing slider · {}",
                        self.cdmw_morph_definition_label
                    )),
                );
                ui.add_enabled(
                    has_mesh_selection,
                    egui::Checkbox::new(
                        &mut self.cdmw_morph_replace_selection_on_edit,
                        crate::localization::tr("Replace scope with current selection"),
                    ),
                )
                .on_disabled_hover_text(crate::localization::tr(
                    "Select elements or Parts before replacing the stored scope",
                ));
                if ui.button(crate::localization::tr("Cancel Edit")).clicked() {
                    self.cdmw_morph_definition_edit_id.clear();
                    self.cdmw_morph_replace_selection_on_edit = false;
                    workflow.create = false;
                }
            });
        }
        let replace_edit_scope = editing_definition && self.cdmw_morph_replace_selection_on_edit;
        ui.push_id("morph-definition", |ui| {
            ui.label(crate::localization::tr("Rule"));
            ComboBox::from_id_salt("morph-rule")
                .width(ui.available_width())
                .selected_text(crate::localization::tr(&self.cdmw_morph_rule))
                .show_ui(ui, |ui| {
                    for (value, label) in [
                        ("volume", "Volume"),
                        ("scale", "Scale"),
                        ("move", "Move"),
                        ("flatten", "Flatten"),
                        ("taper", "Taper"),
                        ("twist", "Twist"),
                        ("radius", "Radius"),
                    ] {
                        ui.selectable_value(
                            &mut self.cdmw_morph_rule,
                            value.to_owned(),
                            crate::localization::tr(label),
                        );
                    }
                });
            ui.label(crate::localization::tr("Axis"));
            ComboBox::from_id_salt("morph-axis")
                .width(ui.available_width())
                .selected_text(crate::localization::tr(self.cdmw_morph_axis.to_ascii_uppercase()))
                .show_ui(ui, |ui| {
                    for axis in ["x", "y", "z"] {
                        ui.selectable_value(
                            &mut self.cdmw_morph_axis,
                            axis.to_owned(),
                            crate::localization::tr(axis.to_ascii_uppercase()),
                        );
                    }
                });
            ui.vertical(|ui| {
                let twist = self.cdmw_morph_rule == "twist";
                ui.label(crate::localization::tr(if twist {
                    "100% rotation (degrees)"
                } else {
                    "100% strength"
                }));
                ui.add(
                    crate::cdmw_ui::numeric::value(&mut self.cdmw_morph_amount)
                        .speed(if twist { 1.0 } else { 0.01 })
                        .range(if twist { -180.0..=180.0 } else { -10.0..=10.0 }),
                );
            });
            ui.add_enabled_ui(!editing_definition || replace_edit_scope, |ui| {
                ui.vertical(|ui| {
                    ui.label(crate::localization::tr("Feather rings"));
                    ui.add(
                        crate::cdmw_ui::numeric::value(&mut self.cdmw_morph_feather).range(0..=64),
                    );
                });
                ui.label(crate::localization::tr("Falloff"));
                ComboBox::from_id_salt("morph-falloff")
                    .width(ui.available_width())
                    .selected_text(crate::localization::tr(&self.cdmw_morph_falloff))
                    .show_ui(ui, |ui| {
                        for falloff in ["constant", "linear", "smooth"] {
                            ui.selectable_value(
                                &mut self.cdmw_morph_falloff,
                                falloff.to_owned(),
                                crate::localization::tr(falloff),
                            );
                        }
                    });
                ui.label(crate::localization::tr("Mirror"));
                ComboBox::from_id_salt("morph-mirror")
                    .width(ui.available_width())
                    .selected_text(crate::localization::tr(&self.cdmw_morph_mirror_mode))
                    .show_ui(ui, |ui| {
                        for mirror in ["off", "x", "y", "z"] {
                            ui.selectable_value(
                                &mut self.cdmw_morph_mirror_mode,
                                mirror.to_owned(),
                                crate::localization::tr(mirror),
                            );
                        }
                    });
            });
            if editing_definition && !replace_edit_scope {
                ui.small(crate::localization::tr("Feather, falloff, and mirror stay locked because the stored scope is being preserved."));
            }
        });
        let create_ready = authoring
            && !morph_unbaked
            && (has_mesh_selection || (editing_definition && !replace_edit_scope))
            && !self.cdmw_morph_profile_name.trim().is_empty()
            && !self.cdmw_morph_definition_label.trim().is_empty();
        let create_label = if editing_definition {
            "Update Slider"
        } else {
            "Add Slider"
        };
        if ui
            .add_enabled(
                create_ready,
                Button::new(crate::localization::tr(create_label)),
            )
            .on_disabled_hover_text(crate::localization::tr(if !authoring {
                "This session is read-only"
            } else if morph_unbaked {
                "Reset or Bake the current Morph preview before changing slider definitions"
            } else if !has_mesh_selection && (!editing_definition || replace_edit_scope) {
                "Select vertices, edges, faces, or Parts to define the slider scope"
            } else {
                "Enter a profile name and slider label"
            }))
            .clicked()
        {
            let profile_name = self.cdmw_morph_profile_name.trim().to_owned();
            let label = self.cdmw_morph_definition_label.trim().to_owned();
            let source_definition_id = self.cdmw_morph_definition_edit_id.clone();
            let source_definition = definitions.iter().find(|candidate| {
                state_str(candidate, "definition_id") == Some(source_definition_id.as_str())
            });
            let category = source_definition
                .and_then(|candidate| state_str(candidate, "category"))
                .unwrap_or("General")
                .to_owned();
            let minimum = source_definition
                .and_then(|candidate| candidate.get("min_percent"))
                .and_then(Value::as_f64)
                .unwrap_or(-100.0);
            let maximum = source_definition
                .and_then(|candidate| candidate.get("max_percent"))
                .and_then(Value::as_f64)
                .unwrap_or(100.0);
            let default = source_definition
                .and_then(|candidate| candidate.get("default_percent"))
                .and_then(Value::as_f64)
                .unwrap_or(0.0);
            let profile_id = if !profile_id.is_empty()
                && (editing_definition || profile_name == active_profile_name)
            {
                profile_id.to_owned()
            } else {
                stable_ui_id("profile", &profile_name)
            };
            let definition_id = stable_ui_id("morph", &label);
            actions.push(UiAction::CdmwCommand {
                command: "morph_create",
                arguments: json!({
                    "definition": {
                        "profile_id": profile_id,
                        "profile_name": profile_name,
                        "definition_id": definition_id,
                        "label": label,
                        "category": category,
                        "rule": self.cdmw_morph_rule,
                        "axis": self.cdmw_morph_axis,
                        "amount": self.cdmw_morph_amount,
                        "feather": self.cdmw_morph_feather,
                        "falloff": self.cdmw_morph_falloff,
                        "mirror_mode": self.cdmw_morph_mirror_mode,
                        "min_percent": minimum,
                        "max_percent": maximum,
                        "default_percent": default,
                        "preserve_selection": editing_definition && !replace_edit_scope,
                        "source_definition_id": source_definition_id
                    }
                }),
                label: if editing_definition {
                    "Update morph slider"
                } else {
                    "Add morph slider"
                },
            });
        }
    }
}
