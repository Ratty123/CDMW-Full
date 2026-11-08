//! Cloth paint: mark which vertices of an imported model follow the template's cloth.
//!
//! The host owns the values (the per-vertex `cloth_paint` attribute, with Undo). This
//! view only shows them on the shared weight overlay and sends explicit selections.

use super::*;
use crate::cdmw_ui::{state_bool, state_str, state_u64};

/// Viewport brush that paints each finished stroke straight away.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum ClothBrush {
    Paint,
    Erase,
}

pub(super) struct ClothPaintView {
    /// Cloth amount the brush and Paint selection apply, 0 (bones) to 1 (cloth).
    pub amount: f64,
    pub brush: Option<ClothBrush>,
    pub show: bool,
    pub supported: bool,
    pub reason: String,
    pub painted: u64,
    weights: HashMap<(u32, u32), f32>,
    state: Value,
    overlay_key: Option<(u64, u64)>,
    visible: Option<HashSet<u32>>,
    pub positions: Vec<[f32; 3]>,
    pub colours: Vec<[f32; 4]>,
    /// The shared overlay currently shows this view's colours.
    pub uploaded: bool,
}

impl Default for ClothPaintView {
    fn default() -> Self {
        Self {
            amount: 1.0,
            brush: None,
            show: true,
            supported: false,
            reason: String::new(),
            painted: 0,
            weights: HashMap::new(),
            state: Value::Null,
            overlay_key: None,
            visible: None,
            positions: Vec::new(),
            colours: Vec::new(),
            uploaded: false,
        }
    }
}

impl ClothPaintView {
    pub fn update(&mut self, state: &Value) {
        let paint = state.get("cloth_paint").unwrap_or(&Value::Null);
        if &self.state == paint {
            return;
        }
        self.state = paint.clone();
        self.overlay_key = None;
        self.supported = state_bool(paint, "supported");
        self.reason = state_str(paint, "reason").unwrap_or("").to_owned();
        self.painted = state_u64(paint, "painted_vertex_count");
        self.weights = parse_paint(paint).unwrap_or_default();
    }

    pub fn prepare(&mut self, mesh: &WorkingMesh, visible: Option<HashSet<u32>>) {
        let key = (mesh.geometry_revision, mesh.topology_generation);
        if self.overlay_key == Some(key) && self.visible == visible && self.uploaded {
            return;
        }
        self.positions.clear();
        self.colours.clear();
        for (_, face) in mesh.faces() {
            if visible.as_ref().is_some_and(|shown| !shown.contains(&face.submesh)) {
                continue;
            }
            let vertices = face.vertices.map(|handle| mesh.vertex(handle));
            let [Some(a), Some(b), Some(c)] = vertices else {
                continue;
            };
            for vertex in [a, b, c] {
                let value = match vertex.provenance {
                    Provenance::Source { submesh, element } => {
                        self.weights.get(&(submesh, element)).copied().unwrap_or(0.0)
                    }
                    Provenance::Generated { .. } => 0.0,
                };
                self.positions.push(vertex.position);
                self.colours.push(paint_colour(value));
            }
        }
        self.overlay_key = Some(key);
        self.visible = visible;
        self.uploaded = false;
    }
}

/// Painted rows only: `{"parts": [{"submesh_index", "values": [[vertex, value]]}]}`.
fn parse_paint(value: &Value) -> Option<HashMap<(u32, u32), f32>> {
    let count = usize::try_from(value["painted_vertex_count"].as_u64()?).ok()?;
    if count > 262_144 {
        return None;
    }
    let mut result = HashMap::with_capacity(count);
    for part in value["parts"].as_array()? {
        let submesh = u32::try_from(part["submesh_index"].as_u64()?).ok()?;
        for row in part["values"].as_array()? {
            let row = row.as_array()?;
            if row.len() != 2 {
                return None;
            }
            let vertex = u32::try_from(row[0].as_u64()?).ok()?;
            let amount = row[1].as_f64()? as f32;
            if !amount.is_finite() || amount <= 0.0 || amount > 1.0
                || result.insert((submesh, vertex), amount).is_some()
            {
                return None;
            }
        }
    }
    (result.len() == count).then_some(result)
}

