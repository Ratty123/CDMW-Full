//! The grouped Mod Management screen, using the original Qt controls as authority.
//! All geometry is in egui points and derives from the host's current font size.

use super::*;
use egui::{CornerRadius, Frame, Margin, Rect, Sense, Stroke, StrokeKind, pos2, vec2};
use std::sync::Arc;

#[cfg(test)]
#[path = "mod_management_tests.rs"]
mod tests;

fn named<'a>(node: &'a Node, name: &str) -> Option<&'a Node> {
    if node.name == name {
        Some(node)
    } else {
        node.children.iter().find_map(|child| named(child, name))
    }
}

fn scale(ui: &Ui) -> f32 {
    TextStyle::Body.resolve(ui.style()).size / 14.0
}

fn muted(ui: &Ui) -> Color32 {
    ui.visuals().weak_text_color()
}

fn line(ui: &Ui) -> Stroke {
    ui.visuals().widgets.noninteractive.bg_stroke
}

fn font(ui: &Ui, points: f32) -> FontId {
    FontId::proportional((points * scale(ui)).max(11.0))
}

fn galley(ui: &Ui, text: &str, points: f32, color: Color32, width: f32) -> Arc<egui::Galley> {
    ui.painter()
        .layout(text.to_owned(), font(ui, points), color, width.max(1.0))
}

fn semantic(ui: &Ui, warning: bool) -> Color32 {
    match (ui.visuals().dark_mode, warning) {
        (true, true) => Color32::from_rgb(229, 183, 117),
        (false, true) => Color32::from_rgb(133, 88, 20),
        (true, false) => Color32::from_rgb(130, 201, 161),
        (false, false) => Color32::from_rgb(41, 120, 74),
    }
}

fn margin(x: f32, y: f32) -> Margin {
    Margin {
        left: x.round() as i8,
        right: x.round() as i8,
        top: y.round() as i8,
        bottom: y.round() as i8,
    }
}

impl PresentationView {
    pub(super) fn mod_management(&mut self, ui: &mut Ui, root: &Node) {
        let Some(pages) = named(root, "mod_management_pages") else {
            self.errors
                .push("Mod Management has no page control".into());
            return;
        };
        let overview = pages
            .children
            .first()
            .filter(|node| node.name == "mod_management_overview");
        if let Some(overview) = overview {
            egui::ScrollArea::vertical()
                .id_salt("mod-management-overview")
                .auto_shrink([false, false])
                .show(ui, |ui| {
                    if let Ok(surface) = Color32::from_hex(root.text("management_surface")) {
                        ui.visuals_mut().window_fill = surface;
                    }
                    self.management_header(ui, root);
                    self.management_tabs(ui, pages);
                    let s = scale(ui);
                    Frame::NONE
                        .inner_margin(margin(22.0 * s, 18.0 * s))
                        .show(ui, |ui| {
                            self.management_overview(ui, overview);
                        });
                    if let Some(bar) = named(root, "mod_management_operation_bar") {
                        self.node(ui, bar);
                    }
                });
        } else {
            self.management_header(ui, root);
            self.management_tabs(ui, pages);
            let bar = named(root, "mod_management_operation_bar");
            let reserved = bar.map_or(0.0, |node| {
                estimate_height(ui, node, ui.available_width()) + 8.0
            });
            let height = (bounded_height(ui) - reserved).max(0.0);
            ui.allocate_ui_with_layout(
                vec2(ui.available_width(), height),
                egui::Layout::top_down(egui::Align::Min),
                |ui| {
                    for page in &pages.children {
                        self.node(ui, page);
                    }
                },
            );
            if let Some(bar) = bar {
                self.node(ui, bar);
            }
        }
    }

