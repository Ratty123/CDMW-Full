use super::*;
use crate::new_item_ui::model::PROTOCOL;

fn control(id: &str, kind: &str, label: &str, props: Value) -> Node {
    Node {
        id: id.into(),
        revision: 1,
        kind: kind.into(),
        label: label.into(),
        enabled: true,
        props,
        ..Default::default()
    }
}

fn state(root: Node) -> State {
    serde_json::from_value(json!({"protocol":PROTOCOL,"session":"owned-headless-ui",
        "generation":1,"root":root,"theme":{"font_pixels":14,"language":"en"}}))
    .unwrap()
}

fn frame(
    context: &egui::Context,
    view: &mut PresentationView,
    state: &State,
    size: Vec2,
    events: Vec<egui::Event>,
) {
    let input = egui::RawInput {
        screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, size)),
        events,
        ..Default::default()
    };
    let mut output = context.run_ui(input, |ui| view.draw(ui, state));
    output.textures_delta.clear();
}

fn click(context: &egui::Context, view: &mut PresentationView, state: &State, point: egui::Pos2) {
    for pressed in [true, false] {
        frame(
            context,
            view,
            state,
            egui::vec2(960.0, 720.0),
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
}

#[test]
fn host_font_and_button_colors_are_used_without_hover_expansion() {
    let context = egui::Context::default();
    for font in [11.0, 13.0, 22.0] {
        for dark in [false, true] {
            apply_theme(
                &context,
                &json!({"dark":dark,"font_pixels":font,
                "button":"#234567","button_hover":"#345678","button_pressed":"#123456",
                "button_border":"#789abc"}),
            );
            let style = context.style_of(if dark {
                egui::Theme::Dark
            } else {
                egui::Theme::Light
            });
            assert_eq!(style.text_styles[&TextStyle::Body].size, font as f32);
            assert_eq!(style.text_styles[&TextStyle::Button].size, font as f32);
            for (visuals, expected) in [
                (&style.visuals.widgets.inactive, "#234567"),
                (&style.visuals.widgets.hovered, "#345678"),
                (&style.visuals.widgets.active, "#123456"),
                (&style.visuals.widgets.open, "#123456"),
            ] {
                assert_eq!(visuals.bg_fill, Color32::from_hex(expected).unwrap());
                assert_eq!(visuals.weak_bg_fill, visuals.bg_fill);
                assert_eq!(visuals.expansion, 0.0);
                assert_eq!(
                    visuals.bg_stroke,
                    egui::Stroke::new(1.0, Color32::from_hex("#789abc").unwrap())
                );
            }
            let mut view = PresentationView::default();
            let state = state(control("button", "button", "Continue", json!({})));
            for _ in 0..3 {
                frame(
                    &context,
                    &mut view,
                    &state,
                    egui::vec2(960.0, 720.0),
                    vec![],
                );
            }
            let rect = view.rects[0].rect;
            frame(
                &context,
                &mut view,
                &state,
                egui::vec2(960.0, 720.0),
                vec![egui::Event::PointerMoved(egui::pos2(
                    rect[0] + 5.0,
                    rect[1] + 5.0,
                ))],
            );
            assert_eq!(view.rects[0].rect, rect);
        }
    }
}

#[test]
fn actual_egui_button_click_preserves_identity_and_disabled_state() {
    let context = egui::Context::default();
    let mut view = PresentationView::default();
    let mut state = state(control(
        "button",
        "button",
        "Build plan",
        json!({"primary":true}),
    ));
    apply_theme(&context, &state.theme);
    for _ in 0..3 {
        frame(
            &context,
            &mut view,
            &state,
            egui::vec2(960.0, 720.0),
            vec![],
        );
    }
    let rect = view
        .rects
        .iter()
        .find(|rect| rect.id == "button")
        .unwrap()
        .rect;
    let point = egui::pos2(rect[0] + rect[2] / 2.0, rect[1] + rect[3] / 2.0);
    click(&context, &mut view, &state, point);
    assert_eq!(view.inputs.len(), 1);
    assert_eq!(
        (
            &*view.inputs[0].control,
            view.inputs[0].revision,
            view.inputs[0].action
        ),
        ("button", 1, "activate")
    );
    state.root.enabled = false;
    click(&context, &mut view, &state, point);
    assert!(view.inputs.is_empty());
}

#[test]
fn acknowledged_text_does_not_erase_newer_typing_and_external_edits_replace_it() {
    let mut view = PresentationView::default();
    assert_eq!(view.edit_text("name", 1, ""), "");
    view.edits.get_mut("name").unwrap().value = "ABC".into();
    view.acknowledge(&Input::new(
        &control("name", "text", "", json!({})),
        "text",
        json!("A"),
    ));
    assert_eq!(view.edit_text("name", 2, "A"), "ABC");
    // A selection/model metadata revision with identical authority is harmless.
    assert_eq!(view.edit_text("name", 3, "A"), "ABC");
    assert_eq!(
        view.edit_text("name", 4, "Externally changed"),
        "Externally changed"
    );
    view.reject_edits();
    assert!(view.edits.is_empty());
}

#[test]
fn typing_into_a_clicked_field_survives_idle_frames_and_host_acknowledgements() {
    let context = egui::Context::default();
    let mut view = PresentationView::default();
    let mut state = state(control(
        "name",
        "text",
        "Name",
        json!({"text":"", "maximum":32767}),
    ));
    apply_theme(&context, &state.theme);
    for _ in 0..3 {
        frame(
            &context,
            &mut view,
            &state,
            egui::vec2(960.0, 720.0),
            vec![],
        );
    }
    let rect = view
        .rects
        .iter()
        .find(|rect| rect.id == "name")
        .unwrap()
        .rect;
    click(
        &context,
        &mut view,
        &state,
        egui::pos2(rect[0] + 30.0, rect[1] + rect[3] / 2.0),
    );
    let mut expected = String::new();
    for character in ["N", "a", "m", "e"] {
        expected.push_str(character);
        frame(
            &context,
            &mut view,
            &state,
            egui::vec2(960.0, 720.0),
            vec![egui::Event::Text(character.into())],
        );
        let input = view
            .inputs
            .iter()
            .find(|input| input.action == "text")
            .expect("Click then keyboard text must emit an edit");
        assert_eq!(input.value, json!(expected));
        view.acknowledge(&input.clone());
        state.root.revision += 1;
        state.root.props["text"] = json!(expected);
        for _ in 0..3 {
            frame(
                &context,
                &mut view,
                &state,
                egui::vec2(960.0, 720.0),
                vec![],
            );
        }
    }
}

#[test]
fn navigation_finishes_the_focused_field_before_hiding_its_page() {
    let context = egui::Context::default();
    let mut view = PresentationView::default();
    let mut root = control("root", "column", "", json!({}));
    root.children = vec![
        control(
            "steps",
            "steps",
            "",
            json!({"selected":1,"steps":[{"text":"Template"},{"text":"Identity"}]}),
        ),
        control("name", "text", "Name", json!({"text":""})),
    ];
    let state = state(root);
    apply_theme(&context, &state.theme);
    for _ in 0..3 {
        frame(
            &context,
            &mut view,
            &state,
            egui::vec2(960.0, 720.0),
            vec![],
        );
    }
    let rect = view
        .rects
        .iter()
        .find(|rect| rect.id == "name")
        .unwrap()
        .rect;
    click(
        &context,
        &mut view,
        &state,
        egui::pos2(rect[0] + 20.0, rect[1] + rect[3] / 2.0),
    );
    let rect = view
        .rects
        .iter()
        .find(|rect| rect.id == "steps")
        .unwrap()
        .rect;
    let point = egui::pos2(rect[0] + 20.0, rect[1] + rect[3] / 2.0);
    frame(
        &context,
        &mut view,
        &state,
        egui::vec2(960.0, 720.0),
        vec![
            egui::Event::PointerMoved(point),
            egui::Event::PointerButton {
                pos: point,
                button: egui::PointerButton::Primary,
                pressed: true,
                modifiers: egui::Modifiers::NONE,
            },
            egui::Event::PointerButton {
                pos: point,
                button: egui::PointerButton::Primary,
                pressed: false,
                modifiers: egui::Modifiers::NONE,
            },
        ],
    );
    assert_eq!(
        view.inputs
            .iter()
            .map(|input| input.action)
            .collect::<Vec<_>>(),
        vec!["finish_edit", "tab"]
    );
    assert_eq!(view.inputs[0].control, "name");
    assert_eq!(view.inputs[1].value, json!(0));
}

#[test]
fn footer_stays_visible_and_grid_preserves_columns_at_small_and_large_sizes() {
    let mut grid = control("grid", "grid", "", json!({}));
    for row in 0..30 {
        for column in 0..3 {
            let mut value = control(
                &format!("field-{row}-{column}"),
                "number",
                "Position",
                json!({"value":0,"minimum":-100,"maximum":100}),
            );
            value.cell = Some([row, column, 1, 1]);
            grid.children.push(value);
        }
    }
    let mut root = control("workspace", "workspace", "", json!({}));
    grid.slot = "body".into();
    let mut back = control("back", "button", "Back", json!({}));
    back.slot = "back".into();
    let mut next = control("next", "button", "Continue", json!({"primary":true}));
    next.slot = "next".into();
    root.children = vec![grid, back, next];
    let state = state(root);
    for size in [egui::vec2(720.0, 480.0), egui::vec2(1440.0, 960.0)] {
        let context = egui::Context::default();
        let mut view = PresentationView::default();
        apply_theme(&context, &state.theme);
        for _ in 0..3 {
            frame(&context, &mut view, &state, size, vec![]);
        }
        for id in ["back", "next"] {
            let rect = view.rects.iter().find(|rect| rect.id == id).unwrap().rect;
            assert!(
                rect[1] > size.y - 80.0 && rect[1] + rect[3] <= size.y,
                "{id}: {rect:?}, {size:?}"
            );
        }
        let xs: Vec<_> = (0..3)
            .map(|column| {
                view.rects
                    .iter()
                    .find(|rect| rect.id == format!("field-0-{column}"))
                    .unwrap()
                    .rect[0]
            })
            .collect();
        assert!(xs[1] > xs[0] + 100.0 && xs[2] > xs[1] + 100.0, "{xs:?}");
        assert!(view.errors.is_empty());
    }
}

#[test]
fn model_validation_and_revision_lookup_reach_embedded_controls() {
    let mut root = control(
        "tabs",
        "tabs",
        "",
        json!({"corners":[control("corner","button","Library",json!({}))]}),
    );
    assert_eq!(root.find_revision("corner"), Some(1));
    let mut nested = control("leaf", "button", "", json!({}));
    for _ in 0..65 {
        let mut parent = control("", "column", "", json!({}));
        parent.children.push(nested);
        nested = parent;
    }
    root.props["corners"] = json!([nested]);
    assert!(state(root).validate("owned-headless-ui").is_err());
}

#[cfg(windows)]
#[test]
fn windows_ui_fonts_cover_latin_cyrillic_and_cjk_item_names() {
    let context = egui::Context::default();
    let mut view = PresentationView::default();
    let state = state(control(
        "name",
        "text",
        "Name",
        json!({"text":"刀剣 中文 한국어 Кириллица Ö"}),
    ));
    apply_theme(&context, &state.theme);
    frame(
        &context,
        &mut view,
        &state,
        egui::vec2(960.0, 720.0),
        vec![],
    );
    assert!(context.fonts_mut(|fonts| {
        fonts.has_glyphs(&FontId::proportional(14.0), "刀剣中文한국어КириллицаÖ")
    }));
}

#[test]
fn confirmation_enter_uses_its_original_default_and_escape_closes_only_top_dialog() {
    let context = egui::Context::default();
    let mut view = PresentationView::default();
    let mut state = state(control("workspace", "column", "", json!({})));
    let mut dialog = control("confirmation", "dialog", "Apply owned fixture?", json!({}));
    dialog.children = vec![
        control("yes", "button", "Yes", json!({})),
        control("no", "button", "No", json!({"default":true})),
    ];
    state.dialogs.push(dialog);
    apply_theme(&context, &state.theme);
    for _ in 0..3 {
        frame(
            &context,
            &mut view,
            &state,
            egui::vec2(960.0, 720.0),
            vec![],
        );
    }
    let event = |key| egui::Event::Key {
        key,
        physical_key: None,
        pressed: true,
        repeat: false,
        modifiers: egui::Modifiers::NONE,
    };
    frame(
        &context,
        &mut view,
        &state,
        egui::vec2(960.0, 720.0),
        vec![event(egui::Key::Enter)],
    );
    assert_eq!(view.inputs.len(), 1);
    assert_eq!(view.inputs[0].control, "no");
    assert_eq!(view.inputs[0].action, "activate");
    frame(
        &context,
        &mut view,
        &state,
        egui::vec2(960.0, 720.0),
        vec![event(egui::Key::Escape)],
    );
    assert_eq!(view.inputs.len(), 1);
    assert_eq!(view.inputs[0].control, "confirmation");
    assert_eq!(view.inputs[0].action, "close_dialog");
}

#[test]
fn table_pointer_selection_and_keyboard_navigation_reach_the_original_view() {
    let context = egui::Context::default();
    let mut view = PresentationView::default();
    let state = state(control(
        "items",
        "table",
        "",
        json!({
        "columns":[{"index":0,"width":240}],"total":2,"offset":0,
        "rows":[{"path":[0],"cells":[{"text":"First","enabled":true,"selectable":true}]},
                {"path":[1],"cells":[{"text":"Second","enabled":true,"selectable":true}]}]}),
    ));
    apply_theme(&context, &state.theme);
    for _ in 0..3 {
        frame(
            &context,
            &mut view,
            &state,
            egui::vec2(960.0, 720.0),
            vec![],
        );
    }
    click(&context, &mut view, &state, egui::pos2(100.0, 15.0));
    assert!(
        view.inputs
            .iter()
            .any(|input| input.action == "select" && input.value["path"] == json!([0]))
    );
    frame(
        &context,
        &mut view,
        &state,
        egui::vec2(960.0, 720.0),
        vec![egui::Event::Key {
            key: egui::Key::ArrowDown,
            physical_key: None,
            pressed: true,
            repeat: false,
            modifiers: egui::Modifiers::NONE,
        }],
    );
    assert!(
        view.inputs
            .iter()
            .any(|input| input.action == "key" && input.value["key"] == "Down")
    );
}

#[test]
fn template_selection_can_transfer_focus_to_search_without_deadlocking() {
    let context = egui::Context::default();
    let mut view = PresentationView::default();
    let state = template_results_state(900, 0, false);
    apply_theme(&context, &state.theme);
    let size = egui::vec2(960.0, 720.0);
    for _ in 0..3 { frame(&context, &mut view, &state, size, vec![]); }
    let rect = view.rects.iter().find(|rect| rect.id == "matches").unwrap().rect;
    let row = egui::pos2(rect[0] + 100.0, rect[1] + 40.0);
    click(&context, &mut view, &state, row);
    assert!(view.inputs.iter().any(|input| input.action == "select"));
    frame(&context, &mut view, &state, size, vec![]);
    let focus = view.table_focus["matches"];
    assert!(context.memory(|memory| memory.has_focus(focus)));

    // Pressing Find transfers focus before the table is drawn. Reading input
    // inside the table's memory transaction used to deadlock this frame.
    let rect = view.rects.iter().find(|rect| rect.id == "find").unwrap().rect;
    click(&context, &mut view, &state, egui::pos2(rect[0] + 50.0, rect[1] + rect[3] / 2.0));
    assert!(!context.memory(|memory| memory.has_focus(focus)));
    frame(&context, &mut view, &state, size, vec![egui::Event::Text("Dragon".into())]);
    assert!(view.inputs.iter().any(|input| input.control == "find"
        && input.action == "text" && input.value == "Dragon"));
    click(&context, &mut view, &state, row);
    assert!(view.inputs.iter().any(|input| input.action == "select"));
}

#[test]
fn reopened_effect_library_recovers_zero_size_without_resetting_dragged_panes() {
    let mut split = control("effects-split", "split", "", json!({
        "horizontal":true,"sizes":[0,900],"indices":[0,1]}));
    split.children = vec![control("library", "viewport", "", json!({})),
                          control("effect-view", "viewport", "", json!({}))];
    let mut state = state(split);
    let context = egui::Context::default();
    let mut view = PresentationView::default();
    apply_theme(&context, &state.theme);
    let size = egui::vec2(1440.0, 900.0);
    for _ in 0..3 { frame(&context, &mut view, &state, size, vec![]); }
    assert!(view.portals[0].rect[2] > 300.0, "{:?}", view.portals);
    view.split_sizes.insert("effects-split".into(), (1, vec![350.0, 1000.0]));
    let library = state.root.children.remove(0);
    state.root.props["indices"] = json!([1]);
    state.root.props["sizes"] = json!([0,900]);
    frame(&context, &mut view, &state, size, vec![]);
    state.root.children.insert(0, library);
    state.root.props["indices"] = json!([0,1]);
    for _ in 0..3 { frame(&context, &mut view, &state, size, vec![]); }
    let width = view.portals[0].rect[2];
    assert!(width > 300.0 && width < 450.0, "dragged ratio was lost: {width}");
}

#[test]
fn checked_and_empty_cells_keep_editors_aligned_with_their_column() {
    let mut table = control("emitters", "table", "", json!({"headers":true,"total":2,
        "columns":[{"index":0,"text":"Use","width":60},
                   {"index":1,"text":"Property","width":200},
                   {"index":2,"text":"Value","width":180}]}));
    table.props["rows"] = json!((0..2).map(|row| json!({"path":[row],"cells":[
        if row == 0 {json!({"text":"","check":0,"enabled":true})} else {json!({"text":"","enabled":false})},
        {"text":"Spawn maximum","enabled":true},
        {"control":control(&format!("value-{row}"),"number","",json!({"value":8,"minimum":0,"maximum":10000}))}
    ]})).collect::<Vec<_>>());
    let state = state(table);
    let context = egui::Context::default();
    let mut view = PresentationView::default();
    apply_theme(&context, &state.theme);
    for _ in 0..3 { frame(&context, &mut view, &state, egui::vec2(960.0,720.0), vec![]); }
    let first = view.rects.iter().find(|item| item.id == "value-0").unwrap();
    let second = view.rects.iter().find(|item| item.id == "value-1").unwrap();
    assert!((first.rect[0] - second.rect[0]).abs() < 1.0, "{first:?} {second:?}");
}

#[test]
fn column_drag_keeps_the_full_distance_on_release_and_after_row_updates() {
    let context = egui::Context::default();
    let mut view = PresentationView::default();
    let mut state = state(control("table", "table", "", json!({
        "headers": true, "sortable": true, "columns": [
            {"index":0,"width":100,"text":"Internal name","resizable":true},
            {"index":1,"width":100,"text":"Name","resizable":true}],
        "total":1,"rows":[{"path":[0],"cells":[
            {"control":control("first-column", "progress", "", json!({"value":50}))}, {"text":"Name"}]}]
    })));
    apply_theme(&context, &state.theme);
    let size = egui::vec2(960.0, 720.0);
    for _ in 0..3 { frame(&context, &mut view, &state, size, vec![]); }
    let column = view.rects.iter().find(|item| item.id == "first-column").unwrap();
    let initial_width = column.rect[2];
    let edge = column.rect[0] + initial_width;
    for (x, pressed) in [(edge, Some(true)), (edge + 40.0, None), (edge + 80.0, None), (edge + 80.0, Some(false))] {
        let point = egui::pos2(x, 13.0);
        let mut events = vec![egui::Event::PointerMoved(point)];
        if let Some(pressed) = pressed {
            events.push(egui::Event::PointerButton {pos:point,button:egui::PointerButton::Primary,
                pressed,modifiers:egui::Modifiers::NONE});
        }
        frame(&context, &mut view, &state, size, events);
    }
    let resize = view.inputs.iter().find(|input| input.action == "resize_column").expect("header drag");
    assert_eq!(resize.value["column"], 0);
    assert_eq!(resize.value["width"], (initial_width + 80.0).round() as u64);
    state.root.revision += 1;
    state.root.props["columns"][0]["width"] = resize.value["width"].clone();
    frame(&context, &mut view, &state, size, vec![]);
    assert_eq!(view.column_widths[&("table".into(), 0)], initial_width + 80.0);

    // Windows can deliver the final move and release before the next paint.
    let start = egui::pos2(edge + 80.0, 13.0);
    let end = egui::pos2(edge + 140.0, 13.0);
    frame(&context, &mut view, &state, size, vec![
        egui::Event::PointerMoved(start), egui::Event::PointerButton {
            pos:start,button:egui::PointerButton::Primary,pressed:true,modifiers:egui::Modifiers::NONE}]);
    frame(&context, &mut view, &state, size, vec![
        egui::Event::PointerMoved(end), egui::Event::PointerButton {
            pos:end,button:egui::PointerButton::Primary,pressed:false,modifiers:egui::Modifiers::NONE}]);
    let resize = view.inputs.iter().find(|input| input.action == "resize_column").expect("coalesced header drag");
    assert_eq!(resize.value["width"], (initial_width + 140.0).round() as u64);

    frame(&context, &mut view, &state, size, vec![]);
    let start = egui::pos2(edge + 140.0, 13.0);
    let end = egui::pos2(edge + 60.0, 13.0);
    frame(&context, &mut view, &state, size, vec![
        egui::Event::PointerMoved(start), egui::Event::PointerButton {
            pos:start,button:egui::PointerButton::Primary,pressed:true,modifiers:egui::Modifiers::NONE},
        egui::Event::PointerMoved(end)]);
    frame(&context, &mut view, &state, size, vec![egui::Event::PointerButton {
            pos:end,button:egui::PointerButton::Primary,pressed:false,modifiers:egui::Modifiers::NONE}]);
    let resize = view.inputs.iter().find(|input| input.action == "resize_column").expect("press and first move in one frame");
    assert_eq!(resize.value["width"], (initial_width + 60.0).round() as u64);

    frame(&context, &mut view, &state, size, vec![]);
    let start = egui::pos2(edge + 60.0, 13.0);
    let end = egui::pos2(edge + 100.0, 13.0);
    frame(&context, &mut view, &state, size, vec![
        egui::Event::PointerMoved(start), egui::Event::PointerButton {
            pos:start,button:egui::PointerButton::Primary,pressed:true,modifiers:egui::Modifiers::NONE},
        egui::Event::PointerMoved(end), egui::Event::PointerButton {
            pos:end,button:egui::PointerButton::Primary,pressed:false,modifiers:egui::Modifiers::NONE}]);
    assert_eq!(view.inputs.len(), 1);
    assert_eq!(view.inputs[0].action, "resize_column");
    assert_eq!(view.inputs[0].value["width"], (initial_width + 100.0).round() as u64);

    state.root.enabled = false;
    frame(&context, &mut view, &state, size, vec![]);
    let start = egui::pos2(edge + 100.0, 13.0);
    let end = egui::pos2(edge + 20.0, 13.0);
    frame(&context, &mut view, &state, size, vec![
        egui::Event::PointerMoved(start), egui::Event::PointerButton {
            pos:start,button:egui::PointerButton::Primary,pressed:true,modifiers:egui::Modifiers::NONE},
        egui::Event::PointerMoved(end), egui::Event::PointerButton {
            pos:end,button:egui::PointerButton::Primary,pressed:false,modifiers:egui::Modifiers::NONE}]);
    assert!(view.inputs.is_empty());
    assert_eq!(view.column_widths[&("table".into(), 0)], initial_width + 100.0);
}

#[test]
fn table_headers_and_rows_align_left_and_stretch_columns_leave_room_for_editors() {
    for font in [14.0, 22.0] {
        for width in [520.0, 1100.0] {
            for (heading, value) in [("Money item", "Money_Copper"), ("Inherent bonus", "BuffLevel_HPRegen")] {
                let context = egui::Context::default();
                let mut view = PresentationView::default();
                let mut state = state(control("table", "table", "", json!({
                    "headers":true,"row_headers":true,"total":2,"grow_y":true,
                    "columns":[{"index":0,"text":heading,"width":2400,"stretch":true},
                               {"index":1,"text":"Parameter level","width":100}],
                    "rows":[{"path":[0],"label":"1","cells":[{"text":value},
                             {"text":"98765","editable":true,"enabled":true}]},
                            {"path":[1],"label":"2","cells":[{"text":"Another item"},
                             {"control":control("last-editor","number","",json!({"value":99}))}]}]
                })));
                state.theme["font_pixels"] = json!(font);
                apply_theme(&context, &state.theme);
                let size = egui::vec2(width, 600.0);
                for _ in 0..3 { frame(&context, &mut view, &state, size, vec![]); }
                let output = context.run_ui(egui::RawInput {
                    screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, size)),
                    ..Default::default()
                }, |ui| view.draw(ui, &state));
                let texts: Vec<_> = output.shapes.iter().filter_map(|shape| match &shape.shape {
                    egui::epaint::Shape::Text(text) => Some(text), _ => None,
                }).collect();
                let heading_text = texts.iter().find(|text| text.galley.job.text == heading).expect("full heading");
                let value_text = texts.iter().find(|text| text.galley.job.text == value).expect("full name");
                assert!((value_text.pos.x - heading_text.pos.x).abs() <= 1.0, "header={} row={} width={width} font={font}", heading_text.pos.x, value_text.pos.x);
                assert!(value_text.pos.x < 60.0, "row must start at the left of its column");
                let field = texts.iter().find(|text| text.galley.job.text == "98765").expect("editable price");
                assert!(field.pos.x + field.galley.size().x < width);
                let editor = view.rects.iter().find(|item| item.id == "last-editor").unwrap();
                assert!(editor.rect[0] + editor.rect[2] <= width, "{editor:?}");
            }
        }
    }
}

