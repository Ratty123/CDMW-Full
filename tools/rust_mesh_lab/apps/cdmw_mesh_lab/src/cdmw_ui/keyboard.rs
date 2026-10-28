//! Keyboard shortcuts: dispatch, tooltip hints and the Keyboard Shortcuts window.
//! A shortcut does what clicking its control does, including being refused with
//! that control's disabled reason.
use super::*;
use crate::cdmw_hair::HairTool;
use crate::shortcuts::{
    Binding, KeyChord, ModifierKey, NumpadKey, ReservedChord, SHORTCUT_GROUPS, SHORTCUTS,
    ShortcutAction, ShortcutGroup, ShortcutKey, ShortcutScope,
};
use cdmw_mesh::hair::GroupMode;

pub(super) const CDMW_REVEAL_VIEWPORT: &str = "cdmw_reveal_viewport_section";

fn shortcut_label(action: ShortcutAction) -> &'static str {
    use ShortcutAction as A;
    match action {
        A::ToolSelect | A::HairSelect => "Select",
        A::ToolMove | A::HairMove => "Move",
        A::ToolRotate => "Rotate",
        A::ToolScale => "Scale",
        A::ToolGrab => "Grab",
        A::ToolBend => "Bend",
        A::ToolSmooth | A::HairSmooth => "Smooth",
        A::ToolInflate => "Inflate",
        A::ToolPinch => "Pinch",
        A::Orbit => "Orbit",
        A::PageViewport => "Viewport",
        A::PageOutput => "Output",
        A::PageVertexParameters => "Vertex Parameters",
        A::PageTopology => "Topology",
        A::PageCleanup => "Cleanup",
        A::PageNormals => "Normals & Tangents",
        A::PageUv => "UV",
        A::PageCloth => "Cloth",
        A::PageJiggle => "Jiggle",
        A::PageMorphRefit => "Morph & Refit",
        A::TargetVertex => "Vertex",
        A::TargetEdge => "Edge",
        A::TargetFace => "Face",
        A::ShapeClick => "Click",
        A::ShapeBrush => "Brush",
        A::ShapeRectangle => "Rectangle",
        A::ShapeLasso => "Lasso",
        A::OperationReplace => "Replace",
        A::OperationAdd => "Add",
        A::OperationSubtract => "Subtract",
        A::OperationToggle => "Toggle",
        A::SelectAll => "Select All",
        A::ClearSelection => "Clear Selection",
        A::InvertSelection => "Invert",
        A::SelectLinked => "Linked",
        A::GrowSelection => "Grow",
        A::ShrinkSelection => "Shrink",
        A::ToggleXRay => "Visible / X-Ray",
        A::ExtendModifier => "Add while held (a click toggles)",
        A::SubtractModifier => "Subtract while held",
        A::FrameSelected => "Frame Selected",
        A::FrameAll => "Fit",
        A::ViewFront => "Front",
        A::ViewBack => "Back",
        A::ViewRight => "Right",
        A::ViewLeft => "Left",
        A::ViewTop => "Top",
        A::ViewBottom => "Bottom",
        A::YawMinus15 => "Yaw -15°",
        A::YawPlus15 => "Yaw +15°",
        A::Undo => "Undo",
        A::Redo => "Redo",
        A::DeleteSelection => "Delete selection",
        A::HairDraw => "Draw",
        A::HairErase => "Erase",
        A::HairCut => "Cut",
        A::HairLengthen => "Lengthen",
        A::HairComb => "Comb",
        A::HairCurl => "Curl",
        A::HairClump => "Clump",
        A::HairPhysics => "Physics",
        A::HairDeleteGuides => "Delete selected hair",
    }
}

fn group_label(group: ShortcutGroup) -> &'static str {
    match group {
        ShortcutGroup::Tools => "Tools",
        ShortcutGroup::Pages => "Pages",
        ShortcutGroup::Selection => "Selection",
        ShortcutGroup::SelectionModifiers => "Selection modifiers",
        ShortcutGroup::View => "Views",
        ShortcutGroup::History => "History",
        ShortcutGroup::Editing => "Editing",
        ShortcutGroup::Hair => "Hair Tools",
    }
}

