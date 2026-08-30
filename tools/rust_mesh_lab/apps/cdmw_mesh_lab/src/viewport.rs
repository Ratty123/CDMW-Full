#![forbid(unsafe_code)]

use crate::camera::OrbitCamera;
use cdmw_interaction::{
    InteractionError, InteractionSnapshot, ProjectedElement, ProjectedHandle, ProjectedTriangle,
    SculptTool, SelectionDomain, SelectionOperation, SelectionQuery, SelectionQueryStats,
    SelectionShape, query_selection, query_selection_with_stats, selection_after_operation,
};
use cdmw_mesh::{History, MeshError, Selection, VertexHandle, WorkingMesh};
use egui::Rect;
use glam::{Vec2, Vec3};
use std::collections::VecDeque;
use std::collections::{HashMap, HashSet};

const MAX_LASSO_POINTS: usize = 4_096;
const MAX_POINTER_EVENTS: usize = 4_096;
const LASSO_MIN_SAMPLE_DISTANCE_SQUARED: f32 = 4.0;

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ViewportPointerEvent {
    PrimaryPressed(Vec2),
    PrimaryMoved(Vec2),
    PrimaryReleased(Vec2),
    Orbit(Vec2),
    Pan(Vec2),
}

#[derive(Debug, Default)]
pub struct PointerEventQueue {
    events: VecDeque<ViewportPointerEvent>,
}

impl PointerEventQueue {
    pub fn push(&mut self, event: ViewportPointerEvent) {
        if self.events.len() < MAX_POINTER_EVENTS {
            self.events.push_back(event);
            return;
        }
        match event {
            ViewportPointerEvent::PrimaryReleased(_) => {
                self.events.pop_back();
                self.events.push_back(event);
            }
            ViewportPointerEvent::PrimaryMoved(_)
            | ViewportPointerEvent::Orbit(_)
            | ViewportPointerEvent::Pan(_) => {
                if self.events.back().is_some_and(|previous| {
                    matches!(
                        (previous, event),
                        (
                            ViewportPointerEvent::PrimaryMoved(_),
                            ViewportPointerEvent::PrimaryMoved(_)
                        ) | (
                            ViewportPointerEvent::Orbit(_),
                            ViewportPointerEvent::Orbit(_)
                        ) | (ViewportPointerEvent::Pan(_), ViewportPointerEvent::Pan(_))
                    )
                }) {
                    self.events.pop_back();
                    self.events.push_back(event);
                }
            }
            ViewportPointerEvent::PrimaryPressed(_) => {}
        }
    }

