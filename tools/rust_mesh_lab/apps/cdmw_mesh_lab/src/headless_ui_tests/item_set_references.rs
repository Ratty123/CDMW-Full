use super::*;

#[test]
fn editable_item_set_groups_keep_view_and_include_independent() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        two_part_application()?,
        egui::vec2(1440.0, 1080.0),
    );
    ui.application.cdmw_state["archive_refit_assets"] = json!([
        {"path": "upper.pac", "part_indices": [0]}, {"path": "lower.pac", "part_indices": [1]}]);
    ui.application.cdmw_state["replacement"] = json!({
        "available": false, "item_set": true, "comparison": "edit",
        "groups": [{"id": "upper", "name": "upper.pac"}, {"id": "lower", "name": "lower.pac"}],
        "parts": [{"id": "upper:0", "index": 0, "asset_id": "upper", "included": true},
                  {"id": "lower:0", "index": 1, "asset_id": "lower", "included": true}]
    });
    ui.settle_layout();
    ui.reveal("upper.pac")?;
    ui.reveal("lower.pac")?;
    assert!(!ui.application.cdmw_has_archive_refit());
    let before = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();
    let view = ui.list_checkbox_rect("lower.pac", "View")?;
    ui.click_at(view.center());
    assert!(ui.application.cdmw_hidden_parts.contains(&1));
    assert!(!has_host_command(&ui.last_actions, "replacement_include"));
    ui.click_at(view.center());
    let include = ui.list_checkbox_rect("lower.pac", "Include")?;
    ui.click_at(include.center());
    assert!(ui.last_actions.iter().any(|action| matches!(action,
        UiAction::CdmwCommand { command: "replacement_include", arguments, .. }
        if arguments["part_ids"] == json!(["lower:0"]) && arguments["included"] == false)));
    assert_eq!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .structural_fingerprint(),
        before
    );
    Ok(())
}

#[test]
fn reference_pieces_inspector_switch_and_view_do_not_edit_geometry() -> TestResult {
    let root = tempdir()?;
    let mut application = triangle_application()?;
    let snapshot = application.mesh.as_ref().ok_or("mesh")?.draw_snapshot();
    application.cdmw_reference_pieces = vec![crate::cdmw_session::LoadedReferencePiece {
        index: 1,
        name: "lower.pac".into(),
        visible: true,
        part_count: 1,
        snapshot: snapshot.clone(),
        textures: Vec::new(),
        material_presentations: Vec::new(),
    }];
    let mut bridge = CdmwBridge::for_test(root.path().to_owned(), "set", 1, 0);
    bridge.set_reference_files_for_test(vec!["upper.pac".into(), "lower.pac".into()]);
    let messages = bridge.capture_messages_for_test();
    application.cdmw_bridge = Some(bridge);
    let mut ui = HeadlessUi::new_integrated_cdmw(application, egui::vec2(1440.0, 1080.0));
    ui.settle_layout();
    ui.click("Reference pieces")?;
    ui.reveal("lower.pac")?;
    ui.click("View")?;
    assert!(!ui.application.cdmw_reference_pieces[0].visible);
    ui.click("View")?;
    assert!(ui.application.cdmw_reference_pieces[0].visible);
    assert_eq!(
        ui.application.mesh.as_ref().ok_or("mesh")?.draw_snapshot(),
        snapshot
    );
    // No edit went to CDMW; the editor's command list (P12) is the only message.
    assert!(
        messages
            .try_iter()
            .all(|message| message["event"] == "commands_state")
    );
    ui.click("Switch editable piece")?;
    ui.click("lower.pac")?;
    assert!(
        ui.last_actions
            .iter()
            .any(|action| matches!(action, UiAction::SwitchItemPiece(1)))
    );
    // The UI harness records actions; the application's handler sends the owned index.
    ui.application
        .handle_actions(vec![UiAction::SwitchItemPiece(1)]);
    let message = messages.recv_timeout(std::time::Duration::from_secs(1))?;
    assert_eq!(message["event"], "switch_item_piece");
    assert_eq!(message["index"], 1);
    assert_eq!(message["session_id"], "set");
    Ok(())
}

