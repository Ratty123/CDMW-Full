//! Edit existing cloth influence through the host's reversible PAC output path.
pub(crate) mod preview;
mod authoring {
    //! Bounded guide creation on existing skeleton bones through the host worker.
    use super::*;

    #[derive(Default)]
    pub(crate) struct GuideView {
        pub selected_only: bool,
        pub source_lod: u32,
        pub height: f64,
        pub reduce_skinning: bool,
        key: Value,
    }

    impl LabApplication {
        pub(super) fn draw_cdmw_guide_authoring(
            &mut self,
            ui: &mut egui::Ui,
            actions: &mut Vec<UiAction>,
        ) {
            let state = self.cdmw_state["cloth_guides"].clone();
            if state.is_null() {
                return;
            }
            crate::localization::collapsing("Create cloth guides (experimental)").show(ui, |ui| {
                ui.small(crate::localization::tr("Builds a simulation mesh from a stored LOD, using the existing bones."));
                if !state_bool(&state, "available") {
                    ui.label(crate::localization::tr(state_str(&state, "reason").unwrap_or("Guide creation is unavailable.")));
                    return;
                }
                ui.checkbox(&mut self.cdmw_cloth.guides.selected_only, crate::localization::tr("Create guides for selected parts only"));
                let selected = self.selected_part_indices();
                let parts = state["parts"].as_array().into_iter().flatten()
                    .filter(|part| (state_bool(part, "included") || !part["rule"].is_null())
                        && (!self.cdmw_cloth.guides.selected_only || selected.contains(&(state_u64(part, "index") as u32))))
                    .collect::<Vec<_>>();
                if parts.is_empty() {
                    ui.label(crate::localization::tr("Select an included part to create guides."));
                    return;
                }
                let ids = parts.iter().filter_map(|part| part["id"].as_str()).collect::<Vec<_>>();
                let enabled = !self.cdmw_busy() && state_bool(&self.cdmw_state, "authoring_enabled");
                let key = json!([ids, parts.iter().map(|part| &part["rule"]).collect::<Vec<_>>()]);
                let view = &mut self.cdmw_cloth.guides;
                if view.key != key {
                    view.key = key;
                    let mixed = parts.iter().any(|part| part["rule"] != parts[0]["rule"]);
                    let rule = if mixed { &Value::Null } else { &parts[0]["rule"] };
                    view.source_lod = rule["source_lod"].as_u64().unwrap_or(0) as u32;
                    let low = parts.iter().filter_map(|part| part["min_y"].as_f64()).fold(f64::INFINITY, f64::min);
                    let high = parts.iter().filter_map(|part| part["max_y"].as_f64()).fold(f64::NEG_INFINITY, f64::max);
                    view.height = rule["fixed_above"].as_f64().unwrap_or(low + (high-low)*0.9);
                    view.reduce_skinning = rule["reduce_skinning"].as_bool().unwrap_or(false);
                }
                egui::ComboBox::from_id_salt("cloth-guide-source-lod")
                    .selected_text(crate::localization::tr(format!("Source LOD {}", view.source_lod))).show_ui(ui, |ui| {
                        for lod in 0..state_u64(&state, "lod_count") as u32 {
                            ui.selectable_value(&mut view.source_lod, lod, crate::localization::tr(format!("Source LOD {lod}")));
                        }
                    });
                let vertices: u64 = parts.iter().filter_map(|part| part["lod_vertices"][view.source_lod as usize].as_u64()).sum();
                ui.small(crate::localization::tr(format!("{vertices} source vertices before welding; maximum 1,024 guides across all parts.")));
                ui.horizontal(|ui| {
                    ui.label(crate::localization::tr("Pin guides at or above Y"));
                    ui.add(crate::cdmw_ui::numeric::value(&mut view.height).speed(0.01));
                });
                ui.small(crate::localization::tr("Height uses displayed model coordinates. Each disconnected piece needs an anchor."));
                ui.checkbox(&mut view.reduce_skinning, crate::localization::tr("Reduce skinning to four bones"));
                ui.small(crate::localization::tr("Optional: keeps the four strongest bone weights and normalizes them at every LOD. This changes skeletal deformation."));
                let valid = enabled && view.height.is_finite() && parts.iter().all(|part| state_bool(part, "included"));
                if ui.add_enabled(valid, egui::Button::new(crate::localization::tr("Create / update guides"))).clicked() {
                    actions.push(UiAction::CdmwCommand { command: "replacement_guides",
                        arguments: json!({"part_ids": ids, "source_lod": view.source_lod, "fixed_above": view.height,
                                          "reduce_skinning": view.reduce_skinning}),
                        label: "Create cloth guides" });
                }
                if ui.add_enabled(enabled && parts.iter().any(|part| !part["rule"].is_null()),
                                  egui::Button::new(crate::localization::tr("Restore source guides"))).clicked() {
                    actions.push(UiAction::CdmwCommand { command: "replacement_guides",
                        arguments: json!({"part_ids": ids, "reset": true}), label: "Restore source guides" });
                }
                ui.small(crate::localization::tr("Creates bindings at every stored LOD. Saved in drafts and Build Mod; game activation is unverified."));
            });
        }
    }
}
pub(super) mod profiles {
    //! Separate raw profile authoring from converted preview presets.
    use crate::UiAction;
    use cdmw_mesh::cloth::Settings;
    use serde::Deserialize;
    use serde_json::{Value, json};

