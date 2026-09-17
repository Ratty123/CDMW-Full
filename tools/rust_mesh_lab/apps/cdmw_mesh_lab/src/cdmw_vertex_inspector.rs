//! Host-authoritative, selection-bound vertex inspection and staged editing.

use super::*;
use egui::{Button, ComboBox, TextEdit};
use std::time::Duration;

pub(super) const CAPABILITY: &str = "vertex_parameters_v1";

#[derive(Default)]
pub(super) struct VertexInspector {
    pub open: bool,
    reveal: bool,
    key: Value,
    changed_at: Option<Instant>,
    pending: Option<(u64, Value)>,
    pub data: Value,
    pub note: String,
    page: u64,
    row: usize,
    fetch: bool,
    pub draft: VertexDraft,
}

#[derive(Default)]
pub(super) struct VertexDraft {
    pub position: [String; 3],
    pub uv0: [String; 2],
    pub normal: [String; 3],
    pub position_offset: bool,
    pub uv_offset: bool,
    pub weight_enabled: bool,
    pub bone: Option<i64>,
    pub weight_mode: usize,
    pub weight: String,
}

impl VertexDraft {
    fn dirty(&self) -> bool {
        self.position
            .iter()
            .chain(&self.uv0)
            .chain(&self.normal)
            .any(|v| !v.trim().is_empty())
            || self.weight_enabled
    }

    pub(super) fn edits(&self) -> Result<Value, String> {
        let mut edits = serde_json::Map::new();
        for (channel, fields, offset) in [
            ("position", self.position.as_slice(), self.position_offset),
            ("uv0", self.uv0.as_slice(), self.uv_offset),
            ("normal", self.normal.as_slice(), false),
        ] {
            if fields.iter().all(|v| v.trim().is_empty()) {
                continue;
            }
            let values = fields
                .iter()
                .map(|text| {
                    if text.trim().is_empty() {
                        return Ok(Value::Null);
                    }
                    let number: f64 = text
                        .trim()
                        .parse()
                        .map_err(|_| format!("Enter a number for {channel}."))?;
                    if !number.is_finite() {
                        return Err(format!("{channel} must be finite."));
                    }
                    Ok(json!(number))
                })
                .collect::<Result<Vec<_>, String>>()?;
            if channel == "normal" && values.iter().any(Value::is_null) {
                return Err("Enter all three components of the normal direction.".into());
            }
            edits.insert(
                channel.into(),
                json!({"mode": if offset { "offset" } else { "set" }, "values": values}),
            );
        }
        if self.weight_enabled {
            let mode = ["set", "offset", "remove", "normalize"]
                .get(self.weight_mode)
                .ok_or("Invalid weight operation.")?;
            if self.bone.is_none() && *mode != "normalize" {
                return Err("Choose a resolved bone.".into());
            }
            let value = if matches!(*mode, "set" | "offset") {
                let value: f64 = self
                    .weight
                    .trim()
                    .parse()
                    .map_err(|_| "Enter a bone influence.")?;
                if !value.is_finite() {
                    return Err("Bone influence must be finite.".into());
                }
                json!(value)
            } else {
                Value::Null
            };
            edits.insert(
                "weights".into(),
                json!({"mode":mode,"bone":self.bone,"value":value}),
            );
        }
        if edits.is_empty() {
            return Err("Enter one or more changes first.".into());
        }
        Ok(Value::Object(edits))
    }
}

impl VertexInspector {
    pub(super) fn clear_draft(&mut self) {
        let batch = self.data["count"].as_u64().unwrap_or(0) > 1;
        self.draft = VertexDraft {
            position_offset: batch,
            uv_offset: batch,
            ..VertexDraft::default()
        };
    }

    fn invalidate(&mut self, key: Value) {
        if self.draft.dirty() {
            self.note = "Selection or mesh changed. Pending inputs were discarded.".into();
        }
        self.data = Value::Null;
        self.clear_draft();
        self.key = key;
        self.page = 0;
        self.row = 0;
        self.fetch = true;
        self.changed_at = Some(Instant::now());
    }
}

