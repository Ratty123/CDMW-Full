//! Viewport diagnostics and fit refusal guidance. Never changes a fit.
use super::*;

const REFIT_WARNING_COLOUR: [f32; 4] = [1.0, 0.35, 0.06, 0.45];
const PART_HOVER_COLOUR: [f32; 4] = [0.15, 0.85, 1.0, 0.65];

fn refit_failure_parts(detail: &str, garments: &[u32]) -> Vec<u32> {
    let mut parts = Vec::new();
    for prefix in ["Part ", "Parts "] {
        for tail in detail.split(prefix).skip(1) {
            let numbers: String = tail.chars().take_while(|c| c.is_ascii_digit()
                || (prefix == "Parts " && matches!(c, ',' | ' '))).collect();
            for part in numbers.split(|c: char| !c.is_ascii_digit()).filter_map(|s| s.parse::<u32>().ok()) {
                if garments.contains(&part) && !parts.contains(&part) {
                    parts.push(part);
                }
            }
        }
    }
    parts
}

impl LabApplication {
    pub(super) fn draw_cdmw_part_hover_option(&self, ui: &mut egui::Ui) {
        let mut enabled = crate::cdmw_layout::auto_open_parts_on_hover(ui.ctx());
        if ui.checkbox(&mut enabled, crate::localization::tr("Open Parts on hover"))
            .on_hover_text(crate::localization::tr("Open the Parts list when hovering a visible surface. Turn off to keep closed panels closed."))
            .changed()
        {
            crate::cdmw_layout::set_auto_open_parts_on_hover(ui.ctx(), enabled);
        }
    }

    pub(super) fn track_cdmw_part_hover(&mut self, ui: &egui::Ui, part: u32, response: &egui::Response) {
        let row = PartNameRow { part, response: response.clone(), clip_rect: ui.clip_rect(),
            scroll_root: ui.stack().iter().find(|entry| entry.kind() == Some(egui::UiKind::ScrollArea)).map(|entry| entry.id) };
        let pending = self.cdmw_part_name_scroll.as_ref()
            .filter(|scroll| scroll.part == part && scroll.targets.contains(&response.id))
            .map(|scroll| scroll.viewport_layer);
        if let Some(layer) = pending {
            if self.cdmw_part_scroll_is_current(&response.ctx, part, layer) {
                self.cdmw_part_name_scroll.as_mut().unwrap().targets.remove(&response.id);
                if !row.fully_visible() {
                    // Run inside the row's scroll area, so another pane cannot
                    // consume this request after the viewport is drawn.
                    response.scroll_to_me_animation(None, egui::style::ScrollAnimation::none());
                    response.ctx.request_repaint();
                }
            } else {
                self.cdmw_part_name_scroll = None;
            }
        }
        self.cdmw_part_name_rows.push(row);
        if response.hovered() && response.ctx.input(|input| input.pointer.hover_pos().is_some()) {
            self.cdmw_hovered_part = Some(part);
        }
    }

    fn cdmw_viewport_part_hover_allowed(&self, context: &egui::Context) -> bool {
        !self.hair.active() && self.cdmw_jiggle.preview.scene.is_none() && !self.cdmw_morph_comparison_active()
            && self.cdmw_state["replacement"]["comparison"].as_str().is_none_or(|mode| mode == "edit")
            && !context.input(|input| input.pointer.any_down()) && !context.any_popup_open()
    }

    fn cdmw_part_scroll_is_current(&self, context: &egui::Context, part: u32, layer: egui::LayerId) -> bool {
        let Some(point) = context.pointer_hover_pos().filter(|_| self.cdmw_viewport_part_hover_allowed(context)) else { return false; };
        let Some(rectangle) = self.viewport_rect.filter(|rect| rect.contains(point)) else { return false; };
        if context.layer_id_at(point) != Some(layer) { return false; }
        let visible = self.cdmw_visible_submeshes();
        self.mesh.as_ref().zip(self.projection.as_ref()).is_some_and(|(mesh, projection)| {
            let current = visible.as_ref().map_or_else(
                || projection.matches(mesh, &self.camera, rectangle, self.viewport_revision),
                |parts| projection.matches_for_submeshes(mesh, &self.camera, rectangle, self.viewport_revision, parts));
            current && projection.part_at(Vec2::new(point.x, point.y)) == Some(part)
        })
    }

