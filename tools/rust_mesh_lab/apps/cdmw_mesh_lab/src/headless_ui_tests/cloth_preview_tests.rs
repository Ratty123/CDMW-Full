//! Exercise cloth through the real controls, owned loader and draw-only scene.
use super::*;
use sha2::{Digest, Sha256};

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
            "constraints": [{"kind": "pair", "indices": [0, 1], "rest": distance}]},
        "parts": [{"index": 0, "records": records}]}))?;
    std::fs::write(root.path().join("jiggle-rig.json"), &payload)?;
    ui.application.cdmw_state["jiggle"] = json!({"available": false, "parts": [],
        "decoded": {"available": true, "cloth": {"available": true},
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
