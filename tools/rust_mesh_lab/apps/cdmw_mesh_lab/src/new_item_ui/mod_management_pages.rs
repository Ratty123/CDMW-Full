//! Shared presentation for management tasks. Controls and events
//! still belong to their Qt pages; this module only lays out and paints them.
use super::*;

#[cfg(test)]
#[path = "mod_management_virtual_tests.rs"]
mod virtual_tests;

#[cfg(test)]
#[path = "mod_management_flat_tests.rs"]
mod flat_tests;

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
                self.management_column(ui, &node.children.iter().collect::<Vec<_>>());
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
                        self.management_row(ui, &cells);
                    });
                }
            }
            "group" if !node.flag("plain") && !node.flag("checkable") => {
                Frame::NONE
                    .fill(ui.visuals().window_fill)
                    .stroke(line(ui))
                    .corner_radius(6)
                    .inner_margin(margin(12.0 * s, 10.0 * s))
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
                        self.management_column(ui, &node.children.iter().collect::<Vec<_>>());
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
                self.management_column(ui, &node.children.iter().collect::<Vec<_>>());
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
                if node.children.len() < 2 {
                    self.management_column(ui, &node.children.iter().collect::<Vec<_>>());
                } else if node.flag("horizontal") && ui.available_width() < 800.0 * s {
                    let height = bounded_height(ui).max(240.0 * s);
                    // A narrow conversion view becomes a closable details drawer.
                    // The toggle stays above the splitter, so it remains reachable.
                    let children: Vec<_> = if node.name == "retrofit_content_splitter" {
                        node.children.iter().skip(1).collect()
                    } else if matches!(node.name.as_str(), "independent_identity_splitter" | "mod_management_health_splitter") {
                        node.children.iter().rev().collect()
                    } else { node.children.iter().collect() };
                    egui::ScrollArea::vertical().id_salt("management-stacked-panes")
                        .auto_shrink([false, false]).max_height(height).show(ui, |ui| {
                            for (index, child) in children.iter().enumerate() {
                                let pane_height = self.management_content_height(ui, child, ui.available_width())
                                    .max(260.0 * s);
                                ui.push_id(index, |ui| {
                                    ui.allocate_ui_with_layout(vec2(ui.available_width(), pane_height),
                                        egui::Layout::top_down(egui::Align::Min), |ui| self.node(ui, child));
                                });
                            }
                        });
                } else {
                    self.split(ui, node);
                }
            }
            "table" => {
                Frame::NONE
                    .fill(ui.visuals().extreme_bg_color)
                    .stroke(line(ui))
                    .corner_radius(4)
                    .inner_margin(margin(8.0 * s, 6.0 * s))
                    .show(ui, |ui| {
                        let empty = node.number("total", 0.0) == 0.0 && !node.text("empty_text").is_empty();
                        let notice = if empty {
                            galley(ui, node.text("empty_text"), 14.0, muted(ui), ui.available_width()).size().y
                                + 12.0 * s + ui.spacing().item_spacing.y
                        } else { 0.0 };
                        let height = (bounded_height(ui) - notice).max(100.0 * s);
                        ui.allocate_ui_with_layout(
                            vec2(ui.available_width(), height),
                            egui::Layout::top_down(egui::Align::Min),
                            |ui| {
                                self.table(ui, node);
                            },
                        );
                        if empty {
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
                        bounded_height(ui).max(text.size().y + 24.0 * s),
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
                let height = bounded_height(ui).max(100.0 * s);
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
                let size = vec2(ui.available_width(), bounded_height(ui).max(160.0 * s));
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

    pub(super) fn management_column(&mut self, ui: &mut Ui, children: &[&Node]) {
        let gap = ui.spacing().item_spacing.y;
        for (index, child) in children.iter().enumerate() {
            ui.push_id(index, |ui| {
                if layout_flexible(child) {
                    // Use the space actually consumed by earlier controls. Their
                    // translated/wrapped height can differ from the estimate.
                    let remaining = &children[index..];
                    let fixed: f32 = remaining.iter().filter(|node| !layout_flexible(node))
                        .map(|node| self.management_content_height(ui, node, ui.available_width())).sum();
                    let extra = (bounded_height(ui) - fixed - gap * remaining.len().saturating_sub(1) as f32).max(0.0);
                    let weight: f32 = remaining.iter().filter(|node| layout_flexible(node))
                        .map(|node| node.stretch.max(1) as f32).sum::<f32>().max(1.0);
                    let height = (extra * child.stretch.max(1) as f32 / weight).max(160.0 * scale(ui));
                    ui.allocate_ui_with_layout(vec2(ui.available_width(), height),
                        egui::Layout::top_down(egui::Align::Min), |ui| self.node(ui, child));
                } else {
                    self.node(ui, child);
                }
            });
        }
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
            "spacer" => 0.0,
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
            child.flag("grow_x") || child.kind == "spacer" || matches!(
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
                    let height = if layout_flexible(child) { bounded_height(ui) }
                        else { self.management_content_height(ui, child, width) };
                    ui.allocate_ui_with_layout(
                        vec2(width, height),
                        egui::Layout::top_down(egui::Align::Min),
                        |ui| {
                            ui.set_width(width);
                            if child.kind == "spacer" {
                                ui.allocate_space(vec2(width, 0.0));
                            } else {
                                self.node(ui, child);
                            }
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
                52.0 * s
                    + node
                        .children
                        .iter()
                        .map(|child| {
                            self.management_content_height(ui, child, width - 24.0 * s) + gap
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
            "row" => self.management_row_height(ui, &node.children.iter().collect::<Vec<_>>(), width),
            "grid" => {
                let mut rows: BTreeMap<i32, Vec<&Node>> = BTreeMap::new();
                for child in &node.children {
                    rows.entry(child.cell.unwrap_or_default()[0]).or_default().push(child);
                }
                rows.values().map(|cells| self.management_row_height(ui, cells, width) + gap).sum()
            }
            "label" if node.text("management_role") == "notice" => {
                galley(ui, node.text("text"), 12.0, muted(ui), width - 24.0 * s).size().y + 18.0 * s
            }
            "label" => if node.text("text").is_empty() { 0.0 } else {
                galley(ui, node.text("text"), 12.0, muted(ui), width).size().y
            },
            _ => estimate_height(ui, node, width),
        }
    }

    fn management_row_height(&self, ui: &Ui, children: &[&Node], width: f32) -> f32 {
        let mut used = 0.0;
        let mut line_height: f32 = 0.0;
        let mut height = 0.0;
        for child in children {
            let wanted = self.management_control_width(ui, child).min(width);
            if used > 0.0 && used + wanted > width {
                height += line_height + ui.spacing().item_spacing.y;
                used = 0.0;
                line_height = 0.0;
            }
            line_height = line_height.max(self.management_content_height(ui, child, wanted.max(1.0)));
            used += wanted + ui.spacing().item_spacing.x;
        }
        height + line_height
    }
}
