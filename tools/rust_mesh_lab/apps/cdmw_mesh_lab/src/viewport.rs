#![forbid(unsafe_code)]

use crate::camera::OrbitCamera;
use cdmw_interaction::{
    InteractionError, InteractionSnapshot, ProjectedElement, ProjectedHandle, ProjectedTriangle,
    SculptTool, SelectionDomain, SelectionOperation, SelectionQuery, SelectionQueryStats,
    SelectionShape, query_selection, query_selection_with_stats, selection_after_operation,
};
use cdmw_mesh::{History, MeshError, Provenance, Selection, VertexHandle, WorkingMesh};
use egui::Rect;
use glam::{Vec2, Vec3};
use std::collections::{BTreeMap, HashMap, HashSet, VecDeque};

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
    pub fn push_primary_path_point(&mut self, point: Vec2) {
        if self.events.len() < MAX_POINTER_EVENTS {
            self.events
                .push_back(ViewportPointerEvent::PrimaryMoved(point));
        } else {
            // Keep the queue bounded while retaining the latest point. This only
            // coalesces after the path has already reached the safety limit.
            self.push(ViewportPointerEvent::PrimaryMoved(point));
        }
    }

    pub fn push(&mut self, event: ViewportPointerEvent) {
        if let Some(previous) = self.events.back_mut() {
            match (previous, event) {
                (
                    ViewportPointerEvent::PrimaryMoved(current),
                    ViewportPointerEvent::PrimaryMoved(next),
                ) => {
                    *current = next;
                    return;
                }
                (ViewportPointerEvent::Orbit(current), ViewportPointerEvent::Orbit(delta))
                | (ViewportPointerEvent::Pan(current), ViewportPointerEvent::Pan(delta)) => {
                    *current += delta;
                    return;
                }
                _ => {}
            }
        }
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

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum SculptSymmetry {
    #[default]
    Off,
    X,
    Y,
    Z,
}

impl SculptSymmetry {
    #[must_use]
    pub const fn label(self) -> &'static str {
        match self {
            Self::Off => "Off",
            Self::X => "X",
            Self::Y => "Y",
            Self::Z => "Z",
        }
    }

    #[must_use]
    pub const fn axis_index(self) -> Option<usize> {
        match self {
            Self::Off => None,
            Self::X => Some(0),
            Self::Y => Some(1),
            Self::Z => Some(2),
        }
    }

    #[must_use]
    pub fn reflect_point(self, mut value: Vec3) -> Vec3 {
        if let Some(axis) = self.axis_index() {
            value[axis] = -value[axis];
        }
        value
    }

    #[must_use]
    pub fn plane_vector(self, mut value: Vec3) -> Vec3 {
        if let Some(axis) = self.axis_index() {
            value[axis] = 0.0;
        }
        value
    }
}

#[derive(Debug, Clone, Default)]
pub struct SculptSymmetryMap {
    pub mode: SculptSymmetry,
    partners: HashMap<VertexHandle, VertexHandle>,
    plane_vertices: HashSet<VertexHandle>,
    tolerance: f32,
    unmatched_vertices: usize,
}

#[derive(Debug, Clone, Default)]
pub struct SymmetricSculptWeights {
    pub combined: HashMap<VertexHandle, f32>,
    pub primary: HashMap<VertexHandle, f32>,
    pub mirrored: HashMap<VertexHandle, f32>,
    pub plane: HashMap<VertexHandle, f32>,
}

