//! Shared presentation for management tasks. Controls and events
//! still belong to their Qt pages; this module only lays out and paints them.
use super::*;

#[cfg(test)]
#[path = "mod_management_virtual_tests.rs"]
mod virtual_tests;

impl PresentationView {
    pub(in super::super) fn management_page_control(&mut self, ui: &mut Ui, node: &Node) -> bool {
        let s = scale(ui);
        match node.kind.as_str() {
            "column" if node.name == "virtual_loader_page" => {
                // This workspace has expanding package/review panes. The generic
                // bounded splitter keeps their scrolling local instead of giving
                // every table a six-row height inside the page's outer scroll.
                self.management_page = false;
                self.column(ui, &node.children);
                self.management_page = true;
            }
            "column" | "dialog" => {
                for child in &node.children {
                    self.node(ui, child);
                }
            }
            "row" => self.management_row(ui, &node.children.iter().collect::<Vec<_>>()),
            "grid" => {
                let mut rows: BTreeMap<i32, Vec<&Node>> = BTreeMap::new();
                for child in &node.children {
                    rows.entry(child.cell.unwrap_or_default()[0])
                        .or_default()
                        .push(child);
                }
                for (row, mut cells) in rows {
                    cells.sort_by_key(|cell| cell.cell.unwrap_or_default()[1]);
                    ui.push_id(row, |ui| {
                        if cells.first().is_some_and(|cell| cell.kind == "label") {
                            self.node(ui, cells.remove(0));
                        }
                        self.management_row(ui, &cells);
                    });
                }
            }
            "group" if !node.flag("plain") && !node.flag("checkable") => {
                Frame::NONE
                    .fill(ui.visuals().window_fill)
                    .stroke(line(ui))
                    .corner_radius(6)
                    .inner_margin(margin(16.0 * s, 14.0 * s))
                    .show(ui, |ui| {
                        ui.set_min_width(ui.available_width());
                        if !node.label.is_empty() {
                            let response = ui.add(
                                egui::Label::new(
                                    RichText::new(&node.label).font(font(ui, 13.0)).strong(),
                                )
                                .wrap(),
                            );
                            self.record(ui, node, &response);
                            ui.add_space(2.0 * s);
                        }
                        for child in &node.children {
                            self.node(ui, child);
                        }
                    });
            }
            "button" | "action" if !node.flag("instant_menu") && node.text("image").is_empty() => {
                let width = self
                    .management_control_width(ui, node)
                    .min(ui.available_width());
                self.management_button(
                    ui,
                    node,
                    width,
                    None,
                    false,
                    node.flag("primary") || node.flag("checked"),
                    13.0,
                );
            }
            "label" if node.text("management_role") == "notice" => {
                Frame::NONE
                    .fill(semantic(ui, true).gamma_multiply(0.08))
                    .stroke(Stroke::new(1.0, semantic(ui, true).gamma_multiply(0.3)))
                    .corner_radius(4)
                    .inner_margin(margin(12.0 * s, 9.0 * s))
                    .show(ui, |ui| {
                        let response = ui.add(
                            egui::Label::new(
                                RichText::new(node.text("text"))
                                    .font(font(ui, 12.0))
                                    .color(semantic(ui, true)),
                            )
                            .wrap(),
                        );
                        self.record(ui, node, &response);
                    });
            }
            "label" if node.text("image").is_empty() && node.array("links").is_empty() => {
                if !node.text("text").is_empty() {
                    let text = RichText::new(node.text("text")).font(font(ui, 12.0));
                    let response = ui.add(
                        egui::Label::new(if node.flag("bold") {
                            text.strong()
                        } else {
                            text.color(muted(ui))
                        })
                        .wrap(),
                    );
                    self.record(ui, node, &response);
                }
            }
            "tabs" => {
                self.management_tabs(ui, node);
                ui.add_space(8.0 * s);
                for child in &node.children {
                    self.node(ui, child);
                }
            }
            "choice" if !node.flag("editable") => {
                let response = egui::ComboBox::from_id_salt("management-choice")
                    .selected_text(node.text("text"))
                    .wrap()
                    .width(ui.available_width())
                    .height((350.0 * s).min(ui.ctx().content_rect().height() - 32.0))
                    .show_ui(ui, |ui| {
                        let width = ui.available_width().min(ui.ctx().content_rect().width() - 32.0);
                        ui.set_width(width);
                        for option in node.array("options") {
                            let selected = option["index"].as_f64().unwrap_or(-1.0)
                                == node.number("selected", -1.0);
                            let response = ui.add_enabled(
                                option["enabled"] != false,
                                egui::Button::selectable(selected, option["text"].as_str().unwrap_or("")).wrap(),
                            );
                            if response.clicked() {
                                self.input(node, "choose", option["index"].clone());
                                ui.close();
                            }
                        }
                    })
                    .response;
                self.record(ui, node, &response);
            }
            "split" => {
                if ui.available_width() < 800.0 * s {
                    for child in &node.children {
                        self.node(ui, child);
                    }
                } else {
                    let width = (ui.available_width() - 10.0) / node.children.len().max(1) as f32;
                    let height = node
                        .children
                        .iter()
                        .map(|child| self.management_content_height(ui, child, width))
                        .fold(300.0 * s, f32::max);
                    ui.allocate_ui_with_layout(
                        vec2(ui.available_width(), height),
                        egui::Layout::top_down(egui::Align::Min),
                        |ui| self.split(ui, node),
                    );
                }
            }
            "table" => {
                Frame::NONE
                    .fill(ui.visuals().extreme_bg_color)
                    .stroke(line(ui))
                    .corner_radius(4)
                    .inner_margin(margin(8.0 * s, 6.0 * s))
                    .show(ui, |ui| {
                        let height = self.management_content_height(ui, node, ui.available_width());
                        ui.allocate_ui_with_layout(
                            vec2(ui.available_width(), height),
                            egui::Layout::top_down(egui::Align::Min),
                            |ui| {
                                self.table(ui, node);
                            },
                        );
                        if node.number("total", 0.0) == 0.0 && !node.text("empty_text").is_empty() {
                            ui.add_space(6.0 * s);
                            let response = ui.add(
                                egui::Label::new(
                                    RichText::new(node.text("empty_text")).color(muted(ui)),
                                )
                                .wrap(),
                            );
                            response.on_hover_text(&node.tooltip);
                        }
                    });
            }
            "text" if node.flag("multiline") => {
                if node.flag("readonly") && node.text("text").is_empty() {
                    let text = galley(
                        ui,
                        node.text("placeholder"),
                        12.0,
                        muted(ui),
                        ui.available_width() - 24.0 * s,
                    );
                    let size = vec2(
                        ui.available_width(),
                        (text.size().y + 24.0 * s).max(88.0 * s),
                    );
                    let (rect, response) = ui.allocate_exact_size(size, Sense::hover());
                    ui.painter().rect(
                        rect,
                        4.0,
                        ui.visuals().extreme_bg_color,
                        line(ui),
                        StrokeKind::Inside,
                    );
                    ui.painter()
                        .galley(rect.min + vec2(12.0, 12.0) * s, text, muted(ui));
                    self.record(ui, node, &response);
                    return true;
                }
                let height = self.management_content_height(ui, node, ui.available_width());
                ui.allocate_ui_with_layout(
                    vec2(ui.available_width(), height),
                    egui::Layout::top_down(egui::Align::Min),
                    |ui| {
                        let response = self.text(ui, node);
                        self.record(ui, node, &response);
                    },
                );
            }
            "viewport" => {
                let size = vec2(ui.available_width(), 280.0 * s);
                let (rect, response) = ui.allocate_exact_size(size, Sense::hover());
                ui.painter().rect(
                    rect,
                    4.0,
                    ui.visuals().extreme_bg_color,
                    line(ui),
                    StrokeKind::Inside,
                );
                self.portals.push(Portal {
                    id: node.id.clone(),
                    rect: rect_array(rect),
                    clip: rect_array(ui.clip_rect()),
                    occlusions: Vec::new(),
                });
                self.record(ui, node, &response);
            }
            _ => return false,
        }
        true
    }

