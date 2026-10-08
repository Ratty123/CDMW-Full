use super::*;
use crate::new_item_ui::PROTOCOL;

fn control(name: &str, kind: &str, label: &str, props: Value) -> Node {
    Node { id: name.into(), name: name.into(), kind: kind.into(), label: label.into(),
        enabled: true, revision: 1, props, tooltip: format!("Help for {name}"), ..Default::default() }
}

#[test]
fn virtual_loader_uses_tall_local_panes_and_keeps_actions_visible() {
    let mut selection = control("selection", "table", "", json!({"headers":true,"sortable":true,
        "columns":[{"text":"Package or folder","stretch":true},{"text":"Type","width":110}],
        "total":40,"rows":(0..40).map(|i| json!({"path":[i],"cells":[{"text":format!("Item {i:02}.cditem")},{"text":"Item package"}]})).collect::<Vec<_>>() }));
    selection.stretch = 1;
    let mut left = control("left", "column", "", json!({}));
    left.children = vec![control("sort", "choice", "", json!({"items":[{"text":"Name (A–Z)","enabled":true}],"current":0})),
        selection, control("add", "button", "Add item packages…", json!({})), control("remove", "button", "Remove selected", json!({}))];
    let mut review = control("review", "text", "", json!({"multiline":true,"readonly":true,"text":"Verified item\n".repeat(400)}));
    review.stretch = 1;
    let mut right = control("right", "column", "", json!({}));
    right.children = vec![control("prepare", "button", "Inspect and prepare", json!({})),
        control("launch", "button", "Launch with virtual profile", json!({})),
        control("progress", "progress", "", json!({"value":54,"minimum":0,"maximum":100,"text":"54%"})),
        review, control("tools", "button", "Runtime and recovery", json!({"checkable":true}))];
    let mut split = control("virtual_loader_workspace", "split", "", json!({"horizontal":true,"sizes":[560,500]}));
    split.children = vec![left, right];
    let mut page = control("virtual_loader_page", "column", "", json!({}));
    page.children = vec![control("intro", "label", "", json!({"text":"Prepare a private profile."})), split];
    let mut pages = control("mod_management_pages", "tabs", "", json!({"selected":1,
        "tabs":[{"text":"Overview"},{"text":"Virtual loader (Experimental)"}]}));
    pages.children.push(page);
    let mut root = control("mod_management_workspace", "column", "", json!({}));
    root.children = vec![control("SectionTitle", "label", "", json!({"text":"Mod Management"})),
        control("mod_management_game_label", "label", "", json!({"text":"Game folder"})),
        control("mod_management_game_folder", "text", "", json!({"text":"C:/games/Crimson Desert"})),
        control("mod_management_choose_game", "button", "Change…", json!({})), pages];
    let state: State = serde_json::from_value(json!({"protocol":PROTOCOL,
        "session":"virtual-layout","generation":1,"root":root,"theme":{"font_pixels":14}})).unwrap();
    for (width, height, font_size) in [(1100., 780., 14.), (1920., 1080., 18.), (2560., 1440., 28.)] {
        let context = egui::Context::default();
        apply_theme(&context, &json!({"font_pixels":font_size}));
        let mut view = PresentationView::default();
        for _ in 0..4 {
            let mut output = context.run_ui(egui::RawInput {
                screen_rect:Some(Rect::from_min_size(egui::Pos2::ZERO, vec2(width,height))), ..Default::default()
            }, |ui| {
                view.draw(ui, &state);
            });
            output.textures_delta.clear();
        }
        assert!(view.errors.is_empty(), "{:?}", view.errors);
        let rect = |id| &view.rects.iter().find(|r| r.id == id).unwrap().rect;
        assert!(rect("selection")[0] + rect("selection")[2] < rect("review")[0]);
        assert!(rect("selection")[3] > height * 0.40, "{:?}", rect("selection"));
        for id in ["selection", "review", "prepare", "launch", "add", "remove", "tools", "progress"] {
            let item = view.rects.iter().find(|r| r.id == id).unwrap();
            assert!(item.rect[1] + item.rect[3] <= height + 1.0, "{id}: {item:?}");
            assert!(item.rect[0] + item.rect[2] <= width + 1.0, "{id}: {item:?}");
        }
    }
}

