//! The Mesh Editor's side panels take the width their content needs, so the
//! viewport keeps the room beside a docked Texture Editor. Widths come from the
//! painted panels (the viewport between them), not from the production helper.

use super::*;
use egui::containers::panel::PanelState;

const LEFT_HEADERS: [&str; 9] = [
    "Tools",
    "Viewport",
    "Output",
    "Selection",
    "Transform",
    "Sculpt",
    "Mesh Data",
    "Rig",
    "Morph & Refit",
];
// The rail's tool buttons; an open group shows them in a grid at the collapsed width.
const LEFT_TOOLS: [&str; 16] = [
    "Move",
    "Rotate",
    "Scale",
    "Grab",
    "Bend",
    "Smooth",
    "Inflate",
    "Pinch",
    "Vertex Parameters",
    "Topology",
    "Cleanup",
    "Normals & Tangents",
    "UV",
    "Cloth",
    "Jiggle",
    "Rig & Weights",
];
const RIGHT_HEADERS: [&str; 7] = [
    "Inspector",
    "Parts",
    "Translucency (experimental)",
    "Glow (experimental)",
    "Shader experiments",
    "Geometry Layers",
    "Action History",
];
const LANGUAGES: [&str; 14] = [
    "de", "es-ES", "es-419", "fr", "it", "pt-BR", "pl", "ru", "tr", "ja", "ko", "zh-Hans",
    "zh-Hant", "en",
];
// The rail's default and minimum widths, which an open section still gets.
const LEFT_OPEN_DEFAULT: f32 = 264.0;
const LEFT_OPEN_MINIMUM: f32 = 220.0;
const RIGHT_OPEN_DEFAULT: f32 = 340.0;

type Error = Box<dyn std::error::Error>;

fn side_panel_ui(theme: &Value) -> Result<HeadlessUi, Error> {
    // Tall enough that no collapsed header scrolls out of sight.
    let mut ui =
        HeadlessUi::new_integrated_cdmw(triangle_application()?, egui::vec2(1600.0, 1400.0));
    // The material sections appear only with their host state, and Translucency
    // has the longest collapsed header of the Inspector.
    for key in ["translucency", "emission", "shader_controls"] {
        ui.application.cdmw_state[key] = json!({"available": false, "parts": []});
    }
    ui.application.apply_cdmw_theme_payload(theme);
    ui.settle_layout();
    Ok(ui)
}

/// The painted (left, right) panel widths: the room the viewport leaves.
fn panel_widths(ui: &HeadlessUi) -> Result<(f32, f32), Error> {
    let viewport = ui.application.viewport_rect.ok_or("viewport")?;
    Ok((viewport.left(), ui.size.x - viewport.right()))
}

/// A header painted whole inside its side panel; an error when it is clipped or missing.
fn header_rect(ui: &HeadlessUi, label: &str, left: bool) -> Result<Rect, Error> {
    let viewport = ui.application.viewport_rect.ok_or("viewport")?;
    ui.label_rect_where(label, |rect| {
        rect.top() >= viewport.top()
            && rect.bottom() <= viewport.bottom()
            && if left {
                rect.right() <= viewport.left()
            } else {
                rect.left() >= viewport.right()
            }
    })
    .ok_or_else(|| format!("{label:?} is cut off or missing").into())
}

/// Where the laid-out text of the header painted at `rect` ends. A glyph's ink
/// can stop short of its advance (a full-width closing bracket, for example).
fn laid_out_right(ui: &HeadlessUi, label: &str, rect: Rect) -> f32 {
    ui.output
        .shapes
        .iter()
        .find_map(|clipped| match &clipped.shape {
            egui::Shape::Text(text)
                if text.galley.job.text == label && text.visual_bounding_rect() == rect =>
            {
                Some(text.pos.x + text.galley.rect.right())
            }
            _ => None,
        })
        .unwrap_or(rect.right())
        .max(rect.right())
}

/// Where the rail's tool buttons would end in the left panel: two buttons
/// side by side, each as wide as the longest word of any tool name, or Move,
/// Rotate or Scale on one line, after the panel's left margin.
fn widest_tool_button_end(ui: &HeadlessUi, translate: &dyn Fn(&str) -> String) -> f32 {
    let context = &ui.application.egui_context;
    let style = context.global_style();
    let font = egui::TextStyle::Button.resolve(&style);
    let margin = egui::Frame::side_top_panel(&style).total_margin().left;
    let padding = style.spacing.button_padding.x * 2.0;
    let width = |text: &str| {
        context.fonts_mut(|fonts| {
            fonts
                .layout_no_wrap(text.to_owned(), font.clone(), Color32::WHITE)
                .size()
                .x
        })
    };
    let word = LEFT_TOOLS
        .iter()
        .flat_map(|tool| {
            translate(tool)
                .split_whitespace()
                .map(|word| width(word))
                .collect::<Vec<_>>()
        })
        .fold(0.0, f32::max);
    let transform = LEFT_TOOLS[..3]
        .iter()
        .map(|tool| width(&translate(tool)) + padding)
        .fold(0.0, f32::max);
    margin + ((word + padding) * 2.0 + style.spacing.item_spacing.x).max(transform)
}

