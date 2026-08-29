#![forbid(unsafe_code)]

use cdmw_mesh::{EdgeHandle, FaceHandle, History, MeshError, Selection, VertexHandle, WorkingMesh};
use glam::{Quat, Vec2, Vec3};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use thiserror::Error;

const MAX_LASSO_POINTS: usize = 4_096;

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
pub struct InteractionSnapshot {
    pub geometry_revision: u64,
    pub topology_generation: u64,
    pub camera_revision: u64,
    pub viewport_revision: u64,
    pub viewport_size: Vec2,
    pub elements: Vec<ProjectedElement>,
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
    if snapshot.geometry_revision != query.geometry_revision
        || snapshot.topology_generation != query.topology_generation
        || snapshot.camera_revision != query.camera_revision
        || snapshot.viewport_revision != query.viewport_revision
    {
        return Err(InteractionError::StaleSnapshot);
    }
    validate_shape(&query.shape)?;
    let mut selection = Selection::default();
    let candidates = snapshot.elements.iter().filter(|element| {
        (!query.visible_only || element.visible)
            && element.position.is_finite()
            && shape_contains(&query.shape, element.position)
            && handle_matches_domain(element.handle, query.domain)
    });
    if let SelectionShape::Click { point, .. } = &query.shape {
        if let Some(candidate) = candidates.min_by(|first, second| {
            first
                .position
                .distance_squared(*point)
                .total_cmp(&second.position.distance_squared(*point))
                .then_with(|| first.depth.total_cmp(&second.depth))
        }) {
            insert_candidate(&mut selection, candidate.handle);
        }
        return Ok(selection);
    }
    for candidate in candidates {
        insert_candidate(&mut selection, candidate.handle);
    }
    Ok(selection)
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
        self.require_running(gesture_id)?;
        if handles.is_empty() || !center.is_finite() || !delta.is_finite() || !strength.is_finite()
        {
            return Err(InteractionError::InvalidShape);
        }
        let original = handles
            .iter()
            .map(|handle| {
                let vertex = mesh.vertex(*handle).ok_or(MeshError::StaleHandle)?;
                Ok((
                    *handle,
                    Vec3::from_array(vertex.position),
                    Vec3::from_array(vertex.normal),
                ))
            })
            .collect::<Result<Vec<_>, MeshError>>()?;
        let mut positions = HashMap::new();
        for (handle, position, normal) in original {
            let next = match tool {
                SculptTool::Grab => position + delta * strength,
                SculptTool::Inflate => {
                    position + normal.try_normalize().unwrap_or(Vec3::Y) * strength
                }
                SculptTool::Pinch => position + (center - position) * strength.clamp(-1.0, 1.0),
                SculptTool::Smooth => {
                    let neighbors = mesh
                        .vertex_neighbors(handle)
                        .ok_or(MeshError::StaleHandle)?;
                    if neighbors.is_empty() {
                        position
                    } else {
                        let total = neighbors.iter().try_fold(Vec3::ZERO, |sum, neighbor| {
                            mesh.vertex(*neighbor)
                                .map(|vertex| sum + Vec3::from_array(vertex.position))
                                .ok_or(MeshError::StaleHandle)
                        })?;
                        let average = total / neighbors.len() as f32;
                        position.lerp(average, strength.clamp(0.0, 1.0))
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
    use cdmw_formats::{MeshFormat, decode_mesh};

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
    fn stale_snapshot_is_rejected_before_selection() {
        let snapshot = InteractionSnapshot {
            geometry_revision: 2,
            topology_generation: 1,
            camera_revision: 1,
            viewport_revision: 1,
            viewport_size: Vec2::splat(100.0),
            elements: Vec::new(),
        };
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
        let snapshot = InteractionSnapshot {
            geometry_revision: mesh.geometry_revision,
            topology_generation: mesh.topology_generation,
            camera_revision: 1,
            viewport_revision: 1,
            viewport_size: Vec2::splat(100.0),
            elements: vec![
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
        };
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
}
