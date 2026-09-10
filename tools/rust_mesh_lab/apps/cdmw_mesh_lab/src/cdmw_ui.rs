#![forbid(unsafe_code)]

use super::*;
use egui::{Button, ComboBox, ScrollArea, Spinner};

const CDMW_VIEW_MODES: [(ViewMode, &str); 7] = [
    (ViewMode::TexturedSolid, "Solid (Textured)"),
    (ViewMode::Solid, "Faces (No Textures)"),
    (ViewMode::SolidWire, "Faces + Wire"),
    (ViewMode::Wireframe, "Wire"),
    (ViewMode::Vertices, "Vertices"),
    (ViewMode::WireVertices, "Wire + Vertices"),
    (ViewMode::XRay, "X-Ray"),
];

const CDMW_WIDE_CHROME_MIN_WIDTH: f32 = 1_280.0;
const REFIT_BODY_COLOUR: Color32 = Color32::from_rgb(100, 190, 245);
const REFIT_ARMOR_COLOUR: Color32 = Color32::from_rgb(240, 190, 95);
const REFIT_READY_COLOUR: Color32 = Color32::from_rgb(110, 210, 160);

fn cdmw_section<R>(
    ui: &mut egui::Ui,
    id: &str,
    title: &str,
    open: Option<bool>,
    body: impl FnOnce(&mut egui::Ui) -> R,
) -> egui::CollapsingResponse<R> {
    // CollapsingHeader creates a child UI; give that child a stable parent even
    // when preceding controls appear, disappear, or change their contents.
    ui.push_id(id, |ui| {
        egui::CollapsingHeader::new(title)
            .id_salt(id)
            .default_open(false)
            .open(open)
            .show(ui, body)
    })
    .inner
}

fn cdmw_chrome_row_height(context: &egui::Context) -> f32 {
    let style = context.style_of(context.theme());
    style.spacing.interact_size.y + style.spacing.item_spacing.y * 2.0 + 2.0
}

fn cdmw_chrome_fits_one_row(context: &egui::Context, available_width: f32) -> bool {
    let style = context.style_of(context.theme());
    let control_scale = (style.spacing.interact_size.y / 24.0).max(1.0);
    available_width >= CDMW_WIDE_CHROME_MIN_WIDTH * control_scale
}

fn cdmw_view_mode_label(mode: ViewMode) -> &'static str {
    if mode == ViewMode::UvChecker {
        return "UV Checker";
    }
    CDMW_VIEW_MODES
        .iter()
        .find_map(|(candidate, label)| (*candidate == mode).then_some(*label))
        .unwrap_or(ViewMode::TexturedSolid.label())
}

fn cdmw_screen_grid_id() -> egui::Id {
    egui::Id::new("cdmw_screen_grid_visible")
}

fn cdmw_screen_grid_visible(context: &egui::Context) -> bool {
    context.data_mut(|data| {
        data.get_temp::<bool>(cdmw_screen_grid_id())
            .unwrap_or(false)
    })
}

fn set_cdmw_screen_grid_visible(context: &egui::Context, visible: bool) {
    context.data_mut(|data| data.insert_temp(cdmw_screen_grid_id(), visible));
}

fn cdmw_theme_colour(theme: &Value, key: &str, fallback: Color32) -> Color32 {
    let Some(value) = theme
        .get("palette")
        .and_then(|palette| palette.get(key))
        .and_then(Value::as_str)
        .map(str::trim)
    else {
        return fallback;
    };
    let hex = value.strip_prefix('#').unwrap_or(value);
    if hex.len() != 6 {
        return fallback;
    }
    let Ok(red) = u8::from_str_radix(&hex[0..2], 16) else {
        return fallback;
    };
    let Ok(green) = u8::from_str_radix(&hex[2..4], 16) else {
        return fallback;
    };
    let Ok(blue) = u8::from_str_radix(&hex[4..6], 16) else {
        return fallback;
    };
    Color32::from_rgb(red, green, blue)
}

fn cdmw_theme_is_dark(theme: &Value, window: Color32) -> bool {
    match theme.get("variant").and_then(Value::as_str) {
        Some(value) if value.eq_ignore_ascii_case("light") => false,
        Some(value) if value.eq_ignore_ascii_case("dark") => true,
        _ => {
            let [red, green, blue, _] = window.to_array();
            (u32::from(red) * 299 + u32::from(green) * 587 + u32::from(blue) * 114) < 128_000
        }
    }
}

impl LabApplication {
    pub(super) fn apply_cdmw_theme(&self) {
        let Some(bridge) = &self.cdmw_bridge else {
            return;
        };
        self.apply_cdmw_theme_payload(&bridge.manifest().theme);
    }

    pub(super) fn apply_cdmw_theme_payload(&self, theme: &Value) {
        let density = theme
            .get("density")
            .and_then(Value::as_str)
            .unwrap_or("compact");
        // Qt point sizes are typographic points; egui sizes are logical pixels.
        // At the Windows 96-DPI baseline this 4/3 conversion makes the embedded
        // text match the surrounding PySide controls instead of appearing tiny.
        let font_size = (theme
            .get("font_point_size")
            .and_then(Value::as_f64)
            .unwrap_or(10.0)
            .clamp(8.0, 18.0) as f32)
            * (96.0 / 72.0);
        let data_font_size = (theme
            .get("data_font_point_size")
            .and_then(Value::as_f64)
            .unwrap_or(f64::from(font_size) * 72.0 / 96.0)
            .clamp(8.0, 18.0) as f32)
            * (96.0 / 72.0);
        let window = cdmw_theme_colour(theme, "window", Color32::from_rgb(30, 30, 30));
        let dark = cdmw_theme_is_dark(theme, window);
        let active_theme = if dark {
            egui::Theme::Dark
        } else {
            egui::Theme::Light
        };
        let mut style = (*self.egui_context.style_of(active_theme)).clone();
        let (item_spacing, button_padding, interaction_height): (egui::Vec2, egui::Vec2, f32) =
            if density.eq_ignore_ascii_case("comfortable") {
                (egui::vec2(10.0, 8.0), egui::vec2(12.0, 7.0), 34.0)
            } else if density.eq_ignore_ascii_case("normal") {
                (egui::vec2(8.0, 6.0), egui::vec2(10.0, 5.0), 29.0)
            } else {
                (egui::vec2(6.0, 4.0), egui::vec2(8.0, 4.0), 25.0)
            };
        style.spacing.item_spacing = item_spacing;
        style.spacing.button_padding = button_padding;
        style.spacing.interact_size.y = interaction_height.max(font_size + 8.0);
        for (text_style, size, family) in [
            (
                egui::TextStyle::Small,
                (font_size - 1.4).max(9.0),
                egui::FontFamily::Proportional,
            ),
            (
                egui::TextStyle::Body,
                font_size,
                egui::FontFamily::Proportional,
            ),
            (
                egui::TextStyle::Button,
                font_size,
                egui::FontFamily::Proportional,
            ),
            (
                egui::TextStyle::Heading,
                font_size + 3.0,
                egui::FontFamily::Proportional,
            ),
            (
                egui::TextStyle::Monospace,
                data_font_size,
                egui::FontFamily::Monospace,
            ),
        ] {
            style
                .text_styles
                .insert(text_style, egui::FontId::new(size, family));
        }

        let surface = cdmw_theme_colour(theme, "surface", style.visuals.window_fill);
        let surface_alt = cdmw_theme_colour(theme, "surface_alt", style.visuals.faint_bg_color);
        let field = cdmw_theme_colour(theme, "field", style.visuals.extreme_bg_color);
        let field_alt = cdmw_theme_colour(theme, "field_alt", style.visuals.code_bg_color);
        let border = cdmw_theme_colour(theme, "border", style.visuals.window_stroke.color);
        let border_strong = cdmw_theme_colour(theme, "border_strong", border);
        let text = cdmw_theme_colour(theme, "text", style.visuals.text_color());
        let text_muted = cdmw_theme_colour(theme, "text_muted", text.gamma_multiply(0.72));
        let text_strong = cdmw_theme_colour(theme, "text_strong", text);
        let button = cdmw_theme_colour(theme, "button", surface_alt);
        let button_hover = cdmw_theme_colour(theme, "button_hover", button);
        let button_pressed = cdmw_theme_colour(theme, "button_pressed", surface);
        let button_border = cdmw_theme_colour(theme, "button_border", border_strong);
        let accent = cdmw_theme_colour(theme, "accent", Color32::from_rgb(53, 150, 215));
        let accent_soft = cdmw_theme_colour(theme, "accent_soft", accent.gamma_multiply(0.55));
        let mut visuals = if dark {
            egui::Visuals::dark()
        } else {
            egui::Visuals::light()
        };
        visuals.panel_fill = window;
        visuals.window_fill = surface;
        visuals.window_stroke = Stroke::new(1.0, border);
        visuals.faint_bg_color = surface_alt;
        visuals.extreme_bg_color = field;
        visuals.text_edit_bg_color = Some(field);
        visuals.code_bg_color = field_alt;
        visuals.weak_text_color = Some(text_muted);
        visuals.hyperlink_color = accent;
        visuals.warn_fg_color = cdmw_theme_colour(theme, "warning_text", visuals.warn_fg_color);
        visuals.error_fg_color = cdmw_theme_colour(theme, "error", visuals.error_fg_color);
        visuals.selection.bg_fill = accent_soft;
        // Selected controls use the muted accent surface, not the bright accent.
        visuals.selection.stroke = Stroke::new(1.0, text_strong);
        visuals.widgets.noninteractive.bg_fill = surface;
        visuals.widgets.noninteractive.weak_bg_fill = surface;
        visuals.widgets.noninteractive.bg_stroke = Stroke::new(1.0, border);
        visuals.widgets.noninteractive.fg_stroke = Stroke::new(1.0, text);
        visuals.widgets.inactive.bg_fill = button;
        visuals.widgets.inactive.weak_bg_fill = button;
        visuals.widgets.inactive.bg_stroke = Stroke::new(1.0, button_border);
        visuals.widgets.inactive.fg_stroke = Stroke::new(1.0, text_strong);
        visuals.widgets.hovered.bg_fill = button_hover;
        visuals.widgets.hovered.weak_bg_fill = button_hover;
        visuals.widgets.hovered.bg_stroke = Stroke::new(1.0, border_strong);
        visuals.widgets.hovered.fg_stroke = Stroke::new(1.0, text_strong);
        visuals.widgets.active.bg_fill = button_pressed;
        visuals.widgets.active.weak_bg_fill = button_pressed;
        visuals.widgets.active.bg_stroke = Stroke::new(1.0, accent);
        visuals.widgets.active.fg_stroke = Stroke::new(1.0, text_strong);
        visuals.widgets.open = visuals.widgets.hovered;
        // Fill, border, and interaction distinguish disabled controls without
        // fading their labels below readable contrast in the darker palettes.
        visuals.disabled_alpha = 0.9;
        style.visuals = visuals;
        self.egui_context.set_style_of(active_theme, style);
        // An explicit preference is required: egui-winit also reports the OS
        // theme, which previously replaced CDMW's dark style with a white UI.
        self.egui_context.set_theme(active_theme);
    }

    pub(super) fn draw_cdmw_ui(&mut self, root_ui: &mut egui::Ui) -> Vec<UiAction> {
        let mut actions = Vec::new();
        self.draw_cdmw_session_bar(root_ui, &mut actions);
        self.draw_cdmw_bottom_bar(root_ui, &mut actions);
        self.draw_cdmw_left_rail(root_ui, &mut actions);
        self.draw_cdmw_right_panels(root_ui, &mut actions);
        self.draw_cdmw_viewport(root_ui);
        actions
    }

    fn cdmw_show_busy_controls(&self) -> bool {
        // Selection is already shown locally. Do not flash the surrounding UI
        // while the host records it; cdmw_busy still guards edits until the reply.
        self.cdmw_pending_request
            .as_ref()
            .is_some_and(|pending| pending.origin != Some(CdmwRequestOrigin::Selection))
    }

    fn draw_cdmw_session_bar(&mut self, root_ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let busy = self.cdmw_show_busy_controls();
        let undo_count = state_u64(&self.cdmw_state, "undo_count");
        let redo_count = state_u64(&self.cdmw_state, "redo_count");
        let authoring = state_bool(&self.cdmw_state, "authoring_enabled");
        let policy_reason = state_str(&self.cdmw_state, "output_policy_reason").unwrap_or("");
        let cursor = state_u64(&self.cdmw_state, "history_cursor");
        let selected = self.selected_counts();
        let wide = cdmw_chrome_fits_one_row(&self.egui_context, root_ui.available_width());
        let row_height = cdmw_chrome_row_height(&self.egui_context);
        egui::Panel::top("cdmw_session_bar")
            .exact_size(if wide { row_height } else { row_height * 2.0 })
            .show(root_ui, |ui| {
                ui.horizontal(|ui| {
                    ui.label(RichText::new("Mesh Editor").heading().strong());
                    if busy {
                        ui.add(Spinner::new());
                    }
                    if wide {
                        ui.separator();
                        self.draw_cdmw_selection_history_controls(
                            ui, actions, busy, authoring, selected, cursor, undo_count, redo_count,
                        );
                    }
                    let available = ui.available_width().max(0.0);
                    ui.allocate_ui_with_layout(
                        egui::vec2(available, ui.spacing().interact_size.y),
                        egui::Layout::right_to_left(egui::Align::Center),
                        |ui| {
                            self.draw_cdmw_finish_control(
                                ui,
                                actions,
                                busy,
                                authoring,
                                policy_reason,
                            );
                        },
                    );
                });
                if !wide {
                    ui.horizontal_wrapped(|ui| {
                        self.draw_cdmw_selection_history_controls(
                            ui, actions, busy, authoring, selected, cursor, undo_count, redo_count,
                        );
                    });
                }
            });
    }

    #[allow(clippy::too_many_arguments)]
    fn draw_cdmw_selection_history_controls(
        &self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        busy: bool,
        authoring: bool,
        selected: SelectedCounts,
        cursor: u64,
        undo_count: u64,
        redo_count: u64,
    ) {
        ui.label(RichText::new("Selection").strong());
        if ui
            .add_enabled(!busy, Button::new("Clear Selection"))
            .on_disabled_hover_text("Wait for the current shadow operation")
            .clicked()
        {
            actions.push(UiAction::ClearSelection);
        }
        let select_all = match self.selection_domain {
            SelectionDomain::Vertex => UiAction::SelectAllVertices,
            SelectionDomain::Edge => UiAction::SelectAllEdges,
            SelectionDomain::Face => UiAction::SelectAllFaces,
        };
        if ui
            .add_enabled(!busy, Button::new("Select All"))
            .on_disabled_hover_text("Wait for the current shadow operation")
            .clicked()
        {
            actions.push(select_all);
        }
        if ui
            .add_enabled(!busy && selected.total() > 0, Button::new("Invert"))
            .on_disabled_hover_text(if busy {
                "Wait for the current shadow operation"
            } else {
                "Select an element first"
            })
            .clicked()
        {
            actions.push(UiAction::InvertSelection(self.selection_domain));
        }
        ui.separator();
        ui.label(RichText::new("History").strong());
        if ui
            .add_enabled(!busy && authoring && undo_count > 0, Button::new("Undo"))
            .on_disabled_hover_text(if busy {
                "Wait for the current shadow operation"
            } else {
                "No Mesh Editor action to undo"
            })
            .clicked()
        {
            actions.push(UiAction::Undo);
        }
        if ui
            .add_enabled(!busy && authoring && redo_count > 0, Button::new("Redo"))
            .on_disabled_hover_text(if busy {
                "Wait for the current shadow operation"
            } else {
                "No Mesh Editor action to redo"
            })
            .clicked()
        {
            actions.push(UiAction::Redo);
        }
        ui.label(format!(
            "Step {cursor} · {undo_count} undo · {redo_count} redo"
        ));
    }