    fn queue_cdmw_part_name_scroll(&mut self, part: u32, layer: egui::LayerId) {
        if self.cdmw_part_name_scroll.as_ref().is_some_and(|scroll|
            scroll.part == part && scroll.viewport_revision == self.viewport_revision)
        { return; }
        // One name per scroll area: keep an already visible match, otherwise
        // reveal the closest match when the same Part occurs in several sections.
        let mut roots = HashMap::<egui::Id, (bool, f32, egui::Id)>::new();
        for row in self.cdmw_part_name_rows.iter().filter(|row| row.part == part && row.clip_rect.is_positive()) {
            let Some(root) = row.scroll_root else { continue; };
            let distance = (row.response.rect.top() - row.clip_rect.bottom())
                .max(row.clip_rect.top() - row.response.rect.bottom()).max(0.0);
            roots.entry(root).and_modify(|entry| {
                entry.0 |= row.fully_visible();
                if distance < entry.1 { entry.1 = distance; entry.2 = row.response.id; }
            }).or_insert((row.fully_visible(), distance, row.response.id));
        }
        let targets: HashSet<_> = roots.values().filter(|entry| !entry.0).map(|entry| entry.2).collect();
        if !targets.is_empty() { self.egui_context.request_repaint(); }
        self.cdmw_part_name_scroll = Some(PartNameScroll { part, targets, viewport_layer: layer,
            viewport_revision: self.viewport_revision });
    }

    pub(super) fn highlight_cdmw_part_names_from_viewport(
        &mut self, ui: &egui::Ui, rectangle: egui::Rect, response: &egui::Response,
    ) {
        if !response.hovered() || !self.cdmw_viewport_part_hover_allowed(ui.ctx()) {
            self.cdmw_part_name_scroll = None;
            return;
        }
        let Some(point) = ui.input(|input| input.pointer.hover_pos()).filter(|point| rectangle.contains(*point)) else {
            self.cdmw_part_name_scroll = None;
            return;
        };
        if !self.ensure_projection(rectangle) { self.cdmw_part_name_scroll = None; return; }
        let part = self.projection.as_ref().and_then(|projection| projection.part_at(Vec2::new(point.x, point.y)));
        self.cdmw_viewport_hovered_part = part;
        let Some(part) = part else { self.cdmw_part_name_scroll = None; return; };
        let panel_id = egui::Id::new("cdmw_parts_panel_open");
        let tab_id = egui::Id::new("cdmw_parts_panel_islands");
        let parts_closed = !cdmw_sidebar_visible(ui.ctx(), CDMW_INSPECTOR_SIDEBAR)
            || ui.ctx().data_mut(|data| !data.get_temp::<bool>(panel_id).unwrap_or(false)
                || data.get_temp::<bool>(tab_id).unwrap_or(false));
        if parts_closed && crate::cdmw_layout::auto_open_parts_on_hover(ui.ctx()) {
            set_cdmw_sidebar_expanded(ui.ctx(), CDMW_INSPECTOR_SIDEBAR, true);
            ui.ctx().data_mut(|data| {
                data.insert_temp(panel_id, true);
                data.insert_temp(tab_id, false);
            });
            // The Inspector is drawn before the viewport. Plan scrolling once
            // its newly opened Parts rows exist on the next frame.
            self.cdmw_part_name_scroll = None;
        } else {
            self.queue_cdmw_part_name_scroll(part, response.layer_id);
        }
        let [r, g, b, _] = PART_HOVER_COLOUR;
        let colour = Color32::from(egui::Rgba::from_rgb(r, g, b));
        // Paint an identification cue on this frame's clipped name rows. Their
        // checkbox/button state and the retained viewport selection stay intact.
        for row in self.cdmw_part_name_rows.iter().filter(|row| row.part == part && row.response.interact_rect.is_positive()) {
            let rect = row.response.interact_rect;
            ui.ctx().layer_painter(row.response.layer_id).with_clip_rect(rect).rect_stroke(
                rect.shrink(0.5), 3.0, Stroke::new(2.0, colour), egui::StrokeKind::Inside);
        }
    }

    pub(crate) fn invalidate_cdmw_part_hover_overlay(&mut self) {
        if self.cdmw_part_hover_overlay.take().is_some()
            && let Some(renderer) = &mut self.renderer
        {
            let _ = renderer.set_part_hover(&[], PART_HOVER_COLOUR);
        }
    }