    fn management_header(&mut self, ui: &mut Ui, root: &Node) {
        let s = scale(ui);
        Frame::NONE
            .inner_margin(margin(22.0 * s, 16.0 * s))
            .show(ui, |ui| {
                ui.spacing_mut().item_spacing = vec2(10.0 * s, 14.0 * s);
                if let Some(title) = named(root, "SectionTitle") {
                    ui.horizontal(|ui| {
                        let (rect, _) =
                            ui.allocate_exact_size(vec2(18.0, 24.0) * s, Sense::hover());
                        icon(ui, rect.center(), 18.0 * s, "layers", muted(ui));
                        let response = ui.add(
                            egui::Label::new(
                                RichText::new(title.text("text"))
                                    .font(font(ui, 20.0))
                                    .strong(),
                            )
                            .wrap(),
                        );
                        self.record(ui, title, &response);
                    });
                }
                let (Some(label), Some(path), Some(choose)) = (
                    named(root, "mod_management_game_label"),
                    named(root, "mod_management_game_folder"),
                    named(root, "mod_management_choose_game"),
                ) else {
                    return;
                };
                let label_width = galley(ui, label.text("text"), 12.0, muted(ui), f32::INFINITY)
                    .size()
                    .x;
                let choose_width = galley(ui, &choose.label, 12.0, muted(ui), f32::INFINITY)
                    .size()
                    .x
                    + 22.0 * s;
                let stacked = ui.available_width() < label_width + choose_width + 230.0 * s;
                if stacked {
                    let response = ui.add(
                        egui::Label::new(
                            RichText::new(label.text("text"))
                                .font(font(ui, 12.0))
                                .color(muted(ui)),
                        )
                        .wrap(),
                    );
                    self.record(ui, label, &response);
                }
                ui.horizontal(|ui| {
                    if !stacked {
                        let response = ui.add(egui::Label::new(
                            RichText::new(label.text("text"))
                                .font(font(ui, 12.0))
                                .color(muted(ui)),
                        ));
                        self.record(ui, label, &response);
                    }
                    let width = (ui.available_width() - choose_width - 10.0 * s).max(40.0 * s);
                    let (rect, response) =
                        ui.allocate_exact_size(vec2(width, 34.0 * s), Sense::hover());
                    ui.painter().rect(
                        rect,
                        CornerRadius::same(4),
                        ui.visuals().extreme_bg_color,
                        line(ui),
                        StrokeKind::Inside,
                    );
                    icon(
                        ui,
                        pos2(rect.left() + 17.0 * s, rect.center().y),
                        14.0 * s,
                        "folder",
                        muted(ui),
                    );
                    let copy_rect = Rect::from_center_size(
                        pos2(rect.right() - 17.0 * s, rect.center().y),
                        vec2(28.0, 28.0) * s,
                    );
                    let text_rect = Rect::from_min_max(
                        pos2(rect.left() + 32.0 * s, rect.top()),
                        pos2(copy_rect.left() - 4.0 * s, rect.bottom()),
                    );
                    let mut job = egui::text::LayoutJob::simple_singleline(
                        path.text("text").to_owned(),
                        font(ui, 12.0),
                        muted(ui),
                    );
                    job.wrap.max_width = text_rect.width().max(1.0);
                    job.wrap.max_rows = 1;
                    job.wrap.break_anywhere = true;
                    let text = ui.fonts_mut(|fonts| fonts.layout_job(job));
                    ui.painter().galley(
                        pos2(text_rect.left(), text_rect.center().y - text.size().y / 2.0),
                        text,
                        muted(ui),
                    );
                    self.record(ui, path, &response);
                    response.on_hover_text(path.text("text"));
                    let copy = ui.put(copy_rect, egui::Button::new("").frame(false));
                    copy.widget_info(|| {
                        egui::WidgetInfo::labeled(
                            egui::WidgetType::Button,
                            ui.is_enabled(),
                            self.tr("copy", "Copy"),
                        )
                    });
                    icon(ui, copy_rect.center(), 14.0 * s, "copy", muted(ui));
                    if copy.clicked() {
                        self.input(path, "copy", Value::Null);
                    }
                    self.record(ui, path, &copy);
                    copy.on_hover_text(self.tr("copy", "Copy"));
                    self.management_button(ui, choose, choose_width, None, false, false, 12.0);
                });
            });
        ui.separator();
    }