fn rail_page(action: ShortcutAction) -> Option<CdmwRailPage> {
    use ShortcutAction as A;
    Some(match action {
        A::ToolSelect => CdmwRailPage::Select,
        A::ToolMove => CdmwRailPage::Move,
        A::ToolRotate => CdmwRailPage::Rotate,
        A::ToolScale => CdmwRailPage::Scale,
        A::ToolGrab => CdmwRailPage::Grab,
        A::ToolBend => CdmwRailPage::Bend,
        A::ToolSmooth => CdmwRailPage::Smooth,
        A::ToolInflate => CdmwRailPage::Inflate,
        A::ToolPinch => CdmwRailPage::Pinch,
        A::PageVertexParameters => CdmwRailPage::VertexParameters,
        A::PageTopology => CdmwRailPage::Topology,
        A::PageCleanup => CdmwRailPage::Cleanup,
        A::PageNormals => CdmwRailPage::Normals,
        A::PageUv => CdmwRailPage::Uv,
        A::PageCloth => CdmwRailPage::Cloth,
        A::PageJiggle => CdmwRailPage::Jiggle,
        A::PageMorphRefit => CdmwRailPage::MorphRefit,
        _ => return None,
    })
}

pub(super) fn rail_page_action(page: CdmwRailPage) -> Option<ShortcutAction> {
    SHORTCUTS
        .iter()
        .map(|spec| spec.action)
        .find(|action| rail_page(*action) == Some(page))
}

fn hair_tool(action: ShortcutAction) -> Option<HairTool> {
    use ShortcutAction as A;
    Some(match action {
        A::HairSelect => HairTool::Select,
        A::HairMove => HairTool::Move,
        A::HairDraw => HairTool::Guide,
        A::HairErase => HairTool::Erase,
        A::HairCut => HairTool::Cut,
        A::HairLengthen => HairTool::Lengthen,
        A::HairComb => HairTool::Comb,
        A::HairSmooth => HairTool::Smooth,
        A::HairCurl => HairTool::Curl,
        A::HairClump => HairTool::Clump,
        A::HairPhysics => HairTool::Physics,
        _ => return None,
    })
}

/// Removes the key presses that trigger a shortcut and returns their actions.
/// Numpad presses recorded by the window loop turn the matching egui key into its numpad key.
fn take_shortcut_presses(
    context: &egui::Context,
    mut numpad: Vec<(egui::Key, NumpadKey)>,
    mut take: impl FnMut(KeyChord) -> bool,
) -> Vec<KeyChord> {
    context.input_mut(|input| {
        let mut taken = Vec::new();
        input.events.retain(|event| {
            let egui::Event::Key {
                key,
                pressed: true,
                repeat,
                modifiers,
                ..
            } = event
            else {
                return true;
            };
            let shortcut_key = match numpad.iter().position(|(candidate, _)| candidate == key) {
                Some(index) => ShortcutKey::Numpad(numpad.remove(index).1),
                None => ShortcutKey::Key(*key),
            };
            let chord = KeyChord::new(shortcut_key, *modifiers);
            if *repeat || !take(chord) {
                return true;
            }
            taken.push(chord);
            false
        });
        taken
    })
}

impl LabApplication {
    pub(crate) fn capture_shortcut_numpad_event(&mut self, event: &WindowEvent) {
        if let WindowEvent::KeyboardInput { event, .. } = event
            && event.state == ElementState::Pressed
            && let winit::keyboard::PhysicalKey::Code(code) = event.physical_key
            && let Some(numpad) = NumpadKey::from_key_code(code)
            && let Some(key) = crate::shortcuts::numpad_egui_key(numpad, &event.logical_key)
        {
            self.shortcut_numpad_presses.push((key, numpad));
        }
    }

    /// The selection operation for a gesture starting now: held modifiers override the dropdown.
    pub(crate) fn held_selection_operation(&self) -> SelectionOperation {
        if !self.shortcuts_live {
            return self.selection_operation;
        }
        let modifiers = self.primary_press_modifiers;
        let held = |action| {
            self.shortcut_keymap
                .modifier(action)
                .is_some_and(|modifier: ModifierKey| modifier.held(modifiers))
        };
        if held(ShortcutAction::SubtractModifier) {
            SelectionOperation::Subtract
        } else if held(ShortcutAction::ExtendModifier) {
            if self.selection_tool == SelectionTool::Click {
                SelectionOperation::Toggle
            } else {
                SelectionOperation::Add
            }
        } else {
            self.selection_operation
        }
    }