    fn draw_cdmw_finish_control(
        &self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        busy: bool,
        authoring: bool,
        policy_reason: &str,
    ) {
        if ui
            .add_enabled(
                !busy && authoring && self.cdmw_host_connected,
                Button::new("Finish Edit Mesh"),
            )
            .on_disabled_hover_text(if busy {
                "Finish waits until the pending shadow transaction completes"
            } else if !authoring {
                policy_reason
            } else {
                "Waiting for the CDMW authoring host"
            })
            .clicked()
        {
            actions.push(UiAction::FinishCdmw);
        }
    }

    fn draw_cdmw_status_contents(&self, ui: &mut egui::Ui) {
        let selected = self.selected_counts();
        let status_label = if self.selection_gesture.is_some() {
            "Live"
        } else if selected.total() > 0 {
            "Selected"
        } else {
            "Ready"
        };
        let colour = match status_label {
            "Selected" => Color32::from_rgb(96, 210, 135),
            "Live" => Color32::from_rgb(245, 190, 75),
            _ => Color32::from_gray(170),
        };
        ui.colored_label(colour, RichText::new(status_label).strong());
        ui.separator();
        ui.label(format!(
            "{} vertices · {} edges · {} faces",
            selected.vertices, selected.edges, selected.faces
        ));
        ui.separator();
        if self.status.to_ascii_lowercase().contains("failed")
            || self.status.to_ascii_lowercase().contains("rejected")
            || self.status.to_ascii_lowercase().contains("error")
        {
            ui.colored_label(Color32::from_rgb(245, 105, 105), &self.status);
        } else {
            ui.label(&self.status);
        }
    }

    fn draw_cdmw_bottom_bar(&mut self, root_ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let wide = cdmw_chrome_fits_one_row(&self.egui_context, root_ui.available_width());
        let row_height = cdmw_chrome_row_height(&self.egui_context);
        egui::Panel::bottom("cdmw_bottom_bar")
            .exact_size(if wide {
                row_height
            } else {
                row_height * 2.0
            })
            .show(root_ui, |ui| {
                ui.horizontal(|ui| {
                    ui.label(RichText::new("Navigation").strong());
                    if ui
                        .add(Button::new("Orbit").selected(self.cdmw_orbit_mode))
                        .on_hover_text(
                            "Neutral navigation mode; edit gestures are inactive. RMB orbits, MMB pans, and the wheel zooms.",
                        )
                        .clicked()
                    {
                        actions.push(UiAction::OrbitMode);
                    }
                    if ui.button("Fit").clicked() {
                        actions.push(UiAction::FrameAll);
                    }
                    if ui.button("Frame Selected").clicked() {
                        actions.push(UiAction::FrameSelected);
                    }
                    ui.separator();
                    ui.label(RichText::new("Views").strong());
                    for (label, view) in [
                        ("Front", StandardView::Front),
                        ("Back", StandardView::Back),
                        ("Top", StandardView::Top),
                        ("Left", StandardView::Left),
                        ("Right", StandardView::Right),
                        ("Bottom", StandardView::Bottom),
                    ] {
                        if ui.small_button(label).clicked() {
                            actions.push(UiAction::StandardView(view));
                        }
                    }
                    ui.separator();
                    if ui.small_button("Yaw -15°").clicked() {
                        actions.push(UiAction::OrbitYaw(-15.0));
                    }
                    if ui.small_button("Yaw +15°").clicked() {
                        actions.push(UiAction::OrbitYaw(15.0));
                    }
                    if wide {
                        ui.separator();
                        self.draw_cdmw_status_contents(ui);
                    }
                });
                if !wide {
                    ui.horizontal(|ui| self.draw_cdmw_status_contents(ui));
                }
            });
    }

    fn draw_cdmw_left_rail(&mut self, root_ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let busy = self.cdmw_show_busy_controls();
        let authoring = state_bool(&self.cdmw_state, "authoring_enabled");
        let policy_reason = state_str(&self.cdmw_state, "output_policy_reason")
            .unwrap_or("Authoring is unavailable under the current output policy")
            .to_owned();
        egui::Panel::left("cdmw_tool_rail")
            .default_size(286.0)
            .min_size(250.0)
            .max_size(360.0)
            .resizable(true)
            .show(root_ui, |ui| {
                ScrollArea::vertical()
                    .id_salt("cdmw-tool-scroll")
                    .show(ui, |ui| {
                        ui.add_enabled_ui(!busy, |ui| {
                            ui.push_id("cdmw-viewport-root", |ui| {
                                egui::CollapsingHeader::new("Viewport")
                                    .id_salt("cdmw-viewport")
                                    .default_open(false)
                                    .show_unindented(ui, |ui| {
                                        self.draw_cdmw_viewport_section(ui, actions)
                                    });
                            });
                        });
                        ui.separator();
                        ui.label(RichText::new("Tools").heading().strong());
                        self.draw_cdmw_tool_group(
                            ui,
                            actions,
                            "Selection",
                            &[(CdmwRailPage::Select, "Select", Some(ViewportTool::Select))],
                            1,
                            busy,
                            authoring,
                            &policy_reason,
                        );
                        self.draw_cdmw_tool_group(
                            ui,
                            actions,
                            "Transform",
                            &[
                                (CdmwRailPage::Move, "Move", Some(ViewportTool::Move)),
                                (CdmwRailPage::Rotate, "Rotate", Some(ViewportTool::Rotate)),
                                (CdmwRailPage::Scale, "Scale", Some(ViewportTool::Scale)),
                            ],
                            3,
                            busy,
                            authoring,
                            &policy_reason,
                        );
                        self.draw_cdmw_tool_group(
                            ui,
                            actions,
                            "Sculpt",
                            &[
                                (CdmwRailPage::Grab, "Grab", Some(ViewportTool::Grab)),
                                (CdmwRailPage::Smooth, "Smooth", Some(ViewportTool::Smooth)),
                                (
                                    CdmwRailPage::Inflate,
                                    "Inflate",
                                    Some(ViewportTool::Inflate),
                                ),
                                (CdmwRailPage::Pinch, "Pinch", Some(ViewportTool::Pinch)),
                            ],
                            2,
                            busy,
                            authoring,
                            &policy_reason,
                        );
                        self.draw_cdmw_tool_group(
                            ui,
                            actions,
                            "Mesh Data",
                            &[
                                (CdmwRailPage::Topology, "Topology", None),
                                (CdmwRailPage::Cleanup, "Cleanup", None),
                                (CdmwRailPage::Normals, "Normals & Tangents", None),
                                (CdmwRailPage::Uv, "UV", None),
                            ],
                            2,
                            busy,
                            authoring,
                            &policy_reason,
                        );
                        ui.add_space(3.0);
                        let active = self.cdmw_rail_page == Some(CdmwRailPage::MorphRefit);
                        if ui
                            .add_enabled(
                                !busy && authoring,
                                Button::new(RichText::new("Morph & Refit").strong())
                                    .selected(active)
                                    .min_size(egui::vec2(ui.available_width(), 30.0)),
                            )
                            .on_disabled_hover_text(&policy_reason)
                            .clicked()
                        {
                            self.cancel_active_gesture("Morph & Refit toggled");
                            self.cdmw_rail_page = if active {
                                None
                            } else {
                                Some(CdmwRailPage::MorphRefit)
                            };
                            self.cdmw_orbit_mode = true;
                        }
                        if self.cdmw_rail_page == Some(CdmwRailPage::MorphRefit) {
                            ui.push_id("cdmw-morph-root", |ui| {
                                egui::Frame::group(ui.style())
                                    .stroke(egui::Stroke::new(1.0, ui.visuals().selection.bg_fill))
                                    .fill(ui.visuals().faint_bg_color)
                                    .inner_margin(10.0)
                                    .show(ui, |ui| {
                                        ui.add_enabled_ui(!busy && authoring, |ui| {
                                            self.draw_cdmw_morph_page(ui, actions)
                                        });
                                    });
                            });
                        }
                    });
            });
    }

    #[allow(clippy::too_many_arguments)]
    fn draw_cdmw_tool_group(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        heading: &str,
        tools: &[(CdmwRailPage, &str, Option<ViewportTool>)],
        columns: usize,
        busy: bool,
        authoring: bool,
        policy_reason: &str,
    ) {
        ui.add_space(3.0);
        let active = tools
            .iter()
            .any(|(page, _, _)| self.cdmw_rail_page == Some(*page));
        let group = ui
            .push_id(("cdmw-tool-group-root", heading), |ui| {
                egui::CollapsingHeader::new(heading)
                    .id_salt(("cdmw-tool-group", heading))
                    .default_open(false)
                    .open(active.then_some(true))
                    .show_unindented(ui, |ui| {
                        let columns = columns.max(1);
                        for row in tools.chunks(columns) {
                            let gap = ui.spacing().item_spacing.x;
                            let button_width = (ui.available_width()
                                - gap * (columns.saturating_sub(1) as f32))
                                / columns as f32;
                            ui.horizontal(|ui| {
                                for &(page, label, tool) in row {
                                    let active = self.cdmw_rail_page == Some(page);
                                    let requires_authoring = !matches!(
                                        page,
                                        CdmwRailPage::Select | CdmwRailPage::RigWeights
                                    );
                                    let enabled = !busy && (!requires_authoring || authoring);
                                    if ui
                                        .add_enabled(
                                            enabled,
                                            Button::new(label).selected(active).min_size(
                                                egui::vec2(
                                                    button_width.max(1.0),
                                                    ui.spacing().interact_size.y,
                                                ),
                                            ),
                                        )
                                        .on_disabled_hover_text(if busy {
                                            "Wait for the current shadow operation"
                                        } else {
                                            policy_reason
                                        })
                                        .clicked()
                                    {
                                        if active {
                                            self.cdmw_rail_page = None;
                                            self.cancel_active_gesture("Tool closed");
                                            self.cdmw_orbit_mode = true;
                                            continue;
                                        }
                                        self.cdmw_rail_page = Some(page);
                                        if page == CdmwRailPage::RigWeights {
                                            self.cancel_active_gesture(
                                                "Rig inspection cancelled the previous gesture",
                                            );
                                            self.viewport_tool = ViewportTool::Select;
                                            self.selection_domain = SelectionDomain::Vertex;
                                            self.cdmw_orbit_mode = false;
                                        }
                                        if let Some(tool) = tool {
                                            if self.viewport_tool != tool {
                                                self.cancel_active_gesture(
                                                    "Tool change cancelled the previous gesture",
                                                );
                                            }
                                            self.viewport_tool = tool;
                                            self.cdmw_orbit_mode = false;
                                        }
                                    }
                                }
                            });
                            if let Some(active_page) = row
                                .iter()
                                .map(|(page, _, _)| *page)
                                .find(|page| self.cdmw_rail_page == Some(*page))
                            {
                                let enabled = !busy
                                    && (matches!(
                                        active_page,
                                        CdmwRailPage::Select | CdmwRailPage::RigWeights
                                    ) || authoring);
                                ui.push_id(format!("cdmw-tool-page-{active_page:?}"), |ui| {
                                    egui::Frame::group(ui.style()).show(ui, |ui| {
                                        ui.add_enabled_ui(enabled, |ui| match active_page {
                                            CdmwRailPage::Select => {
                                                self.draw_cdmw_selection_page(ui, actions)
                                            }
                                            CdmwRailPage::Move
                                            | CdmwRailPage::Rotate
                                            | CdmwRailPage::Scale => self.draw_cdmw_transform_page(
                                                ui,
                                                actions,
                                                active_page,
                                            ),
                                            CdmwRailPage::Grab
                                            | CdmwRailPage::Smooth
                                            | CdmwRailPage::Inflate
                                            | CdmwRailPage::Pinch => {
                                                self.draw_cdmw_brush_page(ui, active_page)
                                            }
                                            CdmwRailPage::Topology => {
                                                self.draw_cdmw_topology_page(ui, actions)
                                            }
                                            CdmwRailPage::Cleanup => {
                                                self.draw_cdmw_cleanup_page(ui, actions)
                                            }
                                            CdmwRailPage::Normals => {
                                                self.draw_cdmw_normals_page(ui, actions)
                                            }
                                            CdmwRailPage::Uv => self.draw_cdmw_uv_page(ui, actions),
                                            CdmwRailPage::RigWeights => {
                                                self.draw_cdmw_rig_weights_page(ui, actions)
                                            }
                                            CdmwRailPage::MorphRefit => {
                                                self.draw_cdmw_morph_page(ui, actions)
                                            }
                                        });
                                    });
                                });
                            }
                        }
                    })
            })
            .inner;
        if group.header_response.clicked() && active {
            if let Some(mut state) =
                egui::collapsing_header::CollapsingState::load(ui.ctx(), group.header_response.id)
            {
                state.set_open(false);
                state.store(ui.ctx());
            }
            self.cdmw_rail_page = None;
            self.cancel_active_gesture("Tool section collapsed");
            self.cdmw_orbit_mode = true;
        }
    }

