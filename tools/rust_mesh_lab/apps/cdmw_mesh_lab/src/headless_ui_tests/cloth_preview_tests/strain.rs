//! Explicit local-input diagnostics; no game data is embedded in the tests.
use crate::cdmw_cloth::preview::{SUBSTEPS, substep_settings};
use cdmw_mesh::{
    cloth::{Constraint, Settings, Simulation, Snapshot},
    jiggle_rig::RigSnapshot,
};
use glam::DVec3;
use serde_json::{Value, json};
use std::path::PathBuf;

#[test]
#[ignore = "requires caller-owned decoded cloth snapshots and a report path"]
fn supplied_guides_measure_constraint_strain() -> std::result::Result<(), Box<dyn std::error::Error>>
{
    let cases: Vec<Value> =
        serde_json::from_slice(&std::fs::read(std::env::var("CDMW_MOTION_PROBE_CASES")?)?)?;
    let report = PathBuf::from(std::env::var("CDMW_CLOTH_STRAIN_REPORT")?);
    let identity = [
        [1., 0., 0., 0.],
        [0., 1., 0., 0.],
        [0., 0., 1., 0.],
        [0., 0., 0., 1.],
    ];
    let mut results = Vec::new();
    for case in cases {
        if case["cloth_available"].as_bool() != Some(true) {
            continue;
        }
        let manifest = PathBuf::from(case["manifest"].as_str().ok_or("manifest path")?);
        let payload: Value = serde_json::from_slice(&std::fs::read(
            manifest.parent().ok_or("parent")?.join("jiggle-rig.json"),
        )?)?;
        let snapshot: Snapshot = serde_json::from_value(payload["cloth"].clone())?;
        let rig: RigSnapshot = serde_json::from_value(payload["rig"].clone())?;
        // Render binding is incidental here: particle integration uses all of
        // the supplied guide frames, authored constraints and fixed vertices.
        let mut record = [0_u8; 40];
        record[28] = 255;
        record[32] = 255;
        let rest = [snapshot.animation_frames[0][3][..3]
            .try_into()
            .map(|p: [f64; 3]| p.map(|v| v as f32))?];
        for substeps in [1, SUBSTEPS] {
            let mut simulation =
                Simulation::new(snapshot.clone(), &rig, &rest, &[record], &[0], &|| false)?;
            let settings = if substeps == 1 {
                Settings::default()
            } else {
                substep_settings(Settings::default())?
            };
            for _ in 0..120 * substeps {
                simulation.step(1. / (60 * substeps) as f64, identity, settings)?;
            }
            let positions = simulation
                .guide_positions()
                .into_iter()
                .map(DVec3::from)
                .collect::<Vec<_>>();
            let mut ratios = snapshot
                .constraints
                .iter()
                .filter_map(|c| match c {
                    Constraint::Pair {
                        indices: [a, b],
                        rest,
                    } if *rest > 0. => Some(positions[*a].distance(positions[*b]) / rest),
                    _ => None,
                })
                .collect::<Vec<_>>();
            ratios.sort_by(f64::total_cmp);
            if substeps == SUBSTEPS
                && let Some(limit) = case["max_pair_ratio"].as_f64()
            {
                assert!(
                    ratios.last().is_some_and(|ratio| *ratio <= limit),
                    "{} exceeded its supplied strain limit",
                    case["name"]
                );
            }
            let displacement = positions
                .iter()
                .zip(&snapshot.animation_frames)
                .map(|(p, frame)| p.distance(DVec3::new(frame[3][0], frame[3][1], frame[3][2])))
                .fold(0.0, f64::max);
            let result = json!({"name": case["name"], "substeps": substeps,
                "max_pair_ratio": ratios.last(), "p95_pair_ratio": ratios[ratios.len()*95/100],
                "max_guide_displacement": displacement});
            println!("{result}");
            results.push(result);
        }
    }
    assert!(!results.is_empty(), "no supplied cloth cases");
    std::fs::write(report, serde_json::to_vec_pretty(&results)?)?;
    Ok(())
}