    pub(crate) fn apply_shortcut_overrides(&mut self, overrides: Option<&Value>) {
        // A host that sends no shortcuts would not understand a shortcuts_changed event.
        self.shortcut_editor.persist = overrides.is_some_and(Value::is_object);
        self.shortcut_keymap =
            crate::shortcuts::Keymap::from_overrides(overrides.unwrap_or(&Value::Null));
    }

    fn publish_shortcuts(&mut self) {
        if !self.shortcut_editor.persist {
            return;
        }
        if let Some(bridge) = &self.cdmw_bridge
            && let Err(error) = bridge.publish_shortcuts(self.shortcut_keymap.overrides_value())
        {
            self.status = format!("Could not save keyboard shortcuts: {error}");
        }
    }

    /// `Move (G)` for icon tooltips that show only a name.
    pub(super) fn shortcut_named(&self, label: &str, action: Option<ShortcutAction>) -> String {
        match action.and_then(|action| self.shortcut_keymap.hint(action)) {
            Some(hint) => format!("{} ({hint})", crate::localization::tr(label)),
            None => crate::localization::tr(label),
        }
    }

    /// A tooltip line for text buttons, empty when the action is unbound.
    pub(super) fn shortcut_tooltip(&self, action: ShortcutAction) -> Option<String> {
        self.shortcut_keymap
            .hint(action)
            .map(|hint| crate::localization::tr(format!("Shortcut: {hint}")))
    }

    pub(crate) fn dispatch_cdmw_shortcuts(
        &mut self,
        context: &egui::Context,
        actions: &mut Vec<UiAction>,
    ) {
        let numpad = std::mem::take(&mut self.shortcut_numpad_presses);
        if self.shortcut_editor.capture.is_some() {
            self.capture_shortcut(context, numpad);
            return;
        }
        if context.egui_wants_keyboard_input()
            || egui::Popup::is_any_open(context)
            || self.cdmw_delete_guidance_open()
            || self.selection_gesture.is_some()
            || self.edit_gesture.is_some()
        {
            return;
        }
        let scope = if self.hair.active() {
            ShortcutScope::Hair
        } else {
            ShortcutScope::Mesh
        };
        let keymap = &self.shortcut_keymap;
        let chords = take_shortcut_presses(context, numpad, |chord| {
            keymap.action_for(chord, scope).is_some()
        });
        for chord in chords {
            if let Some(action) = self.shortcut_keymap.action_for(chord, scope) {
                self.run_shortcut(context, action, actions);
            }
        }
    }

    fn rail_page_refusal(&self, page: CdmwRailPage) -> Option<String> {
        if self.cdmw_show_busy_controls() {
            return Some("Wait for the current shadow operation".to_owned());
        }
        let requires_authoring =
            !matches!(page, CdmwRailPage::Select | CdmwRailPage::VertexParameters);
        if requires_authoring && !state_bool(&self.cdmw_state, "authoring_enabled") {
            return Some(
                state_str(&self.cdmw_state, "output_policy_reason")
                    .unwrap_or("Authoring is unavailable under the current output policy")
                    .to_owned(),
            );
        }
        if self.cdmw_morph_comparison_active()
            && !matches!(page, CdmwRailPage::Select | CdmwRailPage::MorphRefit)
        {
            return Some("Turn outfit corrections back on to continue editing.".to_owned());
        }
        None
    }

    fn open_cdmw_session_page(&self, context: &egui::Context, page: CdmwSidebarPage, reveal: &str) {
        if cdmw_sidebar_visible(context, CDMW_TOOLS_SIDEBAR) {
            context.data_mut(|data| data.insert_temp(egui::Id::new(reveal), true));
        } else {
            let mut settings = CdmwSidebarSettings::load(context);
            settings.show(page, context);
            settings.store(context);
        }
        context.request_repaint();
    }

    fn select_hair_tool(&mut self, tool: HairTool) {
        let Some(state) = self.hair.state.as_ref() else {
            return;
        };
        if state.converted {
            self.status = "Converted to ordinary mesh. Undo restores Hair editing.".to_owned();
            return;
        }
        let generated = state
            .groups
            .iter()
            .all(|group| group.mode == GroupMode::Generated);
        if !(self.hair_input_ready() || self.hair_draw_input_ready()) {
            self.status = "Wait for the current shadow operation".to_owned();
        } else if tool == HairTool::Guide && !generated {
            self.status = "Draw creates new cards in Create hairstyle. Existing hair preserves its original cards and UV layout.".to_owned();
        } else {
            self.hair.tool = Some(tool);
            self.cdmw_orbit_mode = false;
        }
    }