    pub fn drain(&mut self) -> impl Iterator<Item = ViewportPointerEvent> + '_ {
        self.events.drain(..)
    }

    pub fn clear(&mut self) {
        self.events.clear();
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SelectionTool {
    Click,
    Brush,
    Rectangle,
    Lasso,
}

impl SelectionTool {
    #[must_use]
    pub const fn label(self) -> &'static str {
        match self {
            Self::Click => "Click",
            Self::Brush => "Brush",
            Self::Rectangle => "Rectangle",
            Self::Lasso => "Lasso",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BrushFalloff {
    Smooth,
    Linear,
    Constant,
}

impl BrushFalloff {
    #[must_use]
    pub const fn label(self) -> &'static str {
        match self {
            Self::Smooth => "Smooth",
            Self::Linear => "Linear",
            Self::Constant => "Constant",
        }
    }

    #[must_use]
    pub fn weight(self, normalized_distance: f32) -> f32 {
        if !normalized_distance.is_finite() || normalized_distance > 1.0 {
            return 0.0;
        }
        let remaining = 1.0 - normalized_distance.max(0.0);
        match self {
            Self::Smooth => remaining * remaining * (3.0 - 2.0 * remaining),
            Self::Linear => remaining,
            Self::Constant => 1.0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ViewportTool {
    Select,
    Move,
    Rotate,
    Scale,
    Grab,
    Smooth,
    Inflate,
    Pinch,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GizmoAxis {
    Free,
    X,
    Y,
    Z,
    View,
}

impl GizmoAxis {
    #[must_use]
    pub fn vector(self, camera: &OrbitCamera) -> Vec3 {
        match self {
            Self::Free => Vec3::ZERO,
            Self::X => Vec3::X,
            Self::Y => Vec3::Y,
            Self::Z => Vec3::Z,
            Self::View => camera.forward(),
        }
    }
}

impl ViewportTool {
    #[must_use]
    pub const fn label(self) -> &'static str {
        match self {
            Self::Select => "Select",
            Self::Move => "Move",
            Self::Rotate => "Rotate",
            Self::Scale => "Scale",
            Self::Grab => "Grab",
            Self::Smooth => "Smooth",
            Self::Inflate => "Inflate",
            Self::Pinch => "Pinch",
        }
    }

    #[must_use]
    pub const fn sculpt_tool(self) -> Option<SculptTool> {
        match self {
            Self::Grab => Some(SculptTool::Grab),
            Self::Smooth => Some(SculptTool::Smooth),
            Self::Inflate => Some(SculptTool::Inflate),
            Self::Pinch => Some(SculptTool::Pinch),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct ProjectedVertex {
    pub screen: Vec2,
    pub depth: f32,
    pub inside_view: bool,
}

#[derive(Debug, Clone)]
pub struct ViewportProjection {
    pub rectangle: Rect,
    pub interaction: InteractionSnapshot,
    pub vertices: HashMap<VertexHandle, ProjectedVertex>,
}

impl ViewportProjection {
    #[must_use]
    pub fn build(
        mesh: &WorkingMesh,
        camera: &OrbitCamera,
        rectangle: Rect,
        viewport_revision: u64,
    ) -> Self {
        let vertices = mesh
            .vertices()
            .filter_map(|(handle, vertex)| {
                camera
                    .project(Vec3::from_array(vertex.position), rectangle)
                    .map(|projected| {
                        (
                            handle,
                            ProjectedVertex {
                                screen: projected.screen,
                                depth: projected.depth,
                                inside_view: projected.inside_view,
                            },
                        )
                    })
            })
            .collect::<HashMap<_, _>>();
        let mut elements = Vec::with_capacity(
            mesh.vertices()
                .count()
                .saturating_add(mesh.edges().count())
                .saturating_add(mesh.faces().count()),
        );
        let mut depth_triangles = Vec::with_capacity(mesh.faces().count());
        elements.extend(mesh.vertices().filter_map(|(handle, _)| {
            vertices.get(&handle).map(|projected| ProjectedElement {
                handle: ProjectedHandle::Vertex(handle),
                position: projected.screen,
                depth: projected.depth,
                visible: projected.inside_view,
            })
        }));
        for (handle, edge) in mesh.edges() {
            let points = edge
                .vertices
                .iter()
                .filter_map(|vertex| vertices.get(vertex))
                .collect::<Vec<_>>();
            if points.len() == 2 {
                elements.push(ProjectedElement {
                    handle: ProjectedHandle::Edge(handle),
                    position: (points[0].screen + points[1].screen) * 0.5,
                    depth: (points[0].depth + points[1].depth) * 0.5,
                    visible: points.iter().all(|point| point.inside_view),
                });
            }
        }
        for (handle, face) in mesh.faces() {
            let points = face
                .vertices
                .iter()
                .filter_map(|vertex| vertices.get(vertex))
                .collect::<Vec<_>>();
            if points.len() == 3 {
                depth_triangles.push(ProjectedTriangle {
                    positions: [points[0].screen, points[1].screen, points[2].screen],
                    depths: [points[0].depth, points[1].depth, points[2].depth],
                });
                elements.push(ProjectedElement {
                    handle: ProjectedHandle::Face(handle),
                    position: (points[0].screen + points[1].screen + points[2].screen) / 3.0,
                    depth: (points[0].depth + points[1].depth + points[2].depth) / 3.0,
                    visible: points.iter().all(|point| point.inside_view),
                });
            }
        }
        Self {
            rectangle,
            interaction: InteractionSnapshot::new(
                mesh.geometry_revision,
                mesh.topology_generation,
                camera.revision(),
                viewport_revision,
                Vec2::new(rectangle.width(), rectangle.height()),
                elements,
                depth_triangles,
            ),
            vertices,
        }
    }

    #[must_use]
    pub fn matches(
        &self,
        mesh: &WorkingMesh,
        camera: &OrbitCamera,
        rectangle: Rect,
        viewport_revision: u64,
    ) -> bool {
        self.interaction.geometry_revision == mesh.geometry_revision
            && self.interaction.topology_generation == mesh.topology_generation
            && self.interaction.camera_revision == camera.revision()
            && self.interaction.viewport_revision == viewport_revision
            && self.rectangle == rectangle
    }
}

#[derive(Debug, Clone)]
pub struct SelectionGesture {
    pub tool: SelectionTool,
    pub domain: SelectionDomain,
    pub operation: SelectionOperation,
    pub visible_only: bool,
    pub start: Vec2,
    pub current: Vec2,
    pub points: Vec<Vec2>,
    pub radius: f32,
    before: WorkingMesh,
    accumulated: Selection,
    last_query_stats: Option<SelectionQueryStats>,
}

#[derive(Debug, Clone)]
pub struct EditGesture {
    pub gesture_id: u64,
    pub tool: ViewportTool,
    pub axis: GizmoAxis,
    pub handles: HashSet<VertexHandle>,
    pub sculpt_weights: HashMap<VertexHandle, f32>,
    pub pivot: Vec3,
    pub last_pointer: Vec2,
    pub last_sample: Vec2,
}

impl SelectionGesture {
    #[must_use]
    pub fn new(
        mesh: &WorkingMesh,
        tool: SelectionTool,
        domain: SelectionDomain,
        operation: SelectionOperation,
        visible_only: bool,
        point: Vec2,
        radius: f32,
    ) -> Self {
        Self {
            tool,
            domain,
            operation,
            visible_only,
            start: point,
            current: point,
            points: vec![point],
            radius,
            before: mesh.clone(),
            accumulated: Selection::default(),
            last_query_stats: None,
        }
    }

    pub fn update(
        &mut self,
        mesh: &mut WorkingMesh,
        snapshot: &InteractionSnapshot,
        point: Vec2,
    ) -> Result<(), InteractionError> {
        self.record_point(point);
        let Some(shape) = self.shape() else {
            return Ok(());
        };
        let query = SelectionQuery {
            domain: self.domain,
            operation: self.operation,
            visible_only: self.visible_only,
            shape,
            geometry_revision: snapshot.geometry_revision,
            topology_generation: snapshot.topology_generation,
            camera_revision: snapshot.camera_revision,
            viewport_revision: snapshot.viewport_revision,
        };
        let (incoming, stats) = query_selection_with_stats(snapshot, &query)?;
        self.last_query_stats = Some(stats);
        if self.tool == SelectionTool::Brush {
            union_selection(&mut self.accumulated, &incoming);
        } else {
            self.accumulated = incoming;
        }
        let next =
            selection_after_operation(&self.before.selection, self.operation, &self.accumulated);
        mesh.set_selection(next)?;
        Ok(())
    }

    pub fn record_point(&mut self, point: Vec2) {
        self.current = point;
        if self.tool == SelectionTool::Lasso {
            let should_append = !point.is_finite()
                || self.points.len() <= 1
                || self.points.last().is_none_or(|previous| {
                    previous.distance_squared(point) >= LASSO_MIN_SAMPLE_DISTANCE_SQUARED
                });
            if should_append {
                self.points.push(point);
            } else if let Some(previous) = self.points.last_mut() {
                *previous = point;
            }
            if self.points.len() > MAX_LASSO_POINTS {
                compact_lasso_points(&mut self.points);
            }
        }
    }

    #[must_use]
    pub fn last_query_stats(&self) -> Option<SelectionQueryStats> {
        self.last_query_stats
    }

    pub fn commit(self, mesh: &WorkingMesh, history: &mut History) -> Result<bool, MeshError> {
        if self.before.selection == mesh.selection {
            return Ok(false);
        }
        history.commit(
            format!("{} selection", self.tool.label()),
            self.before,
            mesh,
        )?;
        Ok(true)
    }

    pub fn cancel(self, mesh: &mut WorkingMesh) {
        *mesh = self.before;
    }

    #[must_use]
    pub fn shape(&self) -> Option<SelectionShape> {
        match self.tool {
            SelectionTool::Click => Some(SelectionShape::Click {
                point: self.current,
                radius: self.radius,
            }),
            SelectionTool::Brush => Some(SelectionShape::Brush {
                point: self.current,
                radius: self.radius,
            }),
            SelectionTool::Rectangle => Some(SelectionShape::Rectangle {
                minimum: self.start,
                maximum: self.current,
            }),
            SelectionTool::Lasso => (self.points.len() >= 3).then(|| SelectionShape::Lasso {
                points: self.points.clone(),
            }),
        }
    }
}

fn compact_lasso_points(points: &mut Vec<Vec2>) {
    let point_count = points.len();
    let mut compacted = Vec::with_capacity(point_count / 2 + 1);
    for (index, point) in points.iter().copied().enumerate() {
        if (index == 0 || index % 2 == 0 || index + 1 == point_count)
            && compacted.last().copied() != Some(point)
        {
            compacted.push(point);
        }
    }
    *points = compacted;
}

fn union_selection(target: &mut Selection, incoming: &Selection) {
    target.vertices.extend(&incoming.vertices);
    target.edges.extend(&incoming.edges);
    target.faces.extend(&incoming.faces);
    target.submeshes.extend(&incoming.submeshes);
}

pub fn brush_vertex_scope(
    mesh: &WorkingMesh,
    snapshot: &InteractionSnapshot,
    point: Vec2,
    radius: f32,
    visible_only: bool,
) -> Result<HashSet<VertexHandle>, InteractionError> {
    let query = SelectionQuery {
        domain: SelectionDomain::Vertex,
        operation: SelectionOperation::Replace,
        visible_only,
        shape: SelectionShape::Brush { point, radius },
        geometry_revision: snapshot.geometry_revision,
        topology_generation: snapshot.topology_generation,
        camera_revision: snapshot.camera_revision,
        viewport_revision: snapshot.viewport_revision,
    };
    let under_brush = query_selection(snapshot, &query)?.vertices;
    let selected = mesh.selected_vertex_scope();
    if selected.is_empty() {
        Ok(under_brush)
    } else {
        Ok(under_brush.intersection(&selected).copied().collect())
    }
}

pub fn brush_vertex_weights(
    mesh: &WorkingMesh,
    projection: &ViewportProjection,
    point: Vec2,
    radius: f32,
    visible_only: bool,
    falloff: BrushFalloff,
) -> Result<HashMap<VertexHandle, f32>, InteractionError> {
    if !point.is_finite() || !radius.is_finite() || radius <= 0.0 {
        return Err(InteractionError::InvalidShape);
    }
    let handles = brush_vertex_scope(mesh, &projection.interaction, point, radius, visible_only)?;
    Ok(handles
        .into_iter()
        .filter_map(|handle| {
            let projected = projection.vertices.get(&handle)?;
            let weight = falloff.weight(projected.screen.distance(point) / radius);
            (weight > 0.0).then_some((handle, weight))
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use cdmw_formats::{MeshFormat, decode_mesh};

    fn triangle() -> WorkingMesh {
        let document = decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
            MeshFormat::Pam,
        )
        .unwrap_or_else(|error| panic!("fixture decode failed: {error}"));
        WorkingMesh::from_document(&document)
            .unwrap_or_else(|error| panic!("fixture mesh failed: {error}"))
    }

    #[test]
    fn brush_falloff_profiles_are_bounded_and_distinct() {
        assert_eq!(BrushFalloff::Smooth.weight(0.0), 1.0);
        assert_eq!(BrushFalloff::Smooth.weight(0.5), 0.5);
        assert_eq!(BrushFalloff::Smooth.weight(1.0), 0.0);
        assert_eq!(BrushFalloff::Linear.weight(0.25), 0.75);
        assert_eq!(BrushFalloff::Constant.weight(0.75), 1.0);
        assert_eq!(BrushFalloff::Linear.weight(1.25), 0.0);
        assert_eq!(BrushFalloff::Smooth.weight(f32::NAN), 0.0);
    }

    #[test]
    fn brush_vertex_weights_follow_projection_and_selection_scope()
    -> Result<(), Box<dyn std::error::Error>> {
        let mut mesh = triangle();
        let camera = OrbitCamera::default();
        let rectangle = Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(800.0, 600.0));
        let projection = ViewportProjection::build(&mesh, &camera, rectangle, 1);
        let (&center_handle, center) = projection
            .vertices
            .iter()
            .next()
            .ok_or("missing projected vertex")?;
        let radius = projection
            .vertices
            .values()
            .map(|vertex| vertex.screen.distance(center.screen))
            .fold(0.0_f32, f32::max)
            + 1.0;
        let weights = brush_vertex_weights(
            &mesh,
            &projection,
            center.screen,
            radius,
            false,
            BrushFalloff::Linear,
        )?;
        assert_eq!(weights.len(), mesh.vertices().count());
        assert_eq!(weights[&center_handle], 1.0);
        for (handle, projected) in &projection.vertices {
            let expected = 1.0 - projected.screen.distance(center.screen) / radius;
            assert!((weights[handle] - expected).abs() < 1.0e-6);
        }
        assert!(weights.values().any(|weight| *weight < 1.0));

        mesh.selection.vertices.insert(center_handle);
        let restricted = brush_vertex_weights(
            &mesh,
            &projection,
            center.screen,
            radius,
            false,
            BrushFalloff::Constant,
        )?;
        assert_eq!(restricted, HashMap::from([(center_handle, 1.0)]));
        Ok(())
    }

    #[test]
    fn brush_preview_accumulates_and_commits_one_history_entry()
    -> Result<(), Box<dyn std::error::Error>> {
        let mut mesh = triangle();
        let camera = OrbitCamera::default();
        let rectangle = Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(800.0, 600.0));
        let projection = ViewportProjection::build(&mesh, &camera, rectangle, 1);
        let first = projection
            .vertices
            .values()
            .next()
            .ok_or("missing projected vertex")?
            .screen;
        let mut gesture = SelectionGesture::new(
            &mesh,
            SelectionTool::Brush,
            SelectionDomain::Vertex,
            SelectionOperation::Replace,
            false,
            first,
            8.0,
        );
        gesture.update(&mut mesh, &projection.interaction, first)?;
        let mut history = History::new(1_000_000);
        assert!(gesture.commit(&mesh, &mut history)?);
        assert_eq!(history.undo_len(), 1);
        assert!(!mesh.selection.vertices.is_empty());
        Ok(())
    }

    #[test]
    fn lasso_with_too_few_points_has_no_preview_shape() {
        let mesh = triangle();
        let gesture = SelectionGesture::new(
            &mesh,
            SelectionTool::Lasso,
            SelectionDomain::Face,
            SelectionOperation::Replace,
            false,
            Vec2::ZERO,
            8.0,
        );
        assert!(gesture.shape().is_none());
    }

    #[test]
    fn long_lasso_stays_bounded_and_retains_the_release_point() {
        let mesh = triangle();
        let mut gesture = SelectionGesture::new(
            &mesh,
            SelectionTool::Lasso,
            SelectionDomain::Vertex,
            SelectionOperation::Replace,
            false,
            Vec2::ZERO,
            8.0,
        );
        let final_point = Vec2::new(20_000.0, 24.0);
        for index in 1..10_000 {
            gesture.record_point(Vec2::new(index as f32 * 2.0, (index % 7) as f32 * 4.0));
        }
        gesture.record_point(final_point);
        assert!(gesture.points.len() <= MAX_LASSO_POINTS);
        assert_eq!(gesture.points.first(), Some(&Vec2::ZERO));
        assert_eq!(gesture.points.last(), Some(&final_point));
    }

    #[test]
    fn lasso_retains_a_sub_threshold_release_without_losing_its_press() {
        let mesh = triangle();
        let mut gesture = SelectionGesture::new(
            &mesh,
            SelectionTool::Lasso,
            SelectionDomain::Vertex,
            SelectionOperation::Replace,
            false,
            Vec2::ZERO,
            8.0,
        );
        gesture.record_point(Vec2::new(3.0, 0.0));
        let release = Vec2::new(3.5, 0.0);
        gesture.record_point(release);
        assert_eq!(gesture.points.first(), Some(&Vec2::ZERO));
        assert_eq!(gesture.points.last(), Some(&release));
    }

    #[test]
    fn non_finite_lasso_sample_is_rejected_by_the_shared_query() {
        let mut mesh = triangle();
        let camera = OrbitCamera::default();
        let rectangle = Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(800.0, 600.0));
        let projection = ViewportProjection::build(&mesh, &camera, rectangle, 1);
        let mut gesture = SelectionGesture::new(
            &mesh,
            SelectionTool::Lasso,
            SelectionDomain::Vertex,
            SelectionOperation::Replace,
            false,
            Vec2::ZERO,
            8.0,
        );
        gesture.record_point(Vec2::new(3.0, 0.0));
        gesture.record_point(Vec2::new(0.0, 3.0));
        assert!(matches!(
            gesture.update(&mut mesh, &projection.interaction, Vec2::splat(f32::NAN)),
            Err(InteractionError::InvalidShape)
        ));
    }

    #[test]
    fn rectangle_and_lasso_route_face_selection_through_the_shared_snapshot()
    -> Result<(), Box<dyn std::error::Error>> {
        for tool in [SelectionTool::Rectangle, SelectionTool::Lasso] {
            let mut mesh = triangle();
            let camera = OrbitCamera::default();
            let rectangle = Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(800.0, 600.0));
            let projection = ViewportProjection::build(&mesh, &camera, rectangle, 1);
            let center = projection
                .interaction
                .elements
                .iter()
                .find_map(|element| {
                    matches!(element.handle, ProjectedHandle::Face(_)).then_some(element.position)
                })
                .ok_or("missing projected face")?;
            let start = center - Vec2::splat(20.0);
            let mut gesture = SelectionGesture::new(
                &mesh,
                tool,
                SelectionDomain::Face,
                SelectionOperation::Replace,
                false,
                start,
                8.0,
            );
            match tool {
                SelectionTool::Rectangle => {
                    gesture.update(
                        &mut mesh,
                        &projection.interaction,
                        center + Vec2::splat(20.0),
                    )?;
                }
                SelectionTool::Lasso => {
                    for point in [
                        center + Vec2::new(20.0, -20.0),
                        center + Vec2::splat(20.0),
                        center + Vec2::new(-20.0, 20.0),
                    ] {
                        gesture.update(&mut mesh, &projection.interaction, point)?;
                    }
                }
                _ => unreachable!(),
            }
            assert_eq!(mesh.selection.faces.len(), 1);
        }
        Ok(())
    }

    #[test]
    fn cancelling_selection_restores_the_pre_gesture_selection() -> Result<(), InteractionError> {
        let mut mesh = triangle();
        let camera = OrbitCamera::default();
        let rectangle = Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(800.0, 600.0));
        let projection = ViewportProjection::build(&mesh, &camera, rectangle, 1);
        let point = projection
            .vertices
            .values()
            .next()
            .ok_or(InteractionError::InvalidShape)?
            .screen;
        let mut gesture = SelectionGesture::new(
            &mesh,
            SelectionTool::Brush,
            SelectionDomain::Vertex,
            SelectionOperation::Replace,
            false,
            point,
            8.0,
        );
        gesture.update(&mut mesh, &projection.interaction, point)?;
        assert!(!mesh.selection.vertices.is_empty());
        gesture.cancel(&mut mesh);
        assert_eq!(mesh.selection, Selection::default());
        Ok(())
    }

    #[test]
    fn bounded_pointer_queue_preserves_press_and_release_during_a_fast_drag() {
        let mut queue = PointerEventQueue::default();
        queue.push(ViewportPointerEvent::PrimaryPressed(Vec2::ZERO));
        for index in 0..(MAX_POINTER_EVENTS + 500) {
            queue.push(ViewportPointerEvent::PrimaryMoved(Vec2::splat(
                index as f32,
            )));
        }
        let release = Vec2::splat(9_999.0);
        queue.push(ViewportPointerEvent::PrimaryReleased(release));
        let events = queue.drain().collect::<Vec<_>>();
        assert!(events.len() <= MAX_POINTER_EVENTS);
        assert_eq!(
            events.first(),
            Some(&ViewportPointerEvent::PrimaryPressed(Vec2::ZERO))
        );
        assert_eq!(
            events.last(),
            Some(&ViewportPointerEvent::PrimaryReleased(release))
        );
    }
}