    fn draw_cdmw_viewport_section(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        if self.view_mode != ViewMode::UvChecker
            && !CDMW_VIEW_MODES
                .iter()
                .any(|(mode, _)| *mode == self.view_mode)
        {
            self.view_mode = ViewMode::TexturedSolid;
        }
        if self.view_mode == ViewMode::TexturedSolid && !self.cdmw_textured_mode_available {
            self.view_mode = ViewMode::Solid;
        }
        ComboBox::from_label("Display")
            .selected_text(cdmw_view_mode_label(self.view_mode))
            .show_ui(ui, |ui| {
                for (mode, label) in CDMW_VIEW_MODES {
                    let enabled =
                        mode != ViewMode::TexturedSolid || self.cdmw_textured_mode_available;
                    let response = ui
                        .add_enabled(enabled, Button::new(label).selected(self.view_mode == mode))
                        .on_disabled_hover_text(&self.cdmw_textured_mode_reason);
                    if response.clicked() {
                        self.view_mode = mode;
                    }
                }
            });
        if !self.cdmw_textured_mode_available {
            ui.label(
                RichText::new(&self.cdmw_textured_mode_reason)
                    .small()
                    .color(Color32::from_rgb(230, 170, 90)),
            );
        }
        ui.horizontal_wrapped(|ui| {
            ui.checkbox(&mut self.show_normals, "Normals")
                .on_hover_text(
                    "Shows short, sampled cyan lines pointing along vertex normals. These are direction guides, not bones or geometry.",
                );
            ui.checkbox(&mut self.show_bounds, "Bounds");
            let bones_ready = !self.skeleton_overlay_lines.is_empty();
            ui.add_enabled(
                bones_ready,
                egui::Checkbox::new(&mut self.show_bones, "Bones"),
            )
            .on_hover_text(&self.cdmw_skeleton_overlay_reason)
            .on_disabled_hover_text(&self.cdmw_skeleton_overlay_reason);
        });
        ui.checkbox(
            &mut self.deformation_heatmap_enabled,
            "Persistent edit colours",
        )
        .on_hover_text(
            "Shows cumulative deformation from the loaded topology: green for a small change, yellow for a medium change, and red for a large change. Turning this off only hides the preview; it never changes or saves the material.",
        );
        let mut screen_grid_visible = cdmw_screen_grid_visible(ui.ctx());
        if ui
            .checkbox(&mut screen_grid_visible, "Screen grid (overlay)")
            .on_hover_text(
                "Optional two-dimensional alignment guide. It is off by default because it is drawn above the mesh.",
            )
            .changed()
        {
            set_cdmw_screen_grid_visible(ui.ctx(), screen_grid_visible);
        }
        ui.horizontal_wrapped(|ui| {
            if ui.small_button("Fit").clicked() {
                actions.push(UiAction::FrameAll);
            }
            if ui.small_button("Selected").clicked() {
                actions.push(UiAction::FrameSelected);
            }
        });
        ui.add_enabled(false, Button::new("Material Colour"))
            .on_disabled_hover_text(
                "Material Colour is deliberately unavailable in the Mesh Editor product contract",
            );
        cdmw_section(
            ui,
            "cdmw-overlay-appearance",
            "Overlay appearance",
            None,
            |ui| {
                colour_row(ui, "Wire", &mut self.overlay_wire_colour);
                colour_row(ui, "Vertices", &mut self.overlay_vertex_colour);
                colour_row(ui, "Selection", &mut self.overlay_selection_colour);
                colour_row(
                    ui,
                    "Live selection",
                    &mut self.overlay_live_selection_colour,
                );
                ui.add(
                    egui::Slider::new(&mut self.overlay_wire_width, 0.5..=6.0).text("Wire width"),
                );
                ui.add(
                    egui::Slider::new(&mut self.overlay_vertex_size, 0.5..=10.0)
                        .text("Vertex size"),
                );
                colour_row(ui, "Background", &mut self.viewport_background_colour);
                ui.add_enabled_ui(screen_grid_visible, |ui| {
                    colour_row(ui, "Screen grid", &mut self.viewport_grid_colour);
                });
                if ui.button("Reset appearance").clicked() {
                    self.overlay_wire_colour = Color32::from_rgb(105, 125, 155);
                    self.overlay_vertex_colour = Color32::from_gray(205);
                    self.overlay_selection_colour = Color32::from_rgb(255, 145, 35);
                    self.overlay_live_selection_colour = Color32::from_rgb(80, 190, 255);
                    self.viewport_background_colour = Color32::from_rgb(6, 8, 10);
                    self.viewport_grid_colour = Color32::from_rgb(42, 48, 58);
                    self.overlay_wire_width = 1.2;
                    self.overlay_vertex_size = 2.5;
                    self.deformation_heatmap_enabled = true;
                }
            },
        );
        if ui
            .add_enabled(
                state_bool(&self.cdmw_state, "authoring_enabled"),
                Button::new("Open Package in CDMW..."),
            )
            .on_disabled_hover_text(
                "This session is read-only; choose an editable output route first",
            )
            .clicked()
        {
            actions.push(UiAction::ChooseCdmwImportPackage);
        }
        ui.separator();
        self.draw_cdmw_output_policy(ui, actions);
    }

    fn draw_cdmw_output_policy(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let policy = state_str(&self.cdmw_state, "output_policy").unwrap_or("exact_game_asset");
        let exact = policy == "exact_game_asset";
        let free_edit = policy == "free_edit_rebuild";
        let read_only = !exact && !free_edit;
        let archive_refit = self.cdmw_has_archive_refit();
        ui.label(RichText::new("Output").strong());
        ui.horizontal(|ui| {
            if ui.add(Button::new("Exact").selected(exact)).clicked() && !exact {
                actions.push(UiAction::CdmwCommand {
                    command: "configure_output_policy",
                    arguments: json!({"policy": "exact_game_asset", "destination": ""}),
                    label: "Switch to exact output",
                });
            }
            if ui
                .add_enabled(!archive_refit, Button::new("Free Edit").selected(free_edit))
                .on_hover_text("Allows adding and removing geometry. Choose a folder for a new OBJ package.")
                .on_disabled_hover_text("Archive Refit keeps each original game file. Finish this session, then open a separate mesh for Free Edit.")
                .clicked()
                && !free_edit
            {
                actions.push(UiAction::ChooseCdmwFreeEdit);
            }
        });
        let ready = state_bool(&self.cdmw_state, "output_destination_ready");
        let reason = state_str(&self.cdmw_state, "output_policy_reason").unwrap_or("");
        ui.label(if archive_refit {
            "Archive Refit · original game files"
        } else if exact {
            "Protected game-asset output"
        } else if free_edit && ready {
            "Free Edit package folder ready"
        } else if read_only {
            "Read-only until an authoring output is selected"
        } else {
            "Choose a writable package folder"
        });
        if !reason.is_empty() {
            ui.small(reason);
        }
        if ui
            .add_enabled(free_edit && ready, Button::new("Export Free Edit Package"))
            .on_disabled_hover_text("Available only after a Free Edit package folder is proven")
            .clicked()
        {
            actions.push(UiAction::CdmwCommand {
                command: "export_free_edit",
                arguments: json!({}),
                label: "Export Free Edit OBJ",
            });
        }
    }

    pub(super) fn cdmw_has_archive_refit(&self) -> bool {
        self.cdmw_state
            .get("archive_refit_assets")
            .and_then(Value::as_array)
            .is_some_and(|assets| !assets.is_empty())
    }

    fn draw_cdmw_selection_page(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        ui.label(RichText::new("Selection").strong());
        ui.horizontal(|ui| {
            ui.selectable_value(
                &mut self.selection_domain,
                SelectionDomain::Vertex,
                "Vertex",
            );
            ui.selectable_value(&mut self.selection_domain, SelectionDomain::Edge, "Edge");
            ui.selectable_value(&mut self.selection_domain, SelectionDomain::Face, "Face");
        });
        ComboBox::from_label("Shape")
            .selected_text(self.selection_tool.label())
            .show_ui(ui, |ui| {
                for tool in [
                    SelectionTool::Click,
                    SelectionTool::Brush,
                    SelectionTool::Rectangle,
                    SelectionTool::Lasso,
                ] {
                    ui.selectable_value(&mut self.selection_tool, tool, tool.label());
                }
            });
        ComboBox::from_label("Operation")
            .selected_text(format!("{:?}", self.selection_operation))
            .show_ui(ui, |ui| {
                for operation in [
                    SelectionOperation::Replace,
                    SelectionOperation::Add,
                    SelectionOperation::Subtract,
                    SelectionOperation::Toggle,
                ] {
                    ui.selectable_value(
                        &mut self.selection_operation,
                        operation,
                        format!("{operation:?}"),
                    );
                }
            });
        ui.horizontal(|ui| {
            ui.label("Depth");
            ui.selectable_value(&mut self.selection_visible_only, true, "Visible");
            ui.selectable_value(&mut self.selection_visible_only, false, "X-Ray");
        });
        if self.selection_tool == SelectionTool::Brush {
            ui.add(egui::Slider::new(&mut self.brush_radius, 4.0..=240.0).text("Radius px"));
        }
        let selected = self.selected_counts().for_domain(self.selection_domain);
        ui.horizontal_wrapped(|ui| {
            if ui
                .add_enabled(selected > 0, Button::new("Linked"))
                .clicked()
            {
                actions.push(UiAction::SelectLinked(self.selection_domain));
            }
            if ui.add_enabled(selected > 0, Button::new("Grow")).clicked() {
                actions.push(UiAction::GrowSelection(self.selection_domain));
            }
            if ui
                .add_enabled(selected > 0, Button::new("Shrink"))
                .clicked()
            {
                actions.push(UiAction::ShrinkSelection(self.selection_domain));
            }
            if ui.button("Invert").clicked() {
                actions.push(UiAction::InvertSelection(self.selection_domain));
            }
        });
        let free_edit = state_str(&self.cdmw_state, "output_policy") == Some("free_edit_rebuild");
        if ui
            .add_enabled(
                free_edit && self.selected_counts().faces > 0,
                Button::new("Create Part"),
            )
            .on_disabled_hover_text("Create Part requires selected faces and Free Edit output")
            .clicked()
        {
            actions.push(UiAction::CdmwTopology {
                action: "separate",
                label: "Create part from selection",
                params: json!({}),
            });
        }
    }

    fn draw_cdmw_transform_page(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        page: CdmwRailPage,
    ) {
        let selected = self.selected_counts().total() > 0;
        ui.label("Drag a gizmo axis, ring, or center handle in the viewport.");
        match page {
            CdmwRailPage::Rotate => {
                ui.horizontal(|ui| {
                    ui.label("Angle °");
                    ui.add(
                        egui::DragValue::new(&mut self.transform_rotate_step)
                            .speed(0.5)
                            .range(-360.0..=360.0),
                    );
                });
                if self.show_normals {
                    ui.small(
                        "Cyan sampled lines show vertex-normal direction; they are not bones.",
                    );
                }
                let degrees = self.transform_rotate_step;
                ui.horizontal_wrapped(|ui| {
                    for (label, axis) in [
                        ("Rotate X", Vec3::X),
                        ("Rotate Y", Vec3::Y),
                        ("Rotate Z", Vec3::Z),
                    ] {
                        if ui.add_enabled(selected, Button::new(label)).clicked() {
                            actions.push(UiAction::RotateStep { axis, degrees });
                        }
                    }
                });
            }
            CdmwRailPage::Scale => {
                ui.horizontal(|ui| {
                    ui.label("Factor");
                    ui.add(
                        egui::DragValue::new(&mut self.transform_scale_factor)
                            .speed(0.01)
                            .range(0.001..=100.0),
                    );
                });
                let factor = self.transform_scale_factor.max(0.001);
                ui.horizontal_wrapped(|ui| {
                    for (label, scale) in [
                        ("Scale X", Vec3::new(factor, 1.0, 1.0)),
                        ("Scale Y", Vec3::new(1.0, factor, 1.0)),
                        ("Scale Z", Vec3::new(1.0, 1.0, factor)),
                        ("Scale Uniform", Vec3::splat(factor)),
                    ] {
                        if ui.add_enabled(selected, Button::new(label)).clicked() {
                            actions.push(UiAction::ScaleStep(scale));
                        }
                    }
                });
            }
            _ => {
                ui.horizontal(|ui| {
                    ui.label("Axis step");
                    ui.add(egui::DragValue::new(&mut self.transform_translate_step).speed(0.001));
                });
                let step = self.transform_translate_step;
                ui.horizontal_wrapped(|ui| {
                    for (label, axis, sign) in [
                        ("-X", "x", -1.0),
                        ("+X", "x", 1.0),
                        ("-Y", "y", -1.0),
                        ("+Y", "y", 1.0),
                        ("-Z", "z", -1.0),
                        ("+Z", "z", 1.0),
                    ] {
                        if ui.add_enabled(selected, Button::new(label)).clicked() {
                            let mut delta = [0.0_f32; 3];
                            let index = match axis {
                                "x" => 0,
                                "y" => 1,
                                _ => 2,
                            };
                            delta[index] = step * sign;
                            actions.push(UiAction::Nudge(Vec3::from_array(delta)));
                        }
                    }
                });
            }
        }
        ui.small(if selected {
            "Numeric buttons and viewport gestures commit one undoable shadow transaction."
        } else {
            "Select vertices, edges, faces, or parts before transforming."
        });
    }

    fn draw_cdmw_brush_page(&mut self, ui: &mut egui::Ui, page: CdmwRailPage) {
        ui.add(egui::Slider::new(&mut self.brush_radius, 4.0..=240.0).text("Radius px"));
        if page != CdmwRailPage::Grab {
            let range = if page == CdmwRailPage::Inflate {
                -1.0..=1.0
            } else {
                0.01..=1.0
            };
            ui.add(egui::Slider::new(&mut self.brush_strength, range).text("Strength"));
            if page == CdmwRailPage::Inflate {
                ui.small("Positive inflates; negative deflates along the surface normals.");
            }
        }
        ComboBox::from_label("Falloff")
            .selected_text(self.brush_falloff.label())
            .show_ui(ui, |ui| {
                for falloff in [
                    BrushFalloff::Smooth,
                    BrushFalloff::Linear,
                    BrushFalloff::Constant,
                ] {
                    ui.selectable_value(&mut self.brush_falloff, falloff, falloff.label());
                }
            });
        ComboBox::from_label("Symmetry")
            .selected_text(self.sculpt_symmetry.label())
            .show_ui(ui, |ui| {
                for symmetry in [
                    SculptSymmetry::Off,
                    SculptSymmetry::X,
                    SculptSymmetry::Y,
                    SculptSymmetry::Z,
                ] {
                    ui.selectable_value(&mut self.sculpt_symmetry, symmetry, symmetry.label());
                }
            });
        if self.sculpt_symmetry != SculptSymmetry::Off {
            ui.small(format!(
                "{} mirrors in object space; unmatched vertices stay untouched.",
                self.sculpt_symmetry.label()
            ));
        }
        if page == CdmwRailPage::Smooth {
            ComboBox::from_label("Passes")
                .selected_text(format_pass_count(self.smooth_iterations))
                .show_ui(ui, |ui| {
                    for passes in 1..=8 {
                        ui.selectable_value(
                            &mut self.smooth_iterations,
                            passes,
                            format_pass_count(passes),
                        );
                    }
                });
        }
        ui.small(if self.selected_counts().total() == 0 {
            "No selection: the brush affects vertices under its painted area."
        } else {
            "Selected: the painted brush area is clipped to the explicit selection."
        });
    }