    fn run_shortcut(
        &mut self,
        context: &egui::Context,
        action: ShortcutAction,
        actions: &mut Vec<UiAction>,
    ) {
        use ShortcutAction as A;
        let busy = self.cdmw_show_busy_controls();
        let busy_reason = "Wait for the current shadow operation";
        if let Some(page) = rail_page(action) {
            match self.rail_page_refusal(page) {
                Some(reason) => self.status = reason,
                None => self.open_cdmw_tool_settings(context, page),
            }
            return;
        }
        if let Some(tool) = hair_tool(action) {
            self.select_hair_tool(tool);
            return;
        }
        let selected = self.selected_counts();
        match action {
            A::Orbit => actions.push(UiAction::OrbitMode),
            A::PageViewport => {
                self.open_cdmw_session_page(
                    context,
                    CdmwSidebarPage::Viewport,
                    CDMW_REVEAL_VIEWPORT,
                );
            }
            A::PageOutput => {
                self.open_cdmw_session_page(context, CdmwSidebarPage::Output, CDMW_REVEAL_OUTPUT);
            }
            A::TargetVertex => self.selection_domain = SelectionDomain::Vertex,
            A::TargetEdge => self.selection_domain = SelectionDomain::Edge,
            A::TargetFace => self.selection_domain = SelectionDomain::Face,
            A::ShapeClick | A::ShapeBrush | A::ShapeRectangle | A::ShapeLasso => {
                // Choosing a shape means selecting next, as when Blender starts box select.
                if let Some(reason) = self.rail_page_refusal(CdmwRailPage::Select) {
                    self.status = reason;
                    return;
                }
                self.selection_tool = match action {
                    A::ShapeClick => SelectionTool::Click,
                    A::ShapeBrush => SelectionTool::Brush,
                    A::ShapeRectangle => SelectionTool::Rectangle,
                    _ => SelectionTool::Lasso,
                };
                self.open_cdmw_tool_settings(context, CdmwRailPage::Select);
            }
            A::OperationReplace => self.selection_operation = SelectionOperation::Replace,
            A::OperationAdd => self.selection_operation = SelectionOperation::Add,
            A::OperationSubtract => self.selection_operation = SelectionOperation::Subtract,
            A::OperationToggle => self.selection_operation = SelectionOperation::Toggle,
            A::ToggleXRay => {
                self.selection_visible_only = !self.selection_visible_only;
                self.status = if self.selection_visible_only {
                    "Selection depth: Visible"
                } else {
                    "Selection depth: X-Ray"
                }
                .to_owned();
            }
            A::SelectAll | A::ClearSelection if busy => self.status = busy_reason.to_owned(),
            A::SelectAll => actions.push(match self.selection_domain {
                SelectionDomain::Vertex => UiAction::SelectAllVertices,
                SelectionDomain::Edge => UiAction::SelectAllEdges,
                SelectionDomain::Face => UiAction::SelectAllFaces,
            }),
            A::ClearSelection => actions.push(UiAction::ClearSelection),
            A::InvertSelection => {
                let has_selection = if self.hair.active() {
                    !self.hair.selected.is_empty()
                } else {
                    selected.total() > 0
                };
                if busy {
                    self.status = busy_reason.to_owned();
                } else if !has_selection {
                    self.status = "Select an element first".to_owned();
                } else {
                    actions.push(UiAction::InvertSelection(self.selection_domain));
                }
            }
            A::SelectLinked | A::GrowSelection | A::ShrinkSelection => {
                let domain = self.selection_domain;
                if selected.for_domain(domain) == 0 {
                    self.status = "Select an element first".to_owned();
                } else {
                    actions.push(match action {
                        A::SelectLinked => UiAction::SelectLinked(domain),
                        A::GrowSelection => UiAction::GrowSelection(domain),
                        _ => UiAction::ShrinkSelection(domain),
                    });
                }
            }
            A::FrameSelected => actions.push(
                if self
                    .mesh
                    .as_ref()
                    .is_some_and(|mesh| !mesh.selected_vertex_scope().is_empty())
                {
                    UiAction::FrameSelected
                } else {
                    UiAction::FrameAll
                },
            ),
            A::FrameAll => actions.push(UiAction::FrameAll),
            A::ViewFront => actions.push(UiAction::StandardView(StandardView::Front)),
            A::ViewBack => actions.push(UiAction::StandardView(StandardView::Back)),
            A::ViewRight => actions.push(UiAction::StandardView(StandardView::Right)),
            A::ViewLeft => actions.push(UiAction::StandardView(StandardView::Left)),
            A::ViewTop => actions.push(UiAction::StandardView(StandardView::Top)),
            A::ViewBottom => actions.push(UiAction::StandardView(StandardView::Bottom)),
            A::YawMinus15 => actions.push(UiAction::OrbitYaw(-15.0)),
            A::YawPlus15 => actions.push(UiAction::OrbitYaw(15.0)),
            A::Undo | A::Redo => {
                let undo = action == A::Undo;
                let available = state_u64(
                    &self.cdmw_state,
                    if undo { "undo_count" } else { "redo_count" },
                ) > 0;
                if busy {
                    self.status = busy_reason.to_owned();
                } else if !state_bool(&self.cdmw_state, "authoring_enabled") || !available {
                    self.status = if undo {
                        "No Mesh Editor action to undo"
                    } else {
                        "No Mesh Editor action to redo"
                    }
                    .to_owned();
                } else {
                    actions.push(if undo { UiAction::Undo } else { UiAction::Redo });
                }
            }
            A::DeleteSelection => self.cdmw_delete_selection(actions),
            A::HairDeleteGuides => {
                if self.hair.selected.is_empty() {
                    self.status = "Select an element first".to_owned();
                } else {
                    actions.push(UiAction::Hair(HairAction::DeleteGuides));
                }
            }
            A::ExtendModifier | A::SubtractModifier => {}
            _ => {}
        }
    }

