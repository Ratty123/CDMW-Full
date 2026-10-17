//! Painted diagnostics controls, freshness checks and read-only result receipt.
use super::*;

fn diagnostics_ui(selected: &[u32]) -> Result<HeadlessUi, Box<dyn std::error::Error>> {
    let mut ui = super::morph_authoring::authoring_ui()?;
    ui.application.cdmw_state["base_revision"] = json!(9);
    ui.application.cdmw_state["morph_refit"]["state_revision"] = json!(7);
    ui.application.cdmw_state["morph_refit"]["refit"]["distance_warning"] = json!(true);
    ui.application.mesh.as_mut().ok_or("mesh")?.set_selection(Selection {
        submeshes: selected.iter().copied().collect(),
        ..Selection::default()
    })?;
    ui.click("Fit")?;
    Ok(ui)
}

fn report() -> Value {
    json!({
        "available": true,
        "status": "partial",
        "reason": "The sample limit was reached.",
        "session_id": "native-session",
        // Native identity and the host's Morph & Refit watermark need not match.
        "state_revision": 6,
        "host_morph_revision": 7,
        "shadow_revision": 9,
        "requested_submesh_indices": [1, 2],
        "sampled": true,
        "candidate_sample_count": 3000,
        "planned_sample_count": 2048,
        "global_collision_proof": false,
        "body_clearance": {
            "available": true,
            "evaluated_sample_count": 2048,
            "minimum_distance": 0.0005,
            "minimum_normal_offset": -0.0002
        },
        "parts": [{
            "submesh_index": 1,
            "minimum_distance": 0.0005,
            "minimum_distance_sample": {"submesh_index": 1, "kind": "vertex", "vertex_indices": [7, 7, 7]},
            "has_influence_mask": true
        }],
        "layer_spacing": {
            "available": true,
            "evaluated_sample_count": 192,
            "recognized_correspondence_count": 42,
            "ambiguous_candidate_count": 3,
            "minimum_current_gap": 0.003,
            "minimum_retained_ratio": 0.6,
            "details_truncated": false,
            "details": [{
                "sample": {"submesh_index": 1, "kind": "vertex", "vertex_indices": [7, 7, 7]},
                "target_submesh_index": 2,
                "current_gap": 0.003,
                "reference_gap": 0.005,
                "retained_ratio": 0.6
            }]
        }
    })
}

fn painted_text(ui: &HeadlessUi) -> String {
    ui.output.shapes.iter().filter_map(|shape| match &shape.shape {
        egui::Shape::Text(text) => Some(text.galley.job.text.as_str()),
        _ => None,
    }).collect::<Vec<_>>().join("\n")
}

#[test]
fn diagnostics_click_queries_selected_bound_parts_or_all_without_applying_settings() -> TestResult {
    for (selected, expected) in [
        (vec![1], vec![1]),
        (vec![0, 2], vec![2]),
        (vec![], vec![1, 2]),
    ] {
        let mut ui = diagnostics_ui(&selected)?;
        let root = tempdir()?;
        ui.application.cdmw_bridge = Some(CdmwBridge::for_test(
            root.path().to_path_buf(), "diagnostics-click", 2, 9,
        ));
        ui.application.cdmw_refit_settings_dirty.mark("clearance_percent");
        ui.application.cdmw_refit_clearance = 0.75;
        let before = ui.application.mesh.as_ref().ok_or("mesh")?.structural_fingerprint();
        let state_before = ui.application.cdmw_state.clone();
        let actions = ui.actions_from_click("Analyze current fit")?;
        let commands = actions.iter().filter_map(|action| match action {
            UiAction::CdmwCommand { command, arguments, .. } => Some((*command, arguments)),
            _ => None,
        }).collect::<Vec<_>>();
        assert_eq!(commands.len(), 1, "{actions:?}");
        assert_eq!(commands[0].0, "refit_diagnostics");
        assert_eq!(commands[0].1, &json!({
            "submesh_indices": expected, "sample_limit": 2048, "detail_limit": 24,
        }));
        assert_eq!(ui.application.cdmw_pending_request.as_ref().map(|pending| pending.label.as_str()),
            Some("Analyze current fit"));
        assert_eq!(ui.application.cdmw_refit_clearance, 0.75);
        assert!(ui.application.cdmw_refit_settings_dirty.is_dirty());
        assert_eq!(ui.application.cdmw_state, state_before);
        assert_eq!(ui.application.mesh.as_ref().ok_or("mesh")?.structural_fingerprint(), before);
    }
    Ok(())
}

#[test]
fn diagnostics_query_is_disabled_while_a_host_request_is_pending() -> TestResult {
    let mut ui = diagnostics_ui(&[])?;
    // Selection requests leave the surrounding controls visible and enabled;
    // the diagnostics button must still honor the pending-request guard itself.
    ui.application.cdmw_pending_request = Some(CdmwPendingRequest {
        request_id: 10,
        event: "command_result",
        label: "Select parts".to_owned(),
        origin: Some(CdmwRequestOrigin::Selection),
    });
    ui.frame(Vec::new());
    assert!(!has_host_command(&ui.actions_from_click("Analyze current fit")?, "refit_diagnostics"));
    Ok(())
}

