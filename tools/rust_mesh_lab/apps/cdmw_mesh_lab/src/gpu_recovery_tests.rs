use super::*;

#[test]
fn renderer_failure_preserves_authoring_geometry_and_camera() -> headless_tests::TestResult {
    let mut application = headless_tests::triangle_application()?;
    let before = application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .draw_snapshot();
    let camera = application
        .camera
        .view_projection(headless_tests::viewport());
    application.renderer_failed("simulated device removal".into());
    let after = application
        .mesh
        .as_ref()
        .ok_or("mesh lost after GPU failure")?
        .draw_snapshot();
    assert_eq!(before.positions, after.positions);
    assert_eq!(before.indices, after.indices);
    assert_eq!(before.draw_revision, after.draw_revision);
    assert_eq!(
        camera,
        application
            .camera
            .view_projection(headless_tests::viewport())
    );
    assert!(application.renderer.is_none());
    assert!(application.status.contains("simulated device removal"));
    application.handle_cdmw_host_event(HostEvent::RendererRetry);
    assert!(application.gpu_recovery.deadline().is_some());
    assert!(!application.cdmw_exit_requested);
    assert_eq!(
        before.positions,
        application.mesh.as_ref().unwrap().draw_snapshot().positions
    );
    Ok(())
}