#[test]
fn content_columns_keep_effect_headings_and_values_readable() {
    for (width, font) in [(560.0, 14.0), (820.0, 22.0)] {
        let context = egui::Context::default();
        let mut view = PresentationView::default();
        let mut state = state(control("effects", "table", "", json!({
            "headers":true,"sortable":true,"sort_column":0,"total":1,
            "columns":[{"index":0,"text":"Category","width":1000,"size_to_contents":true},
                       {"index":1,"text":"Effect","width":2400,"stretch":true},
                       {"index":2,"text":"Type","width":1000,"size_to_contents":true},
                       {"index":3,"text":"Size","width":1000,"size_to_contents":true}],
            "rows":[{"path":[0],"cells":[{"text":"Lightning"},{"text":"Cast 1 · Lightning"},
                    {"text":"Unknown"},{"text":"31×41.5×3"}]}]
        })));
        state.theme["font_pixels"] = json!(font);
        apply_theme(&context, &state.theme);
        let size = egui::vec2(width, 600.0);
        for _ in 0..3 { frame(&context, &mut view, &state, size, vec![]); }
        let output = context.run_ui(egui::RawInput {
            screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, size)),
            ..Default::default()
        }, |ui| view.draw(ui, &state));
        for expected in ["Category ▴", "Lightning", "Effect", "Cast 1 · Lightning", "Type", "Unknown", "Size", "31×41.5×3"] {
            let (clip, text) = output.shapes.iter().find_map(|shape| match &shape.shape {
                egui::epaint::Shape::Text(text) if text.galley.job.text == expected => Some((shape.clip_rect, text)),
                _ => None,
            }).unwrap_or_else(|| panic!("missing {expected}"));
            assert!(!text.galley.elided, "{expected} is truncated at {width}px");
            assert!(text.pos.x + text.galley.size().x <= clip.right() + 1.0, "{expected} is clipped");
        }
    }
}

