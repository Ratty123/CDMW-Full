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
fn column_drag_keeps_the_full_distance_on_release_and_after_row_updates() {
    let context = egui::Context::default();
    let mut view = PresentationView::default();
    let mut state = state(control("table", "table", "", json!({
        "headers": true, "columns": [
            {"index":0,"width":100,"text":"Internal name","resizable":true},
            {"index":1,"width":100,"text":"Name","resizable":true}],
        "total":0,"rows":[]
    })));
    apply_theme(&context, &state.theme);
    let size = egui::vec2(960.0, 720.0);
    for _ in 0..3 { frame(&context, &mut view, &state, size, vec![]); }
    for (x, pressed) in [(471.0, Some(true)), (511.0, None), (551.0, None), (551.0, Some(false))] {
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
    assert_eq!(resize.value["width"], 552);
    state.root.revision += 1;
    state.root.props["columns"][0]["width"] = json!(552);
    frame(&context, &mut view, &state, size, vec![]);
    assert_eq!(view.column_widths[&("table".into(), 0)], 552.0);

    // Windows can deliver the final move and release before the next paint.
    let start = egui::pos2(551.0, 13.0);
    let end = egui::pos2(611.0, 13.0);
    frame(&context, &mut view, &state, size, vec![
        egui::Event::PointerMoved(start), egui::Event::PointerButton {
            pos:start,button:egui::PointerButton::Primary,pressed:true,modifiers:egui::Modifiers::NONE}]);
    frame(&context, &mut view, &state, size, vec![
        egui::Event::PointerMoved(end), egui::Event::PointerButton {
            pos:end,button:egui::PointerButton::Primary,pressed:false,modifiers:egui::Modifiers::NONE}]);
    let resize = view.inputs.iter().find(|input| input.action == "resize_column").expect("coalesced header drag");
    assert_eq!(resize.value["width"], 612);
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