#[test]
fn diagnostics_render_current_body_and_layer_measurements_with_sample_limits() -> TestResult {
    let mut ui = diagnostics_ui(&[])?;
    ui.application.cdmw_refit_diagnostics = Some(report());
    ui.last_actions.clear();
    ui.frame(Vec::new());
    ui.reveal("Minimum body distance: 0.000500")?;
    ui.reveal("Minimum layer gap: 0.003000")?;
    let text = painted_text(&ui);
    for expected in [
        "Samples: 2048 / 3000",
        "Partial analysis",
        "The sample limit was reached.",
        "Local normal offset: -0.000200",
        "Normal offset uses the nearest face orientation. It does not determine whether a point is inside the body.",
        "Minimum authored gap retained: 60.0%",
        "Ambiguous layer candidates omitted: 3",
    ] {
        assert!(text.contains(expected), "Missing {expected:?}: {text}");
    }
    ui.click("Lowest sampled gaps")?;
    ui.reveal("Part 1, vertex 7: body distance 0.000500")?;
    assert!(painted_text(&ui).contains("Part 1, vertex 7 → Part 2: layer gap 0.003000"));
    assert!(!has_host_command(&ui.last_actions, "refit_diagnostics"));
    Ok(())
}

#[test]
fn diagnostics_hide_stale_metrics_after_host_morph_shadow_or_scope_changes() -> TestResult {
    for change in ["host-morph", "shadow", "scope"] {
        let mut ui = diagnostics_ui(&[])?;
        ui.application.cdmw_refit_diagnostics = Some(report());
        ui.frame(Vec::new());
        ui.reveal("Minimum body distance: 0.000500")?;
        match change {
            "host-morph" => ui.application.cdmw_state["morph_refit"]["state_revision"] = json!(8),
            "shadow" => ui.application.cdmw_state["base_revision"] = json!(10),
            _ => ui.application.mesh.as_mut().ok_or("mesh")?.set_selection(Selection {
                submeshes: [2].into_iter().collect(), ..Selection::default()
            })?,
        }
        ui.last_actions.clear();
        ui.frame(Vec::new());
        ui.reveal("Fit analysis is out of date for this preview or selection. Analyze again.")?;
        let text = painted_text(&ui);
        assert!(!text.contains("Minimum body distance:"), "stale metrics for {change}: {text}");
        assert!(!text.contains("Minimum layer gap:"), "stale metrics for {change}: {text}");
        assert!(!has_host_command(&ui.last_actions, "refit_diagnostics"));
        assert!(has_host_command(&ui.actions_from_click("Analyze current fit")?, "refit_diagnostics"));
    }
    Ok(())
}

#[test]
fn diagnostics_unavailable_report_never_substitutes_zero_measurements() -> TestResult {
    let mut ui = diagnostics_ui(&[])?;
    ui.application.cdmw_refit_diagnostics = Some(json!({
        "available": false, "status": "unavailable", "reason": "No usable binding is available.",
        "state_revision": 6, "host_morph_revision": 7,
        "shadow_revision": 9, "requested_submesh_indices": [1, 2],
        "body_clearance": {"available": false}, "layer_spacing": {"available": false},
    }));
    ui.frame(Vec::new());
    ui.reveal("Analysis unavailable")?;
    let text = painted_text(&ui);
    assert!(text.contains("No usable binding is available."));
    assert!(text.contains("Body clearance unavailable"));
    assert!(text.contains("Layer spacing unavailable"));
    assert!(!text.contains("Minimum body distance:"));
    assert!(!text.contains("Minimum layer gap:"));
    Ok(())
}

#[test]
fn diagnostics_result_is_cached_only_after_a_successful_read_only_reply() -> TestResult {
    for ok in [false, true] {
        let mut ui = diagnostics_ui(&[])?;
        let root = tempdir()?;
        ui.application.cdmw_bridge = Some(CdmwBridge::for_test(
            root.path().to_path_buf(), "diagnostics-ui", 2, 9,
        ));
        ui.application.cdmw_pending_request = Some(CdmwPendingRequest {
            request_id: 1, event: "command_result", label: "Analyze current fit".to_owned(), origin: None,
        });
        ui.application.cdmw_refit_settings_dirty.mark("clearance_percent");
        let before = ui.application.mesh.as_ref().ok_or("mesh")?.structural_fingerprint();
        let mut state = ui.application.cdmw_state.clone();
        state["session_id"] = json!("diagnostics-ui");
        state["selection"] = json!({
            "vertices_by_submesh": {}, "edges_by_submesh": {}, "faces_by_submesh": {}, "source_indices": [],
        });
        // The service query returns state without a document or revision advance.
        ui.application.handle_cdmw_result("command_result", 1, 9, ok,
            json!({"state": state, "result": {"status": "ok", "refit_diagnostics": report()}}),
            if ok { "" } else { "Analysis failed" });
        assert!(ui.application.cdmw_pending_request.is_none(), "{}", ui.application.status);
        assert_eq!(ui.application.cdmw_refit_diagnostics.is_some(), ok, "{}", ui.application.status);
        if ok {
            assert_eq!(ui.application.cdmw_refit_diagnostics, Some(report()));
        }
        assert_eq!(ui.application.cdmw_state["base_revision"], json!(9));
        assert!(ui.application.cdmw_refit_settings_dirty.is_dirty());
        assert_eq!(ui.application.mesh.as_ref().ok_or("mesh")?.structural_fingerprint(), before);
    }
    Ok(())
}
