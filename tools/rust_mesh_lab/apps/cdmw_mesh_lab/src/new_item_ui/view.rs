//! Real egui widgets over the host's existing workflow controls.

use super::model::{ControlRect, Input, Node, Portal, State, rect_array};
use egui::{Color32, FontId, RichText, TextStyle, Ui, Vec2};
use serde_json::{Value, json};
use std::collections::{BTreeMap, HashMap};

#[cfg(test)]
#[path = "view_tests.rs"]
mod tests;

#[derive(Default)]
pub struct PresentationView {
    pub inputs: Vec<Input>,
    pub rects: Vec<ControlRect>,
    pub portals: Vec<Portal>,
    pub errors: Vec<String>,
    edits: HashMap<String, EditText>,
    numbers: HashMap<String, (u64, f64)>,
    accepted_edits: HashMap<String, Value>,
    split_sizes: HashMap<String, (u64, Vec<f32>)>,
    table_focus: HashMap<String, egui::Id>,
    table_end_requests: HashMap<String, (Value, u64, u64)>,
    column_widths: HashMap<(String, u64), f32>,
    column_drag_origins: HashMap<(String, u64), (f32, f32)>,
    menu_positions: HashMap<String, egui::Pos2>,
    dialog_rects: HashMap<String, egui::Rect>,
    crop_origin: HashMap<String, egui::Pos2>,
    pub textures: HashMap<String, egui::TextureHandle>,
    strings: BTreeMap<String, String>,
    compact_depth: usize,
}

struct EditText {
    revision: u64,
    authority: String,
    value: String,
}

impl PresentationView {
    pub fn acknowledge(&mut self, input: &Input) {
        if matches!(input.action, "text" | "number" | "cell") {
            let value = if input.action == "cell" {
                input.value["text"].clone()
            } else {
                input.value.clone()
            };
            self.accepted_edits.insert(input.edit_key(), value);
        }
    }

    pub fn reject_edits(&mut self) {
        self.edits.clear();
        self.numbers.clear();
        self.accepted_edits.clear();
    }

    fn edit_text(&mut self, key: &str, revision: u64, authority: &str) -> String {
        let entry = self
            .edits
            .entry(key.to_owned())
            .or_insert_with(|| EditText {
                revision,
                authority: authority.to_owned(),
                value: authority.to_owned(),
            });
        if entry.revision != revision {
            if entry.authority != authority
                && self
                    .accepted_edits
                    .remove(key)
                    .as_ref()
                    .and_then(Value::as_str)
                    != Some(authority)
            {
                entry.value = authority.to_owned();
            }
            entry.authority = authority.to_owned();
            entry.revision = revision;
        }
        entry.value.clone()
    }

    pub fn draw(&mut self, ui: &mut Ui, state: &State) {
        self.strings.clone_from(&state.strings);
        self.inputs.clear();
        self.rects.clear();
        self.portals.clear();
        self.errors.clear();
        ui.painter()
            .rect_filled(ui.max_rect(), 0.0, ui.visuals().panel_fill);
        if !state.unsupported.is_empty() {
            ui.colored_label(ui.visuals().error_fg_color,
                "This page contains controls that Create New Item cannot display. Please report the affected workflow.");
        }
        ui.add_enabled_ui(state.dialogs.is_empty() && !state.native_modal, |ui| {
            self.node(ui, &state.root)
        });
        if let Some(dialog) = state.dialogs.last() {
            if ui.input_mut(|input| input.consume_key(egui::Modifiers::NONE, egui::Key::Escape)) {
                self.input(dialog, "close_dialog", Value::Null);
            } else if !ui.ctx().egui_wants_keyboard_input()
                && ui.input_mut(|input| input.consume_key(egui::Modifiers::NONE, egui::Key::Enter))
            {
                if let Some(button) = default_button(dialog) {
                    self.input(button, "activate", Value::Null);
                }
            }
        }
        for (index, dialog) in state.dialogs.iter().enumerate() {
            self.portals.clear();
            if dialog.kind == "menu" {
                let position = *self.menu_positions.entry(dialog.id.clone()).or_insert_with(||
                    ui.input(|input| input.pointer.latest_pos()).unwrap_or(ui.ctx().content_rect().center()));
                let mut open = true;
                egui::Popup::new(egui::Id::new((&dialog.id, "menu")), ui.ctx().clone(), position, ui.layer_id())
                    .kind(egui::PopupKind::Menu)
                    .open_bool(&mut open)
                    .layout(egui::Layout::top_down_justified(egui::Align::Min))
                    .width(minimum_width(ui, dialog).min(ui.ctx().content_rect().width() - 24.0))
                    .show(|ui| {
                        for child in &dialog.children { self.menu_item(ui, child); }
                    });
                if !open && !self.inputs.iter().any(|input| input.action == "activate") {
                    self.input(dialog, "close_dialog", Value::Null);
                }
                continue;
            }
            let mut open = true;
            let mut width = (ui.ctx().content_rect().width() * 0.8)
                .min(if dialog.flexible() { 1000.0 } else { 520.0 });
            let max_height = (ui.ctx().content_rect().height() - 96.0).max(200.0);
            let mut height = if dialog.flexible() {
                max_height
            } else {
                (estimate_height(ui, dialog, width) + 32.0).min(max_height)
            };
            let mut position = ui.ctx().content_rect().center() - Vec2::new(width, height) / 2.0;
            if let [x, y, w, h] = dialog.array("saved_rect")
                && let (Some(x), Some(y), Some(w), Some(h)) = (x.as_f64(), y.as_f64(), w.as_f64(), h.as_f64())
                && [x, y, w, h].iter().all(|n| n.is_finite())
                && (120.0..=16000.0).contains(&w) && (80.0..=16000.0).contains(&h)
            {
                width = (w as f32).min(ui.ctx().content_rect().width() - 24.0).max(120.0);
                height = (h as f32).min(max_height);
                position = egui::pos2(x as f32, y as f32);
            }
            let mut actions = Vec::new();
            let body = dialog_body(dialog, &mut actions);
            let response = egui::Window::new(&dialog.label)
                .id(egui::Id::new((&dialog.id, "dialog")))
                .open(&mut open)
                .collapsible(false)
                .resizable(true)
                .default_size(Vec2::new(width, height))
                .default_pos(position)
                .max_height(max_height)
                .show(ui.ctx(), |ui| {
                    ui.add_enabled_ui(index + 1 == state.dialogs.len(), |ui| {
                        let footer = if actions.is_empty() { 0.0 } else {
                            actions.iter().map(|action| estimate_height(ui, action, ui.available_width()))
                                .sum::<f32>() + 16.0
                        };
                        egui::ScrollArea::vertical()
                            .id_salt((&dialog.id, "body"))
                            .min_scrolled_height(0.0)
                            .max_height((if dialog.flexible() { bounded_height(ui) } else { max_height } - footer).max(0.0))
                            .auto_shrink([false, !dialog.flexible()])
                            .show(ui, |ui| {
                                if let Some(body) = &body {
                                    self.column(ui, &body.children);
                                }
                            });
                        if !actions.is_empty() { ui.separator(); }
                        for action in &actions {
                            let width = minimum_width(ui, action).min(ui.available_width());
                            let height = estimate_height(ui, action, width);
                            // A full-height footer keeps spare estimated window height
                            // alive. Allocate only the actions so the dialog can shrink.
                            ui.allocate_ui_with_layout(Vec2::new(ui.available_width(), height),
                                egui::Layout::right_to_left(egui::Align::Min), |ui| {
                                ui.allocate_ui_with_layout(Vec2::new(width, control_height(ui)),
                                    egui::Layout::top_down(egui::Align::Min), |ui| self.node(ui, action));
                            });
                        }
                    });
                });
            if let Some(response) = response {
                let rect = response.response.rect;
                let previous = self.dialog_rects.insert(dialog.id.clone(), rect);
                if previous.is_some_and(|previous| previous != rect)
                    && ui.input(|input| input.pointer.any_down() || input.pointer.any_released())
                {
                    self.input(dialog, "resize_dialog", json!([
                        rect.min.x.round() as i32, rect.min.y.round() as i32,
                        rect.width().max(120.0).round() as u32,
                        rect.height().max(80.0).round() as u32
                    ]));
                }
            }
            if !open {
                self.input(dialog, "close_dialog", Value::Null);
            }
        }
        // Headers and dialog actions are drawn before their fields. Complete
        // edits first, as Qt does on focus loss, before an action hides them.
        self.inputs.sort_by_key(|input| match input.action {
            "text" | "number" | "cell" => 0,
            "finish_edit" | "submit" => 1,
            _ => 2,
        });
        // Native preview HWNDs sit above this egui surface. Punch only the
        // floating-menu/tooltip regions out of them so popups remain visible
        // and receive clicks even when they extend across the viewport.
        let occlusions: Vec<_> = ui.memory(|memory| {
            memory.areas().visible_layer_ids().into_iter()
                .filter(|layer| matches!(layer.order, egui::Order::Foreground | egui::Order::Tooltip))
                .filter_map(|layer| memory.area_rect(layer.id))
                .map(rect_array)
                .collect()
        });
        for portal in &mut self.portals {
            portal.occlusions.clone_from(&occlusions);
        }
        self.menu_positions.retain(|id, _| state.dialogs.iter().any(|dialog| dialog.id == *id));
    }

    fn input(&mut self, node: &Node, action: &'static str, value: Value) {
        if !node.id.is_empty() {
            self.inputs.push(Input::new(node, action, value));
        }
    }

    fn tr(&self, key: &str, source: &str) -> String {
        self.strings
            .get(key)
            .cloned()
            .unwrap_or_else(|| source.to_owned())
    }

    fn record(&mut self, ui: &Ui, node: &Node, response: &egui::Response) {
        if !node.tooltip.is_empty() {
            response.clone().on_hover_text(&node.tooltip).on_disabled_hover_text(&node.tooltip);
        }
        if !node.id.is_empty() {
            self.rects.push(ControlRect {
                id: node.id.clone(),
                kind: node.kind.clone(),
                label: node.label.clone(),
                rect: rect_array(response.rect),
                clip: rect_array(ui.clip_rect()),
                enabled: ui.is_enabled() && node.enabled,
            });
        }
    }