    /// Escape returns to Orbit once nothing else used it. The gesture, text focus
    /// and popup state come from the start of the frame, before Escape closed them.
    pub(super) fn escape_to_orbit(
        &self,
        context: &egui::Context,
        escape_free: bool,
        actions: &mut Vec<UiAction>,
    ) {
        if escape_free
            && !self.hair.active()
            && self.cdmw_rail_page.is_some()
            && !egui::Popup::is_any_open(context)
            && context
                .input_mut(|input| input.consume_key(egui::Modifiers::NONE, egui::Key::Escape))
        {
            actions.push(UiAction::OrbitMode);
        }
    }

    fn capture_shortcut(&mut self, context: &egui::Context, numpad: Vec<(egui::Key, NumpadKey)>) {
        let Some((action, slot)) = self.shortcut_editor.capture else {
            return;
        };
        let chords = take_shortcut_presses(context, numpad, |_| true);
        let Some(chord) = chords.first().copied() else {
            return;
        };
        self.shortcut_editor.capture = None;
        if chord == KeyChord::new(ShortcutKey::Key(egui::Key::Escape), egui::Modifiers::NONE) {
            return;
        }
        if chord
            == KeyChord::new(
                ShortcutKey::Key(egui::Key::Backspace),
                egui::Modifiers::NONE,
            )
        {
            self.shortcut_keymap.clear_slot(action, slot);
            self.publish_shortcuts();
            return;
        }
        if let Some(reason) = chord.reserved_reason() {
            self.shortcut_editor.notice = Some(crate::localization::tr(match reason {
                ReservedChord::EditingKey => {
                    "This key is reserved for cancelling, text entry or focus."
                }
                ReservedChord::CloseWindow => "Alt+F4 closes the window.",
                ReservedChord::Clipboard => "Copy, cut and paste stay with text fields.",
            }));
            return;
        }
        self.assign_shortcut(action, slot, Binding::Chord(chord));
    }

    fn assign_shortcut(&mut self, action: ShortcutAction, slot: usize, binding: Binding) {
        self.shortcut_editor.notice =
            self.shortcut_keymap
                .assign(action, slot, binding)
                .map(|moved| {
                    crate::localization::tr(format!(
                        "{} was removed from {}",
                        moved.binding.text(),
                        crate::localization::tr(shortcut_label(moved.from))
                    ))
                });
        self.publish_shortcuts();
    }