impl SculptSymmetryMap {
    #[must_use]
    pub fn build(mesh: &WorkingMesh, mode: SculptSymmetry) -> Self {
        let Some(axis) = mode.axis_index() else {
            return Self {
                mode,
                ..Self::default()
            };
        };
        let tolerance = symmetry_tolerance(mesh);
        let mut memberships = mesh
            .vertices()
            .map(|(handle, vertex)| {
                let membership = match vertex.provenance {
                    Provenance::Source { submesh, .. } => vec![submesh],
                    Provenance::Generated { .. } => Vec::new(),
                };
                (handle, membership)
            })
            .collect::<HashMap<_, _>>();
        for (_, face) in mesh.faces() {
            for handle in face.vertices {
                if mesh
                    .vertex(handle)
                    .is_some_and(|vertex| matches!(vertex.provenance, Provenance::Generated { .. }))
                {
                    memberships.entry(handle).or_default().push(face.submesh);
                }
            }
        }
        for membership in memberships.values_mut() {
            membership.sort_unstable();
            membership.dedup();
        }

        let mut groups = BTreeMap::<Vec<u32>, Vec<VertexHandle>>::new();
        let mut unmatched_vertices = 0;
        for (handle, membership) in memberships {
            if membership.is_empty() {
                unmatched_vertices += 1;
            } else {
                groups.entry(membership).or_default().push(handle);
            }
        }
        let mut partners = HashMap::new();
        let mut plane_vertices = HashSet::new();
        for handles in groups.values_mut() {
            handles.sort_unstable();
            let mut negative = Vec::new();
            let mut positive_cells = BTreeMap::<(i64, i64, i64), Vec<VertexHandle>>::new();
            for handle in handles.iter().copied() {
                let Some(vertex) = mesh.vertex(handle) else {
                    unmatched_vertices += 1;
                    continue;
                };
                let position = Vec3::from_array(vertex.position);
                if position[axis].abs() <= tolerance {
                    partners.insert(handle, handle);
                    plane_vertices.insert(handle);
                } else if position[axis] < 0.0 {
                    negative.push(handle);
                } else {
                    positive_cells
                        .entry(symmetry_cell(position, tolerance))
                        .or_default()
                        .push(handle);
                }
            }
            for candidates in positive_cells.values_mut() {
                candidates.sort_unstable();
            }
            let mut used_positive = HashSet::new();
            for negative_handle in negative {
                let Some(negative_vertex) = mesh.vertex(negative_handle) else {
                    unmatched_vertices += 1;
                    continue;
                };
                let reflected = mode.reflect_point(Vec3::from_array(negative_vertex.position));
                let cell = symmetry_cell(reflected, tolerance);
                let mut best: Option<(f32, VertexHandle)> = None;
                for x_offset in -1_i64..=1 {
                    for y_offset in -1_i64..=1 {
                        for z_offset in -1_i64..=1 {
                            let neighbor = (
                                cell.0.saturating_add(x_offset),
                                cell.1.saturating_add(y_offset),
                                cell.2.saturating_add(z_offset),
                            );
                            let Some(candidates) = positive_cells.get(&neighbor) else {
                                continue;
                            };
                            for candidate in candidates.iter().copied() {
                                if used_positive.contains(&candidate) {
                                    continue;
                                }
                                let Some(vertex) = mesh.vertex(candidate) else {
                                    continue;
                                };
                                let distance_squared =
                                    Vec3::from_array(vertex.position).distance_squared(reflected);
                                if distance_squared > tolerance * tolerance {
                                    continue;
                                }
                                if best.is_none_or(|(best_distance, best_handle)| {
                                    distance_squared < best_distance
                                        || (distance_squared == best_distance
                                            && candidate < best_handle)
                                }) {
                                    best = Some((distance_squared, candidate));
                                }
                            }
                        }
                    }
                }
                if let Some((_, positive_handle)) = best {
                    used_positive.insert(positive_handle);
                    partners.insert(negative_handle, positive_handle);
                    partners.insert(positive_handle, negative_handle);
                } else {
                    unmatched_vertices += 1;
                }
            }
            let positive_count = positive_cells.values().map(Vec::len).sum::<usize>();
            unmatched_vertices += positive_count.saturating_sub(used_positive.len());
        }
        Self {
            mode,
            partners,
            plane_vertices,
            tolerance,
            unmatched_vertices,
        }
    }

    #[cfg(test)]
    #[must_use]
    pub fn tolerance(&self) -> f32 {
        self.tolerance
    }

    #[must_use]
    pub fn unmatched_vertices(&self) -> usize {
        self.unmatched_vertices
    }

    #[must_use]
    pub fn paired_vertices(&self) -> usize {
        self.partners
            .len()
            .saturating_sub(self.plane_vertices.len())
    }

    #[must_use]
    pub fn plane_vertices(&self) -> usize {
        self.plane_vertices.len()
    }

