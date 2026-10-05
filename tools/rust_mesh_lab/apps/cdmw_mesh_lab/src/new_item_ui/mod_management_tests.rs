use super::*;

fn node(name: &str, kind: &str, text: &str) -> Node {
    Node {
        id: name.into(),
        name: name.into(),
        kind: kind.into(),
        label: text.into(),
        enabled: true,
        revision: 7,
        props: json!({"text":text}),
        ..Default::default()
    }
}

fn fixture(long: bool) -> State {
    let mut root = node("mod_management_workspace", "column", "");
    root.children = vec![
        node("SectionTitle", "label", "Mod Management"),
        node("mod_management_game_label", "label", "Game folder"),
        node(
            "mod_management_game_folder",
            "text",
            "C:/a deliberately long path/Steam/steamapps/common/Crimson Desert",
        ),
        node("mod_management_choose_game", "button", "Change…"),
    ];
    let mut overview = node("mod_management_overview", "column", "");
    for (key, label) in [
        ("enabled", "Enabled"),
        ("disabled", "Disabled"),
        ("attention", "Needs review"),
    ] {
        overview
            .children
            .push(node(&format!("mod_management_count_{key}"), "label", "1"));
        overview.children.push(node(
            &format!("mod_management_count_label_{key}"),
            "label",
            label,
        ));
    }
    for (key, label, buttons) in [
        (
            "installs",
            "Install & manage",
            [
                ("independent", "Install item package"),
                ("installed", "Installed mods"),
            ],
        ),
        (
            "packages",
            "Package tools",
            [("repackage", "Repackage mods"), ("merge", "Merge mods")],
        ),
        (
            "maintenance",
            "Maintenance",
            [("updates", "Check game updates"), ("recovery", "Recovery")],
        ),
    ] {
        let mut group = node(&format!("mod_management_group_{key}"), "group", label);
        let mut column = node("", "column", "");
        column.children = buttons
            .iter()
            .map(|(key, label)| {
                node(
                    &format!("mod_management_open_{key}"),
                    "button",
                    &if long {
                        format!("{label} — längere übersetzte Beschriftung")
                    } else {
                        (*label).into()
                    },
                )
            })
            .collect();
        group.children.push(column);
        overview.children.push(group);
    }
    overview.children.extend([
        node("mod_management_archives_title", "label", "Archive folders"),
        node("mod_management_show_game", "check", "Show game archives"),
        node("mod_management_refresh", "button", "Refresh"),
    ]);
    let mut table = node("mod_management_archives", "table", "");
    table.props = json!({"columns":[{"text":"Folder"},{"text":"Managed by"},{"text":"Status"}],
        "folder_states":{"0037":"found","dmmgen":"missing"},"rows":[
        {"cells":[{"text":"0037"},{"text":"CDMW"},{"text":"Found"}]},
        {"cells":[{"text":"dmmgen"},{"text":"Other manager"},{"text":"Missing files"}]}]});
    overview.children.push(table);
    let mut pages = node("mod_management_pages", "tabs", "");
    pages.props = json!({"selected":0,"tabs":[{"text":"Overview"},{"text":"Installed mods"},{"text":"Independent items"},
        {"text":"Repackage"},{"text":"Merge"},{"text":"Game updates"},{"text":"Recovery"}]});
    pages.children.push(overview);
    root.children.push(pages);
    serde_json::from_value(
        json!({"protocol":super::super::super::model::PROTOCOL,"session":"owned-management-layout",
        "generation":1,"root":root,"theme":{"font_pixels":14,"dark":true}}),
    )
    .unwrap()
}

fn frame(
    ctx: &egui::Context,
    view: &mut PresentationView,
    state: &State,
    size: Vec2,
    events: Vec<egui::Event>,
) -> egui::FullOutput {
    let mut output = ctx.run_ui(
        egui::RawInput {
            screen_rect: Some(Rect::from_min_size(egui::Pos2::ZERO, size)),
            events,
            ..Default::default()
        },
        |ui| view.draw(ui, state),
    );
    output.textures_delta.clear();
    output
}

