#![forbid(unsafe_code)]

use cdmw_interaction::{InteractionError, OperatorController, SculptTool};
use cdmw_mesh::{EdgeHandle, FaceHandle, History, MeshError, VertexHandle, WorkingMesh};
use glam::Vec3;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use thiserror::Error;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ReplayEvent {
    Translate {
        vertex_ordinals: Vec<usize>,
        delta: [f32; 3],
    },
    Sculpt {
        tool: ReplaySculptTool,
        vertex_ordinals: Vec<usize>,
        center: [f32; 3],
        delta: [f32; 3],
        strength: f32,
    },
    DeleteFaces {
        face_ordinals: Vec<usize>,
    },
    SubdivideFaces {
        face_ordinals: Vec<usize>,
    },
    SubdivideEdges {
        edge_ordinals: Vec<usize>,
    },
    DuplicateFaces {
        face_ordinals: Vec<usize>,
    },
    Undo,
    Redo,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReplaySculptTool {
    Grab,
    Smooth,
    Inflate,
    Pinch,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReplayReport {
    pub events_executed: usize,
    pub final_fingerprint: String,
    pub final_vertices: usize,
    pub final_faces: usize,
    pub history_entries: usize,
}

#[derive(Debug, Error)]
pub enum ReplayError {
    #[error("mesh operation failed: {0}")]
    Mesh(#[from] MeshError),
    #[error("interaction failed: {0}")]
    Interaction(#[from] InteractionError),
    #[error("replay references an element ordinal that does not exist")]
    InvalidOrdinal,
}

pub fn run_replay(
    mesh: &mut WorkingMesh,
    events: &[ReplayEvent],
    history_budget: usize,
) -> Result<ReplayReport, ReplayError> {
    let mut history = History::new(history_budget);
    let mut controller = OperatorController::default();
    for event in events {
        match event {
            ReplayEvent::Translate {
                vertex_ordinals,
                delta,
            } => {
                let handles = vertex_handles(mesh, vertex_ordinals)?;
                let gesture = controller.begin(mesh, "replay translate")?;
                controller.translate(mesh, gesture, &handles, Vec3::from_array(*delta))?;
                controller.confirm(mesh, &mut history, gesture)?;
            }
            ReplayEvent::Sculpt {
                tool,
                vertex_ordinals,
                center,
                delta,
                strength,
            } => {
                let handles = vertex_handles(mesh, vertex_ordinals)?;
                let gesture = controller.begin(mesh, "replay sculpt")?;
                controller.sculpt(
                    mesh,
                    gesture,
                    (*tool).into(),
                    &handles,
                    Vec3::from_array(*center),
                    Vec3::from_array(*delta),
                    *strength,
                )?;
                controller.confirm(mesh, &mut history, gesture)?;
            }
            ReplayEvent::DeleteFaces { face_ordinals } => {
                let before = mesh.clone();
                mesh.delete_faces(&face_handles(mesh, face_ordinals)?)?;
                history.commit("replay delete", before, mesh)?;
            }
            ReplayEvent::SubdivideFaces { face_ordinals } => {
                let before = mesh.clone();
                let _ = mesh.subdivide_faces(&face_handles(mesh, face_ordinals)?)?;
                history.commit("replay subdivide", before, mesh)?;
            }
            ReplayEvent::SubdivideEdges { edge_ordinals } => {
                let before = mesh.clone();
                let _ = mesh.subdivide_edges(&edge_handles(mesh, edge_ordinals)?)?;
                history.commit("replay subdivide edges", before, mesh)?;
            }
            ReplayEvent::DuplicateFaces { face_ordinals } => {
                let before = mesh.clone();
                let _ = mesh.duplicate_faces(&face_handles(mesh, face_ordinals)?)?;
                history.commit("replay duplicate", before, mesh)?;
            }
            ReplayEvent::Undo => history.undo(mesh)?,
            ReplayEvent::Redo => history.redo(mesh)?,
        }
    }
    mesh.validate()?;
    Ok(ReplayReport {
        events_executed: events.len(),
        final_fingerprint: mesh.structural_fingerprint(),
        final_vertices: mesh.vertices().count(),
        final_faces: mesh.faces().count(),
        history_entries: history.undo_len(),
    })
}

impl From<ReplaySculptTool> for SculptTool {
    fn from(value: ReplaySculptTool) -> Self {
        match value {
            ReplaySculptTool::Grab => SculptTool::Grab,
            ReplaySculptTool::Smooth => SculptTool::Smooth,
            ReplaySculptTool::Inflate => SculptTool::Inflate,
            ReplaySculptTool::Pinch => SculptTool::Pinch,
        }
    }
}

fn vertex_handles(
    mesh: &WorkingMesh,
    ordinals: &[usize],
) -> Result<HashSet<VertexHandle>, ReplayError> {
    ordinal_handles(mesh.vertices().map(|(handle, _)| handle), ordinals)
}

fn face_handles(
    mesh: &WorkingMesh,
    ordinals: &[usize],
) -> Result<HashSet<FaceHandle>, ReplayError> {
    ordinal_handles(mesh.faces().map(|(handle, _)| handle), ordinals)
}

fn edge_handles(
    mesh: &WorkingMesh,
    ordinals: &[usize],
) -> Result<HashSet<EdgeHandle>, ReplayError> {
    ordinal_handles(mesh.edges().map(|(handle, _)| handle), ordinals)
}

fn ordinal_handles<T: Copy + Eq + std::hash::Hash>(
    handles: impl Iterator<Item = T>,
    ordinals: &[usize],
) -> Result<HashSet<T>, ReplayError> {
    let handles = handles.collect::<Vec<_>>();
    ordinals
        .iter()
        .map(|ordinal| {
            handles
                .get(*ordinal)
                .copied()
                .ok_or(ReplayError::InvalidOrdinal)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use cdmw_formats::{MeshFormat, decode_mesh};

    fn stress_events() -> Vec<ReplayEvent> {
        let mut events = Vec::new();
        for index in 0..1_000 {
            match index % 5 {
                0 => events.push(ReplayEvent::Translate {
                    vertex_ordinals: vec![0, 1, 2],
                    delta: [0.0001, 0.0, 0.0],
                }),
                1 => events.push(ReplayEvent::Sculpt {
                    tool: ReplaySculptTool::Smooth,
                    vertex_ordinals: vec![0, 1, 2],
                    center: [0.0, 0.0, 0.0],
                    delta: [0.0, 0.0, 0.0],
                    strength: 0.01,
                }),
                2 => events.push(ReplayEvent::Sculpt {
                    tool: ReplaySculptTool::Inflate,
                    vertex_ordinals: vec![0, 1, 2],
                    center: [0.0, 0.0, 0.0],
                    delta: [0.0, 0.0, 0.0],
                    strength: 0.0001,
                }),
                3 => events.push(ReplayEvent::Undo),
                _ => events.push(ReplayEvent::Redo),
            }
        }
        events
    }

    fn synthetic_mesh() -> Result<WorkingMesh, ReplayError> {
        let document = decode_mesh(
            &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
            MeshFormat::Pam,
        )
        .map_err(|error| MeshError::Invariant(error.to_string()))?;
        WorkingMesh::from_document(&document).map_err(ReplayError::from)
    }

    #[test]
    fn one_thousand_mixed_events_are_deterministic_and_invariant_safe() -> Result<(), ReplayError> {
        let events = stress_events();
        let mut first = synthetic_mesh()?;
        let mut second = synthetic_mesh()?;
        let first_report = run_replay(&mut first, &events, 8 * 1024 * 1024)?;
        let second_report = run_replay(&mut second, &events, 8 * 1024 * 1024)?;
        assert_eq!(first_report.events_executed, 1_000);
        assert_eq!(
            first_report.final_fingerprint,
            second_report.final_fingerprint
        );
        first.validate()?;
        second.validate()?;
        Ok(())
    }
}