#[test]
fn compact_choice_popup_fits_category_names_and_preserves_selection() {
    for font in [14.0, 22.0] {
        for width in [320.0, 960.0] {
            let context = egui::Context::default();
            let mut root = control("filters", "row", "", json!({}));
            let options: Vec<_> = ["All", "Explosion", "Projectile", "Distortion", "Environment",
                "Fire", "Smoke", "Dust", "Water", "Blood", "Debris", "Beam", "Decal",
                "Portal", "Dark", "Wildlife", "Impact", "Other"].iter().enumerate()
                .map(|(index, label)| json!({"index":index,"text":label})).collect();
            root.children = vec![control("category", "choice", "", json!({"text":"All", "selected":0,"options":options})),
                control("search", "text", "", json!({"grow_x":true}))];
            let mut state = state(root);
            state.theme["font_pixels"] = json!(font);
            apply_theme(&context, &state.theme);
            let mut view = PresentationView::default();
            let size = egui::vec2(width, 720.0);
            for _ in 0..4 { frame(&context, &mut view, &state, size, vec![]); }
            let field = view.rects.iter().find(|rect| rect.id == "category").unwrap().rect;
            let point = egui::pos2(field[0] + 20.0, field[1] + field[3] / 2.0);
            for pressed in [true, false] {
                frame(&context, &mut view, &state, size, vec![egui::Event::PointerMoved(point),
                    egui::Event::PointerButton { pos:point, button:egui::PointerButton::Primary,
                        pressed, modifiers:egui::Modifiers::NONE }]);
            }
            for _ in 0..4 { frame(&context, &mut view, &state, size, vec![]); }
            let output = context.run_ui(egui::RawInput {
                screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, size)),
                ..Default::default()
            }, |ui| view.draw(ui, &state));
            let mut select = None;
            for expected in ["Explosion", "Projectile", "Distortion", "Environment"] {
                let (clip, text) = output.shapes.iter().find_map(|shape| match &shape.shape {
                    egui::epaint::Shape::Text(text) if text.galley.job.text == expected => Some((shape.clip_rect, text)),
                    _ => None,
                }).unwrap_or_else(|| panic!("missing {expected}"));
                assert!(!text.galley.elided, "{expected} is truncated at width={width}, font={font}");
                assert!(text.pos.x + text.galley.size().x <= clip.right() + 1.0,
                    "{expected} is clipped at width={width}, font={font}");
                if expected == "Explosion" { select = Some(text.pos + text.galley.size() / 2.0); }
            }
            let point = select.unwrap();
            for pressed in [true, false] {
                frame(&context, &mut view, &state, size, vec![egui::Event::PointerMoved(point),
                    egui::Event::PointerButton { pos:point, button:egui::PointerButton::Primary,
                        pressed, modifiers:egui::Modifiers::NONE }]);
            }
            assert!(view.inputs.iter().any(|input| input.control == "category" && input.action == "choose" && input.value == 1));
        }
    }
}