    #[derive(Default)]
    pub(crate) struct ProfileView {
        variant: Option<String>,
        source: Value,
        loaded: Option<(Value, Settings)>,
        edit_group: Option<String>,
        edit_source: Option<String>,
        edit_key: Value,
        edit_values: std::collections::BTreeMap<String, f64>,
    }

    impl ProfileView {
        pub(crate) fn clear_loaded(&mut self) {
            self.loaded = None;
        }

        pub(crate) fn has_loaded(&self) -> bool {
            self.loaded.is_some()
        }
    }

    #[derive(Clone, Copy, Deserialize)]
    struct Preset {
        gravity: f64,
        damping: f64,
        stretch: f64,
        bend: f64,
        iterations: u32,
        use_vertex_alpha: bool,
        rotate_guides: bool,
        #[serde(default)]
        spline: bool,
        #[serde(default)]
        restore_angle: f64,
        #[serde(default)]
        single_edge_rotation: bool,
    }

    impl Preset {
        fn read(value: &Value) -> Option<Self> {
            let result: Self = serde_json::from_value(value.clone()).ok()?;
            ((-100.0..=100.0).contains(&result.gravity)
                && (0.0..=10.0).contains(&result.damping)
                && (0.0..=1.0).contains(&result.stretch)
                && (0.0..=1.0).contains(&result.bend)
                && (0.0..=1.0).contains(&result.restore_angle)
                && (1..=8).contains(&result.iterations))
            .then_some(result)
        }

        fn apply(self, settings: &mut Settings, rotation_available: bool) {
            settings.gravity = self.gravity;
            settings.damping = self.damping;
            settings.stretch = self.stretch;
            settings.bend = self.bend;
            settings.spline = self.spline;
            settings.restore_angle = self.restore_angle;
            settings.single_edge_rotation = self.single_edge_rotation;
            settings.iterations = self.iterations;
            settings.use_vertex_alpha = self.use_vertex_alpha;
            settings.rotate_guides = self.rotate_guides && rotation_available;
        }
    }

    impl From<Settings> for Preset {
        fn from(settings: Settings) -> Self {
            Self {
                gravity: settings.gravity,
                damping: settings.damping,
                stretch: settings.stretch,
                bend: settings.bend,
                iterations: settings.iterations,
                use_vertex_alpha: settings.use_vertex_alpha,
                rotate_guides: settings.rotate_guides,
                spline: settings.spline,
                restore_angle: settings.restore_angle,
                single_edge_rotation: settings.single_edge_rotation,
            }
        }
    }