    pub fn node(&mut self, ui: &mut Ui, node: &Node) {
        let key = if node.id.is_empty() {
            format!("{}-{}", node.kind, node.name)
        } else {
            node.id.clone()
        };
        ui.push_id(key, |ui| {
            if ui.is_enabled() && !node.enabled {
                ui.add_enabled_ui(false, |ui| self.control(ui, node));
            } else {
                self.control(ui, node);
            }
        });
    }

    fn control(&mut self, ui: &mut Ui, node: &Node) {
        let response = match node.kind.as_str() {
            "workspace" => {
                self.workspace(ui, node);
                None
            }
            "column" | "dialog" => {
                self.column(ui, &node.children);
                None
            }
            "row" => {
                self.row(ui, &node.children);
                None
            }
            "grid" => {
                self.grid(ui, node);
                None
            }
            "split" => {
                // A split owns full-height panes even inside a scrolling page.
                // Only an inspector's own scroll area should compact its lists.
                let compact_depth = self.compact_depth;
                self.compact_depth = 0;
                self.split(ui, node);
                self.compact_depth = compact_depth;
                None
            }
            "scroll" => {
                let height = bounded_height(ui);
                egui::ScrollArea::vertical()
                    .auto_shrink([false, false])
                    .id_salt("scroll")
                    .max_height(height)
                    .show(ui, |ui| {
                        ui.set_max_height(height);
                        self.compact_depth += 1;
                        self.column(ui, &node.children);
                        self.compact_depth -= 1;
                    });
                None
            }
            "group" => {
                self.group(ui, node);
                None
            }
            "steps" => {
                self.steps(ui, node);
                None
            }
            "tabs" => {
                self.tabs(ui, node);
                None
            }
            "button" | "action" => Some(self.button(ui, node)),
            "check" | "radio" => {
                let mut checked = node.flag("checked");
                let response = if node.kind == "radio" {
                    ui.radio(checked, &node.label)
                } else {
                    ui.checkbox(&mut checked, &node.label)
                };
                if response.clicked() {
                    self.input(
                        node,
                        "toggle",
                        json!(if node.kind == "radio" { true } else { checked }),
                    );
                }
                Some(response)
            }
            "text" => Some(self.text(ui, node)),
            "number" | "slider" => {
                let authority = node.number("value", 0.0);
                let entry = self
                    .numbers
                    .entry(node.id.clone())
                    .or_insert((node.revision, authority));
                if entry.0 != node.revision {
                    if self
                        .accepted_edits
                        .remove(&node.id)
                        .as_ref()
                        .and_then(Value::as_f64)
                        != Some(authority)
                    {
                        entry.1 = authority;
                    }
                    entry.0 = node.revision;
                }
                let mut value = entry.1;
                let min = node.number("minimum", -1e12);
                let max = node.number("maximum", 1e12);
                let response = if node.kind == "slider" {
                    ui.add(
                        egui::Slider::new(&mut value, min..=max)
                            .step_by(node.number("step", 1.0))
                            .show_value(false)
                            .integer(),
                    )
                } else {
                    ui.add_enabled_ui(!node.flag("readonly"), |ui| {
                        ui.add_sized(
                            Vec2::new(
                                ui.available_width().min(200.0),
                                control_height(ui),
                            ),
                            egui::DragValue::new(&mut value)
                                .range(min..=max)
                                .update_while_editing(node.flag("keyboard_tracking"))
                                .speed(node.number("step", 1.0))
                                .max_decimals(node.number("decimals", 0.0) as usize)
                                .custom_formatter(|value, _| {
                                    if value == min && !node.text("special").is_empty() {
                                        node.text("special").to_owned()
                                    } else {
                                        format!(
                                            "{:.*}",
                                            node.number("decimals", 0.0) as usize,
                                            value
                                        )
                                    }
                                })
                                .prefix(node.text("prefix"))
                                .suffix(node.text("suffix")),
                        )
                    })
                    .inner
                };
                if response.changed() {
                    self.numbers.insert(node.id.clone(), (node.revision, value));
                    self.input(node, "number", json!(value));
                }
                if response.lost_focus() || response.drag_stopped() {
                    self.input(node, "finish_edit", Value::Null);
                }
                Some(response)
            }
            "choice" => {
                self.choice(ui, node);
                None
            }
            "table" => {
                self.table(ui, node);
                None
            }
            "label" if node.text("text").is_empty() && node.text("image").is_empty() => None,
            "label" => Some(self.label(ui, node)),
            "image_crop" => Some(self.image_crop(ui, node)),
            "separator" => Some(ui.separator()),
            "progress" => {
                if node.flag("indeterminate") {
                    Some(
                        ui.horizontal(|ui| {
                            ui.spinner();
                            ui.label(node.text("text"));
                        })
                        .response,
                    )
                } else {
                    let min = node.number("minimum", 0.0);
                    let max = node.number("maximum", 100.0);
                    Some(
                        ui.add(
                            egui::ProgressBar::new(
                                ((node.number("value", min) - min) / (max - min).max(1.0)) as f32,
                            )
                            .text(node.text("text"))
                            .desired_width(ui.available_width()),
                        ),
                    )
                }
            }
            "viewport" => {
                let size = Vec2::new(
                    ui.available_width().max(80.0),
                    bounded_height(ui).max(180.0),
                );
                let (rect, response) = ui.allocate_exact_size(size, egui::Sense::hover());
                ui.painter()
                    .rect_filled(rect, 4.0, ui.visuals().extreme_bg_color);
                self.portals.push(Portal {
                    id: node.id.clone(),
                    rect: rect_array(rect),
                    clip: rect_array(ui.clip_rect()),
                    occlusions: Vec::new(),
                });
                Some(response)
            }
            "menu" => {
                for child in &node.children {
                    self.menu_item(ui, child);
                }
                None
            }
            unknown => {
                self.errors
                    .push(format!("Unsupported control {unknown}: {}", node.name));
                Some(ui.colored_label(
                    ui.visuals().error_fg_color,
                    format!("Unsupported control: {unknown}"),
                ))
            }
        };
        if let Some(response) = response {
            self.record(ui, node, &response);
        }
    }

    fn workspace(&mut self, ui: &mut Ui, node: &Node) {
        let rect = ui.available_rect_before_wrap().shrink(6.0);
        let slot = |name: &str| node.children.iter().find(|child| child.slot == name);
        let mut top = rect.top();
        for name in ["notice", "header"] {
            if let Some(child) = slot(name) {
                let mut header = ui.new_child(egui::UiBuilder::new().id_salt(name).max_rect(
                    egui::Rect::from_min_max(egui::pos2(rect.left(), top), rect.right_bottom()),
                ));
                self.node(&mut header, child);
                top = header.min_rect().bottom() + 6.0;
            }
        }
        let footer_height = control_height(ui) + 2.0;
        let footer_top = (rect.bottom() - footer_height).max(top + 80.0);
        let body_rect = egui::Rect::from_min_max(
            egui::pos2(rect.left(), top),
            egui::pos2(rect.right(), footer_top - 2.0),
        );
        if let Some(body) = slot("body") {
            let mut body_ui = ui.new_child(
                egui::UiBuilder::new()
                    .id_salt("workspace-body")
                    .max_rect(body_rect),
            );
            body_ui.set_clip_rect(body_rect.intersect(ui.clip_rect()));
            // The outer scroll is a safety net for short windows and enlarged
            // fonts. The page's own tables/inspectors retain their own scrolling.
            egui::ScrollArea::vertical()
                .id_salt("page-overflow")
                .auto_shrink([false, false])
                .max_height(body_rect.height())
                .show(&mut body_ui, |ui| {
                    ui.set_max_height(body_rect.height());
                    self.node(ui, body);
                });
        }
        ui.painter().hline(
            rect.x_range(),
            footer_top,
            ui.visuals().widgets.noninteractive.bg_stroke,
        );
        let back_width = slot("back").map_or(0.0, |node| minimum_width(ui, node));
        let next_width = slot("next").map_or(0.0, |node| minimum_width(ui, node));
        for (name, left, right) in [
            ("back", rect.left(), rect.left() + back_width),
            ("hint", rect.left() + back_width + 12.0, rect.right() - next_width - 12.0),
            ("next", rect.right() - next_width, rect.right()),
        ] {
            if let Some(child) = slot(name) {
                let mut footer = ui.new_child(
                    egui::UiBuilder::new()
                        .id_salt(name)
                        .max_rect(egui::Rect::from_min_max(
                            egui::pos2(left, footer_top + 1.0),
                            egui::pos2(right, rect.bottom()),
                        ))
                        .layout(egui::Layout::top_down(egui::Align::Center)),
                );
                self.node(&mut footer, child);
            }
        }
        ui.advance_cursor_after_rect(rect);
    }

    fn column(&mut self, ui: &mut Ui, children: &[Node]) {
        if children.is_empty() {
            return;
        }
        let compact = self.compact_depth > 0;
        let flexible = |node: &Node| if compact { has_stretched_editor(node) } else { layout_flexible(node) };
        if compact && !children.iter().any(flexible) {
            for (index, node) in children.iter().enumerate() {
                ui.push_id(index, |ui| self.node(ui, node));
            }
            return;
        }
        let spacing = ui.spacing().item_spacing.y;
        let natural: Vec<_> = children
            .iter()
            .map(|node| estimate_height(ui, node, ui.available_width()))
            .collect();
        let fixed: f32 = children.iter().zip(&natural)
            .filter(|(node, _)| !flexible(node)).map(|(_, height)| *height).sum();
        let extra = (bounded_height(ui) - fixed
            - spacing * children.len().saturating_sub(1) as f32).max(0.0);
        let weights: Vec<_> = children
            .iter()
            .map(|node| {
                if flexible(node) {
                    node.stretch.max(1) as f32
                } else {
                    0.0
                }
            })
            .collect();
        let weight = weights.iter().sum::<f32>().max(1.0);
        for (index, node) in children.iter().enumerate() {
            let height = if flexible(node) { extra * weights[index] / weight } else { natural[index] };
            ui.push_id(index, |ui| {
                if flexible(node) {
                    ui.allocate_ui_with_layout(
                        Vec2::new(ui.available_width(), height),
                        egui::Layout::top_down(egui::Align::Min),
                        |ui| self.node(ui, node),
                    );
                } else {
                    self.node(ui, node);
                }
            });
        }
    }