/// Checks that every collapsed header is whole and that each panel is no wider
/// than its widest header (or, on the left, tool button) plus the padding to
/// its right: the header's button padding, a group frame, the panel's margin
/// and separator line and a solid scroll bar. Returns the panel widths.
fn assert_collapsed_fit(
    ui: &HeadlessUi,
    translate: &dyn Fn(&str) -> String,
    case: &str,
) -> Result<(f32, f32), Error> {
    let (left, right) = panel_widths(ui)?;
    let viewport = ui.application.viewport_rect.ok_or("viewport")?;
    let style = ui.application.egui_context.global_style();
    let scroll = &style.spacing.scroll;
    let padding = style.spacing.button_padding.x
        + egui::Frame::group(&style).total_margin().right
        + egui::Frame::side_top_panel(&style).total_margin().right
        + style.visuals.widgets.noninteractive.bg_stroke.width.round()
        + scroll.bar_inner_margin
        + scroll.bar_width
        + scroll.bar_outer_margin
        + 2.0;
    for (headers, on_left, width) in [
        (&LEFT_HEADERS[..], true, left),
        (&RIGHT_HEADERS[..], false, right),
    ] {
        let panel_left = if on_left { 0.0 } else { viewport.right() };
        let mut widest = if on_left {
            widest_tool_button_end(ui, translate)
        } else {
            0.0_f32
        };
        let mut ends = Vec::new();
        for header in headers {
            let label = translate(header);
            let rect = header_rect(ui, &label, on_left)
                .map_err(|error| format!("{case}: {error}"))?;
            let end = laid_out_right(ui, &label, rect) - panel_left;
            widest = widest.max(end);
            ends.push((*header, end));
        }
        let side = if on_left { "left" } else { "right" };
        assert!(
            width <= widest + padding,
            "{case}: collapsed {side} panel is {width} px for a {widest} px header (+{padding}); {ends:?}"
        );
    }
    Ok((left, right))
}

/// The Parts list's minimum Inspector width, as the panel computed it before
/// it fitted collapsed headers: its Physics, View and Include columns plus 140.
fn parts_list_minimum(ui: &HeadlessUi) -> f32 {
    let context = &ui.application.egui_context;
    let style = context.global_style();
    let font = egui::TextStyle::Body.resolve(&style);
    let header = |text: &str| {
        context.fonts_mut(|fonts| {
            fonts
                .layout_no_wrap(text.to_owned(), font.clone(), Color32::WHITE)
                .size()
                .x
        }) + style.spacing.button_padding.x * 2.0
    };
    let columns = header("Physics").max(58.0)
        + header("View").max(style.spacing.interact_size.y)
        + header("Include").max(style.spacing.interact_size.y);
    (columns + style.spacing.item_spacing.x * 6.0 + 140.0).max(260.0)
}

#[test]
fn collapsed_side_panels_fit_their_headers_in_every_language_up_to_15_pt() -> TestResult {
    let mut ui = side_panel_ui(&json!({"font_point_size": 10.0}))?;
    let (left, right) = assert_collapsed_fit(&ui, &|text| text.to_owned(), "en 10 pt")?;
    assert!(left < LEFT_OPEN_MINIMUM, "collapsed left panel {left}");
    assert!(right < parts_list_minimum(&ui), "collapsed right panel {right}");
    let resources =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../../cdmw/resources/localization");
    for code in LANGUAGES {
        let catalog: Value =
            serde_json::from_slice(&std::fs::read(resources.join(format!("{code}.json")))?)?;
        let translations = catalog["translations"].clone();
        ui.application.apply_cdmw_theme_payload(&json!({
            "language": code, "translations": translations, "font_point_size": 15.0,
        }));
        ui.settle_layout();
        let translate = |source: &str| {
            translations[source]
                .as_str()
                .unwrap_or(source)
                .to_owned()
        };
        assert_collapsed_fit(&ui, &translate, &format!("{code} 15 pt"))?;
    }
    Ok(())
}

/// The painted frame of each tool button, by name, inside the left panel.
fn tool_button_rects(ui: &HeadlessUi, tools: &[&str]) -> Result<Vec<Rect>, Error> {
    tools
        .iter()
        .map(|tool| header_rect(ui, tool, true))
        .collect()
}