impl LabApplication {
    pub(super) fn reveal_vertex_parameters(&mut self, context: &egui::Context) {
        crate::cdmw_ui::set_cdmw_sidebar_expanded(
            context,
            crate::cdmw_ui::CDMW_INSPECTOR_SIDEBAR,
            true,
        );
        self.vertex_inspector.reveal = true;
        self.vertex_inspector.open = true;
        self.vertex_inspector.fetch = true;
    }

    fn vertex_token(&self) -> Value {
        json!({"session_id": self.cdmw_state["session_id"], "mesh_revision": self.cdmw_state["base_revision"],
            "selection_revision":self.cdmw_state["selection_revision"],"topology_generation":self.cdmw_state["topology_generation"]})
    }

    fn vertex_key(&self) -> Value {
        json!([
            self.vertex_token(),
            self.mesh.as_ref().map(|m| (
                m.topology_generation,
                m.geometry_revision,
                m.selection_revision
            ))
        ])
    }

    fn cancel_vertex_inspection(&mut self) {
        if self.vertex_inspector.pending.take().is_some() {
            self.vertex_inspector.fetch = true;
            if let Some(bridge) = &mut self.cdmw_bridge {
                let _ = bridge.submit_vertex_inspect(Value::Null, true);
            }
        }
    }

    pub(super) fn tick_vertex_inspector(&mut self, visible: bool) {
        let key = self.vertex_key();
        if self.vertex_inspector.key != key {
            self.cancel_vertex_inspection();
            self.vertex_inspector.invalidate(key);
        }
        let available =
            self.cdmw_state["vertex_parameters"]["capability"].as_str() == Some(CAPABILITY);
        if !visible
            || !self.vertex_inspector.open
            || !available
            || self.cdmw_busy()
            || self.hair.active()
        {
            self.cancel_vertex_inspection();
            return;
        }
        if !self.vertex_inspector.fetch || self.vertex_inspector.pending.is_some() {
            return;
        }
        if self
            .vertex_inspector
            .changed_at
            .is_some_and(|at| at.elapsed() < Duration::from_millis(160))
        {
            self.egui_context
                .request_repaint_after(Duration::from_millis(160));
            return;
        }
        let arguments =
            json!({"token":self.vertex_token(),"page":self.vertex_inspector.page,"page_size":128});
        if let Some(bridge) = &mut self.cdmw_bridge {
            match bridge.submit_vertex_inspect(arguments, false) {
                Ok(id) => {
                    self.vertex_inspector.pending = Some((id, self.vertex_inspector.key.clone()));
                    self.vertex_inspector.fetch = false;
                }
                Err(error) => {
                    self.vertex_inspector.note = error.to_string();
                    self.vertex_inspector.fetch = false;
                }
            }
        }
    }

    pub(super) fn accept_vertex_inspection(
        &mut self,
        request_id: u64,
        ok: bool,
        payload: Value,
        error: String,
    ) {
        let key = self.vertex_key();
        let Some((expected, pending_key)) = &self.vertex_inspector.pending else {
            return;
        };
        if request_id != *expected {
            return;
        }
        let current = *pending_key == key && self.vertex_inspector.open && !self.cdmw_busy();
        self.vertex_inspector.pending = None;
        if !current {
            return;
        }
        if !ok {
            self.vertex_inspector.note = error;
            return;
        }
        if payload["token"] != self.vertex_token()
            || payload["rows"]
                .as_array()
                .is_none_or(|rows| rows.len() > 128)
        {
            self.vertex_inspector.note = "The vertex inspection reply is stale or invalid.".into();
            return;
        }
        let first = self.vertex_inspector.data.is_null();
        self.vertex_inspector.page = payload["page"].as_u64().unwrap_or(0);
        self.vertex_inspector.data = payload;
        self.vertex_inspector.row = 0;
        if first {
            self.vertex_inspector.clear_draft();
        }
    }

