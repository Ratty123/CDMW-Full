use super::*;

fn rope_application() -> Result<LabApplication, Box<dyn std::error::Error>> {
    let mut application = triangle_application()?;
    let mut document = application.document.as_deref().ok_or("document")?.clone();
    let part = &mut document.lods[0].submeshes[0];
    part.positions.clear();
    part.indices.clear();
    for ring in 0..=8 {
        for side in 0..8 {
            let angle = side as f32 * std::f32::consts::TAU / 8.0;
            part.positions
                .push([ring as f32, 0.2 * angle.cos(), 0.2 * angle.sin()]);
        }
    }
    for ring in 0..8 {
        for side in 0..8 {
            let a = ring * 8 + side;
            let b = ring * 8 + (side + 1) % 8;
            part.indices.extend([a, b, b + 8, a, b + 8, a + 8]);
        }
    }
    part.normals = vec![[0., 0., 1.]; part.positions.len()];
    part.uvs = vec![[0., 0.]; part.positions.len()];
    part.source_vertex_indices = (0..part.positions.len() as i32).collect();
    let mut mesh = WorkingMesh::from_document(&document)?;
    mesh.set_selection(Selection {
        submeshes: HashSet::from([0]),
        ..Selection::default()
    })?;
    application.camera.frame_all(&mesh);
    application.mesh = Some(mesh);
    application.document = Some(Arc::new(document));
    application.projection = None;
    Ok(application)
}

fn ring_point(ui: &mut HeadlessUi, x: f32) -> Result<Vec2, Box<dyn std::error::Error>> {
    ui.frame(Vec::new());
    let rectangle = ui.application.viewport_rect.ok_or("viewport")?;
    assert!(ui.application.ensure_projection(rectangle));
    let projection = ui.application.projection.as_ref().ok_or("projection")?;
    let mesh = ui.application.mesh.as_ref().ok_or("mesh")?;
    mesh.vertices()
        .filter(|(_, vertex)| (vertex.position[0] - x).abs() < 1e-5)
        .filter_map(|(handle, _)| {
            let point = projection.vertices.get(&handle)?.screen;
            let weights =
                brush_vertex_weights(mesh, projection, point, 4.0, true, BrushFalloff::Constant)
                    .ok()?;
            weights.contains_key(&handle).then_some(point)
        })
        .next()
        .ok_or_else(|| "missing visible rope point".into())
}

fn vertices(application: &LabApplication) -> Vec<(VertexHandle, cdmw_mesh::Vertex)> {
    application
        .mesh
        .as_ref()
        .unwrap()
        .vertices()
        .map(|(h, v)| (h, v.clone()))
        .collect()
}

#[test]
fn integrated_bend_clicks_anchor_then_drags_one_sparse_shadow_transaction() -> TestResult {
    let root = tempdir()?;
    let mut ui =
        HeadlessUi::new_integrated_cdmw_for_controls(rope_application()?, egui::vec2(1280., 900.));
    ui.click("Bend")?;
    assert_eq!(ViewportTool::Bend, ui.application.viewport_tool);
    ui.click("Reset anchor")?; // Disabled reset must not create an anchor or history.
    assert!(ui.application.bend_anchor.is_none());
    let baseline = vertices(&ui.application);
    let point = ring_point(&mut ui, 1.)?;
    ui.click_at(egui::pos2(point.x, point.y));
    assert!(
        ui.application.bend_anchor.is_some(),
        "{}",
        ui.application.status
    );
    assert_eq!(0, ui.application.history.undo_len());
    assert_eq!(baseline, vertices(&ui.application));
    ui.application.cdmw_bridge = Some(CdmwBridge::for_test(
        root.path().to_path_buf(),
        "bend-ui",
        1,
        0,
    ));
    let tip = ring_point(&mut ui, 7.)?;
    ui.drag(&[tip, tip + Vec2::new(0., -50.)], PointerButton::Primary);
    assert_ne!(
        baseline,
        vertices(&ui.application),
        "{}",
        ui.application.status
    );
    assert_eq!(1, ui.application.history.undo_len());
    assert_eq!(1, ui.application.cdmw_transaction_attempts);
    assert!(
        ui.application
            .cdmw_pending_request
            .as_ref()
            .is_some_and(|request| request.label == "Bend")
    );
    assert!(
        ui.application
            .bend_anchor
            .as_ref()
            .unwrap()
            .matches(ui.application.mesh.as_ref().unwrap())
    );
    Ok(())
}

