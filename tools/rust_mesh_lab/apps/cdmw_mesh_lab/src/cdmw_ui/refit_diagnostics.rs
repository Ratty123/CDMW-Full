//! Bounded, on-demand observations of the current preview. Never changes a fit.
use super::*;

fn diagnostic_number(value: Option<&Value>) -> String {
    value.and_then(Value::as_f64).filter(|number| number.is_finite())
        .map_or_else(|| crate::localization::tr("Unavailable"), |number| format!("{number:.6}"))
}

fn diagnostic_count(value: Option<&Value>) -> String {
    value.and_then(Value::as_u64)
        .map_or_else(|| "?".to_owned(), |number| number.to_string())
}

fn diagnostic_indices(value: Option<&Value>) -> Option<Vec<u32>> {
    let mut indices = value?.as_array()?.iter()
        .map(|index| u32::try_from(index.as_u64()?).ok())
        .collect::<Option<Vec<_>>>()?;
    indices.sort_unstable();
    indices.dedup();
    Some(indices)
}

fn diagnostic_report_current(report: &Value, state: &Value, shadow_revision: Option<u64>, targets: &[u32]) -> bool {
    let host_morph_revision = state.get("state_revision").and_then(Value::as_u64);
    let mut expected_targets = targets.to_vec();
    expected_targets.sort_unstable();
    expected_targets.dedup();
    host_morph_revision.is_some()
        && shadow_revision.is_some()
        // The host's Morph & Refit watermark can differ from the native
        // solver revision retained in report.state_revision.
        && report.get("host_morph_revision").and_then(Value::as_u64) == host_morph_revision
        && report.get("shadow_revision").and_then(Value::as_u64) == shadow_revision
        && diagnostic_indices(report.get("requested_submesh_indices")) == Some(expected_targets)
}

fn diagnostic_reason(ui: &mut egui::Ui, report: &Value) {
    if let Some(reason) = report.get("reason").and_then(Value::as_str).filter(|reason| !reason.trim().is_empty()) {
        ui.weak(reason);
    }
}

fn diagnostic_sample_label(sample: &Value) -> String {
    let part = diagnostic_count(sample.get("submesh_index"));
    let vertices = diagnostic_indices(sample.get("vertex_indices")).unwrap_or_default();
    if vertices.is_empty() {
        return format!("{} {part}", crate::localization::tr("Part"));
    }
    let label = crate::localization::tr(if vertices.len() == 1 { "vertex" } else { "vertices" });
    format!("{} {part}, {label} {}", crate::localization::tr("Part"),
        vertices.iter().take(3).map(u32::to_string).collect::<Vec<_>>().join(", "))
}

