use super::*;
use crate::shortcuts::{Binding, NumpadKey, ShortcutAction};

/// egui-winit on Windows reports Ctrl as both `ctrl` and `command`.
const CTRL: egui::Modifiers = egui::Modifiers {
    alt: false,
    ctrl: true,
    shift: false,
    mac_cmd: false,
    command: true,
};

fn key(key: egui::Key, pressed: bool, modifiers: egui::Modifiers) -> Event {
    Event::Key {
        key,
        physical_key: None,
        pressed,
        repeat: false,
        modifiers,
    }
}

fn press(ui: &mut HeadlessUi, pressed: egui::Key, modifiers: egui::Modifiers) {
    ui.frame(vec![key(pressed, true, modifiers)]);
    ui.frame(vec![key(pressed, false, modifiers)]);
}

/// The window loop records numpad presses beside the top-row key egui reports.
fn press_numpad(ui: &mut HeadlessUi, digit: u8, modifiers: egui::Modifiers) {
    let reported = egui::Key::from_name(&digit.to_string()).expect("digit key");
    ui.application
        .shortcut_numpad_presses
        .push((reported, NumpadKey::Digit(digit)));
    press(ui, reported, modifiers);
}

fn integrated_triangle() -> Result<HeadlessUi, Box<dyn std::error::Error>> {
    Ok(HeadlessUi::new_integrated_cdmw(
        triangle_application()?,
        egui::vec2(1_440.0, 900.0),
    ))
}

#[test]
fn tool_keys_open_the_tool_a_click_opens_and_escape_returns_to_orbit() -> TestResult {
    let mut ui = integrated_triangle()?;
    for (pressed, modifiers, page, tool) in [
        (
            egui::Key::Q,
            egui::Modifiers::NONE,
            CdmwRailPage::Select,
            ViewportTool::Select,
        ),
        (
            egui::Key::G,
            egui::Modifiers::NONE,
            CdmwRailPage::Move,
            ViewportTool::Move,
        ),
        (
            egui::Key::R,
            egui::Modifiers::NONE,
            CdmwRailPage::Rotate,
            ViewportTool::Rotate,
        ),
        (
            egui::Key::S,
            egui::Modifiers::NONE,
            CdmwRailPage::Scale,
            ViewportTool::Scale,
        ),
        (
            egui::Key::G,
            egui::Modifiers::SHIFT,
            CdmwRailPage::Grab,
            ViewportTool::Grab,
        ),
        (
            egui::Key::W,
            egui::Modifiers::SHIFT,
            CdmwRailPage::Bend,
            ViewportTool::Bend,
        ),
        (
            egui::Key::S,
            egui::Modifiers::SHIFT,
            CdmwRailPage::Smooth,
            ViewportTool::Smooth,
        ),
        (
            egui::Key::I,
            egui::Modifiers::NONE,
            CdmwRailPage::Inflate,
            ViewportTool::Inflate,
        ),
        (
            egui::Key::P,
            egui::Modifiers::NONE,
            CdmwRailPage::Pinch,
            ViewportTool::Pinch,
        ),
    ] {
        press(&mut ui, pressed, modifiers);
        assert_eq!(
            ui.application.cdmw_rail_page,
            Some(page),
            "{pressed:?} {modifiers:?}"
        );
        assert_eq!(
            ui.application.viewport_tool, tool,
            "{pressed:?} {modifiers:?}"
        );
        assert!(!ui.application.cdmw_orbit_mode);
    }
    // A collapsed rail opens a floating panel first; Escape closes that before Orbit.
    for _ in 0..3 {
        if ui.application.cdmw_rail_page.is_none() {
            break;
        }
        press(&mut ui, egui::Key::Escape, egui::Modifiers::NONE);
    }
    assert_eq!(ui.application.cdmw_rail_page, None);
    assert!(ui.application.cdmw_orbit_mode);
    Ok(())
}

#[test]
fn shortcuts_wait_while_a_text_field_has_focus() -> TestResult {
    let mut ui = integrated_triangle()?;
    ui.application.shortcut_editor.open = true;
    ui.frame(Vec::new());
    ui.application
        .egui_context
        .memory_mut(|memory| memory.request_focus(egui::Id::new("cdmw-shortcut-search")));
    ui.frame(Vec::new());
    press(&mut ui, egui::Key::G, egui::Modifiers::NONE);
    assert_ne!(ui.application.cdmw_rail_page, Some(CdmwRailPage::Move));
    ui.application
        .egui_context
        .memory_mut(|memory| memory.surrender_focus(egui::Id::new("cdmw-shortcut-search")));
    ui.frame(Vec::new());
    press(&mut ui, egui::Key::G, egui::Modifiers::NONE);
    assert_eq!(ui.application.cdmw_rail_page, Some(CdmwRailPage::Move));
    Ok(())
}