    fn row(&mut self, ui: &mut Ui, children: &[Node]) {
        if children.len() == 1 {
            self.node(ui, &children[0]);
            return;
        }
        let minimum: f32 = children
            .iter()
            .map(|node| minimum_width(ui, node))
            .sum::<f32>()
            + ui.spacing().item_spacing.x * children.len().saturating_sub(1) as f32;
        if minimum > ui.available_width() && children.len() > 1 {
            let mut start = 0;
            let mut used = 0.0;
            for (index, child) in children.iter().enumerate() {
                let width = minimum_width(ui, child);
                if index > start && used + ui.spacing().item_spacing.x + width > ui.available_width() {
                    ui.push_id(start, |ui| self.row(ui, &children[start..index]));
                    start = index;
                    used = 0.0;
                }
                used += width + if index > start { ui.spacing().item_spacing.x } else { 0.0 };
            }
            ui.push_id(start, |ui| self.row(ui, &children[start..]));
            return;
        }
        let extra = (ui.available_width() - minimum).max(0.0);
        let grows = |child: &Node| !matches!(child.kind.as_str(), "button" | "action" | "check" | "radio" | "label")
            && (child.stretch > 0 || child.flag("grow_x"));
        let grow = children
            .iter()
            .filter(|child| grows(child))
            .count()
            .max(1) as f32;
        let height = control_height(ui);
        ui.horizontal_top(|ui| {
            for (index, child) in children.iter().enumerate() {
                let width = minimum_width(ui, child)
                    + if grows(child) {
                        extra / grow
                    } else {
                        0.0
                    };
                ui.push_id(index, |ui| {
                    ui.allocate_ui_with_layout(
                        Vec2::new(
                            width,
                            if layout_flexible(child) && self.compact_depth == 0 {
                                bounded_height(ui)
                            } else {
                                height
                            },
                        ),
                        egui::Layout::top_down(egui::Align::Min),
                        |ui| {
                            ui.set_min_width(width);
                            self.node(ui, child);
                        },
                    );
                });
            }
        });
    }

    fn grid(&mut self, ui: &mut Ui, node: &Node) {
        let mut rows: BTreeMap<i32, Vec<Node>> = BTreeMap::new();
        let column_count = node
            .children
            .iter()
            .map(|child| {
                let cell = child.cell.unwrap_or([0, 0, 1, 1]);
                cell[1] + cell[3]
            })
            .max()
            .unwrap_or(1)
            .max(1) as usize;
        let spacing = ui.spacing().item_spacing.x;
        let width = (ui.available_width() - spacing * (column_count - 1) as f32).max(80.0);
        let mut widths = vec![width / column_count as f32; column_count];
        // Qt message boxes use spacer-only columns around their icon. Those
        // spacers must not become equal-width blank columns in the projection.
        let mut occupied = vec![false; column_count];
        let mut icons = vec![None; column_count];
        for child in &node.children {
            let cell = child.cell.unwrap_or([0, 0, 1, 1]);
            let start = cell[1].max(0) as usize;
            let end = (start + cell[3].max(1) as usize).min(column_count);
            occupied[start..end].fill(true);
            if cell[3] == 1 && child.kind == "label" && child.text("text").is_empty() {
                if let Some(texture) = self.textures.get(child.text("image")) {
                    icons[start] = Some(texture.size_vec2().x.min(64.0));
                }
            }
        }
        if occupied.contains(&false) || icons.iter().any(Option::is_some) {
            let fixed = icons.iter().flatten().sum::<f32>();
            let growing = occupied.iter().zip(&icons).filter(|(used, icon)| **used && icon.is_none()).count().max(1);
            for column in 0..column_count {
                widths[column] = if !occupied[column] { 0.0 } else {
                    icons[column].unwrap_or((width - fixed).max(0.0) / growing as f32)
                };
            }
        }
        if !node.flag("form") && node.children.iter().all(|child|
            matches!(child.kind.as_str(), "button" | "label" | "check" | "radio")) {
            let mut compact = vec![0.0f32; column_count];
            for child in &node.children {
                let cell = child.cell.unwrap_or([0, 0, 1, 1]);
                if cell[3] == 1 {
                    let column = cell[1].max(0) as usize;
                    compact[column] = compact[column].max(minimum_width(ui, child));
                }
            }
            if compact.iter().all(|length| *length > 0.0) && compact.iter().sum::<f32>() <= width {
                widths = compact;
            }
        }
        if node.flag("form") && column_count == 2 && width >= 400.0 {
            widths[0] = node
                .children
                .iter()
                .filter(|child| child.cell.is_some_and(|cell| cell[1] == 0 && cell[3] == 1))
                .map(|child| minimum_width(ui, child))
                .fold(90.0, f32::max)
                .min(width * 0.38);
            widths[1] = width - widths[0];
        }
        for child in &node.children {
            rows.entry(child.cell.unwrap_or([0, 0, 1, 1])[0])
                .or_default()
                .push(child.clone());
        }
        for (index, mut cells) in rows {
            cells.sort_by_key(|cell| cell.cell.unwrap_or([0, 0, 1, 1])[1]);
            ui.push_id(index, |ui| {
                if node.flag("form") && width < 400.0 {
                    self.column(ui, &cells);
                    return;
                }
                if column_count >= 5
                    && width < 600.0
                    && cells.len() >= 5
                    && cells[0].kind == "label"
                {
                    self.node(ui, &cells[0]);
                    let fields = &cells[1..];
                    let unit = (width - spacing * fields.len().saturating_sub(1) as f32)
                        / fields
                            .iter()
                            .map(|child| if child.kind == "label" { 1.0 } else { 4.0 })
                            .sum::<f32>();
                    ui.horizontal_top(|ui| {
                        for child in fields {
                            let length = unit * if child.kind == "label" { 1.0 } else { 4.0 };
                            ui.allocate_ui_with_layout(
                                Vec2::new(length, control_height(ui)),
                                egui::Layout::top_down(egui::Align::Min),
                                |ui| self.node(ui, child),
                            );
                        }
                    });
                    return;
                }
                ui.horizontal_top(|ui| {
                    let mut column = 0;
                    for child in &cells {
                        let cell = child.cell.unwrap_or([0, 0, 1, 1]);
                        let start = cell[1].max(0) as usize;
                        if start > column {
                            ui.add_space(
                                widths[column..start].iter().sum::<f32>()
                                    + spacing * (start - column) as f32,
                            );
                        }
                        let end = (start + cell[3].max(1) as usize).min(column_count);
                        let cell_width = widths[start..end].iter().sum::<f32>()
                            + spacing * (end - start - 1) as f32;
                        ui.allocate_ui_with_layout(
                            Vec2::new(cell_width, control_height(ui)),
                            egui::Layout::top_down(egui::Align::Min),
                            |ui| {
                                ui.set_min_width(cell_width);
                                self.node(ui, child);
                            },
                        );
                        column = end;
                    }
                });
            });
        }
    }

    fn split(&mut self, ui: &mut Ui, node: &Node) {
        // The hidden Qt inspector has different font metrics and minimum-size
        // hints. Its disclosures must not change this workspace's orientation.
        let model_workspace = node.name == "new_item_model_workspace_splitter";
        let horizontal = model_workspace || node.flag("horizontal");
        if node.children.len() < 2 {
            self.column(ui, &node.children);
            return;
        }
        if horizontal && ui.available_width() < 760.0 {
            let height = bounded_height(ui).max(240.0);
            egui::ScrollArea::vertical().id_salt("stacked-panes")
                .auto_shrink([false, false]).max_height(height).show(ui, |ui| {
                    for (index, child) in node.children.iter().enumerate() {
                        let pane_height = estimate_height(ui, child, ui.available_width())
                            .clamp(260.0, height.max(360.0));
                        ui.push_id(index, |ui| {
                            ui.allocate_ui_with_layout(Vec2::new(ui.available_width(), pane_height),
                                egui::Layout::top_down(egui::Align::Min), |ui| self.node(ui, child));
                        });
                    }
                });
            return;
        }
        let rect = egui::Rect::from_min_size(
            ui.cursor().min,
            Vec2::new(ui.available_width(), bounded_height(ui).max(240.0)),
        );
        let gutter = 10.0;
        let available = (if horizontal {
            rect.width()
        } else {
            rect.height()
        }) - gutter * (node.children.len() - 1) as f32;
        let indices: Vec<_> = (0..node.children.len())
            .map(|index| {
                node.array("indices")
                    .get(index)
                    .and_then(Value::as_u64)
                    .unwrap_or(index as u64) as usize
            })
            .collect();
        let entry = self
            .split_sizes
            .entry(node.id.clone())
            .or_insert_with(|| (0, vec![]));
        if entry.1.is_empty() {
            *entry = (
                node.revision,
                node.array("sizes")
                    .iter()
                    .map(|value| value.as_f64().unwrap_or(1.0) as f32)
                    .collect(),
            );
            if model_workspace && indices == [0, 1] && !node.flag("user_sized") {
                let inspector = (520.0 * TextStyle::Body.resolve(ui.style()).size / 14.0)
                    .min(available * 0.45);
                entry.1 = vec![available - inspector, inspector];
            }
        }
        let mut sizes = entry.1.clone();
        let required = indices.iter().max().copied().unwrap_or(0) + 1;
        if sizes.len() < required {
            sizes.resize(required, 0.0);
        }
        // Qt reports zero for hidden panes. Reopening a pane must recover a usable
        // width, while retaining ratios the user already dragged in this view.
        for index in &indices {
            if sizes[*index] <= 0.0 {
                sizes[*index] = node.array("sizes").get(*index)
                    .and_then(Value::as_f64).unwrap_or(0.0) as f32;
                if sizes[*index] <= 0.0 {
                    sizes[*index] = available / indices.len() as f32;
                }
            }
        }
        entry.1 = sizes.clone();
        let total = indices
            .iter()
            .map(|index| sizes[*index])
            .sum::<f32>()
            .max(1.0);
        let mut cursor = if horizontal { rect.left() } else { rect.top() };
        for (index, child) in node.children.iter().enumerate() {
            let length = available * sizes[indices[index]] / total;
            let pane = if horizontal {
                egui::Rect::from_min_size(
                    egui::pos2(cursor, rect.top()),
                    Vec2::new(length, rect.height()),
                )
            } else {
                egui::Rect::from_min_size(
                    egui::pos2(rect.left(), cursor),
                    Vec2::new(rect.width(), length),
                )
            };
            let mut child_ui = ui.new_child(egui::UiBuilder::new().id_salt(index).max_rect(pane));
            child_ui.set_clip_rect(pane.intersect(ui.clip_rect()));
            self.node(&mut child_ui, child);
            cursor += length;
            if index + 1 < node.children.len() {
                let drag_rect = if horizontal {
                    egui::Rect::from_min_size(
                        egui::pos2(cursor, rect.top()),
                        Vec2::new(gutter, rect.height()),
                    )
                } else {
                    egui::Rect::from_min_size(
                        egui::pos2(rect.left(), cursor),
                        Vec2::new(rect.width(), gutter),
                    )
                };
                let response = ui
                    .interact(
                        drag_rect,
                        ui.id().with(("split-drag", index)),
                        egui::Sense::drag(),
                    )
                    .on_hover_cursor(if horizontal {
                        egui::CursorIcon::ResizeHorizontal
                    } else {
                        egui::CursorIcon::ResizeVertical
                    });
                if response.hovered() || response.dragged() {
                    ui.painter().rect_filled(
                        drag_rect.shrink(2.0),
                        2.0,
                        ui.visuals().widgets.hovered.bg_fill,
                    );
                }
                if response.dragged() {
                    let delta = ui.input(|input| {
                        if horizontal {
                            input.pointer.delta().x
                        } else {
                            input.pointer.delta().y
                        }
                    }) * total
                        / available;
                    let left = indices[index];
                    let right = indices[index + 1];
                    let minimum =
                        (100.0 * total / available).min((sizes[left] + sizes[right]) / 3.0);
                    let change = delta.clamp(minimum - sizes[left], sizes[right] - minimum);
                    sizes[left] += change;
                    sizes[right] -= change;
                    self.split_sizes
                        .insert(node.id.clone(), (node.revision, sizes.clone()));
                }
                if response.drag_stopped() {
                    let values: Vec<_> = sizes
                        .iter()
                        .map(|value| value.round().max(0.0) as u64)
                        .collect();
                    self.input(node, "split", json!(values));
                }
                cursor += gutter;
            }
        }
        ui.advance_cursor_after_rect(rect);
    }