impl LabApplication {
    pub(super) fn draw_cdmw_refit_diagnostics(
        &mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>, state: &Value, targets: &[u32],
    ) {
        ui.separator();
        ui.strong(crate::localization::tr("Current fit diagnostics"));
        let mut scope = targets.to_vec();
        scope.sort_unstable();
        scope.dedup();
        if ui.add_enabled(!self.cdmw_busy() && !scope.is_empty(),
            Button::new(crate::localization::tr("Analyze current fit")))
            .on_hover_text(crate::localization::tr("Inspect the selected bound garments, or all bound garments when none are selected. Uses the current preview without applying pending settings."))
            .clicked()
        {
            actions.push(UiAction::CdmwCommand {
                command: "refit_diagnostics",
                arguments: json!({"submesh_indices": scope, "sample_limit": 2048, "detail_limit": 24}),
                label: "Analyze current fit",
            });
        }
        let Some(report) = self.cdmw_refit_diagnostics.as_ref() else {
            ui.weak(crate::localization::tr("Analyze the current preview to measure body clearance and garment layer spacing."));
            return;
        };
        if !diagnostic_report_current(report, state,
            self.cdmw_state.get("base_revision").and_then(Value::as_u64), targets)
        {
            ui.weak(crate::localization::tr("Fit analysis is out of date for this preview or selection. Analyze again."));
            return;
        }

        ui.weak(crate::localization::tr("Sampled geometry in model units. These measurements do not prove the whole mesh is collision-free."));
        ui.label(format!("{} {} / {}", crate::localization::tr("Samples:"),
            diagnostic_count(report.get("planned_sample_count")),
            diagnostic_count(report.get("candidate_sample_count"))));
        match report.get("status").and_then(Value::as_str) {
            Some("partial") => { ui.weak(crate::localization::tr("Partial analysis")); }
            Some("unavailable") => { ui.weak(crate::localization::tr("Analysis unavailable")); }
            _ => {}
        }
        diagnostic_reason(ui, report);

        let body = &report["body_clearance"];
        if body.get("available").and_then(Value::as_bool) == Some(true) {
            ui.label(format!("{} {}", crate::localization::tr("Minimum body distance:"),
                diagnostic_number(body.get("minimum_distance"))));
            ui.label(format!("{} {}", crate::localization::tr("Local normal offset:"),
                diagnostic_number(body.get("minimum_normal_offset"))));
            ui.weak(crate::localization::tr("Normal offset uses the nearest face orientation. It does not determine whether a point is inside the body."));
            ui.weak(format!("{} {}", crate::localization::tr("Body samples evaluated:"),
                diagnostic_count(body.get("evaluated_sample_count"))));
        } else {
            ui.weak(crate::localization::tr("Body clearance unavailable"));
            diagnostic_reason(ui, body);
        }

        let layers = &report["layer_spacing"];
        if layers.get("available").and_then(Value::as_bool) == Some(true) {
            ui.label(format!("{} {}", crate::localization::tr("Minimum layer gap:"),
                diagnostic_number(layers.get("minimum_current_gap"))));
            let retained = layers.get("minimum_retained_ratio").and_then(Value::as_f64)
                .filter(|ratio| ratio.is_finite())
                .map_or_else(|| crate::localization::tr("Unavailable"), |ratio| format!("{:.1}%", ratio * 100.0));
            ui.label(format!("{} {retained}", crate::localization::tr("Minimum authored gap retained:")));
            ui.weak(format!("{} {}", crate::localization::tr("Layer samples evaluated:"),
                diagnostic_count(layers.get("evaluated_sample_count"))));
        } else {
            ui.weak(crate::localization::tr("Layer spacing unavailable"));
        }
        diagnostic_reason(ui, layers);
        if let Some(ambiguous) = layers.get("ambiguous_candidate_count").and_then(Value::as_u64).filter(|count| *count > 0) {
            ui.weak(format!("{} {ambiguous}", crate::localization::tr("Ambiguous layer candidates omitted:")));
        }

        let mut parts = report.get("parts").and_then(Value::as_array).into_iter().flatten()
            .filter(|part| part.get("minimum_distance").and_then(Value::as_f64).is_some_and(f64::is_finite))
            .collect::<Vec<_>>();
        parts.sort_by(|a, b| a["minimum_distance"].as_f64().unwrap().total_cmp(&b["minimum_distance"].as_f64().unwrap()));
        let mut details = layers.get("details").and_then(Value::as_array).into_iter().flatten()
            .filter(|detail| detail.get("retained_ratio").and_then(Value::as_f64).is_some_and(f64::is_finite))
            .collect::<Vec<_>>();
        details.sort_by(|a, b| a["retained_ratio"].as_f64().unwrap().total_cmp(&b["retained_ratio"].as_f64().unwrap()));
        if !parts.is_empty() || !details.is_empty() {
            crate::localization::collapsing("Lowest sampled gaps")
                .id_salt("refit-diagnostic-locations").show(ui, |ui| {
                    for part in parts.iter().take(3) {
                        let sample = part.get("minimum_distance_sample").unwrap_or(part);
                        ui.label(format!("{}: {} {}", diagnostic_sample_label(sample),
                            crate::localization::tr("body distance"), diagnostic_number(part.get("minimum_distance"))));
                        if part.get("has_influence_mask").and_then(Value::as_bool) == Some(true) {
                            ui.weak(crate::localization::tr("An influence mask is configured for this Part."));
                        }
                    }
                    for detail in details.iter().take(3) {
                        ui.label(format!("{} → {} {}: {} {}", diagnostic_sample_label(&detail["sample"]),
                            crate::localization::tr("Part"), diagnostic_count(detail.get("target_submesh_index")),
                            crate::localization::tr("layer gap"), diagnostic_number(detail.get("current_gap"))));
                    }
                    if parts.len() > 3 || details.len() > 3
                        || layers.get("details_truncated").and_then(Value::as_bool) == Some(true)
                    {
                        ui.weak(crate::localization::tr("Additional sample locations omitted."));
                    }
                });
        }
    }
}