    fn management_control_width(&self, ui: &Ui, node: &Node) -> f32 {
        let s = scale(ui);
        match node.kind.as_str() {
            "button" | "action" => {
                galley(ui, &node.label, 13.0, muted(ui), f32::INFINITY)
                    .size()
                    .x
                    + 24.0 * s
            }
            "group" => 320.0 * s,
            "text" | "choice" => 180.0 * s,
            _ => minimum_width(ui, node),
        }
    }

    fn management_row(&mut self, ui: &mut Ui, children: &[&Node]) {
        if children.is_empty() {
            return;
        }
        let available = ui.available_width();
        let gap = ui.spacing().item_spacing.x;
        let wanted: Vec<_> = children
            .iter()
            .map(|child| self.management_control_width(ui, child).min(available))
            .collect();
        let minimum = wanted.iter().sum::<f32>() + gap * children.len().saturating_sub(1) as f32;
        if minimum > available && children.len() > 1 {
            let mut start = 0;
            let mut used = 0.0;
            for (i, width) in wanted.iter().enumerate() {
                if i > start && used + gap + width > available {
                    ui.push_id(start, |ui| self.management_row(ui, &children[start..i]));
                    start = i;
                    used = 0.0;
                }
                used += width + if i > start { gap } else { 0.0 };
            }
            ui.push_id(start, |ui| self.management_row(ui, &children[start..]));
            return;
        }
        let grows = |child: &Node| {
            matches!(
                child.kind.as_str(),
                "text" | "choice" | "group" | "column" | "row"
            )
        };
        let weight = children
            .iter()
            .filter(|child| grows(child))
            .map(|child| child.stretch.max(1) as f32)
            .sum::<f32>()
            .max(1.0);
        let extra = (available - minimum).max(0.0);
        ui.horizontal_top(|ui| {
            for (i, child) in children.iter().enumerate() {
                let width = wanted[i]
                    + if grows(child) {
                        extra * child.stretch.max(1) as f32 / weight
                    } else {
                        0.0
                    };
                ui.push_id(i, |ui| {
                    ui.allocate_ui_with_layout(
                        vec2(width, control_height(ui)),
                        egui::Layout::top_down(egui::Align::Min),
                        |ui| {
                            ui.set_width(width);
                            self.node(ui, child);
                        },
                    );
                });
            }
        });
    }