    pub(super) fn draw_vertex_inspector(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let reveal = std::mem::take(&mut self.vertex_inspector.reveal);
        let response = egui::CollapsingHeader::new("Vertex Parameters")
            .id_salt("vertex-parameters")
            .default_open(false)
            .open(reveal.then_some(true))
            .show(ui, |ui| self.draw_vertex_parameters_body(ui, actions));
        if reveal {
            response.header_response.scroll_to_me(Some(egui::Align::Min));
        }
        let open = response.fully_open();
        if open && !self.vertex_inspector.open {
            self.vertex_inspector.fetch = true;
        }
        self.vertex_inspector.open = open;
    }

    pub(super) fn draw_vertex_parameters_body(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
    ) {
        if self.cdmw_state["vertex_parameters"]["capability"].as_str() != Some(CAPABILITY) {
            ui.label("Vertex Parameters is unavailable with this host/helper combination.");
            return;
        }
        if !self.vertex_inspector.note.is_empty() {
            ui.label(&self.vertex_inspector.note);
        }
        if ui.button("Refresh values").clicked() {
            self.cancel_vertex_inspection();
            self.vertex_inspector.fetch = true;
            self.vertex_inspector.note.clear();
        }
        let data = self.vertex_inspector.data.clone();
        if data.is_null() {
            ui.label(
                if self.vertex_inspector.pending.is_some() || self.vertex_inspector.fetch {
                    "Inspecting the current selection…"
                } else {
                    "No current inspection. Refresh values to retry."
                },
            );
            return;
        }
        let count = data["count"].as_u64().unwrap_or(0);
        ui.label(format!("{count} selected vertices · LOD {}", data["lod"]));
        ui.small(data["space"].as_str().unwrap_or("Model editing space"));
        if count == 0 {
            ui.label("Select vertices, edges, faces or whole parts.");
            return;
        }
        let ready = !self.cdmw_busy()
            && data["token"] == self.vertex_token()
            && self.vertex_inspector.key == self.vertex_key();
        ui.small("Edit the selection below. Blank fields stay unchanged.");
        for (channel, label) in [
            ("position", "Position"),
            ("uv0", "UV Coordinates"),
            ("normal", "Normals"),
        ] {
            let summary = &data["summaries"][channel];
            let can_edit =
                ready && data["capabilities"][channel]["editable"].as_bool() == Some(true);
            egui::CollapsingHeader::new(label)
                .id_salt(("vertex-edit", channel))
                .default_open(count == 1 && channel == "position")
                .show(ui, |ui| {
                    if !can_edit {
                        ui.small(
                            data["capabilities"][channel]["reason"]
                                .as_str()
                                .unwrap_or("Wait for the current operation."),
                        );
                    }
                    let draft = &mut self.vertex_inspector.draft;
                    let (fields, offset): (&mut [String], Option<&mut bool>) = match channel {
                        "position" => (&mut draft.position, Some(&mut draft.position_offset)),
                        "uv0" => (&mut draft.uv0, Some(&mut draft.uv_offset)),
                        _ => (&mut draft.normal, None),
                    };
                    if let Some(offset) = offset {
                        ui.add_enabled_ui(can_edit, |ui| {
                            ui.horizontal_wrapped(|ui| {
                                ui.label("Change");
                                ui.selectable_value(offset, false, "Set");
                                ui.selectable_value(offset, true, "Offset");
                            })
                        });
                    }
                    let current_width = (ui.available_width() * 0.28).clamp(50.0, 76.0);
                    let input_width =
                        (ui.available_width() - current_width - 46.0).clamp(48.0, 140.0);
                    egui::Grid::new(("vertex-components", channel))
                        .num_columns(3)
                        .min_col_width(0.0)
                        .spacing([6.0, 5.0])
                        .show(ui, |ui| {
                            ui.small("Axis");
                            ui.small("Current");
                            ui.small("New value");
                            ui.end_row();
                            for (axis, field) in fields.iter_mut().enumerate() {
                                let axis_label = if channel == "uv0" {
                                    ["U", "V"][axis]
                                } else {
                                    ["X", "Y", "Z"][axis]
                                };
                                ui.label(axis_label);
                                let mixed = summary["mixed"][axis].as_bool() == Some(true);
                                let current = if mixed {
                                    "Mixed".to_owned()
                                } else {
                                    shown(&summary["values"][axis])
                                };
                                ui.add_sized(
                                    [current_width, ui.spacing().interact_size.y],
                                    egui::Label::new(current)
                                        .truncate()
                                        .halign(egui::Align::Min),
                                )
                                .on_hover_text(if mixed {
                                    format!(
                                        "{axis_label} range: {} to {}",
                                        summary["min"][axis], summary["max"][axis]
                                    )
                                } else {
                                    format!("{axis_label}: {}", summary["values"][axis])
                                });
                                ui.add_enabled(
                                    can_edit,
                                    TextEdit::singleline(field)
                                        .id_salt(("vertex-input", channel, axis))
                                        .hint_text("Unchanged")
                                        .desired_width(input_width),
                                );
                                ui.end_row();
                            }
                        });
                    ui.small(if channel == "normal" {
                        "Enter all three components to change a normal."
                    } else {
                        "Hover Current for exact values or selection ranges."
                    });
                });
        }
        egui::CollapsingHeader::new("Skin Weights")
            .id_salt("vertex-skin-weights")
            .show(ui, |ui| {
                ui.label(format!(
                    "Total influence: {}",
                    summary_text(&data["summaries"]["weight_total"])
                ));
                egui::CollapsingHeader::new("Current influences").show(ui, |ui| {
                    for influence in data["weight_summaries"].as_array().into_iter().flatten() {
                        ui.label(format!(
                            "{} (slot {}): {}",
                            influence["name"].as_str().unwrap_or("Unresolved bone"),
                            influence["slot"],
                            summary_text(influence)
                        ));
                    }
                });
                let enabled = ready
                    && data["capabilities"]["weights"]["editable"].as_bool() == Some(true);
                if !enabled {
                    ui.small(
                        data["capabilities"]["weights"]["reason"]
                            .as_str()
                            .unwrap_or("Weight editing unavailable."),
                    );
                } else {
                    let draft = &mut self.vertex_inspector.draft;
                    ui.checkbox(&mut draft.weight_enabled, "Stage weight change");
                    ui.add_enabled_ui(draft.weight_enabled, |ui| {
                        ui.label("Operation");
                        ComboBox::from_id_salt("vertex-weight-mode")
                            .selected_text(["Set", "Offset", "Remove", "Normalize"][draft.weight_mode])
                            .show_ui(ui, |ui| {
                                for (index, name) in
                                    ["Set", "Offset", "Remove", "Normalize"].iter().enumerate()
                                {
                                    ui.selectable_value(&mut draft.weight_mode, index, *name);
                                }
                            });
                        if draft.weight_mode != 3 {
                            let bones = data["bones"].as_array().cloned().unwrap_or_default();
                            let name = bones.iter()
                                .find(|bone| bone["bone"].as_i64() == draft.bone)
                                .and_then(|bone| bone["name"].as_str())
                                .unwrap_or("Choose bone");
                            ui.label("Bone");
                            ComboBox::from_id_salt("vertex-weight-bone")
                                .width(ui.available_width().max(20.0))
                                .truncate()
                                .selected_text(name)
                                .show_ui(ui, |ui| {
                                    for bone in &bones {
                                        ui.selectable_value(
                                            &mut draft.bone,
                                            bone["bone"].as_i64(),
                                            bone["name"].as_str().unwrap_or("Unresolved"),
                                        );
                                    }
                                });
                        }
                        if draft.weight_mode < 2 {
                            ui.label(if draft.weight_mode == 0 {
                                "Influence (0–1)"
                            } else {
                                "Influence offset"
                            });
                            ui.add(TextEdit::singleline(&mut draft.weight)
                                .hint_text("Value").desired_width(112.0));
                        }
                        ui.small("Other influences redistribute proportionally. Cloth guide weights are preserved.");
                    });
                }
            });
        ui.add_space(4.0);
        ui.horizontal_wrapped(|ui| {
            if ui
                .add_enabled(
                    ready && self.vertex_inspector.draft.dirty(),
                    Button::new(format!("Apply to {count} vertices")),
                )
                .clicked()
            {
                match self.vertex_inspector.draft.edits() {
                    Ok(edits) => actions.push(UiAction::CdmwCommand {
                        command: "vertex_edit",
                        arguments: json!({"token":data["token"],"edits":edits}),
                        label: "Edit Vertex Parameters",
                    }),
                    Err(error) => self.vertex_inspector.note = error,
                }
            }
            if ui.button("Discard").clicked() {
                self.vertex_inspector.clear_draft();
                self.vertex_inspector.note.clear();
            }
        });
        ui.separator();
        egui::CollapsingHeader::new("Inspect one vertex")
            .id_salt("vertex-individual-inspection")
            .default_open(count == 1)
            .show(ui, |ui| {
                let rows = data["rows"].as_array().cloned().unwrap_or_default();
                if !rows.is_empty() {
                    self.vertex_inspector.row = self.vertex_inspector.row.min(rows.len() - 1);
                    let selected = &rows[self.vertex_inspector.row];
                    ComboBox::from_id_salt("vertex-row")
                        .width(ui.available_width().max(20.0))
                        .truncate()
                        .selected_text(row_label(selected))
                        .show_ui(ui, |ui| {
                            for (index, row) in rows.iter().enumerate() {
                                ui.selectable_value(
                                    &mut self.vertex_inspector.row,
                                    index,
                                    row_label(row),
                                );
                            }
                        })
                        .response
                        .on_hover_text(row_label(selected));
                    ui.small("Viewing a row does not change the batch selection.");
                    let row = &rows[self.vertex_inspector.row];
                    ui.label(format!(
                        "Source: {} · part {} · original index {}",
                        row["source"]["kind"].as_str().unwrap_or("unmapped"),
                        shown(&row["source"]["part"]),
                        shown(&row["source"]["original_index"])
                    ));
                    egui::CollapsingHeader::new("Vertex values")
                        .default_open(count == 1)
                        .show(ui, |ui| {
                            for (name, key) in [
                                ("Position", "position"),
                                ("UV0", "uv0"),
                                ("Normal", "normal"),
                                ("Tangent (read-only)", "tangent"),
                            ] {
                                ui.label(format!("{name}: {}", shown(&row[key])))
                                    .on_hover_text(row[key].to_string());
                            }
                            ui.small(
                                "Tangents: PAC save does not support authored tangent writeback.",
                            );
                            if let Some(influences) = row["weights"]["influences"].as_array() {
                                for influence in influences {
                                    ui.label(format!(
                                        "{} (slot {}): {}",
                                        influence["name"].as_str().unwrap_or("Unresolved bone"),
                                        influence["slot"],
                                        influence["weight"]
                                    ));
                                }
                                ui.label(format!(
                                    "Weight total: {}",
                                    shown(&row["weights"]["total"])
                                ));
                            } else {
                                ui.label("Skin weights unavailable.");
                            }
                            let cloth = &row["cloth"];
                            if cloth["available"].as_bool() == Some(true) {
                                ui.label(format!(
                                    "Cloth: original {} · effective {} · {}",
                                    shown(&cloth["original_influence"]),
                                    shown(&cloth["effective_influence"]),
                                    if cloth["fixed"].as_bool() == Some(true) {
                                        "Fixed"
                                    } else {
                                        "Moving"
                                    }
                                ));
                                ui.label(format!(
                                    "Guide bindings: {} · weights {}",
                                    shown(&cloth["guide_indices"]),
                                    shown(&cloth["guide_weights"])
                                ));
                            } else {
                                ui.label(
                                    cloth["reason"]
                                        .as_str()
                                        .unwrap_or("Cloth mapping unavailable."),
                                );
                            }
                        });
                }
                ui.horizontal_wrapped(|ui| {
                    let pages = count.div_ceil(128);
                    let mut page = self.vertex_inspector.page;
                    if ui
                        .add_enabled(page > 0, Button::new("Previous vertices"))
                        .clicked()
                    {
                        page -= 1;
                    }
                    ui.label(format!("Page {} / {pages}", page + 1));
                    if ui
                        .add_enabled(page + 1 < pages, Button::new("Next vertices"))
                        .clicked()
                    {
                        page += 1;
                    }
                    if page != self.vertex_inspector.page {
                        self.cancel_vertex_inspection();
                        self.vertex_inspector.page = page;
                        self.vertex_inspector.fetch = true;
                    }
                });
            });
        egui::CollapsingHeader::new("Cloth & other data")
            .id_salt("vertex-readonly-data")
            .show(ui, |ui| {
                ui.label(format!("Tangents (read-only): {}", summary_text(&data["summaries"]["tangent"])));
                ui.label(format!(
                    "Cloth original: {}",
                    summary_text(&data["cloth_summary"]["original_influence"])
                ));
                ui.label(format!(
                    "Cloth effective: {} · {} fixed",
                    summary_text(&data["cloth_summary"]["effective_influence"]),
                    data["cloth_summary"]["fixed_count"]
                ));
                if ui.button("Open Cloth Controls").clicked() {
                    crate::cdmw_ui::set_cdmw_sidebar_expanded(
                        ui.ctx(),
                        crate::cdmw_ui::CDMW_TOOLS_SIDEBAR,
                        true,
                    );
                    self.activate_cdmw_rail_page(CdmwRailPage::Cloth, None);
                }
                ui.small("UV1 and vertex colours are unavailable. Other undecoded fields are preserved without editing.");
            });
    }
}

