use super::*;

fn state(root: &std::path::Path, app: &LabApplication, revision: u64, cursor: usize) -> Result<Value, Box<dyn std::error::Error>> {
    let mut document = app.document.clone().ok_or("document")?;
    document.lods[0].submeshes[0].positions[0][0] = cursor as f32;
    let mut value = cdmw_state_with_document(root, "history-navigation", revision, &document)?;
    value["authoring_enabled"] = json!(true);
    value["history_entries"] = json!([
        {"action":"transform", "label":"Move", "state":if cursor > 0 {"applied"} else {"undone"}},
        {"action":"jiggle", "label":"Set jiggle contribution", "state":if cursor > 1 {"applied"} else {"undone"}},
        {"action":"select", "label":"Select", "state":if cursor > 2 {"applied"} else {"undone"}}
    ]);
    value["history_cursor"] = json!(cursor);
    value["undo_count"] = json!(cursor);
    value["redo_count"] = json!(3 - cursor);
    Ok(value)
}

fn application(root: &std::path::Path) -> Result<LabApplication, Box<dyn std::error::Error>> {
    let mut app = triangle_application()?;
    app.cdmw_bridge = Some(CdmwBridge::for_test(root.to_path_buf(), "history-navigation", 1, 0));
    let initial = state(root, &app, 0, 3)?;
    app.apply_cdmw_state(initial);
    assert!(!app.cdmw_exit_requested, "{}", app.status);
    Ok(app)
}

fn reply(app: &mut LabApplication, value: Value, ok: bool) {
    let id = app.cdmw_pending_request.as_ref().expect("pending history request").request_id;
    let revision = value["base_revision"].as_u64().unwrap();
    app.handle_cdmw_result("command_result", id, revision, ok, json!({"state":value}), if ok {""} else {"restore failed"});
}

#[test]
fn action_history_traverses_only_acknowledged_steps_and_can_restore_them() -> TestResult {
    let root = tempdir()?;
    let mut app = application(root.path())?;
    app.handle_actions(vec![UiAction::CdmwHistoryCursor { cursor: 1, revision: 0 }]);
    assert_eq!(app.cdmw_pending_request.as_ref().unwrap().label, "Undo");
    assert_eq!(app.document.as_ref().unwrap().lods[0].submeshes[0].positions[0][0], 3.0);
    for (revision, cursor) in [(1, 2), (2, 1)] {
        let value = state(root.path(), &app, revision, cursor)?;
        reply(&mut app, value, true);
        assert!(!app.cdmw_exit_requested, "{}", app.status);
        assert_eq!(app.document.as_ref().unwrap().lods[0].submeshes[0].positions[0][0], cursor as f32);
        assert_eq!(app.cdmw_pending_request.is_some(), cursor != 1);
    }
    app.handle_actions(vec![UiAction::CdmwHistoryCursor { cursor: 3, revision: 2 }]);
    assert_eq!(app.cdmw_pending_request.as_ref().unwrap().label, "Redo");
    for (revision, cursor) in [(3, 2), (4, 3)] {
        let value = state(root.path(), &app, revision, cursor)?;
        reply(&mut app, value, true);
        assert_eq!(app.cdmw_pending_request.is_some(), cursor != 3);
    }
    assert!(!app.cdmw_exit_requested, "{}", app.status);
    assert_eq!(app.cdmw_state["history_cursor"], 3);
    assert_eq!(app.cdmw_transaction_attempts, 0);
    Ok(())
}

#[test]
fn action_history_stops_at_confirmed_state_on_failure_change_noop_or_close() -> TestResult {
    for fault in ["rejection", "trim", "noop", "close"] {
        let root = tempdir()?;
        let mut app = application(root.path())?;
        app.start_cdmw_history(0, 0);
        let value = state(root.path(), &app, 1, 2)?;
        reply(&mut app, value, true);
        let mut value = state(root.path(), &app, 2, if fault == "noop" || fault == "rejection" {2} else {1})?;
        if fault == "trim" {
            value["history_entries"].as_array_mut().unwrap().remove(0);
            value["redo_count"] = json!(1);
        }
        if fault == "close" { app.handle_cdmw_host_event(HostEvent::Cancel("closed".into())); }
        let expected = value["history_cursor"].clone();
        reply(&mut app, value, fault != "rejection");
        assert!(app.cdmw_pending_request.is_none(), "{fault}");
        assert_eq!(app.cdmw_state["history_cursor"], expected, "{fault}");
        assert_eq!(app.document.as_ref().unwrap().lods[0].submeshes[0].positions[0][0], expected.as_u64().unwrap() as f32);
        if fault != "close" { assert!(!app.cdmw_exit_requested, "{}", app.status); }
        if fault == "rejection" { assert!(app.status.contains("restore failed")); }
        if fault == "trim" || fault == "noop" { assert!(app.status.contains("last confirmed action")); }
    }
    Ok(())
}

#[test]
fn action_history_rejects_stale_out_of_range_and_busy_targets() -> TestResult {
    let root = tempdir()?;
    let mut app = application(root.path())?;
    for (target, revision) in [(1, 99), (4, 0), (3, 0)] {
        app.start_cdmw_history(target, revision);
        assert!(app.cdmw_pending_request.is_none());
    }
    app.start_cdmw_history(2, 0);
    let id = app.cdmw_pending_request.as_ref().unwrap().request_id;
    app.start_cdmw_history(0, 0);
    assert_eq!(app.cdmw_pending_request.as_ref().unwrap().request_id, id);
    let value = state(root.path(), &app, 1, 2)?;
    reply(&mut app, value, true);
    assert!(app.cdmw_pending_request.is_none());
    Ok(())
}
