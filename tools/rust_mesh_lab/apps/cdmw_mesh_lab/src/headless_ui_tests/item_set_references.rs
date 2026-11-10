use super::*;

#[test]
fn reference_pieces_inspector_switch_and_view_do_not_edit_geometry() -> TestResult {
    let root = tempdir()?;
    let mut application = triangle_application()?;
    let snapshot = application.mesh.as_ref().ok_or("mesh")?.draw_snapshot();
    application.cdmw_reference_pieces = vec![crate::cdmw_session::LoadedReferencePiece {
        index: 1, name: "lower.pac".into(), visible: true, part_count: 1,
        snapshot: snapshot.clone(), textures: Vec::new(), material_presentations: Vec::new(),
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
    assert_eq!(ui.application.mesh.as_ref().ok_or("mesh")?.draw_snapshot(), snapshot);
    assert!(messages.try_recv().is_err());
    ui.click("Switch editable piece")?;
    ui.click("lower.pac")?;
    assert!(ui.last_actions.iter().any(|action| matches!(action, UiAction::SwitchItemPiece(1))));
    // The UI harness records actions; the application's handler sends the owned index.
    ui.application.handle_actions(vec![UiAction::SwitchItemPiece(1)]);
    let message = messages.recv_timeout(std::time::Duration::from_secs(1))?;
    assert_eq!(message["event"], "switch_item_piece");
    assert_eq!(message["index"], 1);
    assert_eq!(message["session_id"], "set");
    Ok(())
}