    #[must_use]
    pub fn partner(&self, handle: VertexHandle) -> Option<VertexHandle> {
        self.partners.get(&handle).copied()
    }

    #[must_use]
    pub fn expand_weights(
        &self,
        mesh: &WorkingMesh,
        source: &HashMap<VertexHandle, f32>,
    ) -> SymmetricSculptWeights {
        if self.mode == SculptSymmetry::Off {
            return SymmetricSculptWeights {
                combined: source.clone(),
                primary: source.clone(),
                ..SymmetricSculptWeights::default()
            };
        }
        let selected = mesh.selected_vertex_scope();
        let allows = |handle: VertexHandle| selected.is_empty() || selected.contains(&handle);
        let axis = self.mode.axis_index().unwrap_or(0);
        let mut source_handles = source.keys().copied().collect::<Vec<_>>();
        source_handles.sort_unstable();
        let mut source_sign = 0.0_f32;
        let mut strongest_weight = -1.0_f32;
        for handle in &source_handles {
            if self.partner(*handle).is_none() {
                continue;
            }
            let weight = source.get(handle).copied().unwrap_or(0.0);
            if weight > strongest_weight {
                strongest_weight = weight;
                source_sign = mesh
                    .vertex(*handle)
                    .map(|vertex| Vec3::from_array(vertex.position)[axis])
                    .filter(|coordinate| coordinate.abs() > self.tolerance)
                    .map_or(0.0, f32::signum);
            }
        }

        let mut result = SymmetricSculptWeights::default();
        let mut visited = HashSet::new();
        for handle in source_handles {
            let Some(partner) = self.partner(handle) else {
                // With symmetry active an unmatched vertex is deliberately untouched.
                continue;
            };
            if !visited.insert(handle) {
                continue;
            }
            visited.insert(partner);
            let weight = source
                .get(&handle)
                .copied()
                .unwrap_or(0.0)
                .max(source.get(&partner).copied().unwrap_or(0.0));
            if weight <= 0.0 {
                continue;
            }
            for target in [handle, partner] {
                if !allows(target) || result.combined.contains_key(&target) {
                    continue;
                }
                result.combined.insert(target, weight);
                if self.plane_vertices.contains(&target) {
                    result.plane.insert(target, weight);
                    continue;
                }
                let coordinate = mesh
                    .vertex(target)
                    .map(|vertex| Vec3::from_array(vertex.position)[axis])
                    .unwrap_or(0.0);
                let primary = if source_sign == 0.0 {
                    target <= partner.min(handle)
                } else {
                    coordinate.signum() == source_sign
                };
                if primary {
                    result.primary.insert(target, weight);
                } else {
                    result.mirrored.insert(target, weight);
                }
            }
        }
        result
    }
}

fn symmetry_tolerance(mesh: &WorkingMesh) -> f32 {
    let mut minimum = Vec3::splat(f32::INFINITY);
    let mut maximum = Vec3::splat(f32::NEG_INFINITY);
    let mut magnitude = 0.0_f32;
    for (_, vertex) in mesh.vertices() {
        let position = Vec3::from_array(vertex.position);
        minimum = minimum.min(position);
        maximum = maximum.max(position);
        magnitude = magnitude.max(position.abs().max_element());
    }
    let span = (maximum - minimum).max_element();
    if !span.is_finite() || !magnitude.is_finite() {
        return 1.0e-7;
    }
    (span * 1.0e-6)
        .max(magnitude * f32::EPSILON * 8.0)
        .max(1.0e-7)
}