    fn draw_cdmw_topology_page(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let free_edit = state_str(&self.cdmw_state, "output_policy") == Some("free_edit_rebuild");
        let selected = self.selected_counts();
        ui.horizontal_wrapped(|ui| {
            ui.label("Extrude distance");
            ui.add(egui::DragValue::new(&mut self.extrude_distance).speed(0.001));
            ComboBox::from_id_salt("cdmw_extrude_axis")
                .selected_text(self.cdmw_extrude_axis.to_ascii_uppercase())
                .show_ui(ui, |ui| {
                    for axis in ["x", "y", "z"] {
                        ui.selectable_value(
                            &mut self.cdmw_extrude_axis,
                            axis.to_owned(),
                            axis.to_ascii_uppercase(),
                        );
                    }
                });
            ui.label("Inset");
            ui.add(
                egui::DragValue::new(&mut self.inset_amount)
                    .speed(0.01)
                    .range(0.01..=0.95),
            );
        });
        ui.horizontal_wrapped(|ui| {
            ui.label("Loop cuts");
            ui.add(
                egui::DragValue::new(&mut self.cdmw_loop_cut_count)
                    .speed(1)
                    .range(1..=16),
            );
            ui.label("Factor");
            ui.add(
                egui::DragValue::new(&mut self.cdmw_loop_cut_factor)
                    .speed(0.01)
                    .range(0.001..=0.999),
            );
        });
        ui.horizontal_wrapped(|ui| {
            ui.label("Refine");
            ui.add(
                egui::DragValue::new(&mut self.cdmw_refine_strength)
                    .speed(0.01)
                    .range(0.0..=1.0),
            );
            ui.label("passes");
            ui.add(
                egui::DragValue::new(&mut self.cdmw_refine_iterations)
                    .speed(1)
                    .range(1..=12),
            );
        });
        ui.horizontal(|ui| {
            ui.label("Weld distance");
            ui.add(
                egui::DragValue::new(&mut self.cdmw_weld_distance)
                    .speed(0.00001)
                    .range(0.000001..=1.0),
            );
        });
        for (label, action, availability) in [
            ("Delete Selection", "delete", selected.total() > 0),
            (
                "Duplicate Selection",
                "duplicate",
                free_edit && selected.total() > 0,
            ),
            ("Subdivide", "subdivide", free_edit && selected.faces > 0),
            (
                "Refine Smooth",
                "refine_smooth",
                free_edit && selected.faces > 0,
            ),
            ("Loop Cut", "loop_cut", free_edit && selected.edges > 0),
            ("Edge Split", "edge_split", free_edit && selected.edges > 0),
            ("Split", "split", free_edit && selected.total() > 0),
            ("Dissolve", "dissolve", free_edit && selected.total() > 0),
            ("Bridge", "bridge", free_edit && selected.edges > 0),
            ("Fill", "fill", free_edit && selected.edges > 0),
            ("Merge", "merge", free_edit && selected.vertices > 1),
            ("Weld", "weld", free_edit && selected.vertices > 1),
            ("Separate", "separate", free_edit && selected.faces > 0),
        ] {
            if ui
                .add_enabled(
                    availability,
                    Button::new(label).min_size(egui::vec2(ui.available_width(), 24.0)),
                )
                .on_disabled_hover_text(if !free_edit && action != "delete" {
                    "This topology action requires Free Edit output"
                } else {
                    "Select the required mesh elements first"
                })
                .clicked()
            {
                let params = match action {
                    "loop_cut" => json!({
                        "cuts": self.cdmw_loop_cut_count,
                        "factor": self.cdmw_loop_cut_factor,
                    }),
                    "refine_smooth" => json!({
                        "smooth_strength": self.cdmw_refine_strength,
                        "smooth_iterations": self.cdmw_refine_iterations,
                    }),
                    "weld" => json!({"threshold": self.cdmw_weld_distance}),
                    _ => json!({}),
                };
                actions.push(UiAction::CdmwTopology {
                    action,
                    label,
                    params,
                });
            }
        }
        ui.horizontal(|ui| {
            let extrude_label = if selected.faces > 0 {
                "Extrude Faces"
            } else {
                "Extrude Edges"
            };
            if ui
                .add_enabled(
                    free_edit && (selected.faces > 0 || selected.edges > 0),
                    Button::new(extrude_label),
                )
                .on_disabled_hover_text(if !free_edit {
                    "Extrude requires Free Edit output"
                } else {
                    "Select faces or edges first"
                })
                .clicked()
            {
                let offset = match self.cdmw_extrude_axis.as_str() {
                    "x" => [self.extrude_distance, 0.0, 0.0],
                    "y" => [0.0, self.extrude_distance, 0.0],
                    _ => [0.0, 0.0, self.extrude_distance],
                };
                actions.push(UiAction::CdmwTopology {
                    action: "extrude",
                    label: if selected.faces > 0 {
                        "Extrude faces"
                    } else {
                        "Extrude edges"
                    },
                    params: json!({"offset": offset}),
                });
            }
            if ui
                .add_enabled(free_edit && selected.faces > 0, Button::new("Inset"))
                .clicked()
            {
                actions.push(UiAction::CdmwTopology {
                    action: "inset",
                    label: "Inset faces",
                    params: json!({"amount": self.inset_amount}),
                });
            }
        });
    }

    fn draw_cdmw_cleanup_page(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let free_edit = state_str(&self.cdmw_state, "output_policy") == Some("free_edit_rebuild");
        let selected =
            self.selected_counts().total() > 0 || !self.selected_part_indices().is_empty();
        ui.label(RichText::new("Cleanup & Repair").strong());
        if !free_edit {
            ui.colored_label(
                Color32::from_rgb(245, 190, 75),
                "Cleanup is locked by Exact output. Choose Free Edit under Output to allow topology repair.",
            );
        }
        ui.horizontal(|ui| {
            ui.label("Merge distance");
            ui.add(
                egui::DragValue::new(&mut self.cdmw_cleanup_merge_distance)
                    .speed(0.00001)
                    .range(0.000001..=1.0),
            );
        });
        let threshold = self.cdmw_cleanup_merge_distance;
        for (label, action, params) in [
            (
                "Remove Doubles",
                "remove_doubles",
                json!({"threshold": threshold}),
            ),
            ("Delete Loose Vertices", "delete_loose_vertices", json!({})),
            ("Compact Orphans", "compact_orphans", json!({})),
            ("Repair Winding", "fix_winding", json!({})),
            ("Fill Holes", "fill_holes", json!({})),
        ] {
            if ui
                .add_enabled(
                    free_edit,
                    Button::new(label).min_size(egui::vec2(ui.available_width(), 24.0)),
                )
                .on_disabled_hover_text("Cleanup that changes topology requires Free Edit output")
                .clicked()
            {
                actions.push(UiAction::CdmwMeshAction {
                    action,
                    label,
                    params,
                });
            }
        }
        ui.separator();
        ui.label(RichText::new("Mirror Copy").strong());
        ui.horizontal_wrapped(|ui| {
            for (label, axis) in [("Mirror X", "x"), ("Mirror Y", "y"), ("Mirror Z", "z")] {
                if ui
                    .add_enabled(free_edit && selected, Button::new(label))
                    .on_disabled_hover_text(if !free_edit {
                        "Mirrored geometry requires Free Edit output"
                    } else {
                        "Select mesh elements or Parts to mirror"
                    })
                    .clicked()
                {
                    actions.push(UiAction::CdmwMeshAction {
                        action: "mirror",
                        label,
                        params: json!({"axis": axis}),
                    });
                }
            }
        });
        if free_edit {
            ui.small(if selected {
                "Remove Doubles uses selected vertices. Other cleanup actions repair each selected element's owning Part."
            } else {
                "No selection: cleanup applies to every editable Part."
            });
        }
    }

    fn draw_cdmw_normals_page(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let selected =
            self.selected_counts().total() > 0 || !self.selected_part_indices().is_empty();
        ui.checkbox(&mut self.show_normals, "Preview normal directions")
            .on_hover_text(
                "Cyan sampled lines point away from the surface along the current vertex normals.",
            );
        ui.small(
            "Selected elements target their owning Part for Recalculate, Weighted, and Tangents. Flip, Sharpen, Soften, and Copy can use element rows. Normal commands enable the direction preview automatically; tangents are recorded but have no line overlay.",
        );
        for (label, action) in [
            ("Recalculate Normals", "recalculate_normals"),
            ("Generate Tangents", "generate_tangents"),
            ("Flip Normals", "flip_normals"),
            ("Sharpen Normals", "sharpen_normals"),
            ("Soften Normals", "soften_normals"),
            ("Weighted Normals", "weighted_normals"),
            ("Copy Source Normals", "copy_normals"),
        ] {
            let response = ui
                .add_enabled(
                    selected,
                    Button::new(label).min_size(egui::vec2(ui.available_width(), 24.0)),
                )
                .on_disabled_hover_text("Select mesh elements or Parts first");
            if response.clicked() {
                if action != "generate_tangents" {
                    self.show_normals = true;
                }
                actions.push(UiAction::CdmwMeshAction {
                    action,
                    label,
                    params: json!({}),
                });
            }
        }
        ui.small("Copy Source Normals restores the matching original game-mesh normal rows.");
        if let Some(feedback) = &self.cdmw_normals_feedback {
            ui.label(RichText::new(format!("Result: {feedback}")).small());
        }
    }

    fn draw_cdmw_uv_page(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let selected =
            self.selected_counts().total() > 0 || !self.selected_part_indices().is_empty();
        let free_edit = state_str(&self.cdmw_state, "output_policy") == Some("free_edit_rebuild");
        ui.label(RichText::new("UV0 Editing").strong());
        ui.horizontal_wrapped(|ui| {
            if ui.button("Show UV Checker").clicked() {
                self.view_mode = ViewMode::UvChecker;
            }
            ui.small("UV tools move UV0, not the 3D mesh. Use the checker to see the result.");
        });
        ui.horizontal(|ui| {
            ui.label("Move step");
            ui.add(
                egui::DragValue::new(&mut self.cdmw_uv_offset_step)
                    .speed(0.005)
                    .range(0.0001..=10.0),
            );
        });
        let offset = self.cdmw_uv_offset_step;
        ui.horizontal_wrapped(|ui| {
            for (label, uv) in [
                ("U-", [-offset, 0.0]),
                ("U+", [offset, 0.0]),
                ("V-", [0.0, -offset]),
                ("V+", [0.0, offset]),
            ] {
                if ui.add_enabled(selected, Button::new(label)).clicked() {
                    actions.push(UiAction::CdmwMeshAction {
                        action: "uv_transform",
                        label: "Move UV",
                        params: json!({"offset": uv}),
                    });
                }
            }
        });
        ui.horizontal(|ui| {
            ui.label("Scale factor");
            ui.add(
                egui::DragValue::new(&mut self.cdmw_uv_scale_factor)
                    .speed(0.01)
                    .range(0.001..=100.0),
            );
        });
        let scale = self.cdmw_uv_scale_factor.max(0.001);
        ui.horizontal_wrapped(|ui| {
            for (label, params) in [
                (
                    "Scale UV",
                    json!({"scale": [scale, scale], "pivot": [0.5, 0.5]}),
                ),
                ("Flip U", json!({"flip_u": true, "pivot": [0.5, 0.5]})),
                ("Flip V", json!({"flip_v": true, "pivot": [0.5, 0.5]})),
                ("Rotate 90°", json!({"rotate": 90.0, "pivot": [0.5, 0.5]})),
            ] {
                if ui.add_enabled(selected, Button::new(label)).clicked() {
                    actions.push(UiAction::CdmwMeshAction {
                        action: "uv_transform",
                        label,
                        params,
                    });
                }
            }
        });
        ui.separator();
        ui.label(RichText::new("Island & Layout").strong());
        for (label, params, needs_free_edit) in [
            (
                "Normalize Island",
                json!({"uv_island": true, "normalize": true}),
                false,
            ),
            ("Normalize to 0-1", json!({"normalize": true}), false),
            ("Align U", json!({"align_u": "min"}), false),
            ("Align V", json!({"align_v": "min"}), false),
            (
                "Planar Project",
                json!({"projection": "planar", "plane": "xy"}),
                false,
            ),
            ("Box Project", json!({"projection": "box"}), false),
            (
                "Cylindrical Project",
                json!({"projection": "cylindrical", "axis": "z"}),
                false,
            ),
            (
                "Auto Unwrap",
                json!({"auto_uv": true, "allow_topology_change": true}),
                true,
            ),
            ("Pack Islands", json!({"pack": true}), false),
            ("Snap to Grid", json!({"snap_grid": 0.01}), false),
        ] {
            let enabled = selected && (!needs_free_edit || free_edit);
            if ui
                .add_enabled(
                    enabled,
                    Button::new(label).min_size(egui::vec2(ui.available_width(), 24.0)),
                )
                .on_disabled_hover_text(if !selected {
                    "Select mesh elements or Parts first"
                } else {
                    "Auto Unwrap may split vertices and requires Free Edit output"
                })
                .clicked()
            {
                actions.push(UiAction::CdmwMeshAction {
                    action: "uv_transform",
                    label,
                    params,
                });
            }
        }
        ui.horizontal_wrapped(|ui| {
            ui.label("Texture px");
            ui.label("W");
            ui.add(
                egui::DragValue::new(&mut self.cdmw_uv_pixel_width)
                    .speed(1)
                    .range(1..=32768),
            );
            ui.label("H");
            ui.add(
                egui::DragValue::new(&mut self.cdmw_uv_pixel_height)
                    .speed(1)
                    .range(1..=32768),
            );
            if ui
                .add_enabled(selected, Button::new("Snap Pixels"))
                .clicked()
            {
                actions.push(UiAction::CdmwMeshAction {
                    action: "uv_transform",
                    label: "Snap UV to pixels",
                    params: json!({
                        "snap_pixels": true,
                        "texture_size": [
                            self.cdmw_uv_pixel_width,
                            self.cdmw_uv_pixel_height
                        ]
                    }),
                });
            }
        });
        if let Some(feedback) = &self.cdmw_uv_feedback {
            ui.label(RichText::new(format!("Result: {feedback}")).small());
        }
    }

    fn cdmw_morph_part_names(&self, indices: &[u32]) -> String {
        let parts = self
            .document
            .as_ref()
            .and_then(|doc| doc.lods.get(self.active_lod_index));
        let names: Vec<_> = indices
            .iter()
            .take(8)
            .map(|index| {
                parts
                    .and_then(|lod| lod.submeshes.get(*index as usize))
                    .map(|part| format!("{} · {}", index + 1, part.name))
                    .unwrap_or_else(|| format!("Part {}", index + 1))
            })
            .collect();
        if names.is_empty() {
            "None assigned".to_owned()
        } else {
            names.join(", ")
        }
    }