#[test]
#[ignore = "requires caller-owned decoded cloth snapshots and a report path"]
fn supplied_guides_measure_body_contact_response()
-> std::result::Result<(), Box<dyn std::error::Error>> {
    let cases: Vec<Value> =
        serde_json::from_slice(&std::fs::read(std::env::var("CDMW_MOTION_PROBE_CASES")?)?)?;
    let report = PathBuf::from(std::env::var("CDMW_CLOTH_CONTACT_REPORT")?);
    let mut results = Vec::new();
    for case in cases {
        if case["cloth_available"].as_bool() != Some(true) {
            continue;
        }
        let manifest = PathBuf::from(case["manifest"].as_str().ok_or("manifest path")?);
        let payload_path = manifest.parent().ok_or("parent")?.join("jiggle-rig.json");
        let before = std::fs::read(&payload_path)?;
        let payload: Value = serde_json::from_slice(&before)?;
        let snapshot: Snapshot = serde_json::from_value(payload["cloth"].clone())?;
        let rig: RigSnapshot = serde_json::from_value(payload["rig"].clone())?;
        let package = crate::cdmw_session::LoadedCdmwSessionPackage::load(&manifest)?;
        let mesh = cdmw_mesh::WorkingMesh::from_document(package.document())?;
        let draw = mesh.draw_snapshot();
        let bounds = draw.positions.iter().map(|p| glam::Vec3::from(*p)).fold(
            (
                glam::Vec3::splat(f32::INFINITY),
                glam::Vec3::splat(f32::NEG_INFINITY),
            ),
            |(lo, hi), p| (lo.min(p), hi.max(p)),
        );
        let scale = (bounds.1 - bounds.0).max_element();
        let rest = snapshot
            .animation_frames
            .iter()
            .map(|frame| DVec3::new(frame[3][0], frame[3][1], frame[3][2]))
            .collect::<Vec<_>>();
        let mut record = [0_u8; 40];
        record[28] = 255;
        record[32] = 255;
        for up_down in [false, true] {
            for body_collisions in [false, true] {
                let mut simulation = Simulation::new(
                    snapshot.clone(),
                    &rig,
                    &[rest[0].as_vec3().to_array()],
                    &[record],
                    &[0],
                    &|| false,
                )?;
                let settings = substep_settings(Settings {
                    body_collisions,
                    ..Settings::default()
                })?;
                let dt = 1.0 / (60 * SUBSTEPS) as f64;
                let mut peak_displacement = 0.0_f64;
                let mut peak_upward = 0.0_f64;
                let mut samples = Vec::new();
                for step in 1..=240 * SUBSTEPS {
                    let phase = (f64::from(step) * dt / 1.2 * std::f64::consts::TAU) as f32;
                    let dy = if up_down {
                        scale * 0.06 * (1.0 - phase.cos())
                    } else {
                        0.0
                    };
                    let translation = DVec3::Y * f64::from(dy);
                    let motion = glam::DMat4::from_translation(translation).to_cols_array_2d();
                    simulation.step(dt, motion, settings)?;
                    let deltas = simulation
                        .guide_positions()
                        .into_iter()
                        .zip(&rest)
                        .map(|(p, r)| DVec3::from(p) - r - translation)
                        .collect::<Vec<_>>();
                    let displacement = deltas.iter().map(|d| d.length()).fold(0.0, f64::max);
                    let upward = deltas.iter().map(|d| d.y).fold(0.0, f64::max);
                    assert!(displacement.is_finite() && upward.is_finite());
                    peak_displacement = peak_displacement.max(displacement);
                    peak_upward = peak_upward.max(upward);
                    if step % SUBSTEPS == 0
                        && [1, 10, 30, 60, 120, 240].contains(&(step / SUBSTEPS))
                    {
                        samples.push(
                            json!({"frame": step / SUBSTEPS, "max_displacement": displacement,
                            "max_upward": upward}),
                        );
                    }
                }
                let row = json!({"name": case["name"], "body_collisions": body_collisions,
                    "up_down": up_down, "collider_count": snapshot.body_colliders.len(),
                    "peak_guide_displacement": peak_displacement, "peak_guide_upward": peak_upward,
                    "frames": 240, "samples": samples, "rendered": false});
                println!("{row}");
                results.push(row);
            }
        }
        assert_eq!(std::fs::read(payload_path)?, before);
    }
    assert!(!results.is_empty(), "no supplied cloth cases");
    std::fs::write(report, serde_json::to_vec_pretty(&results)?)?;
    Ok(())
}
