//! Bend's selection, two-point interaction and viewport handles.
use super::*;
use cdmw_interaction::bend::{BendRegion, BendStroke};

impl LabApplication {
    fn bend_anchor_valid(&self) -> bool {
        self.bend_anchor
            .as_ref()
            .zip(self.mesh.as_ref())
            .is_some_and(|(anchor, mesh)| anchor.matches(mesh))
    }

    pub(super) fn draw_bend_settings(&mut self, ui: &mut egui::Ui) {
        let selected = self
            .mesh
            .as_ref()
            .is_some_and(|mesh| !mesh.selected_vertex_scope().is_empty());
        let anchored = self.bend_anchor_valid();
        ui.label(crate::localization::tr(if !selected {
            "Select the whole rope Part or island first."
        } else if anchored {
            "1 anchored: drag 2 to bend"
        } else {
            "Click 1 to anchor, then drag 2."
        })).on_hover_text(crate::localization::tr(
            "Select the whole rope, including its back side; use X-Ray for vertex selections. Click the fixed point, then drag a second point sideways. Thickness and length stay fixed, so the endpoint may stop short of the cursor. Only the selected connected section moves. Esc cancels."
        ));
        if ui
            .add_enabled(
                anchored && self.edit_gesture.is_none(),
                egui::Button::new(crate::localization::tr("Reset anchor")),
            )
            .clicked()
        {
            self.bend_anchor = None;
        }
    }

    pub(super) fn begin_bend_gesture(&mut self, rectangle: egui::Rect, point: Vec2) {
        if !self.ensure_projection(rectangle) {
            return;
        }
        let Some(mesh) = &self.mesh else {
            return;
        };
        if mesh.selected_vertex_scope().is_empty() {
            self.status = "Select the rope section before using Bend".into();
            return;
        }
        if !self.bend_anchor_valid() {
            self.bend_anchor = None;
        }
        let Some(projection) = &self.projection else {
            return;
        };
        let candidates =
            brush_vertex_weights(mesh, projection, point, 18.0, true, BrushFalloff::Constant)
                .unwrap_or_default();
        let nearest = candidates
            .keys()
            .copied()
            .filter(|handle| {
                self.bend_anchor
                    .as_ref()
                    .is_none_or(|anchor| anchor.handles.contains(handle))
            })
            .min_by(|a, b| {
                let distance = |handle| {
                    projection
                        .vertices
                        .get(handle)
                        .map_or(f32::INFINITY, |vertex| {
                            vertex.screen.distance_squared(point)
                        })
                };
                distance(a).total_cmp(&distance(b)).then_with(|| a.cmp(b))
            });
        let Some(handle) = nearest else {
            self.status = "Click a visible vertex in the selected rope section".into();
            return;
        };
        let Some(anchor) = &self.bend_anchor else {
            match BendRegion::new(mesh, handle) {
                Ok(anchor) => {
                    self.bend_anchor = Some(anchor);
                    self.status = "1 anchored: drag 2 to bend".into();
                }
                Err(error) => self.status = format!("Could not anchor Bend: {error}"),
            }
            return;
        };
        if handle == anchor.anchor {
            self.status = "Drag a second point farther along the rope, or reset the anchor".into();
            return;
        }
        let stroke = match BendStroke::new(mesh, anchor, handle) {
            Ok(stroke) => stroke,
            Err(error) => {
                self.status =
                    format!("Choose a second point farther along the selected rope: {error}");
                return;
            }
        };
        self.ensure_deformation_reference();
        let Some(mesh) = &self.mesh else {
            return;
        };
        let gesture_id = match self.operator.begin(mesh, "Bend") {
            Ok(id) => id,
            Err(error) => {
                self.status = format!("Could not start Bend: {error}");
                return;
            }
        };
        self.edit_gesture = Some(EditGesture {
            gesture_id,
            tool: ViewportTool::Bend,
            axis: GizmoAxis::Free,
            handles: stroke.region.handles.clone(),
            sculpt_weights: HashMap::new(),
            symmetry_map: SculptSymmetryMap::default(),
            symmetry_primary_weights: HashMap::new(),
            symmetry_mirrored_weights: HashMap::new(),
            symmetry_plane_weights: HashMap::new(),
            pivot: Vec3::from_array(mesh.vertex(handle).expect("picked_vertex").position),
            last_pointer: point,
            last_sample: point,
            start_pointer: point,
            bend: Some(stroke),
        });
        self.status = "Bend preview: release to commit; Esc cancels".into();
    }

    pub(super) fn paint_bend_handles(&self, ui: &egui::Ui, rectangle: egui::Rect) {
        let Some(mesh) = &self.mesh else {
            return;
        };
        let active = self
            .edit_gesture
            .as_ref()
            .and_then(|gesture| gesture.bend.as_ref());
        let anchor = active.map(|stroke| &stroke.region).or_else(|| {
            self.bend_anchor
                .as_ref()
                .filter(|anchor| anchor.matches(mesh))
        });
        let Some(anchor) = anchor else {
            return;
        };
        let mut handles = vec![(anchor.anchor, "1", Color32::from_rgb(255, 190, 65))];
        if let Some(stroke) = active {
            handles.push((stroke.tip, "2", Color32::from_rgb(75, 210, 255)));
        }
        for (handle, label, colour) in handles {
            if let Some(projected) = mesh.vertex(handle).and_then(|vertex| {
                self.camera
                    .project(Vec3::from_array(vertex.position), rectangle)
            }) {
                let point = egui::pos2(projected.screen.x, projected.screen.y);
                ui.painter().circle_filled(point, 8.0, colour);
                ui.painter().text(
                    point,
                    egui::Align2::CENTER_CENTER,
                    label,
                    egui::FontId::proportional(12.0),
                    Color32::BLACK,
                );
            }
        }
    }
}
