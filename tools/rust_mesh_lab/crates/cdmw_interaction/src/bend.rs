//! Two-handle circular bending. Cross-sections rotate without scaling, and the
//! centreline keeps its arc length. Every sample comes from the stroke baseline.
use crate::InteractionError;
use cdmw_mesh::{Provenance, VertexHandle, WorkingMesh};
use glam::{Quat, Vec3};
use std::collections::{HashMap, HashSet};

#[cfg(test)]
mod tests;

#[derive(Debug, Clone)]
pub struct BendRegion {
    pub anchor: VertexHandle,
    pub handles: HashSet<VertexHandle>,
    identity: u64,
    topology: u64,
    selection: u64,
    geometry: u64,
}

impl BendRegion {
    pub fn new(mesh: &WorkingMesh, anchor: VertexHandle) -> Result<Self, InteractionError> {
        let selected = mesh.selected_vertex_scope();
        mesh.vertex(anchor).ok_or(InteractionError::InvalidShape)?;
        if !selected.contains(&anchor) {
            return Err(InteractionError::InvalidShape);
        }
        // Exact coincident seams within the selected Part may connect. Neither
        // proximity nor an adjacent unselected Part can enlarge the edit scope.
        let part = |handle| match mesh.vertex(handle)?.provenance {
            Provenance::Source { submesh, .. } => Some(submesh),
            Provenance::Generated { .. } => mesh
                .vertex_face_slice(handle)?
                .first()
                .and_then(|face| mesh.face(*face))
                .map(|face| face.submesh),
        };
        let root_part = part(anchor).ok_or(InteractionError::InvalidShape)?;
        let mut seams: HashMap<[u32; 3], Vec<VertexHandle>> = HashMap::new();
        let key = |position: [f32; 3]| {
            position.map(|value| if value == 0.0 { 0 } else { value.to_bits() })
        };
        for handle in &selected {
            let vertex = mesh.vertex(*handle).ok_or(InteractionError::InvalidShape)?;
            if part(*handle) == Some(root_part) {
                seams.entry(key(vertex.position)).or_default().push(*handle);
            }
        }
        let mut handles = HashSet::new();
        let mut pending = vec![anchor];
        while let Some(handle) = pending.pop() {
            if !selected.contains(&handle) || handles.contains(&handle) {
                continue;
            }
            let vertex = mesh.vertex(handle).ok_or(InteractionError::InvalidShape)?;
            if part(handle) != Some(root_part) {
                continue;
            }
            handles.insert(handle);
            pending.extend(mesh.vertex_neighbor_slice(handle).unwrap_or_default());
            if let Some(connected) = seams.remove(&key(vertex.position)) {
                pending.extend(connected);
            }
        }
        Ok(Self {
            anchor,
            handles,
            identity: mesh.identity(),
            topology: mesh.topology_generation,
            selection: mesh.selection_revision,
            geometry: mesh.geometry_revision,
        })
    }

    #[must_use]
    pub fn matches(&self, mesh: &WorkingMesh) -> bool {
        self.identity == mesh.identity()
            && self.topology == mesh.topology_generation
            && self.selection == mesh.selection_revision
            && self.geometry == mesh.geometry_revision
    }

    pub fn accept_geometry(&mut self, mesh: &WorkingMesh) {
        self.geometry = mesh.geometry_revision;
    }
}

#[derive(Debug, Clone)]
pub struct BendStroke {
    pub tip: VertexHandle,
    pub region: BendRegion,
    origin: Vec3,
    axis: Vec3,
    length: f32,
    radius: f32,
    original: Vec<(VertexHandle, Vec3)>,
}

impl BendStroke {
    pub(super) fn matches_mesh(&self, mesh: &WorkingMesh) -> bool {
        self.region.identity == mesh.identity()
            && self.region.topology == mesh.topology_generation
            && self.region.selection == mesh.selection_revision
    }