    fn draw_cdmw_morph_meshes(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        state: &Value,
    ) {
        let blocked = if state_bool(state, "unbaked") {
            "Reset or Bake before loading meshes."
        } else if state
            .get("refit")
            .is_some_and(|refit| !value_u32_list(refit, "garment_submesh_indices").is_empty())
        {
            "Clear Refit before loading meshes."
        } else {
            ""
        };
        ui.horizontal_wrapped(|ui| {
            for (role, label) in [("body", "Add as Body..."), ("armor", "Add as Armor...")] {
                if ui
                    .add_enabled(blocked.is_empty(), Button::new(label))
                    .on_hover_text(if role == "body" {
                        "Choose any archive mesh and assign it as the body that drives shape changes."
                    } else {
                        "Choose armor or clothing to follow the body. If needed, the current mesh is assigned as the body."
                    })
                    .on_disabled_hover_text(blocked)
                    .clicked()
                {
                    actions.push(UiAction::ChooseCdmwRefitMesh { role });
                }
            }
        });
        if !blocked.is_empty() {
            ui.small(blocked);
        }
        let body = value_u32_list(state, "driver_submesh_indices");
        let mut assets = self
            .cdmw_state
            .get("archive_refit_assets")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        if assets.is_empty() {
            assets.push(json!({
                "path": state_str(&self.cdmw_state, "loaded_mesh").unwrap_or("Current mesh"),
                "part_indices": (0..self.cdmw_state.get("submesh_count")
                    .and_then(Value::as_u64).unwrap_or_else(|| self.document.as_ref()
                        .and_then(|doc| doc.lods.get(self.active_lod_index))
                        .map_or(0, |lod| lod.submeshes.len() as u64))).collect::<Vec<_>>()
            }));
        }
        for (asset_index, asset) in assets.iter().enumerate() {
            let indices = value_u32_list(asset, "part_indices");
            let body_count = indices.iter().filter(|index| body.contains(index)).count();
            let is_body = !indices.is_empty() && body_count == indices.len();
            let (role, colour) = if is_body {
                ("BODY", REFIT_BODY_COLOUR)
            } else if body_count > 0 {
                ("MIXED", REFIT_ARMOR_COLOUR)
            } else if body.is_empty() {
                ("UNASSIGNED", ui.visuals().weak_text_color())
            } else {
                ("ARMOR", REFIT_ARMOR_COLOUR)
            };
            let path = state_str(asset, "path").unwrap_or("");
            ui.push_id(("refit-asset", asset_index), |ui| {
                ui.group(|ui| {
                    ui.horizontal(|ui| {
                        ui.colored_label(colour, RichText::new(role).strong());
                        ui.weak(format!("{} Parts", indices.len()));
                    });
                    ui.add(egui::Label::new(path.rsplit(['/', '\\']).next().unwrap_or(path)).truncate())
                        .on_hover_text(path);
                    ui.horizontal(|ui| {
                        if ui.button("Select").clicked() {
                            actions.push(UiAction::SetPartSelection(indices.clone()));
                        }
                        if !is_body && ui.add_enabled(blocked.is_empty(), Button::new("Set as body"))
                            .on_hover_text("Assign only this asset's Parts as the body. Other loaded assets become garment candidates.")
                            .on_disabled_hover_text(blocked).clicked() {
                            actions.push(UiAction::CdmwCommand {
                                command: "refit_set_driver", arguments: json!({"submesh_indices": indices}),
                                label: "Set refit body",
                            });
                        }
                    });
                });
            });
        }
        let selected = self.selected_part_indices();
        let counts = self.selected_counts();
        ui.weak(format!("{} Parts selected", selected.len()))
            .on_hover_text(format!(
                "{} vertices · {} edges · {} faces",
                counts.vertices, counts.edges, counts.faces
            ));
        if ui.button("Open Selection tool").clicked() {
            self.cancel_active_gesture("Open selection for Morph & Refit");
            self.cdmw_rail_page = Some(CdmwRailPage::Select);
            self.viewport_tool = ViewportTool::Select;
            self.cdmw_orbit_mode = false;
        }
        cdmw_section(ui, "morph-part-picker", "Choose Parts", None, |ui| {
            let parts = self
                .document
                .as_ref()
                .and_then(|doc| doc.lods.get(self.active_lod_index))
                .map(|lod| {
                    lod.submeshes
                        .iter()
                        .enumerate()
                        .map(|(index, part)| (index as u32, part.name.clone()))
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default();
            let visible = self.cdmw_visible_submeshes();
            ui.scope(|ui| {
                ui.style_mut().wrap_mode = Some(egui::TextWrapMode::Truncate);
                for (index, name) in parts {
                    let mut checked = selected.contains(&index);
                    if ui
                        .add_enabled(
                            visible
                                .as_ref()
                                .is_none_or(|visible| visible.contains(&index)),
                            egui::Checkbox::new(&mut checked, format!("{} · {name}", index + 1)),
                        )
                        .on_hover_text(&name)
                        .on_disabled_hover_text(
                            "Show this Part in the Parts inspector before selecting it",
                        )
                        .changed()
                    {
                        let mut next = selected.clone();
                        next.retain(|item| *item != index);
                        if checked {
                            next.push(index);
                        }
                        actions.push(UiAction::SetPartSelection(next));
                    }
                }
            });
        });
    }

    fn draw_cdmw_refit_roles(
        &self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        body: &[u32],
        garments: &[u32],
    ) {
        ui.horizontal_wrapped(|ui| {
            ui.colored_label(REFIT_BODY_COLOUR, format!("Body · {} Parts", body.len()))
                .on_hover_text(self.cdmw_morph_part_names(body));
            ui.colored_label(
                REFIT_ARMOR_COLOUR,
                format!("Bound · {} Parts", garments.len()),
            )
            .on_hover_text(format!("Garments: {}", self.cdmw_morph_part_names(garments)));
        });
        let available_garments = if body.is_empty() {
            Vec::new()
        } else if garments.is_empty() {
            self.document
                .as_ref()
                .and_then(|doc| doc.lods.get(self.active_lod_index))
                .map(|lod| {
                    (0..lod.submeshes.len() as u32)
                        .filter(|index| !body.contains(index))
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default()
        } else {
            garments.to_vec()
        };
        let selected = self.selected_part_indices();
        ui.horizontal_wrapped(|ui| {
            for (indices, label) in [(body, "Select body"), (available_garments.as_slice(), "Select garments")] {
                if label == "Select garments" && indices.is_empty() && !body.is_empty() {
                    let unbaked = self.cdmw_state.get("morph_refit")
                        .is_some_and(|state| state_bool(state, "unbaked"));
                    if ui.add_enabled(!unbaked, Button::new("Load armor..."))
                        .on_hover_text("No garment Parts are loaded. Choose armor or clothing from the archive.")
                        .on_disabled_hover_text("Reset or Bake before loading armor")
                        .clicked()
                    {
                        actions.push(UiAction::ChooseCdmwRefitMesh { role: "armor" });
                    }
                    continue;
                }
                if ui
                    .add_enabled(!indices.is_empty(), Button::new(label).selected(
                        !indices.is_empty() && indices.len() == selected.len()
                            && indices.iter().all(|index| selected.contains(index))
                    ))
                    .on_hover_text("Select the loaded Parts for editing. This does not load another file.")
                    .on_disabled_hover_text("Assign body Parts first using the control below")
                    .clicked()
                {
                    actions.push(UiAction::SetPartSelection(indices.to_vec()));
                }
            }
        });
        ui.colored_label(
            if garments.is_empty() {
                REFIT_ARMOR_COLOUR
            } else {
                REFIT_READY_COLOUR
            },
            if body.is_empty() {
                "Next: set a body in Meshes & selection."
            } else if available_garments.is_empty() {
                "Next: load armor."
            } else if garments.is_empty() {
                "Next: select garments, then bind."
            } else {
                "Ready · garments follow Shape sliders."
            },
        );
    }

    fn draw_cdmw_morph_page(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let state = self
            .cdmw_state
            .get("morph_refit")
            .cloned()
            .unwrap_or(Value::Null);
        let profile_id = state
            .get("profile_id")
            .and_then(Value::as_str)
            .unwrap_or("");
        let selected_parts = self.selected_part_indices();
        let has_mesh_selection = self.selected_counts().total() > 0 || !selected_parts.is_empty();
        let authoring = state_bool(&self.cdmw_state, "authoring_enabled");
        let definitions = state
            .get("definitions")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let morph_unbaked = state_bool(&state, "unbaked");
        if state.get("available").and_then(Value::as_bool) == Some(false) {
            ui.colored_label(
                Color32::from_rgb(245, 190, 75),
                state_str(&state, "reason").unwrap_or("Morph runtime unavailable"),
            );
            return;
        }
        if morph_unbaked {
            ui.colored_label(
                Color32::from_rgb(245, 190, 75),
                "Shape preview · Reset or Bake when finished.",
            );
        }
        if let Some(failure) = state_str(&state, "failure").filter(|value| !value.trim().is_empty())
        {
            ui.colored_label(Color32::from_rgb(245, 105, 105), failure);
        }
        let profiles = pair_list(&state, "available_profiles");
        let active_profile_name = profiles
            .iter()
            .find(|(id, _)| id == profile_id)
            .map(|(_, name)| name.clone())
            .unwrap_or_default();
        if self.cdmw_morph_hydrated_profile != profile_id {
            if !active_profile_name.is_empty() {
                self.cdmw_morph_profile_name = active_profile_name.clone();
            }
            self.cdmw_morph_hydrated_profile = profile_id.to_owned();
        }
        cdmw_section(ui, "morph-meshes", "Meshes & selection", None, |ui| {
            self.draw_cdmw_morph_meshes(ui, actions, &state);
        });
        let mut reveal_authoring = self.draw_cdmw_refit_section(ui, actions, &state);
        cdmw_section(ui, "morph-profiles", "Profiles & presets", None, |ui| {
            ComboBox::from_label("Profile")
                .selected_text(
                    profiles
                        .iter()
                        .find(|(id, _)| id == profile_id)
                        .map(|(_, name)| name.as_str())
                        .unwrap_or("No active profile"),
                )
                .show_ui(ui, |ui| {
                    for (id, name) in profiles {
                        if ui.selectable_label(id == profile_id, name).clicked() {
                            actions.push(UiAction::CdmwCommand {
                                command: "morph_activate",
                                arguments: json!({"profile_id": id}),
                                label: "Activate morph profile",
                            });
                        }
                    }
                });
            ui.horizontal_wrapped(|ui| {
                if ui
                    .add_enabled(!profile_id.is_empty(), Button::new("Save Profile"))
                    .clicked()
                {
                    actions.push(UiAction::CdmwCommand {
                        command: "morph_save_profile",
                        arguments: json!({}),
                        label: "Save morph profile",
                    });
                }
                if ui
                    .add_enabled(!profile_id.is_empty(), Button::new("Delete Profile"))
                    .clicked()
                {
                    actions.push(UiAction::CdmwCommand {
                        command: "morph_delete_profile",
                        arguments: json!({"profile_id": profile_id}),
                        label: "Delete morph profile",
                    });
                }
            });
            let preset_id = state.get("preset_id").and_then(Value::as_str).unwrap_or("");
            let presets = pair_list(&state, "available_presets");
            ui.add_enabled_ui(!profile_id.is_empty(), |ui| {
                ComboBox::from_label("Saved preset")
                    .selected_text(
                        presets
                            .iter()
                            .find(|(id, _)| id == preset_id)
                            .map(|(_, name)| name.as_str())
                            .unwrap_or("Current values"),
                    )
                    .show_ui(ui, |ui| {
                        for (id, name) in presets {
                            if ui.selectable_label(id == preset_id, name).clicked() {
                                actions.push(UiAction::CdmwCommand {
                                    command: "morph_apply_preset",
                                    arguments: json!({"preset_id": id}),
                                    label: "Apply morph preset",
                                });
                            }
                        }
                    });
            });
            ui.horizontal_wrapped(|ui| {
                ui.add(
                    egui::TextEdit::singleline(&mut self.cdmw_morph_preset_name)
                        .desired_width(ui.available_width()),
                );
                if ui
                    .add_enabled(
                        !profile_id.is_empty() && !self.cdmw_morph_preset_name.trim().is_empty(),
                        Button::new("Save Preset"),
                    )
                    .on_disabled_hover_text("Activate a profile and enter a non-empty preset name")
                    .clicked()
                {
                    let name = self.cdmw_morph_preset_name.trim().to_owned();
                    actions.push(UiAction::CdmwCommand {
                        command: "morph_save_preset",
                        arguments: json!({
                            "preset_id": stable_ui_id("preset", &name),
                            "name": name
                        }),
                        label: "Save morph preset",
                    });
                }
                if ui
                    .add_enabled(!preset_id.is_empty(), Button::new("Delete Preset"))
                    .clicked()
                {
                    actions.push(UiAction::CdmwCommand {
                        command: "morph_delete_preset",
                        arguments: json!({"preset_id": preset_id}),
                        label: "Delete morph preset",
                    });
                }
            });
            ui.horizontal_wrapped(|ui| {
                if ui
                    .add_enabled(authoring && !morph_unbaked, Button::new("Load Preset..."))
                    .clicked()
                {
                    actions.push(UiAction::ChooseCdmwMorphPreset { save: false });
                }
                if ui
                    .add_enabled(
                        !profile_id.is_empty() && !self.cdmw_morph_preset_name.trim().is_empty(),
                        Button::new("Export Preset..."),
                    )
                    .clicked()
                {
                    actions.push(UiAction::ChooseCdmwMorphPreset { save: true });
                }
            });
            ui.small("Export Preset creates a shareable JSON file.");
        });
        cdmw_section(ui, "morph-values", "Shape sliders", None, |ui| {
            if definitions.is_empty() {
                ui.weak("Create a slider or load a preset to begin.");
            }
            let values = pair_number_list(&state, "values");
            for (definition_id, host_value) in values {
                let definition = definitions.iter().find(|candidate| {
                    state_str(candidate, "definition_id") == Some(&definition_id)
                });
                let label = definition
                    .and_then(|candidate| state_str(candidate, "label"))
                    .filter(|label| !label.trim().is_empty())
                    .unwrap_or(&definition_id)
                    .to_owned();
                let minimum = definition
                    .and_then(|candidate| candidate.get("min_percent"))
                    .and_then(Value::as_f64)
                    .filter(|value| value.is_finite())
                    .unwrap_or(-100.0);
                let maximum = definition
                    .and_then(|candidate| candidate.get("max_percent"))
                    .and_then(Value::as_f64)
                    .filter(|value| value.is_finite() && *value > minimum)
                    .unwrap_or(100.0);
                let rule = definition
                    .and_then(|candidate| candidate.get("rule"))
                    .cloned()
                    .unwrap_or(Value::Null);
                let rule_name = state_str(&rule, "kind").unwrap_or("stored").to_owned();
                let rule_axis = state_str(&rule, "axis").unwrap_or("-").to_owned();
                let rule_amount = rule
                    .get("amount")
                    .and_then(Value::as_f64)
                    .filter(|amount| amount.is_finite())
                    .unwrap_or(0.0);
                let rule_feather = rule
                    .get("feather")
                    .and_then(Value::as_u64)
                    .unwrap_or(2)
                    .min(64) as u32;
                let rule_falloff = state_str(&rule, "falloff").unwrap_or("smooth").to_owned();
                let mirror_mode = definition
                    .and_then(|candidate| state_str(candidate, "mirror_mode"))
                    .unwrap_or("off")
                    .to_owned();
                let mut value = self
                    .cdmw_morph_value_drafts
                    .get(&definition_id)
                    .copied()
                    .unwrap_or(host_value);
                let response = ui
                .add(egui::Slider::new(&mut value, minimum..=maximum).text(&label))
                .on_hover_text(format!(
                    "Stored {rule_name} rule · axis {rule_axis} · 100% strength {rule_amount:.3}"
                ));
                let commit = stage_cdmw_morph_value(
                    &mut self.cdmw_morph_value_drafts,
                    &definition_id,
                    value,
                    response.changed(),
                    response.is_pointer_button_down_on() || response.has_focus(),
                    response.drag_stopped() || response.lost_focus(),
                );
                ui.push_id(("morph-definition-actions", &definition_id), |ui| {
                    ui.horizontal_wrapped(|ui| {
                        if ui.button("Edit slider").clicked() {
                            reveal_authoring = true;
                            self.cdmw_morph_definition_edit_id = definition_id.clone();
                            self.cdmw_morph_replace_selection_on_edit = false;
                            self.cdmw_morph_definition_label = label.clone();
                            self.cdmw_morph_rule = rule_name.clone();
                            self.cdmw_morph_axis = rule_axis.clone();
                            self.cdmw_morph_amount = rule_amount as f32;
                            self.cdmw_morph_feather = rule_feather;
                            self.cdmw_morph_falloff = rule_falloff.clone();
                            self.cdmw_morph_mirror_mode = mirror_mode.clone();
                            if !active_profile_name.is_empty() {
                                self.cdmw_morph_profile_name = active_profile_name.clone();
                            }
                        }
                        if ui
                            .add_enabled(authoring && !morph_unbaked, Button::new("Delete slider"))
                            .on_disabled_hover_text(if !authoring {
                                "This session is read-only"
                            } else {
                                "Reset or Bake the current Morph preview before deleting a slider"
                            })
                            .clicked()
                        {
                            actions.push(UiAction::CdmwCommand {
                                command: "morph_delete_definition",
                                arguments: json!({"definition_id": definition_id.clone()}),
                                label: "Delete morph slider",
                            });
                        }
                    });
                });
                if let Some(value) = commit {
                    actions.push(UiAction::CdmwCommand {
                    command: "morph_set_value",
                    arguments: json!({"definition_id": definition_id, "value": value, "phase": "end"}),
                    label: "Change morph value",
                });
                }
            }
            ui.horizontal_wrapped(|ui| {
                if ui
                    .add_enabled(!profile_id.is_empty(), Button::new("Reset"))
                    .clicked()
                {
                    actions.push(UiAction::CdmwCommand {
                        command: "morph_reset",
                        arguments: json!({}),
                        label: "Reset morph",
                    });
                }
                if ui
                    .add_enabled(state_bool(&state, "unbaked"), Button::new("Bake"))
                    .clicked()
                {
                    actions.push(UiAction::CdmwCommand {
                        command: "morph_bake",
                        arguments: json!({}),
                        label: "Bake morph",
                    });
                }
            });
        });
        let authoring_section = cdmw_section(
            ui,
            "morph-authoring",
            "Create / edit sliders",
            reveal_authoring.then_some(true),
            |ui| {
                ui.small(if has_mesh_selection {
                    "New sliders use the current selection."
                } else {
                    "Select a Part or region before creating a slider."
                });
                ui.horizontal(|ui| {
                    ui.label("Profile name");
                    ui.add(
                        egui::TextEdit::singleline(&mut self.cdmw_morph_profile_name)
                            .desired_width(ui.available_width()),
                    );
                });
                ui.horizontal(|ui| {
                    ui.label("Slider label");
                    ui.add(
                        egui::TextEdit::singleline(&mut self.cdmw_morph_definition_label)
                            .desired_width(ui.available_width()),
                    );
                });
                let editing_definition = !self.cdmw_morph_definition_edit_id.is_empty();
                if editing_definition {
                    ui.horizontal_wrapped(|ui| {
                        ui.colored_label(
                            Color32::from_rgb(105, 205, 135),
                            format!("Editing slider · {}", self.cdmw_morph_definition_label),
                        );
                        ui.add_enabled(
                            has_mesh_selection,
                            egui::Checkbox::new(
                                &mut self.cdmw_morph_replace_selection_on_edit,
                                "Replace scope with current selection",
                            ),
                        )
                        .on_disabled_hover_text(
                            "Select elements or Parts before replacing the stored scope",
                        );
                        if ui.button("Cancel Edit").clicked() {
                            self.cdmw_morph_definition_edit_id.clear();
                            self.cdmw_morph_replace_selection_on_edit = false;
                        }
                    });
                }
                let replace_edit_scope =
                    editing_definition && self.cdmw_morph_replace_selection_on_edit;
                cdmw_section(ui, "morph-definition", "Slider definition", None, |ui| {
                    ui.horizontal_wrapped(|ui| {
                        ComboBox::from_label("Rule")
                            .selected_text(&self.cdmw_morph_rule)
                            .show_ui(ui, |ui| {
                                for (value, label) in [
                                    ("volume", "Volume"),
                                    ("scale", "Scale"),
                                    ("move", "Move"),
                                    ("flatten", "Flatten"),
                                    ("taper", "Taper"),
                                    ("twist", "Twist"),
                                    ("radius", "Radius"),
                                ] {
                                    ui.selectable_value(
                                        &mut self.cdmw_morph_rule,
                                        value.to_owned(),
                                        label,
                                    );
                                }
                            });
                        ComboBox::from_label("Axis")
                            .selected_text(self.cdmw_morph_axis.to_ascii_uppercase())
                            .show_ui(ui, |ui| {
                                for axis in ["x", "y", "z"] {
                                    ui.selectable_value(
                                        &mut self.cdmw_morph_axis,
                                        axis.to_owned(),
                                        axis.to_ascii_uppercase(),
                                    );
                                }
                            });
                    });
                    ui.horizontal(|ui| {
                        let twist = self.cdmw_morph_rule == "twist";
                        ui.label(if twist {
                            "100% rotation (degrees)"
                        } else {
                            "100% strength"
                        });
                        ui.add(
                            egui::DragValue::new(&mut self.cdmw_morph_amount)
                                .speed(if twist { 1.0 } else { 0.01 })
                                .range(if twist { -180.0..=180.0 } else { -10.0..=10.0 }),
                        );
                    });
                    ui.add_enabled_ui(!editing_definition || replace_edit_scope, |ui| {
                        ui.horizontal(|ui| {
                            ui.label("Feather rings");
                            ui.add(
                                egui::DragValue::new(&mut self.cdmw_morph_feather).range(0..=64),
                            );
                        });
                        ui.horizontal_wrapped(|ui| {
                            ComboBox::from_label("Falloff")
                                .selected_text(&self.cdmw_morph_falloff)
                                .show_ui(ui, |ui| {
                                    for falloff in ["constant", "linear", "smooth"] {
                                        ui.selectable_value(
                                            &mut self.cdmw_morph_falloff,
                                            falloff.to_owned(),
                                            falloff,
                                        );
                                    }
                                });
                            ComboBox::from_label("Mirror")
                                .selected_text(&self.cdmw_morph_mirror_mode)
                                .show_ui(ui, |ui| {
                                    for mirror in ["off", "x", "y", "z"] {
                                        ui.selectable_value(
                                            &mut self.cdmw_morph_mirror_mode,
                                            mirror.to_owned(),
                                            mirror,
                                        );
                                    }
                                });
                        });
                    });
                    if editing_definition && !replace_edit_scope {
                        ui.small("Feather, falloff, and mirror stay locked because the stored scope is being preserved.");
                    }
                });
                let create_ready = authoring
                    && !morph_unbaked
                    && (has_mesh_selection || (editing_definition && !replace_edit_scope))
                    && !self.cdmw_morph_profile_name.trim().is_empty()
                    && !self.cdmw_morph_definition_label.trim().is_empty();
                let create_label = if editing_definition {
                    "Update Slider"
                } else {
                    "Add Slider"
                };
                if ui
                    .add_enabled(create_ready, Button::new(create_label))
                    .on_disabled_hover_text(if !authoring {
                        "This session is read-only"
                    } else if morph_unbaked {
                        "Reset or Bake the current Morph preview before changing slider definitions"
                    } else if !has_mesh_selection && (!editing_definition || replace_edit_scope) {
                        "Select vertices, edges, faces, or Parts to define the slider scope"
                    } else {
                        "Enter a profile name and slider label"
                    })
                    .clicked()
                {
                    let profile_name = self.cdmw_morph_profile_name.trim().to_owned();
                    let label = self.cdmw_morph_definition_label.trim().to_owned();
                    let source_definition_id = self.cdmw_morph_definition_edit_id.clone();
                    let source_definition = definitions.iter().find(|candidate| {
                        state_str(candidate, "definition_id") == Some(source_definition_id.as_str())
                    });
                    let category = source_definition
                        .and_then(|candidate| state_str(candidate, "category"))
                        .unwrap_or("General")
                        .to_owned();
                    let minimum = source_definition
                        .and_then(|candidate| candidate.get("min_percent"))
                        .and_then(Value::as_f64)
                        .unwrap_or(-100.0);
                    let maximum = source_definition
                        .and_then(|candidate| candidate.get("max_percent"))
                        .and_then(Value::as_f64)
                        .unwrap_or(100.0);
                    let default = source_definition
                        .and_then(|candidate| candidate.get("default_percent"))
                        .and_then(Value::as_f64)
                        .unwrap_or(0.0);
                    let profile_id = if !profile_id.is_empty()
                        && (editing_definition || profile_name == active_profile_name)
                    {
                        profile_id.to_owned()
                    } else {
                        stable_ui_id("profile", &profile_name)
                    };
                    let definition_id = stable_ui_id("morph", &label);
                    actions.push(UiAction::CdmwCommand {
                        command: "morph_create",
                        arguments: json!({
                            "definition": {
                                "profile_id": profile_id,
                                "profile_name": profile_name,
                                "definition_id": definition_id,
                                "label": label,
                                "category": category,
                                "rule": self.cdmw_morph_rule,
                                "axis": self.cdmw_morph_axis,
                                "amount": self.cdmw_morph_amount,
                                "feather": self.cdmw_morph_feather,
                                "falloff": self.cdmw_morph_falloff,
                                "mirror_mode": self.cdmw_morph_mirror_mode,
                                "min_percent": minimum,
                                "max_percent": maximum,
                                "default_percent": default,
                                "preserve_selection": editing_definition && !replace_edit_scope,
                                "source_definition_id": source_definition_id
                            }
                        }),
                        label: if editing_definition {
                            "Update morph slider"
                        } else {
                            "Add morph slider"
                        },
                    });
                }
            },
        );
        if reveal_authoring {
            authoring_section
                .header_response
                .scroll_to_me(Some(egui::Align::Min));
        }
    }

    fn draw_cdmw_refit_section(
        &mut self,
        ui: &mut egui::Ui,
        actions: &mut Vec<UiAction>,
        state: &Value,
    ) -> bool {
        let profile_id = state_str(state, "profile_id").unwrap_or("");
        let selected_parts = self.selected_part_indices();
        let driver_parts = value_u32_list(state, "driver_submesh_indices");
        let refit = state.get("refit").cloned().unwrap_or(Value::Null);
        let bound_garments = value_u32_list(&refit, "garment_submesh_indices");
        let morph_unbaked = state_bool(state, "unbaked");
        let mut create_body_slider = false;
        cdmw_section(ui, "morph-refit", "Refit clothing & armor", None, |ui| {
            self.draw_cdmw_refit_roles(ui, actions, &driver_parts, &bound_garments);
            let has_definitions = state
                .get("definitions")
                .and_then(Value::as_array)
                .is_some_and(|definitions| !definitions.is_empty());
            if !bound_garments.is_empty() && !has_definitions
                && ui.add_enabled(!morph_unbaked, Button::new("Create body slider"))
                    .on_hover_text("Select the body and open the slider creator. The bound garments will follow.")
                    .clicked()
            {
                actions.push(UiAction::SetPartSelection(driver_parts.clone()));
                self.cdmw_morph_definition_edit_id.clear();
                create_body_slider = true;
            }
            if ui
                .add_enabled(
                    !morph_unbaked && !selected_parts.is_empty() && bound_garments.is_empty(),
                    Button::new("Set body from selection"),
                )
                .on_disabled_hover_text(if morph_unbaked {
                    "Reset or Bake before changing the body"
                } else if !bound_garments.is_empty() {
                    "Clear Refit before changing the body"
                } else {
                    "Select one or more body Parts above"
                })
                .clicked()
            {
                actions.push(UiAction::CdmwCommand {
                    command: "refit_set_driver",
                    arguments: json!({"submesh_indices": selected_parts}),
                    label: "Set refit driver",
                });
            }
            let has_driver = !driver_parts.is_empty();
            if ui
                .add_enabled(
                    !profile_id.is_empty()
                        && !morph_unbaked
                        && has_driver
                        && !selected_parts.is_empty()
                        && selected_parts
                            .iter()
                            .all(|index| !driver_parts.contains(index)),
                    Button::new("Bind selected garments"),
                )
                .on_disabled_hover_text(if profile_id.is_empty() {
                    "Activate a Morph profile before binding garments"
                } else if !has_driver {
                    "Set the Refit driver Parts first"
                } else if morph_unbaked {
                    "Reset or Bake before binding garments"
                } else if selected_parts
                    .iter()
                    .any(|index| driver_parts.contains(index))
                {
                    "Body and garment Parts must be different"
                } else {
                    "Select one or more clothing or armor Parts above"
                })
                .clicked()
            {
                actions.push(UiAction::CdmwCommand {
                    command: "refit_bind",
                    arguments: json!({"submesh_indices": selected_parts}),
                    label: "Bind refit garments",
                });
            }
            if ui
                .add_enabled(!profile_id.is_empty(), Button::new("Clear Refit"))
                .on_disabled_hover_text("Activate a Morph profile before clearing Refit")
                .clicked()
            {
                actions.push(UiAction::CdmwCommand {
                    command: "refit_clear",
                    arguments: json!({}),
                    label: "Clear refit",
                });
            }
            if state_bool(&refit, "distance_warning") {
                ui.colored_label(Color32::from_rgb(245, 190, 75),
                "Some garment vertices are far from the body. Check alignment and scale before refitting.");
            }
            let configurable = !profile_id.is_empty() && !bound_garments.is_empty();
            if !configurable {
                ui.weak("Garment settings appear after binding.");
                return;
            }
            let selected_bound_garments = selected_parts
                .iter()
                .copied()
                .filter(|index| bound_garments.contains(index))
                .collect::<Vec<_>>();
            let hydration_target = selected_bound_garments
                .first()
                .copied()
                .or_else(|| bound_garments.first().copied());
            if let Some(target) = hydration_target {
                let setting = refit
                    .get("garment_settings")
                    .and_then(Value::as_array)
                    .and_then(|settings| {
                        settings.iter().find(|setting| {
                            setting.get("submesh_index").and_then(Value::as_u64)
                                == Some(u64::from(target))
                        })
                    });
                let hydration_key = format!(
                    "{}:{target}:{}",
                    state
                        .get("state_revision")
                        .and_then(Value::as_u64)
                        .unwrap_or(0),
                    setting.map_or_else(|| "default".to_owned(), Value::to_string)
                );
                if self.cdmw_refit_hydration_target != Some(target)
                    || (!self.cdmw_refit_settings_dirty
                        && self.cdmw_refit_hydration_key != hydration_key)
                {
                    self.cdmw_refit_hydration_target = Some(target);
                    self.cdmw_refit_settings_dirty = false;
                    self.cdmw_refit_enabled = setting
                        .and_then(|value| value.get("enabled"))
                        .and_then(Value::as_bool)
                        .unwrap_or(true);
                    self.cdmw_refit_intensity = setting
                        .and_then(|value| value.get("intensity_percent"))
                        .and_then(Value::as_f64)
                        .unwrap_or(100.0) as f32;
                    self.cdmw_refit_mode = setting
                        .and_then(|value| value.get("mode"))
                        .and_then(Value::as_str)
                        .unwrap_or("surface")
                        .to_owned();
                    self.cdmw_refit_clearance = setting
                        .and_then(|value| value.get("clearance_percent"))
                        .and_then(Value::as_f64)
                        .unwrap_or(0.0) as f32;
                    self.cdmw_refit_hydration_key = hydration_key;
                }
            }
            ui.separator();
            ui.add_enabled_ui(configurable, |ui| {
                let before = (
                    self.cdmw_refit_enabled,
                    self.cdmw_refit_intensity,
                    self.cdmw_refit_mode.clone(),
                    self.cdmw_refit_clearance,
                );
                ui.checkbox(&mut self.cdmw_refit_enabled, "Refit enabled")
                    .on_hover_text("Let these garments follow body Shape sliders. Apply to update the current preview.");
                ComboBox::from_label("Mode")
                    .selected_text(if self.cdmw_refit_mode == "rigid" { "Rigid" } else { "Surface" })
                    .show_ui(ui, |ui| {
                        ui.selectable_value(
                            &mut self.cdmw_refit_mode,
                            "surface".to_owned(),
                            "Surface",
                        ).on_hover_text("Follow the body surface. Suitable for cloth and flexible armor.");
                        ui.selectable_value(&mut self.cdmw_refit_mode, "rigid".to_owned(), "Rigid")
                            .on_hover_text("Move each Part as a rigid piece. Suitable for hard armor plates.");
                    });
                ui.add(
                    egui::Slider::new(&mut self.cdmw_refit_intensity, 0.0..=200.0)
                        .text("Intensity %"),
                ).on_hover_text("How strongly the garment follows body changes. 100% follows fully; 0% stays still.");
                ui.add(
                    egui::Slider::new(&mut self.cdmw_refit_clearance, 0.0..=5.0)
                        .text("Clearance %"),
                ).on_hover_text("Extra space from the body, as a percentage of body size.");
                if before
                    != (
                        self.cdmw_refit_enabled,
                        self.cdmw_refit_intensity,
                        self.cdmw_refit_mode.clone(),
                        self.cdmw_refit_clearance,
                    )
                {
                    self.cdmw_refit_settings_dirty = true;
                }
                if self.cdmw_refit_settings_dirty {
                    ui.colored_label(REFIT_ARMOR_COLOUR, "Changes not applied");
                } else {
                    ui.weak("Adjust settings, then apply.");
                }
                if ui
                    .add_enabled(
                        !selected_bound_garments.is_empty(),
                        Button::new("Apply to Selected Garments"),
                    )
                    .on_disabled_hover_text("Select one or more bound garment Parts first")
                    .clicked()
                {
                    actions.push(UiAction::CdmwCommand {
                        command: "refit_configure",
                        arguments: json!({
                            "submesh_indices": selected_bound_garments,
                            "enabled": self.cdmw_refit_enabled,
                            "intensity_percent": self.cdmw_refit_intensity,
                            "mode": self.cdmw_refit_mode,
                            "clearance_percent": self.cdmw_refit_clearance
                        }),
                        label: "Apply garment refit settings",
                    });
                }
                if ui.button("Apply to All Bound Garments").clicked() {
                    actions.push(UiAction::CdmwCommand {
                        command: "refit_configure",
                        arguments: json!({
                            "submesh_indices": bound_garments,
                            "enabled": self.cdmw_refit_enabled,
                            "intensity_percent": self.cdmw_refit_intensity,
                            "mode": self.cdmw_refit_mode,
                            "clearance_percent": self.cdmw_refit_clearance
                        }),
                        label: "Apply garment refit settings",
                    });
                }
            });
        });
        create_body_slider
    }

    fn draw_cdmw_right_panels(&mut self, root_ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let busy = self.cdmw_show_busy_controls();
        egui::Panel::right("cdmw_right_panels")
            .default_size(320.0)
            .min_size(270.0)
            .max_size(430.0)
            .resizable(true)
            .show(root_ui, |ui| {
                ScrollArea::vertical().show(ui, |ui| {
                    ui.add_enabled_ui(!busy, |ui| {
                        egui::Frame::group(ui.style()).show(ui, |ui| {
                            ui.set_width(ui.available_width());
                            cdmw_section(ui, "cdmw-parts", "Parts", None, |ui| {
                                self.draw_cdmw_parts(ui, actions);
                            });
                        });
                        ui.add_space(6.0);
                        egui::Frame::group(ui.style()).show(ui, |ui| {
                            ui.set_width(ui.available_width());
                            cdmw_section(ui, "cdmw-layers", "Geometry Layers", None, |ui| {
                                self.draw_cdmw_layers(ui, actions);
                            });
                        });
                        ui.add_space(6.0);
                        egui::Frame::group(ui.style()).show(ui, |ui| {
                            ui.set_width(ui.available_width());
                            cdmw_section(ui, "cdmw-history", "Action History", None, |ui| {
                                self.draw_cdmw_history(ui);
                            });
                        });
                    });
                });
            });
    }

    fn draw_cdmw_parts(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let selected = self.selected_part_indices();
        let parts = self
            .document
            .as_ref()
            .and_then(|document| document.lods.get(self.active_lod_index))
            .map(|lod| {
                lod.submeshes
                    .iter()
                    .enumerate()
                    .map(|(index, part)| (index as u32, part.name.clone(), part.material.clone()))
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        let visible = self.cdmw_visible_submeshes();
        let available = parts
            .iter()
            .map(|(index, _, _)| *index)
            .filter(|index| {
                visible
                    .as_ref()
                    .is_none_or(|visible| visible.contains(index))
            })
            .collect::<Vec<_>>();
        let busy = self.cdmw_busy();
        ui.horizontal(|ui| {
            ui.weak(format!("{} / {} selected", selected.len(), parts.len()));
        });
        ui.add_enabled_ui(!busy, |ui| {
            ui.horizontal_wrapped(|ui| {
                if ui.add_enabled(!available.is_empty(), Button::new("All")).clicked() {
                    actions.push(UiAction::SetPartSelection(available.clone()));
                }
                if ui.button("None").clicked() {
                    actions.push(UiAction::SetPartSelection(Vec::new()));
                }
                if ui.add_enabled(!available.is_empty(), Button::new("Invert")).clicked() {
                    actions.push(UiAction::SetPartSelection(available.iter().copied()
                        .filter(|index| !selected.contains(index)).collect()));
                }
                ui.menu_button("Visibility", |ui| {
                    if ui.add_enabled(!selected.is_empty(), Button::new("Hide Selected")).clicked() {
                        actions.push(UiAction::SetPartVisibility { indices: selected.clone(), visible: false });
                        ui.close();
                    }
                    if ui.add_enabled(!self.cdmw_hidden_parts.is_empty(), Button::new("Show All")).clicked() {
                        actions.push(UiAction::SetPartVisibility {
                            indices: self.cdmw_hidden_parts.iter().copied().collect(), visible: true,
                        });
                        ui.close();
                    }
                }).response.on_hover_text("Viewport visibility only; hidden parts remain in the output");
            });
            let layer_visible = self.cdmw_layer_visible_submeshes();
            ScrollArea::vertical().id_salt("cdmw_parts_list").max_height(160.0).show(ui, |ui| {
                ui.spacing_mut().item_spacing.y = 2.0;
                ui.spacing_mut().button_padding.y = 1.0;
                for (index, name, material) in &parts {
                    ui.push_id(index, |ui| ui.horizontal(|ui| {
                        let in_visible_layer = layer_visible.as_ref().is_none_or(|visible| visible.contains(index));
                        let mut shown = !self.cdmw_hidden_parts.contains(index);
                        if ui.add_enabled(in_visible_layer, egui::Checkbox::without_text(&mut shown))
                            .on_hover_text("Show part in viewport")
                            .on_disabled_hover_text("Show this part's Geometry Layer first")
                            .changed() {
                            actions.push(UiAction::SetPartVisibility { indices: vec![*index], visible: shown });
                        }
                        let active = selected.contains(index);
                        let row = ui.add_enabled(shown && in_visible_layer,
                            Button::selectable(active, format!("{index}: {name}")).truncate());
                        if row.on_hover_text(format!("{index}: {name}\nMaterial: {material}"))
                            .on_disabled_hover_text(format!("{index}: {name}\nMaterial: {material}\nShow this part to select it"))
                            .clicked() {
                            let mut updated = selected.clone();
                            if active { updated.retain(|value| value != index); }
                            else { updated.push(*index); }
                            updated.sort_unstable();
                            actions.push(UiAction::SetPartSelection(updated));
                        }
                    }));
                }
            });
            ui.horizontal_wrapped(|ui| {
                for (action, title, label) in [("duplicate", "Duplicate", "Duplicate part"), ("delete", "Delete", "Delete part")] {
                    let reason = self.cdmw_part_action_reason(action);
                    if ui.add_enabled(reason.is_none(), Button::new(title))
                        .on_disabled_hover_text(reason.unwrap_or_default()).clicked() {
                        actions.push(UiAction::CdmwCommand {
                            command: "topology",
                            arguments: json!({
                                "action": action,
                                "selection": {"source_indices": selected,
                                    "vertices_by_submesh": {}, "edges_by_submesh": {}, "faces_by_submesh": {}},
                                "params": if action == "delete" { json!({"delete_parts": true}) } else { json!({}) },
                                "label": label,
                            }),
                            label,
                        });
                    }
                }
            });
        });
        if busy {
            ui.small("Updating parts…");
        } else if state_str(&self.cdmw_state, "output_policy") != Some("free_edit_rebuild") {
            ui.menu_button("Enable part edits…", |ui| {
                self.draw_cdmw_output_policy(ui, actions)
            })
            .response
            .on_hover_text("Duplicate and Delete require Free Edit output");
        } else if !selected.is_empty() && selected.len() >= parts.len() {
            ui.small("Keep at least one part when deleting.");
        }
    }

    fn cdmw_part_action_reason(&self, action: &str) -> Option<&'static str> {
        if self.cdmw_busy() {
            return Some("Wait for the selected parts to finish updating");
        }
        if !state_bool(&self.cdmw_state, "authoring_enabled") {
            return Some("This session is read-only");
        }
        if state_str(&self.cdmw_state, "output_policy") != Some("free_edit_rebuild") {
            return Some("Choose Free Edit under Output to change the part structure");
        }
        let selected = self.selected_part_indices();
        if selected.is_empty() {
            return Some("Select one or more parts first");
        }
        let count = self
            .document
            .as_ref()
            .and_then(|document| document.lods.get(self.active_lod_index))
            .map_or(0, |lod| lod.submeshes.len());
        if action == "delete" && selected.len() >= count {
            return Some("Keep at least one part when deleting");
        }
        None
    }

    pub(super) fn set_cdmw_part_visibility(&mut self, indices: Vec<u32>, visible: bool) {
        for index in indices {
            if visible {
                self.cdmw_hidden_parts.remove(&index);
            } else {
                self.cdmw_hidden_parts.insert(index);
            }
        }
        let visible = self.cdmw_visible_submeshes();
        if let (Some(mesh), Some(visible)) = (&mut self.mesh, visible) {
            let handles = mesh.element_handles_for_submeshes(&visible);
            let mut selection = mesh.selection.clone();
            selection
                .vertices
                .retain(|handle| handles.vertices.contains(handle));
            selection
                .edges
                .retain(|handle| handles.edges.contains(handle));
            selection
                .faces
                .retain(|handle| handles.faces.contains(handle));
            selection.submeshes.retain(|index| visible.contains(index));
            if selection != mesh.selection && mesh.set_selection(selection).is_ok() {
                self.submit_cdmw_local_edit(CdmwLocalEdit::Selection(
                    "Hide selected parts".to_owned(),
                ));
            }
        }
        self.publish_mesh_snapshot();
    }

    pub(super) fn cdmw_visible_submeshes(&self) -> Option<HashSet<u32>> {
        let layers = self.cdmw_layer_visible_submeshes();
        if self.cdmw_hidden_parts.is_empty() {
            return layers;
        }
        let mut visible = layers.unwrap_or_else(|| {
            self.mesh
                .as_ref()
                .map_or_else(HashSet::new, WorkingMesh::submesh_indices)
        });
        visible.retain(|index| !self.cdmw_hidden_parts.contains(index));
        Some(visible)
    }

    pub(super) fn remap_cdmw_hidden_parts(&self, next: &MeshDocument) -> HashSet<u32> {
        let Some(previous) = self
            .document
            .as_ref()
            .and_then(|document| document.lods.get(self.active_lod_index))
        else {
            return HashSet::new();
        };
        let Some(next) = next.lods.get(self.active_lod_index) else {
            return HashSet::new();
        };
        self.cdmw_hidden_parts
            .iter()
            .filter_map(|index| {
                let part = previous.submeshes.get(*index as usize)?;
                let mut matches = next
                    .submeshes
                    .iter()
                    .enumerate()
                    .filter(|(_, next)| same_source_part(part, next));
                let (index, _) = matches.next()?;
                matches.next().is_none().then_some(index as u32)
            })
            .collect()
    }

    fn draw_cdmw_layers(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        let layer_state = self
            .cdmw_state
            .get("geometry_layers")
            .cloned()
            .unwrap_or(Value::Null);
        let active_id = state_str(&layer_state, "active_layer_id")
            .unwrap_or("")
            .to_owned();
        let layers = layer_state
            .get("layers")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let authoring = state_bool(&self.cdmw_state, "authoring_enabled");
        for layer in &layers {
            let id = state_str(layer, "layer_id").unwrap_or("");
            let name = state_str(layer, "name").unwrap_or("Layer");
            let visible = state_bool(layer, "visible");
            let base = state_bool(layer, "base");
            ui.horizontal(|ui| {
                if ui
                    .add_enabled(authoring, Button::new(name).selected(id == active_id))
                    .on_disabled_hover_text(
                        "Geometry layers cannot be activated in a read-only session",
                    )
                    .clicked()
                {
                    actions.push(UiAction::CdmwCommand {
                        command: "layer_activate",
                        arguments: json!({"layer_id": id}),
                        label: "Activate geometry layer",
                    });
                }
                if ui
                    .add_enabled(
                        authoring && !base,
                        Button::new(if visible { "Visible" } else { "Hidden" }),
                    )
                    .on_disabled_hover_text(if base {
                        "Base mesh is always visible"
                    } else {
                        "Geometry layer visibility cannot change in a read-only session"
                    })
                    .clicked()
                {
                    actions.push(UiAction::CdmwCommand {
                        command: "layer_visibility",
                        arguments: json!({"layer_id": id, "visible": !visible}),
                        label: if visible {
                            "Hide geometry layer"
                        } else {
                            "Show geometry layer"
                        },
                    });
                }
            });
        }
        let active = layers
            .iter()
            .find(|layer| state_str(layer, "layer_id") == Some(active_id.as_str()));
        let active_base = active.is_some_and(|layer| state_bool(layer, "base"));
        let free_edit = state_str(&self.cdmw_state, "output_policy") == Some("free_edit_rebuild");
        let archive_refit = self.cdmw_has_archive_refit();
        let selected_elements = self.mesh.as_ref().map_or(0, |mesh| {
            mesh.selection.vertices.len() + mesh.selection.edges.len() + mesh.selection.faces.len()
        });
        let selected_parts = self.selected_part_indices().len();
        let has_selection = selected_elements > 0 || selected_parts > 0;
        if !authoring {
            ui.small("Geometry Layers are read-only in this session.");
        } else if archive_refit {
            ui.colored_label(REFIT_ARMOR_COLOUR, "Archive Refit · fixed geometry");
            ui.small("Layers organise loaded assets. Adding or removing geometry would prevent saving the original game files.");
        } else if !free_edit {
            ui.colored_label(
                Color32::from_rgb(245, 190, 75),
                "Adding geometry needs Free Edit: export a new OBJ package to a folder.",
            );
        } else if has_selection {
            ui.small(format!(
                "Ready to copy · {selected_elements} selected element(s) · {selected_parts} selected Part(s)"
            ));
        } else {
            ui.small("Select mesh elements in the viewport or click one or more Parts above.");
        }
        ui.horizontal_wrapped(|ui| {
            if ui
                .add_enabled(
                    authoring && free_edit && has_selection,
                    Button::new("Copy Selection"),
                )
                .on_disabled_hover_text(if !authoring {
                    "Geometry Layers are read-only in this session"
                } else if archive_refit {
                    "Archive Refit preserves original geometry. Open a separate mesh for Free Edit."
                } else if !free_edit {
                    "Choose Free Edit under Output before copying geometry"
                } else {
                    "Select mesh elements or Parts to copy"
                })
                .clicked()
            {
                let selection = self.mesh.as_ref().map(cdmw_session::selection_payload).transpose().ok().flatten().unwrap_or_else(|| json!({}));
                actions.push(UiAction::CdmwCommand { command: "layer_copy", arguments: json!({"target": format!("{:?}", self.selection_domain).to_ascii_lowercase(), "selection": selection}), label: "Copy geometry selection" });
            }
            if ui
                .add_enabled(
                    authoring && free_edit && state_bool(&layer_state, "clipboard_ready"),
                    Button::new("Paste New Layer"),
                )
                .on_disabled_hover_text(if !authoring {
                    "Geometry Layers are read-only in this session"
                } else if archive_refit {
                    "Archive Refit preserves original geometry. Open a separate mesh for Free Edit."
                } else if !free_edit {
                    "Choose Free Edit under Output before creating a geometry layer"
                } else {
                    "Copy a mesh-element or Part selection first"
                })
                .clicked()
            {
                actions.push(UiAction::CdmwCommand { command: "layer_paste", arguments: json!({}), label: "Paste geometry layer" });
            }
            if ui.add_enabled(authoring && !active_id.is_empty() && !active_base && !self.cdmw_layer_name.trim().is_empty(), Button::new("Rename")).on_disabled_hover_text("Enter a non-empty name for the active non-base layer").clicked() {
                actions.push(UiAction::CdmwCommand { command: "layer_rename", arguments: json!({"layer_id": active_id, "name": self.cdmw_layer_name.trim()}), label: "Rename geometry layer" });
            }
            if ui.add_enabled(authoring && !active_id.is_empty() && !active_base, Button::new("Up")).clicked() {
                actions.push(UiAction::CdmwCommand { command: "layer_move", arguments: json!({"layer_id": active_id, "direction": -1}), label: "Move geometry layer up" });
            }
            if ui.add_enabled(authoring && !active_id.is_empty() && !active_base, Button::new("Down")).clicked() {
                actions.push(UiAction::CdmwCommand { command: "layer_move", arguments: json!({"layer_id": active_id, "direction": 1}), label: "Move geometry layer down" });
            }
            if ui.add_enabled(authoring && free_edit && !active_id.is_empty() && !active_base, Button::new("Delete")).clicked() {
                actions.push(UiAction::CdmwCommand { command: "layer_delete", arguments: json!({"layer_id": active_id}), label: "Delete geometry layer" });
            }
        });
        ui.horizontal(|ui| {
            ui.label("Layer name");
            ui.text_edit_singleline(&mut self.cdmw_layer_name);
        });
        if free_edit {
            ui.small("Copy Selection → Paste New Layer");
        }
    }

    fn draw_cdmw_history(&self, ui: &mut egui::Ui) {
        let entries = self
            .cdmw_state
            .get("history_entries")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let cursor = state_u64(&self.cdmw_state, "history_cursor") as usize;
        if entries.is_empty() {
            ui.label(RichText::new("No confirmed Mesh Editor actions yet").italics());
        }
        for (index, entry) in entries.iter().enumerate() {
            let label = entry
                .as_str()
                .map(ToOwned::to_owned)
                .or_else(|| {
                    entry
                        .get("label")
                        .and_then(Value::as_str)
                        .map(ToOwned::to_owned)
                })
                .unwrap_or_else(|| format!("Action {}", index + 1));
            ui.label(if index < cursor {
                format!("● {label}")
            } else {
                format!("○ {label}")
            });
        }
    }

    fn draw_cdmw_viewport(&mut self, root_ui: &mut egui::Ui) {
        egui::CentralPanel::no_frame().show(root_ui, |ui| {
            let rectangle = ui.max_rect();
            if cdmw_screen_grid_visible(ui.ctx()) {
                let grid_step = 32.0;
                let grid_stroke = egui::Stroke::new(1.0, self.viewport_grid_colour);
                let mut x = rectangle.left();
                while x <= rectangle.right() {
                    ui.painter().line_segment(
                        [
                            egui::pos2(x, rectangle.top()),
                            egui::pos2(x, rectangle.bottom()),
                        ],
                        grid_stroke,
                    );
                    x += grid_step;
                }
                let mut y = rectangle.top();
                while y <= rectangle.bottom() {
                    ui.painter().line_segment(
                        [
                            egui::pos2(rectangle.left(), y),
                            egui::pos2(rectangle.right(), y),
                        ],
                        grid_stroke,
                    );
                    y += grid_step;
                }
            }
            self.update_viewport_rect(rectangle);
            let response = ui.allocate_rect(rectangle, egui::Sense::click_and_drag());
            let authoring = state_bool(&self.cdmw_state, "authoring_enabled");
            let busy = self.cdmw_busy();
            let edit_allowed = !busy && (self.viewport_tool == ViewportTool::Select || authoring);
            if edit_allowed || busy {
                self.handle_viewport_input(ui, rectangle, &response);
            }
            self.paint_viewport_overlay(ui, rectangle);
            self.paint_rig_overlay(ui, rectangle);
            let mode = if self.cdmw_orbit_mode {
                "Orbit"
            } else {
                self.viewport_tool.label()
            };
            ui.painter().text(
                rectangle.left_top() + egui::vec2(12.0, 12.0),
                egui::Align2::LEFT_TOP,
                format!(
                    "wgpu · D3D12 · {mode} · {}",
                    cdmw_view_mode_label(self.view_mode)
                ),
                egui::TextStyle::Monospace.resolve(ui.style()),
                Color32::from_gray(190),
            );
            if self.cdmw_busy() {
                ui.painter()
                    .rect_filled(rectangle, 0.0, Color32::from_black_alpha(35));
            }
        });
    }

    fn selected_counts(&self) -> SelectedCounts {
        let Some(mesh) = &self.mesh else {
            self.selected_counts_cache.set(None);
            return SelectedCounts::default();
        };
        let key = (mesh.topology_generation, mesh.selection_revision);
        if let Some((cached_key, counts)) = self.selected_counts_cache.get()
            && cached_key == key
        {
            return counts;
        }
        let counts = SelectedCounts {
            vertices: mesh.selected_vertex_scope().len(),
            edges: mesh.selection.edges.len(),
            faces: mesh.selection.faces.len(),
        };
        self.selected_counts_cache.set(Some((key, counts)));
        counts
    }

    pub(super) fn selected_part_indices(&self) -> Vec<u32> {
        self.mesh.as_ref().map_or_else(Vec::new, |mesh| {
            let mut values = mesh.selection.submeshes.iter().copied().collect::<Vec<_>>();
            values.sort_unstable();
            values
        })
    }
}

#[derive(Debug, Clone, Copy, Default)]
pub(super) struct SelectedCounts {
    vertices: usize,
    edges: usize,
    faces: usize,
}

impl SelectedCounts {
    fn total(self) -> usize {
        self.vertices + self.edges + self.faces
    }
    fn for_domain(self, domain: SelectionDomain) -> usize {
        match domain {
            SelectionDomain::Vertex => self.vertices,
            SelectionDomain::Edge => self.edges,
            SelectionDomain::Face => self.faces,
        }
    }
}

fn colour_row(ui: &mut egui::Ui, label: &str, colour: &mut Color32) {
    ui.horizontal(|ui| {
        ui.label(label);
        ui.color_edit_button_srgba(colour);
    });
}

pub(super) fn stable_ui_id(prefix: &str, label: &str) -> String {
    let slug = label
        .trim()
        .to_ascii_lowercase()
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() {
                character
            } else {
                '-'
            }
        })
        .collect::<String>()
        .split('-')
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join("-");
    format!("{prefix}-{}", if slug.is_empty() { "item" } else { &slug })
}

pub(super) fn value_u32_list(value: &Value, key: &str) -> Vec<u32> {
    value
        .get(key)
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|item| item.as_u64().and_then(|number| u32::try_from(number).ok()))
        .collect()
}

pub(super) fn state_str<'a>(state: &'a Value, key: &str) -> Option<&'a str> {
    state.get(key).and_then(Value::as_str)
}

