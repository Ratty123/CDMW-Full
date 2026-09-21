//! Edit existing cloth influence through the host's reversible PAC output path.
pub(crate) mod preview;
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
    }

    impl Preset {
        fn read(value: &Value) -> Option<Self> {
            let result: Self = serde_json::from_value(value.clone()).ok()?;
            ((-100.0..=100.0).contains(&result.gravity)
                && (0.0..=10.0).contains(&result.damping)
                && (0.0..=1.0).contains(&result.stretch)
                && (0.0..=1.0).contains(&result.bend)
                && (1..=8).contains(&result.iterations))
            .then_some(result)
        }

        fn apply(self, settings: &mut Settings, rotation_available: bool) {
            settings.gravity = self.gravity;
            settings.damping = self.damping;
            settings.stretch = self.stretch;
            settings.bend = self.bend;
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
    ) -> bool {
        if let Some((_, manual)) = view.loaded.take() {
            Preset::from(manual).apply(settings, rotation_available);
            return true;
        }
        false
    }

    fn source_key(source: &Value) -> String {
        json!([source["name"], source["path"], source["sha256"]]).to_string()
    }

    fn draw_collision_overrides(ui: &mut egui::Ui, source: &Value, view: &mut ProfileView) {
        ui.collapsing("Collision and attachment overrides", |ui| {
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
                        ui.checkbox(&mut overridden, format!("Override {label}"));
                        if overridden {
                            ui.checkbox(&mut value, "Enabled");
                            view.edit_values.insert(key.to_owned(), if value { 1.0 } else { 0.0 });
                        } else {
                            view.edit_values.remove(key);
                            ui.small(match (raw, original) {
                                (_, Some(0.0)) => "Disabled in source",
                                (_, Some(_)) => "Enabled in source",
                                (Some(_), None) => "Invalid source value",
                                (None, None) => "Source default",
                            });
                        }
                    });
                });
            }
            ui.small("Exports raw collision and attachment switches. The preview does not reproduce every game collision branch.");
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
        ui.collapsing("Edit profile for mod", |ui| {
            if groups.len() == 1 {
                view.edit_group = groups[0]["id"].as_str().map(str::to_owned);
            }
            if groups.len() > 1 {
                ui.horizontal_wrapped(|ui| {
                    for (index, group) in groups.iter().enumerate() {
                        let id = group["id"].as_str().unwrap_or_default();
                        if ui.add(egui::Button::new(format!("Profile group {}", index + 1))
                            .selected(view.edit_group.as_deref() == Some(id))).clicked() {
                            view.edit_group = Some(id.to_owned());
                        }
                    }
                });
            }
            let Some(group) = groups.iter().find(|group| group["id"].as_str() == view.edit_group.as_deref()) else {
                ui.small("Choose a profile group to edit."); return;
            };
            let names = group["names"].as_array().into_iter().flatten().filter_map(Value::as_str).collect::<Vec<_>>();
            ui.label(format!("Applies to all {} parts sharing this assignment", names.len()));
            ui.small(names.join(", "));
            if let Some(reason) = group["reason"].as_str().filter(|reason| !reason.is_empty()) { ui.small(reason); }
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
            egui::ComboBox::from_id_salt("physics-profile-source").selected_text(selected).show_ui(ui, |ui| {
                for source in sources {
                    ui.selectable_value(&mut view.edit_source, Some(source_key(source)),
                        source["name"].as_str().unwrap_or("Profile"));
                }
            });
            if previous != view.edit_source { view.edit_values.clear(); }
            let source = sources.iter().find(|source| Some(source_key(source)) == view.edit_source);
            if let Some(source) = source {
                for (key, label, low, high, integer) in [
                    ("StretchingStiffness", "Stretch stiffness", 0.0, 1.0, false),
                    ("BendingStiffness", "Bend stiffness", 0.0, 1.0, false),
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
                        ui.checkbox(&mut overridden, format!("Override {label}"));
                        if overridden {
                            let mut control = egui::DragValue::new(&mut value).range(low..=high).speed(if integer { 1.0 } else { 0.01 });
                            if integer { control = control.max_decimals(0); }
                            ui.add(control);
                            // Invalid text entered into a numeric control must
                            // never serialize as a null/nonfinite raw override.
                            value = if value.is_finite() { value.clamp(low, high) } else { low };
                            if integer { value = value.round(); }
                            view.edit_values.insert(key.to_owned(), value);
                        } else {
                            view.edit_values.remove(key);
                            ui.small(match (raw, original) {
                                (Some(text), Some(_)) => text,
                                (Some(_), None) => "Invalid source value",
                                (None, _) => "Source default",
                            });
                        }
                    });
                }
                draw_collision_overrides(ui, source, view);
                if ui.add_enabled(enabled && group["available"].as_bool() == Some(true) && !view.edit_values.is_empty(),
                    egui::Button::new("Apply profile edit")).clicked() {
                    actions.push(UiAction::CdmwCommand {
                        command: "replacement_physics_profile",
                        arguments: json!({"group_id": group["id"], "rule": {
                            "variant": variant, "source_profile": source["name"], "source_path": source["path"],
                            "source_sha256": source["sha256"], "values": view.edit_values}}), label: "Edit physics profile",
                    });
                }
            } else { ui.small("Choose a captured source profile before setting overrides."); }
            if ui.add_enabled(enabled && group["available"].as_bool() == Some(true) && group["rule"].is_object(),
                egui::Button::new("Restore profile assignment")).clicked() {
                actions.push(UiAction::CdmwCommand { command: "replacement_physics_profile",
                    arguments: json!({"group_id": group["id"], "reset": true}), label: "Restore physics profile" });
            }
            ui.small("Raw profile values. Saved with Build Mod and drafts; Apply and Restore support Undo.");
            ui.small("Gravity: negative pulls down; positive lifts up.");
            ui.small("Build Mod includes a cloned profile, the profile catalogue and this variant's assignment. Profile edits do not create cloth guides or physics/bone bindings.");
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
        if view
            .loaded
            .as_ref()
            .is_some_and(|(key, _)| *key != selection_key(&view.variant))
        {
            changed |= restore_manual(view, settings, rotation_available);
        }
        ui.collapsing("Authored cloth profile", |ui| {
            if state["available"].as_bool() != Some(true) {
                ui.small(state["reason"].as_str().unwrap_or("Exact physics profiles are unavailable."));
                return;
            }
            if let Some(reason) = state["reason"].as_str().filter(|reason| !reason.is_empty()) {
                ui.small(reason);
            }
            let geometry = &state["cloth_geometry"];
            match geometry["status"].as_str() {
                Some("available") => {
                    if let (Some(count), Some(fixed)) = (geometry["guide_count"].as_u64(), geometry["fixed_count"].as_u64()) {
                        ui.small(format!("Authored cloth guides: {count} ({fixed} fixed)"));
                    }
                }
                Some("absent") => { ui.small("This model has no authored cloth guides. Profile edits do not add cloth or bone jiggle."); }
                Some("unsupported") => {
                    ui.small("Cloth guide data could not be decoded; its availability is unknown.")
                        .on_hover_text(geometry["reason"].as_str().unwrap_or_default());
                }
                _ => {}
            }
            ui.small("Profile variant (preview and mod edit)");
            ui.horizontal_wrapped(|ui| {
                for variant in state["variants"].as_array().into_iter().flatten().filter_map(Value::as_str) {
                    let label = if variant.is_empty() { "Default variant".to_owned() } else { format!("Variant {variant}") };
                    if ui.add(egui::Button::new(label).selected(view.variant.as_deref() == Some(variant))).clicked()
                        && view.variant.as_deref() != Some(variant) {
                        changed |= restore_manual(view, settings, rotation_available);
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
                    ui.small(format!("{name}: {}", if assignments.is_empty() { "Unassigned".to_owned() } else { assignments.join(", ") }));
                }
            }
            draw_authoring(ui, state, view, actions, can_author);
            let profile = match assigned_profile(state, parts, view.variant.as_deref()) {
                Ok(profile) => profile,
                Err(reason) => { ui.small(reason); return; }
            };
            ui.small(profile["path"].as_str().unwrap_or_default())
                .on_hover_text(format!("SHA-256: {}", profile["sha256"].as_str().unwrap_or_default()));
            let Some(preset) = Preset::read(&profile["preview"]) else {
                ui.small(profile["reason"].as_str().filter(|reason| !reason.is_empty()).unwrap_or("Profile values are unsupported by the cloth preview."));
                return;
            };
            ui.small(format!("Stretch {} → {:.4} · bend {} → {:.4}",
                profile["authored"]["stretchingstiffness"].as_str().unwrap_or("?"), preset.stretch,
                profile["authored"]["bendingstiffness"].as_str().unwrap_or("?"), preset.bend));
            if ui.add_enabled(can_apply, egui::Button::new("Use profile in preview")).clicked() {
                let manual = view.loaded.as_ref().map(|(_, manual)| *manual).unwrap_or(*settings);
                view.loaded = Some((selection_key(&view.variant), manual));
                preset.apply(settings, rotation_available);
                changed = true;
            }
            if view.loaded.is_some() {
                ui.small("Profile starting values loaded. Preview sliders can adjust them.");
                if ui.button("Restore manual preview settings").clicked() {
                    changed |= restore_manual(view, settings, rotation_available);
                }
            }
            if preset.rotate_guides && !rotation_available {
                ui.small("Guide rotation cannot be applied without orientation neighbors.");
            }
            ui.small("Loads gravity, damping, stretch, bend, iterations, vertex alpha and supported guide rotation only.");
            ui.small("Uses decoded initial stiffness conversion and a fixed preview clock. Other profile settings and live game activation are not reproduced. Changes are preview-only.");
        });
        changed
    }
}