    fn management_tabs(&mut self, ui: &mut Ui, pages: &Node) {
        let s = scale(ui);
        Frame::NONE
            .inner_margin(margin(18.0 * s, 0.0))
            .show(ui, |ui| {
                ui.spacing_mut().item_spacing = vec2(2.0 * s, 0.0);
                ui.horizontal_wrapped(|ui| {
                    for (index, tab) in pages.array("tabs").iter().enumerate() {
                        if tab["visible"] == false {
                            continue;
                        }
                        let selected = pages.number("selected", 0.0) as usize == index;
                        let color = if selected {
                            ui.visuals().hyperlink_color
                        } else {
                            muted(ui)
                        };
                        let button = egui::Button::new(
                            RichText::new(tab["text"].as_str().unwrap_or(""))
                                .font(font(ui, 12.0))
                                .color(color),
                        )
                        .fill(Color32::TRANSPARENT)
                        .stroke(Stroke::NONE)
                        .corner_radius(0)
                        .min_size(vec2(0.0, 38.0 * s))
                        .wrap();
                        let response =
                            ui.add_enabled(pages.enabled && tab["enabled"] != false, button);
                        if selected {
                            ui.painter().hline(
                                response.rect.x_range(),
                                response.rect.bottom(),
                                Stroke::new(2.0 * s, color),
                            );
                        }
                        if response.clicked() {
                            self.input(pages, "tab", json!(index));
                        }
                        self.record(ui, pages, &response);
                    }
                });
            });
        ui.separator();
    }