#[test]
fn editable_choice_uses_one_row_and_preserves_typing_and_selection() {
    let context = egui::Context::default();
    let mut view = PresentationView::default();
    let state = state(control("part", "choice", "", json!({"editable":true,"text":"Blade",
        "selected":0,"options":[{"index":0,"text":"Blade"},{"index":1,"text":"Handle"}]})));
    apply_theme(&context, &state.theme);
    let size = egui::vec2(960.0, 720.0);
    for _ in 0..3 { frame(&context, &mut view, &state, size, vec![]); }
    assert_eq!(view.rects.len(), 2);
    let field = view.rects[0].rect;
    let arrow = view.rects[1].rect;
    assert!((field[1] - arrow[1]).abs() < 2.0);
    assert!(field[0] + field[2] <= arrow[0]);
    click(&context, &mut view, &state, egui::pos2(field[0] + 20.0, field[1] + 10.0));
    frame(&context, &mut view, &state, size, vec![egui::Event::Text("Custom".into())]);
    assert!(view.inputs.iter().any(|input| input.action == "text" && input.value.as_str().unwrap().contains("Custom")));
    click(&context, &mut view, &state, egui::pos2(arrow[0] + 10.0, arrow[1] + 10.0));
    for _ in 0..3 { frame(&context, &mut view, &state, size, vec![]); }
    let popup = context.memory(|memory| memory.areas().visible_layer_ids().into_iter()
        .filter(|layer| layer.order == egui::Order::Foreground)
        .find_map(|layer| memory.area_rect(layer.id))).unwrap();
    assert!(popup.width() >= field[2], "editable choices must span their field: {popup:?}");
    click(&context, &mut view, &state, popup.min + egui::vec2(24.0, 40.0));
    assert!(view.inputs.iter().any(|input| input.action == "choose" && input.value == 1));
}

#[test]
fn empty_lists_and_nested_action_rows_do_not_reserve_dead_space() {
    let context = egui::Context::default();
    let mut list = control("empty", "table", "", json!({"total":0,"columns":[{"index":0,"width":100}],"rows":[]}));
    list.stretch = 1;
    let mut root = control("inspector", "scroll", "", json!({}));
    root.children = vec![list, control("add", "button", "Add", json!({}))];
    let state = state(root);
    apply_theme(&context, &state.theme);
    let mut view = PresentationView::default();
    for _ in 0..3 { frame(&context, &mut view, &state, egui::vec2(320.0, 600.0), vec![]); }
    let button = view.rects.iter().find(|rect| rect.id == "add").unwrap();
    assert!(button.rect[1] < 40.0, "empty list gap: {:?}", button.rect);
}

#[test]
fn short_tables_fit_their_actual_font_height_without_clipping_the_last_row() {
    for font in [14.0, 20.0, 22.0] {
        let context = egui::Context::default();
        let mut table = control("list", "table", "", json!({"total":3,"headers":true,
            "columns":[{"index":0,"text":"A long heading that should stay on one line","width":100}]}));
        table.props["rows"] = json!((0..3).map(|index| json!({"path":[index],
            "cells":[{"text":format!("Part {index}"),"enabled":true}]})).collect::<Vec<_>>());
        let mut root = control("inspector", "scroll", "", json!({}));
        root.children = vec![table, control("add", "button", "Add", json!({}))];
        let mut state = state(root);
        state.theme["font_pixels"] = json!(font);
        apply_theme(&context, &state.theme);
        let mut view = PresentationView::default();
        for _ in 0..4 { frame(&context, &mut view, &state, egui::vec2(320.0, 600.0), vec![]); }
        let table = view.rects.iter().find(|rect| rect.id == "list").unwrap();
        let button = view.rects.iter().find(|rect| rect.id == "add").unwrap();
        assert!(table.rect[3] + 1.0 >= 4.0 * button.rect[3] + 3.0 * 4.0, "font {font}: {table:?}, {button:?}");
        assert!(table.rect[1] + table.rect[3] <= button.rect[1]);
    }
}