#[test]
fn opening_tool_groups_keeps_the_left_panel_compact() -> TestResult {
    let mut ui = side_panel_ui(&json!({"font_point_size": 10.0}))?;
    let (collapsed, _) = panel_widths(&ui)?;
    assert!(
        collapsed < LEFT_OPEN_MINIMUM,
        "collapsed left panel {collapsed}"
    );
    // A group of buttons fits the compact rail: no group widens it.
    for group in ["Transform", "Sculpt", "Mesh Data", "Rig"] {
        ui.click_tool_button(group)?;
        let (open, _) = panel_widths(&ui)?;
        assert!(
            (open - collapsed).abs() <= 1.0,
            "{group} open: left panel {open}, collapsed {collapsed}"
        );
    }
    // Every button is whole inside the compact rail.
    for tools in [&LEFT_TOOLS[0..3], &LEFT_TOOLS[3..8], &LEFT_TOOLS[8..15]] {
        ui.scroll_tool_rail(-2_000.0);
        ui.reveal(tools[0])?;
        tool_button_rects(&ui, tools)?;
    }
    Ok(())
}

#[test]
fn opening_a_tool_page_gives_the_left_panel_its_working_width() -> TestResult {
    let mut ui = side_panel_ui(&json!({"font_point_size": 10.0}))?;
    let (collapsed, _) = panel_widths(&ui)?;
    ui.click_tool_button("Sculpt")?;
    // A brush's sliders get the rail's usual room.
    ui.click_tool_button("Grab")?;
    let (brush, _) = panel_widths(&ui)?;
    assert!(
        (brush - LEFT_OPEN_DEFAULT).abs() <= 1.0,
        "Grab open: left panel {brush}"
    );
    ui.reveal("Radius px")?;
    // Collapsing the section gives the room back to the viewport.
    ui.click_tool_button("Sculpt")?;
    let (closed, _) = panel_widths(&ui)?;
    assert!(
        (closed - collapsed).abs() <= 1.0,
        "Sculpt closed: left panel {closed}, collapsed {collapsed}"
    );
    Ok(())
}

#[test]
fn opening_the_parts_list_gives_the_right_panel_its_list_width() -> TestResult {
    let mut ui = side_panel_ui(&json!({"font_point_size": 10.0}))?;
    let minimum = parts_list_minimum(&ui);
    let (_, collapsed) = panel_widths(&ui)?;
    assert!(collapsed < minimum, "collapsed right panel {collapsed} < {minimum}");
    ui.click("Parts")?;
    ui.settle_layout();
    let (_, open) = panel_widths(&ui)?;
    assert!(
        open >= minimum && (open - RIGHT_OPEN_DEFAULT).abs() <= 1.0,
        "Parts open: right panel {open}, list minimum {minimum}"
    );
    for column in ["View", "Include"] {
        header_rect(&ui, column, false)?;
    }
    ui.click("Back to Inspector")?;
    ui.settle_layout();
    let (_, closed) = panel_widths(&ui)?;
    assert!(
        (closed - collapsed).abs() <= 1.0,
        "Parts closed: right panel {closed}, collapsed {collapsed}"
    );
    Ok(())
}

#[test]
fn collapsed_side_panels_give_remembered_widths_to_the_viewport() -> TestResult {
    let mut ui = side_panel_ui(&json!({"font_point_size": 10.0}))?;
    crate::cdmw_layout::restore(
        &ui.application.egui_context,
        &json!({"cdmw_tool_rail": 319.0, "cdmw_right_panels": 507.0}),
    );
    ui.settle_layout();
    let (left, right) = assert_collapsed_fit(&ui, &|text| text.to_owned(), "remembered widths")?;
    let viewport = ui.application.viewport_rect.ok_or("viewport")?;
    assert!(
        (viewport.width() - (ui.size.x - left - right)).abs() <= 1.0
            && viewport.width() >= ui.size.x - 319.0 - 507.0 + 300.0,
        "viewport {} beside {left} and {right} px panels",
        viewport.width()
    );
    // The remembered widths come back as soon as a page needs the room.
    ui.click_tool_button("Sculpt")?;
    ui.click_tool_button("Grab")?;
    ui.click("Parts")?;
    ui.settle_layout();
    let (left, right) = panel_widths(&ui)?;
    assert!(
        (left - 319.0).abs() <= 1.0 && (right - 507.0).abs() <= 1.0,
        "opened: {left} and {right}"
    );
    for (key, expected) in [("cdmw_tool_rail", 319.0), ("cdmw_right_panels", 507.0)] {
        let panel =
            PanelState::load(&ui.application.egui_context, egui::Id::new(key)).ok_or(key)?;
        assert!(
            (panel.size().x - expected).abs() <= 1.0,
            "{key}: {panel:?}"
        );
    }
    Ok(())
}