    fn management_overview(&mut self, ui: &mut Ui, overview: &Node) {
        let s = scale(ui);
        ui.spacing_mut().item_spacing = vec2(12.0 * s, 0.0);
        let available = ui.available_width();
        ui.horizontal_wrapped(|ui| {
            for (index, key) in ["enabled", "disabled", "attention"].iter().enumerate() {
                let value = named(overview, &format!("mod_management_count_{key}"));
                let label = named(overview, &format!("mod_management_count_label_{key}"));
                if let (Some(value), Some(label)) = (value, label) {
                    let number = galley(
                        ui,
                        value.text("text"),
                        14.0,
                        ui.visuals().text_color(),
                        available,
                    );
                    let leading = if index == 0 { 21.0 * s } else { 12.0 * s };
                    let offset = leading + number.size().x + 7.0 * s;
                    let caption =
                        galley(ui, label.text("text"), 12.0, muted(ui), available - offset);
                    let size = vec2(
                        offset + caption.size().x,
                        number.size().y.max(caption.size().y).max(22.0 * s),
                    );
                    let (rect, response) = ui.allocate_exact_size(size, Sense::hover());
                    if index == 0 {
                        icon(
                            ui,
                            pos2(rect.left() + 7.0 * s, rect.center().y),
                            14.0 * s,
                            "check",
                            semantic(ui, false),
                        );
                    } else {
                        ui.painter()
                            .vline(rect.left(), rect.y_range().shrink(3.0 * s), line(ui));
                    }
                    let number_pos = pos2(
                        rect.left() + leading,
                        rect.center().y - number.size().y / 2.0,
                    );
                    let caption_pos = pos2(
                        rect.left() + offset,
                        rect.center().y - caption.size().y / 2.0,
                    );
                    let mut number_response = response.clone();
                    number_response.rect = Rect::from_min_size(number_pos, number.size());
                    let mut caption_response = response;
                    caption_response.rect = Rect::from_min_size(caption_pos, caption.size());
                    ui.painter()
                        .galley(number_pos, number, ui.visuals().text_color());
                    ui.painter().galley(caption_pos, caption, muted(ui));
                    self.record(ui, value, &number_response);
                    self.record(ui, label, &caption_response);
                }
            }
        });
        ui.add_space(22.0 * s);
        let groups: Vec<_> = ["installs", "packages", "maintenance"]
            .iter()
            .filter_map(|key| named(overview, &format!("mod_management_group_{key}")))
            .collect();
        let gap = 12.0 * s;
        // Measure translated captions before choosing columns. Narrow screens and
        // larger host fonts stack whole groups; buttons then wrap without clipping.
        let minimum = groups
            .iter()
            .map(|group| {
                group
                    .children
                    .iter()
                    .flat_map(|layout| &layout.children)
                    .map(|button| {
                        galley(
                            ui,
                            &button.label,
                            13.0,
                            ui.visuals().text_color(),
                            f32::INFINITY,
                        )
                        .size()
                        .x + 94.0 * s
                    })
                    .fold(210.0 * s, f32::max)
            })
            .fold(210.0 * s, f32::max);
        let columns = if ui.available_width() >= minimum * 3.0 + gap * 2.0 {
            3
        } else {
            1
        };
        let width = (ui.available_width() - gap * (columns - 1) as f32) / columns as f32;
        if columns == 3 {
            let height = groups
                .iter()
                .map(|group| self.management_group_height(ui, group, width))
                .fold(0.0, f32::max);
            ui.horizontal_top(|ui| {
                for group in groups {
                    self.management_group(ui, group, width, height);
                }
            });
        } else {
            for (index, group) in groups.iter().enumerate() {
                if index > 0 {
                    ui.add_space(gap);
                }
                let height = self.management_group_height(ui, group, width);
                self.management_group(ui, group, width, height);
            }
        }
        ui.add_space(26.0 * s);
        self.management_archive_toolbar(ui, overview);
        ui.add_space(12.0 * s);
        if let Some(table) = named(overview, "mod_management_archives") {
            self.management_table(ui, table);
        }
        if let Some(status) =
            named(overview, "mod_management_status").filter(|node| !node.text("text").is_empty())
        {
            ui.add_space(10.0 * s);
            let warning = status.flag("management_warning");
            let text = galley(
                ui,
                status.text("text"),
                12.0,
                muted(ui),
                ui.available_width() - 22.0 * s,
            );
            let (rect, response) = ui.allocate_exact_size(
                vec2(ui.available_width(), text.size().y.max(16.0 * s)),
                Sense::hover(),
            );
            icon(
                ui,
                pos2(rect.left() + 7.0 * s, rect.top() + 8.0 * s),
                14.0 * s,
                "info",
                if warning {
                    semantic(ui, true)
                } else {
                    muted(ui)
                },
            );
            ui.painter()
                .galley(rect.min + vec2(22.0 * s, 0.0), text, muted(ui));
            self.record(ui, status, &response);
        }
    }

    fn management_group_height(&self, ui: &Ui, group: &Node, width: f32) -> f32 {
        let s = scale(ui);
        let title = galley(ui, &group.label, 12.0, muted(ui), width - 32.0 * s)
            .size()
            .y;
        let buttons = group
            .children
            .iter()
            .flat_map(|layout| &layout.children)
            .map(|button| {
                (galley(ui, &button.label, 13.0, muted(ui), width - 80.0 * s)
                    .size()
                    .y
                    + 18.0 * s)
                    .max(40.0 * s)
            })
            .sum::<f32>();
        title + buttons + 36.0 * s
    }

    fn management_group(&mut self, ui: &mut Ui, group: &Node, width: f32, height: f32) {
        let s = scale(ui);
        ui.allocate_ui_with_layout(
            vec2(width, height),
            egui::Layout::top_down(egui::Align::Min),
            |ui| {
                let rect = Rect::from_min_size(ui.next_widget_position(), vec2(width, height));
                ui.painter().rect(
                    rect,
                    CornerRadius::same(6),
                    ui.visuals().window_fill,
                    line(ui),
                    StrokeKind::Inside,
                );
                Frame::NONE
                    .inner_margin(margin(10.0 * s, 14.0 * s))
                    .show(ui, |ui| {
                        ui.set_width((width - 20.0 * s).max(1.0));
                        let response = ui.add(
                            egui::Label::new(
                                RichText::new(&group.label)
                                    .font(font(ui, 12.0))
                                    .color(muted(ui)),
                            )
                            .wrap(),
                        );
                        self.record(ui, group, &response);
                        ui.add_space(8.0 * s);
                        for button in group.children.iter().flat_map(|layout| &layout.children) {
                            let kind = button
                                .name
                                .strip_prefix("mod_management_open_")
                                .unwrap_or("");
                            self.management_button(
                                ui,
                                button,
                                width - 20.0 * s,
                                Some(kind),
                                true,
                                kind == "independent",
                                13.0,
                            );
                        }
                    });
            },
        );
    }

