use anyhow::{Context, Result, ensure};
use cdmw_formats::MeshDocument;
use cdmw_mesh::WorkingMesh;
use cdmw_replay::{ReplayEvent, ReplayReport, ReplaySculptTool, run_replay};
use serde::Serialize;
use std::time::Instant;

const HISTORY_BUDGET_BYTES: usize = 512 * 1024 * 1024;

#[derive(Debug, Serialize)]
pub struct HeadlessMeshReport {
    pub schema_version: u32,
    pub proof_class: &'static str,
    pub source_content_hash: String,
    pub source_format: String,
    pub parser: String,
    pub lod_count_reported: u32,
    pub lods_loaded: usize,
    pub vertex_count: usize,
    pub face_count: usize,
    pub decode_ms: f64,
    pub scenario_total_ms: f64,
    pub scenarios: Vec<HeadlessScenarioReport>,
}

#[derive(Debug, Serialize)]
pub struct HeadlessScenarioReport {
    pub lod_level: u32,
    pub name: &'static str,
    pub operation_ms: f64,
    pub undo_ms: f64,
    pub redo_ms: f64,
    pub final_vertices: usize,
    pub final_faces: usize,
    pub history_entries: usize,
    pub exact_undo_redo: bool,
    pub invariants_passed: bool,
}

pub fn run_headless_mesh_check(
    document: &MeshDocument,
    decode_ms: f64,
) -> Result<HeadlessMeshReport> {
    let baseline = WorkingMesh::from_document(document)?;
    let vertex_count = baseline.vertices().count();
    let face_count = baseline.faces().count();
    ensure!(
        vertex_count >= 3,
        "headless mesh check requires at least three vertices"
    );
    ensure!(
        face_count >= 1,
        "headless mesh check requires at least one face"
    );
    let started = Instant::now();
    let mut reports = Vec::with_capacity(document.lods.len().saturating_mul(8));
    for (lod_index, lod) in document.lods.iter().enumerate() {
        let lod_baseline =
            WorkingMesh::from_document_lod(document, lod_index).with_context(|| {
                format!(
                    "headless LOD {} working mesh construction failed",
                    lod.level
                )
            })?;
        let lod_vertex_count = lod_baseline.vertices().count();
        let lod_face_count = lod_baseline.faces().count();
        ensure!(
            lod_vertex_count >= 3 && lod_face_count >= 1,
            "headless LOD {} requires editable triangle geometry",
            lod.level
        );
        let baseline_fingerprint = lod_baseline.structural_fingerprint();
        for (name, event) in scenario_events(lod_vertex_count) {
            reports.push(run_scenario(
                document,
                lod_index,
                lod.level,
                &baseline_fingerprint,
                name,
                event,
            )?);
        }
    }
    Ok(HeadlessMeshReport {
        schema_version: 1,
        proof_class: "headless CPU app-core exercise; no window or GPU frame proof",
        source_content_hash: document.source_sha256.clone(),
        source_format: format!("{:?}", document.format).to_ascii_lowercase(),
        parser: document.parser.clone(),
        lod_count_reported: document.lod_count_reported,
        lods_loaded: document.lods.len(),
        vertex_count,
        face_count,
        decode_ms,
        scenario_total_ms: started.elapsed().as_secs_f64() * 1_000.0,
        scenarios: reports,
    })
}