#[test]
fn emitter_properties_expand_inside_the_inspector_and_keep_actions_visible() {
    for font in [14, 22] {
        let mut parameters = control("parameters", "table", "", json!({"total":30,"headers":true,
            "columns":[{"index":0,"text":"Use","width":50,"size_to_contents":true},
                       {"index":1,"text":"Property","width":200},
                       {"index":2,"text":"Value","width":140,"stretch":true}]}));
        parameters.stretch = 1;
        parameters.props["rows"] = json!((0..30).map(|index| json!({"path":[index],"cells":[
            {"text":"","check":0,"enabled":true}, {"text":format!("Emitter property {index}")},
            {"control":control(&format!("value-{index}"), "number", "", json!({"value":1}))}
        ]})).collect::<Vec<_>>());
        let mut contents = control("emitter-page", "column", "", json!({}));
        contents.children = vec![control("emitter", "choice", "", json!({"text":"White Dome Glow"})),
            control("enabled", "check", "Enabled", json!({})), parameters];
        for id in ["Colour curve", "Size curve", "Opacity curve"] {
            let mut curve = control(id, "row", "", json!({}));
            curve.children = vec![control(&format!("{id}-enabled"), "check", id, json!({})),
                control(&format!("{id}-value"), "number", "", json!({"value":1}))];
            contents.children.push(curve);
        }
        contents.children.extend([control("texture", "text", "", json!({"placeholder":"Sprite DDS archive path"})),
            control("status", "label", "", json!({"text":"Editing this emitter's exported data."})),
            control("reset", "button", "Reset emitter", json!({}))]);
        let mut scroll = control("inspector", "scroll", "", json!({}));
        scroll.children.push(contents);
        let mut tabs = control("tabs", "tabs", "", json!({"selected":0,"tabs":[{"text":"Emitters"}]}));
        tabs.children.push(scroll);
        let mut root = control("root", "column", "", json!({}));
        root.children = vec![tabs, control("apply", "button", "Apply placement", json!({}))];
        let mut state = state(root);
        state.theme["font_pixels"] = json!(font);
        let context = egui::Context::default();
        apply_theme(&context, &state.theme);
        let mut view = PresentationView::default();
        let mut previous_height = None;
        for height in [720.0, 1080.0] {
            for _ in 0..4 { frame(&context, &mut view, &state, egui::vec2(560.0,height), vec![]); }
            let rect = |id| view.rects.iter().find(|rect| rect.id == id).unwrap().rect;
            let table = rect("parameters");
            let curve = rect("Colour curve-enabled");
            let reset = rect("reset");
            let apply = rect("apply");
            assert!(table[1] + table[3] <= curve[1] + 1.0);
            assert!(reset[1] + reset[3] <= apply[1]);
            assert!(apply[1] + apply[3] <= height);
            assert!(apply[1] - reset[1] - reset[3] < 32.0, "Unused inspector height: font={font}, height={height}, reset={reset:?}, apply={apply:?}");
            if let Some(previous) = previous_height {
                assert!(table[3] >= previous + 300.0, "Emitter properties must use the taller pane: {previous} -> {}", table[3]);
            }
            previous_height = Some(table[3]);
        }
    }
}

#[test]
fn stats_and_price_tables_fill_their_panes_even_with_few_rows() {
    for rows in [2, 16] {
        for font in [14, 22] {
            let context = egui::Context::default();
            let mut panes = control("stats-split", "split", "", json!({"horizontal":true,"sizes":[900,350]}));
            for (id, title, count) in [("ladder", "Enhancement ladder", rows), ("prices", "Shop price and stack size", 2)] {
                let mut table = control(id, "table", "", json!({"total":count,"headers":true,
                    "columns":[{"index":0,"text":"Value","width":200}]}));
                table.stretch = 1;
                table.props["rows"] = json!((0..count).map(|index| json!({"path":[index],
                    "cells":[{"text":format!("{}", index + 100),"editable":true,"enabled":true}]})).collect::<Vec<_>>());
                let mut contents = control("", "column", "", json!({}));
                contents.children = vec![table, control(&format!("{id}-action"), "button", "Restore", json!({}))];
                let mut group = control(&format!("{id}-group"), "group", title, json!({}));
                group.children.push(contents);
                panes.children.push(group);
            }
            let mut page = control("page", "scroll", "", json!({}));
            page.slot = "body".into();
            page.children = vec![control("summary", "label", "", json!({"text":"Template stats"})), panes];
            let mut next = control("continue", "button", "Continue", json!({}));
            next.slot = "next".into();
            let mut root = control("workspace", "workspace", "", json!({}));
            root.children = vec![page, next];
            let mut state = state(root);
            state.theme["font_pixels"] = json!(font);
            apply_theme(&context, &state.theme);
            let mut view = PresentationView::default();
            for size in [egui::vec2(1280.0, 720.0), egui::vec2(1920.0, 1080.0)] {
                for _ in 0..4 { frame(&context, &mut view, &state, size, vec![]); }
                let footer = view.rects.iter().find(|rect| rect.id == "continue").unwrap().rect;
                for id in ["ladder", "prices"] {
                    let table = view.rects.iter().find(|rect| rect.id == id).unwrap();
                    let action = view.rects.iter().find(|rect| rect.id == format!("{id}-action")).unwrap().rect;
                    assert!(table.rect[3] > size.y * 0.65, "rows {rows}, font {font}: {table:?}");
                    assert!(table.clip[3] >= table.rect[3]);
                    assert!(table.rect[1] + table.rect[3] <= action[1] + 1.0);
                    assert!(action[1] + action[3] <= footer[1], "actions must remain above navigation");
                    assert!(footer[1] - action[1] - action[3] < 32.0, "unused pane height: {action:?}");
                }
                assert!(view.errors.is_empty());
            }
        }
    }
}

fn template_results_state(total: u64, offset: u64, preview: bool) -> State {
    let end = (offset + 128).min(total);
    let mut table = control("matches", "table", "", json!({"total":total,"offset":offset,"end":end,
        "model":[1,1],"headers":true,"columns":[{"index":0,"text":"Item name","width":400}]}));
    table.stretch = 1;
    table.props["rows"] = json!((offset..end).map(|index| json!({"path":[index],
        "cells":[{"text":format!("Template {index}"),"enabled":true}]})).collect::<Vec<_>>());
    let mut selection = control("selection", "column", "", json!({}));
    selection.children = vec![control("find", "text", "", json!({"text":""})),
        control("summary", "label", "", json!({"text":"Current item tables"})), table];
    let mut split = control("template-split", "split", "", json!({"horizontal":true,"sizes":[800,400]}));
    split.children.push(selection);
    if preview { split.children.push(control("preview", "viewport", "", json!({}))); }
    let mut page = control("page", "scroll", "", json!({}));
    page.slot = "body".into();
    page.children.push(split);
    let mut root = control("workspace", "workspace", "", json!({}));
    let mut next = control("continue", "button", "Continue", json!({}));
    next.slot = "next".into();
    root.children = vec![page, next];
    state(root)
}

#[test]
fn template_results_fill_the_page_and_keep_their_height_on_the_last_page() {
    for preview in [false, true] {
        for font in [14, 22] {
            let context = egui::Context::default();
            let mut state = template_results_state(900, 0, preview);
            state.theme["font_pixels"] = json!(font);
            apply_theme(&context, &state.theme);
            let mut view = PresentationView::default();
            let size = egui::vec2(1440.0, 1000.0);
            for _ in 0..4 { frame(&context, &mut view, &state, size, vec![]); }
            let before = view.rects.iter().find(|rect| rect.id == "matches").unwrap().rect;
            let footer = view.rects.iter().find(|rect| rect.id == "continue").unwrap().rect;
            assert!(before[3] > 800.0, "Template list must fill the browser, not an eight-row slot: {before:?}");
            assert!(footer[1] - before[1] - before[3] < 55.0, "Unused space before the footer: {before:?}, {footer:?}");
            let mut last = template_results_state(900, 896, preview);
            last.theme = state.theme.clone();
            for _ in 0..4 { frame(&context, &mut view, &last, size, vec![]); }
            let after = view.rects.iter().find(|rect| rect.id == "matches").unwrap().rect;
            assert_eq!(before, after, "The final four rows must not collapse the browser");
        }
    }
}