    fn group(&mut self, ui: &mut Ui, node: &Node) {
        if node.flag("plain") {
            self.column(ui, &node.children);
            return;
        }
        egui::Frame::group(ui.style())
            .inner_margin(6.0)
            .show(ui, |ui| {
                ui.set_min_width((ui.available_width() - 2.0).max(0.0));
                if node.flag("checkable") {
                    let mut checked = node.flag("checked");
                    let response = ui.checkbox(&mut checked, RichText::new(&node.label).strong());
                    self.record(ui, node, &response);
                    if response.changed() {
                        self.input(node, "toggle", json!(checked));
                    }
                } else if !node.label.is_empty() {
                    let response = ui.label(RichText::new(&node.label).strong());
                    self.record(ui, node, &response);
                }
                self.column(ui, &node.children);
            });
    }

    fn steps(&mut self, ui: &mut Ui, node: &Node) {
        ui.horizontal_wrapped(|ui| {
            for (index, step) in node.array("steps").iter().enumerate() {
                let label = step["text"].as_str().unwrap_or("");
                let active = node.number("selected", 0.0) as usize == index;
                let mark = match step["state"].as_str() {
                    Some("completed") => "✓",
                    Some("warning") => "!",
                    Some("blocked") => "×",
                    _ => "",
                };
                let mut text = RichText::new(format!("{}  {label} {mark}", index + 1));
                if !active {
                    match step["state"].as_str() {
                        Some("warning") => text = text.color(ui.visuals().warn_fg_color),
                        Some("blocked") => text = text.color(ui.visuals().error_fg_color),
                        _ => {}
                    }
                }
                let response = ui.selectable_label(active, text);
                self.record(ui, node, &response);
                if response.clicked() {
                    self.input(node, "tab", json!(index));
                }
                response.on_hover_text(step["tooltip"].as_str().unwrap_or(label));
            }
        });
        ui.separator();
    }

    fn tabs(&mut self, ui: &mut Ui, node: &Node) {
        for corner in node.array("corners") {
            if let Ok(child) = serde_json::from_value::<Node>(corner.clone()) {
                self.node(ui, &child);
            }
        }
        ui.horizontal_wrapped(|ui| {
            for (index, tab) in node.array("tabs").iter().enumerate() {
                if tab["visible"] == false {
                    continue;
                }
                let response = ui.add_enabled(
                    tab["enabled"] != false,
                    egui::Button::selectable(
                        index == node.number("selected", 0.0) as usize,
                        tab["text"].as_str().unwrap_or(""),
                    ),
                );
                self.record(ui, node, &response);
                if response.clicked() {
                    self.input(node, "tab", json!(index));
                }
            }
        });
        ui.separator();
        self.column(ui, &node.children);
    }

    fn button(&mut self, ui: &mut Ui, node: &Node) -> egui::Response {
        let label = if node.label.is_empty() && node.text("image").is_empty() {
            &node.tooltip
        } else {
            &node.label
        };
        if node.flag("instant_menu") {
            return ui
                .menu_button(label, |ui| {
                    for value in node.array("menu") {
                        if let Ok(action) = serde_json::from_value::<Node>(value.clone()) {
                            self.menu_item(ui, &action);
                        }
                    }
                })
                .response;
        }
        let text = if node.flag("primary") || node.flag("checked") {
            RichText::new(label).color(ui.visuals().selection.stroke.color)
        } else {
            RichText::new(label)
        };
        let mut button = if let Some(texture) = self.textures.get(node.text("image")) {
            let image = egui::Image::new(texture).fit_to_exact_size(Vec2::splat(if label.is_empty() { 16.0 } else { 20.0 }));
            if label.is_empty() { egui::Button::image(image) } else { egui::Button::image_and_text(image, text) }
        } else {
            egui::Button::new(text)
        }
        .selected(node.flag("checked"));
        if node.flag("primary") {
            button = button.fill(ui.visuals().selection.bg_fill);
        }
        let response = ui.add_sized(
            Vec2::new(
                ui.available_width().min(minimum_width(ui, node)),
                control_height(ui),
            ),
            button,
        );
        if let Ok(swatch) = Color32::from_hex(node.text("swatch")) {
            ui.painter().hline(
                response.rect.shrink(4.0).x_range(),
                response.rect.bottom() - 3.0,
                egui::Stroke::new(2.0, swatch),
            );
        }
        if response.clicked() {
            self.input(node, "activate", Value::Null);
        }
        response
    }

    fn menu_item(&mut self, ui: &mut Ui, node: &Node) {
        if node.kind == "separator" {
            ui.separator();
            return;
        }
        if !node.children.is_empty() {
            let response = ui.menu_button(&node.label, |ui| {
                for child in &node.children {
                    self.menu_item(ui, child);
                }
            }).response;
            self.record(ui, node, &response);
        } else {
            let response = ui.add_enabled(
                node.enabled,
                egui::Button::new(&node.label).selected(node.flag("checked")).truncate(),
            );
            self.record(ui, node, &response);
            if response.clicked() {
                self.input(node, "activate", Value::Null);
                ui.close();
            }
        }
    }

    fn text(&mut self, ui: &mut Ui, node: &Node) -> egui::Response {
        let follow_tail = node.flag("follow_tail")
            && node.number("offset", 0.0) + node.number("maximum", 65536.0)
                >= node.number("total", 0.0);
        let new_tail = follow_tail && self.edits.get(&node.id)
            .is_none_or(|edit| edit.authority != node.text("text"));
        let mut text = self.edit_text(&node.id, node.revision, node.text("text"));
        let original = text.clone();
        let multiline = node.flag("multiline");
        let readonly = node.flag("readonly");
        let mut immutable = node.text("text");
        let buffer: &mut dyn egui::TextBuffer = if readonly { &mut immutable } else { &mut text };
        let edit = if multiline {
            egui::TextEdit::multiline(buffer)
        } else {
            egui::TextEdit::singleline(buffer)
        }
        .id_salt("value")
        .hint_text(node.text("placeholder"))
        .desired_width(f32::INFINITY)
        .password(node.flag("password"))
        .char_limit(node.number("maximum", 65536.0) as usize);
        let response = if multiline && readonly {
            let footer = control_height(ui) + ui.spacing().item_spacing.y;
            let height = (bounded_height(ui) - footer).max(0.0);
            let output = egui::ScrollArea::vertical()
                .id_salt("text-scroll")
                .min_scrolled_height(0.0)
                .max_height(height)
                .auto_shrink([false, false])
                .stick_to_bottom(follow_tail)
                .show(ui, |ui| {
                    ui.add_sized(Vec2::new(ui.available_width(), height), edit)
                });
            if new_tail {
                let mut state = output.state;
                state.offset.y = (output.content_size.y - output.inner_rect.height()).max(0.0);
                state.store(ui.ctx(), output.id);
                ui.request_repaint();
            }
            let mut response = output.inner;
            // Expose the viewport to hit testing and layout audits, not the
            // potentially thousands of lines inside its scrolling contents.
            response.rect = output.inner_rect;
            response.interact_rect = response.interact_rect.intersect(output.inner_rect);
            response
        } else {
            let height = if multiline { bounded_height(ui).max(78.0) } else { control_height(ui) };
            ui.add_sized(Vec2::new(ui.available_width(), height), edit)
        };
        if response.changed() && !readonly {
            if node.flag("digits_only") {
                // Match QLineEdit's numeric input filtering instead of sending
                // invalid keystrokes to the authority as protocol errors.
                text.retain(|character| character.is_ascii_digit());
            }
            if let Some(entry) = self.edits.get_mut(&node.id) {
                entry.value = text.clone();
            }
            if text != original {
                self.input(node, "text", json!(text));
            }
        }
        if response.lost_focus() && !multiline {
            let action =
                if node.kind == "text" && ui.input(|input| input.key_pressed(egui::Key::Enter)) {
                    "submit"
                } else {
                    "finish_edit"
                };
            self.input(node, action, Value::Null);
        }
        if node.flag("readonly") {
            ui.horizontal(|ui| {
                if ui.small_button(self.tr("copy", "Copy")).clicked() {
                    self.input(node, "copy", Value::Null);
                }
                let total = node.number("total", 0.0) as usize;
                let offset = node.number("offset", 0.0) as usize;
                if total > 65536 {
                    if ui
                        .add_enabled(
                            offset > 0,
                            egui::Button::new(self.tr("previous", "Previous")),
                        )
                        .clicked()
                    {
                        self.input(
                            node,
                            "range",
                            json!({"offset": offset.saturating_sub(65536)}),
                        );
                    }
                    if ui
                        .add_enabled(
                            offset + 65536 < total,
                            egui::Button::new(self.tr("next", "Next")),
                        )
                        .clicked()
                    {
                        self.input(node, "range", json!({"offset": offset + 65536}));
                    }
                }
            });
        }
        response
    }

