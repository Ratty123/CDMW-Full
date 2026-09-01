#![forbid(unsafe_code)]

use cdmw_evidence::sha256_bytes;
use cdmw_formats::{MeshDocument, Submesh};
use glam::{Quat, Vec2, Vec3};
use serde::{Deserialize, Serialize};
use slotmap::{Key, SecondaryMap, SlotMap, new_key_type};
use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicU64, Ordering};
use thiserror::Error;

static NEXT_MESH_IDENTITY: AtomicU64 = AtomicU64::new(1);

new_key_type! {
    pub struct VertexHandle;
    pub struct FaceHandle;
    pub struct EdgeHandle;
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Provenance {
    Source { submesh: u32, element: u32 },
    Generated { operation: u64 },
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Vertex {
    pub position: [f32; 3],
    pub normal: [f32; 3],
    pub uv: [f32; 2],
    pub provenance: Provenance,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Face {
    pub vertices: [VertexHandle; 3],
    pub submesh: u32,
    pub material: u32,
    pub provenance: Provenance,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Edge {
    pub vertices: [VertexHandle; 2],
    pub faces: Vec<FaceHandle>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Selection {
    pub vertices: HashSet<VertexHandle>,
    pub edges: HashSet<EdgeHandle>,
    pub faces: HashSet<FaceHandle>,
    pub submeshes: HashSet<u32>,
}

#[derive(Debug, Clone)]
pub struct WorkingMesh {
    identity: u64,
    vertices: SlotMap<VertexHandle, Vertex>,
    faces: SlotMap<FaceHandle, Face>,
    edges: SlotMap<EdgeHandle, Edge>,
    edge_by_pair: HashMap<(VertexHandle, VertexHandle), EdgeHandle>,
    pub selection: Selection,
    pub topology_generation: u64,
    pub geometry_revision: u64,
    pub selection_revision: u64,
    operation_sequence: u64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DrawSnapshot {
    pub mesh_identity: u64,
    pub draw_revision: u64,
    pub topology_generation: u64,
    pub positions: Vec<[f32; 3]>,
    pub normals: Vec<[f32; 3]>,
    pub uvs: Vec<[f32; 2]>,
    pub indices: Vec<u32>,
    pub triangle_materials: Vec<u32>,
    pub selected_vertices: Vec<u32>,
    pub fingerprint: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct MeshElementHandles {
    pub vertices: HashSet<VertexHandle>,
    pub edges: HashSet<EdgeHandle>,
    pub faces: HashSet<FaceHandle>,
}

#[derive(Debug, Error)]
pub enum MeshError {
    #[error("source document has no editable LOD")]
    MissingLod,
    #[error("source document contains an invalid vertex or face")]
    InvalidSource,
    #[error("stale or missing element handle")]
    StaleHandle,
    #[error("topology invariant failed: {0}")]
    Invariant(String),
    #[error("operation has no eligible elements")]
    EmptyOperation,
    #[error("resource limit exceeded")]
    ResourceLimit,
}

impl WorkingMesh {
    pub fn from_document(document: &MeshDocument) -> Result<Self, MeshError> {
        Self::from_document_lod(document, 0)
    }

    pub fn from_document_lod(document: &MeshDocument, lod_index: usize) -> Result<Self, MeshError> {
        let lod = document.lods.get(lod_index).ok_or(MeshError::MissingLod)?;
        let mut mesh = Self::empty();
        for (submesh_index, submesh) in lod.submeshes.iter().enumerate() {
            mesh.append_submesh(
                submesh,
                u32::try_from(submesh_index).map_err(|_| MeshError::ResourceLimit)?,
            )?;
        }
        mesh.rebuild_edges()?;
        mesh.validate()?;
        Ok(mesh)
    }

    #[must_use]
    pub fn empty() -> Self {
        Self {
            identity: NEXT_MESH_IDENTITY.fetch_add(1, Ordering::Relaxed),
            vertices: SlotMap::with_key(),
            faces: SlotMap::with_key(),
            edges: SlotMap::with_key(),
            edge_by_pair: HashMap::new(),
            selection: Selection::default(),
            topology_generation: 1,
            geometry_revision: 1,
            selection_revision: 1,
            operation_sequence: 0,
        }
    }

    #[must_use]
    pub fn vertex(&self, handle: VertexHandle) -> Option<&Vertex> {
        self.vertices.get(handle)
    }

    #[must_use]
    pub fn face(&self, handle: FaceHandle) -> Option<&Face> {
        self.faces.get(handle)
    }

    #[must_use]
    pub fn edge(&self, handle: EdgeHandle) -> Option<&Edge> {
        self.edges.get(handle)
    }

    pub fn vertices(&self) -> impl Iterator<Item = (VertexHandle, &Vertex)> {
        self.vertices.iter()
    }

    pub fn faces(&self) -> impl Iterator<Item = (FaceHandle, &Face)> {
        self.faces.iter()
    }

    pub fn edges(&self) -> impl Iterator<Item = (EdgeHandle, &Edge)> {
        self.edges.iter()
    }

    #[must_use]
    pub fn submesh_indices(&self) -> HashSet<u32> {
        self.faces.values().map(|face| face.submesh).collect()
    }

    #[must_use]
    pub fn element_handles_for_submeshes(
        &self,
        visible_submeshes: &HashSet<u32>,
    ) -> MeshElementHandles {
        let faces = self
            .faces
            .iter()
            .filter_map(|(handle, face)| {
                visible_submeshes.contains(&face.submesh).then_some(handle)
            })
            .collect::<HashSet<_>>();
        let mut vertices = self
            .vertices
            .iter()
            .filter_map(|(handle, vertex)| match vertex.provenance {
                Provenance::Source { submesh, .. } if visible_submeshes.contains(&submesh) => {
                    Some(handle)
                }
                Provenance::Source { .. } | Provenance::Generated { .. } => None,
            })
            .collect::<HashSet<_>>();
        for handle in &faces {
            if let Some(face) = self.faces.get(*handle) {
                vertices.extend(face.vertices);
            }
        }
        let edges = self
            .edges
            .iter()
            .filter_map(|(handle, edge)| {
                edge.faces
                    .iter()
                    .any(|face| faces.contains(face))
                    .then_some(handle)
            })
            .collect();
        MeshElementHandles {
            vertices,
            edges,
            faces,
        }
    }

    #[must_use]
    pub fn vertex_neighbors(&self, handle: VertexHandle) -> Option<HashSet<VertexHandle>> {
        if !self.vertices.contains_key(handle) {
            return None;
        }
        Some(
            self.edges
                .values()
                .filter(|edge| edge.vertices.contains(&handle))
                .filter_map(|edge| {
                    edge.vertices
                        .into_iter()
                        .find(|candidate| *candidate != handle)
                })
                .collect(),
        )
    }

    #[must_use]
    pub fn selected_vertex_scope(&self) -> HashSet<VertexHandle> {
        let mut scope = self.selection.vertices.clone();
        for handle in &self.selection.edges {
            if let Some(edge) = self.edges.get(*handle) {
                scope.extend(edge.vertices);
            }
        }
        for handle in &self.selection.faces {
            if let Some(face) = self.faces.get(*handle) {
                scope.extend(face.vertices);
            }
        }
        for face in self
            .faces
            .values()
            .filter(|face| self.selection.submeshes.contains(&face.submesh))
        {
            scope.extend(face.vertices);
        }
        scope
    }

    pub fn apply_positions(
        &mut self,
        positions: &HashMap<VertexHandle, [f32; 3]>,
    ) -> Result<(), MeshError> {
        if positions.is_empty() {
            return Err(MeshError::EmptyOperation);
        }
        if positions
            .values()
            .flatten()
            .any(|component| !component.is_finite())
        {
            return Err(MeshError::Invariant("non-finite deformation".to_owned()));
        }
        let changed = positions.keys().copied().collect::<HashSet<_>>();
        let normal_scope = self.normal_scope_for_position_changes(&changed)?;
        for (handle, position) in positions {
            self.vertices
                .get_mut(*handle)
                .ok_or(MeshError::StaleHandle)?
                .position = *position;
        }
        self.geometry_revision = self.geometry_revision.saturating_add(1);
        self.recompute_normals_for(&normal_scope)?;
        self.validate()
    }

    fn append_submesh(&mut self, source: &Submesh, submesh: u32) -> Result<(), MeshError> {
        let mut handles = Vec::with_capacity(source.positions.len());
        for (index, position) in source.positions.iter().enumerate() {
            let normal = source
                .normals
                .get(index)
                .copied()
                .unwrap_or([0.0, 1.0, 0.0]);
            let uv = source.uvs.get(index).copied().unwrap_or([0.0, 0.0]);
            if position
                .iter()
                .chain(normal.iter())
                .chain(uv.iter())
                .any(|value| !value.is_finite())
            {
                return Err(MeshError::InvalidSource);
            }
            handles.push(self.vertices.insert(Vertex {
                position: *position,
                normal,
                uv,
                provenance: Provenance::Source {
                    submesh,
                    element: u32::try_from(index).map_err(|_| MeshError::ResourceLimit)?,
                },
            }));
        }
        for (face_index, triangle) in source.indices.chunks_exact(3).enumerate() {
            let a = usize::try_from(*triangle.first().ok_or(MeshError::InvalidSource)?)
                .map_err(|_| MeshError::InvalidSource)?;
            let b = usize::try_from(*triangle.get(1).ok_or(MeshError::InvalidSource)?)
                .map_err(|_| MeshError::InvalidSource)?;
            let c = usize::try_from(*triangle.get(2).ok_or(MeshError::InvalidSource)?)
                .map_err(|_| MeshError::InvalidSource)?;
            let vertices = [
                *handles.get(a).ok_or(MeshError::InvalidSource)?,
                *handles.get(b).ok_or(MeshError::InvalidSource)?,
                *handles.get(c).ok_or(MeshError::InvalidSource)?,
            ];
            if vertices[0] == vertices[1]
                || vertices[1] == vertices[2]
                || vertices[0] == vertices[2]
            {
                continue;
            }
            self.faces.insert(Face {
                vertices,
                submesh,
                material: submesh,
                provenance: Provenance::Source {
                    submesh,
                    element: u32::try_from(face_index).map_err(|_| MeshError::ResourceLimit)?,
                },
            });
        }
        Ok(())
    }

    pub fn set_selection(&mut self, selection: Selection) -> Result<(), MeshError> {
        if selection
            .vertices
            .iter()
            .any(|handle| !self.vertices.contains_key(*handle))
            || selection
                .faces
                .iter()
                .any(|handle| !self.faces.contains_key(*handle))
            || selection
                .edges
                .iter()
                .any(|handle| !self.edges.contains_key(*handle))
        {
            return Err(MeshError::StaleHandle);
        }
        self.selection = selection;
        self.selection_revision = self.selection_revision.saturating_add(1);
        Ok(())
    }

    pub fn translate_vertices(
        &mut self,
        handles: &HashSet<VertexHandle>,
        delta: Vec3,
    ) -> Result<(), MeshError> {
        if !delta.is_finite() {
            return Err(MeshError::Invariant("non-finite translation".to_owned()));
        }
        if handles.is_empty() {
            return Err(MeshError::EmptyOperation);
        }
        let positions = handles
            .iter()
            .map(|handle| {
                let vertex = self.vertices.get(*handle).ok_or(MeshError::StaleHandle)?;
                Ok((
                    *handle,
                    (Vec3::from_array(vertex.position) + delta).to_array(),
                ))
            })
            .collect::<Result<HashMap<_, _>, MeshError>>()?;
        self.apply_positions(&positions)
    }

    pub fn rotate_vertices(
        &mut self,
        handles: &HashSet<VertexHandle>,
        pivot: Vec3,
        rotation: Quat,
    ) -> Result<(), MeshError> {
        if handles.is_empty() {
            return Err(MeshError::EmptyOperation);
        }
        if !pivot.is_finite() || !rotation.is_finite() || rotation.length_squared() <= 1.0e-8 {
            return Err(MeshError::Invariant(
                "invalid rotation transform".to_owned(),
            ));
        }
        let rotation = rotation.normalize();
        let positions = handles
            .iter()
            .map(|handle| {
                let vertex = self.vertices.get(*handle).ok_or(MeshError::StaleHandle)?;
                let position = pivot + rotation * (Vec3::from_array(vertex.position) - pivot);
                Ok((*handle, position.to_array()))
            })
            .collect::<Result<HashMap<_, _>, MeshError>>()?;
        self.apply_positions(&positions)
    }

    pub fn scale_vertices(
        &mut self,
        handles: &HashSet<VertexHandle>,
        pivot: Vec3,
        scale: Vec3,
    ) -> Result<(), MeshError> {
        if handles.is_empty() {
            return Err(MeshError::EmptyOperation);
        }
        if !pivot.is_finite()
            || !scale.is_finite()
            || scale
                .to_array()
                .iter()
                .any(|component| component.abs() <= 1.0e-6)
        {
            return Err(MeshError::Invariant("invalid scale transform".to_owned()));
        }
        let positions = handles
            .iter()
            .map(|handle| {
                let vertex = self.vertices.get(*handle).ok_or(MeshError::StaleHandle)?;
                let position = pivot + (Vec3::from_array(vertex.position) - pivot) * scale;
                Ok((*handle, position.to_array()))
            })
            .collect::<Result<HashMap<_, _>, MeshError>>()?;
        self.apply_positions(&positions)
    }

    pub fn delete_faces(&mut self, handles: &HashSet<FaceHandle>) -> Result<(), MeshError> {
        if handles.is_empty() {
            return Err(MeshError::EmptyOperation);
        }
        let mut draft = self.clone();
        let mut ordered_handles = handles.iter().copied().collect::<Vec<_>>();
        ordered_handles.sort_by_key(|handle| handle.data().as_ffi());
        for handle in ordered_handles {
            if draft.faces.remove(handle).is_none() {
                return Err(MeshError::StaleHandle);
            }
        }
        draft
            .selection
            .faces
            .retain(|handle| draft.faces.contains_key(*handle));
        draft.finish_topology_operation()?;
        *self = draft;
        Ok(())
    }

    pub fn duplicate_faces(
        &mut self,
        handles: &HashSet<FaceHandle>,
    ) -> Result<HashSet<FaceHandle>, MeshError> {
        self.duplicate_faces_into_submesh(handles, None)
    }

    pub fn duplicate_faces_to_new_submesh(
        &mut self,
        handles: &HashSet<FaceHandle>,
    ) -> Result<HashSet<FaceHandle>, MeshError> {
        if handles.is_empty() {
            return Err(MeshError::EmptyOperation);
        }
        let next_submesh = self
            .faces
            .values()
            .map(|face| face.submesh)
            .max()
            .unwrap_or(0)
            .checked_add(1)
            .ok_or_else(|| MeshError::Invariant("submesh index space exhausted".to_owned()))?;
        self.duplicate_faces_into_submesh(handles, Some(next_submesh))
    }

    fn duplicate_faces_into_submesh(
        &mut self,
        handles: &HashSet<FaceHandle>,
        target_submesh: Option<u32>,
    ) -> Result<HashSet<FaceHandle>, MeshError> {
        if handles.is_empty() {
            return Err(MeshError::EmptyOperation);
        }
        let mut draft = self.clone();
        let operation = draft.next_operation();
        let mut ordered_handles = handles.iter().copied().collect::<Vec<_>>();
        ordered_handles.sort_by_key(|handle| handle.data().as_ffi());
        let originals = ordered_handles
            .into_iter()
            .map(|handle| {
                draft
                    .faces
                    .get(handle)
                    .cloned()
                    .ok_or(MeshError::StaleHandle)
            })
            .collect::<Result<Vec<_>, _>>()?;
        let mut duplicated = HashSet::new();
        let mut duplicated_vertices = HashMap::new();
        for face in originals {
            let mut vertices = face.vertices;
            for handle in &mut vertices {
                let source_handle = *handle;
                *handle = if let Some(duplicate) = duplicated_vertices.get(&source_handle) {
                    *duplicate
                } else {
                    let mut vertex = draft
                        .vertices
                        .get(source_handle)
                        .cloned()
                        .ok_or(MeshError::StaleHandle)?;
                    vertex.provenance = Provenance::Generated { operation };
                    let duplicate = draft.vertices.insert(vertex);
                    duplicated_vertices.insert(source_handle, duplicate);
                    duplicate
                };
            }
            duplicated.insert(draft.faces.insert(Face {
                vertices,
                submesh: target_submesh.unwrap_or(face.submesh),
                material: face.material,
                provenance: Provenance::Generated { operation },
            }));
        }
        draft.selection = Selection {
            faces: duplicated.clone(),
            ..Selection::default()
        };
        draft.finish_topology_operation()?;
        *self = draft;
        Ok(duplicated)
    }

    pub fn extrude_faces(
        &mut self,
        handles: &HashSet<FaceHandle>,
        distance: f32,
    ) -> Result<HashSet<FaceHandle>, MeshError> {
        if handles.is_empty() {
            return Err(MeshError::EmptyOperation);
        }
        if !distance.is_finite() || distance <= 1.0e-6 {
            return Err(MeshError::Invariant(
                "extrude distance must be finite and positive".to_owned(),
            ));
        }

        let mut draft = self.clone();
        let operation = draft.next_operation();
        let mut ordered_handles = handles.iter().copied().collect::<Vec<_>>();
        ordered_handles.sort_by_key(|handle| handle.data().as_ffi());
        let originals = ordered_handles
            .into_iter()
            .map(|handle| {
                draft
                    .faces
                    .get(handle)
                    .cloned()
                    .map(|face| (handle, face))
                    .ok_or(MeshError::StaleHandle)
            })
            .collect::<Result<Vec<_>, _>>()?;

        let mut ordered_source_handles = originals
            .iter()
            .flat_map(|(_, face)| face.vertices)
            .collect::<Vec<_>>();
        ordered_source_handles.sort_by_key(|handle| handle.data().as_ffi());
        ordered_source_handles.dedup();
        let mut cap_vertex_by_source = HashMap::new();
        for source_handle in ordered_source_handles {
            let source = draft
                .vertices
                .get(source_handle)
                .cloned()
                .ok_or(MeshError::StaleHandle)?;
            let direction = Vec3::from_array(source.normal)
                .try_normalize()
                .ok_or_else(|| {
                    MeshError::Invariant("extrude vertex normal is invalid".to_owned())
                })?;
            let position = Vec3::from_array(source.position) + direction * distance;
            if !position.is_finite() {
                return Err(MeshError::Invariant(
                    "extrude position is not finite".to_owned(),
                ));
            }
            let cap = draft.vertices.insert(Vertex {
                position: position.to_array(),
                normal: source.normal,
                uv: source.uv,
                provenance: Provenance::Generated { operation },
            });
            cap_vertex_by_source.insert(source_handle, cap);
        }

        let mut boundary_pairs = HashSet::new();
        let mut boundaries = Vec::new();
        for (_, face) in &originals {
            for (first, second) in [
                (face.vertices[0], face.vertices[1]),
                (face.vertices[1], face.vertices[2]),
                (face.vertices[2], face.vertices[0]),
            ] {
                let pair = ordered_pair(first, second);
                let edge_handle = draft
                    .edge_by_pair
                    .get(&pair)
                    .copied()
                    .ok_or(MeshError::StaleHandle)?;
                let edge = draft.edges.get(edge_handle).ok_or(MeshError::StaleHandle)?;
                let selected_incidence = edge
                    .faces
                    .iter()
                    .filter(|handle| handles.contains(handle))
                    .count();
                let is_boundary = edge.faces.len() == 1 || selected_incidence < edge.faces.len();
                if is_boundary && boundary_pairs.insert(pair) {
                    boundaries.push((first, second, face.submesh, face.material));
                }
            }
        }

        for (handle, _) in &originals {
            let _ = draft.faces.remove(*handle).ok_or(MeshError::StaleHandle)?;
        }
        let mut caps = HashSet::new();
        for (_, face) in originals {
            let cap_vertex = |source| {
                cap_vertex_by_source.get(&source).copied().ok_or_else(|| {
                    MeshError::Invariant("extrude cap mapping is incomplete".to_owned())
                })
            };
            let vertices = [
                cap_vertex(face.vertices[0])?,
                cap_vertex(face.vertices[1])?,
                cap_vertex(face.vertices[2])?,
            ];
            caps.insert(draft.faces.insert(Face {
                vertices,
                submesh: face.submesh,
                material: face.material,
                provenance: Provenance::Generated { operation },
            }));
        }
        for (first, second, submesh, material) in boundaries {
            let cap_first = cap_vertex_by_source.get(&first).copied().ok_or_else(|| {
                MeshError::Invariant("extrude boundary mapping is incomplete".to_owned())
            })?;
            let cap_second = cap_vertex_by_source.get(&second).copied().ok_or_else(|| {
                MeshError::Invariant("extrude boundary mapping is incomplete".to_owned())
            })?;
            for vertices in [[first, second, cap_second], [first, cap_second, cap_first]] {
                draft.faces.insert(Face {
                    vertices,
                    submesh,
                    material,
                    provenance: Provenance::Generated { operation },
                });
            }
        }
        draft.selection = Selection {
            faces: caps.clone(),
            ..Selection::default()
        };
        draft.finish_topology_operation()?;
        *self = draft;
        Ok(caps)
    }

    pub fn inset_faces(
        &mut self,
        handles: &HashSet<FaceHandle>,
        amount: f32,
    ) -> Result<HashSet<FaceHandle>, MeshError> {
        if handles.is_empty() {
            return Err(MeshError::EmptyOperation);
        }
        if !amount.is_finite() || amount <= 0.0 || amount >= 1.0 {
            return Err(MeshError::Invariant(
                "inset amount must be finite and strictly between zero and one".to_owned(),
            ));
        }

        let mut draft = self.clone();
        let operation = draft.next_operation();
        let mut ordered_handles = handles.iter().copied().collect::<Vec<_>>();
        ordered_handles.sort_by_key(|handle| handle.data().as_ffi());
        let originals = ordered_handles
            .into_iter()
            .map(|handle| {
                draft
                    .faces
                    .get(handle)
                    .cloned()
                    .map(|face| (handle, face))
                    .ok_or(MeshError::StaleHandle)
            })
            .collect::<Result<Vec<_>, _>>()?;

        let mut caps = HashSet::new();
        for (handle, face) in originals {
            let source_vertices = face.vertices.map(|source| {
                draft
                    .vertices
                    .get(source)
                    .cloned()
                    .ok_or(MeshError::StaleHandle)
            });
            let [source_a, source_b, source_c] = source_vertices;
            let source_vertices = [source_a?, source_b?, source_c?];
            let position_centroid = source_vertices
                .iter()
                .map(|vertex| Vec3::from_array(vertex.position))
                .sum::<Vec3>()
                / 3.0;
            let uv_centroid = source_vertices
                .iter()
                .map(|vertex| Vec2::from_array(vertex.uv))
                .sum::<Vec2>()
                / 3.0;
            if !position_centroid.is_finite() || !uv_centroid.is_finite() {
                return Err(MeshError::Invariant(
                    "inset source attributes are not finite".to_owned(),
                ));
            }

            let mut inset_vertices = face.vertices;
            for (index, source) in source_vertices.into_iter().enumerate() {
                let position = Vec3::from_array(source.position).lerp(position_centroid, amount);
                let uv = Vec2::from_array(source.uv).lerp(uv_centroid, amount);
                if !position.is_finite() || !uv.is_finite() {
                    return Err(MeshError::Invariant(
                        "inset attributes are not finite".to_owned(),
                    ));
                }
                inset_vertices[index] = draft.vertices.insert(Vertex {
                    position: position.to_array(),
                    normal: source.normal,
                    uv: uv.to_array(),
                    provenance: Provenance::Generated { operation },
                });
            }

            let _ = draft.faces.remove(handle).ok_or(MeshError::StaleHandle)?;
            let [a, b, c] = face.vertices;
            let [inset_a, inset_b, inset_c] = inset_vertices;
            let cap = draft.faces.insert(Face {
                vertices: inset_vertices,
                submesh: face.submesh,
                material: face.material,
                provenance: Provenance::Generated { operation },
            });
            caps.insert(cap);
            for vertices in [
                [a, b, inset_b],
                [a, inset_b, inset_a],
                [b, c, inset_c],
                [b, inset_c, inset_b],
                [c, a, inset_a],
                [c, inset_a, inset_c],
            ] {
                draft.faces.insert(Face {
                    vertices,
                    submesh: face.submesh,
                    material: face.material,
                    provenance: Provenance::Generated { operation },
                });
            }
        }
        draft.selection = Selection {
            faces: caps.clone(),
            ..Selection::default()
        };
        draft.finish_topology_operation()?;
        *self = draft;
        Ok(caps)
    }

    pub fn subdivide_faces(
        &mut self,
        handles: &HashSet<FaceHandle>,
    ) -> Result<HashSet<FaceHandle>, MeshError> {
        if handles.is_empty() {
            return Err(MeshError::EmptyOperation);
        }
        let mut draft = self.clone();
        let operation = draft.next_operation();
        let mut ordered_handles = handles.iter().copied().collect::<Vec<_>>();
        ordered_handles.sort_by_key(|handle| handle.data().as_ffi());
        let originals = ordered_handles
            .into_iter()
            .map(|handle| {
                draft
                    .faces
                    .get(handle)
                    .cloned()
                    .map(|face| (handle, face))
                    .ok_or(MeshError::StaleHandle)
            })
            .collect::<Result<Vec<_>, _>>()?;
        let mut midpoint_by_edge = HashMap::new();
        let mut created = HashSet::new();
        for (handle, face) in originals {
            let a = face.vertices[0];
            let b = face.vertices[1];
            let c = face.vertices[2];
            let ab = draft.midpoint(a, b, operation, &mut midpoint_by_edge)?;
            let bc = draft.midpoint(b, c, operation, &mut midpoint_by_edge)?;
            let ca = draft.midpoint(c, a, operation, &mut midpoint_by_edge)?;
            let _ = draft.faces.remove(handle).ok_or(MeshError::StaleHandle)?;
            for vertices in [[a, ab, ca], [ab, b, bc], [ca, bc, c], [ab, bc, ca]] {
                created.insert(draft.faces.insert(Face {
                    vertices,
                    submesh: face.submesh,
                    material: face.material,
                    provenance: Provenance::Generated { operation },
                }));
            }
        }
        draft.selection = Selection {
            faces: created.clone(),
            ..Selection::default()
        };
        draft.finish_topology_operation()?;
        *self = draft;
        Ok(created)
    }

    pub fn subdivide_edges(
        &mut self,
        handles: &HashSet<EdgeHandle>,
    ) -> Result<HashSet<EdgeHandle>, MeshError> {
        if handles.is_empty() {
            return Err(MeshError::EmptyOperation);
        }
        let mut draft = self.clone();
        let operation = draft.next_operation();
        let mut ordered_handles = handles.iter().copied().collect::<Vec<_>>();
        ordered_handles.sort_by_key(|handle| handle.data().as_ffi());
        let originals = ordered_handles
            .into_iter()
            .map(|handle| {
                draft
                    .edges
                    .get(handle)
                    .map(|edge| edge.vertices)
                    .ok_or(MeshError::StaleHandle)
            })
            .collect::<Result<Vec<_>, _>>()?;
        let mut midpoint_by_edge = HashMap::new();
        let mut child_pairs = Vec::with_capacity(originals.len().saturating_mul(2));
        for [first, second] in originals {
            let midpoint = draft.midpoint(first, second, operation, &mut midpoint_by_edge)?;
            child_pairs.push(ordered_pair(first, midpoint));
            child_pairs.push(ordered_pair(midpoint, second));
        }
        let mut affected = draft
            .faces
            .iter()
            .filter(|(_, face)| {
                triangle_edges(face.vertices)
                    .into_iter()
                    .any(|pair| midpoint_by_edge.contains_key(&pair))
            })
            .map(|(handle, face)| (handle, face.clone()))
            .collect::<Vec<_>>();
        affected.sort_by_key(|(handle, _)| handle.data().as_ffi());
        for (handle, face) in affected {
            let triangles = split_triangle_with_midpoints(face.vertices, &midpoint_by_edge)?;
            let _ = draft.faces.remove(handle).ok_or(MeshError::StaleHandle)?;
            for vertices in triangles {
                draft.faces.insert(Face {
                    vertices,
                    submesh: face.submesh,
                    material: face.material,
                    provenance: Provenance::Generated { operation },
                });
            }
        }
        draft.selection = Selection::default();
        draft.finish_topology_operation()?;
        let selected = child_pairs
            .into_iter()
            .map(|pair| {
                draft.edge_by_pair.get(&pair).copied().ok_or_else(|| {
                    MeshError::Invariant("subdivided child edge is missing".to_owned())
                })
            })
            .collect::<Result<HashSet<_>, _>>()?;
        draft.selection.edges = selected.clone();
        *self = draft;
        Ok(selected)
    }

    fn midpoint(
        &mut self,
        first: VertexHandle,
        second: VertexHandle,
        operation: u64,
        cache: &mut HashMap<(VertexHandle, VertexHandle), VertexHandle>,
    ) -> Result<VertexHandle, MeshError> {
        let key = ordered_pair(first, second);
        if let Some(handle) = cache.get(&key) {
            return Ok(*handle);
        }
        let a = self.vertices.get(first).ok_or(MeshError::StaleHandle)?;
        let b = self.vertices.get(second).ok_or(MeshError::StaleHandle)?;
        let position = (Vec3::from_array(a.position) + Vec3::from_array(b.position)) * 0.5;
        let normal = (Vec3::from_array(a.normal) + Vec3::from_array(b.normal))
            .try_normalize()
            .unwrap_or(Vec3::Y);
        let handle = self.vertices.insert(Vertex {
            position: position.to_array(),
            normal: normal.to_array(),
            uv: [(a.uv[0] + b.uv[0]) * 0.5, (a.uv[1] + b.uv[1]) * 0.5],
            provenance: Provenance::Generated { operation },
        });
        cache.insert(key, handle);
        Ok(handle)
    }

    fn finish_topology_operation(&mut self) -> Result<(), MeshError> {
        self.topology_generation = self.topology_generation.saturating_add(1);
        self.geometry_revision = self.geometry_revision.saturating_add(1);
        self.selection_revision = self.selection_revision.saturating_add(1);
        self.remove_unreferenced_vertices();
        self.rebuild_edges()?;
        self.selection
            .vertices
            .retain(|handle| self.vertices.contains_key(*handle));
        self.selection
            .edges
            .retain(|handle| self.edges.contains_key(*handle));
        self.validate()
    }

    fn remove_unreferenced_vertices(&mut self) {
        let referenced = self
            .faces
            .values()
            .flat_map(|face| face.vertices)
            .collect::<HashSet<_>>();
        self.vertices
            .retain(|handle, _| referenced.contains(&handle));
    }

    fn rebuild_edges(&mut self) -> Result<(), MeshError> {
        self.edges.clear();
        self.edge_by_pair.clear();
        for (face_handle, face) in &self.faces {
            for (first, second) in [
                (face.vertices[0], face.vertices[1]),
                (face.vertices[1], face.vertices[2]),
                (face.vertices[2], face.vertices[0]),
            ] {
                let pair = ordered_pair(first, second);
                if let Some(edge_handle) = self.edge_by_pair.get(&pair).copied() {
                    let edge = self
                        .edges
                        .get_mut(edge_handle)
                        .ok_or(MeshError::StaleHandle)?;
                    edge.faces.push(face_handle);
                } else {
                    let edge_handle = self.edges.insert(Edge {
                        vertices: [pair.0, pair.1],
                        faces: vec![face_handle],
                    });
                    self.edge_by_pair.insert(pair, edge_handle);
                }
            }
        }
        Ok(())
    }

    fn normal_scope_for_position_changes(
        &self,
        changed: &HashSet<VertexHandle>,
    ) -> Result<HashSet<VertexHandle>, MeshError> {
        if changed
            .iter()
            .any(|handle| !self.vertices.contains_key(*handle))
        {
            return Err(MeshError::StaleHandle);
        }
        Ok(self
            .faces
            .values()
            .filter(|face| face.vertices.iter().any(|handle| changed.contains(handle)))
            .flat_map(|face| face.vertices)
            .collect())
    }

    fn recompute_normals_for(&mut self, scope: &HashSet<VertexHandle>) -> Result<(), MeshError> {
        let mut accumulators: SecondaryMap<VertexHandle, Vec3> = SecondaryMap::new();
        for handle in scope {
            if !self.vertices.contains_key(*handle) {
                return Err(MeshError::StaleHandle);
            }
            accumulators.insert(*handle, Vec3::ZERO);
        }
        for face in self.faces.values() {
            if !face.vertices.iter().any(|handle| scope.contains(handle)) {
                continue;
            }
            let a = Vec3::from_array(
                self.vertices
                    .get(face.vertices[0])
                    .ok_or(MeshError::StaleHandle)?
                    .position,
            );
            let b = Vec3::from_array(
                self.vertices
                    .get(face.vertices[1])
                    .ok_or(MeshError::StaleHandle)?
                    .position,
            );
            let c = Vec3::from_array(
                self.vertices
                    .get(face.vertices[2])
                    .ok_or(MeshError::StaleHandle)?
                    .position,
            );
            let normal = (b - a).cross(c - a);
            for handle in face.vertices {
                if let Some(value) = accumulators.get_mut(handle) {
                    *value += normal;
                }
            }
        }
        for handle in scope {
            let vertex = self
                .vertices
                .get_mut(*handle)
                .ok_or(MeshError::StaleHandle)?;
            let fallback = Vec3::from_array(vertex.normal)
                .try_normalize()
                .unwrap_or(Vec3::Y);
            vertex.normal = accumulators
                .get(*handle)
                .copied()
                .and_then(Vec3::try_normalize)
                .unwrap_or(fallback)
                .to_array();
        }
        Ok(())
    }

    pub fn validate(&self) -> Result<(), MeshError> {
        for (vertex_handle, vertex) in &self.vertices {
            if vertex
                .position
                .iter()
                .chain(vertex.normal.iter())
                .chain(vertex.uv.iter())
                .any(|component| !component.is_finite())
            {
                return Err(MeshError::Invariant(format!(
                    "vertex {:?} contains a non-finite attribute",
                    vertex_handle.data()
                )));
            }
        }
        for (face_handle, face) in &self.faces {
            if face.vertices[0] == face.vertices[1]
                || face.vertices[1] == face.vertices[2]
                || face.vertices[0] == face.vertices[2]
            {
                return Err(MeshError::Invariant(format!(
                    "face {:?} repeats a vertex",
                    face_handle.data()
                )));
            }
            if face
                .vertices
                .iter()
                .any(|handle| !self.vertices.contains_key(*handle))
            {
                return Err(MeshError::Invariant(format!(
                    "face {:?} references a missing vertex",
                    face_handle.data()
                )));
            }
        }
        for (edge_handle, edge) in &self.edges {
            if edge.vertices[0] == edge.vertices[1] || edge.faces.is_empty() {
                return Err(MeshError::Invariant(format!(
                    "edge {:?} has invalid incidence",
                    edge_handle.data()
                )));
            }
            if edge
                .faces
                .iter()
                .any(|handle| !self.faces.contains_key(*handle))
            {
                return Err(MeshError::Invariant(format!(
                    "edge {:?} references a missing face",
                    edge_handle.data()
                )));
            }
        }
        Ok(())
    }

    #[must_use]
    pub fn structural_fingerprint(&self) -> String {
        let mut snapshot = self.draw_snapshot();
        std::mem::take(&mut snapshot.fingerprint)
    }

    #[must_use]
    pub fn draw_snapshot(&self) -> DrawSnapshot {
        self.draw_snapshot_with_elements(None, self.geometry_revision)
    }

    #[must_use]
    pub fn draw_snapshot_for_submeshes(&self, visible_submeshes: &HashSet<u32>) -> DrawSnapshot {
        let elements = self.element_handles_for_submeshes(visible_submeshes);
        self.draw_snapshot_with_elements(
            Some(&elements),
            filtered_draw_revision(self.geometry_revision, visible_submeshes),
        )
    }

    fn draw_snapshot_with_elements(
        &self,
        elements: Option<&MeshElementHandles>,
        draw_revision: u64,
    ) -> DrawSnapshot {
        let vertex_capacity = elements.map_or(self.vertices.len(), |items| items.vertices.len());
        let face_capacity = elements.map_or(self.faces.len(), |items| items.faces.len());
        let mut positions = Vec::with_capacity(vertex_capacity);
        let mut normals = Vec::with_capacity(vertex_capacity);
        let mut uvs = Vec::with_capacity(vertex_capacity);
        let mut handles = HashMap::new();
        for (handle, vertex) in &self.vertices {
            if elements.is_some_and(|items| !items.vertices.contains(&handle)) {
                continue;
            }
            let index = u32::try_from(positions.len()).unwrap_or(u32::MAX);
            handles.insert(handle, index);
            positions.push(vertex.position);
            normals.push(vertex.normal);
            uvs.push(vertex.uv);
        }
        let mut indices = Vec::with_capacity(face_capacity.saturating_mul(3));
        let mut triangle_materials = Vec::with_capacity(face_capacity);
        for (face_handle, face) in &self.faces {
            if elements.is_some_and(|items| !items.faces.contains(&face_handle)) {
                continue;
            }
            for handle in face.vertices {
                if let Some(index) = handles.get(&handle) {
                    indices.push(*index);
                }
            }
            triangle_materials.push(face.material);
        }
        let selected_vertices = self
            .selection
            .vertices
            .iter()
            .filter_map(|handle| handles.get(handle).copied())
            .collect();
        let mut bytes = Vec::new();
        for position in &positions {
            for component in position {
                bytes.extend_from_slice(&component.to_le_bytes());
            }
        }
        for index in &indices {
            bytes.extend_from_slice(&index.to_le_bytes());
        }
        DrawSnapshot {
            mesh_identity: self.identity,
            draw_revision,
            topology_generation: self.topology_generation,
            positions,
            normals,
            uvs,
            indices,
            triangle_materials,
            selected_vertices,
            fingerprint: sha256_bytes(&bytes),
        }
    }

    fn next_operation(&mut self) -> u64 {
        self.operation_sequence = self.operation_sequence.saturating_add(1);
        self.operation_sequence
    }
}

fn filtered_draw_revision(geometry_revision: u64, visible_submeshes: &HashSet<u32>) -> u64 {
    let mut revision = 0xcbf2_9ce4_8422_2325_u64;
    for byte in geometry_revision.to_le_bytes() {
        revision ^= u64::from(byte);
        revision = revision.wrapping_mul(0x0000_0100_0000_01b3);
    }
    let mut ordered = visible_submeshes.iter().copied().collect::<Vec<_>>();
    ordered.sort_unstable();
    for submesh in ordered {
        for byte in submesh.to_le_bytes() {
            revision ^= u64::from(byte);
            revision = revision.wrapping_mul(0x0000_0100_0000_01b3);
        }
    }
    revision
}

fn ordered_pair(first: VertexHandle, second: VertexHandle) -> (VertexHandle, VertexHandle) {
    if first.data().as_ffi() <= second.data().as_ffi() {
        (first, second)
    } else {
        (second, first)
    }
}

fn triangle_edges(vertices: [VertexHandle; 3]) -> [(VertexHandle, VertexHandle); 3] {
    [
        ordered_pair(vertices[0], vertices[1]),
        ordered_pair(vertices[1], vertices[2]),
        ordered_pair(vertices[2], vertices[0]),
    ]
}

fn split_triangle_with_midpoints(
    vertices: [VertexHandle; 3],
    midpoint_by_edge: &HashMap<(VertexHandle, VertexHandle), VertexHandle>,
) -> Result<Vec<[VertexHandle; 3]>, MeshError> {
    let [a, b, c] = vertices;
    let [ab_pair, bc_pair, ca_pair] = triangle_edges(vertices);
    let ab = midpoint_by_edge.get(&ab_pair).copied();
    let bc = midpoint_by_edge.get(&bc_pair).copied();
    let ca = midpoint_by_edge.get(&ca_pair).copied();
    let triangles = match (ab, bc, ca) {
        (Some(ab), None, None) => vec![[a, ab, c], [ab, b, c]],
        (None, Some(bc), None) => vec![[b, bc, a], [bc, c, a]],
        (None, None, Some(ca)) => vec![[c, ca, b], [ca, a, b]],
        (Some(ab), Some(bc), None) => vec![[a, ab, c], [ab, bc, c], [ab, b, bc]],
        (None, Some(bc), Some(ca)) => vec![[b, bc, a], [bc, ca, a], [bc, c, ca]],
        (Some(ab), None, Some(ca)) => vec![[c, ca, b], [ca, ab, b], [ca, a, ab]],
        (Some(ab), Some(bc), Some(ca)) => vec![[a, ab, ca], [ab, b, bc], [ca, bc, c], [ab, bc, ca]],
        (None, None, None) => {
            return Err(MeshError::Invariant(
                "subdivision face has no selected edge".to_owned(),
            ));
        }
    };
    Ok(triangles)
}

#[derive(Debug, Clone)]
pub struct HistoryEntry {
    pub label: String,
    pub before: WorkingMesh,
    pub after: WorkingMesh,
    pub before_fingerprint: String,
    pub after_fingerprint: String,
    pub retained_bytes_estimate: usize,
}

#[derive(Debug, Clone)]
pub struct History {
    undo: Vec<HistoryEntry>,
    redo: Vec<HistoryEntry>,
    budget_bytes: usize,
    retained_bytes: usize,
}

impl History {
    #[must_use]
    pub fn new(budget_bytes: usize) -> Self {
        Self {
            undo: Vec::new(),
            redo: Vec::new(),
            budget_bytes: budget_bytes.max(1),
            retained_bytes: 0,
        }
    }

    pub fn commit(
        &mut self,
        label: impl Into<String>,
        before: WorkingMesh,
        after: &WorkingMesh,
    ) -> Result<(), MeshError> {
        before.validate()?;
        after.validate()?;
        if before.identity != after.identity {
            return Err(MeshError::Invariant(
                "history snapshots belong to different meshes".to_owned(),
            ));
        }
        let retained_bytes_estimate =
            estimate_mesh_bytes(&before).saturating_add(estimate_mesh_bytes(after));
        let entry = HistoryEntry {
            label: label.into(),
            before_fingerprint: before.structural_fingerprint(),
            after_fingerprint: after.structural_fingerprint(),
            before,
            after: after.clone(),
            retained_bytes_estimate,
        };
        let discarded_redo_bytes = self.redo.iter().fold(0_usize, |total, entry| {
            total.saturating_add(entry.retained_bytes_estimate)
        });
        self.retained_bytes = self.retained_bytes.saturating_sub(discarded_redo_bytes);
        self.redo.clear();
        self.retained_bytes = self
            .retained_bytes
            .saturating_add(entry.retained_bytes_estimate);
        self.undo.push(entry);
        while self.retained_bytes > self.budget_bytes && self.undo.len() > 1 {
            let removed = self.undo.remove(0);
            self.retained_bytes = self
                .retained_bytes
                .saturating_sub(removed.retained_bytes_estimate);
        }
        Ok(())
    }

    pub fn undo(&mut self, mesh: &mut WorkingMesh) -> Result<(), MeshError> {
        let entry = self.undo.last().ok_or(MeshError::EmptyOperation)?;
        entry.before.validate()?;
        if mesh.identity != entry.after.identity {
            return Err(MeshError::Invariant(
                "undo history belongs to a different mesh".to_owned(),
            ));
        }
        let entry = self.undo.pop().ok_or(MeshError::EmptyOperation)?;
        *mesh = entry.before.clone();
        self.redo.push(entry);
        Ok(())
    }

    pub fn redo(&mut self, mesh: &mut WorkingMesh) -> Result<(), MeshError> {
        let entry = self.redo.last().ok_or(MeshError::EmptyOperation)?;
        entry.after.validate()?;
        if mesh.identity != entry.before.identity {
            return Err(MeshError::Invariant(
                "redo history belongs to a different mesh".to_owned(),
            ));
        }
        let entry = self.redo.pop().ok_or(MeshError::EmptyOperation)?;
        *mesh = entry.after.clone();
        self.undo.push(entry);
        Ok(())
    }

    #[must_use]
    pub fn undo_len(&self) -> usize {
        self.undo.len()
    }

    #[must_use]
    pub fn retained_bytes(&self) -> usize {
        self.retained_bytes
    }

    #[must_use]
    pub fn budget_bytes(&self) -> usize {
        self.budget_bytes
    }
}

fn estimate_mesh_bytes(mesh: &WorkingMesh) -> usize {
    mesh.vertices
        .len()
        .saturating_mul(std::mem::size_of::<Vertex>())
        + mesh.faces.len().saturating_mul(std::mem::size_of::<Face>())
        + mesh.edges.len().saturating_mul(std::mem::size_of::<Edge>())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn triangle() -> WorkingMesh {
        let mut mesh = WorkingMesh::empty();
        let a = mesh.vertices.insert(Vertex {
            position: [0.0, 0.0, 0.0],
            normal: [0.0, 0.0, 1.0],
            uv: [0.0, 0.0],
            provenance: Provenance::Source {
                submesh: 0,
                element: 0,
            },
        });
        let b = mesh.vertices.insert(Vertex {
            position: [1.0, 0.0, 0.0],
            normal: [0.0, 0.0, 1.0],
            uv: [1.0, 0.0],
            provenance: Provenance::Source {
                submesh: 0,
                element: 1,
            },
        });
        let c = mesh.vertices.insert(Vertex {
            position: [0.0, 1.0, 0.0],
            normal: [0.0, 0.0, 1.0],
            uv: [0.0, 1.0],
            provenance: Provenance::Source {
                submesh: 0,
                element: 2,
            },
        });
        mesh.faces.insert(Face {
            vertices: [a, b, c],
            submesh: 0,
            material: 0,
            provenance: Provenance::Source {
                submesh: 0,
                element: 0,
            },
        });
        mesh.rebuild_edges()
            .unwrap_or_else(|error| panic!("edge rebuild failed: {error}"));
        mesh
    }

    fn two_triangle_quad() -> WorkingMesh {
        let mut mesh = triangle();
        let b = mesh
            .vertices
            .iter()
            .find_map(|(handle, vertex)| (vertex.position == [1.0, 0.0, 0.0]).then_some(handle))
            .unwrap_or_else(|| panic!("quad vertex B is missing"));
        let c = mesh
            .vertices
            .iter()
            .find_map(|(handle, vertex)| (vertex.position == [0.0, 1.0, 0.0]).then_some(handle))
            .unwrap_or_else(|| panic!("quad vertex C is missing"));
        let d = mesh.vertices.insert(Vertex {
            position: [1.0, 1.0, 0.0],
            normal: [0.0, 0.0, 1.0],
            uv: [1.0, 1.0],
            provenance: Provenance::Source {
                submesh: 0,
                element: 3,
            },
        });
        mesh.faces.insert(Face {
            vertices: [b, d, c],
            submesh: 0,
            material: 0,
            provenance: Provenance::Source {
                submesh: 0,
                element: 1,
            },
        });
        mesh.rebuild_edges()
            .unwrap_or_else(|error| panic!("edge rebuild failed: {error}"));
        mesh
    }

    fn two_disconnected_triangles() -> WorkingMesh {
        let mut mesh = WorkingMesh::empty();
        for (submesh, offset, normal) in [
            (0, Vec3::ZERO, [1.0, 0.0, 0.0]),
            (1, Vec3::new(10.0, 0.0, 0.0), [0.0, 1.0, 0.0]),
        ] {
            let vertices = [Vec3::ZERO, Vec3::X, Vec3::Y].map(|position| {
                mesh.vertices.insert(Vertex {
                    position: (position + offset).to_array(),
                    normal,
                    uv: [0.0, 0.0],
                    provenance: Provenance::Source {
                        submesh,
                        element: 0,
                    },
                })
            });
            mesh.faces.insert(Face {
                vertices,
                submesh,
                material: submesh,
                provenance: Provenance::Source {
                    submesh,
                    element: 0,
                },
            });
        }
        mesh.rebuild_edges()
            .unwrap_or_else(|error| panic!("edge rebuild failed: {error}"));
        mesh
    }

    fn assert_exact_working_state(actual: &WorkingMesh, expected: &WorkingMesh) {
        assert_eq!(actual.identity, expected.identity);
        assert_eq!(actual.vertices.len(), expected.vertices.len());
        assert_eq!(actual.faces.len(), expected.faces.len());
        assert_eq!(actual.edges.len(), expected.edges.len());
        for (handle, vertex) in &expected.vertices {
            assert_eq!(actual.vertices.get(handle), Some(vertex));
        }
        for (handle, face) in &expected.faces {
            assert_eq!(actual.faces.get(handle), Some(face));
        }
        for (handle, edge) in &expected.edges {
            assert_eq!(actual.edges.get(handle), Some(edge));
        }
        assert_eq!(actual.edge_by_pair, expected.edge_by_pair);
        assert_eq!(actual.selection, expected.selection);
        assert_eq!(actual.topology_generation, expected.topology_generation);
        assert_eq!(actual.geometry_revision, expected.geometry_revision);
        assert_eq!(actual.selection_revision, expected.selection_revision);
        assert_eq!(actual.operation_sequence, expected.operation_sequence);
    }

    #[test]
    fn explicit_lod_construction_preserves_the_default_and_checks_bounds() -> Result<(), MeshError>
    {
        let document = cdmw_formats::decode_mesh(
            &cdmw_formats::synthetic::two_lod_pac(),
            cdmw_formats::MeshFormat::Pac,
        )
        .map_err(|_| MeshError::InvalidSource)?;
        let default = WorkingMesh::from_document(&document)?;
        let first = WorkingMesh::from_document_lod(&document, 0)?;
        assert_eq!(
            default.structural_fingerprint(),
            first.structural_fingerprint()
        );
        assert_ne!(default.identity, first.identity);
        assert_eq!(first.identity, first.clone().identity);
        let second = WorkingMesh::from_document_lod(&document, 1)?;
        assert_eq!(second.vertices().count(), 4);
        assert_eq!(second.faces().count(), 2);
        assert!(matches!(
            WorkingMesh::from_document_lod(&document, 2),
            Err(MeshError::MissingLod)
        ));
        Ok(())
    }

    #[test]
    fn draw_snapshot_preserves_one_material_owner_per_triangle() {
        let snapshot = two_disconnected_triangles().draw_snapshot();
        assert_eq!(snapshot.indices.len(), 6);
        assert_eq!(snapshot.triangle_materials, vec![0, 1]);
    }

    #[test]
    fn filtered_draw_snapshot_omits_hidden_geometry_and_selection() -> Result<(), MeshError> {
        let mut mesh = two_disconnected_triangles();
        let hidden_vertex = mesh
            .vertices()
            .find_map(|(handle, vertex)| match vertex.provenance {
                Provenance::Source { submesh: 1, .. } => Some(handle),
                Provenance::Source { .. } | Provenance::Generated { .. } => None,
            })
            .ok_or(MeshError::InvalidSource)?;
        mesh.set_selection(Selection {
            vertices: HashSet::from([hidden_vertex]),
            ..Selection::default()
        })?;

        let visible = HashSet::from([0]);
        let elements = mesh.element_handles_for_submeshes(&visible);
        let snapshot = mesh.draw_snapshot_for_submeshes(&visible);

        assert_eq!(elements.faces.len(), 1);
        assert_eq!(elements.edges.len(), 3);
        assert_eq!(elements.vertices.len(), 3);
        assert!(!elements.vertices.contains(&hidden_vertex));
        assert_eq!(snapshot.positions.len(), 3);
        assert_eq!(snapshot.indices.len(), 3);
        assert_eq!(snapshot.triangle_materials, vec![0]);
        assert!(snapshot.selected_vertices.is_empty());
        assert_ne!(snapshot.draw_revision, mesh.draw_snapshot().draw_revision);
        Ok(())
    }

    #[test]
    fn source_non_manifold_edges_remain_editable() -> Result<(), MeshError> {
        let mut mesh = WorkingMesh::empty();
        let shared_a = mesh.vertices.insert(Vertex {
            position: [-1.0, 0.0, 0.0],
            normal: [0.0, 1.0, 0.0],
            uv: [0.0, 0.0],
            provenance: Provenance::Source {
                submesh: 0,
                element: 0,
            },
        });
        let shared_b = mesh.vertices.insert(Vertex {
            position: [1.0, 0.0, 0.0],
            normal: [0.0, 1.0, 0.0],
            uv: [1.0, 0.0],
            provenance: Provenance::Source {
                submesh: 0,
                element: 1,
            },
        });
        for (element, position) in [
            [0.0, 1.0, 0.0],
            [0.0, -1.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, -1.0],
        ]
        .into_iter()
        .enumerate()
        {
            let outer = mesh.vertices.insert(Vertex {
                position,
                normal: [0.0, 1.0, 0.0],
                uv: [0.5, 1.0],
                provenance: Provenance::Source {
                    submesh: 0,
                    element: u32::try_from(element + 2).map_err(|_| MeshError::ResourceLimit)?,
                },
            });
            mesh.faces.insert(Face {
                vertices: [shared_a, shared_b, outer],
                submesh: 0,
                material: 0,
                provenance: Provenance::Source {
                    submesh: 0,
                    element: u32::try_from(element).map_err(|_| MeshError::ResourceLimit)?,
                },
            });
        }
        mesh.rebuild_edges()?;
        let shared_edge = *mesh
            .edge_by_pair
            .get(&ordered_pair(shared_a, shared_b))
            .ok_or(MeshError::InvalidSource)?;
        assert_eq!(
            mesh.edge(shared_edge)
                .ok_or(MeshError::InvalidSource)?
                .faces
                .len(),
            4
        );
        mesh.validate()?;

        let children = mesh.subdivide_edges(&HashSet::from([shared_edge]))?;
        assert_eq!(mesh.faces.len(), 8);
        assert_eq!(mesh.vertices.len(), 7);
        assert_eq!(children.len(), 2);
        for child in children {
            assert_eq!(
                mesh.edge(child)
                    .ok_or(MeshError::InvalidSource)?
                    .faces
                    .len(),
                4
            );
        }
        mesh.validate()?;

        let selected = HashSet::from([mesh.faces.keys().next().ok_or(MeshError::InvalidSource)?]);
        mesh.duplicate_faces(&selected)?;
        mesh.validate()
    }

    #[test]
    fn subdivide_is_atomic_and_produces_four_faces() -> Result<(), MeshError> {
        let mut mesh = triangle();
        let selected = mesh.faces.keys().collect::<HashSet<_>>();
        let created = mesh.subdivide_faces(&selected)?;
        assert_eq!(created.len(), 4);
        assert_eq!(mesh.faces.len(), 4);
        assert_eq!(mesh.vertices.len(), 6);
        assert_eq!(mesh.selection.faces, created);
        mesh.validate()
    }

    #[test]
    fn subdivide_edge_interpolates_attributes_and_selects_both_children() -> Result<(), MeshError> {
        let mut mesh = triangle();
        let source_vertices = mesh
            .vertices
            .iter()
            .map(|(handle, vertex)| (handle, vertex.clone()))
            .collect::<HashMap<_, _>>();
        let edge_handle = mesh.edges.keys().next().ok_or(MeshError::InvalidSource)?;
        let edge = mesh
            .edges
            .get(edge_handle)
            .cloned()
            .ok_or(MeshError::InvalidSource)?;
        let face = mesh
            .faces
            .values()
            .next()
            .cloned()
            .ok_or(MeshError::InvalidSource)?;
        let children = mesh.subdivide_edges(&HashSet::from([edge_handle]))?;
        assert_eq!(mesh.faces.len(), 2);
        assert_eq!(mesh.vertices.len(), 4);
        assert_eq!(children.len(), 2);
        assert_eq!(mesh.selection.edges, children);
        let (midpoint_handle, midpoint) = mesh
            .vertices
            .iter()
            .find(|(handle, _)| !source_vertices.contains_key(handle))
            .ok_or(MeshError::InvalidSource)?;
        let first = &source_vertices[&edge.vertices[0]];
        let second = &source_vertices[&edge.vertices[1]];
        assert_eq!(
            Vec3::from_array(midpoint.position),
            (Vec3::from_array(first.position) + Vec3::from_array(second.position)) * 0.5
        );
        assert_eq!(
            midpoint.uv,
            [
                (first.uv[0] + second.uv[0]) * 0.5,
                (first.uv[1] + second.uv[1]) * 0.5,
            ]
        );
        assert_eq!(midpoint.provenance, Provenance::Generated { operation: 1 });
        for (handle, vertex) in source_vertices {
            assert_eq!(mesh.vertex(handle), Some(&vertex));
        }
        for (_, split_face) in mesh.faces() {
            assert_eq!(split_face.submesh, face.submesh);
            assert_eq!(split_face.material, face.material);
        }
        for child in &children {
            let child = mesh.edge(*child).ok_or(MeshError::InvalidSource)?;
            assert!(child.vertices.contains(&midpoint_handle));
            assert!(
                child.vertices.contains(&edge.vertices[0])
                    || child.vertices.contains(&edge.vertices[1])
            );
        }
        mesh.validate()
    }

    #[test]
    fn every_selected_edge_pattern_preserves_triangle_winding() -> Result<(), MeshError> {
        for mask in 1_u8..8 {
            let mut mesh = triangle();
            let mut edges = mesh.edges.keys().collect::<Vec<_>>();
            edges.sort_by_key(|handle| handle.data().as_ffi());
            let selected = edges
                .into_iter()
                .enumerate()
                .filter_map(|(index, handle)| ((mask & (1 << index)) != 0).then_some(handle))
                .collect::<HashSet<_>>();
            let selected_count = selected.len();
            mesh.subdivide_edges(&selected)?;
            assert_eq!(mesh.faces.len(), selected_count + 1);
            for (_, face) in mesh.faces() {
                let a = Vec3::from_array(
                    mesh.vertex(face.vertices[0])
                        .ok_or(MeshError::InvalidSource)?
                        .position,
                );
                let b = Vec3::from_array(
                    mesh.vertex(face.vertices[1])
                        .ok_or(MeshError::InvalidSource)?
                        .position,
                );
                let c = Vec3::from_array(
                    mesh.vertex(face.vertices[2])
                        .ok_or(MeshError::InvalidSource)?
                        .position,
                );
                assert!((b - a).cross(c - a).z > 0.0);
            }
            mesh.validate()?;
        }
        Ok(())
    }

    #[test]
    fn subdividing_all_triangle_edges_is_atomic_and_rejects_stale_handles() -> Result<(), MeshError>
    {
        let mut mesh = triangle();
        let selected = mesh.edges.keys().collect::<HashSet<_>>();
        let stale = *selected.iter().next().ok_or(MeshError::InvalidSource)?;
        let children = mesh.subdivide_edges(&selected)?;
        assert_eq!(mesh.faces.len(), 4);
        assert_eq!(mesh.vertices.len(), 6);
        assert_eq!(children.len(), 6);
        assert_eq!(mesh.selection.edges, children);
        mesh.validate()?;

        let before_stale_attempt = mesh.clone();
        assert!(matches!(
            mesh.subdivide_edges(&HashSet::from([stale])),
            Err(MeshError::StaleHandle)
        ));
        assert_exact_working_state(&mesh, &before_stale_attempt);
        Ok(())
    }

    #[test]
    fn duplicate_selects_new_faces_and_preserves_source_assignments() -> Result<(), MeshError> {
        let mut mesh = triangle();
        let original = mesh.faces.keys().next().ok_or(MeshError::InvalidSource)?;
        let original_face = mesh
            .face(original)
            .cloned()
            .ok_or(MeshError::InvalidSource)?;
        let duplicated = mesh.duplicate_faces(&HashSet::from([original]))?;
        assert_eq!(duplicated.len(), 1);
        assert_eq!(mesh.selection.faces, duplicated);
        let duplicate = duplicated
            .iter()
            .next()
            .copied()
            .ok_or(MeshError::InvalidSource)?;
        let duplicate_face = mesh.face(duplicate).ok_or(MeshError::InvalidSource)?;
        assert_eq!(duplicate_face.submesh, original_face.submesh);
        assert_eq!(duplicate_face.material, original_face.material);
        mesh.validate()
    }

    #[test]
    fn duplicate_preserves_selected_patch_adjacency_and_isolates_source_vertices()
    -> Result<(), MeshError> {
        let mut mesh = two_triangle_quad();
        let source_vertices = mesh.vertices.keys().collect::<HashSet<_>>();
        let source_faces = mesh.faces.keys().collect::<HashSet<_>>();
        let duplicated = mesh.duplicate_faces(&source_faces)?;
        assert_eq!(duplicated.len(), 2);
        assert_eq!(mesh.faces.len(), 4);
        assert_eq!(mesh.vertices.len(), 8);
        assert_eq!(mesh.selection.faces, duplicated);
        let duplicate_vertices = mesh.selected_vertex_scope();
        assert_eq!(duplicate_vertices.len(), 4);
        assert!(duplicate_vertices.is_disjoint(&source_vertices));
        assert_eq!(
            mesh.edges
                .values()
                .filter(|edge| {
                    edge.faces.len() == 2 && edge.faces.iter().all(|face| duplicated.contains(face))
                })
                .count(),
            1
        );
        for face in &duplicated {
            let face = mesh.face(*face).ok_or(MeshError::InvalidSource)?;
            assert_eq!(face.submesh, 0);
            assert_eq!(face.material, 0);
        }
        mesh.validate()
    }

    #[test]
    fn duplicate_to_new_submesh_allocates_a_new_part_and_preserves_material()
    -> Result<(), MeshError> {
        let mut mesh = two_triangle_quad();
        let source_attributes = mesh.vertices.values().cloned().collect::<Vec<_>>();
        let source_faces = mesh.faces.keys().collect::<HashSet<_>>();
        let first_part = mesh.duplicate_faces_to_new_submesh(&source_faces)?;
        assert_eq!(first_part.len(), 2);
        assert!(source_faces.iter().all(|handle| {
            mesh.face(*handle)
                .is_some_and(|face| face.submesh == 0 && face.material == 0)
        }));
        assert!(first_part.iter().all(|handle| {
            mesh.face(*handle)
                .is_some_and(|face| face.submesh == 1 && face.material == 0)
        }));
        for handle in mesh.selected_vertex_scope() {
            let duplicate = mesh.vertex(handle).ok_or(MeshError::InvalidSource)?;
            assert!(matches!(
                duplicate.provenance,
                Provenance::Generated { operation: 1 }
            ));
            assert!(source_attributes.iter().any(|source| {
                source.position == duplicate.position
                    && source.normal == duplicate.normal
                    && source.uv == duplicate.uv
            }));
        }
        for handle in &first_part {
            let face = mesh.face(*handle).ok_or(MeshError::InvalidSource)?;
            let [a, b, c] = face.vertices.map(|vertex| {
                Vec3::from_array(
                    mesh.vertex(vertex)
                        .unwrap_or_else(|| panic!("duplicate face vertex is missing"))
                        .position,
                )
            });
            assert!((b - a).cross(c - a).z > 0.0);
        }
        let vertices_before_second_part = mesh
            .vertices
            .iter()
            .map(|(handle, vertex)| (handle, vertex.position))
            .collect::<HashMap<_, _>>();
        let second_part = mesh.duplicate_faces_to_new_submesh(&first_part)?;
        assert!(second_part.iter().all(|handle| {
            mesh.face(*handle)
                .is_some_and(|face| face.submesh == 2 && face.material == 0)
        }));
        assert_eq!(mesh.selection.faces, second_part);
        assert_eq!(mesh.faces.len(), 6);
        assert_eq!(mesh.vertices.len(), 12);
        let moved_positions = mesh
            .selected_vertex_scope()
            .into_iter()
            .map(|handle| {
                let position = mesh
                    .vertex(handle)
                    .ok_or(MeshError::InvalidSource)?
                    .position;
                Ok((handle, (Vec3::from_array(position) + Vec3::Z).to_array()))
            })
            .collect::<Result<HashMap<_, _>, MeshError>>()?;
        mesh.apply_positions(&moved_positions)?;
        for (handle, position) in vertices_before_second_part {
            assert_eq!(
                mesh.vertex(handle)
                    .ok_or(MeshError::InvalidSource)?
                    .position,
                position
            );
        }
        mesh.validate()
    }

    #[test]
    fn extrude_face_builds_a_moved_cap_and_three_boundary_walls() -> Result<(), MeshError> {
        let mut mesh = two_triangle_quad();
        let source_vertices = mesh
            .vertices
            .iter()
            .map(|(handle, vertex)| (handle, vertex.clone()))
            .collect::<HashMap<_, _>>();
        let selected = mesh.faces.keys().next().ok_or(MeshError::InvalidSource)?;
        let selected_face = mesh
            .faces
            .get_mut(selected)
            .ok_or(MeshError::InvalidSource)?;
        selected_face.submesh = 2;
        selected_face.material = 7;
        let source_face = mesh
            .face(selected)
            .cloned()
            .ok_or(MeshError::InvalidSource)?;
        let unselected = mesh
            .faces
            .iter()
            .find(|(handle, _)| *handle != selected)
            .map(|(handle, face)| (handle, face.clone()))
            .ok_or(MeshError::InvalidSource)?;

        let caps = mesh.extrude_faces(&HashSet::from([selected]), 0.25)?;
        assert_eq!(caps.len(), 1);
        assert_eq!(mesh.selection.faces, caps);
        assert_eq!(mesh.vertices.len(), 7);
        assert_eq!(mesh.faces.len(), 8);
        assert_eq!(mesh.face(unselected.0), Some(&unselected.1));
        for (handle, source) in &source_vertices {
            assert_eq!(mesh.vertex(*handle), Some(source));
        }

        let cap = mesh
            .face(*caps.iter().next().ok_or(MeshError::InvalidSource)?)
            .ok_or(MeshError::InvalidSource)?;
        assert_eq!(cap.submesh, source_face.submesh);
        assert_eq!(cap.material, source_face.material);
        for (source_handle, cap_handle) in source_face.vertices.into_iter().zip(cap.vertices) {
            let source = source_vertices
                .get(&source_handle)
                .ok_or(MeshError::InvalidSource)?;
            let cap_vertex = mesh.vertex(cap_handle).ok_or(MeshError::InvalidSource)?;
            assert_eq!(cap_vertex.normal, source.normal);
            assert_eq!(cap_vertex.uv, source.uv);
            assert_eq!(
                Vec3::from_array(cap_vertex.position),
                Vec3::from_array(source.position) + Vec3::Z * 0.25
            );
            assert_eq!(
                cap_vertex.provenance,
                Provenance::Generated { operation: 1 }
            );
        }
        let sides = mesh
            .faces()
            .filter(|(handle, _)| *handle != unselected.0 && !caps.contains(handle))
            .collect::<Vec<_>>();
        assert_eq!(sides.len(), 6);
        for (_, side) in sides {
            assert_eq!(side.submesh, source_face.submesh);
            assert_eq!(side.material, source_face.material);
            let [Some(a), Some(b), Some(c)] = side.vertices.map(|handle| {
                mesh.vertex(handle)
                    .map(|vertex| Vec3::from_array(vertex.position))
            }) else {
                return Err(MeshError::InvalidSource);
            };
            assert!((b - a).cross(c - a).length_squared() > 0.0);
        }
        mesh.validate()
    }

    #[test]
    fn extrude_region_shares_cap_vertices_and_skips_the_internal_wall() -> Result<(), MeshError> {
        let mut mesh = two_triangle_quad();
        let source_vertices = mesh.vertices.keys().collect::<HashSet<_>>();
        let selected = mesh.faces.keys().collect::<HashSet<_>>();
        let caps = mesh.extrude_faces(&selected, 0.5)?;

        assert_eq!(caps.len(), 2);
        assert_eq!(mesh.selection.faces, caps);
        assert_eq!(mesh.vertices.len(), 8);
        assert_eq!(mesh.faces.len(), 10);
        let cap_vertices = mesh.selected_vertex_scope();
        assert_eq!(cap_vertices.len(), 4);
        assert!(cap_vertices.is_disjoint(&source_vertices));
        assert_eq!(
            mesh.edges
                .values()
                .filter(|edge| edge.faces.len() == 2
                    && edge.faces.iter().all(|face| caps.contains(face)))
                .count(),
            1
        );
        assert_eq!(
            mesh.faces
                .values()
                .filter(|face| {
                    face.vertices
                        .iter()
                        .any(|vertex| source_vertices.contains(vertex))
                        && face
                            .vertices
                            .iter()
                            .any(|vertex| cap_vertices.contains(vertex))
                })
                .count(),
            8
        );
        mesh.validate()
    }

    #[test]
    fn inset_face_builds_an_inward_cap_and_six_owner_preserving_ring_faces() -> Result<(), MeshError>
    {
        let mut mesh = two_triangle_quad();
        let source_vertices = mesh
            .vertices
            .iter()
            .map(|(handle, vertex)| (handle, vertex.clone()))
            .collect::<HashMap<_, _>>();
        let selected = mesh.faces.keys().next().ok_or(MeshError::InvalidSource)?;
        let selected_face = mesh
            .faces
            .get_mut(selected)
            .ok_or(MeshError::InvalidSource)?;
        selected_face.submesh = 2;
        selected_face.material = 7;
        let source_face = mesh
            .face(selected)
            .cloned()
            .ok_or(MeshError::InvalidSource)?;
        let unselected = mesh
            .faces
            .iter()
            .find(|(handle, _)| *handle != selected)
            .map(|(handle, face)| (handle, face.clone()))
            .ok_or(MeshError::InvalidSource)?;
        let position_centroid = source_face
            .vertices
            .iter()
            .map(|handle| {
                source_vertices
                    .get(handle)
                    .map(|vertex| Vec3::from_array(vertex.position))
                    .ok_or(MeshError::InvalidSource)
            })
            .collect::<Result<Vec<_>, _>>()?
            .into_iter()
            .sum::<Vec3>()
            / 3.0;
        let uv_centroid = source_face
            .vertices
            .iter()
            .map(|handle| {
                source_vertices
                    .get(handle)
                    .map(|vertex| Vec2::from_array(vertex.uv))
                    .ok_or(MeshError::InvalidSource)
            })
            .collect::<Result<Vec<_>, _>>()?
            .into_iter()
            .sum::<Vec2>()
            / 3.0;

        let caps = mesh.inset_faces(&HashSet::from([selected]), 0.25)?;
        assert_eq!(caps.len(), 1);
        assert_eq!(mesh.selection.faces, caps);
        assert_eq!(mesh.vertices.len(), 7);
        assert_eq!(mesh.faces.len(), 8);
        assert_eq!(mesh.face(unselected.0), Some(&unselected.1));
        for (handle, source) in &source_vertices {
            assert_eq!(mesh.vertex(*handle), Some(source));
        }

        let cap = mesh
            .face(*caps.iter().next().ok_or(MeshError::InvalidSource)?)
            .ok_or(MeshError::InvalidSource)?;
        assert_eq!(cap.submesh, source_face.submesh);
        assert_eq!(cap.material, source_face.material);
        assert_eq!(cap.provenance, Provenance::Generated { operation: 1 });
        for (source_handle, cap_handle) in source_face.vertices.into_iter().zip(cap.vertices) {
            let source = source_vertices
                .get(&source_handle)
                .ok_or(MeshError::InvalidSource)?;
            let cap_vertex = mesh.vertex(cap_handle).ok_or(MeshError::InvalidSource)?;
            assert_eq!(cap_vertex.normal, source.normal);
            assert_eq!(
                Vec3::from_array(cap_vertex.position),
                Vec3::from_array(source.position).lerp(position_centroid, 0.25)
            );
            assert_eq!(
                Vec2::from_array(cap_vertex.uv),
                Vec2::from_array(source.uv).lerp(uv_centroid, 0.25)
            );
            assert_eq!(
                cap_vertex.provenance,
                Provenance::Generated { operation: 1 }
            );
        }
        let ring_faces = mesh
            .faces()
            .filter(|(handle, _)| *handle != unselected.0 && !caps.contains(handle))
            .collect::<Vec<_>>();
        assert_eq!(ring_faces.len(), 6);
        for (_, ring) in ring_faces {
            assert_eq!(ring.submesh, source_face.submesh);
            assert_eq!(ring.material, source_face.material);
            assert_eq!(ring.provenance, Provenance::Generated { operation: 1 });
            let [Some(a), Some(b), Some(c)] = ring.vertices.map(|handle| {
                mesh.vertex(handle)
                    .map(|vertex| Vec3::from_array(vertex.position))
            }) else {
                return Err(MeshError::InvalidSource);
            };
            assert!((b - a).cross(c - a).length_squared() > 0.0);
        }
        mesh.validate()
    }

    #[test]
    fn inset_selected_faces_individually_keeps_separate_caps() -> Result<(), MeshError> {
        let mut mesh = two_triangle_quad();
        let source_vertices = mesh
            .vertices
            .iter()
            .map(|(handle, vertex)| (handle, vertex.clone()))
            .collect::<HashMap<_, _>>();
        let selected = mesh.faces.keys().collect::<HashSet<_>>();
        let caps = mesh.inset_faces(&selected, 0.2)?;

        assert_eq!(caps.len(), 2);
        assert_eq!(mesh.selection.faces, caps);
        assert_eq!(mesh.vertices.len(), 10);
        assert_eq!(mesh.faces.len(), 14);
        for (handle, source) in &source_vertices {
            assert_eq!(mesh.vertex(*handle), Some(source));
        }
        let cap_vertex_sets = caps
            .iter()
            .map(|handle| {
                mesh.face(*handle)
                    .map(|face| face.vertices.into_iter().collect::<HashSet<_>>())
                    .ok_or(MeshError::InvalidSource)
            })
            .collect::<Result<Vec<_>, _>>()?;
        assert_eq!(cap_vertex_sets.len(), 2);
        assert!(cap_vertex_sets[0].is_disjoint(&cap_vertex_sets[1]));
        let source_handles = source_vertices.keys().copied().collect::<HashSet<_>>();
        assert!(mesh.selected_vertex_scope().is_disjoint(&source_handles));
        mesh.validate()
    }

    #[test]
    fn failed_topology_operations_leave_the_exact_working_state() -> Result<(), MeshError> {
        let mut duplicate_mesh = triangle();
        let duplicate_face = duplicate_mesh
            .faces
            .keys()
            .next()
            .ok_or(MeshError::InvalidSource)?;
        let repeated_vertex = duplicate_mesh
            .face(duplicate_face)
            .ok_or(MeshError::InvalidSource)?
            .vertices[0];
        duplicate_mesh
            .faces
            .get_mut(duplicate_face)
            .ok_or(MeshError::InvalidSource)?
            .vertices[1] = repeated_vertex;
        let duplicate_before = duplicate_mesh.clone();
        assert!(matches!(
            duplicate_mesh.duplicate_faces(&HashSet::from([duplicate_face])),
            Err(MeshError::Invariant(_))
        ));
        assert_exact_working_state(&duplicate_mesh, &duplicate_before);

        let mut subdivide_mesh = duplicate_before.clone();
        let subdivide_before = subdivide_mesh.clone();
        assert!(matches!(
            subdivide_mesh.subdivide_faces(&HashSet::from([duplicate_face])),
            Err(MeshError::Invariant(_))
        ));
        assert_exact_working_state(&subdivide_mesh, &subdivide_before);

        let mut extrude_mesh = duplicate_before.clone();
        let extrude_before = extrude_mesh.clone();
        assert!(
            extrude_mesh
                .extrude_faces(&HashSet::from([duplicate_face]), 0.25)
                .is_err()
        );
        assert_exact_working_state(&extrude_mesh, &extrude_before);

        let mut inset_mesh = duplicate_before.clone();
        let inset_before = inset_mesh.clone();
        assert!(
            inset_mesh
                .inset_faces(&HashSet::from([duplicate_face]), 0.25)
                .is_err()
        );
        assert_exact_working_state(&inset_mesh, &inset_before);

        let mut invalid_distance = triangle();
        let invalid_distance_face = invalid_distance
            .faces
            .keys()
            .next()
            .ok_or(MeshError::InvalidSource)?;
        let invalid_distance_before = invalid_distance.clone();
        for distance in [0.0, -1.0, f32::NAN, f32::INFINITY] {
            assert!(matches!(
                invalid_distance.extrude_faces(&HashSet::from([invalid_distance_face]), distance),
                Err(MeshError::Invariant(_))
            ));
            assert_exact_working_state(&invalid_distance, &invalid_distance_before);
        }

        let mut invalid_amount = triangle();
        let invalid_amount_face = invalid_amount
            .faces
            .keys()
            .next()
            .ok_or(MeshError::InvalidSource)?;
        let invalid_amount_before = invalid_amount.clone();
        for amount in [0.0, -1.0, 1.0, 1.1, f32::NAN, f32::INFINITY] {
            assert!(matches!(
                invalid_amount.inset_faces(&HashSet::from([invalid_amount_face]), amount),
                Err(MeshError::Invariant(_))
            ));
            assert_exact_working_state(&invalid_amount, &invalid_amount_before);
        }
        assert!(matches!(
            invalid_amount.inset_faces(&HashSet::new(), 0.25),
            Err(MeshError::EmptyOperation)
        ));
        assert_exact_working_state(&invalid_amount, &invalid_amount_before);

        let mut stale_inset = triangle();
        let stale_face = stale_inset
            .faces
            .keys()
            .next()
            .ok_or(MeshError::InvalidSource)?;
        stale_inset.delete_faces(&HashSet::from([stale_face]))?;
        let stale_before = stale_inset.clone();
        assert!(matches!(
            stale_inset.inset_faces(&HashSet::from([stale_face]), 0.25),
            Err(MeshError::StaleHandle)
        ));
        assert_exact_working_state(&stale_inset, &stale_before);

        let mut invalid_normal = triangle();
        let invalid_normal_face = invalid_normal
            .faces
            .keys()
            .next()
            .ok_or(MeshError::InvalidSource)?;
        let invalid_normal_vertex = invalid_normal
            .face(invalid_normal_face)
            .ok_or(MeshError::InvalidSource)?
            .vertices[0];
        invalid_normal
            .vertices
            .get_mut(invalid_normal_vertex)
            .ok_or(MeshError::InvalidSource)?
            .normal = [0.0; 3];
        let invalid_normal_before = invalid_normal.clone();
        assert!(matches!(
            invalid_normal.extrude_faces(&HashSet::from([invalid_normal_face]), 0.25),
            Err(MeshError::Invariant(_))
        ));
        assert_exact_working_state(&invalid_normal, &invalid_normal_before);

        let mut exhausted_submesh = triangle();
        let exhausted_face = exhausted_submesh
            .faces
            .keys()
            .next()
            .ok_or(MeshError::InvalidSource)?;
        exhausted_submesh
            .faces
            .get_mut(exhausted_face)
            .ok_or(MeshError::InvalidSource)?
            .submesh = u32::MAX;
        let exhausted_before = exhausted_submesh.clone();
        assert!(matches!(
            exhausted_submesh.duplicate_faces_to_new_submesh(&HashSet::new()),
            Err(MeshError::EmptyOperation)
        ));
        assert_exact_working_state(&exhausted_submesh, &exhausted_before);
        assert!(matches!(
            exhausted_submesh.duplicate_faces_to_new_submesh(&HashSet::from([exhausted_face])),
            Err(MeshError::Invariant(_))
        ));
        assert_exact_working_state(&exhausted_submesh, &exhausted_before);

        let mut delete_mesh = triangle();
        let valid_face = delete_mesh
            .faces
            .keys()
            .next()
            .ok_or(MeshError::InvalidSource)?;
        let mut invalid_face = delete_mesh
            .face(valid_face)
            .cloned()
            .ok_or(MeshError::InvalidSource)?;
        invalid_face.vertices[1] = invalid_face.vertices[0];
        delete_mesh.faces.insert(invalid_face);
        let delete_before = delete_mesh.clone();
        assert!(matches!(
            delete_mesh.delete_faces(&HashSet::from([valid_face])),
            Err(MeshError::Invariant(_))
        ));
        assert_exact_working_state(&delete_mesh, &delete_before);
        Ok(())
    }

    #[test]
    fn subdivision_rejects_attribute_overflow_without_mutating_the_mesh() -> Result<(), MeshError> {
        let mut mesh = triangle();
        let edge = mesh.edges.keys().next().ok_or(MeshError::InvalidSource)?;
        let endpoints = mesh.edge(edge).ok_or(MeshError::StaleHandle)?.vertices;
        for endpoint in endpoints {
            mesh.vertices
                .get_mut(endpoint)
                .ok_or(MeshError::StaleHandle)?
                .position[0] = f32::MAX;
        }
        mesh.validate()?;
        let before = mesh.clone();

        assert!(matches!(
            mesh.subdivide_edges(&HashSet::from([edge])),
            Err(MeshError::Invariant(message)) if message.contains("non-finite attribute")
        ));
        assert_exact_working_state(&mesh, &before);
        Ok(())
    }

    #[test]
    fn validation_rejects_non_finite_position_normal_and_uv_components() {
        for attribute in ["position", "normal", "uv"] {
            let mut mesh = triangle();
            let handle = mesh
                .vertices
                .keys()
                .next()
                .unwrap_or_else(|| panic!("triangle must contain a vertex"));
            let vertex = mesh
                .vertices
                .get_mut(handle)
                .unwrap_or_else(|| panic!("triangle vertex must remain live"));
            match attribute {
                "position" => vertex.position[0] = f32::NAN,
                "normal" => vertex.normal[1] = f32::INFINITY,
                "uv" => vertex.uv[0] = f32::NEG_INFINITY,
                _ => unreachable!(),
            }
            assert!(matches!(
                mesh.validate(),
                Err(MeshError::Invariant(message)) if message.contains("non-finite attribute")
            ));
        }
    }

    #[test]
    fn stale_face_handle_is_rejected_after_delete() -> Result<(), MeshError> {
        let mut mesh = triangle();
        let face = mesh.faces.keys().next().ok_or(MeshError::InvalidSource)?;
        mesh.delete_faces(&HashSet::from([face]))?;
        assert!(matches!(
            mesh.delete_faces(&HashSet::from([face])),
            Err(MeshError::StaleHandle)
        ));
        Ok(())
    }

    #[test]
    fn one_commit_round_trips_through_undo_and_redo() -> Result<(), MeshError> {
        let mut mesh = triangle();
        let before = mesh.clone();
        let handles = mesh.vertices.keys().collect::<HashSet<_>>();
        mesh.translate_vertices(&handles, Vec3::Z)?;
        let committed = mesh.structural_fingerprint();
        let mut history = History::new(1_000_000);
        history.commit("translate", before.clone(), &mesh)?;
        assert_eq!(history.undo_len(), 1);
        assert_eq!(history.budget_bytes(), 1_000_000);
        let committed_bytes = history.retained_bytes();
        assert!(committed_bytes > 0);
        assert!(committed_bytes <= history.budget_bytes());
        history.undo(&mut mesh)?;
        assert_eq!(history.retained_bytes(), committed_bytes);
        assert_eq!(
            mesh.structural_fingerprint(),
            before.structural_fingerprint()
        );
        history.redo(&mut mesh)?;
        assert_eq!(history.retained_bytes(), committed_bytes);
        assert_eq!(mesh.structural_fingerprint(), committed);
        Ok(())
    }

    #[test]
    fn history_rejects_invalid_snapshots_and_cross_mesh_replay_atomically() -> Result<(), MeshError>
    {
        let mut invalid_before = triangle();
        let invalid_handle = invalid_before
            .vertices
            .keys()
            .next()
            .ok_or(MeshError::InvalidSource)?;
        let valid_after = invalid_before.clone();
        invalid_before
            .vertices
            .get_mut(invalid_handle)
            .ok_or(MeshError::StaleHandle)?
            .position[0] = f32::NAN;
        let mut rejected = History::new(1_000_000);
        assert!(matches!(
            rejected.commit("invalid", invalid_before, &valid_after),
            Err(MeshError::Invariant(_))
        ));
        assert!(rejected.undo.is_empty());
        assert!(rejected.redo.is_empty());

        let mut mesh = triangle();
        let before = mesh.clone();
        let handles = mesh.vertices.keys().collect::<HashSet<_>>();
        mesh.translate_vertices(&handles, Vec3::Z)?;
        let after = mesh.clone();
        let mut history = History::new(1_000_000);
        history.commit("translate", before, &mesh)?;

        let mut other = triangle();
        let other_before = other.clone();
        assert!(matches!(
            history.undo(&mut other),
            Err(MeshError::Invariant(message)) if message.contains("different mesh")
        ));
        assert_exact_working_state(&other, &other_before);
        assert_eq!(history.undo.len(), 1);
        assert!(history.redo.is_empty());

        history.undo(&mut mesh)?;
        assert!(history.undo.is_empty());
        assert_eq!(history.redo.len(), 1);
        assert!(matches!(
            history.redo(&mut other),
            Err(MeshError::Invariant(message)) if message.contains("different mesh")
        ));
        assert_exact_working_state(&other, &other_before);
        assert!(history.undo.is_empty());
        assert_eq!(history.redo.len(), 1);

        history.redo(&mut mesh)?;
        assert_exact_working_state(&mesh, &after);
        Ok(())
    }

    #[test]
    fn new_commit_releases_discarded_redo_memory() -> Result<(), MeshError> {
        let mut mesh = triangle();
        let baseline = mesh.clone();
        let handles = mesh.vertices.keys().collect::<HashSet<_>>();
        mesh.translate_vertices(&handles, Vec3::X)?;
        let mut history = History::new(1_000_000);
        history.commit("first", baseline, &mesh)?;
        let first_entry_bytes = history.retained_bytes();
        history.undo(&mut mesh)?;
        assert_eq!(history.retained_bytes(), first_entry_bytes);

        let second_before = mesh.clone();
        mesh.translate_vertices(&handles, Vec3::Y)?;
        let second_entry_bytes =
            estimate_mesh_bytes(&second_before).saturating_add(estimate_mesh_bytes(&mesh));
        history.commit("second", second_before, &mesh)?;
        assert_eq!(history.retained_bytes(), second_entry_bytes);
        assert_eq!(history.undo_len(), 1);
        Ok(())
    }

    #[test]
    fn rotate_and_scale_selected_vertices_preserve_invariants() -> Result<(), MeshError> {
        let mut mesh = triangle();
        let handles = mesh.vertices.keys().collect::<HashSet<_>>();
        mesh.rotate_vertices(
            &handles,
            Vec3::ZERO,
            Quat::from_rotation_z(std::f32::consts::FRAC_PI_2),
        )?;
        mesh.scale_vertices(&handles, Vec3::ZERO, Vec3::splat(2.0))?;
        assert!(mesh.vertices.values().any(|vertex| {
            Vec3::from_array(vertex.position).distance(Vec3::new(0.0, 2.0, 0.0)) < 1.0e-5
        }));
        mesh.validate()
    }

    #[test]
    fn deformation_preserves_positions_and_normals_outside_the_affected_one_ring()
    -> Result<(), MeshError> {
        let mut mesh = two_disconnected_triangles();
        let changed = mesh
            .vertices()
            .find_map(|(handle, vertex)| {
                (vertex.provenance
                    == Provenance::Source {
                        submesh: 0,
                        element: 0,
                    })
                .then_some(handle)
            })
            .ok_or(MeshError::InvalidSource)?;
        let untouched = mesh
            .vertices()
            .filter(|(_, vertex)| {
                vertex.provenance
                    == Provenance::Source {
                        submesh: 1,
                        element: 0,
                    }
            })
            .map(|(handle, vertex)| (handle, vertex.clone()))
            .collect::<Vec<_>>();
        let mut position = mesh.vertex(changed).ok_or(MeshError::StaleHandle)?.position;
        position[2] += 0.25;
        mesh.apply_positions(&HashMap::from([(changed, position)]))?;
        for (handle, vertex) in untouched {
            assert_eq!(mesh.vertex(handle), Some(&vertex));
        }
        assert!(
            mesh.vertices()
                .filter(|(_, vertex)| vertex.provenance
                    == Provenance::Source {
                        submesh: 0,
                        element: 0
                    })
                .all(|(_, vertex)| vertex.normal != [1.0, 0.0, 0.0])
        );
        mesh.validate()
    }

    #[test]
    fn topology_operations_preserve_existing_source_normals_outside_their_generated_vertices()
    -> Result<(), MeshError> {
        for operation in ["delete", "duplicate", "subdivide"] {
            let mut mesh = two_disconnected_triangles();
            let selected = mesh
                .faces()
                .find_map(|(handle, face)| (face.submesh == 0).then_some(handle))
                .ok_or(MeshError::InvalidSource)?;
            let originals = mesh
                .vertices()
                .map(|(handle, vertex)| (handle, vertex.normal))
                .collect::<Vec<_>>();
            match operation {
                "delete" => mesh.delete_faces(&HashSet::from([selected]))?,
                "duplicate" => {
                    mesh.duplicate_faces(&HashSet::from([selected]))?;
                }
                "subdivide" => {
                    mesh.subdivide_faces(&HashSet::from([selected]))?;
                }
                _ => unreachable!(),
            }
            for (handle, normal) in originals {
                if let Some(vertex) = mesh.vertex(handle) {
                    assert_eq!(vertex.normal, normal, "{operation} changed {handle:?}");
                }
            }
            mesh.validate()?;
        }
        Ok(())
    }
}
