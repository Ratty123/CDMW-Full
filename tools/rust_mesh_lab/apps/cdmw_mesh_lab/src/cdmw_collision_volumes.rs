//! Collision shapes: resize, move, copy and remove the volumes cloth collides with.
//!
//! The host decodes each source (the PAC's own set, or a body/head PABV loaded as a
//! collision input from the game archives) and owns the edit, its Undo entry and
//! the output. This view keeps an unsaved draft of the values and sends the
//! differences from the source as one explicit command.

use super::*;
use crate::cdmw_ui::state_bool;

#[derive(Clone, Debug, PartialEq)]
pub(super) struct VolumeDraft {
    pub parameters: Vec<f64>,
    pub position: [f64; 3],
    pub removed: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub(super) struct CopyDraft {
    pub template: usize,
    pub parameters: Vec<f64>,
    pub position: [f64; 3],
}

#[derive(Default)]
pub(super) struct CollisionView {
    pub source: Option<String>,
    pub selected: Option<Selection>,
    pub volumes: Vec<VolumeDraft>,
    pub copies: Vec<CopyDraft>,
    pub scale: f64,
    key: Value,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Selection {
    Volume(usize),
    Copy(usize),
}

fn numbers(value: &Value) -> Vec<f64> {
    value.as_array().into_iter().flatten().filter_map(Value::as_f64).collect()
}

fn position(value: &Value) -> [f64; 3] {
    let values = numbers(value);
    [values.first().copied().unwrap_or(0.0), values.get(1).copied().unwrap_or(0.0),
     values.get(2).copied().unwrap_or(0.0)]
}

/// Draft values from the source rows and the saved edit, if any.
pub(super) fn draft_from(source: &Value) -> (Vec<VolumeDraft>, Vec<CopyDraft>) {
    let rows = source["rows"].as_array().map(Vec::as_slice).unwrap_or(&[]);
    let mut volumes: Vec<VolumeDraft> = rows.iter().map(|row| VolumeDraft {
        parameters: numbers(&row["parameters"]), position: position(&row["position"]), removed: false,
    }).collect();
    let edit = &source["edit"];
    for change in edit["changes"].as_array().into_iter().flatten() {
        let Some(volume) = change["ordinal"].as_u64().and_then(|i| volumes.get_mut(i as usize)) else { continue };
        volume.removed = change["removed"].as_bool().unwrap_or(false);
        if change["parameters"].is_array() { volume.parameters = numbers(&change["parameters"]); }
        if change["position"].is_array() { volume.position = position(&change["position"]); }
    }
    let copies = edit["copies"].as_array().into_iter().flatten().filter_map(|copy| {
        let template = copy["template"].as_u64()? as usize;
        let base = volumes.get(template)?;
        let base_row = rows.get(template)?;
        Some(CopyDraft {
            template,
            parameters: if copy["parameters"].is_array() { numbers(&copy["parameters"]) } else { numbers(&base_row["parameters"]) },
            position: if copy["position"].is_array() { position(&copy["position"]) } else { base.position },
        })
    }).collect();
    (volumes, copies)
}

fn same(a: &[f64], b: &[f64]) -> bool {
    a.len() == b.len() && a.iter().zip(b).all(|(x, y)| (x - y).abs() <= 1e-7 * x.abs().max(y.abs()).max(1.0))
}

/// The command arguments: only what differs from the source rows.
pub(super) fn edit_arguments(source: &Value, volumes: &[VolumeDraft], copies: &[CopyDraft]) -> Value {
    let rows = source["rows"].as_array().map(Vec::as_slice).unwrap_or(&[]);
    let mut changes = Vec::new();
    for (ordinal, (row, draft)) in rows.iter().zip(volumes).enumerate() {
        if draft.removed {
            changes.push(json!({"ordinal": ordinal, "removed": true, "parameters": null, "position": null}));
            continue;
        }
        let parameters = (!same(&draft.parameters, &numbers(&row["parameters"]))).then(|| json!(draft.parameters));
        let moved = (!same(&draft.position, &position(&row["position"]))).then(|| json!(draft.position));
        if parameters.is_some() || moved.is_some() {
            changes.push(json!({"ordinal": ordinal, "removed": false, "parameters": parameters, "position": moved}));
        }
    }
    let copies = copies.iter().map(|copy| json!({
        "template": copy.template, "parameters": copy.parameters, "position": copy.position,
    })).collect::<Vec<_>>();
    json!({"source": source["source"], "changes": changes, "copies": copies})
}

fn size_labels(shape: &str) -> &'static [&'static str] {
    match shape {
        "sphere" => &["Radius"],
        "capsule" | "cylinder" => &["Radius", "Height"],
        "box" => &["Depth (Z)", "Width (X)", "Height (Y)"],
        _ => &[],
    }
}

fn source_label(source: &Value) -> String {
    let path = source["source"].as_str().unwrap_or_default();
    let file = path.rsplit(['/', '\\']).next().unwrap_or(path);
    match source["role"].as_str() {
        Some("model") => crate::localization::tr("This model's shapes"),
        Some("body") => crate::localization::tr(format!("Body: {file}")),
        Some("head") => crate::localization::tr(format!("Head: {file}")),
        _ => crate::localization::tr(format!("Saved: {file}")),
    }
}

fn row_label(row: &Value, index: usize) -> String {
    let shape = crate::localization::tr(match row["shape"].as_str() {
        Some("sphere") => "Sphere", Some("capsule") => "Capsule", Some("cylinder") => "Cylinder",
        Some("box") => "Box", _ => "Mesh",
    });
    let bone = row["bone"].as_str().filter(|bone| !bone.is_empty()).map(str::to_owned)
        .unwrap_or_else(|| format!("{:#010x}", row["bone_key"].as_u64().unwrap_or(0)));
    format!("{} · {shape} · {bone}", index + 1)
}

impl LabApplication {
    pub(super) fn draw_collision_volume_authoring(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let state = self.cdmw_state["collision_volumes"].clone();
        let sources = state["sources"].as_array().cloned().unwrap_or_default();
        let idle = !self.cdmw_busy();
        let authoring = idle && state_bool(&self.cdmw_state, "authoring_enabled");
        crate::localization::collapsing("Collision shapes").id_salt("Collision shapes (experimental)").show(ui, |ui| {
            if sources.is_empty() {
                ui.small(crate::localization::tr(state["reason"].as_str().filter(|r| !r.is_empty())
                    .unwrap_or("This model has no collision shapes. Load body or head volumes under Collision sources to edit them.")));
                return;
            }
            let view = &mut self.cdmw_collision;
            if view.source.as_ref().is_none_or(|current| !sources.iter().any(|s| s["source"].as_str() == Some(current))) {
                view.source = sources[0]["source"].as_str().map(str::to_owned);
            }
            ui.horizontal_wrapped(|ui| {
                for source in &sources {
                    let id = source["source"].as_str().unwrap_or_default();
                    let mut label = source_label(source);
                    if !source["edit"].is_null() { label.push_str(" *"); }
                    if ui.add(egui::Button::new(label).selected(view.source.as_deref() == Some(id)))
                        .on_hover_text(id).clicked() {
                        view.source = Some(id.to_owned());
                    }
                }
            });
            let Some(source) = sources.iter().find(|s| s["source"].as_str() == view.source.as_deref()).cloned() else { return };
            if state_bool(&source, "shared") {
                ui.small(crate::localization::tr("Every model on this body uses these volumes. Build Mod ships the edited file, which changes them all and conflicts with other mods that ship it."));
            }
            let key = json!([source["source"], source["sha256"], source["edit"]]);
            if view.key != key {
                view.key = key;
                (view.volumes, view.copies) = draft_from(&source);
                view.selected = None;
                view.scale = 1.0;
            }
            let rows = source["rows"].as_array().cloned().unwrap_or_default();
            let available = state_bool(&source, "available") && authoring;
            if let Some(reason) = source["reason"].as_str().filter(|r| !r.is_empty()) {
                ui.small(crate::localization::tr(reason));
            }
            egui::ScrollArea::vertical().id_salt("collision-volume-rows").max_height(160.0).show(ui, |ui| {
                for (index, row) in rows.iter().enumerate() {
                    let removed = view.volumes.get(index).is_some_and(|v| v.removed);
                    let mut text = egui::RichText::new(row_label(row, index));
                    if removed { text = text.strikethrough().weak(); }
                    if ui.add(egui::Button::new(text).selected(view.selected == Some(Selection::Volume(index)))).clicked() {
                        view.selected = Some(Selection::Volume(index));
                    }
                }
                for (index, copy) in view.copies.iter().enumerate() {
                    let label = format!("+ {}", rows.get(copy.template).map(|row| row_label(row, copy.template)).unwrap_or_default());
                    if ui.add(egui::Button::new(label).selected(view.selected == Some(Selection::Copy(index)))).clicked() {
                        view.selected = Some(Selection::Copy(index));
                    }
                }
            });
            let shape_of = |template: usize| rows.get(template).and_then(|row| row["shape"].as_str()).unwrap_or("mesh").to_owned();
            match view.selected {
                Some(Selection::Volume(index)) if index < view.volumes.len() => {
                    let shape = shape_of(index);
                    let draft = &mut view.volumes[index];
                    ui.add_enabled_ui(!draft.removed, |ui| draw_values(ui, &shape, &mut draft.parameters, &mut draft.position));
                    ui.horizontal_wrapped(|ui| {
                        let label = if draft.removed { "Keep shape" } else { "Remove shape" };
                        if ui.add_enabled(available, egui::Button::new(crate::localization::tr(label))).clicked() {
                            draft.removed = !draft.removed;
                        }
                        if ui.add_enabled(available && !draft.removed, egui::Button::new(crate::localization::tr("Copy shape")))
                            .on_hover_text(crate::localization::tr("Adds a copy on the same bone. Move or resize it after copying.")).clicked() {
                            let copy = CopyDraft { template: index, parameters: draft.parameters.clone(), position: draft.position };
                            view.copies.push(copy);
                            view.selected = Some(Selection::Copy(view.copies.len() - 1));
                        }
                    });
                }
                Some(Selection::Copy(index)) if index < view.copies.len() => {
                    let shape = shape_of(view.copies[index].template);
                    let copy = &mut view.copies[index];
                    draw_values(ui, &shape, &mut copy.parameters, &mut copy.position);
                    if ui.add_enabled(available, egui::Button::new(crate::localization::tr("Delete copy"))).clicked() {
                        view.copies.remove(index);
                        view.selected = None;
                    }
                }
                _ => { ui.small(crate::localization::tr("Choose a shape to resize, move, copy or remove it.")); }
            }
            ui.horizontal(|ui| {
                ui.add(crate::cdmw_ui::numeric::value(&mut view.scale).range(0.05..=20.0).speed(0.01));
                if ui.add_enabled(available, egui::Button::new(crate::localization::tr("Scale all sizes")))
                    .on_hover_text(crate::localization::tr("Multiplies every shape's radius, height and box size; mesh shapes keep their size.")).clicked() {
                    let factor = view.scale;
                    for draft in view.volumes.iter_mut().filter(|draft| !draft.removed) {
                        draft.parameters.iter_mut().for_each(|value| *value = (*value * factor).clamp(1e-4, 100.0));
                    }
                    for copy in &mut view.copies {
                        copy.parameters.iter_mut().for_each(|value| *value = (*value * factor).clamp(1e-4, 100.0));
                    }
                }
            });
            let arguments = edit_arguments(&source, &view.volumes, &view.copies);
            let pending = arguments["changes"].as_array().is_some_and(|rows| !rows.is_empty())
                || arguments["copies"].as_array().is_some_and(|rows| !rows.is_empty());
            ui.horizontal_wrapped(|ui| {
                if ui.add_enabled(available && pending, egui::Button::new(crate::localization::tr("Apply shape edits")))
                    .on_hover_text(crate::localization::tr("Saved with Build Mod and drafts; Undo applies. The cloth preview uses the edited shapes.")).clicked() {
                    actions.push(UiAction::CdmwCommand { command: "replacement_collision_volumes", arguments,
                        label: "Edit collision shapes" });
                }
                if ui.add_enabled(idle && !source["edit"].is_null(),
                    egui::Button::new(crate::localization::tr("Restore source shapes"))).clicked() {
                    actions.push(UiAction::CdmwCommand { command: "replacement_collision_volumes",
                        arguments: json!({"source": source["source"], "reset": true}), label: "Restore collision shapes" });
                }
            });
        }).header_response
            .on_hover_text(crate::localization::tr("Resize, move, copy or remove the shapes cloth collides with. In-game collision with edited shapes is untested."));
    }
}

fn draw_values(ui: &mut egui::Ui, shape: &str, parameters: &mut [f64], position: &mut [f64; 3]) {
    for (value, label) in parameters.iter_mut().zip(size_labels(shape)) {
        ui.horizontal(|ui| {
            ui.label(crate::localization::tr(*label));
            ui.add(crate::cdmw_ui::numeric::value(value).range(0.0001..=100.0).speed(0.001));
        });
    }
    if shape == "mesh" {
        ui.small(crate::localization::tr("Mesh shapes can be moved, copied or removed, not resized."));
    }
    ui.horizontal(|ui| {
        ui.label(crate::localization::tr("Position"))
            .on_hover_text(crate::localization::tr("Centre in the bone's own space, in metres."));
        for value in position.iter_mut() {
            ui.add(crate::cdmw_ui::numeric::value(value).range(-1000.0..=1000.0).speed(0.001).compact_width(56.0));
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn source() -> Value {
        json!({"source": "model", "rows": [
            {"shape": "capsule", "parameters": [0.1, 0.4], "position": [0.0, 0.5, 0.0]},
            {"shape": "sphere", "parameters": [0.2], "position": [0.0, 1.6, 0.0]},
        ], "edit": null})
    }

    #[test]
    fn unchanged_draft_sends_nothing_and_changes_are_minimal() {
        let source = source();
        let (mut volumes, mut copies) = draft_from(&source);
        let empty = edit_arguments(&source, &volumes, &copies);
        assert_eq!(empty["changes"], json!([]));
        assert_eq!(empty["copies"], json!([]));
        volumes[0].parameters[0] = 0.05;
        volumes[1].removed = true;
        copies.push(CopyDraft { template: 0, parameters: vec![0.05, 0.4], position: [0.0, 0.2, 0.0] });
        let edit = edit_arguments(&source, &volumes, &copies);
        assert_eq!(edit["changes"], json!([
            {"ordinal": 0, "removed": false, "parameters": [0.05, 0.4], "position": null},
            {"ordinal": 1, "removed": true, "parameters": null, "position": null}]));
        assert_eq!(edit["copies"][0]["template"], json!(0));
    }

    #[test]
    fn saved_edit_round_trips_through_the_draft() {
        let mut source = source();
        source["edit"] = json!({"changes": [
            {"ordinal": 1, "removed": false, "parameters": null, "position": [0.0, 1.5, 0.1]}],
            "copies": [{"template": 0, "parameters": [0.08, 0.5], "position": [0.0, 0.2, 0.0]}]});
        let (volumes, copies) = draft_from(&source);
        assert_eq!(volumes[1].position, [0.0, 1.5, 0.1]);
        assert_eq!(copies.len(), 1);
        let edit = edit_arguments(&source, &volumes, &copies);
        assert_eq!(edit["changes"], source["edit"]["changes"]);
        assert_eq!(edit["copies"], source["edit"]["copies"]);
    }
}