#[test]
fn unified_mod_list_uses_full_width_and_keeps_apply_and_launch_visible() {
    let mut actions = control("actions", "row", "", json!({}));
    actions.children = [
        ("add", "Add item packages…"), ("folder", "Add mod folder…"),
        ("apply", "Apply changes"), ("launch", "Launch game"), ("cancel", "Cancel"),
    ].into_iter().map(|(name, label)| control(name, "button", label, json!({}))).collect();
    let mut list = control("mods", "table", "", json!({"headers":true,"sortable":true,
        "columns":[{"text":"Mod","width":340},{"text":"Type","width":170},
            {"text":"Loads with","width":180},{"text":"Status","stretch":true}],
        "total":40,"rows":(0..40).map(|i| json!({"path":[i],"cells":[
            {"text":format!("Mod {i:02}")},{"text":"Item package"},{"text":"CDMW launch"},{"text":"Applied"}]})).collect::<Vec<_>>() }));
    list.stretch = 1;
    let mut page = control("virtual_loader_page", "column", "", json!({}));
    page.children = vec![control("notice", "label", "", json!({"text":"Experimental"})), actions,
        control("search", "text", "", json!({"placeholder":"Search mods…"})), list,
        control("remove", "button", "Remove selected", json!({})),
        control("status", "label", "", json!({"text":"Profile applied. Ready to launch."})),
        control("details", "button", "Loader details", json!({"checkable":true}))];
    let mut pages = control("mod_management_pages", "tabs", "", json!({"selected":0,
        "tabs":[{"text":"Mods"},{"text":"Advanced"}]}));
    let mut stack = control("mod_management_mods", "column", "", json!({}));
    stack.children.push(page);
    pages.children.push(stack);
    let mut root = control("mod_management_workspace", "column", "", json!({}));
    root.children = vec![control("SectionTitle", "label", "", json!({"text":"Mod Management"})),
        control("mod_management_game_label", "label", "", json!({"text":"Game folder"})),
        control("mod_management_game_folder", "text", "", json!({"text":"C:/games/Crimson Desert"})),
        control("mod_management_choose_game", "button", "Change…", json!({})), pages];
    let state: State = serde_json::from_value(json!({"protocol":PROTOCOL,
        "session":"unified-mod-list","generation":1,"root":root})).unwrap();
    for (width, height, font_size) in [(900., 700., 14.), (1400., 900., 20.), (2560., 1440., 28.)] {
        let context = egui::Context::default();
        apply_theme(&context, &json!({"font_pixels":font_size}));
        let mut view = PresentationView::default();
        for _ in 0..4 {
            let mut output = context.run_ui(egui::RawInput {
                screen_rect:Some(Rect::from_min_size(egui::Pos2::ZERO, vec2(width,height))), ..Default::default()
            }, |ui| view.draw(ui, &state));
            output.textures_delta.clear();
        }
        assert!(view.errors.is_empty(), "{:?}", view.errors);
        let list_rect = view.rects.iter().find(|r| r.id == "mods").unwrap().rect;
        assert!(list_rect[2] > width * 0.85, "{list_rect:?}");
        assert!(list_rect[3] > height * 0.25, "{list_rect:?}");
        for id in ["add", "folder", "apply", "launch", "cancel", "search", "mods", "remove", "details"] {
            let item = view.rects.iter().find(|r| r.id == id).unwrap();
            assert!(item.rect[1] + item.rect[3] <= height + 1.0, "{id}: {item:?}");
            assert!(item.rect[0] + item.rect[2] <= width + 1.0, "{id}: {item:?}");
        }
    }
}