    pub(super) fn draw_cdmw_shortcut_editor(&mut self, context: &egui::Context) {
        if !self.shortcut_editor.open {
            self.shortcut_editor.capture = None;
            return;
        }
        let mut open = true;
        egui::Window::new(crate::localization::tr("Keyboard Shortcuts"))
            .id(egui::Id::new("cdmw-keyboard-shortcuts"))
            .open(&mut open)
            .collapsible(false)
            .resizable(true)
            .default_size(egui::vec2(460.0, 520.0))
            .constrain_to(context.content_rect())
            .show(context, |ui| {
                ui.add(
                    egui::Label::new(crate::localization::tr(
                        "Click a shortcut, then press the new keys. Escape cancels and Backspace removes it. Keys work while the editor has focus; click the viewport first.",
                    ))
                    .wrap(),
                );
                ui.add(
                    egui::TextEdit::singleline(&mut self.shortcut_editor.filter)
                        .id(egui::Id::new("cdmw-shortcut-search"))
                        .hint_text(crate::localization::tr("Search"))
                        .desired_width(f32::INFINITY),
                );
                if let Some(notice) = &self.shortcut_editor.notice {
                    ui.add(egui::Label::new(notice.as_str()).wrap());
                }
                ui.separator();
                let footer = ui.spacing().interact_size.y + ui.spacing().item_spacing.y * 2.0;
                ScrollArea::vertical()
                    .max_height((ui.available_height() - footer).max(1.0))
                    .auto_shrink([false, true])
                    .show(ui, |ui| {
                        let columns = self.shortcut_columns(ui);
                        let mut drawn = false;
                        for group in SHORTCUT_GROUPS {
                            drawn |= self.draw_shortcut_group(ui, group, columns, drawn);
                        }
                    });
                ui.separator();
                if ui.button(crate::localization::tr("Reset All")).clicked() {
                    self.shortcut_keymap.reset_all();
                    self.shortcut_editor.capture = None;
                    self.shortcut_editor.notice = None;
                    self.publish_shortcuts();
                }
            });
        if !open {
            self.shortcut_editor.open = false;
            self.shortcut_editor.capture = None;
            self.shortcut_editor.notice = None;
        }
    }

    // One set of column widths for every group, so key buttons line up down the
    // whole window instead of per group, and labels truncate before keys move.
    fn shortcut_columns(&self, ui: &egui::Ui) -> [f32; 3] {
        let measure = |text: String, style: egui::TextStyle| {
            ui.painter()
                .layout_no_wrap(text, style.resolve(ui.style()), ui.visuals().text_color())
                .size()
                .x
        };
        let combo_icon = ui.spacing().icon_width + ui.spacing().icon_spacing;
        let mut binding = measure(
            crate::localization::tr("Press keys..."),
            egui::TextStyle::Button,
        )
        .max(
            measure(
                crate::localization::tr("Unassigned"),
                egui::TextStyle::Button,
            ) + combo_icon,
        );
        let mut label = 0.0_f32;
        for spec in SHORTCUTS {
            let text = crate::localization::tr(shortcut_label(spec.action));
            label = label.max(measure(text, egui::TextStyle::Body));
            for chord in self.shortcut_keymap.bindings(spec.action) {
                binding = binding.max(measure(chord.text(), egui::TextStyle::Button));
            }
        }
        let binding = (binding + ui.spacing().button_padding.x * 2.0).max(72.0);
        let reset = ui.spacing().interact_size.y;
        // The floating scroll bar draws over the right edge; keep reset clear of it.
        let scroll_bar = ui.spacing().scroll.bar_width + ui.spacing().scroll.bar_outer_margin;
        let keys = binding * crate::shortcuts::MAX_CHORDS as f32
            + reset
            + scroll_bar
            + ui.spacing().item_spacing.x * (crate::shortcuts::MAX_CHORDS + 1) as f32;
        [
            label.min(ui.available_width() - keys).max(48.0),
            binding,
            reset,
        ]
    }

