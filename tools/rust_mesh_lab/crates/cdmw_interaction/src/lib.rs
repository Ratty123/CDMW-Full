#![forbid(unsafe_code)]

use cdmw_mesh::{EdgeHandle, FaceHandle, History, MeshError, Selection, VertexHandle, WorkingMesh};
use glam::{Quat, Vec2, Vec3};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use thiserror::Error;

const MAX_LASSO_POINTS: usize = 4_096;
const SCREEN_GRID_CELL_SIZE: f32 = 32.0;
const DEPTH_VISIBILITY_EPSILON: f32 = 1.0e-4;
const TRIANGLE_BVH_LEAF_SIZE: usize = 8;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum OperatorState {
    Idle,
    Armed,
    Preparing,
    Running,
    Confirming,
    Committed,
    Cancelled,
    Failed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum SelectionDomain {
    Vertex,
    Edge,
    Face,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum SelectionOperation {
    Replace,
    Add,
    Subtract,
    Toggle,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SelectionCommand {
    SelectAll,
    SelectLinked,
    Invert,
    Grow,
    Shrink,
    Clear,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum SculptTool {
    Grab,
    Smooth,
    Inflate,
    Pinch,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ProjectedHandle {
    Vertex(VertexHandle),
    Edge(EdgeHandle),
    Face(FaceHandle),
}

#[derive(Debug, Clone, PartialEq)]
pub struct ProjectedElement {
    pub handle: ProjectedHandle,
    pub position: Vec2,
    pub depth: f32,
    pub visible: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ProjectedTriangle {
    pub positions: [Vec2; 3],
    pub depths: [f32; 3],
}

#[derive(Debug, Clone, PartialEq)]
pub struct InteractionSnapshot {
    pub geometry_revision: u64,
    pub topology_generation: u64,
    pub camera_revision: u64,
    pub viewport_revision: u64,
    pub viewport_size: Vec2,
    pub elements: Vec<ProjectedElement>,
    pub depth_triangles: Vec<ProjectedTriangle>,
    spatial_index: ScreenSpaceIndex,
    depth_index: TriangleBvh,
}

impl InteractionSnapshot {
    #[must_use]
    pub fn new(
        geometry_revision: u64,
        topology_generation: u64,
        camera_revision: u64,
        viewport_revision: u64,
        viewport_size: Vec2,
        elements: Vec<ProjectedElement>,
        depth_triangles: Vec<ProjectedTriangle>,
    ) -> Self {
        let spatial_index = ScreenSpaceIndex::build(&elements);
        let depth_index = TriangleBvh::build(&depth_triangles);
        Self {
            geometry_revision,
            topology_generation,
            camera_revision,
            viewport_revision,
            viewport_size,
            elements,
            depth_triangles,
            spatial_index,
            depth_index,
        }
    }

    fn depth_visible(&self, element: &ProjectedElement) -> (bool, usize) {
        if !element.visible || !element.depth.is_finite() {
            return (false, 0);
        }
        let candidate_indices = self.depth_index.candidate_indices(element.position);
        let inspected = candidate_indices.len();
        let nearest = candidate_indices
            .into_iter()
            .filter_map(|index| self.depth_triangles.get(index))
            .filter_map(|triangle| interpolated_depth(triangle, element.position))
            .min_by(f32::total_cmp);
        let visible = nearest.is_none_or(|depth| element.depth <= depth + DEPTH_VISIBILITY_EPSILON);
        (visible, inspected)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SelectionQueryStats {
    pub candidates_inspected: usize,
    pub total_elements: usize,
    pub depth_triangles_inspected: usize,
}

#[derive(Debug, Clone, PartialEq)]
struct ScreenSpaceIndex {
    cells: HashMap<(i32, i32), Vec<usize>>,
}

impl ScreenSpaceIndex {
    fn build(elements: &[ProjectedElement]) -> Self {
        let mut cells = HashMap::<(i32, i32), Vec<usize>>::new();
        for (index, element) in elements.iter().enumerate() {
            if element.position.is_finite() {
                cells
                    .entry(cell_for(element.position))
                    .or_default()
                    .push(index);
            }
        }
        Self { cells }
    }

    fn candidate_indices(&self, shape: &SelectionShape) -> Vec<usize> {
        let Some((minimum, maximum)) = shape_bounds(shape) else {
            return Vec::new();
        };
        let low = cell_for(minimum.min(maximum));
        let high = cell_for(minimum.max(maximum));
        let width = i64::from(high.0)
            .saturating_sub(i64::from(low.0))
            .saturating_add(1);
        let height = i64::from(high.1)
            .saturating_sub(i64::from(low.1))
            .saturating_add(1);
        let cell_area = width.saturating_mul(height);
        let direct_lookup_limit = i64::try_from(self.cells.len())
            .unwrap_or(i64::MAX)
            .saturating_mul(4)
            .max(64);
        let mut indices = Vec::new();
        if cell_area <= direct_lookup_limit {
            for y in low.1..=high.1 {
                for x in low.0..=high.0 {
                    if let Some(cell) = self.cells.get(&(x, y)) {
                        indices.extend(cell);
                    }
                }
            }
        } else {
            for (&(x, y), cell) in &self.cells {
                if x >= low.0 && x <= high.0 && y >= low.1 && y <= high.1 {
                    indices.extend(cell);
                }
            }
        }
        indices.sort_unstable();
        indices
    }
}

#[derive(Debug, Clone, PartialEq, Default)]
struct TriangleBvh {
    nodes: Vec<TriangleBvhNode>,
    root: Option<usize>,
}

#[derive(Debug, Clone, PartialEq)]
struct TriangleBvhNode {
    minimum: Vec2,
    maximum: Vec2,
    left: Option<usize>,
    right: Option<usize>,
    triangles: Vec<usize>,
}

impl TriangleBvh {
    fn build(triangles: &[ProjectedTriangle]) -> Self {
        let indices = triangles
            .iter()
            .enumerate()
            .filter_map(|(index, triangle)| triangle_is_finite(triangle).then_some(index))
            .collect::<Vec<_>>();
        if indices.is_empty() {
            return Self::default();
        }
        let mut nodes = Vec::new();
        let root = Some(Self::append_node(triangles, indices, &mut nodes));
        Self { nodes, root }
    }

    fn append_node(
        triangles: &[ProjectedTriangle],
        mut indices: Vec<usize>,
        nodes: &mut Vec<TriangleBvhNode>,
    ) -> usize {
        let (minimum, maximum) = triangle_set_bounds(triangles, &indices);
        if indices.len() <= TRIANGLE_BVH_LEAF_SIZE {
            let index = nodes.len();
            nodes.push(TriangleBvhNode {
                minimum,
                maximum,
                left: None,
                right: None,
                triangles: indices,
            });
            return index;
        }
        let axis = usize::from((maximum.y - minimum.y) > (maximum.x - minimum.x));
        indices.sort_by(|first, second| {
            triangle_centroid(&triangles[*first])[axis]
                .total_cmp(&triangle_centroid(&triangles[*second])[axis])
                .then_with(|| first.cmp(second))
        });
        let right_indices = indices.split_off(indices.len() / 2);
        let left = Self::append_node(triangles, indices, nodes);
        let right = Self::append_node(triangles, right_indices, nodes);
        let index = nodes.len();
        nodes.push(TriangleBvhNode {
            minimum,
            maximum,
            left: Some(left),
            right: Some(right),
            triangles: Vec::new(),
        });
        index
    }

    fn candidate_indices(&self, point: Vec2) -> Vec<usize> {
        let Some(root) = self.root else {
            return Vec::new();
        };
        let mut stack = vec![root];
        let mut indices = Vec::new();
        while let Some(node_index) = stack.pop() {
            let Some(node) = self.nodes.get(node_index) else {
                continue;
            };
            if !point_in_bounds(point, node.minimum, node.maximum) {
                continue;
            }
            if let Some(left) = node.left {
                stack.push(left);
            }
            if let Some(right) = node.right {
                stack.push(right);
            }
            indices.extend(&node.triangles);
        }
        indices.sort_unstable();
        indices
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum SelectionShape {
    Click { point: Vec2, radius: f32 },
    Brush { point: Vec2, radius: f32 },
    Rectangle { minimum: Vec2, maximum: Vec2 },
    Lasso { points: Vec<Vec2> },
}

#[derive(Debug, Clone, PartialEq)]
pub struct SelectionQuery {
    pub domain: SelectionDomain,
    pub operation: SelectionOperation,
    pub visible_only: bool,
    pub shape: SelectionShape,
    pub geometry_revision: u64,
    pub topology_generation: u64,
    pub camera_revision: u64,
    pub viewport_revision: u64,
}

#[derive(Debug, Error)]
pub enum InteractionError {
    #[error("another modal operator already owns pointer input")]
    Busy,
    #[error("operator transition is invalid")]
    InvalidTransition,
    #[error("interaction snapshot is stale")]
    StaleSnapshot,
    #[error("selection shape contains invalid coordinates")]
    InvalidShape,
    #[error("selection shape exceeds the retained-point limit")]
    ShapeLimit,
    #[error("mesh operation failed: {0}")]
    Mesh(#[from] MeshError),
}

pub fn query_selection(
    snapshot: &InteractionSnapshot,
    query: &SelectionQuery,
) -> Result<Selection, InteractionError> {
    query_selection_with_stats(snapshot, query).map(|(selection, _)| selection)
}

pub fn query_selection_with_stats(
    snapshot: &InteractionSnapshot,
    query: &SelectionQuery,
) -> Result<(Selection, SelectionQueryStats), InteractionError> {
    if snapshot.geometry_revision != query.geometry_revision
        || snapshot.topology_generation != query.topology_generation
        || snapshot.camera_revision != query.camera_revision
        || snapshot.viewport_revision != query.viewport_revision
    {
        return Err(InteractionError::StaleSnapshot);
    }
    validate_shape(&query.shape)?;
    let mut selection = Selection::default();
    let candidate_indices = snapshot.spatial_index.candidate_indices(&query.shape);
    let mut stats = SelectionQueryStats {
        candidates_inspected: candidate_indices.len(),
        total_elements: snapshot.elements.len(),
        depth_triangles_inspected: 0,
    };
    let mut candidates = Vec::new();
    for candidate_index in candidate_indices {
        let Some(element) = snapshot.elements.get(candidate_index) else {
            continue;
        };
        if !element.position.is_finite()
            || !shape_contains(&query.shape, element.position)
            || !handle_matches_domain(element.handle, query.domain)
        {
            continue;
        }
        if query.visible_only {
            let (visible, depth_triangles_inspected) = snapshot.depth_visible(element);
            stats.depth_triangles_inspected = stats
                .depth_triangles_inspected
                .saturating_add(depth_triangles_inspected);
            if !visible {
                continue;
            }
        }
        candidates.push(element);
    }
    if let SelectionShape::Click { point, .. } = &query.shape {
        if let Some(candidate) = candidates.into_iter().min_by(|first, second| {
            first
                .position
                .distance_squared(*point)
                .total_cmp(&second.position.distance_squared(*point))
                .then_with(|| first.depth.total_cmp(&second.depth))
        }) {
            insert_candidate(&mut selection, candidate.handle);
        }
        return Ok((selection, stats));
    }
    for candidate in candidates {
        insert_candidate(&mut selection, candidate.handle);
    }
    Ok((selection, stats))
}

fn handle_matches_domain(handle: ProjectedHandle, domain: SelectionDomain) -> bool {
    matches!(
        (handle, domain),
        (ProjectedHandle::Vertex(_), SelectionDomain::Vertex)
            | (ProjectedHandle::Edge(_), SelectionDomain::Edge)
            | (ProjectedHandle::Face(_), SelectionDomain::Face)
    )
}

fn insert_candidate(selection: &mut Selection, handle: ProjectedHandle) {
    match handle {
        ProjectedHandle::Vertex(handle) => {
            selection.vertices.insert(handle);
        }
        ProjectedHandle::Edge(handle) => {
            selection.edges.insert(handle);
        }
        ProjectedHandle::Face(handle) => {
            selection.faces.insert(handle);
        }
    }
}

pub fn apply_selection(
    mesh: &mut WorkingMesh,
    operation: SelectionOperation,
    incoming: Selection,
) -> Result<(), InteractionError> {
    let next = selection_after_operation(&mesh.selection, operation, &incoming);
    mesh.set_selection(next)?;
    Ok(())
}

#[must_use]
pub fn selection_after_operation(
    base: &Selection,
    operation: SelectionOperation,
    incoming: &Selection,
) -> Selection {
    let mut next = base.clone();
    match operation {
        SelectionOperation::Replace => next = incoming.clone(),
        SelectionOperation::Add => union_selection(&mut next, incoming),
        SelectionOperation::Subtract => subtract_selection(&mut next, incoming),
        SelectionOperation::Toggle => toggle_selection(&mut next, incoming),
    }
    next
}

#[must_use]
pub fn selection_after_command(
    mesh: &WorkingMesh,
    domain: SelectionDomain,
    command: SelectionCommand,
) -> Selection {
    if command == SelectionCommand::Clear {
        return Selection::default();
    }
    let mut next = if command == SelectionCommand::SelectAll {
        Selection::default()
    } else {
        mesh.selection.clone()
    };
    match domain {
        SelectionDomain::Vertex => {
            next.vertices = vertex_selection_after_command(mesh, command);
        }
        SelectionDomain::Edge => {
            next.edges = edge_selection_after_command(mesh, command);
        }
        SelectionDomain::Face => {
            next.faces = face_selection_after_command(mesh, command);
        }
    }
    next
}

fn vertex_selection_after_command(
    mesh: &WorkingMesh,
    command: SelectionCommand,
) -> HashSet<VertexHandle> {
    let current = &mesh.selection.vertices;
    match command {
        SelectionCommand::SelectAll => mesh.vertices().map(|(handle, _)| handle).collect(),
        SelectionCommand::Invert => mesh
            .vertices()
            .map(|(handle, _)| handle)
            .filter(|handle| !current.contains(handle))
            .collect(),
        SelectionCommand::SelectLinked => {
            let mut neighbors_by_vertex = HashMap::<VertexHandle, Vec<VertexHandle>>::new();
            for (_, edge) in mesh.edges() {
                neighbors_by_vertex
                    .entry(edge.vertices[0])
                    .or_default()
                    .push(edge.vertices[1]);
                neighbors_by_vertex
                    .entry(edge.vertices[1])
                    .or_default()
                    .push(edge.vertices[0]);
            }
            let mut linked = current.clone();
            let mut frontier = current.iter().copied().collect::<Vec<_>>();
            while let Some(handle) = frontier.pop() {
                if let Some(neighbors) = neighbors_by_vertex.get(&handle) {
                    for neighbor in neighbors {
                        if linked.insert(*neighbor) {
                            frontier.push(*neighbor);
                        }
                    }
                }
            }
            linked
        }
        SelectionCommand::Grow => {
            let mut grown = current.clone();
            for (_, edge) in mesh.edges() {
                if edge.vertices.iter().any(|handle| current.contains(handle)) {
                    grown.extend(edge.vertices);
                }
            }
            grown
        }
        SelectionCommand::Shrink => {
            let mut shrunk = current.clone();
            for (_, edge) in mesh.edges() {
                let first_selected = current.contains(&edge.vertices[0]);
                let second_selected = current.contains(&edge.vertices[1]);
                if first_selected && !second_selected {
                    shrunk.remove(&edge.vertices[0]);
                }
                if second_selected && !first_selected {
                    shrunk.remove(&edge.vertices[1]);
                }
            }
            shrunk
        }
        SelectionCommand::Clear => HashSet::new(),
    }
}

fn edge_selection_after_command(
    mesh: &WorkingMesh,
    command: SelectionCommand,
) -> HashSet<EdgeHandle> {
    let current = &mesh.selection.edges;
    match command {
        SelectionCommand::SelectAll => mesh.edges().map(|(handle, _)| handle).collect(),
        SelectionCommand::Invert => mesh
            .edges()
            .map(|(handle, _)| handle)
            .filter(|handle| !current.contains(handle))
            .collect(),
        SelectionCommand::SelectLinked => {
            let mut edges_by_vertex = HashMap::<VertexHandle, Vec<EdgeHandle>>::new();
            for (handle, edge) in mesh.edges() {
                for vertex in edge.vertices {
                    edges_by_vertex.entry(vertex).or_default().push(handle);
                }
            }
            let mut linked = current.clone();
            let mut frontier = current.iter().copied().collect::<Vec<_>>();
            while let Some(handle) = frontier.pop() {
                if let Some(edge) = mesh.edge(handle) {
                    for vertex in edge.vertices {
                        if let Some(neighbors) = edges_by_vertex.get(&vertex) {
                            for neighbor in neighbors {
                                if linked.insert(*neighbor) {
                                    frontier.push(*neighbor);
                                }
                            }
                        }
                    }
                }
            }
            linked
        }
        SelectionCommand::Grow => {
            let touched_vertices = current
                .iter()
                .filter_map(|handle| mesh.edge(*handle))
                .flat_map(|edge| edge.vertices)
                .collect::<HashSet<_>>();
            let mut grown = current.clone();
            grown.extend(
                mesh.edges()
                    .filter(|(_, edge)| {
                        edge.vertices
                            .iter()
                            .any(|vertex| touched_vertices.contains(vertex))
                    })
                    .map(|(handle, _)| handle),
            );
            grown
        }
        SelectionCommand::Shrink => {
            let boundary_vertices = mesh
                .edges()
                .filter(|(handle, _)| !current.contains(handle))
                .flat_map(|(_, edge)| edge.vertices)
                .collect::<HashSet<_>>();
            current
                .iter()
                .copied()
                .filter(|handle| {
                    mesh.edge(*handle).is_some_and(|edge| {
                        edge.vertices
                            .iter()
                            .all(|vertex| !boundary_vertices.contains(vertex))
                    })
                })
                .collect()
        }
        SelectionCommand::Clear => HashSet::new(),
    }
}

fn face_selection_after_command(
    mesh: &WorkingMesh,
    command: SelectionCommand,
) -> HashSet<FaceHandle> {
    let current = &mesh.selection.faces;
    match command {
        SelectionCommand::SelectAll => mesh.faces().map(|(handle, _)| handle).collect(),
        SelectionCommand::Invert => mesh
            .faces()
            .map(|(handle, _)| handle)
            .filter(|handle| !current.contains(handle))
            .collect(),
        SelectionCommand::SelectLinked => {
            let mut edges_by_face = HashMap::<FaceHandle, Vec<EdgeHandle>>::new();
            for (edge_handle, edge) in mesh.edges() {
                for face in &edge.faces {
                    edges_by_face.entry(*face).or_default().push(edge_handle);
                }
            }
            let mut linked = current.clone();
            let mut frontier = current.iter().copied().collect::<Vec<_>>();
            while let Some(handle) = frontier.pop() {
                if let Some(edges) = edges_by_face.get(&handle) {
                    for edge_handle in edges {
                        if let Some(edge) = mesh.edge(*edge_handle) {
                            for neighbor in &edge.faces {
                                if linked.insert(*neighbor) {
                                    frontier.push(*neighbor);
                                }
                            }
                        }
                    }
                }
            }
            linked
        }
        SelectionCommand::Grow => {
            let mut grown = current.clone();
            for (_, edge) in mesh.edges() {
                if edge.faces.iter().any(|face| current.contains(face)) {
                    grown.extend(edge.faces.iter().copied());
                }
            }
            grown
        }
        SelectionCommand::Shrink => {
            let mut boundary = HashSet::new();
            for (_, edge) in mesh.edges() {
                let has_selected = edge.faces.iter().any(|face| current.contains(face));
                let has_unselected = edge.faces.iter().any(|face| !current.contains(face));
                if has_selected && has_unselected {
                    boundary.extend(
                        edge.faces
                            .iter()
                            .filter(|face| current.contains(face))
                            .copied(),
                    );
                }
            }
            current.difference(&boundary).copied().collect()
        }
        SelectionCommand::Clear => HashSet::new(),
    }
}

fn union_selection(target: &mut Selection, incoming: &Selection) {
    target.vertices.extend(&incoming.vertices);
    target.edges.extend(&incoming.edges);
    target.faces.extend(&incoming.faces);
    target.submeshes.extend(&incoming.submeshes);
}

fn subtract_selection(target: &mut Selection, incoming: &Selection) {
    target
        .vertices
        .retain(|handle| !incoming.vertices.contains(handle));
    target
        .edges
        .retain(|handle| !incoming.edges.contains(handle));
    target
        .faces
        .retain(|handle| !incoming.faces.contains(handle));
    target
        .submeshes
        .retain(|handle| !incoming.submeshes.contains(handle));
}

fn toggle_selection(target: &mut Selection, incoming: &Selection) {
    toggle_set(&mut target.vertices, &incoming.vertices);
    toggle_set(&mut target.edges, &incoming.edges);
    toggle_set(&mut target.faces, &incoming.faces);
    toggle_set(&mut target.submeshes, &incoming.submeshes);
}

fn toggle_set<T: Copy + Eq + std::hash::Hash>(target: &mut HashSet<T>, incoming: &HashSet<T>) {
    for handle in incoming {
        if !target.remove(handle) {
            target.insert(*handle);
        }
    }
}

fn validate_shape(shape: &SelectionShape) -> Result<(), InteractionError> {
    let valid = match shape {
        SelectionShape::Click { point, radius } | SelectionShape::Brush { point, radius } => {
            point.is_finite() && radius.is_finite() && *radius >= 0.0
        }
        SelectionShape::Rectangle { minimum, maximum } => {
            minimum.is_finite() && maximum.is_finite()
        }
        SelectionShape::Lasso { points } => {
            if points.len() > MAX_LASSO_POINTS {
                return Err(InteractionError::ShapeLimit);
            }
            points.len() >= 3 && points.iter().all(|point| point.is_finite())
        }
    };
    if valid {
        Ok(())
    } else {
        Err(InteractionError::InvalidShape)
    }
}

fn shape_bounds(shape: &SelectionShape) -> Option<(Vec2, Vec2)> {
    match shape {
        SelectionShape::Click { point, radius } | SelectionShape::Brush { point, radius } => {
            let extent = Vec2::splat(*radius);
            Some((*point - extent, *point + extent))
        }
        SelectionShape::Rectangle { minimum, maximum } => Some((*minimum, *maximum)),
        SelectionShape::Lasso { points } => {
            let first = points.first().copied()?;
            Some(
                points
                    .iter()
                    .copied()
                    .fold((first, first), |(low, high), point| {
                        (low.min(point), high.max(point))
                    }),
            )
        }
    }
}

fn cell_for(point: Vec2) -> (i32, i32) {
    (
        (point.x / SCREEN_GRID_CELL_SIZE).floor() as i32,
        (point.y / SCREEN_GRID_CELL_SIZE).floor() as i32,
    )
}

fn triangle_is_finite(triangle: &ProjectedTriangle) -> bool {
    triangle.positions.iter().all(|point| point.is_finite())
        && triangle.depths.iter().all(|depth| depth.is_finite())
}

fn triangle_bounds(triangle: &ProjectedTriangle) -> (Vec2, Vec2) {
    triangle.positions.iter().copied().fold(
        (Vec2::splat(f32::INFINITY), Vec2::splat(f32::NEG_INFINITY)),
        |(minimum, maximum), point| (minimum.min(point), maximum.max(point)),
    )
}

fn triangle_set_bounds(triangles: &[ProjectedTriangle], indices: &[usize]) -> (Vec2, Vec2) {
    indices.iter().fold(
        (Vec2::splat(f32::INFINITY), Vec2::splat(f32::NEG_INFINITY)),
        |(minimum, maximum), index| {
            let (triangle_minimum, triangle_maximum) = triangle_bounds(&triangles[*index]);
            (minimum.min(triangle_minimum), maximum.max(triangle_maximum))
        },
    )
}

fn triangle_centroid(triangle: &ProjectedTriangle) -> Vec2 {
    (triangle.positions[0] + triangle.positions[1] + triangle.positions[2]) / 3.0
}

fn point_in_bounds(point: Vec2, minimum: Vec2, maximum: Vec2) -> bool {
    let tolerance = Vec2::splat(1.0e-3);
    point.cmpge(minimum - tolerance).all() && point.cmple(maximum + tolerance).all()
}

fn interpolated_depth(triangle: &ProjectedTriangle, point: Vec2) -> Option<f32> {
    let [a, b, c] = triangle.positions;
    let denominator = (b.y - c.y) * (a.x - c.x) + (c.x - b.x) * (a.y - c.y);
    if !denominator.is_finite() || denominator.abs() <= f32::EPSILON {
        return None;
    }
    let first = ((b.y - c.y) * (point.x - c.x) + (c.x - b.x) * (point.y - c.y)) / denominator;
    let second = ((c.y - a.y) * (point.x - c.x) + (a.x - c.x) * (point.y - c.y)) / denominator;
    let third = 1.0 - first - second;
    let barycentric_tolerance = -1.0e-5;
    if first < barycentric_tolerance
        || second < barycentric_tolerance
        || third < barycentric_tolerance
    {
        return None;
    }
    let depth =
        triangle.depths[0] * first + triangle.depths[1] * second + triangle.depths[2] * third;
    depth.is_finite().then_some(depth)
}

fn shape_contains(shape: &SelectionShape, point: Vec2) -> bool {
    match shape {
        SelectionShape::Click {
            point: center,
            radius,
        }
        | SelectionShape::Brush {
            point: center,
            radius,
        } => point.distance_squared(*center) <= radius * radius,
        SelectionShape::Rectangle { minimum, maximum } => {
            let low = minimum.min(*maximum);
            let high = minimum.max(*maximum);
            point.cmpge(low).all() && point.cmple(high).all()
        }
        SelectionShape::Lasso { points } => point_in_polygon(point, points),
    }
}

fn point_in_polygon(point: Vec2, polygon: &[Vec2]) -> bool {
    let mut inside = false;
    let Some(mut previous) = polygon.last().copied() else {
        return false;
    };
    for current in polygon {
        let crosses = (current.y > point.y) != (previous.y > point.y);
        if crosses {
            let denominator = previous.y - current.y;
            if denominator.abs() > f32::EPSILON {
                let x = (previous.x - current.x) * (point.y - current.y) / denominator + current.x;
                if point.x < x {
                    inside = !inside;
                }
            }
        }
        previous = *current;
    }
    inside
}

#[derive(Debug, Clone)]
pub struct ModalOperator {
    pub state: OperatorState,
    pub gesture_id: u64,
    pub label: String,
    pub base_geometry_revision: u64,
    pub base_topology_generation: u64,
    pub base_selection_revision: u64,
    before: WorkingMesh,
}

#[derive(Debug)]
pub struct OperatorController {
    active: Option<ModalOperator>,
    next_gesture_id: u64,
}

impl Default for OperatorController {
    fn default() -> Self {
        Self {
            active: None,
            next_gesture_id: 1,
        }
    }
}

impl OperatorController {
    pub fn begin(
        &mut self,
        mesh: &WorkingMesh,
        label: impl Into<String>,
    ) -> Result<u64, InteractionError> {
        if self.active.is_some() {
            return Err(InteractionError::Busy);
        }
        let gesture_id = self.next_gesture_id;
        self.next_gesture_id = self.next_gesture_id.saturating_add(1);
        self.active = Some(ModalOperator {
            state: OperatorState::Running,
            gesture_id,
            label: label.into(),
            base_geometry_revision: mesh.geometry_revision,
            base_topology_generation: mesh.topology_generation,
            base_selection_revision: mesh.selection_revision,
            before: mesh.clone(),
        });
        Ok(gesture_id)
    }

    pub fn translate(
        &self,
        mesh: &mut WorkingMesh,
        gesture_id: u64,
        handles: &HashSet<VertexHandle>,
        delta: Vec3,
    ) -> Result<(), InteractionError> {
        self.require_running(gesture_id)?;
        mesh.translate_vertices(handles, delta)?;
        Ok(())
    }

    pub fn rotate(
        &self,
        mesh: &mut WorkingMesh,
        gesture_id: u64,
        handles: &HashSet<VertexHandle>,
        pivot: Vec3,
        rotation: Quat,
    ) -> Result<(), InteractionError> {
        self.require_running(gesture_id)?;
        mesh.rotate_vertices(handles, pivot, rotation)?;
        Ok(())
    }

    pub fn scale(
        &self,
        mesh: &mut WorkingMesh,
        gesture_id: u64,
        handles: &HashSet<VertexHandle>,
        pivot: Vec3,
        scale: Vec3,
    ) -> Result<(), InteractionError> {
        self.require_running(gesture_id)?;
        mesh.scale_vertices(handles, pivot, scale)?;
        Ok(())
    }

    pub fn sculpt(
        &self,
        mesh: &mut WorkingMesh,
        gesture_id: u64,
        tool: SculptTool,
        handles: &HashSet<VertexHandle>,
        center: Vec3,
        delta: Vec3,
        strength: f32,
    ) -> Result<(), InteractionError> {
        let weights = handles
            .iter()
            .copied()
            .map(|handle| (handle, 1.0))
            .collect::<HashMap<_, _>>();
        self.sculpt_weighted(mesh, gesture_id, tool, &weights, center, delta, strength)
    }

    pub fn sculpt_weighted(
        &self,
        mesh: &mut WorkingMesh,
        gesture_id: u64,
        tool: SculptTool,
        weights: &HashMap<VertexHandle, f32>,
        center: Vec3,
        delta: Vec3,
        strength: f32,
    ) -> Result<(), InteractionError> {
        self.require_running(gesture_id)?;
        if weights.is_empty()
            || !center.is_finite()
            || !delta.is_finite()
            || !strength.is_finite()
            || weights
                .values()
                .any(|weight| !weight.is_finite() || !(0.0..=1.0).contains(weight))
        {
            return Err(InteractionError::InvalidShape);
        }
        let original = weights
            .iter()
            .map(|(handle, weight)| {
                let vertex = mesh.vertex(*handle).ok_or(MeshError::StaleHandle)?;
                Ok((
                    *handle,
                    *weight,
                    Vec3::from_array(vertex.position),
                    Vec3::from_array(vertex.normal),
                ))
            })
            .collect::<Result<Vec<_>, MeshError>>()?;
        let mut positions = HashMap::new();
        for (handle, weight, position, normal) in original {
            let weighted_strength = strength * weight;
            let next = match tool {
                SculptTool::Grab => position + delta * weighted_strength,
                SculptTool::Inflate => {
                    position + normal.try_normalize().unwrap_or(Vec3::Y) * weighted_strength
                }
                SculptTool::Pinch => {
                    position + (center - position) * weighted_strength.clamp(-1.0, 1.0)
                }
                SculptTool::Smooth => {
                    let mut neighbors = mesh
                        .vertex_neighbors(handle)
                        .ok_or(MeshError::StaleHandle)?
                        .into_iter()
                        .collect::<Vec<_>>();
                    if neighbors.is_empty() {
                        position
                    } else {
                        neighbors.sort_unstable();
                        let total = neighbors.iter().try_fold(Vec3::ZERO, |sum, neighbor| {
                            mesh.vertex(*neighbor)
                                .map(|vertex| sum + Vec3::from_array(vertex.position))
                                .ok_or(MeshError::StaleHandle)
                        })?;
                        let average = total / neighbors.len() as f32;
                        position.lerp(average, weighted_strength.clamp(0.0, 1.0))
                    }
                }
            };
            positions.insert(handle, next.to_array());
        }
        mesh.apply_positions(&positions)?;
        Ok(())
    }

    pub fn confirm(
        &mut self,
        mesh: &mut WorkingMesh,
        history: &mut History,
        gesture_id: u64,
    ) -> Result<(), InteractionError> {
        let mut operator = self
            .active
            .take()
            .ok_or(InteractionError::InvalidTransition)?;
        if operator.gesture_id != gesture_id || operator.state != OperatorState::Running {
            self.active = Some(operator);
            return Err(InteractionError::InvalidTransition);
        }
        operator.state = OperatorState::Confirming;
        if let Err(error) = mesh.validate() {
            operator.state = OperatorState::Failed;
            *mesh = operator.before;
            return Err(error.into());
        }
        let before = operator.before;
        if let Err(error) = history.commit(operator.label.clone(), before.clone(), mesh) {
            *mesh = before;
            operator.state = OperatorState::Failed;
            return Err(error.into());
        }
        operator.state = OperatorState::Committed;
        Ok(())
    }

    pub fn cancel(
        &mut self,
        mesh: &mut WorkingMesh,
        gesture_id: u64,
    ) -> Result<(), InteractionError> {
        let mut operator = self
            .active
            .take()
            .ok_or(InteractionError::InvalidTransition)?;
        if operator.gesture_id != gesture_id || operator.state != OperatorState::Running {
            self.active = Some(operator);
            return Err(InteractionError::InvalidTransition);
        }
        *mesh = operator.before;
        operator.state = OperatorState::Cancelled;
        Ok(())
    }

    fn require_running(&self, gesture_id: u64) -> Result<(), InteractionError> {
        self.active
            .as_ref()
            .filter(|operator| {
                operator.gesture_id == gesture_id && operator.state == OperatorState::Running
            })
            .map(|_| ())
            .ok_or(InteractionError::InvalidTransition)
    }

    #[must_use]
    pub fn state(&self) -> OperatorState {
        self.active
            .as_ref()
            .map_or(OperatorState::Idle, |operator| operator.state)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use cdmw_formats::{MeshDocument, MeshFormat, MeshLod, SourceRange, Submesh, decode_mesh};

    #[test]
    fn reversed_lasso_winding_selects_the_same_point() -> Result<(), InteractionError> {
        let clockwise = SelectionShape::Lasso {
            points: vec![Vec2::ZERO, Vec2::X, Vec2::ONE, Vec2::Y],
        };
        let counter_clockwise = SelectionShape::Lasso {
            points: vec![Vec2::Y, Vec2::ONE, Vec2::X, Vec2::ZERO],
        };
        validate_shape(&clockwise)?;
        validate_shape(&counter_clockwise)?;
        assert_eq!(
            shape_contains(&clockwise, Vec2::splat(0.5)),
            shape_contains(&counter_clockwise, Vec2::splat(0.5))
        );
        Ok(())
    }

    #[test]
    fn topology_selection_commands_are_exact_for_vertices_edges_and_faces()
    -> Result<(), Box<dyn std::error::Error>> {
        let document = decode_mesh(&cdmw_formats::synthetic::two_lod_pac(), MeshFormat::Pac)?;
        let mut mesh = WorkingMesh::from_document_lod(&document, 1)?;
        let vertex_count = mesh.vertices().count();
        let edge_count = mesh.edges().count();
        let face_count = mesh.faces().count();
        assert_eq!((vertex_count, edge_count, face_count), (4, 5, 2));

        let corner = mesh
            .vertices()
            .map(|(handle, _)| handle)
            .find(|handle| {
                mesh.vertex_neighbors(*handle)
                    .is_some_and(|neighbors| neighbors.len() == 2)
            })
            .ok_or("missing quad corner")?;
        let retained_face = mesh
            .faces()
            .next()
            .map(|(handle, _)| handle)
            .ok_or("missing face")?;
        mesh.set_selection(Selection {
            vertices: HashSet::from([corner]),
            faces: HashSet::from([retained_face]),
            ..Selection::default()
        })?;
        let grown_vertices =
            selection_after_command(&mesh, SelectionDomain::Vertex, SelectionCommand::Grow);
        assert_eq!(grown_vertices.vertices.len(), 3);
        assert!(grown_vertices.vertices.contains(&corner));
        assert_eq!(grown_vertices.faces, HashSet::from([retained_face]));
        mesh.set_selection(grown_vertices)?;
        let shrunk_vertices =
            selection_after_command(&mesh, SelectionDomain::Vertex, SelectionCommand::Shrink);
        assert_eq!(shrunk_vertices.vertices, HashSet::from([corner]));
        assert_eq!(shrunk_vertices.faces, HashSet::from([retained_face]));
        mesh.set_selection(shrunk_vertices)?;
        let inverted_vertices =
            selection_after_command(&mesh, SelectionDomain::Vertex, SelectionCommand::Invert);
        assert_eq!(inverted_vertices.vertices.len(), vertex_count - 1);
        assert!(!inverted_vertices.vertices.contains(&corner));
        assert_eq!(inverted_vertices.faces, HashSet::from([retained_face]));
        let all_vertices =
            selection_after_command(&mesh, SelectionDomain::Vertex, SelectionCommand::SelectAll);
        assert_eq!(all_vertices.vertices.len(), vertex_count);
        assert!(all_vertices.edges.is_empty() && all_vertices.faces.is_empty());

        let boundary_edge = mesh
            .edges()
            .find(|(_, edge)| edge.faces.len() == 1)
            .map(|(handle, _)| handle)
            .ok_or("missing boundary edge")?;
        mesh.set_selection(Selection {
            edges: HashSet::from([boundary_edge]),
            ..Selection::default()
        })?;
        let grown_edges =
            selection_after_command(&mesh, SelectionDomain::Edge, SelectionCommand::Grow);
        assert!(grown_edges.edges.len() > 1);
        assert!(grown_edges.edges.contains(&boundary_edge));
        let shrunk_edges =
            selection_after_command(&mesh, SelectionDomain::Edge, SelectionCommand::Shrink);
        assert!(shrunk_edges.edges.is_empty());
        let inverted_edges =
            selection_after_command(&mesh, SelectionDomain::Edge, SelectionCommand::Invert);
        assert_eq!(inverted_edges.edges.len(), edge_count - 1);
        assert!(!inverted_edges.edges.contains(&boundary_edge));

        mesh.set_selection(Selection {
            faces: HashSet::from([retained_face]),
            ..Selection::default()
        })?;
        let grown_faces =
            selection_after_command(&mesh, SelectionDomain::Face, SelectionCommand::Grow);
        assert_eq!(grown_faces.faces.len(), face_count);
        let shrunk_faces =
            selection_after_command(&mesh, SelectionDomain::Face, SelectionCommand::Shrink);
        assert!(shrunk_faces.faces.is_empty());
        let inverted_faces =
            selection_after_command(&mesh, SelectionDomain::Face, SelectionCommand::Invert);
        assert_eq!(inverted_faces.faces.len(), face_count - 1);
        assert!(!inverted_faces.faces.contains(&retained_face));
        assert_eq!(
            selection_after_command(&mesh, SelectionDomain::Face, SelectionCommand::Clear),
            Selection::default()
        );
        Ok(())
    }

    #[test]
    fn select_linked_stays_inside_the_seeded_component_for_every_domain()
    -> Result<(), Box<dyn std::error::Error>> {
        let document = decode_mesh(&cdmw_formats::synthetic::two_lod_pac(), MeshFormat::Pac)?;
        let mut mesh = WorkingMesh::from_document_lod(&document, 1)?;
        let source_vertices = mesh
            .vertices()
            .map(|(handle, _)| handle)
            .collect::<HashSet<_>>();
        let source_faces = mesh
            .faces()
            .map(|(handle, _)| handle)
            .collect::<HashSet<_>>();
        let duplicated_faces = mesh.duplicate_faces(&source_faces)?;
        assert_eq!(
            (
                mesh.vertices().count(),
                mesh.edges().count(),
                mesh.faces().count()
            ),
            (8, 10, 4)
        );

        let vertex_seed = *source_vertices
            .iter()
            .next()
            .ok_or("missing source vertex")?;
        let preserved_face = *duplicated_faces
            .iter()
            .next()
            .ok_or("missing duplicate face")?;
        mesh.set_selection(Selection {
            vertices: HashSet::from([vertex_seed]),
            faces: HashSet::from([preserved_face]),
            ..Selection::default()
        })?;
        let linked_vertices = selection_after_command(
            &mesh,
            SelectionDomain::Vertex,
            SelectionCommand::SelectLinked,
        );
        assert_eq!(linked_vertices.vertices, source_vertices);
        assert_eq!(linked_vertices.faces, HashSet::from([preserved_face]));

        let edge_seed = mesh
            .edges()
            .find(|(_, edge)| {
                edge.vertices
                    .iter()
                    .all(|vertex| source_vertices.contains(vertex))
            })
            .map(|(handle, _)| handle)
            .ok_or("missing source edge")?;
        mesh.set_selection(Selection {
            edges: HashSet::from([edge_seed]),
            ..Selection::default()
        })?;
        let linked_edges =
            selection_after_command(&mesh, SelectionDomain::Edge, SelectionCommand::SelectLinked);
        assert_eq!(linked_edges.edges.len(), 5);
        assert!(linked_edges.edges.iter().all(|handle| {
            mesh.edge(*handle).is_some_and(|edge| {
                edge.vertices
                    .iter()
                    .all(|vertex| source_vertices.contains(vertex))
            })
        }));

        let face_seed = *source_faces.iter().next().ok_or("missing source face")?;
        mesh.set_selection(Selection {
            faces: HashSet::from([face_seed]),
            ..Selection::default()
        })?;
        let linked_faces =
            selection_after_command(&mesh, SelectionDomain::Face, SelectionCommand::SelectLinked);
        assert_eq!(linked_faces.faces, source_faces);
        assert!(linked_faces.faces.is_disjoint(&duplicated_faces));

        mesh.set_selection(Selection::default())?;
        assert_eq!(
            selection_after_command(&mesh, SelectionDomain::Face, SelectionCommand::SelectLinked),
            Selection::default()
        );
        Ok(())
    }

    #[test]
    fn stale_snapshot_is_rejected_before_selection() {
        let snapshot =
            InteractionSnapshot::new(2, 1, 1, 1, Vec2::splat(100.0), Vec::new(), Vec::new());
        let query = SelectionQuery {
            domain: SelectionDomain::Vertex,
            operation: SelectionOperation::Replace,
            visible_only: true,
            shape: SelectionShape::Click {
                point: Vec2::ZERO,
                radius: 4.0,
            },
            geometry_revision: 1,
            topology_generation: 1,
            camera_revision: 1,
            viewport_revision: 1,
        };
        assert!(matches!(
            query_selection(&snapshot, &query),
            Err(InteractionError::StaleSnapshot)
        ));
    }

    #[test]
    fn click_selects_only_the_nearest_candidate() -> Result<(), Box<dyn std::error::Error>> {
        let document = decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
            MeshFormat::Pam,
        )?;
        let mesh = WorkingMesh::from_document(&document)?;
        let handles = mesh
            .vertices()
            .map(|(handle, _)| handle)
            .collect::<Vec<_>>();
        let snapshot = InteractionSnapshot::new(
            mesh.geometry_revision,
            mesh.topology_generation,
            1,
            1,
            Vec2::splat(100.0),
            vec![
                ProjectedElement {
                    handle: ProjectedHandle::Vertex(handles[0]),
                    position: Vec2::new(2.0, 0.0),
                    depth: 0.5,
                    visible: true,
                },
                ProjectedElement {
                    handle: ProjectedHandle::Vertex(handles[1]),
                    position: Vec2::new(5.0, 0.0),
                    depth: 0.2,
                    visible: true,
                },
            ],
            Vec::new(),
        );
        let query = SelectionQuery {
            domain: SelectionDomain::Vertex,
            operation: SelectionOperation::Replace,
            visible_only: false,
            shape: SelectionShape::Click {
                point: Vec2::ZERO,
                radius: 10.0,
            },
            geometry_revision: mesh.geometry_revision,
            topology_generation: mesh.topology_generation,
            camera_revision: 1,
            viewport_revision: 1,
        };
        let selected = query_selection(&snapshot, &query)?;
        assert_eq!(selected.vertices, HashSet::from([handles[0]]));
        Ok(())
    }

    #[test]
    fn visible_only_rejects_an_element_behind_the_depth_surface()
    -> Result<(), Box<dyn std::error::Error>> {
        let document = decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
            MeshFormat::Pam,
        )?;
        let mesh = WorkingMesh::from_document(&document)?;
        let handles = mesh
            .vertices()
            .map(|(handle, _)| handle)
            .collect::<Vec<_>>();
        let snapshot = InteractionSnapshot::new(
            mesh.geometry_revision,
            mesh.topology_generation,
            1,
            1,
            Vec2::splat(100.0),
            vec![
                ProjectedElement {
                    handle: ProjectedHandle::Vertex(handles[0]),
                    position: Vec2::ZERO,
                    depth: 0.2,
                    visible: true,
                },
                ProjectedElement {
                    handle: ProjectedHandle::Vertex(handles[1]),
                    position: Vec2::ZERO,
                    depth: 0.8,
                    visible: true,
                },
            ],
            vec![ProjectedTriangle {
                positions: [
                    Vec2::new(-10.0, -10.0),
                    Vec2::new(10.0, -10.0),
                    Vec2::new(0.0, 10.0),
                ],
                depths: [0.2; 3],
            }],
        );
        let mut query = SelectionQuery {
            domain: SelectionDomain::Vertex,
            operation: SelectionOperation::Replace,
            visible_only: false,
            shape: SelectionShape::Brush {
                point: Vec2::ZERO,
                radius: 2.0,
            },
            geometry_revision: mesh.geometry_revision,
            topology_generation: mesh.topology_generation,
            camera_revision: 1,
            viewport_revision: 1,
        };
        let xray = query_selection(&snapshot, &query)?;
        assert_eq!(xray.vertices, HashSet::from([handles[0], handles[1]]));
        query.visible_only = true;
        let (visible, stats) = query_selection_with_stats(&snapshot, &query)?;
        assert_eq!(visible.vertices, HashSet::from([handles[0]]));
        assert_eq!(stats.depth_triangles_inspected, 2);
        Ok(())
    }

    #[test]
    fn depth_bvh_bounds_local_visibility_candidates() -> Result<(), Box<dyn std::error::Error>> {
        let document = decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
            MeshFormat::Pam,
        )?;
        let mesh = WorkingMesh::from_document(&document)?;
        let handle = mesh
            .vertices()
            .next()
            .map(|(handle, _)| handle)
            .ok_or("missing synthetic vertex")?;
        let depth_triangles = (0..16_384)
            .map(|index| {
                let origin = Vec2::new((index % 128) as f32 * 8.0, (index / 128) as f32 * 8.0);
                ProjectedTriangle {
                    positions: [
                        origin,
                        origin + Vec2::new(3.0, 0.0),
                        origin + Vec2::new(0.0, 3.0),
                    ],
                    depths: [0.3; 3],
                }
            })
            .collect::<Vec<_>>();
        let point = Vec2::new(64.0 * 8.0 + 1.0, 64.0 * 8.0 + 1.0);
        let snapshot = InteractionSnapshot::new(
            mesh.geometry_revision,
            mesh.topology_generation,
            1,
            1,
            Vec2::splat(1_024.0),
            vec![ProjectedElement {
                handle: ProjectedHandle::Vertex(handle),
                position: point,
                depth: 0.3,
                visible: true,
            }],
            depth_triangles,
        );
        let query = SelectionQuery {
            domain: SelectionDomain::Vertex,
            operation: SelectionOperation::Replace,
            visible_only: true,
            shape: SelectionShape::Click { point, radius: 2.0 },
            geometry_revision: mesh.geometry_revision,
            topology_generation: mesh.topology_generation,
            camera_revision: 1,
            viewport_revision: 1,
        };
        let (selection, stats) = query_selection_with_stats(&snapshot, &query)?;
        assert_eq!(selection.vertices, HashSet::from([handle]));
        assert!(stats.depth_triangles_inspected <= 32, "{stats:?}");
        Ok(())
    }

    #[test]
    fn local_query_uses_a_bounded_screen_grid_candidate_set()
    -> Result<(), Box<dyn std::error::Error>> {
        let document = decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
            MeshFormat::Pam,
        )?;
        let mesh = WorkingMesh::from_document(&document)?;
        let handle = mesh
            .vertices()
            .next()
            .map(|(handle, _)| handle)
            .ok_or("missing synthetic vertex")?;
        let elements = (0..100_000)
            .map(|index| ProjectedElement {
                handle: ProjectedHandle::Vertex(handle),
                position: Vec2::new((index % 1_000) as f32 * 8.0, (index / 1_000) as f32 * 8.0),
                depth: 0.5,
                visible: true,
            })
            .collect::<Vec<_>>();
        let snapshot = InteractionSnapshot::new(
            mesh.geometry_revision,
            mesh.topology_generation,
            1,
            1,
            Vec2::new(8_000.0, 800.0),
            elements,
            Vec::new(),
        );
        let query = SelectionQuery {
            domain: SelectionDomain::Vertex,
            operation: SelectionOperation::Replace,
            visible_only: false,
            shape: SelectionShape::Click {
                point: Vec2::new(4_000.0, 400.0),
                radius: 4.0,
            },
            geometry_revision: mesh.geometry_revision,
            topology_generation: mesh.topology_generation,
            camera_revision: 1,
            viewport_revision: 1,
        };
        let (selected, stats) = query_selection_with_stats(&snapshot, &query)?;
        assert_eq!(stats.total_elements, 100_000);
        assert!(stats.candidates_inspected <= 64, "{stats:?}");
        assert_eq!(selected.vertices, HashSet::from([handle]));
        Ok(())
    }

    #[test]
    fn one_hundred_cancelled_gestures_restore_the_exact_fingerprint()
    -> Result<(), Box<dyn std::error::Error>> {
        let document = decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
            MeshFormat::Pam,
        )?;
        let mut mesh = WorkingMesh::from_document(&document)?;
        let baseline = mesh.structural_fingerprint();
        let handles = mesh
            .vertices()
            .map(|(handle, _)| handle)
            .collect::<HashSet<_>>();
        let mut controller = OperatorController::default();
        for _ in 0..100 {
            let gesture = controller.begin(&mesh, "cancel stress")?;
            controller.translate(&mut mesh, gesture, &handles, Vec3::splat(0.01))?;
            controller.cancel(&mut mesh, gesture)?;
            assert_eq!(mesh.structural_fingerprint(), baseline);
            assert_eq!(controller.state(), OperatorState::Idle);
        }
        Ok(())
    }

    #[test]
    fn one_hundred_lasso_variants_are_winding_stable() -> Result<(), InteractionError> {
        for index in 0..100 {
            let inset = index as f32 * 0.0001;
            let forward = SelectionShape::Lasso {
                points: vec![
                    Vec2::splat(inset),
                    Vec2::new(1.0 - inset, inset),
                    Vec2::splat(1.0 - inset),
                    Vec2::new(inset, 1.0 - inset),
                ],
            };
            let mut reverse_points = match &forward {
                SelectionShape::Lasso { points } => points.clone(),
                _ => Vec::new(),
            };
            reverse_points.reverse();
            let reverse = SelectionShape::Lasso {
                points: reverse_points,
            };
            validate_shape(&forward)?;
            validate_shape(&reverse)?;
            assert_eq!(
                shape_contains(&forward, Vec2::splat(0.5)),
                shape_contains(&reverse, Vec2::splat(0.5))
            );
        }
        Ok(())
    }

    #[test]
    fn rotate_and_scale_share_one_modal_history_transaction()
    -> Result<(), Box<dyn std::error::Error>> {
        let document = decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
            MeshFormat::Pam,
        )?;
        let mut mesh = WorkingMesh::from_document(&document)?;
        let handles = mesh
            .vertices()
            .map(|(handle, _)| handle)
            .collect::<HashSet<_>>();
        let mut controller = OperatorController::default();
        let mut history = History::new(1_000_000);
        let gesture = controller.begin(&mesh, "rotate and scale")?;
        controller.rotate(
            &mut mesh,
            gesture,
            &handles,
            Vec3::ZERO,
            Quat::from_rotation_z(0.25),
        )?;
        controller.scale(&mut mesh, gesture, &handles, Vec3::ZERO, Vec3::splat(1.1))?;
        controller.confirm(&mut mesh, &mut history, gesture)?;
        assert_eq!(history.undo_len(), 1);
        assert_eq!(controller.state(), OperatorState::Idle);
        Ok(())
    }

    #[test]
    fn smooth_uses_stable_neighbor_order_for_exact_replay() -> Result<(), Box<dyn std::error::Error>>
    {
        let neighbor_x = [1.0e20, 1.0, -1.0e20, 2.0, 1.0e20, -3.0, -1.0e20, 4.0];
        let mut positions = vec![[0.0, 0.0, 0.0]];
        positions.extend(
            neighbor_x
                .iter()
                .enumerate()
                .map(|(index, x)| [*x, index as f32 + 1.0, 0.0]),
        );
        let mut indices = Vec::new();
        for index in 1..=neighbor_x.len() {
            indices.extend_from_slice(&[
                0,
                u32::try_from(index)?,
                u32::try_from(index % neighbor_x.len() + 1)?,
            ]);
        }
        let vertex_count = positions.len();
        let document = MeshDocument {
            format: MeshFormat::Pam,
            source_sha256: "order-sensitive-synthetic".to_owned(),
            parser: "test".to_owned(),
            lod_count_reported: 1,
            lods: vec![MeshLod {
                level: 0,
                submeshes: vec![Submesh {
                    name: "fan".to_owned(),
                    material: String::new(),
                    positions,
                    normals: vec![[0.0, 1.0, 0.0]; vertex_count],
                    uvs: vec![[0.0, 0.0]; vertex_count],
                    indices,
                    source_vertex_indices: (0..vertex_count)
                        .map(i32::try_from)
                        .collect::<Result<Vec<_>, _>>()?,
                    source_range: SourceRange {
                        offset: 0,
                        length: 0,
                    },
                    vertex_stride: 12,
                    layout: "test_fan".to_owned(),
                }],
            }],
            warnings: Vec::new(),
            structural_fingerprint: "test".to_owned(),
        };
        let mut expected = None;
        for _ in 0..64 {
            let mut mesh = WorkingMesh::from_document(&document)?;
            let center = mesh
                .vertices()
                .next()
                .map(|(handle, _)| handle)
                .ok_or("missing fan center")?;
            let handles = HashSet::from([center]);
            let mut controller = OperatorController::default();
            let gesture = controller.begin(&mesh, "deterministic smooth")?;
            controller.sculpt(
                &mut mesh,
                gesture,
                SculptTool::Smooth,
                &handles,
                Vec3::ZERO,
                Vec3::ZERO,
                1.0,
            )?;
            let mut history = History::new(1_000_000);
            controller.confirm(&mut mesh, &mut history, gesture)?;
            let fingerprint = mesh.structural_fingerprint();
            if let Some(expected) = &expected {
                assert_eq!(&fingerprint, expected);
            } else {
                expected = Some(fingerprint);
            }
        }
        Ok(())
    }

    #[test]
    fn weighted_sculpt_scales_only_the_supplied_vertices() -> Result<(), Box<dyn std::error::Error>>
    {
        let document = decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
            MeshFormat::Pam,
        )?;
        let mut mesh = WorkingMesh::from_document(&document)?;
        let mut handles = mesh
            .vertices()
            .map(|(handle, _)| handle)
            .collect::<Vec<_>>();
        handles.sort_unstable();
        let before = handles
            .iter()
            .map(|handle| {
                mesh.vertex(*handle)
                    .map(|vertex| (*handle, Vec3::from_array(vertex.position)))
                    .ok_or("missing vertex")
            })
            .collect::<Result<HashMap<_, _>, _>>()?;
        let weights = HashMap::from([(handles[0], 1.0), (handles[1], 0.25)]);
        let delta = Vec3::new(4.0, -2.0, 1.0);
        let mut controller = OperatorController::default();
        let gesture = controller.begin(&mesh, "weighted grab")?;
        controller.sculpt_weighted(
            &mut mesh,
            gesture,
            SculptTool::Grab,
            &weights,
            Vec3::ZERO,
            delta,
            0.5,
        )?;

        assert_eq!(
            Vec3::from_array(mesh.vertex(handles[0]).ok_or("first vertex")?.position),
            before[&handles[0]] + delta * 0.5
        );
        assert_eq!(
            Vec3::from_array(mesh.vertex(handles[1]).ok_or("second vertex")?.position),
            before[&handles[1]] + delta * 0.125
        );
        assert_eq!(
            Vec3::from_array(mesh.vertex(handles[2]).ok_or("third vertex")?.position),
            before[&handles[2]]
        );

        let mut history = History::new(1_000_000);
        controller.confirm(&mut mesh, &mut history, gesture)?;
        assert_eq!(history.undo_len(), 1);
        history.undo(&mut mesh)?;
        for handle in handles {
            assert_eq!(
                Vec3::from_array(mesh.vertex(handle).ok_or("restored vertex")?.position),
                before[&handle]
            );
        }
        Ok(())
    }
}