    fn assigned_profile<'a>(
        state: &'a Value,
        parts: &[Value],
        variant: Option<&str>,
    ) -> Result<&'a Value, &'static str> {
        let variant =
            variant.ok_or("Choose a preview variant. The active game variant is not known.")?;
        let rows = state["parts"]
            .as_array()
            .ok_or("Profile part assignments are unavailable.")?;
        let mut selected_path = None;
        for part in parts {
            let row = rows
                .iter()
                .find(|row| row["index"] == part["index"])
                .ok_or("A selected part has no verified profile assignment.")?;
            let bindings = row["bindings"]
                .as_array()
                .ok_or("Profile assignments are unavailable.")?;
            let matches = bindings
                .iter()
                .filter(|binding| binding["variant"].as_str() == Some(variant))
                .collect::<Vec<_>>();
            if matches.is_empty() {
                return Err("A selected part has no assignment in this variant.");
            }
            for binding in matches {
                if binding["profile"].as_str() == Some("") {
                    return Err("This variant explicitly leaves a selected part without a profile.");
                }
                if binding["reason"]
                    .as_str()
                    .is_none_or(|reason| !reason.is_empty())
                {
                    return Err("A selected profile could not be resolved from its exact source.");
                }
                let path = binding["path"]
                    .as_str()
                    .filter(|path| !path.is_empty())
                    .ok_or("The exact profile source is unavailable.")?;
                if selected_path.is_some_and(|previous| previous != path) {
                    return Err(
                        "Selected parts use different profiles. Preview one assignment at a time.",
                    );
                }
                selected_path = Some(path);
            }
        }
        let path = selected_path.ok_or("Select an included part to inspect its profile.")?;
        state["profiles"]
            .as_array()
            .and_then(|profiles| {
                profiles
                    .iter()
                    .find(|profile| profile["path"].as_str() == Some(path))
            })
            .ok_or("The exact profile source is unavailable.")
    }

    fn restore_manual(
        view: &mut ProfileView,
        settings: &mut Settings,
        rotation_available: bool,
        spline_available: bool,
    ) -> bool {
        if let Some((_, manual)) = view.loaded.take() {
            Preset::from(manual).apply(settings, if manual.spline { spline_available } else { rotation_available });
            return true;
        }
        false
    }

    fn source_key(source: &Value) -> String {
        json!([source["name"], source["path"], source["sha256"]]).to_string()
    }

    fn draw_collision_overrides(ui: &mut egui::Ui, source: &Value, view: &mut ProfileView) {
        crate::localization::collapsing("Collision and attachment overrides").show(ui, |ui| {
            for (key, label) in [
                ("IsCloak", "Cloak behavior"),
                ("UseBackStopCollision", "Backstop collisions"),
                ("UseInputPositionCollision", "Input-position collisions"),
                ("ShrinkWhenShieldIsInSocket", "Shrink around sheathed shield"),
                ("UseLraConstraint", "Long-range attachments"),
            ] {
                ui.push_id(key, |ui| {
                    ui.horizontal_wrapped(|ui| {
                        let raw = source["authored"][key.to_ascii_lowercase()].as_str();
                        let original = raw.and_then(|text| text.parse::<f64>().ok())
                            .filter(|value| *value == 0.0 || *value == 1.0);
                        let mut overridden = view.edit_values.contains_key(key);
                        let mut value = view.edit_values.get(key).copied().or(original).unwrap_or(0.0) == 1.0;
                        ui.checkbox(&mut overridden, crate::localization::tr(format!("Override {label}")));
                        if overridden {
                            ui.checkbox(&mut value, crate::localization::tr("Enabled"));
                            view.edit_values.insert(key.to_owned(), if value { 1.0 } else { 0.0 });
                        } else {
                            view.edit_values.remove(key);
                            ui.small(crate::localization::tr(match (raw, original) {
                                (_, Some(0.0)) => "Disabled in source",
                                (_, Some(_)) => "Enabled in source",
                                (Some(_), None) => "Invalid source value",
                                (None, None) => "Source default",
                            }));
                        }
                    });
                });
            }
            ui.small(crate::localization::tr("Exports raw collision and attachment switches. The preview does not reproduce every game collision branch."));
        });
    }

    fn draw_authoring(
        ui: &mut egui::Ui,
        state: &Value,
        view: &mut ProfileView,
        actions: &mut Vec<UiAction>,
        enabled: bool,
    ) {
        let Some(variant) = view.variant.clone() else {
            return;
        };
        let groups = state["groups"]
            .as_array()
            .into_iter()
            .flatten()
            .filter(|group| group["variant"].as_str() == Some(variant.as_str()))
            .collect::<Vec<_>>();
        if groups.is_empty() {
            return;
        }
        crate::localization::collapsing("Edit profile for mod").show(ui, |ui| {
            if groups.len() == 1 {
                view.edit_group = groups[0]["id"].as_str().map(str::to_owned);
            }
            if groups.len() > 1 {
                ui.horizontal_wrapped(|ui| {
                    for (index, group) in groups.iter().enumerate() {
                        let id = group["id"].as_str().unwrap_or_default();
                        if ui.add(egui::Button::new(crate::localization::tr(format!("Profile group {}", index + 1)))
                            .selected(view.edit_group.as_deref() == Some(id))).clicked() {
                            view.edit_group = Some(id.to_owned());
                        }
                    }
                });
            }
            let Some(group) = groups.iter().find(|group| group["id"].as_str() == view.edit_group.as_deref()) else {
                ui.small(crate::localization::tr("Choose a profile group to edit.")); return;
            };
            let names = group["names"].as_array().into_iter().flatten().filter_map(Value::as_str).collect::<Vec<_>>();
            ui.label(crate::localization::tr(format!("Applies to all {} parts sharing this assignment", names.len())));
            ui.small(crate::localization::tr(names.join(", ")));
            if let Some(reason) = group["reason"].as_str().filter(|reason| !reason.is_empty()) { ui.small(crate::localization::tr(reason)); }
            let sources = state["sources"].as_array().map(Vec::as_slice).unwrap_or(&[]);
            let key = json!([state["sidecar_sha256"], group["id"], group["rule"], sources]);
            if view.edit_key != key {
                view.edit_key = key;
                let saved = &group["rule"];
                view.edit_source = sources.iter().find(|source| {
                    if saved.is_object() {
                        source["name"] == saved["source_profile"] && source["path"] == saved["source_path"]
                            && source["sha256"] == saved["source_sha256"]
                    } else { source["name"] == group["source_profile"] }
                }).map(source_key);
                view.edit_values = saved["values"].as_object().into_iter().flatten()
                    .filter_map(|(key, value)| value.as_f64().map(|value| (key.clone(), value))).collect();
            }
            let previous = view.edit_source.clone();
            let selected = sources.iter().find(|source| Some(source_key(source)) == view.edit_source)
                .and_then(|source| source["name"].as_str()).unwrap_or("Choose source profile");
            egui::ComboBox::from_id_salt("physics-profile-source").selected_text(crate::localization::tr(selected)).show_ui(ui, |ui| {
                for source in sources {
                    ui.selectable_value(&mut view.edit_source, Some(source_key(source)),
                        crate::localization::tr(source["name"].as_str().unwrap_or("Profile")));
                }
            });
            if previous != view.edit_source { view.edit_values.clear(); }
            let source = sources.iter().find(|source| Some(source_key(source)) == view.edit_source);
            if let Some(source) = source {
                for (key, label, low, high, integer) in [
                    ("StretchingStiffness", "Stretch stiffness", 0.0, 1.0, false),
                    ("BendingStiffness", "Bend stiffness", 0.0, 1.0, false),
                    ("RestoreAngleStiffness", "Spring-back stiffness", 0.0, 1.0, false),
                    ("Damping", "Damping", 0.0, 10.0, false),
                    ("Gravity", "Gravity", -100.0, 100.0, false),
                    ("SolverIterationCount", "Iterations", 1.0, 64.0, true),
                    ("UseVertexAlphaPositionBlending", "Vertex alpha", 0.0, 1.0, true),
                    ("UseRotationCorrection", "Guide rotation", 0.0, 1.0, true),
                ] {
                    ui.horizontal(|ui| {
                        let raw = source["authored"][key.to_ascii_lowercase()].as_str();
                        let original = raw.and_then(|text| text.parse::<f64>().ok())
                            .filter(|number| number.is_finite());
                        let mut overridden = view.edit_values.contains_key(key);
                        let mut value = view.edit_values.get(key).copied()
                            .filter(|number| number.is_finite()).or(original).unwrap_or(low).clamp(low, high);
                        ui.checkbox(&mut overridden, crate::localization::tr(format!("Override {label}")));
                        if overridden {
                            let mut control = crate::cdmw_ui::numeric::value(&mut value).range(low..=high).speed(if integer { 1.0 } else { 0.01 });
                            if integer { control = control.max_decimals(0); }
                            ui.add(control);
                            // Invalid text entered into a numeric control must
                            // never serialize as a null/nonfinite raw override.
                            value = if value.is_finite() { value.clamp(low, high) } else { low };
                            if integer { value = value.round(); }
                            view.edit_values.insert(key.to_owned(), value);
                        } else {
                            view.edit_values.remove(key);
                            ui.small(crate::localization::tr(match (raw, original) {
                                (Some(text), Some(_)) => text,
                                (Some(_), None) => "Invalid source value",
                                (None, _) => "Source default",
                            }));
                        }
                    });
                }
                draw_collision_overrides(ui, source, view);
                if ui.add_enabled(enabled && group["available"].as_bool() == Some(true) && !view.edit_values.is_empty(),
                    egui::Button::new(crate::localization::tr("Apply profile edit"))).clicked() {
                    actions.push(UiAction::CdmwCommand {
                        command: "replacement_physics_profile",
                        arguments: json!({"group_id": group["id"], "rule": {
                            "variant": variant, "source_profile": source["name"], "source_path": source["path"],
                            "source_sha256": source["sha256"], "values": view.edit_values}}), label: "Edit physics profile",
                    });
                }
            } else { ui.small(crate::localization::tr("Choose a captured source profile before setting overrides.")); }
            if ui.add_enabled(enabled && group["available"].as_bool() == Some(true) && group["rule"].is_object(),
                egui::Button::new(crate::localization::tr("Restore profile assignment"))).clicked() {
                actions.push(UiAction::CdmwCommand { command: "replacement_physics_profile",
                    arguments: json!({"group_id": group["id"], "reset": true}), label: "Restore physics profile" });
            }
            ui.small(crate::localization::tr("Raw profile values. Saved with Build Mod and drafts; Apply and Restore support Undo."));
            ui.small(crate::localization::tr("Gravity: negative pulls down; positive lifts up."));
            ui.small(crate::localization::tr("Build Mod includes a cloned profile, the profile catalogue and this variant's assignment. Profile edits do not create cloth guides or physics/bone bindings."));
        });
    }

    pub(crate) fn draw(
        ui: &mut egui::Ui,
        state: &Value,
        parts: &[Value],
        view: &mut ProfileView,
        settings: &mut Settings,
        can_apply: bool,
        rotation_available: bool,
        spline_available: bool,
        actions: &mut Vec<UiAction>,
        can_author: bool,
    ) -> bool {
        let source = json!([state["source"], state["sidecar_sha256"]]);
        if view.source != source {
            view.source = source;
            view.variant = None;
            view.edit_group = None;
            view.edit_source = None;
            view.edit_key = Value::Null;
            view.edit_values.clear();
        }
        let mut changed = false;
        // Also run while collapsed: changing part/sources must not leave a preset
        // from another assignment driving the newly selected preview.
        let selection_key = |variant: &Option<String>| {
            json!([
                state,
                parts.iter().map(|part| &part["index"]).collect::<Vec<_>>(),
                variant
            ])
        };
        let key = selection_key(&view.variant);
        if let Some((previous, manual)) =
            view.loaded.clone().filter(|(previous, _)| *previous != key)
        {
            // A saved edit to the same selected assignment refreshes the preset.
            // A different model, part selection or variant restores manual values.
            let preset = (previous[1] == key[1]
                && previous[2] == key[2]
                && state["available"].as_bool() == Some(true)
                && state["reason"].as_str().is_none_or(str::is_empty)
                && previous[0]["source"] == state["source"]
                && previous[0]["sidecar_sha256"] == state["sidecar_sha256"])
                .then(|| assigned_profile(state, parts, view.variant.as_deref()).ok())
                .flatten()
                .and_then(|profile| Preset::read(&profile["preview"]))
                .filter(|preset| !preset.spline || spline_available);
            if let Some(preset) = preset {
                let current = assigned_profile(state, parts, view.variant.as_deref()).ok();
                let old = assigned_profile(&previous[0], parts, view.variant.as_deref()).ok();
                if current != old {
                    preset.apply(settings, if preset.spline { spline_available } else { rotation_available });
                    changed = true;
                }
                view.loaded = Some((key, manual));
            } else {
                changed |= restore_manual(view, settings, rotation_available, spline_available);
            }
        }
        crate::localization::collapsing("Authored physics profile").show(ui, |ui| {
            if state["available"].as_bool() != Some(true) {
                ui.small(crate::localization::tr(state["reason"].as_str().unwrap_or("Exact physics profiles are unavailable.")));
                return;
            }
            if let Some(reason) = state["reason"].as_str().filter(|reason| !reason.is_empty()) {
                ui.small(crate::localization::tr(reason));
            }
            let geometry = &state["cloth_geometry"];
            match geometry["status"].as_str() {
                Some("available") => {
                    if let (Some(count), Some(fixed)) = (geometry["guide_count"].as_u64(), geometry["fixed_count"].as_u64()) {
                        ui.small(crate::localization::tr(format!("Authored cloth guides: {count} ({fixed} fixed)")));
                    }
                }
                Some("absent") => { ui.small(crate::localization::tr("This model has no authored cloth guides. Profile edits do not add cloth or bone jiggle.")); }
                Some("unsupported") => {
                    ui.small(crate::localization::tr("Cloth guide data could not be decoded; its availability is unknown."))
                        .on_hover_text(crate::localization::tr(geometry["reason"].as_str().unwrap_or_default()));
                }
                _ => {}
            }
            ui.small(crate::localization::tr("Profile variant (preview and mod edit)"));
            ui.horizontal_wrapped(|ui| {
                for variant in state["variants"].as_array().into_iter().flatten().filter_map(Value::as_str) {
                    let label = if variant.is_empty() { "Default variant".to_owned() } else { format!("Variant {variant}") };
                    if ui.add(egui::Button::new(crate::localization::tr(label)).selected(view.variant.as_deref() == Some(variant))).clicked()
                        && view.variant.as_deref() != Some(variant) {
                        changed |= restore_manual(view, settings, rotation_available, spline_available);
                        view.variant = Some(variant.to_owned());
                    }
                }
            });
            if let Some(variant) = view.variant.as_deref() {
                for part in parts {
                    let row = state["parts"].as_array().and_then(|rows| rows.iter().find(|row| row["index"] == part["index"]));
                    let bindings = row.and_then(|row| row["bindings"].as_array());
                    let assignments = bindings.into_iter().flatten()
                        .filter(|binding| binding["variant"].as_str() == Some(variant))
                        .map(|binding| binding["profile"].as_str().filter(|name| !name.is_empty()).unwrap_or("None (explicit empty)"))
                        .collect::<Vec<_>>();
                    let name = part["name"].as_str().unwrap_or("Part");
                    ui.small(crate::localization::tr(format!("{name}: {}", if assignments.is_empty() { "Unassigned".to_owned() } else { assignments.join(", ") })));
                }
            }
            draw_authoring(ui, state, view, actions, can_author);
            let profile = match assigned_profile(state, parts, view.variant.as_deref()) {
                Ok(profile) => profile,
                Err(reason) => { ui.small(crate::localization::tr(reason)); return; }
            };
            ui.small(crate::localization::tr(profile["path"].as_str().unwrap_or_default()))
                .on_hover_text(crate::localization::tr(format!("SHA-256: {}", profile["sha256"].as_str().unwrap_or_default())));
            let Some(preset) = Preset::read(&profile["preview"]) else {
                ui.small(crate::localization::tr(profile["reason"].as_str().filter(|reason| !reason.is_empty()).unwrap_or("Profile values are unsupported by the cloth preview.")));
                return;
            };
            ui.small(crate::localization::tr(format!("Stretch {} → {:.4} · bend {} → {:.4}",
                profile["authored"]["stretchingstiffness"].as_str().unwrap_or("?"), preset.stretch,
                profile["authored"]["bendingstiffness"].as_str().unwrap_or("?"), preset.bend)));
            if preset.spline {
                ui.small(crate::localization::tr(format!("Spring-back {} → {:.4}",
                    profile["authored"]["restoreanglestiffness"].as_str().unwrap_or("?"), preset.restore_angle)));
                if !spline_available {
                    ui.small(crate::localization::tr("Spline preview needs complete ordered guide chains with fixed roots."));
                }
            }
            if ui.add_enabled(can_apply && (!preset.spline || spline_available), egui::Button::new(crate::localization::tr("Use profile in preview"))).clicked() {
                let manual = view.loaded.as_ref().map(|(_, manual)| *manual).unwrap_or(*settings);
                view.loaded = Some((selection_key(&view.variant), manual));
                preset.apply(settings, if preset.spline { spline_available } else { rotation_available });
                changed = true;
            }
            if view.loaded.is_some() {
                ui.small(crate::localization::tr("Profile starting values loaded. Preview sliders can adjust them."));
                if ui.button(crate::localization::tr("Restore manual preview settings")).clicked() {
                    changed |= restore_manual(view, settings, rotation_available, spline_available);
                }
            }
            if preset.rotate_guides && !(if preset.spline { spline_available } else { rotation_available }) {
                ui.small(crate::localization::tr("Guide rotation cannot be applied without orientation neighbors."));
            }
            ui.small(crate::localization::tr("Loads gravity, damping, stretch, bend, spline spring-back, iterations, vertex alpha and supported guide rotation. Saved edits refresh a loaded profile."));
            ui.small(crate::localization::tr("Uses decoded initial stiffness conversion and a fixed preview clock. Other profile settings and live game activation are not reproduced. Changes are preview-only."));
        });
        changed
    }
}