    fn choice(&mut self, ui: &mut Ui, node: &Node) {
        if node.flag("editable") {
            let width = ui.available_width();
            ui.horizontal(|ui| {
                let arrow_width = control_height(ui);
                let field = ui.allocate_ui_with_layout(Vec2::new((width - arrow_width - ui.spacing().item_spacing.x).max(24.0), arrow_width),
                    egui::Layout::top_down(egui::Align::Min), |ui| {
                        let mut edit = node.clone();
                        edit.props["maximum"] = json!(65536);
                        let response = self.text(ui, &edit);
                        self.record(ui, node, &response);
                    });
                let arrow = ui.add_sized(Vec2::splat(arrow_width), egui::Button::new("▾"));
                egui::Popup::menu(&arrow).anchor(field.response.rect.union(arrow.rect)).width(width).show(|ui| {
                    ui.set_width((width - 16.0).max(40.0));
                    egui::ScrollArea::vertical().max_height(350.0).show(ui, |ui| self.choice_options(ui, node));
                });
                self.record(ui, node, &arrow);
            });
            return;
        }
        ui.set_min_width(minimum_width(ui, node).min(ui.ctx().content_rect().width() - 32.0));
        let response = egui::ComboBox::from_id_salt("choices")
            .selected_text(node.text("text"))
            .truncate()
            .width(ui.available_width().max(80.0))
            .height(350.0)
            .show_ui(ui, |ui| self.choice_options(ui, node))
            .response;
        self.record(ui, node, &response);
    }

    fn choice_options(&mut self, ui: &mut Ui, node: &Node) {
        let option_width = node.array("options").iter().map(|option| {
            ui.painter().layout_no_wrap(option["text"].as_str().unwrap_or("").to_owned(),
                TextStyle::Button.resolve(ui.style()), ui.visuals().text_color()).size().x
        }).fold(0.0, f32::max) + 2.0 * ui.spacing().button_padding.x + 4.0;
        // The closed field may only say "All"; its menu still needs to fit
        // longer choices and the current font, within the window's bounds.
        let width = ui.available_width().max(option_width).min(ui.ctx().content_rect().width() - 32.0);
        ui.set_width(width);
        for option in node.array("options") {
            let selected = option["index"].as_f64().unwrap_or(-1.0) == node.number("selected", -1.0);
            let label = option["text"].as_str().unwrap_or("");
            let response = ui.add_enabled(option["enabled"] != false,
                egui::Button::selectable(selected, label).truncate());
            if response.clicked() {
                self.input(node, "choose", option["index"].clone());
                ui.close();
            }
            let tooltip = option["tooltip"].as_str().filter(|text| !text.is_empty()).unwrap_or(label);
            response.on_hover_text(tooltip).on_disabled_hover_text(tooltip);
        }
        self.paging(ui, node, &node.props);
    }

    fn image_crop(&mut self, ui: &mut Ui, node: &Node) -> egui::Response {
        let source = Vec2::new(
            node.number("width", 1.0) as f32,
            node.number("height", 1.0) as f32,
        );
        let scale = (ui.available_width() / source.x)
            .min(bounded_height(ui).clamp(180.0, 420.0) / source.y);
        let (space, _) = ui.allocate_exact_size(
            Vec2::new(ui.available_width(), source.y * scale),
            egui::Sense::hover(),
        );
        let rect = egui::Rect::from_center_size(space.center(), source * scale);
        let response = ui.interact(rect, ui.id().with("crop-image"), egui::Sense::drag());
        if let Some(texture) = self.textures.get(node.text("image")) {
            ui.painter().image(
                texture.id(),
                rect,
                egui::Rect::from_min_max(egui::Pos2::ZERO, egui::pos2(1.0, 1.0)),
                Color32::WHITE,
            );
        }
        let values = node.array("selection");
        let v = |index: usize| values.get(index).and_then(Value::as_f64).unwrap_or(0.0) as f32;
        let mut selection = egui::Rect::from_min_size(
            rect.min + Vec2::new(v(0), v(1)) * scale,
            Vec2::new(v(2), v(3)) * scale,
        );
        if response.drag_started() {
            if let Some(point) = ui.input(|input| input.pointer.press_origin()) {
                self.crop_origin.insert(node.id.clone(), point);
            }
        }
        if response.dragged() || response.drag_stopped() {
            if let (Some(start), Some(end)) = (
                self.crop_origin.get(&node.id),
                response.interact_pointer_pos(),
            ) {
                selection = egui::Rect::from_two_pos(rect.clamp(*start), rect.clamp(end));
                if response.drag_stopped() {
                    let min = (selection.min - rect.min) / scale;
                    let max = (selection.max - rect.min) / scale;
                    let x = min.x.floor().max(0.0) as u64;
                    let y = min.y.floor().max(0.0) as u64;
                    let w = (max.x.floor() + 1.0).min(source.x) as u64 - x;
                    let h = (max.y.floor() + 1.0).min(source.y) as u64 - y;
                    if w >= 2 && h >= 2 {
                        self.input(node, "crop", json!([x, y, w, h]));
                    }
                }
            }
        }
        for outside in [
            egui::Rect::from_min_max(rect.min, egui::pos2(rect.right(), selection.top())),
            egui::Rect::from_min_max(egui::pos2(rect.left(), selection.bottom()), rect.max),
            egui::Rect::from_min_max(
                egui::pos2(rect.left(), selection.top()),
                selection.left_bottom(),
            ),
            egui::Rect::from_min_max(
                selection.right_top(),
                egui::pos2(rect.right(), selection.bottom()),
            ),
        ] {
            ui.painter()
                .rect_filled(outside, 0.0, Color32::from_black_alpha(135));
        }
        ui.painter().rect_stroke(
            selection,
            0.0,
            egui::Stroke::new(2.0, ui.visuals().selection.bg_fill),
            egui::StrokeKind::Inside,
        );
        response.on_hover_cursor(egui::CursorIcon::Crosshair)
    }

    fn label(&mut self, ui: &mut Ui, node: &Node) -> egui::Response {
        if let Some(texture) = self.textures.get(node.text("image")) {
            ui.add(
                egui::Image::new(texture)
                    .max_size(Vec2::splat(320.0))
                    .shrink_to_fit(),
            );
        }
        if !node.array("spans").is_empty() {
            if node.array("links").is_empty() {
                let mut job = egui::text::LayoutJob::default();
                for span in node.array("spans") {
                    let mut text = RichText::new(span["text"].as_str().unwrap_or(""));
                    if span["bold"] == true || node.flag("bold") {
                        text = text.strong();
                    }
                    if span["italic"] == true {
                        text = text.italics();
                    }
                    if let Ok(color) = Color32::from_hex(span["color"].as_str().unwrap_or("")) {
                        text = text.color(readable_color(color, ui.visuals().panel_fill));
                    }
                    text.append_to(
                        &mut job,
                        ui.style(),
                        egui::FontSelection::Default,
                        egui::Align::Min,
                    );
                }
                return ui.add(egui::Label::new(job).wrap());
            }
            return ui
                .horizontal_wrapped(|ui| {
                    ui.spacing_mut().item_spacing.x = 0.0;
                    for span in node.array("spans") {
                        let value = span["text"].as_str().unwrap_or("");
                        if value == "\n" {
                            ui.end_row();
                            continue;
                        }
                        let mut text = RichText::new(value);
                        if span["bold"] == true || node.flag("bold") {
                            text = text.strong();
                        }
                        if span["italic"] == true {
                            text = text.italics();
                        }
                        if let Ok(color) = Color32::from_hex(span["color"].as_str().unwrap_or("")) {
                            text = text.color(readable_color(color, ui.visuals().panel_fill));
                        }
                        let url = span["url"].as_str().unwrap_or("");
                        if url.is_empty() {
                            ui.add(egui::Label::new(text).wrap());
                        } else if ui.link(text).clicked() {
                            self.input(node, "link", json!(url));
                        }
                    }
                })
                .response;
        }
        let text = if node.flag("bold") {
            RichText::new(node.text("text")).strong()
        } else {
            RichText::new(node.text("text"))
        };
        let response = ui.add(egui::Label::new(text).wrap());
        for link in node.array("links") {
            if ui.link(link["text"].as_str().unwrap_or("")).clicked() {
                self.input(node, "link", link["url"].clone());
            }
        }
        response
    }