    fn management_button(
        &mut self,
        ui: &mut Ui,
        node: &Node,
        width: f32,
        image: Option<&str>,
        arrow: bool,
        primary: bool,
        points: f32,
    ) -> egui::Response {
        let s = scale(ui);
        let left = if image.is_some() { 32.0 * s } else { 10.0 * s };
        let right = if arrow { 28.0 * s } else { 10.0 * s };
        let color = if !node.enabled || !ui.is_enabled() {
            ui.visuals().weak_text_color()
        } else if primary {
            ui.visuals().hyperlink_color
        } else {
            ui.visuals().text_color()
        };
        let text = galley(ui, &node.label, points, color, width - left - right);
        let height = (text.size().y + 18.0 * s).max(if arrow { 40.0 * s } else { 34.0 * s });
        let fill = if primary {
            ui.visuals().selection.bg_fill.gamma_multiply(0.22)
        } else if arrow {
            Color32::TRANSPARENT
        } else {
            ui.visuals().extreme_bg_color
        };
        let stroke = if arrow { Stroke::NONE } else { line(ui) };
        let response = ui.add_enabled(
            node.enabled,
            egui::Button::new("")
                .fill(fill)
                .stroke(stroke)
                .corner_radius(4)
                .min_size(vec2(width, height)),
        );
        response.widget_info(|| {
            egui::WidgetInfo::labeled(
                egui::WidgetType::Button,
                ui.is_enabled() && node.enabled,
                &node.label,
            )
        });
        let rect = response.rect;
        if let Some(image) = image {
            icon(
                ui,
                pos2(rect.left() + 16.0 * s, rect.center().y),
                16.0 * s,
                image,
                if primary { color } else { muted(ui) },
            );
        }
        ui.painter().galley(
            pos2(rect.left() + left, rect.center().y - text.size().y / 2.0),
            text,
            color,
        );
        if arrow {
            icon(
                ui,
                pos2(rect.right() - 14.0 * s, rect.center().y),
                12.0 * s,
                "chevron",
                muted(ui),
            );
        }
        if response.clicked() {
            self.input(node, "activate", Value::Null);
        }
        self.record(ui, node, &response);
        response
    }

    fn management_archive_toolbar(&mut self, ui: &mut Ui, overview: &Node) {
        let (Some(title), Some(check), Some(refresh)) = (
            named(overview, "mod_management_archives_title"),
            named(overview, "mod_management_show_game"),
            named(overview, "mod_management_refresh"),
        ) else {
            return;
        };
        let s = scale(ui);
        let title_width = galley(ui, title.text("text"), 14.0, muted(ui), f32::INFINITY)
            .size()
            .x;
        let check_width = galley(ui, &check.label, 12.0, muted(ui), f32::INFINITY)
            .size()
            .x
            + 24.0 * s;
        let refresh_width = galley(ui, &refresh.label, 12.0, muted(ui), f32::INFINITY)
            .size()
            .x
            + 44.0 * s;
        let wide = ui.available_width() >= title_width + check_width + refresh_width + 38.0 * s;
        let controls = |view: &mut Self, ui: &mut Ui| {
            let mut checked = check.flag("checked");
            let response = ui.add_enabled(
                check.enabled,
                egui::Checkbox::new(
                    &mut checked,
                    RichText::new(&check.label)
                        .font(font(ui, 12.0))
                        .color(muted(ui)),
                ),
            );
            if response.changed() {
                view.input(check, "toggle", json!(checked));
            }
            view.record(ui, check, &response);
            view.management_button(
                ui,
                refresh,
                refresh_width.min(ui.max_rect().width()),
                Some("refresh"),
                false,
                false,
                12.0,
            );
        };
        ui.horizontal(|ui| {
            let response = ui.add(
                egui::Label::new(
                    RichText::new(title.text("text"))
                        .font(font(ui, 14.0))
                        .strong(),
                )
                .wrap(),
            );
            self.record(ui, title, &response);
            if wide {
                ui.add_space(
                    (ui.available_width() - check_width - refresh_width - 24.0 * s).max(0.0),
                );
                controls(self, ui);
            }
        });
        if !wide {
            ui.add_space(8.0 * s);
            ui.horizontal_wrapped(|ui| controls(self, ui));
        }
    }

