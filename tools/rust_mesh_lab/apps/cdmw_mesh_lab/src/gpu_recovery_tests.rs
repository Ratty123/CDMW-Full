use super::*;

#[test]
fn skipped_surface_frames_retain_font_uploads_until_rendered() {
    let context = egui::Context::default();
    let first = context.run_ui(egui::RawInput::default(), |ui| {
        ui.label("Fresh font glyphs ABCxyz123");
    });
    let mut pending = first.textures_delta;
    assert!(!pending.set.is_empty());
    let mut font_updates = pending.clone();
    for _ in 0..3 {
        let result = render_pending_egui_textures(&mut pending, |textures| {
            assert!(*textures == font_updates);
            Err::<(), _>("surface occluded")
        });
        assert!(result.is_err());
    }
    let next = context.run_ui(egui::RawInput::default(), |ui| {
        ui.label("Fresh font glyphs ABCxyz123");
    });
    assert!(next.textures_delta.is_empty());
    pending.append(next.textures_delta);
    render_pending_egui_textures(&mut pending, |textures| {
        assert!(*textures == font_updates);
        Ok::<(), &str>(())
    })
    .unwrap();
    assert!(pending.is_empty());
    font_updates.clear();
}

#[test]
fn skipped_surface_frame_merges_image_updates_and_frees() {
    let mut pending = egui::TexturesDelta::default();
    let image_id = egui::TextureId::Managed(3);
    let removed_id = egui::TextureId::Managed(4);
    let image = |colour| {
        egui::epaint::ImageDelta::full(
            egui::ColorImage::filled([2, 2], colour),
            egui::TextureOptions::LINEAR,
        )
    };
    pending.push(image_id, image(egui::Color32::RED));
    pending.push(removed_id, image(egui::Color32::BLUE));
    assert!(render_pending_egui_textures(&mut pending, |_| Err::<(), _>("timeout")).is_err());
    let mut next = egui::TexturesDelta::default();
    next.push(image_id, image(egui::Color32::GREEN));
    next.free(removed_id);
    pending.append(next);
    render_pending_egui_textures(&mut pending, |textures| {
        assert_eq!(textures.set.len(), 1);
        assert_eq!(textures.set[&image_id].len(), 1);
        assert!(textures.set[&image_id][0].image == image(egui::Color32::GREEN).image);
        assert!(textures.free.contains(&removed_id));
        Ok::<(), &str>(())
    })
    .unwrap();
    assert!(pending.is_empty());
}

#[test]
fn closing_with_pending_texture_updates_is_safe() -> headless_tests::TestResult {
    let mut application = headless_tests::triangle_application()?;
    let output = application
        .egui_context
        .run_ui(egui::RawInput::default(), |ui| {
            ui.label("Closing before the first surface frame");
        });
    application
        .pending_egui_textures
        .append(output.textures_delta);
    assert!(!application.pending_egui_textures.is_empty());
    drop(application);
    Ok(())
}

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