    fn paging(&mut self, ui: &mut Ui, node: &Node, props: &Value) {
        let total = props["total"].as_u64().unwrap_or(0);
        let offset = props["offset"].as_u64().unwrap_or(0);
        let end = props["end"].as_u64().unwrap_or((offset + 128).min(total));
        if offset == 0 && end >= total {
            return;
        }
        ui.horizontal(|ui| {
            if ui.add_enabled(offset > 0, egui::Button::new(self.tr("previous", "Previous"))).clicked() {
                self.input(node, "range", json!({"offset": offset.saturating_sub(128), "parent": props["parent"].as_array().cloned().unwrap_or_default()}));
            }
            ui.label(format!("{}–{} / {}", offset + 1, end, total));
            if ui.add_enabled(end < total, egui::Button::new(self.tr("next", "Next"))).clicked() {
                self.input(node, "range", json!({"offset": end, "parent": props["parent"].as_array().cloned().unwrap_or_default()}));
            }
        });
    }

    fn table(&mut self, ui: &mut Ui, node: &Node) {
        let focus_id = self
            .table_focus
            .get(&node.id)
            .copied()
            .unwrap_or_else(|| ui.id().with("table-focus"));
        let (focused, previously_focused) = ui.memory(|memory| {
            (memory.has_focus(focus_id), memory.had_focus_last_frame(focus_id))
        });
        // Both memory and input lock the same egui context. Release the memory
        // read before input takes its write lock when a row loses focus.
        let focused = focused
            || previously_focused && !ui.input(|input| input.pointer.any_pressed());
        if focused {
            for (key, name) in [
                (egui::Key::ArrowUp, "Up"),
                (egui::Key::ArrowDown, "Down"),
                (egui::Key::ArrowLeft, "Left"),
                (egui::Key::ArrowRight, "Right"),
                (egui::Key::Home, "Home"),
                (egui::Key::End, "End"),
                (egui::Key::PageUp, "PageUp"),
                (egui::Key::PageDown, "PageDown"),
                (egui::Key::Enter, "Return"),
                (egui::Key::Space, "Space"),
            ] {
                let modifiers = ui.input(|input| input.modifiers);
                if ui.input_mut(|input| input.consume_key(modifiers, key)) {
                    ui.memory_mut(|memory| memory.request_focus(focus_id));
                    self.input(
                        node,
                        "key",
                        json!({"key":name,"shift":modifiers.shift,"control":modifiers.command}),
                    );
                }
            }
        }
        let columns: Vec<_> = node
            .array("columns")
            .iter()
            .filter(|column| column["hidden"] != true)
            .collect();
        let row_header_width = if node.flag("row_headers") {
            let digits = ui.painter().layout_no_wrap(
                (node.number("total", 0.0) as u64).to_string(),
                TextStyle::Body.resolve(ui.style()), ui.visuals().text_color(),
            ).size().x;
            node.array("rows").iter().map(|row| ui.painter().layout_no_wrap(
                row["label"].as_str().unwrap_or("").to_owned(), TextStyle::Body.resolve(ui.style()),
                ui.visuals().text_color()).size().x).fold(digits, f32::max).min(120.0) + 12.0
        } else { 0.0 };
        let header_height = control_height(ui);
        let header_space = if node.flag("headers") { header_height + ui.spacing().item_spacing.y } else { 0.0 };
        let gaps = ui.spacing().item_spacing.x
            * (columns.len() + usize::from(row_header_width > 0.0)).saturating_sub(1) as f32;
        let budget = (ui.available_width() - row_header_width - gaps
            - ui.spacing().scroll.allocated_width()).max(0.0);
        // Qt's hidden backing view can be much wider than this pane. Preserve
        // content columns and give the remaining space to its stretch columns;
        // scaling all widths equally starves short headings and price editors.
        let minimums: Vec<f32> = columns.iter().map(|column| {
            let heading = column["text"].as_str().unwrap_or("");
            let heading = if node.flag("sortable") { format!("{heading} ▾") } else { heading.to_owned() };
            let heading_width = ui.painter().layout_no_wrap(
                heading, TextStyle::Body.resolve(ui.style()), ui.visuals().text_color(),
            ).size().x + 2.0 * ui.spacing().button_padding.x + 4.0;
            let index = column["index"].as_u64().unwrap_or(0) as usize;
            let editor_width = node.array("rows").iter().map(|row| {
                let cell = &row["cells"][index];
                if let Ok(control) = serde_json::from_value::<Node>(cell["control"].clone()) {
                    minimum_width(ui, &control).min(180.0)
                } else if cell["editable"] == true { 64.0 } else { 0.0 }
            }).fold(0.0, f32::max);
            heading_width.clamp(40.0, 260.0).max(editor_width)
        }).collect();
        let manual: Vec<_> = columns.iter().map(|column| self.column_widths
            .get(&(node.id.clone(), column["index"].as_u64().unwrap_or(0))).copied()).collect();
        let mut widths: Vec<_> = columns.iter().enumerate().map(|(index, column)| {
            manual[index].unwrap_or_else(|| if column["stretch"] == true {
                minimums[index]
            } else if column["size_to_contents"] == true {
                let col = column["index"].as_u64().unwrap_or(0) as usize;
                node.array("rows").iter().map(|row| {
                    ui.painter().layout_no_wrap(row["cells"][col]["text"].as_str().unwrap_or("").to_owned(),
                        TextStyle::Body.resolve(ui.style()), ui.visuals().text_color()).size().x
                        + 2.0 * (ui.spacing().button_padding.x + ui.spacing().item_spacing.x)
                }).fold(minimums[index], f32::max).min(220.0).max(minimums[index])
            } else { (column["width"].as_f64().unwrap_or(160.0) as f32).max(minimums[index]) })
        }).collect();
        let used = widths.iter().sum::<f32>();
        if used > budget {
            let shrinkable: f32 = widths.iter().enumerate().filter(|(i, _)| manual[*i].is_none())
                .map(|(i, width)| (width - minimums[i]).max(0.0)).sum();
            let factor = ((used - budget) / shrinkable.max(1.0)).min(1.0);
            for (index, width) in widths.iter_mut().enumerate() {
                if manual[index].is_none() { *width -= (*width - minimums[index]).max(0.0) * factor; }
            }
        } else {
            let has_stretch = columns.iter().enumerate().any(|(i, column)| column["stretch"] == true && manual[i].is_none());
            let stretch: Vec<_> = columns.iter().enumerate().filter(|(i, column)|
                manual[*i].is_none() && (!has_stretch || column["stretch"] == true)).map(|(i, _)| i).collect();
            let extra = (budget - used) / stretch.len().max(1) as f32;
            for index in stretch { widths[index] += extra; }
        }
        let total = node.number("total", 0.0) as u64;
        let offset = node.number("offset", 0.0) as u64;
        let end = node.props["end"].as_u64().unwrap_or((offset + 128).min(total));
        let paging_height = if offset > 0 || end < total {
            control_height(ui) + ui.spacing().item_spacing.y
        } else { 0.0 };
        let height = (bounded_height(ui) - paging_height).max(100.0);
        let fill_height = if self.compact_depth > 0 { has_stretched_editor(node) } else { layout_flexible(node) };
        let rows = total.max(1) as f32;
        let rows = if self.compact_depth > 0 && !fill_height { rows.min(8.0) } else { rows };
        let height = if fill_height { height } else {
            height.min(rows * (control_height(ui) + ui.spacing().item_spacing.y) + header_space)
        };
        let mut at_end = false;
        let response = egui::ScrollArea::horizontal().id_salt("table-columns").auto_shrink([false,!fill_height])
            .max_height(height).show(ui, |ui| {
                ui.set_min_width(widths.iter().sum::<f32>() + row_header_width + gaps);
                if node.flag("headers") { ui.horizontal(|ui| {
                    if row_header_width > 0.0 { ui.allocate_space(Vec2::new(row_header_width,header_height)); }
                    for (column,width) in columns.iter().zip(&widths) {
                        let mut text = column["text"].as_str().unwrap_or("").to_owned();
                        if column["index"].as_f64() == Some(node.number("sort_column",-1.0)) && node.flag("sortable") {
                            text.push_str(if node.flag("sort_descending") {" ▾"} else {" ▴"});
                        }
                        let (header_rect, _) = ui.allocate_exact_size(Vec2::new(*width,header_height),egui::Sense::hover());
                        let mut button_rect = header_rect;
                        button_rect.min.x += ui.spacing().button_padding.x;
                        if column["resizable"] == true { button_rect.max.x -= 4.0; }
                        let sense = if node.flag("sortable") { egui::Sense::click() } else { egui::Sense::hover() };
                        let response = ui.interact(button_rect, ui.id().with(("column-header", column["index"].as_u64())), sense).on_hover_text(&text);
                        ui.painter().with_clip_rect(ui.clip_rect().intersect(button_rect)).text(
                            button_rect.left_center(), egui::Align2::LEFT_CENTER, &text,
                            TextStyle::Body.resolve(ui.style()), ui.visuals().text_color());
                        ui.painter().hline(header_rect.x_range(), header_rect.bottom(), ui.visuals().widgets.noninteractive.bg_stroke);
                        ui.advance_cursor_after_rect(header_rect);
                        if response.clicked() && node.flag("sortable") {
                            self.input(node,"sort",json!({"column":column["index"],"descending":!node.flag("sort_descending")}));
                        }
                        if column["resizable"] == true {
                            // Reserve the edge for dragging. Overlapping the
                            // button lets its click sense steal native drags.
                            let rect = egui::Rect::from_center_size(egui::pos2(header_rect.right(),header_rect.center().y),Vec2::new(8.0,header_rect.height()));
                            ui.interact(rect,ui.id().with(("column-width",column["index"].as_u64())),egui::Sense::drag()).on_hover_cursor(egui::CursorIcon::ResizeHorizontal);
                            let key = (node.id.clone(), column["index"].as_u64().unwrap_or(0));
                            if !ui.is_enabled() {
                                self.column_drag_origins.remove(&key);
                            }
                            // Preserve event order: a press and its first move
                            // can share a frame. egui's final-position hit test
                            // then misses a grab that started on this edge.
                            for event in ui.input(|input| input.raw.events.clone()) {
                                match event {
                                    egui::Event::PointerButton {pos, button:egui::PointerButton::Primary, pressed:true, ..} => {
                                        self.column_drag_origins.remove(&key);
                                        if ui.is_enabled() && rect.contains(pos) && ui.clip_rect().contains(pos)
                                            && ui.ctx().layer_id_at(pos) == Some(ui.layer_id()) {
                                            self.column_drag_origins.insert(key.clone(), (pos.x, *width));
                                        }
                                    }
                                    egui::Event::PointerMoved(pos) => {
                                        if let Some((start, original)) = self.column_drag_origins.get(&key) {
                                            self.column_widths.insert(key.clone(), (*original + pos.x - *start).clamp(40.0,4000.0));
                                        }
                                    }
                                    egui::Event::PointerButton {pos, button:egui::PointerButton::Primary, pressed:false, ..} => {
                                        if let Some((start, original)) = self.column_drag_origins.remove(&key) {
                                            let resized = (original + pos.x - start).clamp(40.0,4000.0);
                                            self.column_widths.insert(key.clone(), resized);
                                            self.input(node,"resize_column",json!({"column":column["index"],"width":resized.round() as u64}));
                                        }
                                    }
                                    _ => {}
                                }
                            }
                            if !ui.input(|input| input.pointer.primary_down()) {
                                self.column_drag_origins.remove(&key);
                            }
                        }
                    }
                }); }
                let rows = egui::ScrollArea::vertical().id_salt(("rows",offset)).auto_shrink([false,!fill_height])
                    .min_scrolled_height(0.0)
                    .max_height((height-header_space).max(header_height)).show(ui, |ui| {
                        if node.array("rows").is_empty() { ui.weak("—"); }
                        self.table_rows(ui,node,&node.props,&columns,&widths,row_header_width,0,focus_id);
                    });
                let scrolling_down = ui.input(|input| input.pointer.latest_pos().is_some_and(|point| rows.inner_rect.contains(point))
                    && input.raw.events.iter().any(|event| matches!(event, egui::Event::MouseWheel { delta, .. } if delta.y < 0.0)));
                at_end = (rows.state.offset.y > 0.0 || scrolling_down)
                    && rows.state.offset.y + rows.inner_rect.height() >= rows.content_size.y-40.0;
            });
        let response_for_audit = ui.interact(
            response.inner_rect,
            ui.id().with("table-audit"),
            egui::Sense::hover(),
        );
        self.record(ui, node, &response_for_audit);
        ui.memory_mut(|memory| {
            memory.set_focus_lock_filter(
                focus_id,
                egui::EventFilter {
                    horizontal_arrows: true,
                    vertical_arrows: true,
                    ..Default::default()
                },
            )
        });
        let request = (node.props["model"].clone(), offset, total);
        if at_end && end >= total && self.table_end_requests.get(&node.id) != Some(&request) {
            // Reaching an intermediate presentation page is not the end of the
            // Qt model. Repeated requests otherwise append rows every frame and
            // race the refreshed document while the user remains at the bottom.
            self.table_end_requests.insert(node.id.clone(), request);
            self.input(
                node,
                "range",
                json!({"offset": offset, "end": true}),
            );
        }
        self.paging(ui, node, &node.props);
    }