    fn management_table(&mut self, ui: &mut Ui, table: &Node) {
        let s = scale(ui);
        let width = ui.available_width();
        let widths = [width * 0.24, width * 0.34, width * 0.42];
        let pad = (14.0 * s).min(width * 0.025);
        let columns = table.array("columns");
        let rows = table.array("rows");
        let header: Vec<_> = (0..3)
            .map(|i| {
                galley(
                    ui,
                    columns
                        .get(i)
                        .and_then(|v| v["text"].as_str())
                        .unwrap_or(""),
                    12.0,
                    muted(ui),
                    widths[i] - pad * 2.0,
                )
            })
            .collect();
        let header_height = header.iter().map(|g| g.size().y).fold(0.0, f32::max) + 20.0 * s;
        let cells: Vec<_> = rows
            .iter()
            .map(|row| {
                (0..3)
                    .map(|col| {
                        let text = row["cells"][col]["text"].as_str().unwrap_or("");
                        let inset = if col == 2 { 22.0 * s } else { 0.0 };
                        let color = if col == 1 && text != "CDMW" {
                            muted(ui)
                        } else {
                            ui.visuals().text_color()
                        };
                        galley(ui, text, 13.0, color, widths[col] - pad * 2.0 - inset)
                    })
                    .collect::<Vec<_>>()
            })
            .collect();
        let heights: Vec<_> = cells
            .iter()
            .map(|row| {
                (row.iter().map(|g| g.size().y).fold(0.0, f32::max) + 18.0 * s).max(46.0 * s)
            })
            .collect();
        let height = header_height + heights.iter().sum::<f32>();
        let (rect, response) = ui.allocate_exact_size(vec2(width, height), Sense::hover());
        let painter = ui.painter();
        painter.rect(
            rect,
            CornerRadius::same(5),
            ui.visuals().window_fill,
            line(ui),
            StrokeKind::Inside,
        );
        let mut x = rect.left();
        for (col, text) in header.into_iter().enumerate() {
            painter.galley(
                pos2(x + pad, rect.top() + (header_height - text.size().y) / 2.0),
                text,
                muted(ui),
            );
            x += widths[col];
        }
        let mut y = rect.top() + header_height;
        for (row_index, (cells, height)) in cells.into_iter().zip(heights).enumerate() {
            painter.hline(rect.x_range(), y, line(ui));
            let name = rows[row_index]["cells"][0]["text"].as_str().unwrap_or("");
            let status = table.props["folder_states"][name]
                .as_str()
                .unwrap_or("optional");
            let mut x = rect.left();
            for (col, text) in cells.into_iter().enumerate() {
                let inset = if col == 2 { 22.0 * s } else { 0.0 };
                if col == 2 {
                    icon(
                        ui,
                        pos2(x + pad + 7.0 * s, y + height / 2.0),
                        14.0 * s,
                        match status {
                            "found" => "check",
                            "missing" => "warning",
                            _ => "info",
                        },
                        match status {
                            "found" => semantic(ui, false),
                            "missing" => semantic(ui, true),
                            _ => muted(ui),
                        },
                    );
                }
                painter.galley(
                    pos2(x + pad + inset, y + (height - text.size().y) / 2.0),
                    text,
                    ui.visuals().text_color(),
                );
                x += widths[col];
            }
            y += height;
        }
        self.record(ui, table, &response);
        self.paging(ui, table, &table.props);
    }
}

