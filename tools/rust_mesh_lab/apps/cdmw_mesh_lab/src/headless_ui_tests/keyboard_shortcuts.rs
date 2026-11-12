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

#[test]
fn the_command_palette_chord_goes_to_cdmw_even_while_typing() -> TestResult {
    let mut ui = integrated_triangle()?;
    let root = tempfile::tempdir()?;
    let mut bridge = CdmwBridge::for_test(root.path().to_path_buf(), "palette", 1, 0);
    let messages = bridge.capture_messages_for_test();
    ui.application.cdmw_bridge = Some(bridge);
    let ctrl_shift = egui::Modifiers {
        shift: true,
        ..CTRL
    };
    ui.application.shortcut_editor.open = true;
    ui.frame(Vec::new());
    ui.application
        .egui_context
        .memory_mut(|memory| memory.request_focus(egui::Id::new("cdmw-shortcut-search")));
    ui.frame(Vec::new());
    press(&mut ui, egui::Key::P, ctrl_shift);
    let sent = std::iter::from_fn(|| {
        messages
            .recv_timeout(std::time::Duration::from_secs(5))
            .ok()
    })
    .find(|message| message["event"] == "app_shortcut")
    .expect("app_shortcut sent to CDMW");
    assert_eq!(sent["command"], "command_palette");
    assert_eq!(sent["protocol"], cdmw_session::PROTOCOL);
    Ok(())
}

#[test]
fn cdmw_mirrors_the_editor_s_commands_and_can_run_one() -> TestResult {
    let mut ui = integrated_triangle()?;
    let root = tempfile::tempdir()?;
    let mut bridge = CdmwBridge::for_test(root.path().to_path_buf(), "commands", 1, 0);
    let messages = bridge.capture_messages_for_test();
    ui.application.cdmw_bridge = Some(bridge);
    ui.frame(Vec::new());
    let state = std::iter::from_fn(|| {
        messages
            .recv_timeout(std::time::Duration::from_secs(5))
            .ok()
    })
    .find(|message| message["event"] == "commands_state")
    .expect("commands_state sent to CDMW");
    let commands = state["commands"].as_array().expect("command list");
    let grab = commands
        .iter()
        .find(|command| command["id"] == "tool.move")
        .expect("tool.move listed");
    assert_eq!(grab["keys"], json!(["G"]));
    assert_eq!(grab["label"], "Move");
    assert_eq!(commands.len(), crate::shortcuts::SHORTCUTS.len());
    // An unchanged state is not sent again.
    ui.frame(Vec::new());
    assert!(
        messages
            .recv_timeout(std::time::Duration::from_millis(200))
            .map_or(true, |message| message["event"] != "commands_state")
    );
    // The palette's request runs the command as its key press does.
    ui.application
        .pending_host_commands
        .push("tool.move".to_owned());
    ui.frame(Vec::new());
    assert_eq!(ui.application.cdmw_rail_page, Some(CdmwRailPage::Move));
    Ok(())
}

#[test]
fn run_command_must_name_an_editor_command() {
    let root = tempfile::tempdir().expect("temporary directory");
    let mut bridge = CdmwBridge::for_test(root.path().to_path_buf(), "commands", 1, 0);
    let message = |command: &str| {
        json!({"event": "run_command", "protocol": cdmw_session::PROTOCOL, "session_id": "commands",
               "process_generation": 1, "command": command})
    };
    assert!(matches!(
        bridge.decode_host_event_for_test(message("tool.move")),
        HostEvent::RunCommand(command) if command == "tool.move"
    ));
    assert!(matches!(
        bridge.decode_host_event_for_test(message("delete.everything")),
        HostEvent::Fatal(_)
    ));
}

/// CDMW's Shortcuts page lists the editor's commands from this file when no
/// editor runs. Set CDMW_WRITE_MESH_COMMANDS=1 to rewrite it after changing the keymap.
#[test]
fn the_committed_command_list_matches_the_editor_s_keymap() {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../../../cdmw/resources/mesh_editor_commands.json");
    let expected = crate::cdmw_ui::keyboard::mesh_editor_commands_resource();
    let text = serde_json::to_string_pretty(&expected).expect("json") + "\n";
    if std::env::var("CDMW_WRITE_MESH_COMMANDS").as_deref() == Ok("1") {
        std::fs::write(&path, &text).expect("write the command list");
    }
    let committed: Value =
        serde_json::from_str(&std::fs::read_to_string(&path).expect("read the command list"))
            .expect("valid json");
    assert_eq!(
        committed, expected,
        "cdmw/resources/mesh_editor_commands.json is stale; rerun with CDMW_WRITE_MESH_COMMANDS=1"
    );
}
