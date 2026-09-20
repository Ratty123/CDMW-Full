//! Exercise cloth through the real controls, owned loader and draw-only scene.
use super::*;
use sha2::{Digest, Sha256};

mod strain;

fn fixture() -> Result<(tempfile::TempDir, HeadlessUi, Vec<u8>), Box<dyn std::error::Error>> {
    let root = tempdir()?;
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1440.0, 1800.0),
    );
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(
        root.path().to_path_buf(),
        "cloth",
        1,
        0,
    ));
    let identity = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ];
    let rest = ui
        .application
        .mesh
        .as_ref()
        .unwrap()
        .draw_snapshot()
        .positions;
    let frames = rest
        .iter()
        .map(|position| {
            let mut frame = identity;
            frame[0][3] = 1.0; // Packed animation-frame metadata, not an affine lane.
            frame[3][..3].copy_from_slice(&position.map(f64::from));
            frame[3][0] -= 0.2; // Render vertices sit away from their guide pivots.
            frame
        })
        .collect::<Vec<_>>();
    let records = (0_u32..3)
        .map(|index| {
            let mut record = [0_u8; 40];
            record[28] = 255;
            record[32] = 255;
            record[38] = 255;
            record[24..28].copy_from_slice(&(index << 10).to_le_bytes());
            record
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>()
        })
        .collect::<Vec<_>>();
    let distance = (Vec3::from(rest[0]) - Vec3::from(rest[1])).length();
    let payload = serde_json::to_vec(&json!({"version": 1,
        "rig": {"bone_palette": [0], "parents": [-1], "inverse_bind_matrices": [identity],
            "neutral_global_matrices": [identity], "neutral_local_matrices": [identity]},
        "cloth": {"version": 1, "source_positions": rest, "animation_frames": frames,
            "fixed": [true, false, false], "alpha_blends": [1.0, 0.0, 1.0],
            "orientation_neighbors": [[1, 2], [2, 0], [0, 1]],
            "constraints": [{"kind": "pair", "indices": [0, 1], "rest": distance}]},
        "parts": [{"index": 0, "records": records}]}))?;
    std::fs::write(root.path().join("jiggle-rig.json"), &payload)?;
    ui.application.cdmw_state["jiggle"] = json!({"available": false, "parts": [],
        "decoded": {"available": true, "cloth": {"available": true, "rotation_available": true},
            "file": {"path": "jiggle-rig.json", "data_type": "jiggle_rig_json", "count": 1,
                "byte_length": payload.len(), "sha256": format!("{:X}", Sha256::digest(&payload)),
                "content_type": "application/json"}},
        "overlay_parts": [{"index": 0, "preview": {"available": true, "vertex_count": 3,
            "original_cloth_bytes": [0, 0, 0], "current_cloth_bytes": [63, 32, 0],
            "original_bytes": [255, 255, 255], "current_bytes": [255, 255, 255]}}]});
    ui.application.cdmw_state["cloth"] = json!({"available": true, "lod_count": 4,
        "parts": [{"index": 0, "id": "cloth:0", "included": true, "min_y": 0.0,
            "max_y": 1.0, "rule": null}]});
    ui.click_tool_button("Cloth")?;
    Ok((root, ui, payload))
}

fn wait(ui: &mut HeadlessUi) -> TestResult {
    let deadline = Instant::now() + std::time::Duration::from_secs(5);
    while ui.application.cdmw_jiggle.preview.pending.is_some() {
        assert!(Instant::now() < deadline, "cloth preview loader timed out");
        ui.application.poll_loader();
        std::thread::sleep(std::time::Duration::from_millis(1));
    }
    ui.frame(Vec::new());
    Ok(())
}

fn advance(ui: &mut HeadlessUi) -> TestResult {
    for _ in 0..20 {
        ui.application.advance_jiggle_preview(1.0 / 60.0)?;
    }
    Ok(())
}