#[test]
fn bend_painted_controls_undo_redo_and_reset_anchor() -> TestResult {
    let mut ui = HeadlessUi::new(rope_application()?, egui::vec2(1280., 900.));
    ui.click("Bend")?;
    let baseline = vertices(&ui.application);
    let point = ring_point(&mut ui, 1.)?;
    ui.click_at(egui::pos2(point.x, point.y));
    let tip = ring_point(&mut ui, 7.)?;
    ui.drag(&[tip, tip + Vec2::new(0., -50.)], PointerButton::Primary);
    let bent = vertices(&ui.application);
    assert_ne!(baseline, bent, "{}", ui.application.status);
    ui.click("Undo")?;
    assert_eq!(baseline, vertices(&ui.application));
    ui.click("Redo")?;
    assert_eq!(bent, vertices(&ui.application));
    // The anchor can be reset after history navigation.
    let point = ring_point(&mut ui, 1.)?;
    ui.click_at(egui::pos2(point.x, point.y));
    ui.click("Reset anchor")?;
    assert!(ui.application.bend_anchor.is_none());
    Ok(())
}

#[test]
fn bend_escape_and_resize_restore_the_exact_drag_baseline_without_submission() -> TestResult {
    for resize in [false, true] {
        let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
            rope_application()?,
            egui::vec2(1280., 900.),
        );
        ui.click("Bend")?;
        let baseline = vertices(&ui.application);
        let point = ring_point(&mut ui, 1.)?;
        ui.click_at(egui::pos2(point.x, point.y));
        let tip = ring_point(&mut ui, 7.)?;
        ui.frame(vec![
            Event::PointerMoved(egui::pos2(tip.x, tip.y)),
            pointer_button(egui::pos2(tip.x, tip.y), PointerButton::Primary, true),
        ]);
        ui.frame(vec![Event::PointerMoved(egui::pos2(tip.x, tip.y - 50.))]);
        assert!(
            ui.application.edit_gesture.is_some(),
            "{}",
            ui.application.status
        );
        assert_ne!(baseline, vertices(&ui.application));
        if resize {
            ui.size.x += 200.;
            ui.frame(Vec::new());
        } else {
            ui.frame(vec![Event::Key {
                key: egui::Key::Escape,
                physical_key: None,
                pressed: true,
                repeat: false,
                modifiers: egui::Modifiers::NONE,
            }]);
        }
        assert!(ui.application.edit_gesture.is_none());
        assert_eq!(baseline, vertices(&ui.application));
        assert_eq!(0, ui.application.history.undo_len());
        assert_eq!(0, ui.application.cdmw_transaction_attempts);
    }
    Ok(())
}

#[test]
fn bend_requires_selection_and_clicking_without_drag_keeps_history_empty() -> TestResult {
    let mut ui =
        HeadlessUi::new_integrated_cdmw_for_controls(rope_application()?, egui::vec2(1280., 900.));
    ui.click("Bend")?;
    let root = ring_point(&mut ui, 1.)?;
    ui.click_at(egui::pos2(root.x, root.y));
    let tip = ring_point(&mut ui, 7.)?;
    ui.click_at(egui::pos2(tip.x, tip.y));
    assert_eq!(0, ui.application.history.undo_len());
    assert_eq!(0, ui.application.cdmw_transaction_attempts);
    ui.application
        .mesh
        .as_mut()
        .unwrap()
        .set_selection(Selection::default())?;
    ui.click_at(egui::pos2(root.x, root.y));
    assert!(ui.application.edit_gesture.is_none());
    assert!(ui.application.status.contains("Select the rope"));
    Ok(())
}