pub(super) fn state_u64(state: &Value, key: &str) -> u64 {
    state.get(key).and_then(Value::as_u64).unwrap_or(0)
}

pub(super) fn state_bool(state: &Value, key: &str) -> bool {
    state.get(key).and_then(Value::as_bool).unwrap_or(false)
}

fn pair_list(state: &Value, key: &str) -> Vec<(String, String)> {
    state
        .get(key)
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|pair| {
            let values = pair.as_array()?;
            Some((
                values.first()?.as_str()?.to_owned(),
                values.get(1)?.as_str()?.to_owned(),
            ))
        })
        .collect()
}

fn pair_number_list(state: &Value, key: &str) -> Vec<(String, f64)> {
    state
        .get(key)
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|pair| {
            let values = pair.as_array()?;
            Some((
                values.first()?.as_str()?.to_owned(),
                values.get(1)?.as_f64()?,
            ))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn integrated_display_modes_match_the_mesh_editor_product_choices() {
        assert_eq!(
            CDMW_VIEW_MODES.map(|(_, label)| label),
            [
                "Solid (Textured)",
                "Faces (No Textures)",
                "Faces + Wire",
                "Wire",
                "Vertices",
                "Wire + Vertices",
                "X-Ray",
            ]
        );
        let modes = CDMW_VIEW_MODES.map(|(mode, _)| mode);
        for diagnostic in [
            ViewMode::GameOutdoor,
            ViewMode::BaseColor,
            ViewMode::NormalMap,
            ViewMode::UvChecker,
            ViewMode::BaseAlpha,
            ViewMode::PartId,
            ViewMode::MaterialResponse,
            ViewMode::LayerMask,
        ] {
            assert!(!modes.contains(&diagnostic));
        }
    }

    #[test]
    fn screen_grid_is_explicitly_opt_in() {
        let context = egui::Context::default();
        assert!(!cdmw_screen_grid_visible(&context));
        set_cdmw_screen_grid_visible(&context, true);
        assert!(cdmw_screen_grid_visible(&context));
    }

    #[test]
    fn cdmw_theme_selects_the_explicit_variant_palette_font_scale_and_density() {
        let application = LabApplication::new(None, None);
        application.apply_cdmw_theme_payload(&json!({
            "variant": "light",
            "font_point_size": 12.0,
            "data_font_point_size": 10.0,
            "density": "comfortable",
            "palette": {
                "window": "#f4f6f8",
                "surface": "#ffffff",
                "surface_alt": "#eef2f6",
                "field": "#ffffff",
                "field_alt": "#f7f9fb",
                "border": "#d5dde6",
                "border_strong": "#8e959e",
                "text": "#1f2933",
                "text_muted": "#5d6978",
                "text_strong": "#111827",
                "button": "#eef2f6",
                "button_hover": "#e2e8f0",
                "button_pressed": "#d7dfe8",
                "button_border": "#868c94",
                "accent": "#2563eb",
                "accent_text": "#ffffff",
                "accent_soft": "#dbeafe",
                "warning_text": "#8a5a00",
                "error": "#c0362c"
            }
        }));

        assert_eq!(application.egui_context.theme(), egui::Theme::Light);
        let style = application.egui_context.global_style();
        assert_eq!(style.visuals.panel_fill, Color32::from_rgb(244, 246, 248));
        assert_eq!(style.visuals.window_fill, Color32::WHITE);
        assert_eq!(
            style.visuals.selection.bg_fill,
            Color32::from_rgb(219, 234, 254)
        );
        assert_eq!(
            style.visuals.selection.stroke.color,
            Color32::from_rgb(17, 24, 39)
        );
        assert_eq!(style.spacing.item_spacing, egui::vec2(10.0, 8.0));
        assert_eq!(style.spacing.interact_size.y, 34.0);
        let body = style
            .text_styles
            .get(&egui::TextStyle::Body)
            .expect("body font");
        let monospace = style
            .text_styles
            .get(&egui::TextStyle::Monospace)
            .expect("data font");
        assert!((body.size - 16.0).abs() < 0.01);
        assert!((monospace.size - 13.333_333).abs() < 0.01);
    }

    #[test]
    fn integrated_textured_mode_requires_a_successful_owned_upload() {
        let mut application = LabApplication::new(None, None);
        application.view_mode = ViewMode::TexturedSolid;
        application.record_cdmw_texture_uploads(1, 0, 0, Some("DDS upload validation failed"));
        assert!(!application.cdmw_textured_mode_available);
        assert_eq!(application.view_mode, ViewMode::Solid);
        assert!(
            application
                .cdmw_textured_mode_reason
                .contains("DDS upload validation failed")
        );

        application.view_mode = ViewMode::TexturedSolid;
        application.record_cdmw_texture_uploads(1, 1, 1, None);
        assert!(application.cdmw_textured_mode_available);
        assert_eq!(application.view_mode, ViewMode::TexturedSolid);
        assert!(application.cdmw_textured_mode_reason.is_empty());
    }
}