#[test]
fn comparisons_pause_settings_and_reset_preserve_authored_mesh_without_jiggle_flags() -> TestResult
{
    let (_root, mut ui, _) = fixture()?;
    let authored = ui.application.mesh.as_ref().unwrap().draw_snapshot();
    ui.click("Play preview")?;
    assert!(ui.application.cdmw_jiggle.preview.pending.is_some());
    wait(&mut ui)?;
    assert!(ui.application.cdmw_jiggle.preview.playing);
    advance(&mut ui)?;
    let current = ui
        .application
        .cdmw_jiggle
        .preview
        .scene
        .as_ref()
        .unwrap()
        .frame
        .clone();
    assert_ne!(current.positions, authored.positions);
    ui.click("Pause preview")?;
    advance(&mut ui)?;
    assert_eq!(
        ui.application
            .cdmw_jiggle
            .preview
            .scene
            .as_ref()
            .unwrap()
            .frame,
        current
    );
    ui.click("Resume preview")?;
    ui.click("Original flags")?;
    assert_eq!(
        ui.application
            .cdmw_jiggle
            .preview
            .scene
            .as_ref()
            .unwrap()
            .frame,
        current
    );
    wait(&mut ui)?;
    advance(&mut ui)?;
    let original = ui
        .application
        .cdmw_jiggle
        .preview
        .scene
        .as_ref()
        .unwrap()
        .frame
        .clone();
    assert_ne!(original.positions[1], current.positions[1]);
    assert_eq!(original.positions[2], current.positions[2]);
    assert!(original.normals.iter().flatten().all(|v| v.is_finite()));
    ui.click("All disabled")?;
    wait(&mut ui)?;
    advance(&mut ui)?;
    let disabled = ui
        .application
        .cdmw_jiggle
        .preview
        .scene
        .as_ref()
        .unwrap()
        .frame
        .clone();
    for i in 0..3 {
        let actual = Vec3::from(disabled.positions[i]) - Vec3::from(authored.positions[i]);
        let translation = Vec3::from(disabled.positions[0]) - Vec3::from(authored.positions[0]);
        assert!((actual - translation).length() < 1e-6);
    }
    assert_ne!(disabled.positions[2], original.positions[2]);

    ui.click("Original flags")?;
    wait(&mut ui)?;
    ui.click("Cloth preview settings")?;
    ui.click("Use authored vertex alpha")?;
    ui.click("Reset preview")?;
    ui.click("Play preview")?;
    wait(&mut ui)?;
    advance(&mut ui)?;
    let alpha = &ui
        .application
        .cdmw_jiggle
        .preview
        .scene
        .as_ref()
        .unwrap()
        .frame;
    assert_eq!(alpha.positions[2], disabled.positions[2]);
    assert_eq!(alpha.positions[1], original.positions[1]);
    ui.click("Preview floor")?;
    assert!(ui.label_rect("Floor height (Y)").is_some());
    ui.click("Reset cloth preview settings")?;
    assert!(ui.label_rect("Floor height (Y)").is_none());
    ui.click("Reset preview")?;
    assert!(ui.application.cdmw_jiggle.preview.scene.is_none());
    assert!(!ui.application.cdmw_jiggle.preview.playing);
    assert_eq!(
        ui.application.mesh.as_ref().unwrap().draw_snapshot(),
        authored
    );
    Ok(())
}

#[test]
fn failed_preparation_retains_frame_and_cancel_or_geometry_change_rejects_results() -> TestResult {
    let (root, mut ui, payload) = fixture()?;
    ui.click("Play preview")?;
    wait(&mut ui)?;
    advance(&mut ui)?;
    let previous = ui
        .application
        .cdmw_jiggle
        .preview
        .scene
        .as_ref()
        .unwrap()
        .frame
        .clone();
    let path = root.path().join("jiggle-rig.json");
    std::fs::write(&path, vec![b' '; payload.len()])?;
    ui.click("Original flags")?;
    wait(&mut ui)?;
    assert!(!ui.application.cdmw_jiggle.preview.playing);
    assert_eq!(
        ui.application
            .cdmw_jiggle
            .preview
            .scene
            .as_ref()
            .unwrap()
            .frame,
        previous
    );
    std::fs::write(&path, payload)?;
    ui.click("Play preview")?;
    wait(&mut ui)?;
    assert!(ui.application.cdmw_jiggle.preview.playing);
    ui.click("All disabled")?;
    let cancelled = ui.application.cdmw_jiggle.preview.pending.unwrap();
    ui.click("Reset preview")?;
    ui.application
        .accept_prepared_jiggle(cancelled, Err("stale failure".into()));
    ui.application.poll_loader();
    assert!(ui.application.cdmw_jiggle.preview.pending.is_none());
    assert!(ui.application.cdmw_jiggle.preview.scene.is_none());
    ui.click("Play preview")?;
    ui.application.mesh.as_mut().unwrap().geometry_revision += 1;
    wait(&mut ui)?;
    assert!(!ui.application.cdmw_jiggle.preview.playing);
    assert!(ui.application.cdmw_jiggle.preview.scene.is_none());
    Ok(())
}

