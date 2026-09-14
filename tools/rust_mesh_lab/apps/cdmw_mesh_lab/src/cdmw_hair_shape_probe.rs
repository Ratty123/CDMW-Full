//! Opt-in rendered and CPU drag evidence using retained production materials.
use super::*;

#[test]
#[ignore = "requires retained loader materials and a DX12 GPU; writes temporary evidence"]
fn hair_draw_shapes_render_and_drag_benchmark() {
    let input: Value = serde_json::from_slice(&std::fs::read(std::env::var("CDMW_HAIR_PROBE_INPUT").unwrap()).unwrap()).unwrap();
    let root = PathBuf::from(std::env::var("CDMW_HAIR_PROBE_OUTPUT").unwrap());
    std::fs::create_dir_all(&root).unwrap();
    let state: HairState = serde_json::from_value(input["hair"].clone()).unwrap();
    let document: MeshDocument = serde_json::from_value(input["document"].clone()).unwrap();
    let prepared = prepare(state, document, "Empty".into(), Preparation::Empty, &AtomicBool::new(false)).unwrap();
    let mut app = LabApplication::new(None, None);
    app.document = Some(prepared.document);
    app.cdmw_state = input["host"].clone();
    app.hydrate_hair(Some(prepared.state));
    app.hair.pending_preset = false;
    let rect = egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(1280.0, 900.0));
    app.viewport_rect = Some(rect);
    let mut results = vec![];
    for shape in [DrawShape::Freehand, DrawShape::Straight, DrawShape::Arc, DrawShape::Circle] {
        app.run_hair_action(HairAction::Empty);
        await_hair(&mut app);
        app.camera.set_standard_view(crate::camera::StandardView::Front);
        let scalp = &app.hair.state.as_ref().unwrap().scalp;
        app.camera.frame_positions_in_viewport(scalp.positions.iter().copied().map(Vec3::from), rect);
        let crown = scalp.triangles.iter().map(|f| f.iter().map(|i| Vec3::from(scalp.positions[*i as usize])).sum::<Vec3>() / 3.0)
            .max_by(|a, b| a.y.total_cmp(&b.y)).unwrap();
        let start = app.camera.project(crown, rect).unwrap().screen + Vec2::new(60.0, 65.0);
        app.hair.tool = Some(HairTool::Guide);
        app.hair.draw_shape = shape;
        app.hair.draw_follow_scalp = shape == DrawShape::Freehand;
        app.dispatch_hair_pointer(ViewportPointerEvent::PrimaryPressed(start), rect, false, false, false);
        let mut timings = vec![];
        let mut end = start;
        for i in 1..=120 {
            let t = i as f32 / 120.0;
            end = start + if shape == DrawShape::Freehand { Vec2::new(60.0 * (t * 4.0).sin(), 420.0 * t) }
                else { Vec2::new(100.0, 220.0) * t };
            let tick = Instant::now();
            app.dispatch_hair_pointer(ViewportPointerEvent::PrimaryMoved(end), rect, false, false, false);
            app.render_hair();
            timings.push(tick.elapsed().as_secs_f64() * 1000.0);
        }
        let stroke = app.hair.stroke.as_ref().unwrap();
        assert!(!stroke.guides.is_empty(), "{shape:?}: {}", app.hair.feedback);
        let scene = app.hair.scene.as_ref().unwrap();
        let tick = Instant::now();
        for _ in 0..10 { std::hint::black_box(hair::generate(stroke, &AtomicBool::new(false)).unwrap()); }
        let rebuilt = tick.elapsed().as_secs_f64() * 100.0;
        let tick = Instant::now();
        for _ in 0..10 { std::hint::black_box(hair::generate_cached(stroke, &AtomicBool::new(false),
            &scene.scalp_picking, &scene.scalp_indices, Some(&app.hair.drawing)).unwrap()); }
        let cached = tick.elapsed().as_secs_f64() * 100.0;
        app.dispatch_hair_pointer(ViewportPointerEvent::PrimaryReleased(end), rect, false, false, false);
        await_hair(&mut app);
        let frame = app.hair.scene.as_ref().unwrap().frame.positions.clone();
        let name = format!("{shape:?}").to_lowercase();
        capture_hair_workflow_step(&app, &input, &root, &name);
        capture_hair_workflow_view(&app, &input, &root, &format!("{name}-side"), 270.0);
        let guide = &app.hair.state.as_ref().unwrap().guides[0];
        let max_bend = guide.points.windows(3).map(|p| {
            let a = (Vec3::from(p[1]) - Vec3::from(p[0])).normalize();
            let b = (Vec3::from(p[2]) - Vec3::from(p[1])).normalize();
            a.dot(b).clamp(-1.0, 1.0).acos().to_degrees()
        }).fold(0.0_f32, f32::max);
        // Sharp facial contours can turn a fitted guide beyond a right angle.
        // Reject reversals and also verify the monotone screen path that normal
        // contact corrections previously folded back on itself at face seams.
        assert!(max_bend < 120.0, "{shape:?}: collision reversed a guide by {max_bend} degrees");
        if shape != DrawShape::Circle {
            for pair in guide.points.windows(2) {
                let a = app.camera.project(Vec3::from(pair[0]), rect).unwrap().screen;
                let b = app.camera.project(Vec3::from(pair[1]), rect).unwrap().screen;
                assert!(b.y >= a.y - 0.25, "{shape:?}: collision reversed the drawn silhouette");
            }
        }
        std::fs::write(root.join(format!("{name}-state.json")), serde_json::to_vec(app.hair.state.as_ref().unwrap()).unwrap()).unwrap();
        std::fs::write(root.join(format!("{name}-candidate.json")), serde_json::to_vec(&json!({
            "hair":app.hair.state.as_ref().unwrap(),
            "submeshes":app.hair.preview.as_ref().unwrap().lods[0].submeshes})).unwrap()).unwrap();
        timings.sort_by(f64::total_cmp);
        let mut move_timings = vec![];
        let (point, _) = visible_lock(&app, rect);
        app.hair.tool = Some(HairTool::Move);
        app.dispatch_hair_pointer(ViewportPointerEvent::PrimaryPressed(point), rect, false, false, false);
        let end = point + Vec2::new(40.0, -15.0);
        for i in 1..=60 {
            let tick = Instant::now();
            app.dispatch_hair_pointer(ViewportPointerEvent::PrimaryMoved(point.lerp(end, i as f32 / 60.0)), rect, false, false, false);
            app.render_hair();
            move_timings.push(tick.elapsed().as_secs_f64() * 1000.0);
        }
        assert_ne!(frame, app.hair.scene.as_ref().unwrap().frame.positions);
        app.dispatch_hair_pointer(ViewportPointerEvent::PrimaryReleased(end), rect, false, false, false);
        await_hair(&mut app);
        capture_hair_workflow_step(&app, &input, &root, &format!("{name}-moved"));
        move_timings.sort_by(f64::total_cmp);
        results.push(json!({"shape":name,"draw_cpu_p50_ms":timings[60],"draw_cpu_p95_ms":timings[114],
            "move_cpu_p95_ms":move_timings[57],"generation_rebuild_index_ms":rebuilt,"generation_cached_index_ms":cached,
            "max_bend_degrees":max_bend,"guides":app.hair.state.as_ref().unwrap().guides.len(),"vertices":app.hair.scene.as_ref().unwrap().reference_start}));
    }
    std::fs::write(root.join("drag-benchmark.json"), serde_json::to_vec_pretty(&results).unwrap()).unwrap();
    eprintln!("{}", serde_json::to_string(&results).unwrap());
}