use super::*;
use crate::cdmw_ui::{state_bool, state_str, state_u64};

pub(super) struct ClothView {
    pub selected_only: bool,
    pub amount_percent: f64,
    pub use_height: bool,
    pub height: f64,
    pub fade: f64,
    pub profiles: profiles::ProfileView,
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
            key: Value::Null,
        }
    }
}

impl LabApplication {
    pub(super) fn draw_cdmw_cloth_page(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let cloth = self.cdmw_state["cloth"].clone();
        ui.small("Fixed vertices follow the skeleton. Existing cloth bindings only.");
        if !state_bool(&cloth, "available") {
            ui.label(state_str(&cloth, "reason").unwrap_or("Cloth influence is unavailable."));
            let parts = self.cdmw_state["replacement"]["parts"].as_array().cloned().unwrap_or_default();
            let can_author = !self.cdmw_busy() && state_bool(&self.cdmw_state, "authoring_enabled");
            profiles::draw(ui, &self.cdmw_state["physics_profiles"], &parts,
                &mut self.cdmw_cloth.profiles, &mut self.cdmw_jiggle.preview.cloth_settings, false, false, actions, can_author);
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
        self.draw_cloth_preview_controls(ui, &parts, actions);
        self.draw_cloth_collision_inputs(ui, actions);
    }
}