    pub(crate) fn refresh_cdmw_part_hover_overlay(&mut self) {
        let part = self.cdmw_hovered_part.filter(|_| self.cdmw_mode() && !self.hair.active()
            && self.cdmw_jiggle.preview.scene.is_none() && !self.cdmw_morph_comparison_active()
            && self.cdmw_state["replacement"]["comparison"].as_str().is_none_or(|mode| mode == "edit"));
        let Some((part, mesh)) = part.zip(self.mesh.as_ref()) else {
            self.invalidate_cdmw_part_hover_overlay();
            return;
        };
        let visible = self.cdmw_visible_submeshes();
        if self.cdmw_part_hover_overlay.as_ref().is_none_or(|(cached_part, overlay)|
            *cached_part != part || !overlay.matches(mesh, &visible, PART_HOVER_COLOUR))
        {
            self.cdmw_part_hover_overlay = Some((part,
                FaceSelectionOverlay::build_for_parts(mesh, visible, PART_HOVER_COLOUR, &[part])));
        }
        if let (Some(renderer), Some((_, overlay))) = (&mut self.renderer, &mut self.cdmw_part_hover_overlay)
            && !overlay.uploaded
        {
            match renderer.set_part_hover(&overlay.positions, PART_HOVER_COLOUR) {
                Ok(()) => overlay.uploaded = true,
                Err(error) => self.status = format!("Part highlight failed: {error}"),
            }
        }
    }

