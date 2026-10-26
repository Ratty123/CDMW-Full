//! Every application theme keeps controls, their states and status text apart.
//! The palettes are a copy of the host's theme table; a Python test keeps it current.
use super::*;

fn palettes() -> serde_json::Map<String, Value> {
    serde_json::from_str(include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/tests/fixtures/ui-theme-palettes.json"
    )))
    .expect("theme palette fixture")
}

#[test]
fn every_theme_distinguishes_controls_states_and_status_text() {
    let palettes = palettes();
    assert!(palettes.len() >= 19, "missing application themes");
    for (key, palette) in palettes {
        let application = crate::headless_tests::triangle_application().expect("application");
        application.apply_cdmw_theme_payload(&json!({"theme": key, "palette": palette}));
        let context = &application.egui_context;
        let visuals = context.style_of(context.theme()).visuals.clone();
        let text = visuals.widgets.inactive.fg_stroke.color;
        let button = visuals.widgets.inactive.weak_bg_fill;
        let panel = visuals.panel_fill;

        // Disabled controls fade enough to look unavailable but stay readable.
        let alpha = visuals.disabled_alpha;
        let faded = cdmw_mix(button, panel, alpha);
        let enabled = cdmw_contrast(text, button);
        let disabled = cdmw_contrast(cdmw_mix(text, faded, alpha), faded);
        assert!(disabled >= 4.4, "{key}: disabled text {disabled:.2}:1");
        assert!(disabled <= enabled * 0.75, "{key}: disabled {disabled:.2} vs enabled {enabled:.2}");

        // Primary, destructive and selected controls keep readable labels.
        let accent = visuals.hyperlink_color;
        let accent_text = context
            .data(|data| data.get_temp::<Color32>(egui::Id::new(CDMW_ACCENT_TEXT)))
            .expect("theme accent text");
        assert!(cdmw_contrast(accent_text, accent) >= 4.5, "{key}: primary label");
        assert!(cdmw_contrast(cdmw_danger_colour(&visuals), button) >= 4.5, "{key}: destructive label");
        assert_ne!(cdmw_danger_colour(&visuals), text, "{key}: destructive label is not tinted");
        assert!(cdmw_contrast(visuals.selection.stroke.color, visuals.selection.bg_fill) >= 4.5, "{key}: selected label");

        // Values read as fields, and slider rails and fills stand out from the panel.
        assert!(cdmw_contrast(text, visuals.text_edit_bg_color()) >= 4.5, "{key}: value text");
        assert!(cdmw_contrast(cdmw_slider_rail(&visuals), panel) >= 3.0, "{key}: slider rail");
        assert!(cdmw_contrast(accent, panel) >= 3.0, "{key}: slider fill");

        // Status colours chosen for dark themes read on light themes too.
        for status in [REFIT_BODY_COLOUR, REFIT_ARMOR_COLOUR, REFIT_READY_COLOUR, Color32::from_rgb(245, 105, 105)] {
            let readable = cdmw_readable_in(&visuals, status);
            for background in [panel, visuals.window_fill] {
                assert!(cdmw_contrast(readable, background) >= 4.5, "{key}: status {status:?} on {background:?}");
            }
        }
    }
}