#[test]
fn missing_decoded_guides_disables_playback_but_keeps_saved_cloth_controls() -> TestResult {
    let (_root, mut ui, _) = fixture()?;
    ui.application.cdmw_state["jiggle"]["decoded"]["cloth"] = json!({
        "available": false, "reason": "No supported guide mesh in this PAC."});
    ui.frame(Vec::new());
    assert!(
        ui.label_rect("No supported guide mesh in this PAC.")
            .is_some()
    );
    assert!(ui.label_rect("Disable cloth").is_some());
    ui.click("Play preview")?;
    assert!(ui.application.cdmw_jiggle.preview.pending.is_none());
    assert!(ui.application.cdmw_jiggle.preview.scene.is_none());
    Ok(())
}

#[test]
fn rotation_control_changes_surface_around_guides_and_disables_when_unsupported() -> TestResult {
    let (root, mut ui, payload) = fixture()?;
    let authored = ui.application.mesh.as_ref().unwrap().draw_snapshot();
    ui.click("Cloth preview settings")?;
    ui.click("Play preview")?;
    wait(&mut ui)?;
    advance(&mut ui)?;
    let translated = ui
        .application
        .cdmw_jiggle
        .preview
        .scene
        .as_ref()
        .unwrap()
        .frame
        .clone();
    ui.click("Reset preview")?;
    ui.click("Guide rotation correction")?;
    ui.click("Play preview")?;
    wait(&mut ui)?;
    advance(&mut ui)?;
    let rotated = &ui
        .application
        .cdmw_jiggle
        .preview
        .scene
        .as_ref()
        .unwrap()
        .frame;
    assert_ne!(rotated.positions[1], translated.positions[1]);
    assert_eq!(rotated.positions[0], translated.positions[0]);
    assert!(rotated.normals.iter().flatten().all(|v| v.is_finite()));
    let rotated = rotated.clone();
    ui.click("Reset preview")?;
    ui.click("Single-edge rotation")?;
    ui.click("Play preview")?;
    wait(&mut ui)?;
    advance(&mut ui)?;
    let single = &ui
        .application
        .cdmw_jiggle
        .preview
        .scene
        .as_ref()
        .unwrap()
        .frame;
    assert_ne!(single.positions[1], translated.positions[1]);
    assert_ne!(single.positions, rotated.positions);
    assert_eq!(single.positions[0], translated.positions[0]);
    assert!(single.normals.iter().flatten().all(|v| v.is_finite()));
    assert_eq!(std::fs::read(root.path().join("jiggle-rig.json"))?, payload);
    ui.click("Cloth preview settings")?;
    ui.application.cdmw_state["jiggle"]["decoded"]["cloth"]["rotation_available"] = json!(false);
    ui.frame(Vec::new());
    ui.click("Reset preview")?;
    ui.click("Play preview")?;
    wait(&mut ui)?;
    advance(&mut ui)?;
    assert_eq!(
        ui.application
            .cdmw_jiggle
            .preview
            .scene
            .as_ref()
            .unwrap()
            .frame,
        translated
    );
    assert_eq!(
        ui.application.mesh.as_ref().unwrap().draw_snapshot(),
        authored
    );
    Ok(())
}

#[test]
fn body_collision_control_uses_owned_volumes_and_preserves_authored_mesh() -> TestResult {
    check_body_collision_source("pab_primary")
}

#[test]
fn model_body_collision_control_uses_owned_volumes_and_preserves_authored_mesh() -> TestResult {
    check_body_collision_source("pac_model")
}