#[test]
fn template_scrolling_requests_more_only_once_at_the_end_of_loaded_results() {
    let context = egui::Context::default();
    let mut state = template_results_state(900, 0, false);
    apply_theme(&context, &state.theme);
    let mut view = PresentationView::default();
    let size = egui::vec2(1440.0, 1000.0);
    for _ in 0..4 { frame(&context, &mut view, &state, size, vec![]); }
    let mut requests = Vec::new();
    let scroll_to_end = |view: &mut PresentationView, state: &State, requests: &mut Vec<Value>| {
        for _ in 0..24 {
            frame(&context, view, state, size, vec![egui::Event::PointerMoved(egui::pos2(300.0,200.0)),
                egui::Event::MouseWheel { unit:egui::MouseWheelUnit::Point, delta:egui::vec2(0.0,-400.0), phase:egui::TouchPhase::Move, modifiers:egui::Modifiers::NONE }]);
            requests.extend(view.inputs.iter().filter(|input| input.action == "range" && input.value["end"] == true).map(|input| input.value.clone()));
        }
    };
    scroll_to_end(&mut view, &state, &mut requests);
    assert!(requests.is_empty(), "Scrolling the first 128 of 900 rows must not fetch more Qt rows: {requests:?}");

    state = template_results_state(900, 768, false);
    scroll_to_end(&mut view, &state, &mut requests);
    assert!(requests.is_empty(), "The loaded results still have another page");

    state = template_results_state(896, 768, false);
    scroll_to_end(&mut view, &state, &mut requests);
    assert_eq!(requests.len(), 1, "The last loaded page must request more once, not on every frame");
    let rectangle = view.rects.iter().find(|rect| rect.id == "matches").unwrap().rect;
    for _ in 0..30 {
        state.generation += 1;
        frame(&context, &mut view, &state, size, vec![]);
        assert!(!view.inputs.iter().any(|input| input.action == "range" && input.value["end"] == true));
        assert_eq!(view.rects.iter().find(|rect| rect.id == "matches").unwrap().rect, rectangle);
    }
    state = template_results_state(900, 896, false);
    scroll_to_end(&mut view, &state, &mut requests);
    assert_eq!(requests.len(), 2, "A short final page must still be able to fetch more rows");
    assert_eq!(requests[1]["offset"], 896);
}

#[test]
fn narrow_split_keeps_the_stacked_inspector_reachable_by_scrolling() {
    let context = egui::Context::default();
    let mut viewport = control("view", "column", "", json!({}));
    viewport.children = vec![control("tools", "button", "Frame", json!({})),
        control("preview", "viewport", "", json!({}))];
    let mut inspector = control("inspector", "scroll", "", json!({}));
    inspector.children = vec![control("apply", "button", "Apply placement", json!({}))];
    let mut split = control("split", "split", "", json!({"horizontal":true,"sizes":[650,380]}));
    split.children = vec![viewport, inspector];
    let state = state(split);
    apply_theme(&context, &state.theme);
    let mut view = PresentationView::default();
    let size = egui::vec2(640.0, 400.0);
    for _ in 0..4 { frame(&context, &mut view, &state, size, vec![]); }
    for _ in 0..8 {
        frame(&context, &mut view, &state, size, vec![egui::Event::PointerMoved(egui::pos2(620.0, 200.0)),
            egui::Event::MouseWheel {unit:egui::MouseWheelUnit::Point,delta:egui::vec2(0.0,-160.0),phase:egui::TouchPhase::Move,modifiers:egui::Modifiers::NONE}]);
    }
    let button = view.rects.iter().find(|rect| rect.id == "apply").unwrap();
    assert!(button.rect[1] >= button.clip[1] && button.rect[1] + button.rect[3] <= button.clip[1] + button.clip[3], "{button:?}");
}

#[test]
fn compact_input_dialog_keeps_buttons_below_the_field_at_each_font_size() {
    for font in [11.0, 14.0, 22.0] {
        let context = egui::Context::default();
        let mut state = state(control("background", "label", "", json!({"text":"Workspace"})));
        state.theme["font_pixels"] = json!(font);
        let mut actions = control("actions", "row", "", json!({"dialog_actions":true}));
        actions.children = vec![control("ok", "button", "OK", json!({"default":true})), control("cancel", "button", "Cancel", json!({}))];
        let mut dialog = control("save", "dialog", "Save effect", json!({}));
        dialog.children = vec![control("label", "label", "", json!({"text":"Name:"})),
            control("name", "text", "", json!({"text":"Owned fixture effect"})), actions];
        state.dialogs.push(dialog);
        apply_theme(&context, &state.theme);
        let mut view = PresentationView::default();
        for _ in 0..5 { frame(&context, &mut view, &state, egui::vec2(640.0, 480.0), vec![]); }
        let field = view.rects.iter().find(|rect| rect.id == "name").unwrap().rect;
        for id in ["ok", "cancel"] {
            let action = view.rects.iter().find(|rect| rect.id == id).unwrap();
            assert!(action.rect[1] >= field[1] + field[3], "{font}: {:?}, {field:?}", action.rect);
            assert!(action.rect[1] + action.rect[3] <= action.clip[1] + action.clip[3] + 1.0);
        }
    }
}

#[test]
fn context_menu_is_compact_and_outside_click_closes_only_the_menu() {
    let context = egui::Context::default();
    let mut state = state(control("background", "button", "Continue", json!({})));
    let mut menu = control("menu", "menu", "", json!({}));
    menu.children = vec![control("copy", "action", "Copy Filename", json!({})),
        control("open", "action", "Open In Archive Browser", json!({}))];
    state.dialogs.push(menu);
    apply_theme(&context, &state.theme);
    let mut view = PresentationView::default();
    for _ in 0..4 { frame(&context, &mut view, &state, egui::vec2(960.0, 720.0),
        vec![egui::Event::PointerMoved(egui::pos2(450.0, 300.0))]); }
    let action = view.rects.iter().find(|rect| rect.id == "copy").unwrap();
    assert!(action.rect[2] < 300.0);
    assert!(action.rect[0] >= 440.0 && action.rect[1] >= 290.0);
    click(&context, &mut view, &state, egui::pos2(10.0, 10.0));
    assert!(view.inputs.iter().any(|input| input.control == "menu" && input.action == "close_dialog"));
    assert!(!view.inputs.iter().any(|input| input.control == "background"));
}

