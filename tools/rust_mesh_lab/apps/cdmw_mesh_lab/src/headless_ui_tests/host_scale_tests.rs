//! The embedded editor draws at the UI scale of the screen CDMW's Qt host is on,
//! not at the scale winit kept for the child window when it was created.

use super::*;

/// The physical pixel size Qt draws a point size at on a screen with this device
/// pixel ratio: points at 96 logical pixels per inch, times the ratio.
fn qt_text_pixels(points: f32, device_pixel_ratio: f32) -> f32 {
    points * 96.0 / 72.0 * device_pixel_ratio
}

/// One frame as `LabApplication::redraw` runs it: the host scale is synced first,
/// then egui-winit sizes the screen by the window scale times egui's zoom.
fn redraw(ui: &mut HeadlessUi, window_scale: f32, physical: egui::Vec2) -> FullOutput {
    ui.application.sync_cdmw_host_scale(window_scale);
    let input_scale = ui
        .application
        .egui_pixels_per_point(f64::from(window_scale)) as f32;
    let mut input = egui::RawInput {
        screen_rect: Some(Rect::from_min_size(Pos2::ZERO, physical / input_scale)),
        ..Default::default()
    };
    input
        .viewports
        .entry(egui::ViewportId::ROOT)
        .or_default()
        .native_pixels_per_point = Some(window_scale);
    let context = ui.application.egui_context.clone();
    let mut output = context.run_ui(input, |root| {
        ui.application.draw_cdmw_ui(root);
    });
    output.textures_delta.clear();
    output
}

fn painted_text_sizes(output: &FullOutput) -> Vec<f32> {
    output
        .shapes
        .iter()
        .filter_map(|shape| match &shape.shape {
            egui::Shape::Text(text) => Some(text),
            _ => None,
        })
        .flat_map(|text| {
            text.galley
                .job
                .sections
                .iter()
                .map(|section| section.format.font_id.size)
        })
        .collect()
}

#[test]
fn host_scale_sets_pixels_per_point_and_text_matches_qt_on_either_monitor() -> TestResult {
    let mut ui =
        HeadlessUi::new_integrated_cdmw(triangle_application()?, egui::vec2(1400.0, 1000.0));
    let physical = egui::vec2(2100.0, 1500.0);

    // A standalone run (no host scale) keeps winit's own scale.
    ui.application
        .apply_cdmw_theme_payload(&json!({"font_point_size": 8.0}));
    let output = redraw(&mut ui, 1.5, physical);
    assert!((output.pixels_per_point - 1.5).abs() < 0.0001);

    // Fredric's screens: 144 dpi (150 %) and 96 dpi. The child window keeps the
    // scale of the monitor it was created on (`window`) while CDMW is on `host`.
    for (window_scale, host_scale) in [
        (1.0, 1.5), // created on the 96 dpi screen, CDMW now on the 150 % one
        (1.0, 1.0), // CDMW moved to the 96 dpi screen
        (1.5, 1.0), // created on the 150 % screen, CDMW now on the 96 dpi one
        (1.5, 1.5), // and back again
        (1.5, 1.25),
        (1.0, 2.0),
    ] {
        ui.application
            .apply_cdmw_theme_payload(&json!({"font_point_size": 8.0, "scale": host_scale}));
        for _ in 0..2 {
            let output = redraw(&mut ui, window_scale, physical);
            assert!(
                (output.pixels_per_point - host_scale).abs() < 0.0001,
                "window {window_scale}, host {host_scale}: egui drew at {} pixels per point",
                output.pixels_per_point
            );
            let body =
                ui.application.egui_context.global_style().text_styles[&egui::TextStyle::Body].size;
            assert!(
                painted_text_sizes(&output)
                    .iter()
                    .any(|size| (size - body).abs() < 0.01),
                "the editor paints body text"
            );
            let egui_pixels = body * output.pixels_per_point;
            let qt_pixels = qt_text_pixels(8.0, host_scale);
            assert!(
                (egui_pixels - qt_pixels).abs() < 0.01,
                "window {window_scale}, host {host_scale}: 8 pt is {egui_pixels} px in the \
                 editor and {qt_pixels} px in Qt"
            );
            let content = ui
                .application
                .egui_context
                .input(|input| input.content_rect().size());
            assert!(
                (content - physical / host_scale).length() < 0.01,
                "window {window_scale}, host {host_scale}: content {content:?}"
            );
        }
        // Raw viewport pointer events (orbit, gizmo, lasso) map physical pixels
        // with the same scale egui uses, so they land where egui drew the viewport.
        let input_scale = ui.application.egui_pixels_per_point(window_scale.into());
        ui.application.capture_viewport_pointer_event(
            &WindowEvent::CursorMoved {
                device_id: DeviceId::dummy(),
                position: winit::dpi::PhysicalPosition::new(600.0, 450.0),
            },
            input_scale,
        );
        let point = ui
            .application
            .raw_pointer_position
            .ok_or("pointer position")?;
        assert!(
            (point - Vec2::new(600.0, 450.0) / host_scale).length() < 0.001,
            "window {window_scale}, host {host_scale}: pointer at {point:?}"
        );
    }
    Ok(())
}