#[test]
fn numpad_keys_turn_the_view_while_top_row_digits_choose_the_target() -> TestResult {
    let mut ui = integrated_triangle()?;
    press(&mut ui, egui::Key::Num2, egui::Modifiers::NONE);
    assert_eq!(ui.application.selection_domain, SelectionDomain::Edge);
    press(&mut ui, egui::Key::Num3, egui::Modifiers::NONE);
    assert_eq!(ui.application.selection_domain, SelectionDomain::Face);
    for (digit, modifiers) in [
        (1, egui::Modifiers::NONE),
        (7, CTRL),
        (3, egui::Modifiers::NONE),
    ] {
        let before = ui.application.camera.revision();
        press_numpad(&mut ui, digit, modifiers);
        assert!(
            ui.application.camera.revision() > before,
            "Num{digit} {modifiers:?}"
        );
        assert_eq!(
            ui.application.selection_domain,
            SelectionDomain::Face,
            "Num{digit}"
        );
    }
    assert!(ui.application.selection_visible_only);
    press(&mut ui, egui::Key::Z, egui::Modifiers::SHIFT);
    assert!(
        !ui.application.selection_visible_only,
        "Shift+Z switches to X-Ray"
    );
    press(&mut ui, egui::Key::Z, egui::Modifiers::SHIFT);
    assert!(ui.application.selection_visible_only);
    let before = ui.application.camera.revision();
    press(&mut ui, egui::Key::F, egui::Modifiers::NONE);
    assert!(
        ui.application.camera.revision() > before,
        "F frames the mesh"
    );
    Ok(())
}

#[test]
fn history_keys_follow_the_undo_and_redo_buttons() -> TestResult {
    let mut ui = integrated_triangle()?;
    press(&mut ui, egui::Key::Z, CTRL);
    assert_eq!(ui.application.status, "No Mesh Editor action to undo");
    ui.application.cdmw_state["undo_count"] = json!(1);
    ui.application.cdmw_state["redo_count"] = json!(1);
    for (pressed, modifiers, undo) in [
        (egui::Key::Z, CTRL, true),
        (egui::Key::Z, CTRL | egui::Modifiers::SHIFT, false),
        (egui::Key::Y, CTRL, false),
    ] {
        ui.last_actions.clear();
        press(&mut ui, pressed, modifiers);
        assert!(
            ui.last_actions.iter().any(|action| if undo {
                matches!(action, UiAction::Undo)
            } else {
                matches!(action, UiAction::Redo)
            }),
            "{pressed:?} {modifiers:?}: {:?}",
            ui.last_actions
        );
    }
    Ok(())
}

#[test]
fn shift_click_toggles_and_ctrl_drag_subtracts_without_changing_the_dropdown() -> TestResult {
    let mut ui = integrated_triangle()?;
    press(&mut ui, egui::Key::Q, egui::Modifiers::NONE);
    press(&mut ui, egui::Key::Num1, egui::Modifiers::NONE);
    ui.application.selection_tool = SelectionTool::Click;
    ui.application.brush_radius = 6.0;
    ui.projected_point(SelectionDomain::Vertex)?;
    let points = ui
        .application
        .projection
        .as_ref()
        .ok_or("projection")?
        .interaction
        .elements
        .iter()
        .filter(|element| matches!(element.handle, ProjectedHandle::Vertex(_)))
        .map(|element| element.position)
        .collect::<Vec<_>>();
    assert_eq!(points.len(), 3);
    // The modifier is released in the same frame as the click, as when a frame on a
    // dense mesh runs only after the user has let go of Shift: the press-time set counts.
    let click = |ui: &mut HeadlessUi, point: Vec2, modifiers: egui::Modifiers| {
        let position = egui::pos2(point.x, point.y);
        ui.frame(vec![
            Event::ModifiersChanged(modifiers),
            Event::PointerMoved(position),
            Event::PointerButton {
                pos: position,
                button: PointerButton::Primary,
                pressed: true,
                modifiers,
            },
            Event::PointerButton {
                pos: position,
                button: PointerButton::Primary,
                pressed: false,
                modifiers,
            },
            Event::ModifiersChanged(egui::Modifiers::NONE),
        ]);
        ui.frame(Vec::new());
    };
    let selected = |ui: &HeadlessUi| {
        ui.application
            .mesh
            .as_ref()
            .map_or(0, |mesh| mesh.selection.vertices.len())
    };
    click(&mut ui, points[0], egui::Modifiers::NONE);
    assert_eq!(selected(&ui), 1);
    click(&mut ui, points[1], egui::Modifiers::SHIFT);
    assert_eq!(selected(&ui), 2, "{}", ui.application.status);
    click(&mut ui, points[0], egui::Modifiers::SHIFT);
    assert_eq!(
        selected(&ui),
        1,
        "Shift+click on a selected vertex removes it"
    );
    assert_eq!(
        ui.application.selection_operation,
        SelectionOperation::Replace
    );

    press(&mut ui, egui::Key::B, egui::Modifiers::NONE);
    assert_eq!(ui.application.selection_tool, SelectionTool::Rectangle);
    let minimum = points
        .iter()
        .fold(Vec2::splat(f32::MAX), |low, point| low.min(*point))
        - Vec2::splat(20.0);
    let maximum = points
        .iter()
        .fold(Vec2::splat(f32::MIN), |high, point| high.max(*point))
        + Vec2::splat(20.0);
    let start = egui::pos2(minimum.x, minimum.y);
    let end = egui::pos2(maximum.x, maximum.y);
    ui.frame(vec![
        Event::ModifiersChanged(CTRL),
        Event::PointerMoved(start),
        Event::PointerButton {
            pos: start,
            button: PointerButton::Primary,
            pressed: true,
            modifiers: CTRL,
        },
        Event::PointerMoved(end),
        Event::PointerButton {
            pos: end,
            button: PointerButton::Primary,
            pressed: false,
            modifiers: CTRL,
        },
        Event::ModifiersChanged(egui::Modifiers::NONE),
    ]);
    ui.frame(Vec::new());
    assert_eq!(
        selected(&ui),
        0,
        "Ctrl+drag subtracts: {}",
        ui.application.status
    );
    assert_eq!(
        ui.application.selection_operation,
        SelectionOperation::Replace
    );
    Ok(())
}