fn shown(value: &Value) -> String {
    match value {
        Value::Null => "Unavailable".into(),
        Value::Array(values) => values.iter().map(shown).collect::<Vec<_>>().join(", "),
        Value::Number(number) => {
            if let Some(value) = number.as_i64() {
                return value.to_string();
            }
            let value = number.as_f64().unwrap_or(0.0);
            if value != 0.0 && (value.abs() < 0.000001 || value.abs() >= 1_000_000.0) {
                format!("{value:.3e}")
            } else {
                format!("{value:.6}")
                    .trim_end_matches('0')
                    .trim_end_matches('.')
                    .to_owned()
            }
        }
        Value::String(text) => text.clone(),
        _ => value.to_string(),
    }
}
fn row_label(row: &Value) -> String {
    format!(
        "{} · part {} · vertex {}",
        row["part_name"].as_str().unwrap_or("Part"),
        row["part"],
        row["vertex"]
    )
}
fn summary_text(summary: &Value) -> String {
    let available = summary["available_count"].as_u64().unwrap_or(0);
    if available == 0 {
        return "Unavailable".into();
    }
    let mixed = summary["mixed"]
        .as_array()
        .is_some_and(|values| values.iter().any(|v| v.as_bool() == Some(true)));
    let mut text = if mixed {
        format!(
            "Mixed · {} to {}",
            shown(&summary["min"]),
            shown(&summary["max"])
        )
    } else {
        shown(&summary["values"])
    };
    if summary["available_count"] != summary["selection_count"] {
        text.push_str(&format!(" · available on {available} vertices"));
    }
    text
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn vertex_draft_partial_values_and_validation() {
        let mut draft = VertexDraft::default();
        draft.position[1] = "2.5".into();
        assert_eq!(
            draft.edits().unwrap()["position"],
            json!({"mode":"set","values":[null,2.5,null]})
        );
        draft.position[0] = "NaN".into();
        assert!(draft.edits().is_err());
        draft.position[0].clear();
        draft.normal[0] = "1".into();
        assert!(draft.edits().is_err());
    }
    #[test]
    fn vertex_invalidation_discards_targeted_inputs() {
        let mut inspector = VertexInspector::default();
        inspector.draft.position[0] = "1".into();
        inspector.invalidate(json!(["new selection"]));
        assert!(!inspector.draft.dirty());
        assert!(inspector.note.contains("discarded"));
        assert!(inspector.data.is_null());
    }
    #[test]
    fn vertex_inspection_rejects_stale_replies_and_closed_sections() {
        let mut app = crate::headless_tests::triangle_application().unwrap();
        app.cdmw_state = json!({"session_id":"inspect-test","base_revision":1,"selection_revision":2,"topology_generation":3});
        app.vertex_inspector.open = true;
        let key = app.vertex_key();
        app.vertex_inspector.pending = Some((10, key.clone()));
        let payload = json!({"token":app.vertex_token(),"count":2,"rows":[]});
        app.accept_vertex_inspection(9, true, payload.clone(), String::new());
        assert!(app.vertex_inspector.data.is_null());
        assert!(app.vertex_inspector.pending.is_some());
        app.mesh.as_mut().unwrap().selection_revision += 1;
        app.accept_vertex_inspection(10, true, payload.clone(), String::new());
        assert!(app.vertex_inspector.data.is_null());
        app.vertex_inspector.pending = Some((11, app.vertex_key()));
        app.accept_vertex_inspection(11, true, payload.clone(), String::new());
        assert_eq!(app.vertex_inspector.data["count"], 2);
        assert!(app.vertex_inspector.draft.position_offset);
        assert!(app.vertex_inspector.draft.uv_offset);
        app.vertex_inspector.data = Value::Null;
        app.vertex_inspector.pending = Some((12, app.vertex_key()));
        app.vertex_inspector.open = false;
        app.accept_vertex_inspection(12, true, payload, String::new());
        assert!(app.vertex_inspector.data.is_null());
    }

    #[test]
    fn vertex_inspection_is_idle_when_closed_or_unsupported() {
        let mut app = crate::headless_tests::triangle_application().unwrap();
        app.cdmw_state = json!({"vertex_parameters":{"capability":CAPABILITY}});
        app.tick_vertex_inspector(true);
        assert!(app.vertex_inspector.pending.is_none());
        app.vertex_inspector.open = true;
        app.cdmw_state = Value::Null;
        app.tick_vertex_inspector(true);
        assert!(app.vertex_inspector.pending.is_none());
    }
    #[test]
    fn vertex_inspection_debounces_and_cancels_superseded_work() {
        let mut app = crate::headless_tests::triangle_application().unwrap();
        let root = tempfile::tempdir().unwrap();
        app.cdmw_bridge = Some(CdmwBridge::for_test(
            root.path().into(),
            "inspect-test",
            1,
            1,
        ));
        app.cdmw_state = json!({"session_id":"inspect-test","base_revision":1,"selection_revision":2,"topology_generation":3,"vertex_parameters":{"capability":CAPABILITY}});
        app.vertex_inspector.open = true;
        app.tick_vertex_inspector(true);
        assert!(
            app.vertex_inspector.pending.is_none(),
            "selection changes are debounced"
        );
        app.vertex_inspector.changed_at = Some(Instant::now() - Duration::from_millis(200));
        app.tick_vertex_inspector(true);
        let first = app.vertex_inspector.pending.clone().unwrap();
        app.tick_vertex_inspector(true);
        assert_eq!(app.vertex_inspector.pending, Some(first.clone()));
        app.mesh.as_mut().unwrap().selection_revision += 1;
        app.tick_vertex_inspector(true);
        assert!(app.vertex_inspector.pending.is_none());
        app.vertex_inspector.changed_at = Some(Instant::now() - Duration::from_millis(200));
        app.tick_vertex_inspector(true);
        assert!(app.vertex_inspector.pending.as_ref().unwrap().0 > first.0);
        app.tick_vertex_inspector(false);
        assert!(app.vertex_inspector.pending.is_none());
    }
}