    pub(super) fn cdmw_part_name_atoms<'a>(&self, part: u32, label: impl egui::IntoAtoms<'a>) -> egui::Atoms<'a> {
        let mut atoms = egui::Atoms::new(label);
        if self.cdmw_part_colours_active() {
            let [r, g, b, _] = viewport::part_colour(part);
            let colour = Color32::from(egui::Rgba::from_rgb(r, g, b));
            // The GUI atlas white pixel gives the badge a solid fill without an extra texture.
            let white = egui::epaint::WHITE_UV;
            atoms.push_left(egui::Image::new((egui::TextureId::default(), egui::vec2(10.0, 10.0)))
                .uv(egui::Rect::from_min_max(white, white)).tint(colour));
        }
        atoms
    }

    pub(crate) fn refresh_cdmw_mesh_display(&mut self) {
        let visible_submeshes = self.cdmw_visible_submeshes();
        let snapshot = self.mesh.as_ref().map(|mesh| {
            visible_submeshes.as_ref().map_or_else(
                || mesh.draw_snapshot(),
                |visible| mesh.draw_snapshot_for_submeshes(visible),
            )
        });
        let part_colours = if self.cdmw_part_colours_active() {
            self.mesh.as_ref().zip(snapshot.as_ref()).map(|(mesh, snapshot)|
                viewport::part_colour_snapshot(mesh, visible_submeshes.as_ref(), snapshot))
        } else { None };
        self.cdmw_part_colours_applied = self.cdmw_part_colours_active();
        let deformation_reference = snapshot.as_ref().filter(|_| part_colours.is_none()).and_then(|snapshot| {
            deformation_reference_for_snapshot(
                self.deformation_heatmap_enabled,
                self.deformation_reference.as_mut(),
                visible_submeshes.as_ref(),
                snapshot,
            )
        });
        if let (Some(renderer), Some(snapshot)) = (&mut self.renderer, snapshot)
            && let Err(error) = if let Some(colours) = &self.cdmw_jiggle.region_colours {
                renderer.set_snapshot_with_vertex_colours(&snapshot, colours)
            } else if let Some(colours) = &part_colours {
                renderer.set_snapshot_with_vertex_colours(&snapshot, colours)
            } else if self.edit_gesture.is_some() {
                renderer.set_snapshot_with_deformation_interactive(&snapshot, deformation_reference)
            } else {
                renderer.set_snapshot_with_deformation(&snapshot, deformation_reference)
            }
        {
            self.status = format!("GPU update failed: {error}");
        }
    }

    pub(crate) fn cdmw_part_colours_active(&self) -> bool {
        self.cdmw_mode() && self.view_mode == ViewMode::PartId && !self.hair.active()
            && self.cdmw_jiggle.region_colours.is_none() && self.cdmw_jiggle.preview.scene.is_none()
    }

    pub(super) fn set_cdmw_display_mode(&mut self, mode: ViewMode) {
        let was_coloured = self.view_mode == ViewMode::PartId;
        if mode == ViewMode::PartId && !was_coloured {
            self.cdmw_part_colours_previous_mode = self.view_mode;
        }
        self.view_mode = mode;
        if was_coloured != (mode == ViewMode::PartId) {
            self.refresh_cdmw_mesh_display();
        }
    }

    fn cdmw_refit_preview_revision(&self) -> (Option<u64>, Option<u64>, usize) {
        (self.cdmw_state["base_revision"].as_u64(),
            self.cdmw_state.pointer("/morph_refit/state_revision").and_then(Value::as_u64),
            self.active_lod_index)
    }

    pub(crate) fn cdmw_refit_feedback_is_current(&self) -> bool {
        self.cdmw_refit_feedback.as_ref().is_some_and(|feedback|
            feedback.preview_revision == self.cdmw_refit_preview_revision())
    }

    pub(crate) fn record_cdmw_refit_feedback(&mut self, label: &str, ok: bool, error: &str, retain_for_selection: bool) {
        let fitting = matches!(label, "Fit to body" | "Apply garment refit settings"
            | "Apply island refit settings" | "Inherit Part fitting settings");
        if !ok && (error.contains("Fit to body:") || error.contains("clearance displacement solve did not converge")) {
            self.cdmw_refit_feedback = Some(RefitFeedback { detail: error.trim().to_owned(), reveal: true,
                preview_revision: self.cdmw_refit_preview_revision(), highlight: true, overlay: None });
        } else if (ok && (fitting || matches!(label, "Reset morph" | "Bake morph" | "Clear refit")))
            || (!ok && fitting)
        {
            self.cdmw_refit_feedback = None;
        } else if ok && retain_for_selection {
            let current = self.cdmw_refit_preview_revision();
            if let Some(feedback) = &mut self.cdmw_refit_feedback
                && feedback.preview_revision.2 == current.2
            {
                // A validated selection advances both protocol and morph snapshot
                // watermarks without changing the retained fit.
                feedback.preview_revision = current;
            }
        }
    }

    pub(crate) fn invalidate_cdmw_refit_overlay(&mut self) {
        if let Some(feedback) = &mut self.cdmw_refit_feedback { feedback.overlay = None; }
        if let Some(renderer) = &mut self.renderer {
            let _ = renderer.set_refit_warning(&[], REFIT_WARNING_COLOUR);
        }
    }

    pub(crate) fn cdmw_refit_highlight_parts(&self) -> Vec<u32> {
        let active = self.cdmw_refit_feedback.as_ref().is_some_and(|feedback|
            feedback.highlight && feedback.preview_revision == self.cdmw_refit_preview_revision())
            && !self.hair.active() && !self.cdmw_morph_comparison_active()
            && self.cdmw_state["replacement"]["comparison"].as_str().is_none_or(|mode| mode == "edit");
        if !active || self.mesh.is_none() { return Vec::new(); }
        let garments = value_u32_list(&self.cdmw_state["morph_refit"]["refit"], "garment_submesh_indices");
        refit_failure_parts(&self.cdmw_refit_feedback.as_ref().unwrap().detail, &garments)
    }

    pub(crate) fn refresh_cdmw_refit_overlay(&mut self) {
        let parts = self.cdmw_refit_highlight_parts();
        let Some(mesh) = self.mesh.as_ref().filter(|_| !parts.is_empty()) else {
            self.invalidate_cdmw_refit_overlay();
            return;
        };
        let visible = self.cdmw_visible_submeshes();
        let feedback = self.cdmw_refit_feedback.as_mut().unwrap();
        if feedback.overlay.as_ref().is_none_or(|overlay| !overlay.matches(mesh, &visible, REFIT_WARNING_COLOUR)) {
            feedback.overlay = Some(FaceSelectionOverlay::build_for_parts(mesh, visible, REFIT_WARNING_COLOUR, &parts));
        }
        if let (Some(renderer), Some(overlay)) = (&mut self.renderer, &mut feedback.overlay)
            && !overlay.uploaded
        {
            match renderer.set_refit_warning(&overlay.positions, REFIT_WARNING_COLOUR) {
                Ok(()) => overlay.uploaded = true,
                Err(error) => self.status = format!("Fit highlight failed: {error}"),
            }
        }
    }

    fn select_cdmw_refit_feedback_parts(actions: &mut Vec<UiAction>, parts: Vec<u32>) {
        actions.push(UiAction::SetPartVisibility { indices: parts.clone(), visible: true });
        actions.push(UiAction::SetPartSelection(parts));
    }

    pub(super) fn draw_cdmw_refit_feedback(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>, garments: &[u32]) {
        if self.cdmw_refit_feedback.as_ref().is_some_and(|feedback|
            feedback.preview_revision != self.cdmw_refit_preview_revision())
        {
            self.cdmw_refit_feedback = None;
        }
        let Some(feedback) = self.cdmw_refit_feedback.as_mut() else { return; };
        let reveal = std::mem::take(&mut feedback.reveal);
        let detail = feedback.detail.clone();
        let mut highlight = feedback.highlight;
        let parts = refit_failure_parts(&detail, garments);
        let refit = &self.cdmw_state["morph_refit"]["refit"];
        let settings = refit["garment_settings"].as_array().into_iter().flatten().filter(|row| {
            row["submesh_index"].as_u64().is_some_and(|part| parts.is_empty()
                || parts.iter().any(|index| u64::from(*index) == part))
        }).collect::<Vec<_>>();
        let zero_clearance = settings.iter().any(|row| row["clearance_percent"].as_f64() == Some(0.0)
            || row["island_settings"].as_array().into_iter().flatten()
                .any(|island| island["clearance_percent"].as_f64() == Some(0.0)));
        let protected = settings.iter().any(|row| row["has_vertex_mask"].as_bool() == Some(true));
        let (reason, hint) = if protected && detail.contains("protection mask") {
            ("Garment intersects the body.", "Reduce local protection or adjust the garment position, then retry.")
        } else if detail.contains("rigid assembly") || detail.contains("rigid component") {
            ("Rigid pieces cannot move clear.", "Check the garment size and position, then retry.")
        } else if detail.contains("triangle") && !detail.contains("beneath its triangles")
            || detail.contains("crosses its own surface")
        {
            ("Fitting would fold or damage the mesh.", "Lower Tightness, then Apply. Keep loose trim at 0%.")
        } else {
            let reason = if detail.contains("Part ") && (detail.contains("cannot clear Part ")
                || detail.contains("still intersects Part ") || detail.contains("layer separation"))
            {
                "Garment layers overlap."
            } else if detail.contains("body") && detail.contains("cannot clear") {
                "Garment intersects the body."
            } else {
                "Fit could not find a safe shape."
            };
            (reason, if zero_clearance {
                "Try 0.1% Clearance or lower Tightness, then Apply."
            } else {
                "Increase Clearance or lower Tightness, then Apply."
            })
        };
        let response = egui::Frame::group(ui.style()).show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.colored_label(cdmw_readable(ui, REFIT_ARMOR_COLOUR), crate::localization::tr("Fit blocked · preview kept"));
            if !parts.is_empty() {
                let selected_parts = self.selected_part_indices();
                let can_select = !self.cdmw_busy();
                ui.horizontal_wrapped(|ui| {
                    for part in &parts {
                        let row = ui.add_enabled(can_select, Button::new(self.cdmw_part_name_atoms(*part, self.cdmw_morph_part_names(&[*part]))).small()
                            .selected(selected_parts.contains(part)));
                        self.track_cdmw_part_hover(ui, *part, &row);
                        if row
                            .on_hover_text(crate::localization::tr("Select these Parts to adjust their fitting. Hidden Parts are shown."))
                            .clicked()
                        {
                            Self::select_cdmw_refit_feedback_parts(actions, vec![*part]);
                        }
                    }
                });
                ui.checkbox(&mut highlight, crate::localization::tr("Highlight in viewport"))
                    .on_hover_text(crate::localization::tr("Highlights the affected garments on the retained preview, including obscured areas."));
                if ui.add_enabled(can_select, Button::new(crate::localization::tr("Select affected parts")))
                    .on_hover_text(crate::localization::tr("Select these Parts to adjust their fitting. Hidden Parts are shown."))
                    .clicked()
                {
                    Self::select_cdmw_refit_feedback_parts(actions, parts.clone());
                }
            }
            ui.add(egui::Label::new(crate::localization::tr(reason)).wrap());
            ui.add(egui::Label::new(crate::localization::tr(hint)).wrap());
            crate::localization::collapsing("Fit details").id_salt("refit-failure-details").show(ui, |ui| {
                ui.add(egui::Label::new(&detail).wrap().selectable(true));
            });
        }).response;
        if let Some(feedback) = &mut self.cdmw_refit_feedback { feedback.highlight = highlight; }
        if reveal { response.scroll_to_me(Some(egui::Align::Center)); }
    }
}

