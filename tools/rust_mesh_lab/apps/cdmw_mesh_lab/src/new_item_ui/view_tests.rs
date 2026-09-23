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