#[test]
fn grouped_management_controls_fit_widths_fonts_and_translated_captions() {
    for long in [false, true] {
        for font in [11.0_f32, 14.0, 18.0, 28.0] {
            for width in [1920.0, 1366.0, 1024.0, 736.0, 480.0, 360.0] {
                let ctx = egui::Context::default();
                apply_theme(&ctx, &json!({"font_pixels":font,"dark":true}));
                let mut view = PresentationView::default();
                let state = fixture(long);
                let size = vec2(width, 1080.0);
                for _ in 0..3 {
                    frame(&ctx, &mut view, &state, size, vec![]);
                }
                assert!(view.errors.is_empty(), "{:?}", view.errors);
                let actions: Vec<_> = view
                    .rects
                    .iter()
                    .filter(|r| r.id.starts_with("mod_management_open_"))
                    .collect();
                assert_eq!(actions.len(), 6);
                for control in &view.rects {
                    let [x, _, w, _] = control.rect;
                    assert!(
                        x >= -0.5 && x + w <= width + 0.5,
                        "{width}/{font}/{long}: {} {:?}",
                        control.id,
                        control.rect
                    );
                }
                for (index, first) in actions.iter().enumerate() {
                    let a = Rect::from_min_size(
                        pos2(first.rect[0], first.rect[1]),
                        vec2(first.rect[2], first.rect[3]),
                    );
                    let text = ctx.fonts_mut(|fonts| {
                        fonts.layout(
                            first.label.clone(),
                            FontId::proportional((13.0 * font / 14.0).max(11.0)),
                            Color32::WHITE,
                            (first.rect[2] - 60.0 * font / 14.0).max(1.0),
                        )
                    });
                    assert!(
                        text.size().y + 18.0 * font / 14.0 <= first.rect[3] + 0.5,
                        "Caption clipped: {} {:?} {:?}",
                        first.id,
                        text.size(),
                        first.rect
                    );
                    for second in actions.iter().skip(index + 1) {
                        let b = Rect::from_min_size(
                            pos2(second.rect[0], second.rect[1]),
                            vec2(second.rect[2], second.rect[3]),
                        );
                        let overlap = a.intersect(b);
                        assert!(
                            overlap.width() <= 0.5 || overlap.height() <= 0.5,
                            "Buttons overlap at {width}/{font}: {} {} {a:?} {b:?}",
                            first.id,
                            second.id
                        );
                    }
                    assert!(first.rect[3] >= 39.0 * font / 14.0);
                }
            }
        }
    }
}

#[test]
fn grouped_management_clicks_use_original_authority_and_disabled_state() {
    let ctx = egui::Context::default();
    apply_theme(&ctx, &json!({"font_pixels":14,"dark":true}));
    let mut view = PresentationView::default();
    let mut state = fixture(false);
    let size = vec2(1200.0, 900.0);
    for _ in 0..3 {
        frame(&ctx, &mut view, &state, size, vec![]);
    }
    for key in [
        "independent",
        "installed",
        "repackage",
        "merge",
        "updates",
        "recovery",
    ] {
        let id = format!("mod_management_open_{key}");
        let rect = view.rects.iter().find(|r| r.id == id).unwrap().rect;
        let point = pos2(rect[0] + rect[2] / 2.0, rect[1] + rect[3] / 2.0);
        for pressed in [true, false] {
            frame(
                &ctx,
                &mut view,
                &state,
                size,
                vec![
                    egui::Event::PointerMoved(point),
                    egui::Event::PointerButton {
                        pos: point,
                        button: egui::PointerButton::Primary,
                        pressed,
                        modifiers: egui::Modifiers::NONE,
                    },
                ],
            );
        }
        assert!(
            view.inputs.iter().any(|input| input.control == id
                && input.revision == 7
                && input.action == "activate")
        );
    }
    state.native_modal = true;
    let rect = view
        .rects
        .iter()
        .find(|r| r.id == "mod_management_open_independent")
        .unwrap()
        .rect;
    let point = pos2(rect[0] + 20.0, rect[1] + 20.0);
    for pressed in [true, false] {
        frame(
            &ctx,
            &mut view,
            &state,
            size,
            vec![
                egui::Event::PointerMoved(point),
                egui::Event::PointerButton {
                    pos: point,
                    button: egui::PointerButton::Primary,
                    pressed,
                    modifiers: egui::Modifiers::NONE,
                },
            ],
        );
    }
    assert!(view.inputs.is_empty());
}

#[test]
fn grouped_management_short_windows_can_scroll_to_every_action() {
    for (width, pixels) in [(520.0, 14.0), (360.0, 28.0)] {
        let ctx = egui::Context::default();
        apply_theme(&ctx, &json!({"font_pixels":pixels,"dark":true}));
        let state = fixture(false);
        let mut view = PresentationView::default();
        let size = vec2(width, 400.0);
        let mut seen = std::collections::BTreeSet::new();
        for step in 0..50 {
            let events = if step < 3 {
                vec![]
            } else {
                vec![
                    egui::Event::PointerMoved(pos2(width - 20.0, 200.0)),
                    egui::Event::MouseWheel {
                        unit: egui::MouseWheelUnit::Point,
                        delta: vec2(0.0, -100.0),
                        phase: egui::TouchPhase::Move,
                        modifiers: egui::Modifiers::NONE,
                    },
                ]
            };
            frame(&ctx, &mut view, &state, size, events);
            for control in &view.rects {
                if control.id.starts_with("mod_management_open_")
                    && control.rect[1] >= control.clip[1]
                    && control.rect[1] + control.rect[3] <= control.clip[1] + control.clip[3]
                {
                    seen.insert(control.id.clone());
                }
            }
            if seen.len() == 6 {
                break;
            }
        }
        assert_eq!(
            seen.len(),
            6,
            "Unreachable action at {width}/{pixels}: {seen:?}"
        );
    }
}