fn diagnostic_number(value: Option<&Value>) -> String {
    value.and_then(Value::as_f64).filter(|number| number.is_finite())
        .map_or_else(|| crate::localization::tr("Unavailable"), |number| format!("{number:.6}"))
}

fn diagnostic_count(value: Option<&Value>) -> String {
    value.and_then(Value::as_u64)
        .map_or_else(|| "?".to_owned(), |number| number.to_string())
}

fn diagnostic_indices(value: Option<&Value>) -> Option<Vec<u32>> {
    let mut indices = value?.as_array()?.iter()
        .map(|index| u32::try_from(index.as_u64()?).ok())
        .collect::<Option<Vec<_>>>()?;
    indices.sort_unstable();
    indices.dedup();
    Some(indices)
}

fn diagnostic_report_current(report: &Value, state: &Value, shadow_revision: Option<u64>, targets: &[u32]) -> bool {
    let host_morph_revision = state.get("state_revision").and_then(Value::as_u64);
    let mut expected_targets = targets.to_vec();
    expected_targets.sort_unstable();
    expected_targets.dedup();
    host_morph_revision.is_some()
        && shadow_revision.is_some()
        // The host's Morph & Refit watermark can differ from the native
        // solver revision retained in report.state_revision.
        && report.get("host_morph_revision").and_then(Value::as_u64) == host_morph_revision
        && report.get("shadow_revision").and_then(Value::as_u64) == shadow_revision
        && diagnostic_indices(report.get("requested_submesh_indices")) == Some(expected_targets)
}