    fn table_rows(
        &mut self,
        ui: &mut Ui,
        node: &Node,
        props: &Value,
        columns: &[&Value],
        widths: &[f32],
        row_header_width: f32,
        depth: usize,
        focus_id: egui::Id,
    ) {
        if let Some(rows) = props["rows"].as_array() {
            for row in rows {
                ui.push_id(row["path"].to_string(), |ui| {
                    ui.horizontal(|ui| {
                        if node.flag("row_headers") {
                            ui.add_sized(Vec2::new(row_header_width, control_height(ui)), egui::Label::new(row["label"].as_str().unwrap_or("")).truncate());
                        }
                        for (column, width) in columns.iter().zip(widths) {
                            let col = column["index"].as_u64().unwrap_or(0) as usize;
                            let cell = &row["cells"][col];
                            ui.push_id(col, |ui| {
                                ui.allocate_ui_with_layout(Vec2::new(*width, control_height(ui)), egui::Layout::left_to_right(egui::Align::Center), |ui| {
                                    // Empty/check-only cells still occupy their column.
                                    // Otherwise the next editor slides left on those rows.
                                    ui.set_min_width(*width);
                                    if col == 0 && node.flag("tree") {
                                        ui.add_space(depth as f32 * 14.0);
                                        if row["children"] == true && ui.small_button(if row["expanded"] == true { "−" } else { "+" }).clicked() {
                                            self.input(node, "expand", json!({"path": row["path"], "expanded": row["expanded"] != true}));
                                        }
                                    }
                                    if let Ok(control) = serde_json::from_value::<Node>(cell["control"].clone()) {
                                        self.node(ui, &control);
                                    } else if let Some(check) = cell["check"].as_u64() {
                                        let mut checked = check == 2;
                                        let label = cell["text"].as_str().unwrap_or("");
                                        ui.style_mut().wrap_mode = Some(egui::TextWrapMode::Truncate);
                                        let response = ui.add_enabled(cell["enabled"] != false, egui::Checkbox::new(&mut checked, label));
                                        if response.changed() {
                                            self.input(node, "check_cell", json!({"path": row["path"], "column": col, "check": if checked {2} else {0}}));
                                        }
                                        let tooltip = cell["tooltip"].as_str().filter(|text| !text.is_empty()).unwrap_or(label);
                                        response.on_hover_text(tooltip).on_disabled_hover_text(tooltip);
                                    } else if cell["editable"] == true {
                                        let key = format!("{}:{}:{}", node.id, row["path"], col);
                                        let mut text = self.edit_text(&key, node.revision, cell["text"].as_str().unwrap_or(""));
                                        let background = Color32::from_hex(cell["background"].as_str().unwrap_or(""))
                                            .unwrap_or(ui.visuals().extreme_bg_color);
                                        let response = ui.add_sized(Vec2::new(*width, control_height(ui)),
                                            egui::TextEdit::singleline(&mut text).desired_width(0.0).background_color(background));
                                        if response.clicked() {
                                            self.input(node, "select", json!({"path":row["path"],"column":col,"mode":"click"}));
                                        }
                                        if response.changed() {
                                            if let Some(entry) = self.edits.get_mut(&key) { entry.value = text.clone(); }
                                            self.input(node, "cell", json!({"path": row["path"], "column": col, "text": text}));
                                        }
                                        response.on_hover_text(cell["tooltip"].as_str().unwrap_or(""));
                                    } else {
                                        let mut text = RichText::new(cell["text"].as_str().unwrap_or(""));
                                        if cell["bold"] == true { text = text.strong(); }
                                        if cell["italic"] == true { text = text.italics(); }
                                        if cell["selected"] == true { text = text.color(ui.visuals().selection.stroke.color); }
                                        else if let Ok(color) = Color32::from_hex(cell["foreground"].as_str().unwrap_or("")) { text = text.color(color); }
                                        let mut button = egui::Button::selectable(cell["selected"] == true, "").left_text(text).truncate();
                                        if cell["selected"] != true {
                                            if let Ok(color) = Color32::from_hex(cell["background"].as_str().unwrap_or("")) { button = button.fill(color); }
                                        }
                                        let response = ui.add_enabled_ui(cell["enabled"] != false,|ui|ui.add_sized(Vec2::new(*width,control_height(ui)),button)).inner;
                                        if response.clicked() || response.double_clicked() {
                                            response.request_focus();
                                            self.table_focus.insert(node.id.clone(),response.id);
                                            let mode = if response.double_clicked() { "double" } else if ui.input(|i| i.modifiers.shift) { "range" }
                                                else if ui.input(|i| i.modifiers.command) { "toggle" } else { "click" };
                                            self.input(node, "select", json!({"path": row["path"], "column": col, "mode": mode}));
                                        }
                                        if response.has_focus() { self.table_focus.insert(node.id.clone(),response.id); }
                                        if response.secondary_clicked() && node.flag("context_menu") {
                                            self.input(node, "menu", json!({"path": row["path"], "column": col}));
                                        }
                                        response.on_hover_text(cell["tooltip"].as_str().unwrap_or(""));
                                    }
                                });
                            });
                        }
                    });
                    if row["nested"].is_object() {
                        self.table_rows(ui, node, &row["nested"], columns, widths, row_header_width, depth + 1,focus_id);
                        self.paging(ui,node,&row["nested"]);
                    }
                });
            }
        }
    }
}

fn readable_color(mut foreground: Color32, background: Color32) -> Color32 {
    let luminance = |color: Color32| {
        let linear = |value: u8| {
            let value = value as f32 / 255.0;
            if value <= 0.04045 {
                value / 12.92
            } else {
                ((value + 0.055) / 1.055).powf(2.4)
            }
        };
        0.2126 * linear(color.r()) + 0.7152 * linear(color.g()) + 0.0722 * linear(color.b())
    };
    let base = luminance(background);
    for _ in 0..24 {
        let value = luminance(foreground);
        if (base.max(value) + 0.05) / (base.min(value) + 0.05) >= 4.5 {
            break;
        }
        let adjust = |channel: u8| {
            if base > 0.4 {
                (channel as f32 * 0.85) as u8
            } else {
                channel.saturating_add(16)
            }
        };
        foreground = Color32::from_rgb(
            adjust(foreground.r()),
            adjust(foreground.g()),
            adjust(foreground.b()),
        );
    }
    foreground
}

fn default_button(node: &Node) -> Option<&Node> {
    if node.kind == "button" && node.enabled && node.flag("default") {
        Some(node)
    } else {
        node.children.iter().find_map(default_button)
    }
}

fn bounded_height(ui: &Ui) -> f32 {
    let value = ui.available_height();
    if value.is_finite() {
        value.clamp(0.0, 4096.0)
    } else {
        600.0
    }
}

fn control_height(ui: &Ui) -> f32 {
    (ui.text_style_height(&TextStyle::Button) + 2.0 * ui.spacing().button_padding.y)
        .max(ui.spacing().interact_size.y).ceil()
}

fn layout_flexible(node: &Node) -> bool {
    match node.kind.as_str() {
        "table" => node.stretch > 0 || node.number("total", 0.0) > 8.0,
        "viewport" | "scroll" | "image_crop" => true,
        "text" => node.flag("multiline"),
        _ => node.children.iter().any(layout_flexible),
    }
}