#[test]
fn grouped_management_monitor_scale_changes_keep_buttons_and_pointer_aligned() {
    let ctx = egui::Context::default();
    let mut state = fixture(false);
    apply_theme(&ctx, &state.theme);
    let mut view = PresentationView::default();
    for (window_scale, host_scale) in [(1.5, 1.0), (1.5, 1.25), (1.5, 1.5), (1.5, 2.0), (2.0, 1.0)]
    {
        state.theme["pixels_per_point"] = json!(host_scale);
        let mut point_pixels = egui::Pos2::ZERO;
        for pressed in [None, None, Some(true), Some(false)] {
            super::super::super::sync_host_scale(&ctx, &state.theme, window_scale);
            let input_scale = window_scale * ctx.zoom_factor();
            let size = vec2(2560.0, 1440.0) / input_scale;
            let mut input = egui::RawInput {
                screen_rect: Some(Rect::from_min_size(egui::Pos2::ZERO, size)),
                ..Default::default()
            };
            input
                .viewports
                .entry(egui::ViewportId::ROOT)
                .or_default()
                .native_pixels_per_point = Some(window_scale);
            if let Some(pressed) = pressed {
                let point = point_pixels / input_scale;
                input.events = vec![
                    egui::Event::PointerMoved(point),
                    egui::Event::PointerButton {
                        pos: point,
                        button: egui::PointerButton::Primary,
                        pressed,
                        modifiers: egui::Modifiers::NONE,
                    },
                ];
            }
            let mut output = ctx.run_ui(input, |ui| view.draw(ui, &state));
            output.textures_delta.clear();
            assert!((output.pixels_per_point - host_scale).abs() < 0.001);
            let button = view
                .rects
                .iter()
                .find(|r| r.id == "mod_management_open_recovery")
                .unwrap();
            assert!(button.rect[0] + button.rect[2] <= size.x);
            assert!(button.rect[1] + button.rect[3] <= size.y);
            point_pixels = pos2(
                button.rect[0] + button.rect[2] / 2.0,
                button.rect[1] + button.rect[3] / 2.0,
            ) * host_scale;
        }
        assert!(
            view.inputs
                .iter()
                .any(|input| input.control == "mod_management_open_recovery"
                    && input.action == "activate")
        );
    }
}

#[test]
fn grouped_management_other_pages_keep_navigation_and_operation_controls() {
    let ctx = egui::Context::default();
    let mut state = fixture(false);
    apply_theme(&ctx, &state.theme);
    let pages = state
        .root
        .children
        .iter_mut()
        .find(|node| node.name == "mod_management_pages")
        .unwrap();
    pages.props["selected"] = json!(4);
    let mut pane = node("merge-pane", "column", "");
    pane.children
        .push(node("merge-existing-action", "button", "Compare mods"));
    pages.children = vec![pane];
    let mut bar = node("mod_management_operation_bar", "row", "");
    bar.children
        .push(node("cancel-existing-operation", "button", "Cancel"));
    state.root.children.push(bar);
    let mut view = PresentationView::default();
    let size = vec2(960.0, 720.0);
    for _ in 0..3 {
        frame(&ctx, &mut view, &state, size, vec![]);
    }
    for id in ["merge-existing-action", "cancel-existing-operation"] {
        let control = view.rects.iter().find(|rect| rect.id == id).unwrap();
        assert!(
            control.rect[1] >= 0.0 && control.rect[1] + control.rect[3] <= size.y,
            "{control:?}"
        );
    }
    let tabs: Vec<_> = view
        .rects
        .iter()
        .filter(|rect| rect.id == "mod_management_pages")
        .collect();
    assert_eq!(tabs.len(), 7);
    let rect = tabs[1].rect;
    let point = pos2(rect[0] + rect[2] / 2.0, rect[1] + rect[3] / 2.0);
    for pressed in [true, false] {
        frame(
            &ctx,
            &mut view,
            &state,
            size,
            vec![
                egui::Event::PointerMoved(point),
                egui::Event::PointerButton {
                    pos: point,
                    button: egui::PointerButton::Primary,
                    pressed,
                    modifiers: egui::Modifiers::NONE,
                },
            ],
        );
    }
    assert!(
        view.inputs
            .iter()
            .any(|input| input.control == "mod_management_pages"
                && input.action == "tab"
                && input.value == json!(1))
    );
}