/// Optional rendered audit over documents from new_item_rust_ui_harness.py.
/// No game data or live workflow actions are involved: only renderer input.
#[test]
#[ignore = "requires owned documents in CDMW_UI_AUDIT_ROOT; writes GPU captures beside them"]
fn render_owned_ui_popups_and_scrolled_panels() {
    use std::path::{Path, PathBuf};
    fn documents(root: &Path, found: &mut Vec<PathBuf>) {
        for entry in std::fs::read_dir(root).unwrap() {
            let path = entry.unwrap().path();
            if path.is_dir() {
                if path.file_name().unwrap() != "interactions" { documents(&path, found); }
            } else if path.extension().is_some_and(|ext| ext == "json")
                && !path.to_string_lossy().ends_with(".layout.json") {
                found.push(path);
            }
        }
    }
    fn nodes(node: &Node, found: &mut Vec<Node>) {
        found.push(node.clone());
        for child in node.children.iter().chain(node.embedded_nodes().iter()) { nodes(child, found); }
    }
    fn draw(context: &egui::Context, view: &mut PresentationView, state: &State, size: Vec2,
        tick: &mut f64, textures: &mut egui::TexturesDelta, events: Vec<egui::Event>) -> egui::FullOutput {
        *tick += 0.25;
        let mut output = context.run_ui(egui::RawInput {
            screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, size)),
            time: Some(*tick), events, ..Default::default()
        }, |ui| view.draw(ui, state));
        textures.append(std::mem::take(&mut output.textures_delta));
        output
    }
    fn capture(path: &Path, context: &egui::Context, output: egui::FullOutput,
        size: Vec2, textures: &egui::TexturesDelta) {
        let jobs = context.tessellate(output.shapes, output.pixels_per_point);
        pollster::block_on(super::super::capture::write_png(path, [size.x as u32, size.y as u32],
            output.pixels_per_point, &jobs, textures)).unwrap();
    }
    let root = PathBuf::from(std::env::var("CDMW_UI_AUDIT_ROOT").expect("owned document directory"));
    let mut paths = Vec::new();
    documents(&root, &mut paths);
    paths.sort();
    let mut seen = std::collections::HashSet::new();
    let mut evidence = Vec::new();
    for path in paths {
        let Ok(state) = serde_json::from_slice::<State>(&std::fs::read(&path).unwrap()) else { continue; };
        let layout_path = path.with_extension("layout.json");
        let Ok(layout) = std::fs::read(&layout_path) else { continue; };
        let layout: Value = serde_json::from_slice(&layout).unwrap();
        let size = egui::vec2(layout["size"][0].as_f64().unwrap() as f32, layout["size"][1].as_f64().unwrap() as f32);
        let output_dir = path.parent().unwrap().join("interactions");
        std::fs::create_dir_all(&output_dir).unwrap();
        let stem = path.file_stem().unwrap().to_str().unwrap();
        let context = egui::Context::default();
        apply_theme(&context, &state.theme);
        let mut view = PresentationView::default();
        super::super::load_images(&context, &mut view, &state).unwrap();
        let mut tick = 0.0;
        let mut textures = egui::TexturesDelta::default();
        for _ in 0..4 { draw(&context, &mut view, &state, size, &mut tick, &mut textures, vec![]); }
        let mut controls = Vec::new();
        nodes(state.dialogs.last().unwrap_or(&state.root), &mut controls);
        // Inspect both panes after each scroll; this reaches controls below the
        // initial fold without assuming a fixed inspector height or font size.
        for scroll in 0..12 {
            for node in controls.iter().filter(|node| node.kind == "choice" || node.flag("instant_menu")) {
                let key = format!("{size:?}:{:?}:{}:{}:{}:{}", state.theme, node.kind, node.name, node.label, node.props);
                if seen.contains(&key) { continue; }
                let rect = view.rects.iter().rev().find(|rect| rect.id == node.id && rect.enabled
                    && rect.rect[0] >= rect.clip[0] && rect.rect[1] >= rect.clip[1]
                    && rect.rect[0] + rect.rect[2] <= rect.clip[0] + rect.clip[2] + 1.0
                    && rect.rect[1] + rect.rect[3] <= rect.clip[1] + rect.clip[3] + 1.0);
                let Some(rect) = rect else { continue; };
                seen.insert(key);
                let point = egui::pos2(rect.rect[0] + rect.rect[2] / 2.0, rect.rect[1] + rect.rect[3] / 2.0);
                for pressed in [true, false] {
                    draw(&context, &mut view, &state, size, &mut tick, &mut textures, vec![
                        egui::Event::PointerMoved(point), egui::Event::PointerButton {
                            pos:point,button:egui::PointerButton::Primary,pressed,modifiers:egui::Modifiers::NONE}]);
                }
                for _ in 0..3 { draw(&context, &mut view, &state, size, &mut tick, &mut textures, vec![]); }
                let output = draw(&context, &mut view, &state, size, &mut tick, &mut textures, vec![]);
                let areas = context.memory(|memory| memory.areas().visible_layer_ids().into_iter()
                    .filter(|layer| layer.order == egui::Order::Foreground)
                    .filter_map(|layer| memory.area_rect(layer.id)).collect::<Vec<_>>());
                assert!(!areas.is_empty(), "popup did not open: {path:?} {}", node.id);
                for area in &areas {
                    assert!(area.min.x >= -1.0 && area.min.y >= -1.0 && area.max.x <= size.x + 1.0 && area.max.y <= size.y + 1.0,
                        "popup outside window: {path:?} {} {area:?}", node.id);
                }
                let file = output_dir.join(format!("{stem}-{}-popup.png", node.id));
                capture(&file, &context, output, size, &textures);
                evidence.push(json!({"document":path,"control":node.id,"name":node.name,"label":node.label,"capture":file}));
                draw(&context, &mut view, &state, size, &mut tick, &mut textures, vec![egui::Event::Key {
                    key:egui::Key::Escape,physical_key:None,pressed:true,repeat:false,modifiers:egui::Modifiers::NONE}]);
                for _ in 0..2 { draw(&context, &mut view, &state, size, &mut tick, &mut textures, vec![]); }
            }
            if !state.dialogs.is_empty() { break; }
            for x in [0.25, 0.9] {
                draw(&context, &mut view, &state, size, &mut tick, &mut textures, vec![
                    egui::Event::PointerMoved(egui::pos2(size.x * x, size.y * 0.65)),
                    egui::Event::MouseWheel {unit:egui::MouseWheelUnit::Point,delta:egui::vec2(0.0,-320.0),phase:egui::TouchPhase::Move,modifiers:egui::Modifiers::NONE}]);
                for _ in 0..3 { draw(&context, &mut view, &state, size, &mut tick, &mut textures, vec![]); }
            }
            if scroll == 11 {
                let output = draw(&context, &mut view, &state, size, &mut tick, &mut textures, vec![]);
                capture(&output_dir.join(format!("{stem}-scrolled.png")), &context, output, size, &textures);
            }
        }
        textures.clear();
        println!("Audited {}", path.display());
    }
    assert!(!evidence.is_empty());
    std::fs::write(root.join("popup-evidence.json"), serde_json::to_vec_pretty(&evidence).unwrap()).unwrap();
    println!("Captured {} popup states", evidence.len());
}

#[test]
fn compact_material_checklist_has_no_horizontal_overflow() {
    for font in [14.0, 22.0] {
        for width in [300.0, 300.5, 560.0, 560.5] {
            let context = egui::Context::default();
            let mut view = PresentationView::default();
            view.compact_depth = 1;
            let mut table = control("glow-parts", "table", "", json!({"total":12,
                "columns":[{"index":0,"width":160}], "rows":[]}));
            table.props["rows"] = json!((0..12).map(|index| json!({"path":[index],
                "cells":[{"text":(["lambert1","Gem_outside","Gem_inside","Very_Long_Material_Name_With_Multiple_Surface_And_Shader_Identifiers"][index % 4]),
                    "enabled":true,"check":if index == 0 {0} else {2}}]})).collect::<Vec<_>>());
            apply_theme(&context, &json!({"font_pixels":font}));
            let size = egui::vec2(width, 480.0);
            let mut scroll_id = egui::Id::NULL;
            for tick in 0..8 {
                let mut output = context.run_ui(egui::RawInput {
                    screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, size)),
                    time: Some(tick as f64), ..Default::default()
                }, |ui| {
                    scroll_id = ui.make_persistent_id(egui::IdSalt::new("table-columns"));
                    view.table(ui, &table);
                });
                output.textures_delta.clear();
            }
            let mut scroll = egui::scroll_area::State::load(&context, scroll_id).unwrap();
            scroll.offset.x = 1000.0;
            scroll.store(&context, scroll_id);
            let mut output = context.run_ui(egui::RawInput {
                screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, size)),
                time: Some(9.0), ..Default::default()
            }, |ui| view.table(ui, &table));
            output.textures_delta.clear();
            let scroll = egui::scroll_area::State::load(&context, scroll_id).unwrap();
            assert_eq!(scroll.offset.x, 0.0, "Material names must fit without horizontal scrolling: width={width}, font={font}");
        }
    }
}

#[test]
fn inspector_expansion_does_not_resize_the_viewport_and_short_lists_are_compact() {
    let mut table = control("parts", "table", "", json!({"total":3,
        "columns":[{"index":0,"width":120}], "rows":[]}));
    table.props["rows"] = json!((0..3).map(|index| json!({"path":[index],
        "cells":[{"text":format!("Part {index}"),"enabled":true,"check":0}]})).collect::<Vec<_>>());
    let mut group = control("appearance", "group", "Appearance", json!({}));
    group.children = vec![table, control("quick", "button", "Quick turn", json!({}))];
    let mut inspector = control("inspector", "scroll", "", json!({}));
    inspector.children.push(group);
    let mut split = control("split", "split", "", json!({"horizontal":true,"sizes":[640,320]}));
    split.name = "new_item_model_workspace_splitter".into();
    split.children = vec![control("preview", "viewport", "", json!({})), inspector];
    split.slot = "body".into();
    let mut root = control("workspace", "workspace", "", json!({}));
    root.children.push(split);
    let mut state = state(root);
    let context = egui::Context::default();
    apply_theme(&context, &state.theme);
    let mut view = PresentationView::default();
    let size = egui::vec2(960.0, 720.0);
    for _ in 0..3 { frame(&context, &mut view, &state, size, vec![]); }
    let before = view.portals[0].rect;
    assert!(before[3] > 640.0, "{before:?}");
    let list = view.rects.iter().find(|control| control.id == "parts").unwrap();
    assert!(list.rect[3] < 100.0, "Three parts must not reserve an empty panel: {list:?}");
    let split = &mut state.root.children[0];
    split.revision += 1;
    split.props["sizes"] = json!([580,380]); // hidden Qt layout changed its size hint
    split.props["horizontal"] = json!(false);
    for index in 0..30 {
        split.children[1].children[0].children.push(control(&format!("turn-{index}"), "button", "Turn", json!({})));
    }
    for _ in 0..3 { frame(&context, &mut view, &state, size, vec![]); }
    assert_eq!(view.portals[0].rect, before);
}