fn symmetry_cell(position: Vec3, tolerance: f32) -> (i64, i64, i64) {
    let quantize = |value: f32| (value / tolerance).floor() as i64;
    (
        quantize(position.x),
        quantize(position.y),
        quantize(position.z),
    )
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

#[derive(Debug)]
pub struct FaceSelectionOverlay {
    geometry_revision: u64,
    topology_generation: u64,
    selection_revision: u64,
    visible_submeshes: Option<HashSet<u32>>,
    colour: [f32; 4],
    pub positions: Vec<[f32; 3]>,
    pub uploaded: bool,
}

impl FaceSelectionOverlay {
    pub fn build(mesh: &WorkingMesh, visible: Option<HashSet<u32>>, colour: [f32; 4]) -> Self {
        let mut handles = if mesh.selection.submeshes.is_empty() {
            mesh.selection.faces.iter().copied().collect::<Vec<_>>()
        } else {
            mesh.faces()
                .filter_map(|(handle, face)| {
                    (mesh.selection.faces.contains(&handle)
                        || mesh.selection.submeshes.contains(&face.submesh))
                    .then_some(handle)
                })
                .collect()
        };
        handles.sort_unstable();
        let positions = handles
            .iter()
            .filter_map(|handle| mesh.face(*handle))
            .filter(|face| {
                visible
                    .as_ref()
                    .is_none_or(|visible| visible.contains(&face.submesh))
            })
            .flat_map(|face| face.vertices.iter())
            .filter_map(|handle| mesh.vertex(*handle).map(|vertex| vertex.position))
            .collect();
        Self {
            geometry_revision: mesh.geometry_revision,
            topology_generation: mesh.topology_generation,
            selection_revision: mesh.selection_revision,
            visible_submeshes: visible,
            colour,
            positions,
            uploaded: false,
        }
    }

    pub fn matches(
        &self,
        mesh: &WorkingMesh,
        visible: &Option<HashSet<u32>>,
        colour: [f32; 4],
    ) -> bool {
        self.geometry_revision == mesh.geometry_revision
            && self.topology_generation == mesh.topology_generation
            && self.selection_revision == mesh.selection_revision
            && &self.visible_submeshes == visible
            && self.colour == colour
    }
}

#[derive(Debug, Clone)]
pub struct ViewportProjection {
    pub rectangle: Rect,
    pub interaction: InteractionSnapshot,
    pub vertices: HashMap<VertexHandle, ProjectedVertex>,
    visible_submeshes: Option<Vec<u32>>,
}

impl ViewportProjection {
    #[must_use]
    pub fn build(
        mesh: &WorkingMesh,
        camera: &OrbitCamera,
        rectangle: Rect,
        viewport_revision: u64,
    ) -> Self {
        Self::build_with_visibility(mesh, camera, rectangle, viewport_revision, None)
    }

    #[must_use]
    pub fn build_for_submeshes(
        mesh: &WorkingMesh,
        camera: &OrbitCamera,
        rectangle: Rect,
        viewport_revision: u64,
        visible_submeshes: &HashSet<u32>,
    ) -> Self {
        Self::build_with_visibility(
            mesh,
            camera,
            rectangle,
            viewport_revision,
            Some(visible_submeshes),
        )
    }

    fn build_with_visibility(
        mesh: &WorkingMesh,
        camera: &OrbitCamera,
        rectangle: Rect,
        viewport_revision: u64,
        visible_submeshes: Option<&HashSet<u32>>,
    ) -> Self {
        let visible_elements =
            visible_submeshes.map(|submeshes| mesh.element_handles_for_submeshes(submeshes));
        let vertices = mesh
            .vertices()
            .filter(|(handle, _)| {
                visible_elements
                    .as_ref()
                    .is_none_or(|elements| elements.vertices.contains(handle))
            })
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
        let mut elements = Vec::with_capacity(vertices.len().saturating_mul(3));
        let mut depth_triangles = Vec::with_capacity(
            visible_elements
                .as_ref()
                .map_or_else(|| mesh.faces().count(), |items| items.faces.len()),
        );
        elements.extend(mesh.vertices().filter_map(|(handle, _)| {
            vertices.get(&handle).map(|projected| ProjectedElement {
                handle: ProjectedHandle::Vertex(handle),
                position: projected.screen,
                depth: projected.depth,
                visible: projected.inside_view,
            })
        }));
        for (handle, edge) in mesh.edges() {
            if visible_elements
                .as_ref()
                .is_some_and(|elements| !elements.edges.contains(&handle))
            {
                continue;
            }
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
            if visible_elements
                .as_ref()
                .is_some_and(|elements| !elements.faces.contains(&handle))
            {
                continue;
            }
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
            visible_submeshes: visible_submeshes.map(|submeshes| {
                let mut ordered = submeshes.iter().copied().collect::<Vec<_>>();
                ordered.sort_unstable();
                ordered
            }),
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
        self.matches_with_visibility(mesh, camera, rectangle, viewport_revision, None)
    }

    #[must_use]
    pub fn matches_for_submeshes(
        &self,
        mesh: &WorkingMesh,
        camera: &OrbitCamera,
        rectangle: Rect,
        viewport_revision: u64,
        visible_submeshes: &HashSet<u32>,
    ) -> bool {
        self.matches_with_visibility(
            mesh,
            camera,
            rectangle,
            viewport_revision,
            Some(visible_submeshes),
        )
    }

    fn matches_with_visibility(
        &self,
        mesh: &WorkingMesh,
        camera: &OrbitCamera,
        rectangle: Rect,
        viewport_revision: u64,
        visible_submeshes: Option<&HashSet<u32>>,
    ) -> bool {
        let requested = visible_submeshes.map(|submeshes| {
            let mut ordered = submeshes.iter().copied().collect::<Vec<_>>();
            ordered.sort_unstable();
            ordered
        });
        self.interaction.geometry_revision == mesh.geometry_revision
            && self.interaction.topology_generation == mesh.topology_generation
            && self.interaction.camera_revision == camera.revision()
            && self.interaction.viewport_revision == viewport_revision
            && self.rectangle == rectangle
            && self.visible_submeshes == requested
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
    pub symmetry_map: SculptSymmetryMap,
    pub symmetry_primary_weights: HashMap<VertexHandle, f32>,
    pub symmetry_mirrored_weights: HashMap<VertexHandle, f32>,
    pub symmetry_plane_weights: HashMap<VertexHandle, f32>,
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
        let previous = self.current;
        self.record_point(point);
        let Some(mut shape) = self.shape() else {
            return Ok(());
        };
        if self.tool == SelectionTool::Brush {
            shape = SelectionShape::BrushStroke {
                start: previous,
                end: point,
                radius: self.radius,
            };
        }
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

pub fn brush_vertex_weights_unclipped(
    projection: &ViewportProjection,
    point: Vec2,
    radius: f32,
    visible_only: bool,
    falloff: BrushFalloff,
) -> Result<HashMap<VertexHandle, f32>, InteractionError> {
    if !point.is_finite() || !radius.is_finite() || radius <= 0.0 {
        return Err(InteractionError::InvalidShape);
    }
    let query = SelectionQuery {
        domain: SelectionDomain::Vertex,
        operation: SelectionOperation::Replace,
        visible_only,
        shape: SelectionShape::Brush { point, radius },
        geometry_revision: projection.interaction.geometry_revision,
        topology_generation: projection.interaction.topology_generation,
        camera_revision: projection.interaction.camera_revision,
        viewport_revision: projection.interaction.viewport_revision,
    };
    let handles = query_selection(&projection.interaction, &query)?.vertices;
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
    use cdmw_formats::{MeshDocument, MeshFormat, MeshLod, SourceRange, Submesh, decode_mesh};

    fn triangle() -> WorkingMesh {
        let document = decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
            MeshFormat::Pam,
        )
        .unwrap_or_else(|error| panic!("fixture decode failed: {error}"));
        WorkingMesh::from_document(&document)
            .unwrap_or_else(|error| panic!("fixture mesh failed: {error}"))
    }

    fn submesh(name: &str, positions: Vec<[f32; 3]>, indices: Vec<u32>) -> Submesh {
        let vertex_count = positions.len();
        Submesh {
            name: name.to_owned(),
            material: format!("{name}-material"),
            positions,
            normals: vec![[0.0, 0.0, 1.0]; vertex_count],
            uvs: vec![[0.0, 0.0]; vertex_count],
            indices,
            source_vertex_indices: (0..vertex_count)
                .map(|index| i32::try_from(index).unwrap_or(i32::MAX))
                .collect(),
            source_range: SourceRange {
                offset: 0,
                length: 0,
            },
            vertex_stride: 0,
            layout: "symmetry-test".to_owned(),
        }
    }

    fn symmetry_mesh() -> WorkingMesh {
        let document = MeshDocument {
            format: MeshFormat::Pam,
            source_sha256: String::new(),
            parser: "symmetry-test".to_owned(),
            lod_count_reported: 1,
            lods: vec![MeshLod {
                level: 0,
                submeshes: vec![submesh(
                    "symmetric",
                    vec![
                        [-1.0, 0.0, 0.0],
                        [1.0, 0.0, 0.0],
                        [0.0, 1.0, 0.0],
                        [2.0, 2.0, 0.0],
                    ],
                    vec![0, 1, 2],
                )],
            }],
            warnings: Vec::new(),
            structural_fingerprint: String::new(),
        };
        WorkingMesh::from_document(&document)
            .unwrap_or_else(|error| panic!("symmetry fixture failed: {error}"))
    }

    fn handle_at(mesh: &WorkingMesh, position: [f32; 3]) -> VertexHandle {
        mesh.vertices()
            .find_map(|(handle, vertex)| (vertex.position == position).then_some(handle))
            .unwrap_or_else(|| panic!("missing fixture vertex at {position:?}"))
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
    fn symmetry_pairing_is_deterministic_and_leaves_unmatched_vertices_out() {
        let mesh = symmetry_mesh();
        let negative = handle_at(&mesh, [-1.0, 0.0, 0.0]);
        let positive = handle_at(&mesh, [1.0, 0.0, 0.0]);
        let plane = handle_at(&mesh, [0.0, 1.0, 0.0]);
        let unmatched = handle_at(&mesh, [2.0, 2.0, 0.0]);
        let first = SculptSymmetryMap::build(&mesh, SculptSymmetry::X);
        let second = SculptSymmetryMap::build(&mesh, SculptSymmetry::X);
        assert_eq!(first.partner(negative), Some(positive));
        assert_eq!(first.partner(positive), Some(negative));
        assert_eq!(first.partner(plane), Some(plane));
        assert_eq!(first.partner(unmatched), None);
        assert_eq!(first.unmatched_vertices(), 1);
        assert_eq!(first.paired_vertices(), 2);
        assert_eq!(first.plane_vertices(), 1);
        assert_eq!(first.partner(negative), second.partner(negative));
        assert!(first.tolerance() > 0.0 && first.tolerance() < 1.0e-3);

        let expanded = first.expand_weights(&mesh, &HashMap::from([(unmatched, 1.0)]));
        assert!(expanded.combined.is_empty());
    }

    #[test]
    fn symmetry_expansion_clips_the_mirror_to_the_explicit_selection() -> Result<(), MeshError> {
        let mut mesh = symmetry_mesh();
        let negative = handle_at(&mesh, [-1.0, 0.0, 0.0]);
        let positive = handle_at(&mesh, [1.0, 0.0, 0.0]);
        let symmetry = SculptSymmetryMap::build(&mesh, SculptSymmetry::X);
        mesh.set_selection(Selection {
            vertices: HashSet::from([negative]),
            ..Selection::default()
        })?;
        let expanded = symmetry.expand_weights(&mesh, &HashMap::from([(negative, 0.75)]));
        assert_eq!(expanded.combined, HashMap::from([(negative, 0.75)]));
        assert!(!expanded.combined.contains_key(&positive));

        mesh.set_selection(Selection {
            vertices: HashSet::from([positive]),
            ..Selection::default()
        })?;
        let mirrored_after_clip =
            symmetry.expand_weights(&mesh, &HashMap::from([(negative, 0.75)]));
        assert_eq!(
            mirrored_after_clip.combined,
            HashMap::from([(positive, 0.75)])
        );
        Ok(())
    }

    #[test]
    fn symmetry_never_pairs_vertices_across_submeshes_and_off_preserves_weights() {
        let document = MeshDocument {
            format: MeshFormat::Pam,
            source_sha256: String::new(),
            parser: "symmetry-submesh-test".to_owned(),
            lod_count_reported: 1,
            lods: vec![MeshLod {
                level: 0,
                submeshes: vec![
                    submesh(
                        "negative",
                        vec![[-1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, -1.0, 0.0]],
                        vec![0, 1, 2],
                    ),
                    submesh(
                        "positive",
                        vec![[1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, -2.0, 0.0]],
                        vec![0, 1, 2],
                    ),
                ],
            }],
            warnings: Vec::new(),
            structural_fingerprint: String::new(),
        };
        let mesh = WorkingMesh::from_document(&document).expect("submesh symmetry fixture");
        let negative = handle_at(&mesh, [-1.0, 0.0, 0.0]);
        let positive = handle_at(&mesh, [1.0, 0.0, 0.0]);
        let symmetry = SculptSymmetryMap::build(&mesh, SculptSymmetry::X);
        assert_eq!(symmetry.partner(negative), None);
        assert_eq!(symmetry.partner(positive), None);

        let weights = HashMap::from([(negative, 0.5), (positive, 0.25)]);
        let off = SculptSymmetryMap::build(&mesh, SculptSymmetry::Off);
        let expanded = off.expand_weights(&mesh, &weights);
        assert_eq!(expanded.combined, weights);
        assert_eq!(expanded.primary, weights);
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
    fn layer_filtered_projection_excludes_hidden_geometry_from_picking()
    -> Result<(), Box<dyn std::error::Error>> {
        let mut document = decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
            MeshFormat::Pam,
        )?;
        let mut hidden = document.lods[0].submeshes[0].clone();
        hidden.name = "hidden".to_owned();
        for position in &mut hidden.positions {
            position[0] += 10.0;
        }
        document.lods[0].submeshes.push(hidden);
        let mesh = WorkingMesh::from_document(&document)?;
        let camera = OrbitCamera::default();
        let rectangle = Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(800.0, 600.0));
        let visible = HashSet::from([0]);
        let projection =
            ViewportProjection::build_for_submeshes(&mesh, &camera, rectangle, 7, &visible);

        let allowed = mesh.element_handles_for_submeshes(&visible);
        assert_eq!(projection.vertices.len(), 3);
        assert_eq!(
            projection
                .interaction
                .elements
                .iter()
                .filter(|element| matches!(element.handle, ProjectedHandle::Face(_)))
                .count(),
            1
        );
        assert!(
            projection
                .interaction
                .elements
                .iter()
                .all(|element| match element.handle {
                    ProjectedHandle::Vertex(handle) => allowed.vertices.contains(&handle),
                    ProjectedHandle::Edge(handle) => allowed.edges.contains(&handle),
                    ProjectedHandle::Face(handle) => allowed.faces.contains(&handle),
                })
        );
        assert!(projection.matches_for_submeshes(&mesh, &camera, rectangle, 7, &visible));
        assert!(!projection.matches(&mesh, &camera, rectangle, 7));
        Ok(())
    }

    #[test]
    fn visible_brush_excludes_nearby_back_surfaces_in_the_fitted_camera()
    -> Result<(), Box<dyn std::error::Error>> {
        let rectangle = Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(1440.0, 900.0));
        for scale in [1.0, 0.01, 100.0] {
            let mut document = decode_mesh(
                &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
                MeshFormat::Pam,
            )?;
            // A fitted perspective camera compresses the front/back separation
            // to well below 0.0001 in normalized depth, even on a thick torso.
            document.lods[0].submeshes = [-0.05, 0.05]
                .into_iter()
                .map(|depth| {
                    submesh(
                        "surface",
                        vec![
                            [-scale, -scale, depth * scale],
                            [scale, -scale, depth * scale],
                            [0.0, scale, depth * scale],
                        ],
                        vec![0, 1, 2],
                    )
                })
                .collect();
            let mut mesh = WorkingMesh::from_document(&document)?;
            let mut camera = OrbitCamera::default();
            camera.frame_all_in_viewport(&mesh, rectangle);
            let projection = ViewportProjection::build(&mesh, &camera, rectangle, 1);
            let center = Vec2::new(rectangle.center().x, rectangle.center().y);
            for domain in [
                SelectionDomain::Vertex,
                SelectionDomain::Edge,
                SelectionDomain::Face,
            ] {
                for visible_only in [false, true] {
                    let mut gesture = SelectionGesture::new(
                        &mesh,
                        SelectionTool::Brush,
                        domain,
                        SelectionOperation::Replace,
                        visible_only,
                        center,
                        1000.0,
                    );
                    gesture.update(&mut mesh, &projection.interaction, center)?;
                    let selected = mesh.selected_vertex_scope();
                    assert_eq!(
                        selected.len(),
                        if visible_only { 3 } else { 6 },
                        "{domain:?} visible={visible_only} scale={scale}"
                    );
                    if visible_only {
                        assert!(selected.iter().all(|handle| {
                            mesh.vertex(*handle)
                                .is_some_and(|vertex| vertex.position[2] < 0.0)
                        }));
                    }
                }
            }
        }
        Ok(())
    }

    #[test]
    fn fast_face_brush_selects_between_samples_and_preserves_undo()
    -> Result<(), Box<dyn std::error::Error>> {
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
            .ok_or("projected face")?;
        let start = center - Vec2::new(30.0, 0.0);
        let end = center + Vec2::new(30.0, 0.0);
        let mut gesture = SelectionGesture::new(
            &mesh,
            SelectionTool::Brush,
            SelectionDomain::Face,
            SelectionOperation::Toggle,
            true,
            start,
            4.0,
        );
        gesture.update(&mut mesh, &projection.interaction, start)?;
        assert!(mesh.selection.faces.is_empty());
        gesture.update(&mut mesh, &projection.interaction, end)?;
        assert_eq!(
            mesh.selection.faces.len(),
            1,
            "a fast brush skipped the face between samples"
        );
        gesture.update(&mut mesh, &projection.interaction, start)?;
        assert_eq!(
            mesh.selection.faces.len(),
            1,
            "revisiting a face toggled it twice in one stroke"
        );
        let mut history = History::new(1_000_000);
        assert!(gesture.commit(&mesh, &mut history)?);
        assert_eq!(history.undo_len(), 1);
        history.undo(&mut mesh)?;
        assert!(mesh.selection.faces.is_empty());
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

    #[test]
    fn pointer_queue_coalesces_motion_without_losing_navigation_distance() {
        let mut queue = PointerEventQueue::default();
        queue.push(ViewportPointerEvent::PrimaryPressed(Vec2::ZERO));
        queue.push(ViewportPointerEvent::PrimaryMoved(Vec2::new(1.0, 2.0)));
        queue.push(ViewportPointerEvent::PrimaryMoved(Vec2::new(4.0, 8.0)));
        queue.push(ViewportPointerEvent::PrimaryReleased(Vec2::new(4.0, 8.0)));
        queue.push(ViewportPointerEvent::Orbit(Vec2::new(1.0, -2.0)));
        queue.push(ViewportPointerEvent::Orbit(Vec2::new(3.0, 5.0)));
        queue.push(ViewportPointerEvent::Pan(Vec2::new(-2.0, 1.0)));
        queue.push(ViewportPointerEvent::Pan(Vec2::new(0.5, 2.0)));

        assert_eq!(
            queue.drain().collect::<Vec<_>>(),
            vec![
                ViewportPointerEvent::PrimaryPressed(Vec2::ZERO),
                ViewportPointerEvent::PrimaryMoved(Vec2::new(4.0, 8.0)),
                ViewportPointerEvent::PrimaryReleased(Vec2::new(4.0, 8.0)),
                ViewportPointerEvent::Orbit(Vec2::new(4.0, 3.0)),
                ViewportPointerEvent::Pan(Vec2::new(-1.5, 3.0)),
            ]
        );
    }

    #[test]
    fn pointer_queue_preserves_explicit_path_points_for_lasso_input() {
        let mut queue = PointerEventQueue::default();
        queue.push(ViewportPointerEvent::PrimaryPressed(Vec2::ZERO));
        queue.push_primary_path_point(Vec2::new(1.0, 2.0));
        queue.push_primary_path_point(Vec2::new(4.0, 8.0));
        queue.push(ViewportPointerEvent::PrimaryReleased(Vec2::new(4.0, 8.0)));

        assert_eq!(
            queue.drain().collect::<Vec<_>>(),
            vec![
                ViewportPointerEvent::PrimaryPressed(Vec2::ZERO),
                ViewportPointerEvent::PrimaryMoved(Vec2::new(1.0, 2.0)),
                ViewportPointerEvent::PrimaryMoved(Vec2::new(4.0, 8.0)),
                ViewportPointerEvent::PrimaryReleased(Vec2::new(4.0, 8.0)),
            ]
        );
    }
}