use super::*;
use crate::cdmw_ui::{state_bool, state_str, state_u64};

pub(super) fn physics_badge(part: &Value) -> String {
    let label = match part["kind"].as_str() {
        Some("spline") => crate::localization::tr("Spline"),
        Some("cloth") => crate::localization::tr("Cloth"),
        Some("guide") => crate::localization::tr("Guide bindings"),
        Some("jiggle") => crate::localization::tr("Jiggle contribution"),
        Some("none") => crate::localization::tr("No guide or jiggle bindings"),
        _ => crate::localization::tr("Unknown physics"),
    };
    if part["kind"] != "jiggle"
        && part["jiggle_counts"].as_array().is_some_and(|counts| {
            counts.iter().any(|count| count.as_u64().is_some_and(|value| value > 0))
        })
    {
        crate::localization::tr(format!("{} + jiggle", label))
    } else {
        label
    }
}

pub(super) fn physics_lines(part: &Value) -> Vec<String> {
    let mut lines = vec![crate::localization::tr(format!("Physics: {}", physics_badge(part)))];
    let guides = part["guide_counts"].as_array();
    let vertices = part["vertex_counts"][0].as_u64().unwrap_or(0);
    let source_guides = part["guide_counts"][0].as_u64().unwrap_or(0);
    if guides.is_some_and(|counts| counts.iter().any(|count| count.as_u64().is_some_and(|value| value > 0))) {
        lines.push(crate::localization::tr(format!("{} / {} source vertices use guides", source_guides, vertices)));
        if let Some(counts) = guides.filter(|counts| counts.len() > 1) {
            let counts = counts.iter().map(|count| count.as_u64().unwrap_or(0).to_string()).collect::<Vec<_>>().join(" / ");
            lines.push(crate::localization::tr(format!("Guide vertices by LOD: {}", counts)));
        }
        if part["guides"]["status"] == "available" {
            lines.push(crate::localization::tr(format!("Guides: {} · fixed anchors: {}",
                state_u64(&part["guides"], "guide_count"), state_u64(&part["guides"], "fixed_count"))));
        }
        if let Some(current) = part["current_guide_count"].as_u64()
            && current != source_guides
        {
            lines.push(crate::localization::tr(format!("Current edit: {} guide vertices", current)));
        }
    }
    let source_jiggle = part["jiggle_counts"][0].as_u64().unwrap_or(0);
    if source_jiggle > 0 {
        lines.push(crate::localization::tr(format!("{} / {} source vertices have jiggle contribution", source_jiggle, vertices)));
        if let Some(current) = part["current_jiggle_count"].as_u64()
            && current != source_jiggle
        {
            lines.push(crate::localization::tr(format!("Current edit: {} jiggle vertices", current)));
        }
    }
    if part["mode_source"] == "pac_default" {
        lines.push(crate::localization::tr("Mode comes from the PAC default; the exact profile assignment is unknown."));
    }
    if let Some(profiles) = part["profiles"].as_array() {
        for profile in profiles {
            let variant = state_str(profile, "variant").unwrap_or("?");
            let name = state_str(profile, "profile").unwrap_or_default();
            lines.push(if name.is_empty() {
                crate::localization::tr(format!("Variant {}: no profile assigned", variant))
            } else {
                let mode = state_str(profile, "mode").filter(|mode| !mode.is_empty())
                    .map(crate::localization::tr).unwrap_or_else(|| crate::localization::tr("Unresolved"));
                crate::localization::tr(format!("Variant {}: {} ({})", variant, name, mode))
            });
        }
    }
    for key in ["reason", "preview_reason"] {
        if let Some(reason) = state_str(part, key).filter(|reason| !reason.is_empty()) {
            lines.push(match reason {
                "guide_mesh_missing" => crate::localization::tr("Render guide bindings exist, but their guide mesh is missing."),
                "guide_indices_out_of_range" => crate::localization::tr("Render guide bindings refer outside the decoded guide mesh."),
                "profile_assignment_missing" => crate::localization::tr("No exact profile assignment is available; this is the PAC default."),
                "profile_assignment_unresolved" => crate::localization::tr("The assigned physics profile is unresolved or ambiguous."),
                "profile_assignment_empty" => crate::localization::tr("No named physics profile is assigned for these variants."),
                "profile_modes_mixed" => crate::localization::tr("Physics mode varies by variant."),
                "profile_mode_unsupported" => crate::localization::tr("The assigned profile does not select cloth or spline simulation."),
                "spline_preview_approximate" => crate::localization::tr("Controlled spline preview approximates game motion."),
                _ => crate::localization::tr(reason),
            });
        }
    }
    lines
}