/// Fredric's report on a set's Parts list: the Physics column read "Unknown p..." on
/// every row, and the file rows' tick boxes sat left of the part rows'. Header, file
/// rows and part rows share one grid at every width and density; a long physics badge
/// is shown whole; a part that was not inspected leaves its cell empty.
#[test]
fn item_set_parts_list_shares_one_column_grid_and_shows_physics_whole() -> TestResult {
    let long_badge = "Cloth + jiggle (source)";
    for (panel, font, density) in [
        (300.0, 10.0, "compact"),
        (380.0, 10.0, "normal"),
        (640.0, 10.0, "normal"),
        (380.0, 15.0, "comfortable"),
        (640.0, 15.0, "comfortable"),
    ] {
        let case = format!("panel {panel}, font {font}, {density}");
        let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
            two_part_application()?,
            egui::vec2(1600.0, 1080.0),
        );
        ui.application
            .apply_cdmw_theme_payload(&json!({"font_point_size": font, "density": density}));
        crate::cdmw_layout::restore(
            &ui.application.egui_context,
            &json!({"cdmw_right_panels": panel}),
        );
        ui.application.cdmw_state["archive_refit_assets"] = json!([
            {"path": "upper.pac", "part_indices": [0]}, {"path": "lower.pac", "part_indices": [1]}]);
        ui.application.cdmw_state["replacement"] = json!({
            "available": false, "item_set": true, "comparison": "edit",
            "groups": [{"id": "upper", "name": "upper.pac"}, {"id": "lower", "name": "lower.pac"}],
            "parts": [{"id": "upper:0", "index": 0, "asset_id": "upper", "included": true},
                      {"id": "lower:0", "index": 1, "asset_id": "lower", "included": true}]
        });
        ui.application.cdmw_state["physics"] = json!({"parts": [
            {"index": 0, "kind": "cloth", "source_only": true, "jiggle_counts": [2]},
            {"index": 1, "kind": "unknown"}]});
        ui.settle_layout();
        ui.reveal("upper.pac")?;
        let right = ui.application.viewport_rect.ok_or("viewport")?.right();
        for column in ["View", "Include"] {
            let header = ui
                .label_rect_where(column, |rect| rect.left() > right)
                .ok_or_else(|| format!("{case}: {column} header"))?;
            for row in ["upper.pac", "0: Part A", "lower.pac", "1: Part B"] {
                // The box nearest the header on the row's line. A text's visual box
                // includes descenders, so "on the line" allows half a row height.
                let label = ui.reveal(row)?;
                let rect = ui
                    .output
                    .shapes
                    .iter()
                    .filter_map(|clipped| match &clipped.shape {
                        egui::Shape::Rect(shape)
                            if (8.0..=40.0).contains(&shape.rect.width())
                                && (shape.rect.width() - shape.rect.height()).abs() < 1.0
                                && (shape.rect.center().y - label.center().y).abs()
                                    < label.height().max(shape.rect.height()) * 0.5
                                && clipped.clip_rect.contains_rect(shape.rect) =>
                        {
                            Some(shape.rect)
                        }
                        _ => None,
                    })
                    .min_by(|a, b| {
                        (a.center().x - header.center().x)
                            .abs()
                            .total_cmp(&(b.center().x - header.center().x).abs())
                    })
                    .ok_or_else(|| format!("{case}: no {column} box beside {row}"))?;
                assert!(
                    (rect.center().x - header.center().x).abs() <= 1.0,
                    "{case}: {row} {column} box at {} but header at {}",
                    rect.center().x,
                    header.center().x
                );
            }
        }
        let painted = |label: &str| {
            ui.output.shapes.iter().find_map(|clipped| match &clipped.shape {
                egui::Shape::Text(text)
                    if text.galley.job.text == label
                        && text.visual_bounding_rect().left() > right =>
                {
                    Some(text.galley.elided)
                }
                _ => None,
            })
        };
        // At the default width and wider the whole badge shows; narrower, the name keeps
        // its share and the badge truncates (its tooltip has the whole text).
        if panel >= 640.0 || (panel >= 380.0 && font <= 10.0) {
            assert_eq!(painted(long_badge), Some(false), "{case}: the badge is cut off");
        } else {
            assert!(painted(long_badge).is_some(), "{case}: the badge is missing");
        }
        assert_eq!(painted("Physics"), Some(false), "{case}: the header is cut off");
        assert_eq!(painted("0: Part A"), Some(false), "{case}: the part name is cut off");
        assert_eq!(painted("Unknown physics"), None, "{case}: an uninspected part shows a badge");
    }
    Ok(())
}