// Small line icons stay sharp at the current monitor's pixels-per-point.
fn icon(ui: &Ui, center: egui::Pos2, size: f32, kind: &str, color: Color32) {
    let p = |x, y| center + vec2(x - 12.0, y - 12.0) * (size / 24.0);
    let stroke = Stroke::new((size / 12.0).max(1.0), color);
    let path = |points: &[(f32, f32)]| {
        ui.painter().add(egui::Shape::line(
            points.iter().map(|&(x, y)| p(x, y)).collect(),
            stroke,
        ));
    };
    match kind {
        "independent" | "repackage" | "installed" => {
            path(&[
                (12., 3.),
                (21., 8.),
                (21., 17.),
                (12., 22.),
                (3., 17.),
                (3., 8.),
                (12., 3.),
            ]);
            path(&[(3., 8.), (12., 13.), (21., 8.)]);
            path(&[(12., 13.), (12., 22.)]);
            if kind == "independent" {
                path(&[(18., 2.), (18., 8.)]);
                path(&[(15., 5.), (21., 5.)]);
            }
            if kind == "installed" {
                path(&[(7., 5.), (16., 10.), (16., 19.)]);
            }
        }
        "merge" => {
            path(&[(4., 4.), (4., 9.), (11., 12.), (20., 12.)]);
            path(&[(4., 20.), (4., 15.), (11., 12.)]);
            path(&[(16., 8.), (20., 12.), (16., 16.)]);
        }
        "updates" => {
            path(&[(8., 3.), (3., 3.), (3., 8.)]);
            path(&[(16., 3.), (21., 3.), (21., 8.)]);
            path(&[(3., 16.), (3., 21.), (8., 21.)]);
            path(&[(16., 21.), (21., 21.), (21., 16.)]);
            path(&[(5., 12.), (19., 12.)]);
        }
        "recovery" | "refresh" => {
            let points: Vec<_> = (0..=20)
                .map(|i| {
                    let a = -2.6 + i as f32 * 5.35 / 20.0;
                    (12. + a.cos() * 9., 12. + a.sin() * 9.)
                })
                .collect();
            path(&points);
            path(&[(3., 3.), (3., 9.), (9., 9.)]);
            if kind == "recovery" {
                path(&[(12., 7.), (12., 12.), (16., 14.)]);
            }
        }
        "chevron" => path(&[(9., 5.), (16., 12.), (9., 19.)]),
        "layers" => {
            path(&[(3., 8.), (12., 3.), (21., 8.), (12., 13.), (3., 8.)]);
            path(&[(3., 13.), (12., 18.), (21., 13.)]);
        }
        "folder" => path(&[
            (3., 5.),
            (9., 5.),
            (12., 8.),
            (21., 8.),
            (21., 20.),
            (3., 20.),
            (3., 5.),
        ]),
        "copy" => {
            path(&[(8., 8.), (21., 8.), (21., 21.), (8., 21.), (8., 8.)]);
            path(&[(16., 5.), (16., 3.), (3., 3.), (3., 16.), (5., 16.)]);
        }
        "warning" => {
            path(&[(12., 3.), (23., 21.), (1., 21.), (12., 3.)]);
            path(&[(12., 9.), (12., 14.)]);
            ui.painter().circle_filled(p(12., 18.), size / 22., color);
        }
        "check" | "info" => {
            ui.painter().circle_stroke(center, size * 0.44, stroke);
            if kind == "check" {
                path(&[(6., 12.), (10., 16.), (18., 8.)]);
            } else {
                path(&[(12., 11.), (12., 17.)]);
                ui.painter().circle_filled(p(12., 7.), size / 22., color);
            }
        }
        _ => {}
    }
}