    pub fn new(
        mesh: &WorkingMesh,
        region: &BendRegion,
        tip: VertexHandle,
    ) -> Result<Self, InteractionError> {
        if !region.matches(mesh) || !region.handles.contains(&tip) || tip == region.anchor {
            return Err(InteractionError::InvalidShape);
        }
        let root = Vec3::from_array(
            mesh.vertex(region.anchor)
                .ok_or(InteractionError::InvalidShape)?
                .position,
        );
        let end = Vec3::from_array(
            mesh.vertex(tip)
                .ok_or(InteractionError::InvalidShape)?
                .position,
        );
        let initial = end - root;
        if !initial.is_finite() || initial.length() <= 1.0e-6 {
            return Err(InteractionError::InvalidShape);
        }
        let mut original = region
            .handles
            .iter()
            .map(|handle| {
                mesh.vertex(*handle)
                    .map(|vertex| (*handle, Vec3::from_array(vertex.position)))
                    .ok_or(InteractionError::InvalidShape)
            })
            .collect::<Result<Vec<_>, _>>()?;
        original.sort_unstable_by_key(|(handle, _)| *handle);
        let initial_axis = initial.normalize();
        // Centre each handle's narrow slice so picking the visible rope surface
        // does not turn it into the centre of rotation of every cross-section.
        let slice_center = |point: Vec3| {
            let mut total = Vec3::ZERO;
            let mut count = 0;
            let mut unique = HashSet::new();
            for (_, vertex) in &original {
                if (*vertex - point).dot(initial_axis).abs() <= initial.length() * 0.025
                    && unique.insert(
                        vertex
                            .to_array()
                            .map(|value| if value == 0.0 { 0 } else { value.to_bits() }),
                    )
                {
                    total += *vertex;
                    count += 1;
                }
            }
            if count > 0 {
                total / count as f32
            } else {
                point
            }
        };
        let center = slice_center(root);
        let axis = (slice_center(end) - center)
            .try_normalize()
            .unwrap_or(initial_axis);
        let origin = center + axis * (root - center).dot(axis);
        let length = (end - root).dot(axis);
        if length <= 1.0e-6 {
            return Err(InteractionError::InvalidShape);
        }
        let radius = original
            .iter()
            .filter_map(|(_, point)| {
                let offset = *point - origin;
                let along = offset.dot(axis);
                (along >= 0.0 && along <= length).then_some((offset - axis * along).length())
            })
            .fold(0.0_f32, f32::max);
        if length <= radius * 2.0 {
            return Err(InteractionError::InvalidShape);
        }
        Ok(Self {
            tip,
            region: region.clone(),
            origin,
            axis,
            length,
            radius,
            original,
        })
    }

    pub fn positions(
        &self,
        delta: Vec3,
    ) -> Result<HashMap<VertexHandle, [f32; 3]>, InteractionError> {
        if !delta.is_finite() {
            return Err(InteractionError::InvalidShape);
        }
        let desired = self.axis * self.length + delta;
        let lateral = desired - self.axis * desired.dot(self.axis);
        if !desired.is_finite() || !lateral.is_finite() || !lateral.length_squared().is_finite() {
            return Err(InteractionError::InvalidShape);
        }
        let side = lateral.try_normalize();
        let angle = side.map_or(0.0, |_| {
            let requested = 2.0 * lateral.length().atan2(desired.dot(self.axis));
            // Keep the inside of the bend away from the centre of curvature.
            requested
                .min(2.8)
                .min(0.8 * self.length / self.radius.max(1.0e-6))
        });
        let rotation_axis = side.map(|side| self.axis.cross(side).normalize());
        let mut positions = HashMap::with_capacity(self.original.len());
        for (handle, position) in &self.original {
            let offset = *position - self.origin;
            let along = offset.dot(self.axis);
            if along <= 1.0e-6 || *handle == self.region.anchor {
                continue;
            }
            if angle <= 1.0e-6 {
                positions.insert(*handle, position.to_array());
                continue;
            }
            let theta = angle * (along / self.length).min(1.0);
            let rotation = Quat::from_axis_angle(rotation_axis.expect("nonzero bend"), theta);
            let radius = self.length / angle;
            let mut center = self.origin
                + self.axis * (radius * theta.sin())
                + side.expect("nonzero bend") * (radius * (1.0 - theta.cos()));
            if along > self.length {
                center += rotation * self.axis * (along - self.length);
            }
            let next = center + rotation * (offset - self.axis * along);
            if !next.is_finite() {
                return Err(InteractionError::InvalidShape);
            }
            positions.insert(*handle, next.to_array());
        }
        Ok(positions)
    }
}