fn scenario_events(vertex_count: usize) -> [(&'static str, ReplayEvent); 8] {
    let vertex_ordinals = (0..vertex_count.min(64)).collect::<Vec<_>>();
    [
        (
            "move",
            ReplayEvent::Translate {
                vertex_ordinals: vertex_ordinals.clone(),
                delta: [0.0005, 0.0002, 0.0001],
            },
        ),
        (
            "grab",
            ReplayEvent::Sculpt {
                tool: ReplaySculptTool::Grab,
                vertex_ordinals: vertex_ordinals.clone(),
                center: [0.0, 0.0, 0.0],
                delta: [0.0003, -0.0002, 0.0001],
                strength: 1.0,
            },
        ),
        (
            "smooth",
            ReplayEvent::Sculpt {
                tool: ReplaySculptTool::Smooth,
                vertex_ordinals: vertex_ordinals.clone(),
                center: [0.0, 0.0, 0.0],
                delta: [0.0, 0.0, 0.0],
                strength: 0.05,
            },
        ),
        (
            "inflate",
            ReplayEvent::Sculpt {
                tool: ReplaySculptTool::Inflate,
                vertex_ordinals: vertex_ordinals.clone(),
                center: [0.0, 0.0, 0.0],
                delta: [0.0, 0.0, 0.0],
                strength: 0.0001,
            },
        ),
        (
            "pinch",
            ReplayEvent::Sculpt {
                tool: ReplaySculptTool::Pinch,
                vertex_ordinals,
                center: [0.0, 0.0, 0.0],
                delta: [0.0, 0.0, 0.0],
                strength: 0.01,
            },
        ),
        (
            "delete_face",
            ReplayEvent::DeleteFaces {
                face_ordinals: vec![0],
            },
        ),
        (
            "subdivide_face",
            ReplayEvent::SubdivideFaces {
                face_ordinals: vec![0],
            },
        ),
        (
            "duplicate_face",
            ReplayEvent::DuplicateFaces {
                face_ordinals: vec![0],
            },
        ),
    ]
}

fn run_scenario(
    document: &MeshDocument,
    lod_index: usize,
    lod_level: u32,
    baseline_fingerprint: &str,
    name: &'static str,
    event: ReplayEvent,
) -> Result<HeadlessScenarioReport> {
    let (operation, operation_ms) = run_variant(document, lod_index, std::slice::from_ref(&event))?;
    ensure!(
        operation.final_fingerprint != baseline_fingerprint,
        "headless LOD {lod_level} {name} scenario made no geometry change"
    );
    let (undo, undo_ms) = run_variant(document, lod_index, &[event.clone(), ReplayEvent::Undo])?;
    let (redo, redo_ms) = run_variant(
        document,
        lod_index,
        &[event, ReplayEvent::Undo, ReplayEvent::Redo],
    )?;
    let exact_undo_redo = undo.final_fingerprint == baseline_fingerprint
        && redo.final_fingerprint == operation.final_fingerprint;
    ensure!(
        exact_undo_redo,
        "headless LOD {lod_level} {name} undo/redo mismatch: baseline={baseline_fingerprint}, operation={}, undo={}, redo={}",
        operation.final_fingerprint,
        undo.final_fingerprint,
        redo.final_fingerprint
    );
    ensure!(
        operation.history_entries == 1,
        "headless LOD {lod_level} {name} created the wrong history count"
    );
    ensure!(
        redo.history_entries == 1,
        "headless LOD {lod_level} {name} redo did not restore history"
    );
    Ok(HeadlessScenarioReport {
        lod_level,
        name,
        operation_ms,
        undo_ms,
        redo_ms,
        final_vertices: operation.final_vertices,
        final_faces: operation.final_faces,
        history_entries: operation.history_entries,
        exact_undo_redo,
        invariants_passed: true,
    })
}

fn run_variant(
    document: &MeshDocument,
    lod_index: usize,
    events: &[ReplayEvent],
) -> Result<(ReplayReport, f64)> {
    let mut mesh = WorkingMesh::from_document_lod(document, lod_index)?;
    let started = Instant::now();
    let report = run_replay(&mut mesh, events, HISTORY_BUDGET_BYTES)
        .with_context(|| format!("headless replay failed after {} event(s)", events.len()))?;
    mesh.validate()?;
    Ok((report, started.elapsed().as_secs_f64() * 1_000.0))
}

#[cfg(test)]
mod tests {
    use super::*;
    use cdmw_formats::{MeshFormat, decode_mesh};

    #[test]
    fn synthetic_headless_mesh_check_covers_every_edit_family_on_every_lod() -> Result<()> {
        let document = decode_mesh(&cdmw_formats::synthetic::two_lod_pac(), MeshFormat::Pac)?;
        let report = run_headless_mesh_check(&document, 0.0)?;
        assert_eq!(report.lods_loaded, 2);
        assert_eq!(report.scenarios.len(), 16);
        assert_eq!(
            report
                .scenarios
                .iter()
                .filter(|scenario| scenario.lod_level == 0)
                .count(),
            8
        );
        assert_eq!(
            report
                .scenarios
                .iter()
                .filter(|scenario| scenario.lod_level == 1)
                .count(),
            8
        );
        assert!(
            report
                .scenarios
                .iter()
                .all(|scenario| scenario.exact_undo_redo && scenario.invariants_passed)
        );
        Ok(())
    }
}