    fn draw_shortcut_group(
        &mut self,
        ui: &mut egui::Ui,
        group: ShortcutGroup,
        [label_width, binding_width, reset_width]: [f32; 3],
        gap: bool,
    ) -> bool {
        let filter = self.shortcut_editor.filter.trim().to_lowercase();
        let rows = SHORTCUTS
            .iter()
            .filter(|spec| spec.group == group)
            .filter(|spec| {
                filter.is_empty()
                    || crate::localization::tr(shortcut_label(spec.action))
                        .to_lowercase()
                        .contains(&filter)
                    || self
                        .shortcut_keymap
                        .bindings(spec.action)
                        .iter()
                        .any(|binding| binding.text().to_lowercase().contains(&filter))
            })
            .collect::<Vec<_>>();
        if rows.is_empty() {
            return false;
        }
        if gap {
            ui.add_space(ui.spacing().item_spacing.y * 2.0);
        }
        ui.label(RichText::new(crate::localization::tr(group_label(group))).strong());
        let height = ui.spacing().interact_size.y;
        for (index, spec) in rows.into_iter().enumerate() {
            // The stripe is reserved before the row so it paints underneath, and it
            // spans the scroll width rather than the widgets' extent.
            let stripe = ui.painter().add(egui::Shape::Noop);
            let row = ui.push_id(spec.id, |ui| {
                ui.horizontal(|ui| {
                    cdmw_list_cell(ui, label_width, |ui| {
                        ui.add(
                            egui::Label::new(crate::localization::tr(shortcut_label(spec.action)))
                                .truncate(),
                        );
                    });
                    if spec.takes_modifier() {
                        cdmw_list_cell(ui, binding_width, |ui| {
                            self.draw_modifier_binding(ui, spec.action, binding_width);
                        });
                        for _ in 1..crate::shortcuts::MAX_CHORDS {
                            cdmw_list_cell(ui, binding_width, |_| {});
                        }
                    } else {
                        let bindings = self.shortcut_keymap.bindings(spec.action);
                        for slot in 0..crate::shortcuts::MAX_CHORDS {
                            let capturing =
                                self.shortcut_editor.capture == Some((spec.action, slot));
                            let text = if capturing {
                                crate::localization::tr("Press keys...")
                            } else if let Some(binding) = bindings.get(slot) {
                                binding.text()
                            } else if slot == bindings.len() && slot == 0 {
                                crate::localization::tr("Unassigned")
                            } else if slot == bindings.len() {
                                "+".to_owned()
                            } else {
                                cdmw_list_cell(ui, binding_width, |_| {});
                                continue;
                            };
                            let response = ui
                                .push_id(slot, |ui| {
                                    ui.add_sized(
                                        [binding_width, height],
                                        Button::new(text).selected(capturing).truncate(),
                                    )
                                })
                                .inner;
                            if response.clicked() {
                                self.shortcut_editor.capture = Some((spec.action, slot));
                                self.shortcut_editor.notice = None;
                            }
                        }
                    }
                    let default = self.shortcut_keymap.is_default(spec.action);
                    if ui
                        .push_id("reset", |ui| {
                            ui.add_enabled(
                                !default,
                                Button::new("↺").min_size(egui::vec2(reset_width, height)),
                            )
                            .on_hover_text(crate::localization::tr("Reset to default"))
                        })
                        .inner
                        .clicked()
                    {
                        self.shortcut_keymap.reset(spec.action);
                        self.publish_shortcuts();
                    }
                })
                .response
            });
            if index % 2 == 1 {
                let band = row
                    .inner
                    .rect
                    .expand2(egui::vec2(0.0, ui.spacing().item_spacing.y * 0.5));
                ui.painter().set(
                    stripe,
                    egui::epaint::RectShape::filled(
                        egui::Rect::from_x_y_ranges(ui.max_rect().x_range(), band.y_range()),
                        ui.visuals().widgets.noninteractive.corner_radius,
                        ui.visuals().faint_bg_color,
                    ),
                );
            }
        }
        true
    }

    fn draw_modifier_binding(&mut self, ui: &mut egui::Ui, action: ShortcutAction, width: f32) {
        let current = self.shortcut_keymap.modifier(action);
        let mut chosen = current;
        egui::ComboBox::from_id_salt((
            "cdmw-shortcut-modifier",
            crate::shortcuts::spec_for(action).id,
        ))
        .width(width)
        .selected_text(current.map_or_else(
            || crate::localization::tr("Unassigned"),
            |modifier| Binding::Modifier(modifier).text(),
        ))
        .show_ui(ui, |ui| {
            for modifier in [ModifierKey::Shift, ModifierKey::Ctrl, ModifierKey::Alt] {
                ui.selectable_value(
                    &mut chosen,
                    Some(modifier),
                    Binding::Modifier(modifier).text(),
                );
            }
            ui.selectable_value(&mut chosen, None, crate::localization::tr("Unassigned"));
        });
        if chosen != current {
            match chosen {
                Some(modifier) => self.assign_shortcut(action, 0, Binding::Modifier(modifier)),
                None => {
                    self.shortcut_keymap.clear_slot(action, 0);
                    self.publish_shortcuts();
                }
            }
        }
    }
}
