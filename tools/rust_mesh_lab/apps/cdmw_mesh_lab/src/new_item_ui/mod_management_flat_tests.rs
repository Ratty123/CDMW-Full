use super::*;
use crate::new_item_ui::PROTOCOL;

fn node(id: &str, kind: &str, props: Value) -> Node {
    Node { id: id.into(), name: id.into(), kind: kind.into(), props,
        enabled: true, revision: 1, ..Default::default() }
}

fn button(id: &str, label: &str) -> Node {
    let mut result = node(id, "button", json!({}));
    result.label = label.into();
    result
}

fn fixture(total: usize, details: bool) -> State {
    let mut table = node("packages", "table", json!({"headers":true,"total":total,
        "columns":[{"index":0,"text":"Use","width":50,"resizable":true},
            {"index":1,"text":"Package","width":360,"resizable":true},
            {"index":2,"text":"Status","width":170,"resizable":true}],
        "empty_text":"Scan a source folder to find packages.",
        "rows":(0..total).map(|i| json!({"path":[i],"cells":[
            {"text":"","check":2},{"text":format!("Package {i:02}")},{"text":"Ready"}]})).collect::<Vec<_>>() }));
    table.name = "retrofit_packages_table".into();
    table.stretch = 1;
    let mut list = node("list", "column", json!({}));
    list.children = vec![table, node("summary", "label", json!({"text":"40 packages"}))];
    let mut split = node("retrofit_content_splitter", "split", json!({"horizontal":true,"sizes":[800,360]}));
    split.stretch = 1;
    split.children.push(list);
    if details {
        let mut panel = node("details", "group", json!({}));
        panel.label = "Package details".into();
        panel.children = vec![node("package-name", "label", json!({"text":"Emberfall Mantle"})),
            node("manager", "choice", json!({"text":"Mod Manager","selected":0,
                "options":[{"index":0,"text":"Mod Manager","enabled":true}]})),
            node("zip", "check", json!({"checked":true})),
            node("plan", "text", json!({"multiline":true,"readonly":true,"text":"Output plan\n".repeat(50)}))];
        panel.children[2].label = "Ready zip".into();
        split.children.push(panel);
    }
    let mut path = node("paths", "row", json!({}));
    path.children = vec![node("source", "text", json!({"text":"C:/Mods/Packages","grow_x":true})),
        button("scan", "Scan")];
    let mut footer = node("footer", "row", json!({}));
    footer.children = vec![button("preview", "Preview plan"), button("convert", "Repackage selected")];
    let mut page = node("convert-page", "column", json!({}));
    page.children = vec![path, button("details-toggle", "Package details"), split, footer];
    let mut tasks = node("mod_management_package_task", "tabs", json!({"selected":0,
        "tabs":[{"text":"Convert"},{"text":"Combine"},{"text":"Update"}]}));
    tasks.children.push(page);
    let mut pages = node("mod_management_pages", "tabs", json!({"selected":1,
        "tabs":[{"text":"Mods"},{"text":"Prepare packages"},{"text":"Item identities"},
            {"text":"Shared files"},{"text":"Health and recovery"}]}));
    pages.children.push(tasks);
    let mut root = node("mod_management_workspace", "column", json!({}));
    root.children = vec![node("SectionTitle", "label", json!({"text":"Mod Management"})),
        node("mod_management_game_label", "label", json!({"text":"Game folder"})),
        node("mod_management_game_folder", "text", json!({"text":"C:/Games/Crimson Desert"})),
        button("mod_management_choose_game", "Change…"), pages];
    serde_json::from_value(json!({"protocol":PROTOCOL,"session":"flat-management","generation":1,"root":root})).unwrap()
}

fn draw(ctx: &egui::Context, view: &mut PresentationView, state: &State, size: Vec2) {
    let mut output = ctx.run_ui(egui::RawInput {
        screen_rect: Some(Rect::from_min_size(egui::Pos2::ZERO, size)), ..Default::default()
    }, |ui| view.draw(ui, state));
    output.textures_delta.clear();
    assert!(view.errors.is_empty(), "{:?}", view.errors);
}

#[test]
fn flat_package_lists_fill_the_window_even_when_empty_and_keep_actions_visible() {
    for total in [0, 40] {
        let state = fixture(total, false);
        for (width, height, pixels) in [(900., 700., 14.), (1440., 900., 18.), (2560., 1440., 28.)] {
            let ctx = egui::Context::default();
            apply_theme(&ctx, &json!({"font_pixels":pixels}));
            let mut view = PresentationView::default();
            for _ in 0..4 { draw(&ctx, &mut view, &state, vec2(width, height)); }
            let table = view.rects.iter().find(|r| r.id == "packages").unwrap().rect;
            assert!(table[2] > width * 0.85 && table[3] > height * 0.42,
                "List lost its expanding area: {width}/{height}/{pixels}, total={total}, {table:?}");
            for id in ["details-toggle", "preview", "convert", "source", "scan"] {
                let r = view.rects.iter().find(|r| r.id == id).unwrap();
                assert!(r.rect[0] >= 0.0 && r.rect[0] + r.rect[2] <= width + 1.0, "{r:?}");
                assert!(r.rect[1] >= 0.0 && r.rect[1] + r.rect[3] <= height + 1.0, "{r:?}");
            }
        }
    }
}

#[test]
fn narrow_package_details_open_in_view_and_can_be_closed_without_scrolling() {
    let state = fixture(40, true);
    for (width, pixels) in [(520., 14.), (900., 18.)] {
        let ctx = egui::Context::default();
        apply_theme(&ctx, &json!({"font_pixels":pixels}));
        let mut view = PresentationView::default();
        let size = vec2(width, 700.);
        for _ in 0..4 { draw(&ctx, &mut view, &state, size); }
        assert!(!view.rects.iter().any(|r| r.id == "packages"));
        for id in ["details-toggle", "package-name", "manager", "preview", "convert"] {
            let r = view.rects.iter().find(|r| r.id == id).unwrap();
            assert!(r.rect[1] >= r.clip[1] && r.rect[1] + r.rect[3] <= r.clip[1] + r.clip[3] + 1.0,
                "Drawer control is not visible: {r:?}");
            assert!(r.rect[0] >= 0.0 && r.rect[0] + r.rect[2] <= width + 1.0, "{r:?}");
        }
    }
}