#[test]
fn appearance_body_collision_control_uses_owned_volumes_and_preserves_authored_mesh() -> TestResult {
    check_body_collision_source("appearance")
}

#[test]
fn collision_input_controls_choose_roles_clear_and_observe_model_precedence() -> TestResult {
    let (_root, mut ui, _) = fixture()?;
    let authored = ui.application.mesh.as_ref().unwrap().draw_snapshot();
    ui.click("Collision sources")?;
    for role in ["body", "head"] {
        assert!(ui.actions_from_click(&format!("Choose {role} PABV…"))?.iter().any(
            |action| matches!(action, UiAction::ChooseClothCollisionInput { role: selected } if *selected == role)
        ));
    }
    ui.application.cdmw_state["jiggle"]["collision_inputs"] = json!({"body": "chosen.pabv"});
    ui.application.cdmw_state["jiggle"]["decoded"]["cloth"]["body_collider_source"] = json!("pac_model");
    ui.frame(Vec::new());
    assert!(ui.label_rect("Body volumes: chosen.pabv").is_some());
    assert!(ui.actions_from_click("Choose body PABV…")?.is_empty());
    let actions = ui.actions_from_click("Clear collision inputs")?;
    assert!(actions.iter().any(|action| matches!(action,
        UiAction::CdmwCommand { command: "cloth_collision_input", arguments, .. } if arguments == &json!({"clear": true})
    )));
    assert!(ui.application.cdmw_pending_request.is_some());
    assert_eq!(ui.application.mesh.as_ref().unwrap().draw_snapshot(), authored);
    Ok(())
}

fn check_body_collision_source(source: &str) -> TestResult {
    let (root, mut ui, payload) = fixture()?;
    let authored = ui.application.mesh.as_ref().unwrap().draw_snapshot();
    let mut payload: Value = serde_json::from_slice(&payload)?;
    let guide = &payload["cloth"]["animation_frames"][1][3];
    let x = guide[0].as_f64().unwrap() - 0.25;
    let z = guide[2].as_f64().unwrap();
    payload["cloth"]["body_colliders"] = json!([{
        "kind": 5, "center1": [x, -10.0, z], "center2": [x, 10.0, z], "radius": 0.5,
        "bone_index": 0, "source_ordinal": 0
    }]);
    let payload = serde_json::to_vec(&payload)?;
    std::fs::write(root.path().join("jiggle-rig.json"), &payload)?;
    let state = &mut ui.application.cdmw_state["jiggle"]["decoded"];
    state["file"]["byte_length"] = json!(payload.len());
    state["file"]["sha256"] = json!(format!("{:X}", Sha256::digest(&payload)));
    state["cloth"]["body_collider_count"] = json!(1);
    state["cloth"]["body_collider_source"] = json!(source);
    ui.click("Cloth preview settings")?;
    let source_label = if source == "pac_model" {
        "Uses this model's authored collision volumes."
    } else if source == "appearance" {
        "Uses the explicitly selected body/head collision inputs."
    } else {
        "Uses the matched rig's default volumes."
    };
    assert!(ui.label_rect(source_label).is_some());
    ui.click("Play preview")?;
    wait(&mut ui)?;
    advance(&mut ui)?;
    let without = ui
        .application
        .cdmw_jiggle
        .preview
        .scene
        .as_ref()
        .unwrap()
        .frame
        .clone();
    ui.click("Reset preview")?;
    ui.click("Body collisions")?;
    assert!(ui.label_rect("Collision margin").is_some());
    ui.click("Play preview")?;
    wait(&mut ui)?;
    advance(&mut ui)?;
    let with = ui
        .application
        .cdmw_jiggle
        .preview
        .scene
        .as_ref()
        .unwrap()
        .frame
        .clone();
    assert_ne!(with.positions[1], without.positions[1]);
    assert_eq!(with.positions[0], without.positions[0]);
    assert!(with.normals.iter().flatten().all(|v| v.is_finite()));
    assert_eq!(
        ui.application.mesh.as_ref().unwrap().draw_snapshot(),
        authored
    );
    assert_eq!(std::fs::read(root.path().join("jiggle-rig.json"))?, payload);
    ui.click("Reset preview")?;
    // A populated but unrecognized source must not enable contacts.
    ui.application.cdmw_state["jiggle"]["decoded"]["cloth"]["body_collider_source"] = json!("unknown");
    ui.frame(Vec::new());
    ui.click("Body collisions")?;
    assert!(ui.label_rect("Collision margin").is_none());
    ui.click("Play preview")?;
    wait(&mut ui)?;
    advance(&mut ui)?;
    assert_eq!(
        ui.application
            .cdmw_jiggle
            .preview
            .scene
            .as_ref()
            .unwrap()
            .frame,
        without
    );
    ui.click("Reset preview")?;
    ui.application.cdmw_state["jiggle"]["decoded"]["cloth"]["body_collider_source"] = json!(source);
    ui.application.cdmw_state["jiggle"]["decoded"]["cloth"]["body_collider_count"] = json!(0);
    ui.frame(Vec::new());
    ui.click("Body collisions")?;
    assert!(ui.label_rect("Collision margin").is_none());
    Ok(())
}