fn diagnostic_reason(ui: &mut egui::Ui, report: &Value) {
    if let Some(reason) = report.get("reason").and_then(Value::as_str).filter(|reason| !reason.trim().is_empty()) {
        ui.weak(reason);
    }
}

fn diagnostic_sample_label(sample: &Value) -> String {
    let part = diagnostic_count(sample.get("submesh_index"));
    let vertices = diagnostic_indices(sample.get("vertex_indices")).unwrap_or_default();
    if vertices.is_empty() {
        return format!("{} {part}", crate::localization::tr("Part"));
    }
    let label = crate::localization::tr(if vertices.len() == 1 { "vertex" } else { "vertices" });
    format!("{} {part}, {label} {}", crate::localization::tr("Part"),
        vertices.iter().take(3).map(u32::to_string).collect::<Vec<_>>().join(", "))
}

impl LabApplication {
    pub(super) fn draw_cdmw_refit_diagnostics(
        &mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>, state: &Value, targets: &[u32],
    ) {
        ui.separator();
        ui.strong(crate::localization::tr("Current fit diagnostics"));
        let mut scope = targets.to_vec();
        scope.sort_unstable();
        scope.dedup();
        if ui.add_enabled(!self.cdmw_busy() && !scope.is_empty(),
            Button::new(crate::localization::tr("Analyze current fit")))
            .on_hover_text(crate::localization::tr("Inspect the selected bound garments, or all bound garments when none are selected. Uses the current preview without applying pending settings."))
            .clicked()
        {
            actions.push(UiAction::CdmwCommand {
                command: "refit_diagnostics",
                arguments: json!({"submesh_indices": scope, "sample_limit": 2048, "detail_limit": 24}),
                label: "Analyze current fit",
            });
        }
        let Some(report) = self.cdmw_refit_diagnostics.as_ref() else {
            ui.weak(crate::localization::tr("Analyze the current preview to measure body clearance and garment layer spacing."));
            return;
        };
        if !diagnostic_report_current(report, state,
            self.cdmw_state.get("base_revision").and_then(Value::as_u64), targets)
        {
            ui.weak(crate::localization::tr("Fit analysis is out of date for this preview or selection. Analyze again."));
            return;
        }

        ui.weak(crate::localization::tr("Sampled geometry in model units. These measurements do not prove the whole mesh is collision-free."));
        ui.label(format!("{} {} / {}", crate::localization::tr("Samples:"),
            diagnostic_count(report.get("planned_sample_count")),
            diagnostic_count(report.get("candidate_sample_count"))));
        match report.get("status").and_then(Value::as_str) {
            Some("partial") => { ui.weak(crate::localization::tr("Partial analysis")); }
            Some("unavailable") => { ui.weak(crate::localization::tr("Analysis unavailable")); }
            _ => {}
        }
        diagnostic_reason(ui, report);

        let body = &report["body_clearance"];
        if body.get("available").and_then(Value::as_bool) == Some(true) {
            ui.label(format!("{} {}", crate::localization::tr("Minimum body distance:"),
                diagnostic_number(body.get("minimum_distance"))));
            ui.label(format!("{} {}", crate::localization::tr("Local normal offset:"),
                diagnostic_number(body.get("minimum_normal_offset"))));
            ui.weak(crate::localization::tr("Normal offset uses the nearest face orientation. It does not determine whether a point is inside the body."));
            ui.weak(format!("{} {}", crate::localization::tr("Body samples evaluated:"),
                diagnostic_count(body.get("evaluated_sample_count"))));
        } else {
            ui.weak(crate::localization::tr("Body clearance unavailable"));
            diagnostic_reason(ui, body);
        }

        let layers = &report["layer_spacing"];
        if layers.get("available").and_then(Value::as_bool) == Some(true) {
            ui.label(format!("{} {}", crate::localization::tr("Minimum layer gap:"),
                diagnostic_number(layers.get("minimum_current_gap"))));
            let retained = layers.get("minimum_retained_ratio").and_then(Value::as_f64)
                .filter(|ratio| ratio.is_finite())
                .map_or_else(|| crate::localization::tr("Unavailable"), |ratio| format!("{:.1}%", ratio * 100.0));
            ui.label(format!("{} {retained}", crate::localization::tr("Minimum authored gap retained:")));
            ui.weak(format!("{} {}", crate::localization::tr("Layer samples evaluated:"),
                diagnostic_count(layers.get("evaluated_sample_count"))));
        } else {
            ui.weak(crate::localization::tr("Layer spacing unavailable"));
        }
        diagnostic_reason(ui, layers);
        if let Some(ambiguous) = layers.get("ambiguous_candidate_count").and_then(Value::as_u64).filter(|count| *count > 0) {
            ui.weak(format!("{} {ambiguous}", crate::localization::tr("Ambiguous layer candidates omitted:")));
        }

        let mut parts = report.get("parts").and_then(Value::as_array).into_iter().flatten()
            .filter(|part| part.get("minimum_distance").and_then(Value::as_f64).is_some_and(f64::is_finite))
            .collect::<Vec<_>>();
        parts.sort_by(|a, b| a["minimum_distance"].as_f64().unwrap().total_cmp(&b["minimum_distance"].as_f64().unwrap()));
        let mut details = layers.get("details").and_then(Value::as_array).into_iter().flatten()
            .filter(|detail| detail.get("retained_ratio").and_then(Value::as_f64).is_some_and(f64::is_finite))
            .collect::<Vec<_>>();
        details.sort_by(|a, b| a["retained_ratio"].as_f64().unwrap().total_cmp(&b["retained_ratio"].as_f64().unwrap()));
        if !parts.is_empty() || !details.is_empty() {
            crate::localization::collapsing("Lowest sampled gaps")
                .id_salt("refit-diagnostic-locations").show(ui, |ui| {
                    for part in parts.iter().take(3) {
                        let sample = part.get("minimum_distance_sample").unwrap_or(part);
                        ui.label(format!("{}: {} {}", diagnostic_sample_label(sample),
                            crate::localization::tr("body distance"), diagnostic_number(part.get("minimum_distance"))));
                        if part.get("has_influence_mask").and_then(Value::as_bool) == Some(true) {
                            ui.weak(crate::localization::tr("An influence mask is configured for this Part."));
                        }
                    }
                    for detail in details.iter().take(3) {
                        ui.label(format!("{} → {} {}: {} {}", diagnostic_sample_label(&detail["sample"]),
                            crate::localization::tr("Part"), diagnostic_count(detail.get("target_submesh_index")),
                            crate::localization::tr("layer gap"), diagnostic_number(detail.get("current_gap"))));
                    }
                    if parts.len() > 3 || details.len() > 3
                        || layers.get("details_truncated").and_then(Value::as_bool) == Some(true)
                    {
                        ui.weak(crate::localization::tr("Additional sample locations omitted."));
                    }
                });
        }
    }
}