/// Unpainted vertices stay dark; cloth shows from teal to warm gold.
fn paint_colour(value: f32) -> [f32; 4] {
    let stops = [[0.10, 0.16, 0.24], [0.10, 0.68, 0.76], [1.0, 0.72, 0.18]];
    let t = value.clamp(0.0, 1.0) * 2.0;
    let start = usize::from(t > 1.0);
    let fraction = t - start as f32;
    let rgb: [f32; 3] = std::array::from_fn(|i| {
        stops[start][i] * (1.0 - fraction) + stops[start + 1][i] * fraction
    });
    [rgb[0], rgb[1], rgb[2], 0.86]
}

impl LabApplication {
    /// True while the Cloth page shows paint on the shared weight overlay.
    pub(super) fn cloth_paint_overlay_active(&self) -> bool {
        self.cdmw_rail_page == Some(CdmwRailPage::Cloth)
            && self.cdmw_cloth_paint.supported
            && self.cdmw_cloth_paint.show
    }

    /// The value a finished brush stroke paints, while the cloth brush is in use.
    pub(super) fn cloth_brush_value(&self) -> Option<f64> {
        let brush = self.cdmw_cloth_paint.brush?;
        (self.cdmw_cloth_paint.supported
            && self.cdmw_rail_page == Some(CdmwRailPage::Cloth)
            && self.viewport_tool == ViewportTool::Select
            && self.selection_tool == SelectionTool::Brush)
            .then_some(if brush == ClothBrush::Erase { 0.0 } else { self.cdmw_cloth_paint.amount })
    }

    /// Paint the vertices of the stroke just committed (the current selection).
    pub(super) fn submit_cloth_brush_stroke(&mut self, value: f64) {
        let label = if value > 0.0 { "Paint cloth" } else { "Erase cloth" };
        self.submit_cdmw_command("cloth_paint_set", json!({"value": value}), label);
    }

    pub(super) fn set_cloth_brush(&mut self, brush: Option<ClothBrush>) {
        self.cdmw_cloth_paint.brush = brush;
        if brush.is_some() {
            self.cancel_active_gesture("Cloth brush selected");
            self.viewport_tool = ViewportTool::Select;
            self.selection_tool = SelectionTool::Brush;
            self.selection_domain = SelectionDomain::Vertex;
            self.cdmw_orbit_mode = false;
            self.cdmw_cloth_paint.show = true;
        }
    }