#[test]
#[ignore = "requires caller-owned PAC/PAB authoring packages and evidence output paths"]
fn supplied_motion_packages_preserve_mesh_and_compare_decoded_playback() -> TestResult {
    let cases_path = PathBuf::from(std::env::var("CDMW_MOTION_PROBE_CASES")?);
    let report_path = PathBuf::from(std::env::var("CDMW_MOTION_PROBE_REPORT")?);
    let cases: Vec<Value> = serde_json::from_slice(&std::fs::read(&cases_path)?)?;
    assert!(!cases.is_empty() && cases.len() <= 16);
    let mut reports = Vec::new();
    for case in cases {
        let manifest_path = PathBuf::from(case["manifest"].as_str().ok_or("manifest path")?);
        let manifest_before = std::fs::read(&manifest_path)?;
        let package = crate::cdmw_session::LoadedCdmwSessionPackage::load(&manifest_path)?;
        let state = package.manifest().state.clone();
        let cloth = state["cloth"]["available"].as_bool() == Some(true);
        let jiggle = state["jiggle"]["available"].as_bool() == Some(true);
        let mut application = LabApplication::new(None, None);
        application.mesh = Some(WorkingMesh::from_document(package.document())?);
        application.document = Some(package.document().clone());
        let mut ui =
            HeadlessUi::new_integrated_cdmw_for_controls(application, egui::vec2(1440.0, 1800.0));
        ui.application.cdmw_bridge = Some(CdmwBridge::for_test(
            package.root().to_path_buf(),
            "motion-probe",
            1,
            0,
        ));
        ui.application.cdmw_state = state;
        let authored = ui.application.mesh.as_ref().unwrap().draw_snapshot();
        let inactive = ui
            .application
            .mesh
            .as_ref()
            .unwrap()
            .vertices()
            .enumerate()
            .filter_map(|(i, (_, vertex))| {
                let cdmw_mesh::Provenance::Source { submesh, element } = vertex.provenance else {
                    return None;
                };
                let rows = ui.application.cdmw_state["jiggle"]["overlay_parts"].as_array()?;
                let data = &rows
                    .iter()
                    .find(|row| row["index"].as_u64() == Some(u64::from(submesh)))?["preview"];
                let key = if cloth {
                    "current_cloth_bytes"
                } else {
                    "current_bytes"
                };
                let byte = data[key][element as usize].as_u64()?;
                let mask = if cloth { 63 } else { 15 };
                (byte & mask == mask).then_some(i)
            })
            .collect::<Vec<_>>();
        let mut row = json!({"name": case["name"], "manifest": manifest_path,
            "vertices": authored.positions.len(), "cloth": cloth, "jiggle": jiggle,
            "source_sha256": case["sha256"], "rendered": false});
        ui.click_tool_button(if cloth { "Cloth" } else { "Jiggle" })?;
        if case["rotate_guides"].as_bool() == Some(true) {
            assert!(cloth);
            assert_eq!(
                ui.application.cdmw_state["jiggle"]["decoded"]["cloth"]["rotation_available"],
                true
            );
            ui.click("Cloth preview settings")?;
            ui.click("Guide rotation correction")?;
            row["guide_rotation"] = json!(true);
        }
        if !cloth && !jiggle {
            assert!(ui.label_rect("Play preview").is_none());
            row["no_vertex_contribution"] = json!(true);
        } else {
            if !cloth {
                ui.click("Selected parts")?;
            }
            let source = ui
                .application
                .cdmw_bridge
                .as_ref()
                .unwrap()
                .jiggle_source(&ui.application.cdmw_state)?;
            let payload_before = source.read()?;
            let mut motion_reports = Vec::new();
            for motion in ["Up / down", "Turning"] {
                ui.click(motion)?;
                let mut frames = Vec::new();
                let mut step_millis = Vec::new();
                for comparison in ["Current flags", "All disabled"] {
                    ui.click(comparison)?;
                    ui.click("Play preview")?;
                    wait(&mut ui)?;
                    assert!(
                        ui.application.cdmw_jiggle.preview.playing,
                        "{} failed to start {} / {}",
                        case["name"], motion, comparison
                    );
                    let started = Instant::now();
                    for _ in 0..120 {
                        ui.application.advance_jiggle_preview(1.0 / 60.0)?;
                    }
                    step_millis.push(started.elapsed().as_secs_f64() * 1000.0 / 120.0);
                    let frame = ui
                        .application
                        .cdmw_jiggle
                        .preview
                        .scene
                        .as_ref()
                        .unwrap()
                        .frame
                        .clone();
                    assert!(
                        frame
                            .positions
                            .iter()
                            .flatten()
                            .chain(frame.normals.iter().flatten())
                            .all(|v| v.is_finite())
                    );
                    frames.push(frame);
                    ui.click("Reset preview")?;
                }
                let delta = frames[0]
                    .positions
                    .iter()
                    .zip(&frames[1].positions)
                    .map(|(a, b)| (Vec3::from(*a) - Vec3::from(*b)).length())
                    .collect::<Vec<_>>();
                let max_delta = delta.iter().copied().fold(0.0_f32, f32::max);
                let inactive_error = inactive.iter().map(|i| delta[*i]).fold(0.0_f32, f32::max);
                assert!(
                    inactive_error < 1e-5,
                    "zero-contribution vertices deformed: {inactive_error}"
                );
                let rigid_error = frames[1]
                    .positions
                    .iter()
                    .zip(&authored.positions)
                    .map(|(p, rest)| {
                        ((Vec3::from(*p) - Vec3::from(frames[1].positions[0])).length()
                            - (Vec3::from(*rest) - Vec3::from(authored.positions[0])).length())
                        .abs()
                    })
                    .fold(0.0_f32, f32::max);
                assert!(
                    rigid_error < 1e-5,
                    "all-disabled comparison distorted the mesh: {rigid_error}"
                );
                if let Some(limit) = case["max_displacement"].as_f64() {
                    assert!(
                        f64::from(max_delta) <= limit,
                        "{} exceeded its supplied displacement limit: {max_delta}",
                        case["name"]
                    );
                }
                assert!(
                    max_delta > 1e-6,
                    "{} had no simulated deformation in {}",
                    case["name"],
                    motion
                );
                assert_eq!(
                    ui.application.mesh.as_ref().unwrap().draw_snapshot(),
                    authored
                );
                motion_reports.push(json!({"motion": motion, "frames": 120,
                    "maximum_simulated_displacement": max_delta,
                    "zero_contribution_error": inactive_error, "all_disabled_rigid_error": rigid_error,
                    "deformed_vertices": delta.iter().filter(|d| **d > 1e-6).count(),
                    "mean_cpu_step_ms_current_disabled": step_millis}));
            }
            assert_eq!(source.read()?, payload_before);
            row["motion"] = json!(motion_reports);
            row["rig_payload_unchanged"] = json!(true);
        }
        assert_eq!(
            ui.application.mesh.as_ref().unwrap().draw_snapshot(),
            authored
        );
        assert_eq!(std::fs::read(&manifest_path)?, manifest_before);
        row["authored_mesh_unchanged"] = json!(true);
        println!("{row}");
        reports.push(row);
        std::fs::write(&report_path, serde_json::to_vec_pretty(&reports)?)?;
    }
    Ok(())
}
