use super::*;

#[test]
fn rejected_delete_shows_the_host_error_without_mutating_geometry() -> TestResult {
    for label in ["Delete part", "Delete selection", "Delete Selection"] {
        let root = tempdir()?;
        let mut application = triangle_application()?;
        let document = application.document.as_deref().cloned().ok_or("document")?;
        application.cdmw_bridge = Some(CdmwBridge::for_test(
            root.path().to_path_buf(),
            "delete-feedback",
            1,
            0,
        ));
        application.cdmw_pending_request = Some(CdmwPendingRequest {
            request_id: 1,
            event: "command_result",
            label: label.into(),
            origin: None,
        });
        let state = cdmw_state_with_document(root.path(), "delete-feedback", 0, &document)?;
        application.handle_cdmw_result(
            "command_result",
            1,
            0,
            false,
            json!({"state": state}),
            "This deletion is outside the supported Exact topology contract.",
        );
        assert!(application.cdmw_pending_request.is_none());
        assert_eq!(application.document.as_deref(), Some(&document));
        let message = format!(
            "{label} rejected: This deletion is outside the supported Exact topology contract."
        );
        assert_eq!(application.status, message);
        let context = application.egui_context.clone();
        for _ in 0..2 {
            let mut output = context.run_ui(
                egui::RawInput {
                    screen_rect: Some(egui::Rect::from_min_size(
                        egui::Pos2::ZERO,
                        egui::vec2(1440.0, 1080.0),
                    )),
                    ..Default::default()
                },
                |ui| {
                    application.draw_cdmw_ui(ui);
                },
            );
            assert!(output.shapes.iter().any(|shape| matches!(&shape.shape,
                egui::Shape::Text(text) if text.galley.job.text == message)));
            output.textures_delta.clear();
        }
    }
    Ok(())
}