fn has_stretched_editor(node: &Node) -> bool {
    // An explicitly expanding editor can fill an inspector without stretching
    // every short list that happens to share the scroll area.
    node.kind == "table" && node.stretch > 0 && node.number("total", 0.0) > 0.0
        || node.kind == "text" && node.flag("multiline") && node.flag("readonly") && node.stretch > 0
        || node.children.iter().any(has_stretched_editor)
}

fn dialog_body(node: &Node, actions: &mut Vec<Node>) -> Option<Node> {
    if node.flag("dialog_actions") {
        actions.push(node.clone());
        return None;
    }
    let mut body = node.clone();
    body.children = node
        .children
        .iter()
        .filter_map(|child| dialog_body(child, actions))
        .collect();
    if !node.children.is_empty() && body.children.is_empty() {
        None
    } else {
        Some(body)
    }
}

fn minimum_width(ui: &Ui, node: &Node) -> f32 {
    match node.kind.as_str() {
        "label" => (ui.painter().layout_no_wrap(node.text("text").to_owned(),
            TextStyle::Body.resolve(ui.style()), ui.visuals().text_color()).size().x + 4.0).clamp(12.0, 200.0),
        "number" => {
            let text = format!("{}{:.*}{}", node.text("prefix"), node.number("decimals", 0.0) as usize,
                node.number("value", 0.0), node.text("suffix"));
            (ui.painter().layout_no_wrap(text, TextStyle::Button.resolve(ui.style()),
                ui.visuals().text_color()).size().x + 24.0).clamp(64.0, 180.0)
        }
        "slider" => 140.0,
        "button" | "action" | "check" | "radio" => {
            let font = TextStyle::Button.resolve(ui.style());
            if node.label.is_empty() && !node.text("image").is_empty() { return control_height(ui) + 4.0; }
            let label = if node.label.is_empty() && node.text("image").is_empty() {
                &node.tooltip
            } else {
                &node.label
            };
            let text = ui
                .painter()
                .layout_no_wrap(label.clone(), font, ui.visuals().text_color());
            let accessory = if matches!(node.kind.as_str(), "check" | "radio") || !node.text("image").is_empty() {
                28.0
            } else {
                0.0
            };
            (text.size().x + ui.spacing().button_padding.x * 2.0 + accessory + 4.0)
                .clamp(24.0, 360.0)
        }
        "choice" if !node.flag("grow_x") && !node.flag("editable") => {
            (ui.painter().layout_no_wrap(node.text("text").to_owned(),
                TextStyle::Button.resolve(ui.style()), ui.visuals().text_color()).size().x
                + ui.spacing().icon_width + ui.spacing().item_spacing.x + ui.spacing().button_padding.x * 2.0 + 8.0).clamp(80.0, 240.0)
        }
        "text" | "choice" => 150.0,
        "row" => node.children.iter().map(|child| minimum_width(ui, child)).sum::<f32>()
            + ui.spacing().item_spacing.x * node.children.len().saturating_sub(1) as f32,
        "column" | "group" | "menu" => node
            .children
            .iter()
            .map(|child| minimum_width(ui, child))
            .fold(0.0, f32::max),
        _ => 180.0,
    }
}

fn estimate_height(ui: &Ui, node: &Node, width: f32) -> f32 {
    match node.kind.as_str() {
        "label" => {
            if node.text("text").is_empty() { return 0.0; }
            ui.painter().layout(node.text("text").to_owned(), TextStyle::Body.resolve(ui.style()),
                ui.visuals().text_color(), width.max(1.0)).size().y
        }
        "steps" => {
            if width < 900.0 {
                80.0
            } else {
                46.0
            }
        }
        "separator" => 8.0,
        "button" | "action" => {
            if !node.text("image").is_empty() { return control_height(ui); }
            let label = if node.label.is_empty() { &node.tooltip } else { &node.label };
            let text_width = (minimum_width(ui, node).min(width)
                - 2.0 * ui.spacing().button_padding.x).max(1.0);
            let text = ui.painter().layout(label.clone(), TextStyle::Button.resolve(ui.style()),
                ui.visuals().text_color(), text_width);
            (text.size().y + 2.0 * ui.spacing().button_padding.y).max(control_height(ui))
        }
        "text" if node.flag("multiline") => 100.0,
        "table" => node.number("total", 0.0).clamp(1.0, 8.0) as f32
            * (control_height(ui) + ui.spacing().item_spacing.y)
            + if node.flag("headers") { control_height(ui) + ui.spacing().item_spacing.y } else { 0.0 },
        "viewport" => 260.0,
        "row" => {
            let mut used = 0.0;
            let mut height = 0.0;
            let mut line_height: f32 = 0.0;
            for child in &node.children {
                let child_width = minimum_width(ui, child).min(width);
                if used > 0.0 && used + ui.spacing().item_spacing.x + child_width > width {
                    height += line_height + ui.spacing().item_spacing.y;
                    used = 0.0;
                    line_height = 0.0;
                }
                if used > 0.0 { used += ui.spacing().item_spacing.x; }
                used += child_width;
                line_height = line_height.max(estimate_height(ui, child, child_width));
            }
            height + line_height
        }
        "split" => node
            .children
            .iter()
            .map(|child| estimate_height(ui, child, width / node.children.len().max(1) as f32))
            .fold(control_height(ui), f32::max),
        "grid" => {
            let columns = node
                .children
                .iter()
                .map(|child| {
                    let cell = child.cell.unwrap_or([0, 0, 1, 1]);
                    cell[1] + cell[3]
                })
                .max()
                .unwrap_or(1)
                .max(1);
            let mut heights = BTreeMap::<i32, f32>::new();
            for child in &node.children {
                let cell = child.cell.unwrap_or([0, 0, 1, 1]);
                let height = estimate_height(ui, child, width * cell[3] as f32 / columns as f32);
                heights
                    .entry(cell[0])
                    .and_modify(|value| *value = value.max(height))
                    .or_insert(height);
            }
            heights.values().sum::<f32>() + heights.len().saturating_sub(1) as f32 * ui.spacing().item_spacing.y
        }
        "column" | "scroll" | "group" | "tabs" | "dialog" => {
            let height = node
                .children
                .iter()
                .map(|child| estimate_height(ui, child, width))
                .sum::<f32>()
                + node.children.len().saturating_sub(1) as f32 * ui.spacing().item_spacing.y;
            height
                + if matches!(node.kind.as_str(), "group" | "tabs") {
                    control_height(ui) + 16.0
                } else {
                    0.0
                }
        }
        _ => control_height(ui),
    }
}

pub fn apply_theme(context: &egui::Context, theme: &Value) {
    super::fonts::configure(context, theme);
    let dark = theme["dark"].as_bool().unwrap_or(true);
    let color = |key: &str, fallback: Color32| {
        theme[key]
            .as_str()
            .and_then(|value| Color32::from_hex(value).ok())
            .unwrap_or(fallback)
    };
    let theme_kind = if dark {
        egui::Theme::Dark
    } else {
        egui::Theme::Light
    };
    let mut style = (*context.style_of(theme_kind)).clone();
    style.visuals = if dark {
        egui::Visuals::dark()
    } else {
        egui::Visuals::light()
    };
    style.visuals.panel_fill = color("background", style.visuals.panel_fill);
    style.visuals.window_fill = color("panel", style.visuals.window_fill);
    style.visuals.extreme_bg_color = color("panel", style.visuals.extreme_bg_color);
    style.visuals.override_text_color = None;
    let foreground = color("text", if dark { Color32::WHITE } else { Color32::BLACK });
    for visuals in [
        &mut style.visuals.widgets.noninteractive,
        &mut style.visuals.widgets.inactive,
        &mut style.visuals.widgets.hovered,
        &mut style.visuals.widgets.active,
        &mut style.visuals.widgets.open,
    ] {
        visuals.fg_stroke.color = foreground;
        visuals.expansion = 0.0;
    }
    style.visuals.weak_text_color = Some(color("muted", Color32::GRAY));
    style.visuals.selection.bg_fill = color("accent", style.visuals.selection.bg_fill);
    style.visuals.selection.stroke.color = color("accent_text", Color32::WHITE);
    style.visuals.hyperlink_color = color("link", style.visuals.hyperlink_color);
    let button = color("button", style.visuals.widgets.inactive.bg_fill);
    let hover = color("button_hover", style.visuals.widgets.hovered.bg_fill);
    let pressed = color("button_pressed", style.visuals.widgets.active.bg_fill);
    let border = color("button_border", color("border", Color32::GRAY));
    for (visuals, fill) in [
        (&mut style.visuals.widgets.inactive, button),
        (&mut style.visuals.widgets.hovered, hover),
        (&mut style.visuals.widgets.active, pressed),
        (&mut style.visuals.widgets.open, pressed),
    ] {
        visuals.bg_fill = fill;
        visuals.weak_bg_fill = fill;
        visuals.bg_stroke = egui::Stroke::new(1.0, border);
    }
    style.visuals.widgets.noninteractive.bg_stroke.color = color(
        "border",
        style.visuals.widgets.noninteractive.bg_stroke.color,
    );
    let font = theme["font_pixels"]
        .as_f64()
        .unwrap_or(14.0)
        .clamp(8.0, 64.0) as f32;
    for kind in [TextStyle::Body, TextStyle::Button, TextStyle::Monospace] {
        style.text_styles.insert(kind, FontId::proportional(font));
    }
    style.text_styles.insert(
        TextStyle::Small,
        FontId::proportional((font - 1.0).max(8.0)),
    );
    style
        .text_styles
        .insert(TextStyle::Heading, FontId::proportional(font + 4.0));
    style.spacing.interact_size.y = font + 8.0;
    style.spacing.item_spacing = Vec2::new(6.0, 4.0);
    style.spacing.button_padding = Vec2::new(8.0, 3.0);
    style.spacing.scroll = egui::style::ScrollStyle::solid();
    context.set_style_of(theme_kind, style);
    context.set_theme(theme_kind);
}