#[test]
fn rebinding_moves_a_used_key_and_applies_at_once() -> TestResult {
    let mut ui = integrated_triangle()?;
    ui.application.shortcut_editor.open = true;
    ui.application.shortcut_editor.capture = Some((ShortcutAction::ToolScale, 0));
    press(&mut ui, egui::Key::G, egui::Modifiers::NONE);
    assert_eq!(ui.application.shortcut_editor.capture, None);
    assert!(
        ui.application
            .shortcut_editor
            .notice
            .as_deref()
            .is_some_and(|notice| notice.contains("Move"))
    );
    assert_eq!(
        ui.application.cdmw_rail_page, None,
        "a captured key does not also run"
    );
    press(&mut ui, egui::Key::G, egui::Modifiers::NONE);
    assert_eq!(ui.application.cdmw_rail_page, Some(CdmwRailPage::Scale));
    let saved = ui.application.shortcut_keymap.overrides_value();
    assert_eq!(saved["tool.scale"], json!(["G"]));
    assert_eq!(saved["tool.move"], json!([]));

    // Reserved keys are refused with a reason; Escape cancels; Backspace clears.
    ui.application.shortcut_editor.capture = Some((ShortcutAction::ToolRotate, 0));
    press(&mut ui, egui::Key::C, CTRL);
    assert!(ui.application.shortcut_editor.notice.is_some());
    assert_eq!(
        ui.application
            .shortcut_keymap
            .hint(ShortcutAction::ToolRotate)
            .as_deref(),
        Some("R")
    );
    ui.application.shortcut_editor.capture = Some((ShortcutAction::ToolRotate, 0));
    press(&mut ui, egui::Key::Escape, egui::Modifiers::NONE);
    assert_eq!(
        ui.application
            .shortcut_keymap
            .hint(ShortcutAction::ToolRotate)
            .as_deref(),
        Some("R")
    );
    ui.application.shortcut_editor.capture = Some((ShortcutAction::ToolRotate, 0));
    press(&mut ui, egui::Key::Backspace, egui::Modifiers::NONE);
    assert_eq!(
        ui.application
            .shortcut_keymap
            .hint(ShortcutAction::ToolRotate),
        None
    );

    // A changed selection modifier takes over at once.
    ui.application.shortcut_keymap.assign(
        ShortcutAction::ExtendModifier,
        0,
        Binding::parse("Alt").ok_or("Alt")?,
    );
    ui.application.shortcut_editor.open = false;
    press(&mut ui, egui::Key::Q, egui::Modifiers::NONE);
    ui.application.primary_press_modifiers = egui::Modifiers::ALT;
    assert_eq!(
        ui.application.held_selection_operation(),
        SelectionOperation::Toggle
    );
    ui.application.primary_press_modifiers = egui::Modifiers::SHIFT;
    assert_eq!(
        ui.application.held_selection_operation(),
        SelectionOperation::Replace
    );
    Ok(())
}

#[test]
fn read_only_sessions_keep_view_keys_and_refuse_edit_tools() -> TestResult {
    let mut ui = integrated_triangle()?;
    ui.application.cdmw_state["authoring_enabled"] = json!(false);
    ui.application.cdmw_state["output_policy_reason"] = json!("Choose an output route first.");
    ui.frame(Vec::new());
    press(&mut ui, egui::Key::G, egui::Modifiers::NONE);
    assert_ne!(ui.application.cdmw_rail_page, Some(CdmwRailPage::Move));
    assert_eq!(ui.application.status, "Choose an output route first.");
    press(&mut ui, egui::Key::Q, egui::Modifiers::NONE);
    assert_eq!(ui.application.cdmw_rail_page, Some(CdmwRailPage::Select));
    let before = ui.application.camera.revision();
    press(&mut ui, egui::Key::Home, egui::Modifiers::NONE);
    assert!(ui.application.camera.revision() > before);
    Ok(())
}