#[test]
fn combo_popup_masks_the_native_portal_and_survives_a_state_refresh() {
    let mut root = control("root", "column", "", json!({}));
    root.children = vec![control("shader", "choice", "", json!({"text":"Blade","selected":0,
        "options":[{"index":0,"text":"Blade","enabled":true},
                   {"index":1,"text":"Handle","enabled":true}]})),
        control("preview", "viewport", "", json!({}))];
    let mut state = state(root);
    let context = egui::Context::default();
    apply_theme(&context, &state.theme);
    let mut view = PresentationView::default();
    let size = egui::vec2(960.0, 720.0);
    for _ in 0..3 { frame(&context, &mut view, &state, size, vec![]); }
    let field = view.rects.iter().find(|item| item.id == "shader").unwrap().rect;
    click(&context, &mut view, &state, egui::pos2(field[0]+20.0, field[1]+field[3]/2.0));
    state.root.children[0].revision += 1;
    frame(&context, &mut view, &state, size, vec![]);
    let portal = &view.portals[0];
    let popup = portal.occlusions.first().expect("Combo must occlude the native viewport");
    assert!(popup[1]+popup[3] > portal.rect[1]);
    let style = context.style_of(egui::Theme::Dark);
    let y = popup[1] + egui::Frame::popup(&style).total_margin().top
        + style.spacing.interact_size.y * 1.5 + style.spacing.item_spacing.y;
    let point = egui::pos2(popup[0]+20.0, y);
    click(&context, &mut view, &state, point);
    assert!(view.inputs.iter().any(|input| input.control == "shader" && input.action == "choose" && input.value == 1), "{:?}", view.inputs);
}

#[test]
fn compact_action_buttons_stay_together_at_different_font_and_window_sizes() {
    for font in [11.0, 14.0, 22.0] {
        for width in [320.0, 960.0] {
            let context = egui::Context::default();
            let mut root = control("actions", "row", "", json!({}));
            root.children = vec![control("fit", "button", "Fit", json!({"grow_x":true})),
                control("reset", "button", "Reset", json!({"grow_x":true}))];
            let mut state = state(root);
            state.theme["font_pixels"] = json!(font);
            apply_theme(&context, &state.theme);
            let mut view = PresentationView::default();
            for _ in 0..3 { frame(&context, &mut view, &state, egui::vec2(width, 720.0), vec![]); }
            let a = &view.rects[0].rect;
            let b = &view.rects[1].rect;
            assert!(a[2] < 100.0 && b[2] < 120.0, "{a:?} {b:?}");
            let gap = b[0] - a[0] - a[2];
            assert!((0.0..=8.0).contains(&gap), "Related actions must stay together: {gap}");
            assert_eq!(a[1], b[1]);
        }
    }
}

#[test]
fn choice_and_section_help_appears_on_hover_including_disabled_controls() {
    for kind in ["choice", "group"] {
        for enabled in [true, false] {
            let context = egui::Context::default();
            let mut help = control("help", kind, "Shader experiments", json!({"text":"Keep source"}));
            help.tooltip = "These are the source material requirements.".into();
            help.enabled = enabled;
            let mut root = control("root", "column", "", json!({}));
            root.children = vec![help, control("preview", "viewport", "", json!({}))];
            let state = state(root);
            apply_theme(&context, &state.theme);
            let mut style = (*context.style_of(egui::Theme::Dark)).clone();
            style.interaction.tooltip_delay = 0.0;
            style.interaction.show_tooltips_only_when_still = false;
            context.set_style_of(egui::Theme::Dark, style);
            let mut view = PresentationView::default();
            let size = egui::vec2(960.0,720.0);
            for _ in 0..3 { frame(&context, &mut view, &state, size, vec![]); }
            let rect = view.rects.iter().find(|item| item.id == "help").unwrap().rect;
            let point = egui::pos2(rect[0]+10.0, rect[1]+rect[3]/2.0);
            for _ in 0..4 { frame(&context, &mut view, &state, size, vec![egui::Event::PointerMoved(point)]); }
            assert!(!view.portals[0].occlusions.is_empty(), "Missing help: {kind} enabled={enabled}");
            assert!(view.inputs.is_empty());
        }
    }
}

#[test]
fn numeric_text_filters_invalid_keys_and_accepts_a_leading_zero_folder_number() {
    let context = egui::Context::default();
    let mut view = PresentationView::default();
    let mut state = state(control("folder", "text", "", json!({"text":"","placeholder":"Auto","maximum":4,"digits_only":true})));
    apply_theme(&context, &state.theme);
    let size = egui::vec2(960.0, 720.0);
    for _ in 0..3 { frame(&context, &mut view, &state, size, vec![]); }
    let rect = view.rects[0].rect;
    click(&context, &mut view, &state, egui::pos2(rect[0]+12.0,rect[1]+rect[3]/2.0));
    for (key, expected) in [("a",""),("0","0"),("0","00"),("x","00"),("3","003"),("6","0036")] {
        frame(&context, &mut view, &state, size, vec![egui::Event::Text(key.into())]);
        if key == "a" || key == "x" {
            assert!(!view.inputs.iter().any(|input| input.action == "text"));
        } else {
            let input = view.inputs.iter().find(|input| input.action == "text").unwrap().clone();
            assert_eq!(input.value, json!(expected));
            view.acknowledge(&input);
        }
        state.root.revision += 1;
        state.root.props["text"] = json!(expected);
        frame(&context, &mut view, &state, size, vec![]);
    }
}

#[test]
fn icon_crop_drag_maps_back_to_source_pixels_and_obeys_disabled_state() {
    let context = egui::Context::default();
    let mut view = PresentationView::default();
    let mut state = state(control(
        "crop",
        "image_crop",
        "",
        json!({"width":800,"height":600,"selection":[0,0,800,600]}),
    ));
    apply_theme(&context, &state.theme);
    for _ in 0..3 {
        frame(
            &context,
            &mut view,
            &state,
            egui::vec2(960.0, 720.0),
            vec![],
        );
    }
    let rect = view
        .rects
        .iter()
        .find(|rect| rect.id == "crop")
        .unwrap()
        .rect;
    let point =
        |x: f32, y: f32| egui::pos2(rect[0] + x * rect[2] / 800.0, rect[1] + y * rect[3] / 600.0);
    let start = point(100.0, 80.0);
    let end = point(400.0, 360.0);
    let drag = |view: &mut PresentationView, state: &State| {
        for (position, button) in [(start, Some(true)), (end, None), (end, Some(false))] {
            let mut events = vec![egui::Event::PointerMoved(position)];
            if let Some(pressed) = button {
                events.push(egui::Event::PointerButton {
                    pos: position,
                    button: egui::PointerButton::Primary,
                    pressed,
                    modifiers: egui::Modifiers::NONE,
                });
            }
            frame(&context, view, state, egui::vec2(960.0, 720.0), events);
        }
    };
    drag(&mut view, &state);
    assert_eq!(view.inputs.len(), 1);
    let input = &view.inputs[0];
    assert_eq!((&*input.control, input.action), ("crop", "crop"));
    for (value, expected) in input
        .value
        .as_array()
        .unwrap()
        .iter()
        .zip([100, 80, 301, 281])
    {
        assert!(
            (value.as_i64().unwrap() - expected).abs() <= 1,
            "{}",
            input.value
        );
    }
    state.root.enabled = false;
    drag(&mut view, &state);
    assert!(view.inputs.is_empty());
}

#[test]
fn crop_dialog_shows_its_actions_at_large_font_size() {
    let context = egui::Context::default();
    let mut view = PresentationView::default();
    let mut state = state(control("workspace", "column", "", json!({})));
    state.theme["font_pixels"] = json!(18);
    let mut dialog = control("dialog", "dialog", "Symbolbereich auswählen", json!({}));
    let mut contents = control("contents", "column", "", json!({}));
    let mut actions = control("actions", "row", "", json!({"dialog_actions":true}));
    actions.children = vec![
        control("reset", "button", "Auf Vollbild zurücksetzen", json!({})),
        control(
            "use",
            "button",
            "Auswahl verwenden",
            json!({"default":true}),
        ),
        control("cancel", "button", "Abbrechen", json!({})),
    ];
    contents.children = vec![
        control(
            "instructions",
            "label",
            "",
            json!({"text":
        "Ziehen Sie ein Rechteck um den zu verwendenden Bereich. Die Auswahl wird in das Symbol eingepasst, wobei das Seitenverhältnis erhalten bleibt.", "wrap":true}),
        ),
        control(
            "crop",
            "image_crop",
            "",
            json!({"width":384,"height":384,"selection":[96,96,192,192]}),
        ),
        control(
            "status",
            "label",
            "",
            json!({"text":"Ausgewählter Quellbereich: 192 x 192 Pixel"}),
        ),
        actions,
    ];
    dialog.children.push(contents);
    state.dialogs.push(dialog);
    apply_theme(&context, &state.theme);
    for _ in 0..4 {
        frame(
            &context,
            &mut view,
            &state,
            egui::vec2(960.0, 720.0),
            vec![],
        );
    }
    for id in ["reset", "use", "cancel"] {
        let control = view.rects.iter().find(|rect| rect.id == id).unwrap();
        assert!(
            control.rect[1] >= control.clip[1]
                && control.rect[1] + control.rect[3] <= control.clip[1] + control.clip[3],
            "{id}: {:?}, {:?}",
            control.rect,
            control.clip
        );
    }
}