    fn management_content_height(&self, ui: &Ui, node: &Node, width: f32) -> f32 {
        let s = scale(ui);
        let gap = ui.spacing().item_spacing.y;
        match node.kind.as_str() {
            "table" => {
                (control_height(ui) + 6.0 * s) * (node.number("total", 0.0) as f32).clamp(1.0, 6.0)
                    + if node.flag("headers") {
                        control_height(ui) + gap
                    } else {
                        0.0
                    }
                    + 20.0 * s
            }
            "text" if node.flag("multiline") => {
                let lines = node.text("text").lines().count().clamp(4, 12) as f32;
                (lines * ui.text_style_height(&TextStyle::Body)
                    + control_height(ui)
                    + gap
                    + 16.0 * s)
                    .max(144.0 * s)
            }
            "viewport" => 280.0 * s,
            "group" => {
                64.0 * s
                    + node
                        .children
                        .iter()
                        .map(|child| {
                            self.management_content_height(ui, child, width - 32.0 * s) + gap
                        })
                        .sum::<f32>()
            }
            "tabs" => {
                60.0 * s
                    + node
                        .children
                        .iter()
                        .map(|child| self.management_content_height(ui, child, width) + gap)
                        .sum::<f32>()
            }
            "column" | "dialog" => node
                .children
                .iter()
                .map(|child| self.management_content_height(ui, child, width) + gap)
                .sum(),
            _ => estimate_height(ui, node, width),
        }
    }
}