pub(super) struct ClothView {
    pub selected_only: bool,
    pub amount_percent: f64,
    pub use_height: bool,
    pub height: f64,
    pub fade: f64,
    pub profiles: profiles::ProfileView,
    pub guides: authoring::GuideView,
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
            profiles: profiles::ProfileView::default(),
            guides: authoring::GuideView::default(),
            key: Value::Null,
        }
    }
}

impl LabApplication {
    pub(super) fn draw_cdmw_physics_detection(&self, ui: &mut egui::Ui, indices: &[u32]) {
        let rows: Vec<_> = self.cdmw_state["physics"]["parts"].as_array().into_iter().flatten()
            .filter(|part| indices.contains(&(state_u64(part, "index") as u32))).collect();
        if rows.is_empty() { return; }
        crate::localization::collapsing("Detected physics")
            .id_salt(ui.id().with("detected-physics")).default_open(true).show(ui, |ui| {
                for part in &rows {
                    if rows.len() > 1 { ui.strong(state_str(part, "name").unwrap_or_default()); }
                    for line in physics_lines(part) { ui.small(line); }
                }
            });
    }

    pub(super) fn draw_cdmw_cloth_page(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let cloth = self.cdmw_state["cloth"].clone();
        let inspected = if self.cdmw_cloth.selected_only { self.selected_part_indices() } else {
            cloth["parts"].as_array().into_iter().flatten()
                .filter(|part| state_bool(part, "included")).map(|part| state_u64(part, "index") as u32).collect()
        };
        self.draw_cdmw_physics_detection(ui, &inspected);
        self.draw_cdmw_guide_authoring(ui, actions);
        ui.small(crate::localization::tr("Fixed vertices follow the skeleton. Cloth amount edits retained bindings."));
        if !state_bool(&cloth, "available") {
            ui.label(crate::localization::tr(state_str(&cloth, "reason").unwrap_or("Cloth influence is unavailable.")));
            let parts = self.cdmw_state["replacement"]["parts"].as_array().cloned().unwrap_or_default();
            let can_author = !self.cdmw_busy() && state_bool(&self.cdmw_state, "authoring_enabled");
            profiles::draw(ui, &self.cdmw_state["physics_profiles"], &parts,
                &mut self.cdmw_cloth.profiles, &mut self.cdmw_jiggle.preview.cloth_settings, false, false, false, actions, can_author);
            return;
        }
        ui.checkbox(&mut self.cdmw_cloth.selected_only, crate::localization::tr("Selected parts only"));
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
            ui.label(crate::localization::tr("Select an included part with cloth bindings."));
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
        ui.small(crate::localization::tr(format!(
            "{} parts · applies to all {} LODs",
            parts.len(),
            state_u64(&cloth, "lod_count")
        )));
        if mixed {
            ui.small(crate::localization::tr("Mixed saved settings. Apply replaces them for these parts."));
        }
        ui.add(
            crate::cdmw_ui::numeric::slider(&mut self.cdmw_cloth.amount_percent, 0.0..=100.0)
                .text(crate::localization::tr("Cloth amount")),
        );
        ui.checkbox(&mut self.cdmw_cloth.use_height, crate::localization::tr("Fix vertices above height"));
        if self.cdmw_cloth.use_height {
            ui.horizontal(|ui| {
                ui.label(crate::localization::tr("Height (Y)"));
                ui.add(crate::cdmw_ui::numeric::value(&mut self.cdmw_cloth.height).speed(0.01));
            });
            ui.horizontal(|ui| {
                ui.label(crate::localization::tr("Fade below height"));
                ui.add(
                    crate::cdmw_ui::numeric::value(&mut self.cdmw_cloth.fade)
                        .range(0.0..=f64::MAX)
                        .speed(0.01),
                );
            });
            ui.small(crate::localization::tr("Uses displayed model coordinates. Higher vertices stay fixed; lower vertices move."));
        }
        if ui.button(crate::localization::tr("Apply cloth settings")).clicked() {
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
            if ui.button(crate::localization::tr("Disable cloth")).clicked() {
                actions.push(UiAction::CdmwCommand {
                    command: "replacement_cloth",
                    arguments: json!({"part_ids": ids, "rule": {"amount": 0.0, "fixed_above": null, "fade": 0.0}}),
                    label: "Disable cloth influence",
                });
            }
            if ui.add_enabled(parts.iter().any(|part| !part["rule"].is_null()), egui::Button::new(crate::localization::tr("Restore cloth"))).clicked() {
                actions.push(UiAction::CdmwCommand {
                    command: "replacement_cloth",
                    arguments: json!({"part_ids": ids, "reset": true}),
                    label: "Restore cloth influence",
                });
            }
        });
        ui.small(crate::localization::tr("Saved with Build PAC and drafts. Preview simulation remains approximate."));
        self.draw_cloth_preview_controls(ui, &parts, actions);
        self.draw_cloth_collision_inputs(ui, actions);
    }
}
