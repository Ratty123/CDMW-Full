use super::*;

#[test]
fn island_controls_survive_host_reload_and_clip_restored_selection() -> TestResult {
    let root = tempdir()?;
    let mut ui = island_ui(egui::vec2(1280.0, 900.0))?;
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(
        root.path().to_path_buf(),
        "islands",
        1,
        0,
    ));
    ui.application.set_island_visibility(0, vec![1], false);
    let original = ui.application.document.clone().ok_or("document")?;
    ui.application.cdmw_state["selection"] =
        json!({"source_indices":[], "faces_by_submesh":{"0":[0,1]}});
    ui.application.install_cdmw_document(original.clone())?;
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    assert_eq!(mesh.viewport_hidden_faces().len(), 1);
    assert_eq!(
        mesh.selection.faces.len(),
        1,
        "host restored selection into hidden geometry"
    );
    ui.application.cdmw_state["replacement"]["comparison"] = json!("output");
    let mut output = original.clone();
    output.lods[0].submeshes[0].indices.truncate(3);
    ui.application.install_cdmw_document(output)?;
    assert!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .viewport_hidden_faces()
            .is_empty()
    );
    assert_eq!(
        ui.application.cdmw_hidden_islands.len(),
        1,
        "comparison discarded edit visibility"
    );
    ui.application.cdmw_state["replacement"]["comparison"] = json!("edit");
    ui.application.install_cdmw_document(original)?;
    assert_eq!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .viewport_hidden_faces()
            .len(),
        1
    );
    Ok(())
}

fn island_ui(size: egui::Vec2) -> Result<HeadlessUi, Box<dyn std::error::Error>> {
    let mut application = triangle_application()?;
    let document = application.document.as_mut().ok_or("document")?;
    let part = &mut document.lods[0].submeshes[0];
    part.name = "Skull and horns".into();
    let positions = part
        .positions
        .iter()
        .map(|p| [p[0] + 3.0, p[1], p[2]])
        .collect::<Vec<_>>();
    part.positions.extend(positions);
    part.normals.extend(part.normals.clone());
    part.uvs.extend(part.uvs.clone());
    part.source_vertex_indices.extend([3, 4, 5]);
    part.indices.extend([3, 4, 5]);
    application.mesh = Some(WorkingMesh::from_document(document)?);
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(application, size);
    ui.application.cdmw_state["replacement"] =
        json!({"available":true,"comparison":"edit","parts":[]});
    ui.application.cdmw_state["mesh_islands"] = json!({"parts":[{"index":0,"part_id":"owned:0","name":"Skull and horns",
        "available":true,"reason":"","islands":[{"faces":[0],"included":true},{"faces":[1],"included":true}]}]});
    ui.settle_layout();
    Ok(ui)
}

#[test]
fn island_controls_select_isolate_and_restore_without_export_edits() -> TestResult {
    let mut ui = island_ui(egui::vec2(1440.0, 1080.0))?;
    let before = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();
    ui.click("Island 1 · 1 faces")?;
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    assert!(mesh.selection.submeshes.is_empty());
    assert_eq!(mesh.selection.faces.len(), 1);
    assert_eq!(mesh.selected_vertex_scope().len(), 3);
    ui.click("Isolate")?;
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    let visible = ui
        .application
        .cdmw_visible_submeshes()
        .ok_or("visibility")?;
    let handles = mesh.element_handles_for_submeshes(&visible);
    assert_eq!(handles.faces.len(), 1);
    assert_eq!(handles.vertices.len(), 3);
    let filtered = mesh.draw_snapshot_for_submeshes(&visible);
    assert_eq!(filtered.indices.len(), 3);
    assert_eq!(
        mesh.draw_snapshot().indices.len(),
        6,
        "viewport mask changed authored geometry"
    );
    assert_eq!(mesh.structural_fingerprint(), before);
    // Both depth-aware and X-ray picking receive the same filtered projection.
    ui.application
        .ensure_projection(ui.application.viewport_rect.ok_or("viewport")?);
    assert_eq!(
        ui.application
            .projection
            .as_ref()
            .ok_or("projection")?
            .interaction
            .depth_triangles
            .len(),
        1
    );
    ui.click("Show all islands")?;
    assert!(
        ui.application
            .mesh
            .as_ref()
            .ok_or("mesh")?
            .viewport_hidden_faces()
            .is_empty()
    );
    assert_eq!(ui.application.cdmw_transaction_attempts, 0);
    Ok(())
}

#[test]
fn island_controls_dispatch_exact_mod_mask_and_preserve_deformation_alignment() -> TestResult {
    let mut ui = island_ui(egui::vec2(1280.0, 900.0))?;
    let row = ui.reveal("Island 1 · 1 faces")?;
    ui.last_actions.clear();
    ui.click_where("Mod", |rect| (rect.center().y - row.center().y).abs() < 2.0)?;
    let actions = std::mem::take(&mut ui.last_actions);
    assert!(actions.iter().any(|action| matches!(action,
        UiAction::CdmwCommand { command:"replacement_islands", arguments, .. }
        if arguments == &json!({"part_id":"owned:0","faces":[0],"included":false}))));
    ui.application.ensure_deformation_reference();
    ui.application.set_island_visibility(0, vec![0], false);
    let visible = ui.application.cdmw_visible_submeshes().ok_or("visible")?;
    let snapshot = ui
        .application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .draw_snapshot_for_submeshes(&visible);
    let reference = ui
        .application
        .deformation_reference
        .as_mut()
        .ok_or("reference")?;
    assert_eq!(
        reference
            .positions_for_snapshot(Some(&visible), &snapshot)
            .ok_or("positions")?,
        snapshot.positions
    );
    // Topology replacement cannot accidentally hide faces with reused ordinals.
    ui.application.document.as_mut().ok_or("document")?.lods[0].submeshes[0]
        .indices
        .swap(0, 1);
    ui.application.sync_island_visibility();
    assert!(ui.application.cdmw_hidden_islands.is_empty());
    Ok(())
}