    pub(super) fn draw_cdmw_cloth_paint(&mut self, ui: &mut egui::Ui, actions: &mut Vec<UiAction>) {
        if !self.cdmw_cloth_paint.supported {
            return;
        }
        // Another tool, or another selection mode, ends the cloth brush.
        if self.cdmw_cloth_paint.brush.is_some()
            && (self.viewport_tool != ViewportTool::Select || self.selection_tool != SelectionTool::Brush)
        {
            self.cdmw_cloth_paint.brush = None;
        }
        let can_paint = !self.cdmw_busy() && state_bool(&self.cdmw_state, "authoring_enabled");
        crate::localization::collapsing("Cloth paint (experimental)")
            .default_open(true)
            .show(ui, |ui| {
                ui.horizontal_wrapped(|ui| {
                    let brush = self.cdmw_cloth_paint.brush;
                    for (kind, label, tip) in [
                        (ClothBrush::Paint, "Brush", "Paint cloth by dragging over the model. Painted areas swing with the template's cloth."),
                        (ClothBrush::Erase, "Eraser", "Drag over the model to return painted areas to the bones."),
                    ] {
                        let on = brush == Some(kind);
                        if ui
                            .add_enabled(can_paint, egui::Button::new(crate::localization::tr(label)).selected(on))
                            .on_hover_text(crate::localization::tr(tip))
                            .clicked()
                        {
                            self.set_cloth_brush(if on { None } else { Some(kind) });
                        }
                    }
                });
                if self.cdmw_cloth_paint.brush.is_some() {
                    ui.add(
                        crate::cdmw_ui::numeric::slider(&mut self.brush_radius, 4.0..=240.0)
                            .text(crate::localization::tr("Brush size px")),
                    );
                }
                ui.add(
                    crate::cdmw_ui::numeric::slider(&mut self.cdmw_cloth_paint.amount, 0.0..=1.0)
                        .text(crate::localization::tr("Cloth amount")),
                )
                .on_hover_text(crate::localization::tr(
                    "0 follows the bones only, 1 swings fully with the cloth. Use lower values near seams and waistbands.",
                ));
                ui.horizontal_wrapped(|ui| {
                    if ui
                        .add_enabled(can_paint, egui::Button::new(crate::localization::tr("Paint whole model")))
                        .on_hover_text(crate::localization::tr(
                            "Paint every vertex with the cloth amount above, for a garment that moves as cloth all over.",
                        ))
                        .clicked()
                    {
                        actions.push(UiAction::CdmwCommand {
                            command: "cloth_paint_set",
                            arguments: json!({"value": self.cdmw_cloth_paint.amount, "whole_model": true}),
                            label: "Paint cloth",
                        });
                    }
                    if ui
                        .add_enabled(can_paint && self.cdmw_cloth_paint.painted > 0,
                            egui::Button::new(crate::localization::tr("Clear whole model")))
                        .on_hover_text(crate::localization::tr("Return every vertex to the bones."))
                        .clicked()
                    {
                        actions.push(UiAction::CdmwCommand {
                            command: "cloth_paint_set",
                            arguments: json!({"value": 0.0, "whole_model": true}),
                            label: "Clear cloth paint",
                        });
                    }
                });
                // Paint what is already selected (vertices, or whole Parts from the Parts list).
                let parts = self.selected_part_indices().into_iter().collect::<HashSet<_>>();
                let selected = self.mesh.as_ref().map_or(0, |mesh| {
                    let mut handles = mesh.selection.vertices.iter().copied().collect::<HashSet<_>>();
                    if !parts.is_empty() {
                        for (_, face) in mesh.faces() {
                            if parts.contains(&face.submesh) {
                                handles.extend(face.vertices);
                            }
                        }
                    }
                    handles.len()
                });
                if self.cdmw_cloth_paint.brush.is_none() && selected > 0 {
                    ui.horizontal_wrapped(|ui| {
                        if ui
                            .add_enabled(can_paint, egui::Button::new(crate::localization::tr("Paint selection")))
                            .clicked()
                        {
                            actions.push(UiAction::CdmwCommand {
                                command: "cloth_paint_set",
                                arguments: json!({"value": self.cdmw_cloth_paint.amount}),
                                label: "Paint cloth",
                            });
                        }
                        if ui
                            .add_enabled(can_paint, egui::Button::new(crate::localization::tr("Clear selection")))
                            .on_hover_text(crate::localization::tr("Return the selected vertices to the bones."))
                            .clicked()
                        {
                            actions.push(UiAction::CdmwCommand {
                                command: "cloth_paint_set",
                                arguments: json!({"value": 0.0}),
                                label: "Clear cloth paint",
                            });
                        }
                    });
                }
                ui.horizontal_wrapped(|ui| {
                    ui.checkbox(&mut self.cdmw_cloth_paint.show, crate::localization::tr("Show cloth paint"));
                    ui.small(crate::localization::tr(format!(
                        "{} painted vertices", self.cdmw_cloth_paint.painted
                    )));
                });
                if !self.cdmw_cloth_paint.reason.is_empty() {
                    ui.small(crate::localization::tr(self.cdmw_cloth_paint.reason.clone()));
                }
            });
        ui.separator();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn paint_rows_reject_duplicates_out_of_range_and_wrong_counts() {
        let good = json!({"painted_vertex_count": 2, "parts": [
            {"submesh_index": 0, "values": [[1, 0.5], [3, 1.0]]}]});
        assert_eq!(parse_paint(&good).unwrap().len(), 2);
        let mut duplicate = good.clone();
        duplicate["parts"][0]["values"][1][0] = json!(1);
        assert!(parse_paint(&duplicate).is_none());
        let mut over = good.clone();
        over["parts"][0]["values"][0][1] = json!(1.5);
        assert!(parse_paint(&over).is_none());
        let mut count = good.clone();
        count["painted_vertex_count"] = json!(3);
        assert!(parse_paint(&count).is_none());
    }

    #[test]
    fn update_follows_support_and_resets_on_new_state() {
        let mut view = ClothPaintView::default();
        view.update(&json!({"cloth_paint": {"supported": true, "painted_vertex_count": 1,
            "parts": [{"submesh_index": 2, "values": [[0, 1.0]]}]}}));
        assert!(view.supported && view.painted == 1 && view.weights.len() == 1);
        view.update(&json!({"cloth_paint": {"supported": false, "reason": "Game model"}}));
        assert!(!view.supported && view.weights.is_empty() && view.reason == "Game model");
    }
}
