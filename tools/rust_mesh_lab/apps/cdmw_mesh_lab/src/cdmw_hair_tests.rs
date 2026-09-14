use super::*;
use cdmw_formats::{MeshFormat, MeshLod, SourceRange, Submesh};
use cdmw_render_wgpu::*;

fn fixture() -> (HairState, MeshDocument) {
    let mut positions = vec![];
    let mut triangles = vec![];
    for z in 0..17 {
        for x in 0..17 {
            positions.push([(x as f32 - 8.0) * 0.02, 0.2, (z as f32 - 8.0) * 0.02]);
        }
    }
    for z in 0..16 {
        for x in 0..16 {
            let i = z * 17 + x;
            triangles.extend([[i, i + 17, i + 1], [i + 1, i + 17, i + 18]]);
        }
    }
    let state = HairState {
        vertex_sources: Default::default(),
        prepared_parts: vec![],
        locks: vec![],
        next_lock_id: 1,
        style_name: "Test style".into(),
        startup_preset: "bob".into(),
        version: cdmw_mesh::hair::HAIR_VERSION,
        revision: 1,
        scalp: hair::Scalp {
            identity: "owned-head".into(),
            positions,
            triangles,
        },
        bound_reference: "owned-head".into(),
        references: vec![],
        reference_parts: vec![],
        converted: false,
        template: hair::Template {
            path: "hair.pac".into(),
            sha256: "a".repeat(64),
            target_stem: "hair-new".into(),
            character: "Damiane".into(),
            physics_profile: "Hair".into(),
        },
        groups: vec![HairGroup {
            id: 0,
            name: "Hair".into(),
            part: 0,
            mode: GroupMode::Generated,
            width: 0.012,
            cards_per_guide: 6,
            uv_rect: [0.0, 0.0, 1.0, 1.0],
        }],
        guides: vec![],
        bindings: vec![],
        collisions: vec![hair::Capsule {
            a: [0.0, -0.1, 0.0],
            b: [0.0, 0.1, 0.0],
            radius: 0.10,
            follows_head: true,
        }],
    };
    let part = Submesh {
        name: "Hair".into(),
        material: "Hair".into(),
        positions: vec![[0.0, 0.2, 0.0], [0.03, 0.2, 0.0], [0.0, 0.25, 0.0]],
        normals: vec![[0.0, 0.0, 1.0]; 3],
        uvs: vec![[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
        indices: vec![0, 1, 2],
        source_vertex_indices: vec![0, 1, 2],
        source_range: SourceRange {
            offset: 0,
            length: 0,
        },
        vertex_stride: 0,
        layout: "owned".into(),
    };
    let document = MeshDocument {
        format: MeshFormat::Pac,
        parser: "owned".into(),
        source_sha256: "a".repeat(64),
        lod_count_reported: 1,
        lods: vec![MeshLod {
            level: 0,
            submeshes: vec![part],
        }],
        warnings: vec![],
        structural_fingerprint: "owned".into(),
    };
    (state, document)
}

#[test]
fn hair_presets_create_distinct_geometry_and_keep_references_outside_output() {
    let (state, doc) = fixture();
    let mut shapes = vec![];
    for preset in [Preset::Cropped, Preset::Bob, Preset::Long, Preset::Ponytail] {
        let result = prepare(
            state.clone(),
            doc.clone(),
            "preset".into(),
            Preparation::Fill(0, preset, 0.3),
            &AtomicBool::new(false),
        )
        .unwrap();
        assert_eq!(result.state.guides.len(), 256);
        assert_eq!(result.document.lods[0].submeshes[0].positions.len(), 49_152);
        let scene = build_scene(&result.document, &result.state, true, None, 1);
        assert_eq!(
            scene.frame.positions.len(),
            49_152 + state.scalp.positions.len()
        );
        assert_eq!(result.document.lods[0].submeshes.len(), 1);
        assert!(!shapes.contains(&result.document.lods[0].submeshes[0].positions));
        shapes.push(result.document.lods[0].submeshes[0].positions.clone());
    }
}

#[test]
fn hair_existing_bind_groom_retains_uv_and_conversion_preserves_current_geometry() {
    let (mut state, doc) = fixture();
    state.groups[0].mode = GroupMode::Existing;
    hair::plant_guide(
        &mut state,
        Attachment {
            triangle: 200,
            barycentric: [1.0 / 3.0; 3],
        },
        0,
        Preset::Long,
        0.3,
        16,
    )
    .unwrap();
    let before = doc.clone();
    let mut bound = prepare(
        state,
        doc,
        "bind".into(),
        Preparation::Bind(0),
        &AtomicBool::new(false),
    )
    .unwrap();
    hair::groom(
        &mut bound.state,
        &[0],
        Groom::Comb,
        0.8,
        [0.1, 0.02, 0.03],
        false,
    )
    .unwrap();
    let mut groomed = prepare(
        bound.state,
        bound.document,
        "comb".into(),
        Preparation::Generate,
        &AtomicBool::new(false),
    )
    .unwrap();
    assert_ne!(
        groomed.document.lods[0].submeshes[0].positions,
        before.lods[0].submeshes[0].positions
    );
    assert_eq!(
        groomed.document.lods[0].submeshes[0].uvs,
        before.lods[0].submeshes[0].uvs
    );
    assert_eq!(
        groomed.document.lods[0].submeshes[0].indices,
        before.lods[0].submeshes[0].indices
    );
    groomed.state.converted = true;
    let converted = prepare(
        groomed.state,
        groomed.document.clone(),
        "convert".into(),
        Preparation::Metadata,
        &AtomicBool::new(false),
    )
    .unwrap();
    assert_eq!(converted.document, groomed.document);
}

#[test]
fn hair_cancelled_generation_and_rebind_leave_input_unchanged() {
    let (state, doc) = fixture();
    assert!(prepare(
        state.clone(),
        doc,
        "fill".into(),
        Preparation::Fill(0, Preset::Bob, 0.3),
        &AtomicBool::new(true)
    )
    .is_err());
    let mut state = state;
    hair::plant_guide(
        &mut state,
        Attachment {
            triangle: 200,
            barycentric: [1.0 / 3.0; 3],
        },
        0,
        Preset::Bob,
        0.3,
        16,
    )
    .unwrap();
    let before = state.clone();
    assert!(state
        .rebind_cancellable(state.scalp.clone(), &AtomicBool::new(true))
        .is_err());
    assert_eq!(state, before);
}

#[test]
fn hair_finish_waits_for_generation_and_cancel_restores_last_scene() {
    let (state, document) = fixture();
    let mut app = LabApplication::new(None, None);
    app.document = Some(document);
    app.hair.state = Some(state.clone());
    app.queue_hair(
        state.clone(),
        "Preset",
        Preparation::Fill(0, Preset::Bob, 0.3),
    );
    assert!(app.hair.preparing());
    app.submit_cdmw_finish();
    assert!(app.status.contains("hair generation"));
    app.hair
        .job
        .as_ref()
        .unwrap()
        .cancel
        .store(true, Ordering::Relaxed);
    app.hair.generation += 1;
    while app
        .hair
        .job
        .as_ref()
        .is_some_and(|job| !job.handle.is_finished())
    {
        std::thread::yield_now();
    }
    app.poll_hair();
    assert!(!app.hair.preparing());
    assert_eq!(app.hair.state, Some(state));
    assert!(app.hair.preview.is_none());
}

/// Real resident picker/loader handoff, production pointer dispatcher and draw
/// snapshots, followed by DX12 capture. Desktop presentation remains a separate gate.
#[test]
#[ignore = "requires authorized installed assets and a DX12 GPU"]
fn hair_production_render_and_benchmark() {
    let root =
        PathBuf::from(std::env::var("CDMW_HAIR_PROBE_OUTPUT").expect("temporary evidence output"));
    std::fs::create_dir_all(&root).unwrap();
    let input: Value = serde_json::from_slice(
        &std::fs::read(std::env::var("CDMW_HAIR_PROBE_INPUT").expect("real workflow input"))
            .unwrap(),
    )
    .unwrap();
    let source: HairState = serde_json::from_value(input["hair"].clone()).unwrap();
    let document: MeshDocument = serde_json::from_value(input["document"].clone()).unwrap();
    let package = PathBuf::from(input["session_root"].as_str().unwrap());
    let material: Value = serde_json::from_slice(
        &std::fs::read(
            package.join(
                input["host"]["archive_refit_materials"]["file"]["path"]
                    .as_str()
                    .unwrap(),
            ),
        )
        .unwrap(),
    )
    .unwrap();
    let rows = material["textures"].as_array().unwrap();
    let bytes: Vec<_> = rows
        .iter()
        .map(|r| std::fs::read(package.join(r["file"]["path"].as_str().unwrap())).unwrap())
        .collect();
    let ownership: Vec<Vec<Vec<u32>>> = rows
        .iter()
        .map(|r| serde_json::from_value(r["material_indices_by_lod"].clone()).unwrap())
        .collect();
    let textures: Vec<_> = rows
        .iter()
        .enumerate()
        .map(|(i, r)| HeadlessMaterialTexture {
            bytes: &bytes[i],
            role: serde_json::from_value(r["role"].clone()).unwrap(),
            material_indices_by_lod: &ownership[i],
        })
        .collect();
    let presentations: Vec<SessionMaterialPresentation> =
        serde_json::from_value(material["material_presentations"].clone()).unwrap();
    let factor_owners: Vec<_> = presentations
        .iter()
        .map(|p| cdmw_material_ownership(p, 1))
        .collect();
    let factors: Vec<_> = presentations
        .iter()
        .zip(&factor_owners)
        .map(|(p, o)| HeadlessMaterialFactors {
            factors: cdmw_material_preview_factors(p),
            material_indices_by_lod: o,
        })
        .collect();
    assert!(
        !textures.is_empty() && !factors.is_empty(),
        "materials must come from the real loader"
    );
    let generated = source.groups.iter().all(|g| g.mode == GroupMode::Generated);
    let span = (hair_bounds(&source).1 - hair_bounds(&source).0).max_element();
    let mut app = LabApplication::new(None, None);
    app.cdmw_state = input["host"].clone();
    let rect = egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(1920.0, 1080.0));
    app.viewport_rect = Some(rect);
    let mut preparation_ms = vec![];
    let reference_only =
        std::env::var("CDMW_HAIR_PROBE_OPERATION").ok().as_deref() == Some("mannequin");
    for (name, preset, length) in if reference_only {
        vec![("mannequin", Preset::Bob, 0.7)]
    } else if generated {
        vec![
            ("bob", Preset::Bob, 0.7),
            ("cropped", Preset::Cropped, 0.18),
            ("long", Preset::Long, 1.4),
            ("ponytail", Preset::Ponytail, 1.6),
        ]
    } else {
        vec![("existing", Preset::Bob, 0.7)]
    } {
        let started = Instant::now();
        let prepared = prepare(
            source.clone(),
            document.clone(),
            name.into(),
            if reference_only {
                Preparation::Empty
            } else if generated {
                Preparation::Fill(source.groups[0].id, preset, span * length)
            } else {
                Preparation::Analyze
            },
            &AtomicBool::new(false),
        )
        .unwrap();
        preparation_ms.push(started.elapsed().as_secs_f64() * 1000.0);
        app.document = Some(prepared.document);
        app.hydrate_hair(Some(prepared.state));
        app.hair.pending_preset = false;
        app.render_hair();
        let frame = &app.hair.scene.as_ref().unwrap().frame;
        for (view, yaw) in [("front", 180.0), ("side", 90.0), ("rear", 0.0)] {
            let textured = root.join(format!("{name}-{view}.bmp"));
            let base = root.join(format!("{name}-{view}-base.bmp"));
            let ids = root.join(format!("{name}-{view}-ids.bmp"));
            let report = pollster::block_on(run_headless_material_capture(
                frame,
                &textures,
                &factors,
                HeadlessMaterialCaptureOptions {
                    width: 1920,
                    height: 1080,
                    camera: Some(HeadlessMaterialCaptureCamera {
                        yaw_degrees: yaw,
                        pitch_degrees: 0.0,
                    }),
                    ..Default::default()
                },
                HeadlessMaterialCaptureOutput {
                    textured_bmp: &textured,
                    base_color_bmp: &base,
                    part_id_bmp: &ids,
                    normal_map: None,
                    material_response: None,
                    layer_mask: None,
                },
            ))
            .unwrap();
            assert!(
                (reference_only || report.dds_textures_uploaded > 0)
                    && report.textured.non_background_pixels > 1000
            );
            assert!(
                reference_only
                    || report.owner_coverage.iter().any(|o| o.material_index
                        < document.lods[0].submeshes.len() as u32
                        && o.pixel_count > 10),
                "hair must appear in the captured image"
            );
        }
    }
    if reference_only {
        return;
    }
    let topology_probe =
        std::env::var("CDMW_HAIR_PROBE_OPERATION").ok().as_deref() == Some("cut_delete");
    if topology_probe && !generated {
        let groups = app.hair.state.as_ref().unwrap().groups.clone();
        for group in groups {
            let ids: HashSet<_> = app
                .hair
                .state
                .as_ref()
                .unwrap()
                .locks
                .iter()
                .filter(|l| l.part == group.part && l.kind == LockKind::Unresolved)
                .map(|l| l.id as usize)
                .collect();
            if ids.is_empty() {
                continue;
            }
            app.hair.selected = ids;
            app.hair.tool = Some(HairTool::Root);
            let state = app.hair.state.as_ref().unwrap();
            let root = state
                .scalp
                .triangles
                .iter()
                .map(|f| {
                    f.iter()
                        .map(|i| Vec3::from(state.scalp.positions[*i as usize]))
                        .sum::<Vec3>()
                        / 3.0
                })
                .max_by(|a, b| a.y.total_cmp(&b.y))
                .unwrap();
            let point = app.camera.project(root, rect).unwrap().screen;
            app.dispatch_hair_pointer(
                ViewportPointerEvent::PrimaryPressed(point),
                rect,
                false,
                false,
                false,
            );
            app.dispatch_hair_pointer(
                ViewportPointerEvent::PrimaryReleased(point),
                rect,
                false,
                false,
                false,
            );
            await_hair(&mut app);
        }
        if let Err(reason) = app.hair_motion_reason() {
            assert!(reason.contains("too wide for stable motion"), "{reason}");
        }
    }
    // Benchmark Bob in the requested 256 x 16 / roughly 50k-vertex workload.
    if generated {
        let prepared = prepare(
            source.clone(),
            document.clone(),
            "Bob".into(),
            Preparation::Fill(source.groups[0].id, Preset::Bob, span * 0.7),
            &AtomicBool::new(false),
        )
        .unwrap();
        app.document = Some(prepared.document);
        app.hydrate_hair(Some(prepared.state));
        app.hair.pending_preset = false;
        app.render_hair();
    }
    if topology_probe {
        let (point, id) = visible_lock(&app, rect);
        app.hair.tool = Some(HairTool::Cut);
        app.dispatch_hair_pointer(
            ViewportPointerEvent::PrimaryPressed(point),
            rect,
            false,
            false,
            false,
        );
        app.dispatch_hair_pointer(
            ViewportPointerEvent::PrimaryReleased(point),
            rect,
            false,
            false,
            false,
        );
        await_hair(&mut app);
        let (_, other) = visible_lock(&app, rect);
        app.hair.selected = HashSet::from([other as usize]);
        app.run_hair_action(HairAction::DeleteGuides);
        await_hair(&mut app);
        assert!(!app
            .hair
            .state
            .as_ref()
            .unwrap()
            .locks
            .iter()
            .any(|l| l.id == other));
        if let Err(reason) = app.hair_motion_reason() {
            assert!(
                !generated && reason.contains("too wide for stable motion"),
                "Cut/deletion bindings failed for {id}: {reason}"
            );
        }
    }
    let bounds = app.hair.scene.as_ref().unwrap().frame.positions.clone();
    app.camera
        .frame_positions_in_viewport(bounds.iter().copied().map(Vec3::from), rect);
    let (point, id) = visible_lock(&app, rect);
    let mut picking = vec![];
    for _ in 0..120 {
        let stamp = Instant::now();
        assert!(app.lock_at(point, rect).is_some());
        picking.push(stamp.elapsed().as_secs_f64() * 1000.0);
    }
    app.hair.tool = Some(HairTool::Move);
    app.hair.selected = HashSet::from([id as usize]);
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryPressed(point),
        rect,
        false,
        false,
        false,
    );
    let mut grooming = vec![];
    for i in 1..=120 {
        let stamp = Instant::now();
        app.dispatch_hair_pointer(
            ViewportPointerEvent::PrimaryMoved(point + Vec2::new(i as f32 * 0.5, 0.0)),
            rect,
            false,
            false,
            false,
        );
        app.render_hair();
        grooming.push(stamp.elapsed().as_secs_f64() * 1000.0);
    }
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryReleased(point + Vec2::new(60.0, 0.0)),
        rect,
        false,
        false,
        false,
    );
    await_hair(&mut app);
    let authored = app.hair.state.clone().unwrap();
    let final_doc = app.hair.preview.as_ref().or(app.document.as_ref()).unwrap();
    let mut candidate = json!({"hair":authored,"submeshes":final_doc.lods[0].submeshes});
    for part in candidate["submeshes"].as_array_mut().unwrap() {
        part["source_vertices"] = part["source_vertex_indices"].clone();
    }
    std::fs::write(
        root.join("candidate.json"),
        serde_json::to_vec(&candidate).unwrap(),
    )
    .unwrap();
    let reason = app.hair_motion_reason().err();
    let kinds = app.hair.state.as_ref().unwrap().locks.iter().fold(
        std::collections::BTreeMap::<String, usize>::new(),
        |mut counts, l| {
            *counts.entry(format!("{:?}", l.kind)).or_default() += 1;
            counts
        },
    );
    let rest = app.hair.scene.as_ref().unwrap().frame.clone();
    let mut timings = vec![];
    let mut hair_motion = 0.0_f32;
    if reason.is_none() {
        app.hair.playing = true;
        app.hair.head_test = 3;
        let mut callback = |frame: &mut DrawSnapshot| {
            app.hair.last_tick = Instant::now() - std::time::Duration::from_secs_f64(1.0 / 60.0);
            app.render_hair();
            assert!(app.hair.playing, "{}", app.hair.feedback);
            *frame = app.hair.scene.as_ref().unwrap().frame.clone();
            hair_motion = hair_motion.max(
                frame.positions[..app.hair.scene.as_ref().unwrap().reference_start]
                    .iter()
                    .zip(&rest.positions)
                    .map(|(a, b)| Vec3::from(*a).distance(Vec3::from(*b)))
                    .fold(0.0_f32, f32::max),
            );
            Ok(())
        };
        let textured = root.join("motion.bmp");
        let base = root.join("motion-base.bmp");
        let ids = root.join("motion-ids.bmp");
        let (_, frames) = pollster::block_on(run_headless_motion_capture(
            &rest,
            &textures,
            &factors,
            HeadlessMaterialCaptureRequest {
                options: HeadlessMaterialCaptureOptions {
                    width: 1920,
                    height: 1080,
                    ..Default::default()
                },
                output: HeadlessMaterialCaptureOutput {
                    textured_bmp: &textured,
                    base_color_bmp: &base,
                    part_id_bmp: &ids,
                    normal_map: None,
                    material_response: None,
                    layer_mask: None,
                },
            },
            180,
            &mut callback,
        ))
        .unwrap();
        timings = frames;
        assert!(hair_motion > 0.005);
        assert_eq!(app.hair.state.as_ref().unwrap(), &authored);
    }
    fn p95(mut values: Vec<f64>) -> f64 {
        if values.is_empty() {
            return 0.0;
        }
        values.sort_by(f64::total_cmp);
        values[(values.len() * 95 / 100).min(values.len() - 1)]
    }
    let mean = timings.iter().map(|v| v[1]).sum::<f64>() / timings.len().max(1) as f64;
    let mut contacts = vec![];
    if reason.is_none() {
        let surface = hair::surface::SurfaceIndex::new(
            &authored.scalp.positions,
            &authored
                .scalp
                .triangles
                .iter()
                .flatten()
                .copied()
                .collect::<Vec<_>>(),
        );
        let indices: Vec<_> = authored.scalp.triangles.iter().flatten().copied().collect();
        for movement in 0..6 {
            app.run_hair_action(HairAction::Reset);
            app.hair.head_test = movement;
            app.hair.playing = true;
            for _ in 0..120 {
                app.hair.last_tick =
                    Instant::now() - std::time::Duration::from_secs_f64(1.0 / 60.0);
                app.render_hair();
            }
            app.hair.playing = false;
            let scene = app.hair.scene.as_ref().unwrap();
            let sim = app.hair.simulation.as_ref().unwrap();
            let mut penetration = 0.0_f32;
            for binding in &authored.bindings {
                if binding.segment == 0 && binding.t == 0.0 {
                    continue;
                }
                let first = scene.parts.iter().find(|p| p.0 == binding.part).unwrap().1;
                let world = Vec3::from(scene.frame.positions[first + binding.vertex as usize]);
                let local =
                    sim.pivot + app.hair.rotation.inverse() * (world - sim.pivot - sim.translation);
                penetration = penetration.max(
                    surface
                        .contact(&authored.scalp.positions, &indices, local, 0.0)
                        .distance(local),
                );
            }
            let textured = root.join(format!("movement-{movement}.bmp"));
            let base = root.join(format!("movement-{movement}-base.bmp"));
            let ids = root.join(format!("movement-{movement}-ids.bmp"));
            pollster::block_on(run_headless_material_capture(
                &scene.frame,
                &textures,
                &factors,
                HeadlessMaterialCaptureOptions {
                    width: 1920,
                    height: 1080,
                    ..Default::default()
                },
                HeadlessMaterialCaptureOutput {
                    textured_bmp: &textured,
                    base_color_bmp: &base,
                    part_id_bmp: &ids,
                    normal_map: None,
                    material_response: None,
                    layer_mask: None,
                },
            ))
            .unwrap();
            let paused = scene.frame.positions.clone();
            app.render_hair();
            assert_eq!(paused, app.hair.scene.as_ref().unwrap().frame.positions);
            assert_eq!(app.hair.state.as_ref().unwrap(), &authored);
            app.run_hair_action(HairAction::Reset);
            app.render_hair();
            let reset = app.hair.scene.as_ref().unwrap().frame.positions.clone();
            app.run_hair_action(HairAction::Reset);
            app.render_hair();
            assert_eq!(reset, app.hair.scene.as_ref().unwrap().frame.positions);
            contacts.push(json!({"movement":movement,"max_card_penetration_m":penetration,"pause_reset":true,"transient":true}));
        }
        std::fs::write(
            root.join("motion-contacts.json"),
            serde_json::to_vec_pretty(&contacts).unwrap(),
        )
        .unwrap();
    }
    let report = json!({"proof":"production pointer dispatcher and draw snapshots; DX12 offscreen capture; desktop presentation unmeasured",
        "guides":authored.guides.len(),"hair_vertices":rest.positions.len()-app.hair.state.as_ref().unwrap().scalp.positions.len()-app.hair.state.as_ref().unwrap().references.iter().map(|r|r.positions.len()).sum::<usize>(),
        "locks":kinds,"preparation_ms":preparation_ms,"selection_cpu_p95_ms":p95(picking),"input_to_draw_snapshot_p95_ms":p95(grooming),
        "offscreen_frame_ms":mean,"offscreen_fps":if mean>0.0{1000.0/mean}else{0.0},"hair_motion_distance":hair_motion,"motion_blocker":reason,
        "material_overrides":false,"explicit_root_correction":topology_probe&&!generated,"cut_delete":topology_probe,"game_verified":false});
    std::fs::write(
        root.join("benchmark.json"),
        serde_json::to_vec_pretty(&report).unwrap(),
    )
    .unwrap();
    println!("{report}");
    if generated {
        assert!(reason.is_none());
        assert!(mean <= 1000.0 / 30.0, "offscreen frame budget exceeded");
        assert!(
            contacts
                .iter()
                .all(|v| v["max_card_penetration_m"].as_f64().unwrap() <= 0.002),
            "Visible card penetration: {contacts:?}"
        );
    }
}

#[test]
#[ignore = "requires an authorized real hairstyle state and temporary evidence directory"]
fn hair_production_settle_regression() {
    let input = std::env::var("CDMW_HAIR_PROBE_INPUT").unwrap();
    let root = std::path::PathBuf::from(std::env::var("CDMW_HAIR_PROBE_OUTPUT").unwrap());
    std::fs::create_dir_all(&root).unwrap();
    let state: HairState = serde_json::from_slice(&std::fs::read(input).unwrap()).unwrap();
    let (min, max) = hair_bounds(&state);
    let mut cases = vec![];
    for extra in [0.0, 0.0001, 0.0005] {
        for movement in 0..6 {
            let mut simulation = Simulation::new(&state).unwrap();
            for frame in 0..120 {
                let pose = simulation
                    .advance_test(
                        1.0 / 60.0 + extra,
                        hair::MotionSettings::default(),
                        &state.collisions,
                        movement,
                        max.y - min.y,
                    )
                    .unwrap();
                simulation
                    .settled_state(&state, pose.head)
                    .unwrap_or_else(|e| {
                        panic!("Settling movement {movement}, frame {frame}, jitter {extra}: {e}")
                    });
            }
            cases.push(json!({"movement":movement,"frame_jitter_seconds":extra,"valid_settled_frames":120}));
        }
    }
    std::fs::write(
        root.join("settle-regression.json"),
        serde_json::to_vec_pretty(&cases).unwrap(),
    )
    .unwrap();
}

#[test]
#[ignore = "requires a real prepared hair candidate and a temporary evidence directory"]
fn hair_production_contact_regression() {
    let input = std::env::var("CDMW_HAIR_PROBE_INPUT").unwrap();
    let root = std::path::PathBuf::from(std::env::var("CDMW_HAIR_PROBE_OUTPUT").unwrap());
    std::fs::create_dir_all(&root).unwrap();
    let candidate: Value = serde_json::from_slice(&std::fs::read(input).unwrap()).unwrap();
    let state: HairState = serde_json::from_value(candidate["hair"].clone()).unwrap();
    let (min, max) = hair_bounds(&state);
    let indices: Vec<_> = state.scalp.triangles.iter().flatten().copied().collect();
    let surface = hair::surface::SurfaceIndex::new(&state.scalp.positions, &indices);
    let parts: Vec<(u32, Vec<[f32; 3]>)> = candidate["submeshes"]
        .as_array()
        .unwrap()
        .iter()
        .enumerate()
        .map(|(i, part)| {
            (
                i as u32,
                serde_json::from_value(part["positions"].clone()).unwrap(),
            )
        })
        .collect();
    let mut report = vec![];
    for movement in 0..6 {
        let mut simulation = Simulation::new(&state).unwrap();
        let mut worst = 0.0_f32;
        let mut detail = Value::Null;
        let mut elapsed = 0.0;
        for frame in 0..120 {
            let start = Instant::now();
            let pose = simulation
                .advance_test(
                    1.0 / 60.0,
                    hair::MotionSettings::default(),
                    &state.collisions,
                    movement,
                    max.y - min.y,
                )
                .unwrap();
            elapsed += start.elapsed().as_secs_f64();
            if frame % 10 != 9 {
                continue;
            }
            for (part, rest) in &parts {
                let mut positions = rest.clone();
                hair::deform(&state.bindings, &simulation.points, *part, &mut positions).unwrap();
                for binding in state
                    .bindings
                    .iter()
                    .filter(|b| b.part == *part && !(b.segment == 0 && b.t == 0.0))
                {
                    let local = simulation.pivot
                        + pose.head.inverse()
                            * (Vec3::from(positions[binding.vertex as usize])
                                - simulation.pivot
                                - simulation.translation);
                    let penetration = surface
                        .contact(&state.scalp.positions, &indices, local, 0.0)
                        .distance(local);
                    if penetration > worst {
                        worst = penetration;
                        detail = json!({"frame":frame,"binding":binding,"point":local.to_array(),"guide":simulation.points[binding.guide as usize]});
                    }
                }
            }
        }
        report.push(json!({"movement":movement,"max_card_penetration_m":worst,"simulation_frame_ms":elapsed*1000.0/120.0,"worst":detail}));
    }
    std::fs::write(
        root.join("contact-regression.json"),
        serde_json::to_vec_pretty(&report).unwrap(),
    )
    .unwrap();
    println!("{}", serde_json::to_string(&report).unwrap());
    assert!(report
        .iter()
        .all(|v| v["max_card_penetration_m"].as_f64().unwrap() <= 0.002));
}

fn ready_hair_app() -> (LabApplication, egui::Rect) {
    let (state, document) = fixture();
    let result = prepare(
        state,
        document,
        "Bob".into(),
        Preparation::Fill(0, Preset::Bob, 0.3),
        &AtomicBool::new(false),
    )
    .unwrap();
    let mut app = LabApplication::new(None, None);
    app.document = Some(result.document.clone());
    app.cdmw_state = json!({"hair":{"available":true,"materials_ready":true},"replacement":{"comparison":"edit"}});
    app.hydrate_hair(Some(result.state));
    app.hair.pending_preset = false;
    let rect = egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(1920.0, 1080.0));
    app.viewport_rect = Some(rect);
    app.camera.frame_positions_in_viewport(
        result.document.lods[0].submeshes[0]
            .positions
            .iter()
            .copied()
            .map(Vec3::from),
        rect,
    );
    app.render_hair();
    (app, rect)
}

fn visible_lock(app: &LabApplication, rect: egui::Rect) -> (Vec2, u64) {
    let scene = app.hair.scene.as_ref().unwrap();
    for face in scene.frame.indices.chunks_exact(3).step_by(17) {
        let position = face
            .iter()
            .map(|i| Vec3::from(scene.frame.positions[*i as usize]))
            .sum::<Vec3>()
            / 3.0;
        if let Some(p) = app.camera.project(position, rect) {
            if let Some((id, _, _)) = app.lock_at(p.screen, rect) {
                if app
                    .hair
                    .state
                    .as_ref()
                    .is_some_and(|s| s.locks.iter().any(|l| l.id == id && l.guide.is_some()))
                {
                    return (p.screen, id);
                }
            }
        }
    }
    panic!("No visible selectable hair lock");
}

fn await_hair(app: &mut LabApplication) {
    let deadline = Instant::now() + std::time::Duration::from_secs(10);
    while app.hair.job.is_some() || !app.hair.queued.is_empty() {
        assert!(Instant::now() < deadline, "Hair preparation timed out");
        std::thread::sleep(std::time::Duration::from_millis(1));
        app.poll_hair();
    }
    app.render_hair();
}

fn await_hair_host(app: &mut LabApplication) {
    let deadline = Instant::now() + std::time::Duration::from_secs(120);
    loop {
        app.poll_cdmw();
        app.poll_hair();
        assert!(!app.cdmw_exit_requested, "{}", app.status);
        if !app.hair.preparing() && !app.cdmw_busy() {
            break;
        }
        assert!(
            Instant::now() < deadline,
            "Host acknowledgement timed out: {} / {}",
            app.status,
            app.hair.feedback
        );
        std::thread::sleep(std::time::Duration::from_millis(5));
    }
    assert!(!app.status.contains("rejected"), "{}", app.status);
    app.render_hair();
}

fn capture_hair_workflow_step(
    app: &LabApplication,
    input: &Value,
    root: &std::path::Path,
    name: &str,
) {
    if std::env::var_os("CDMW_HAIR_PROBE_CAPTURE_STEPS").is_none() {
        return;
    }
    let package = PathBuf::from(input["session_root"].as_str().unwrap());
    let material: Value = serde_json::from_slice(
        &std::fs::read(
            package.join(
                input["host"]["archive_refit_materials"]["file"]["path"]
                    .as_str()
                    .unwrap(),
            ),
        )
        .unwrap(),
    )
    .unwrap();
    let rows = material["textures"].as_array().unwrap();
    let bytes: Vec<_> = rows
        .iter()
        .map(|r| std::fs::read(package.join(r["file"]["path"].as_str().unwrap())).unwrap())
        .collect();
    let ownership: Vec<Vec<Vec<u32>>> = rows
        .iter()
        .map(|r| serde_json::from_value(r["material_indices_by_lod"].clone()).unwrap())
        .collect();
    let textures: Vec<_> = rows
        .iter()
        .enumerate()
        .map(|(i, r)| HeadlessMaterialTexture {
            bytes: &bytes[i],
            role: serde_json::from_value(r["role"].clone()).unwrap(),
            material_indices_by_lod: &ownership[i],
        })
        .collect();
    let presentations: Vec<SessionMaterialPresentation> =
        serde_json::from_value(material["material_presentations"].clone()).unwrap();
    let factor_owners: Vec<_> = presentations
        .iter()
        .map(|p| cdmw_material_ownership(p, 1))
        .collect();
    let factors: Vec<_> = presentations
        .iter()
        .zip(&factor_owners)
        .map(|(p, o)| HeadlessMaterialFactors {
            factors: cdmw_material_preview_factors(p),
            material_indices_by_lod: o,
        })
        .collect();
    assert!(
        !textures.is_empty() && !factors.is_empty(),
        "materials must come from the real loader"
    );
    let textured = root.join(format!("tool-{name}.bmp"));
    let base = root.join(format!("tool-{name}-base.bmp"));
    let ids = root.join(format!("tool-{name}-ids.bmp"));
    let report = pollster::block_on(run_headless_material_capture(
        &app.hair.scene.as_ref().unwrap().frame,
        &textures,
        &factors,
        HeadlessMaterialCaptureOptions {
            width: 1280,
            height: 900,
            camera: Some(HeadlessMaterialCaptureCamera {
                yaw_degrees: 180.0,
                pitch_degrees: 0.0,
            }),
            ..Default::default()
        },
        HeadlessMaterialCaptureOutput {
            textured_bmp: &textured,
            base_color_bmp: &base,
            part_id_bmp: &ids,
            normal_map: None,
            material_response: None,
            layer_mask: None,
        },
    ))
    .unwrap();
    assert!(report.textured.non_background_pixels > 1000);
    if app.hair.scene.as_ref().unwrap().reference_start > 0 {
        assert!(report.dds_textures_uploaded > 0);
    }
}

#[test]
#[ignore = "requires authorized installed assets and the Python production host"]
fn hair_production_workflow_matrix() {
    let input: Value = serde_json::from_slice(
        &std::fs::read(std::env::var("CDMW_HAIR_PROBE_INPUT").unwrap()).unwrap(),
    )
    .unwrap();
    let mailbox = PathBuf::from(std::env::var("CDMW_HAIR_PROBE_MAILBOX").unwrap());
    let state: HairState = serde_json::from_value(input["hair"].clone()).unwrap();
    let generated = state.groups.iter().all(|g| g.mode == GroupMode::Generated);
    let empty_start = std::env::var_os("CDMW_HAIR_PROBE_EMPTY_START").is_some();
    assert!(!empty_start || generated);
    let mut app = LabApplication::new(None, None);
    app.document = Some(serde_json::from_value(input["document"].clone()).unwrap());
    app.cdmw_state = input["host"].clone();
    let rect = egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(1280.0, 900.0));
    app.viewport_rect = Some(rect);
    app.hydrate_hair(Some(state));
    app.hair.pending_preset = false;
    app.cdmw_bridge = Some(crate::cdmw_session::CdmwBridge::for_hair_probe(
        PathBuf::from(input["session_root"].as_str().unwrap()),
        input["session_id"].as_str().unwrap(),
        input["host"]["base_revision"].as_u64().unwrap(),
        mailbox.clone(),
    ));
    app.render_hair();
    let mut results = vec![];
    if generated {
        app.hair.requested_preset = Some(if empty_start { "empty" } else { "bob" }.into());
        app.poll_hair();
    } else {
        app.run_hair_action(HairAction::Prepare);
    }
    await_hair_host(&mut app);
    if empty_start {
        assert!(app.hair.state.as_ref().unwrap().guides.is_empty());
        assert_eq!(app.hair.scene.as_ref().unwrap().reference_start, 0);
    }
    results.push(json!({"tool":"preset/setup","revision":app.hair.state.as_ref().unwrap().revision,"blank_start":empty_start}));
    capture_hair_workflow_step(&app, &input, &mailbox, "setup");
    if generated {
        for preset in ["empty", "cropped", "long", "ponytail", "bob", "bob"]
            .into_iter()
            .filter(|_| !empty_start)
        {
            let before = app.hair.state.clone().unwrap();
            app.hair.requested_preset = Some(preset.into());
            app.poll_hair();
            await_hair_host(&mut app);
            let after = app.hair.state.clone().unwrap();
            // Bounded history may evict an older action. Verify the single
            // undoable edit itself, not growth of the retained stack.
            app.submit_cdmw_command("undo", json!({}), "Undo preset");
            await_hair_host(&mut app);
            assert_eq!(app.hair.state.as_ref().unwrap().guides, before.guides);
            assert_eq!(app.hair.state.as_ref().unwrap().locks, before.locks);
            app.submit_cdmw_command("redo", json!({}), "Redo preset");
            await_hair_host(&mut app);
            assert_eq!(app.hair.state.as_ref().unwrap().guides, after.guides);
            assert_eq!(app.hair.state.as_ref().unwrap().locks, after.locks);
            assert_eq!(
                app.hair.state.as_ref().unwrap().locks.is_empty(),
                preset == "empty"
            );
            results.push(
                json!({"tool":format!("Preset {preset}"),"one_undo":true,"acknowledged":true}),
            );
        }
        for stroke in 0..2 {
            app.camera
                .set_standard_view(crate::camera::StandardView::Top);
            let scalp = &app.hair.state.as_ref().unwrap().scalp;
            app.camera
                .frame_positions_in_viewport(scalp.positions.iter().copied().map(Vec3::from), rect);
            let root = scalp
                .triangles
                .iter()
                .map(|face| {
                    face.iter()
                        .map(|i| Vec3::from(scalp.positions[*i as usize]))
                        .sum::<Vec3>()
                        / 3.0
                })
                .max_by(|a, b| a.y.total_cmp(&b.y))
                .unwrap();
            let point =
                app.camera.project(root, rect).unwrap().screen + Vec2::X * stroke as f32 * 12.0;
            app.hair.tool = Some(HairTool::Guide);
            app.hair.symmetry = stroke == 1;
            let count = app.hair.state.as_ref().unwrap().locks.len();
            for event in [
                ViewportPointerEvent::PrimaryPressed(point),
                ViewportPointerEvent::PrimaryMoved(point + Vec2::new(25.0, 40.0)),
                ViewportPointerEvent::PrimaryReleased(point + Vec2::new(25.0, 40.0)),
            ] {
                app.dispatch_hair_pointer(event, rect, false, false, false);
            }
            await_hair_host(&mut app);
            assert!(
                app.hair.state.as_ref().unwrap().locks.len() > count,
                "Draw {stroke}: {}",
                app.hair.feedback
            );
            capture_hair_workflow_step(&app, &input, &mailbox, &format!("draw-{}", stroke + 1));
            results.push(json!({"tool":format!("Draw {}",stroke+1),"symmetry":stroke==1,"geometry_changed":true,"acknowledged":true}));
        }
    } else {
        let unresolved = app
            .hair
            .state
            .as_ref()
            .unwrap()
            .locks
            .iter()
            .filter(|l| l.kind == LockKind::Unresolved)
            .count();
        if unresolved > 0 {
            assert!(app.hair_motion_reason().is_err());
            results.push(
                json!({"tool":"existing preparation","unresolved":unresolved,"motion_gated":true}),
            );
        }
        app.camera
            .set_standard_view(crate::camera::StandardView::Top);
        let groups = app.hair.state.as_ref().unwrap().groups.clone();
        for group in groups {
            let ids: HashSet<_> = app
                .hair
                .state
                .as_ref()
                .unwrap()
                .locks
                .iter()
                .filter(|l| l.part == group.part && l.kind == LockKind::Unresolved)
                .map(|l| l.id as usize)
                .collect();
            if ids.is_empty() {
                continue;
            }
            app.hair.selected = ids.clone();
            app.run_hair_action(HairAction::Rigid);
            await_hair_host(&mut app);
            app.submit_cdmw_command("undo", json!({}), "Undo rigid attachment");
            await_hair_host(&mut app);
            app.hair.selected = ids;
            app.hair.group = group.id;
            app.hair.tool = Some(HairTool::Root);
            let scalp = &app.hair.state.as_ref().unwrap().scalp;
            app.camera
                .frame_positions_in_viewport(scalp.positions.iter().copied().map(Vec3::from), rect);
            let root = scalp
                .triangles
                .iter()
                .map(|f| {
                    f.iter()
                        .map(|i| Vec3::from(scalp.positions[*i as usize]))
                        .sum::<Vec3>()
                        / 3.0
                })
                .max_by(|a, b| a.y.total_cmp(&b.y))
                .unwrap();
            let point = app.camera.project(root, rect).unwrap().screen;
            for event in [
                ViewportPointerEvent::PrimaryPressed(point),
                ViewportPointerEvent::PrimaryReleased(point),
            ] {
                app.dispatch_hair_pointer(event, rect, false, false, false);
            }
            await_hair_host(&mut app);
        }
        let motion_blocker = app.hair_motion_reason().err();
        if let Some(reason) = &motion_blocker {
            assert!(reason.contains("too wide for stable motion"), "{reason}");
        }
        results.push(json!({"tool":"root/group and rigid attachment","acknowledged":true,"motion_blocker":motion_blocker}));
    }
    capture_hair_workflow_step(&app, &input, &mailbox, "prepared");
    app.camera
        .set_standard_view(crate::camera::StandardView::Front);
    app.camera.frame_positions_in_viewport(
        app.hair
            .scene
            .as_ref()
            .unwrap()
            .frame
            .positions
            .iter()
            .copied()
            .map(Vec3::from),
        rect,
    );
    let (point, id) = visible_lock(&app, rect);
    app.hair.tool = Some(HairTool::Select);
    let selection_state = app.hair.state.clone();
    for ctrl in [false, true, false] {
        for event in [
            ViewportPointerEvent::PrimaryPressed(point),
            ViewportPointerEvent::PrimaryReleased(point),
        ] {
            app.dispatch_hair_pointer(event, rect, ctrl, false, false);
        }
        assert_eq!(app.hair.selected.contains(&(id as usize)), !ctrl);
    }
    for event in [
        ViewportPointerEvent::PrimaryPressed(Vec2::splat(1.0)),
        ViewportPointerEvent::PrimaryMoved(Vec2::new(1278.0, 898.0)),
        ViewportPointerEvent::PrimaryReleased(Vec2::new(1278.0, 898.0)),
    ] {
        app.dispatch_hair_pointer(event, rect, false, false, false);
    }
    assert!(!app.hair.selected.is_empty());
    assert_eq!(app.hair.state, selection_state);
    results.push(json!({"tool":"Select, Ctrl-select, marquee","selection_only":true}));
    for tool in [
        HairTool::Lengthen,
        HairTool::Move,
        HairTool::Comb,
        HairTool::Smooth,
        HairTool::Curl,
        HairTool::Clump,
    ] {
        let (point, id) = visible_lock(&app, rect);
        app.hair.selected.clear();
        app.hair.tool = Some(tool);
        app.hair.radius = 100.0;
        let before = app.hair.state.clone().unwrap();
        let frame = app.hair.scene.as_ref().unwrap().frame.positions.clone();
        for event in [
            ViewportPointerEvent::PrimaryPressed(point),
            ViewportPointerEvent::PrimaryMoved(point + Vec2::new(8.0, 4.0)),
            ViewportPointerEvent::PrimaryReleased(point + Vec2::new(8.0, 4.0)),
        ] {
            app.dispatch_hair_pointer(event, rect, false, false, false);
        }
        await_hair_host(&mut app);
        assert_ne!(
            frame,
            app.hair.scene.as_ref().unwrap().frame.positions,
            "{tool:?}: {}",
            app.hair.feedback
        );
        let after = app.hair.state.clone().unwrap();
        assert!(after
            .guides
            .iter()
            .zip(&before.guides)
            .all(|(a, b)| a.points[0] == b.points[0]));
        capture_hair_workflow_step(&app, &input, &mailbox, &format!("{tool:?}"));
        results.push(json!({"tool":format!("{tool:?}"),"lock":id,"geometry_changed":true,"roots_fixed":true,"acknowledged":true}));
        if tool == HairTool::Lengthen {
            app.submit_cdmw_command("undo", json!({}), "Undo");
            await_hair_host(&mut app);
            assert_eq!(app.hair.state.as_ref().unwrap().guides, before.guides);
            app.submit_cdmw_command("redo", json!({}), "Redo");
            await_hair_host(&mut app);
            assert_eq!(app.hair.state.as_ref().unwrap().guides, after.guides);
            if empty_start {
                results.push(json!({"tool":"Lengthen Undo/Redo","acknowledged":true}));
                std::fs::write(
                    mailbox.join("tools.json"),
                    serde_json::to_vec_pretty(&results).unwrap(),
                )
                .unwrap();
                return;
            }
        }
    }
    for action in [HairAction::Settings, HairAction::DeleteGuides] {
        let (_, id) = visible_lock(&app, rect);
        app.hair.selected = HashSet::from([id as usize]);
        app.hair.width *= 1.2;
        app.hair.density = 3;
        let before = app.hair.scene.as_ref().unwrap().frame.positions.clone();
        app.run_hair_action(action.clone());
        await_hair_host(&mut app);
        assert_ne!(
            before,
            app.hair.scene.as_ref().unwrap().frame.positions,
            "{action:?}: {}",
            app.hair.feedback
        );
        capture_hair_workflow_step(&app, &input, &mailbox, &format!("{action:?}"));
        results.push(
            json!({"tool":format!("{action:?}"),"geometry_changed":true,"acknowledged":true}),
        );
    }
    for tool in [HairTool::Cut, HairTool::Erase] {
        let (point, _) = visible_lock(&app, rect);
        app.hair.tool = Some(tool);
        let before = app.hair.scene.as_ref().unwrap().frame.positions.clone();
        for event in [
            ViewportPointerEvent::PrimaryPressed(point),
            ViewportPointerEvent::PrimaryReleased(point),
        ] {
            app.dispatch_hair_pointer(event, rect, false, false, false);
        }
        await_hair_host(&mut app);
        assert_ne!(
            before,
            app.hair.scene.as_ref().unwrap().frame.positions,
            "{tool:?}: {}",
            app.hair.feedback
        );
        capture_hair_workflow_step(&app, &input, &mailbox, &format!("{tool:?}"));
        results
            .push(json!({"tool":format!("{tool:?}"),"geometry_changed":true,"acknowledged":true}));
    }
    if let Err(reason) = app.hair_motion_reason() {
        assert!(
            !generated && reason.contains("too wide for stable motion"),
            "{reason}"
        );
        let before = app.hair.state.clone();
        app.hair.playing = true;
        app.render_hair();
        assert!(!app.hair.playing);
        app.run_hair_action(HairAction::Settle);
        assert_eq!(app.hair.feedback, reason);
        assert_eq!(app.hair.state, before);
        assert!(!app.hair.preparing());
        results.push(
            json!({"tool":"Motion / settled shape","unavailable":reason,"state_unchanged":true}),
        );
    } else {
        app.hair.playing = true;
        for _ in 0..30 {
            app.hair.last_tick = Instant::now() - std::time::Duration::from_secs_f64(1.0 / 60.0);
            app.render_hair();
        }
        let before_settle = app.hair.state.as_ref().unwrap().guides.clone();
        std::fs::write(
            mailbox.join("before-settle.json"),
            serde_json::to_vec(app.hair.state.as_ref().unwrap()).unwrap(),
        )
        .unwrap();
        app.run_hair_action(HairAction::Settle);
        await_hair_host(&mut app);
        let settled = app.hair.state.as_ref().unwrap().guides.clone();
        assert!(
            settled != before_settle,
            "Settled shape was not published: {}",
            app.hair.feedback
        );
        app.submit_cdmw_command("undo", json!({}), "Undo settled shape");
        await_hair_host(&mut app);
        assert!(
            app.hair.state.as_ref().unwrap().guides == before_settle,
            "Undo did not restore the pre-settled guides"
        );
        app.submit_cdmw_command("redo", json!({}), "Redo settled shape");
        await_hair_host(&mut app);
        assert!(
            app.hair.state.as_ref().unwrap().guides == settled,
            "Redo did not restore the settled guides"
        );
        capture_hair_workflow_step(&app, &input, &mailbox, "settled");
        results.push(json!({"tool":"Settle and Undo/Redo","acknowledged":true}));
    }
    app.run_hair_action(HairAction::Convert);
    await_hair_host(&mut app);
    assert!(app.hair.state.as_ref().unwrap().converted);
    app.submit_cdmw_command("undo", json!({}), "Undo conversion");
    await_hair_host(&mut app);
    assert!(!app.hair.state.as_ref().unwrap().converted);
    results.push(json!({"tool":"Convert and Undo","acknowledged":true}));
    std::fs::write(
        mailbox.join("tools.json"),
        serde_json::to_vec_pretty(&results).unwrap(),
    )
    .unwrap();
}

#[test]
fn hair_production_dispatch_select_move_delete_and_restore() {
    let (mut app, rect) = ready_hair_app();
    let (point, id) = visible_lock(&app, rect);
    let before = app.hair.state.clone().unwrap();
    let original = app.document.clone().unwrap();
    app.hair.tool = Some(HairTool::Select);
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryPressed(point),
        rect,
        false,
        false,
        false,
    );
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryReleased(point),
        rect,
        false,
        false,
        false,
    );
    assert_eq!(app.hair.selected, HashSet::from([id as usize]));
    assert_eq!(
        app.hair.state.as_ref().unwrap(),
        &before,
        "selection must not edit state"
    );
    assert!(!app.hair.preparing());
    app.hair.tool = Some(HairTool::Move);
    let old_frame = app.hair.scene.as_ref().unwrap().frame.positions.clone();
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryPressed(point),
        rect,
        false,
        false,
        false,
    );
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryMoved(point + Vec2::new(48.0, -16.0)),
        rect,
        false,
        false,
        false,
    );
    app.render_hair();
    assert_ne!(
        old_frame,
        app.hair.scene.as_ref().unwrap().frame.positions,
        "the rendered hair must move during the drag"
    );
    let gi = before
        .locks
        .iter()
        .find(|l| l.id == id)
        .unwrap()
        .guide
        .unwrap() as usize;
    let stroke = app.hair.stroke.as_ref().unwrap();
    assert_eq!(stroke.guides[gi].points[0], before.guides[gi].points[0]);
    for (index, guide) in before.guides.iter().enumerate() {
        if index != gi {
            assert_eq!(&stroke.guides[index], guide);
        }
    }
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryReleased(point + Vec2::new(48.0, -16.0)),
        rect,
        false,
        false,
        false,
    );
    await_hair(&mut app);
    assert_eq!(
        app.hair.state.as_ref().unwrap().revision,
        before.revision + 1,
        "one stroke is one edit"
    );
    assert_eq!(
        app.hair.preview.as_ref().unwrap().lods[0].submeshes[0].uvs,
        original.lods[0].submeshes[0].uvs
    );
    let saved_state = app.hair.state.clone().unwrap();
    let saved_doc = app.hair.preview.clone().unwrap();
    app.run_hair_action(HairAction::DeleteGuides);
    await_hair(&mut app);
    assert!(!app
        .hair
        .state
        .as_ref()
        .unwrap()
        .locks
        .iter()
        .any(|l| l.id == id));
    assert!(
        app.hair.preview.as_ref().unwrap().lods[0].submeshes[0]
            .positions
            .len()
            < saved_doc.lods[0].submeshes[0].positions.len()
    );
    app.document = Some(saved_doc.clone());
    app.hydrate_hair(Some(saved_state.clone()));
    app.render_hair();
    assert_eq!(
        app.hair.state.as_ref().unwrap(),
        &saved_state,
        "host Undo restores all hair state"
    );
    assert_eq!(app.document.as_ref().unwrap(), &saved_doc);
}

#[test]
fn hair_production_motion_deforms_hair_not_only_reference_and_reset_is_neutral() {
    let (mut app, _) = ready_hair_app();
    let before = app.hair.state.clone().unwrap();
    let original = app.document.clone().unwrap();
    let rest = app.hair.scene.as_ref().unwrap().frame.positions.clone();
    app.hair.playing = true;
    app.hair.head_test = 3;
    for _ in 0..60 {
        app.hair.last_tick = Instant::now() - std::time::Duration::from_secs_f64(1.0 / 60.0);
        app.render_hair();
    }
    assert!(app.hair.playing, "{}", app.hair.feedback);
    let scene = app.hair.scene.as_ref().unwrap();
    let hair_moved = scene.frame.positions[..scene.reference_start]
        .iter()
        .zip(&rest)
        .any(|(a, b)| Vec3::from(*a).distance(Vec3::from(*b)) > 0.005);
    assert!(hair_moved, "moving only the bust must fail");
    let sim = app.hair.simulation.as_ref().unwrap();
    let (min, max) = hair_bounds(&before);
    let pose = hair::PreviewPose::at(sim.pivot, (max.y - min.y).max(0.01), sim.elapsed as f32, 3);
    assert!(
        sim.points
            .iter()
            .zip(&before.guides)
            .any(|(g, rest)| Vec3::from(*g.last().unwrap())
                .distance(pose.head_point(Vec3::from(*rest.points.last().unwrap())))
                > 0.005),
        "strands must deform beyond rigid head motion"
    );
    assert_eq!(
        app.hair.state.as_ref().unwrap(),
        &before,
        "simulation must not change authored hair"
    );
    assert_eq!(app.document.as_ref().unwrap(), &original);
    app.run_hair_action(HairAction::Reset);
    app.render_hair();
    assert_eq!(app.hair.scene.as_ref().unwrap().frame.positions, rest);
    app.run_hair_action(HairAction::Settle);
    assert_eq!(app.hair.feedback, "Play motion first");
    assert_eq!(app.hair.state.as_ref().unwrap(), &before);
    assert!(!app.hair.preparing());
}

#[test]
fn hair_existing_motion_rejects_wide_bindings_and_allows_rigid_correction() {
    let (mut app, _) = ready_hair_app();
    let state = app.hair.state.as_mut().unwrap();
    state.groups[0].mode = GroupMode::Existing;
    for lock in &mut state.locks {
        lock.kind = LockKind::Bound;
    }
    state.revision += 1;
    assert!(
        app.hair_motion_reason().is_ok(),
        "Narrow existing cards can simulate"
    );
    let state = app.hair.state.as_mut().unwrap();
    let guide = state.bindings[0].guide;
    state.bindings[0].offset[0] = 0.10;
    state.revision += 1;
    let id = state
        .locks
        .iter()
        .find(|l| l.guide == Some(guide))
        .unwrap()
        .id;
    let before = state.clone();
    let reason = app.hair_motion_reason().unwrap_err();
    assert!(reason.contains("too wide for stable motion"));
    app.hair.playing = true;
    app.render_hair();
    assert!(!app.hair.playing);
    app.run_hair_action(HairAction::Settle);
    assert_eq!(app.hair.feedback, reason);
    assert_eq!(app.hair.state.as_ref().unwrap(), &before);
    assert!(!app.hair.preparing());
    app.hair.selected = HashSet::from([id as usize]);
    app.run_hair_action(HairAction::Rigid);
    await_hair(&mut app);
    assert!(app.hair_motion_reason().is_ok(), "{}", app.hair.feedback);
    assert_eq!(
        app.hair
            .state
            .as_ref()
            .unwrap()
            .locks
            .iter()
            .find(|l| l.id == id)
            .unwrap()
            .kind,
        LockKind::Rigid
    );
}

#[test]
fn hair_facial_references_follow_the_head_below_the_neck_blend() {
    let (mut app, _) = ready_hair_app();
    let detail = hair::Scalp {
        identity: "head:facial-details".into(),
        positions: vec![[0.02, 0.16, 0.0], [0.03, 0.16, 0.0], [0.02, 0.17, 0.0]],
        triangles: vec![[0, 1, 2]],
    };
    app.hair
        .state
        .as_mut()
        .unwrap()
        .references
        .push(detail.clone());
    app.hair.scene = None;
    app.hair.playing = true;
    app.hair.head_test = 3;
    for _ in 0..30 {
        app.hair.last_tick = Instant::now() - std::time::Duration::from_secs_f64(1.0 / 60.0);
        app.render_hair();
    }
    let state = app.hair.state.as_ref().unwrap();
    let scene = app.hair.scene.as_ref().unwrap();
    let sim = app.hair.simulation.as_ref().unwrap();
    let (min, max) = hair_bounds(state);
    let pose = hair::PreviewPose::at(sim.pivot, (max.y - min.y).max(0.01), sim.elapsed as f32, 3);
    let first = scene.frame.positions.len() - detail.positions.len();
    for (rest, actual) in detail.positions.iter().zip(&scene.frame.positions[first..]) {
        assert!(
            pose.head_point(Vec3::from(*rest))
                .distance(Vec3::from(*actual))
                < 1e-6
        );
    }
    assert_eq!(
        state.scalp.positions.len(),
        fixture().0.scalp.positions.len()
    );
}

#[test]
fn hair_repeated_presets_and_empty_clicks_do_not_duplicate_or_publish() {
    let (mut app, rect) = ready_hair_app();
    let before = app.hair.state.clone().unwrap();
    app.run_hair_action(HairAction::Fill);
    await_hair(&mut app);
    assert_eq!(app.hair.state.as_ref().unwrap().guides.len(), 256);
    assert_eq!(app.hair.state.as_ref().unwrap().locks.len(), 256);
    let revision = app.hair.state.as_ref().unwrap().revision;
    app.hair.tool = Some(HairTool::Move);
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryPressed(Vec2::new(-100.0, -100.0)),
        rect,
        false,
        false,
        false,
    );
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryReleased(Vec2::new(-100.0, -100.0)),
        rect,
        false,
        false,
        false,
    );
    assert_eq!(app.hair.state.as_ref().unwrap().revision, revision);
    assert!(!app.hair.preparing());
    assert_eq!(before.guides.len(), 256);
}

#[test]
fn hair_legacy_hydration_preserves_existing_geometry_until_explicit_preparation() {
    let (mut app, _) = ready_hair_app();
    let original = app.document.clone();
    let mut old = app.hair.state.clone().unwrap();
    old.locks.clear();
    old.prepared_parts.clear();
    old.revision = 9;
    old.groups[0].mode = GroupMode::Existing;
    app.hair = HairEditor::default();
    app.hydrate_hair(Some(old.clone()));
    app.poll_hair();
    assert_eq!(app.document, original);
    assert_eq!(app.hair.state, Some(old));
    assert!(!app.hair.preparing());
    assert!(app.hair_motion_reason().is_err());
}

#[test]
fn hair_draw_is_visible_during_stroke_and_symmetry_cut_erase_remove_geometry() {
    let (mut app, rect) = ready_hair_app();
    app.run_hair_action(HairAction::Empty);
    await_hair(&mut app);
    app.hair.tool = Some(HairTool::Guide);
    app.hair.symmetry = true;
    let point = app
        .camera
        .project(Vec3::new(0.08, 0.2, 0.0), rect)
        .unwrap()
        .screen;
    let vertices = app.hair.scene.as_ref().unwrap().frame.positions.len();
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryPressed(point),
        rect,
        false,
        false,
        false,
    );
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryMoved(point + Vec2::new(50.0, 90.0)),
        rect,
        false,
        false,
        false,
    );
    app.render_hair();
    assert_eq!(app.hair.stroke.as_ref().unwrap().locks.len(), 2);
    assert!(
        app.hair.scene.as_ref().unwrap().frame.positions.len() > vertices,
        "Draw must show cards before release"
    );
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryReleased(point + Vec2::new(50.0, 90.0)),
        rect,
        false,
        false,
        false,
    );
    await_hair(&mut app);
    let state = app.hair.state.clone().unwrap();
    assert_eq!(state.locks[0].mirrored, Some(state.locks[1].id));
    app.camera
        .set_standard_view(crate::camera::StandardView::Top);
    let (point, id) = visible_lock(&app, rect);
    app.hair.tool = Some(HairTool::Cut);
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryPressed(point),
        rect,
        false,
        false,
        false,
    );
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryReleased(point),
        rect,
        false,
        false,
        false,
    );
    await_hair(&mut app);
    let cut = app.hair.state.as_ref().unwrap();
    for lock in &cut.locks {
        let g = lock.guide.unwrap() as usize;
        assert_eq!(cut.guides[g].points[0], state.guides[g].points[0]);
        assert!(
            Vec3::from(*cut.guides[g].points.last().unwrap())
                .distance(Vec3::from(cut.guides[g].points[0]))
                < Vec3::from(*state.guides[g].points.last().unwrap())
                    .distance(Vec3::from(state.guides[g].points[0])),
            "Cut must affect each mirrored tip"
        );
    }
    assert!(cut.locks.iter().any(|l| l.id == id));
    let (point, _) = visible_lock(&app, rect);
    app.hair.tool = Some(HairTool::Erase);
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryPressed(point),
        rect,
        false,
        false,
        false,
    );
    app.render_hair();
    assert_eq!(
        app.hair.selected.len(),
        2,
        "Erase highlights the explicit mirror too"
    );
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryReleased(point),
        rect,
        false,
        false,
        false,
    );
    await_hair(&mut app);
    assert!(app.hair.state.as_ref().unwrap().locks.is_empty());
    assert!(app.hair.preview.as_ref().unwrap().lods[0].submeshes[0]
        .indices
        .is_empty());
}

#[test]
fn hair_draw_follows_curved_scalp_and_ctrl_lifts_away_without_entering_it() {
    for free in [false, true] {
        let (mut state, doc) = fixture();
        for p in &mut state.scalp.positions {
            p[1] = (0.25_f32.powi(2) - p[0] * p[0] - p[2] * p[2]).sqrt();
        }
        state.collisions.clear();
        let mut app = LabApplication::new(None, None);
        app.document = Some(doc);
        app.cdmw_state = json!({"hair":{"available":true,"materials_ready":true},"replacement":{"comparison":"edit"}});
        app.hydrate_hair(Some(state.clone()));
        app.hair.pending_preset = false;
        let rect = egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(1920.0, 1080.0));
        app.viewport_rect = Some(rect);
        app.camera
            .set_standard_view(crate::camera::StandardView::Top);
        app.camera.frame_positions_in_viewport(
            state.scalp.positions.iter().copied().map(Vec3::from),
            rect,
        );
        app.run_hair_action(HairAction::Empty);
        await_hair(&mut app);
        app.hair.tool = Some(HairTool::Guide);
        let mut screen = Vec2::ZERO;
        for step in 0..17 {
            let x = if free {
                step as f32 * 0.008
            } else {
                -0.128 + step as f32 * 0.016
            };
            let p = Vec3::new(x, (0.25_f32.powi(2) - x * x).sqrt(), 0.0);
            screen = app.camera.project(p, rect).unwrap().screen;
            let event = if step == 0 {
                ViewportPointerEvent::PrimaryPressed(screen)
            } else {
                ViewportPointerEvent::PrimaryMoved(screen)
            };
            app.dispatch_hair_pointer(event, rect, free, false, false);
        }
        app.dispatch_hair_pointer(
            ViewportPointerEvent::PrimaryReleased(screen),
            rect,
            free,
            false,
            false,
        );
        await_hair(&mut app);
        let after = app.hair.state.as_ref().unwrap();
        assert_eq!(after.guides.len(), 1, "{}", app.hair.feedback);
        let guide = &after.guides[0];
        assert!(guide.points.len() > 8);
        assert!(
            Vec3::from(guide.points[0]).distance(after.scalp.point(&guide.root).unwrap()) < 1e-6
        );
        let scene = app.hair.scene.as_ref().unwrap();
        for p in guide.points.iter().skip(1).copied().map(Vec3::from) {
            let (surface, normal) = scene
                .scalp_picking
                .nearest(&after.scalp.positions, &scene.scalp_indices, p)
                .unwrap();
            assert!((p - surface).dot(normal) >= -0.0003, "stroke entered scalp");
        }
        let tip = Vec3::from(*guide.points.last().unwrap());
        let (surface, _) = scene
            .scalp_picking
            .nearest(&after.scalp.positions, &scene.scalp_indices, tip)
            .unwrap();
        if free {
            assert!(tip.distance(surface) > 0.025, "Ctrl did not lift the tip");
        } else {
            assert!(
                tip.distance(surface) < 0.012,
                "Draw did not follow the scalp"
            );
        }
        for p in &app.hair.preview.as_ref().unwrap().lods[0].submeshes[0].positions {
            let p = Vec3::from(*p);
            assert!(
                scene
                    .scalp_picking
                    .contact(&after.scalp.positions, &scene.scalp_indices, p, 0.0)
                    .distance(p)
                    < 0.0003,
                "generated follower card entered scalp: {p:?}"
            );
        }
    }
}

#[test]
fn hair_shaping_tools_change_rendered_hair_keep_roots_and_lengthen_only_tips() {
    for tool in [
        HairTool::Lengthen,
        HairTool::Smooth,
        HairTool::Comb,
        HairTool::Curl,
        HairTool::Clump,
    ] {
        let (mut app, rect) = ready_hair_app();
        let (point, id) = visible_lock(&app, rect);
        app.hair.tool = Some(tool);
        app.hair.radius = 100.0;
        assert!(
            app.hair.selected.is_empty(),
            "tools must work without a prior selection"
        );
        let before = app.hair.state.clone().unwrap();
        let frame = app.hair.scene.as_ref().unwrap().frame.positions.clone();
        app.dispatch_hair_pointer(
            ViewportPointerEvent::PrimaryPressed(point),
            rect,
            false,
            false,
            false,
        );
        app.dispatch_hair_pointer(
            ViewportPointerEvent::PrimaryMoved(point + Vec2::new(4.0, 2.0)),
            rect,
            false,
            false,
            false,
        );
        if tool == HairTool::Lengthen {
            assert_eq!(app.hair.selected, HashSet::from([id as usize]));
        }
        app.render_hair();
        assert_ne!(
            app.hair.scene.as_ref().unwrap().frame.positions,
            frame,
            "{tool:?} must affect production buffers"
        );
        let stroke = app.hair.stroke.as_ref().unwrap();
        for (a, b) in stroke.guides.iter().zip(&before.guides) {
            assert_eq!(a.points[0], b.points[0]);
        }
        if tool == HairTool::Lengthen {
            let gi = before
                .locks
                .iter()
                .find(|l| l.id == id)
                .unwrap()
                .guide
                .unwrap() as usize;
            let count = before.guides[gi].points.len();
            assert_eq!(
                stroke.guides[gi].points[..count - 1],
                before.guides[gi].points[..count - 1]
            );
            assert_ne!(
                stroke.guides[gi].points[count - 1],
                before.guides[gi].points[count - 1]
            );
        }
        app.dispatch_hair_pointer(
            ViewportPointerEvent::PrimaryReleased(point + Vec2::new(4.0, 2.0)),
            rect,
            false,
            false,
            false,
        );
        await_hair(&mut app);
        assert_eq!(
            app.hair.state.as_ref().unwrap().revision,
            before.revision + 1
        );
    }
}

#[test]
fn hair_stroke_escape_cancels_without_history_and_playback_resumes_same_pose() {
    let (mut app, rect) = ready_hair_app();
    app.hair.playing = true;
    for _ in 0..12 {
        app.hair.last_tick = Instant::now() - std::time::Duration::from_secs_f64(1.0 / 60.0);
        app.render_hair();
    }
    let elapsed = app.hair.simulation.as_ref().unwrap().elapsed;
    let (point, _) = visible_lock(&app, rect);
    app.hair.tool = Some(HairTool::Move);
    let before = app.hair.state.clone().unwrap();
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryPressed(point),
        rect,
        false,
        false,
        false,
    );
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryMoved(point + Vec2::X * 12.0),
        rect,
        false,
        false,
        false,
    );
    app.render_hair();
    assert!(!app.hair.playing);
    let context = app.egui_context.clone();
    let mut output = context.run_ui(
        egui::RawInput {
            events: vec![egui::Event::Key {
                key: egui::Key::Escape,
                physical_key: None,
                pressed: true,
                repeat: false,
                modifiers: Default::default(),
            }],
            ..Default::default()
        },
        |ui| {
            app.handle_hair_input(ui, rect);
        },
    );
    output.textures_delta.clear();
    assert_eq!(app.hair.state.as_ref().unwrap(), &before);
    assert!(app.hair.stroke.is_none());
    assert!(!app.hair.preparing());
    app.render_hair();
    let (point, _) = visible_lock(&app, rect);
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryPressed(point),
        rect,
        false,
        false,
        false,
    );
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryMoved(point + Vec2::X * 12.0),
        rect,
        false,
        false,
        false,
    );
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryReleased(point + Vec2::X * 12.0),
        rect,
        false,
        false,
        false,
    );
    await_hair(&mut app);
    assert!(app.hair.playing, "{}", app.hair.feedback);
    assert!(
        app.hair.simulation.as_ref().unwrap().elapsed >= elapsed,
        "Editing must not reset head/shoulder motion"
    );
}

#[test]
fn hair_acknowledgement_does_not_reset_selection_camera_or_newer_edits() {
    let (mut app, rect) = ready_hair_app();
    let (point, id) = visible_lock(&app, rect);
    let before = app.hair.state.clone().unwrap();
    let document = app.document.clone().unwrap();
    app.hair.selected.insert(id as usize);
    app.hair.inflight = Some(PreparedHair {
        state: before.clone(),
        document: document.clone(),
        label: "first".into(),
        milliseconds: 1.0,
    });
    app.hair.state.as_mut().unwrap().revision += 1;
    assert!(app.accept_hair_ack(before.revision + 9).is_err());
    assert!(app.hair.inflight.is_some());
    app.accept_hair_ack(before.revision).unwrap();
    assert_eq!(
        app.hair.state.as_ref().unwrap().revision,
        before.revision + 1
    );
    assert!(app.hair.selected.contains(&(id as usize)));
    assert_eq!(app.lock_at(point, rect).unwrap().0, id);
    assert_eq!(app.hair.acknowledged, Some((before, document)));
}

#[test]
fn hair_generated_legacy_locks_upgrade_without_regeneration_or_geometry_changes() {
    let (mut app, _) = ready_hair_app();
    let original = app.document.clone();
    let mut old = app.hair.state.clone().unwrap();
    old.locks.clear();
    old.prepared_parts.clear();
    old.revision = 9;
    app.hair = HairEditor::default();
    app.hydrate_hair(Some(old.clone()));
    app.poll_hair();
    assert_eq!(app.document, original);
    assert!(!app.hair.preparing());
    assert_eq!(app.hair.state.as_ref().unwrap().guides, old.guides);
    assert_eq!(
        app.hair.state.as_ref().unwrap().locks.len(),
        old.guides.len()
    );
    assert!(app.hair_motion_reason().is_ok());
}

#[test]
fn hair_history_requests_queue_behind_completed_strokes_without_merging_steps() {
    let (mut app, rect) = ready_hair_app();
    let (point, _) = visible_lock(&app, rect);
    app.hair.tool = Some(HairTool::Move);
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryPressed(point),
        rect,
        false,
        false,
        false,
    );
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryMoved(point + Vec2::X * 5.0),
        rect,
        false,
        false,
        false,
    );
    app.dispatch_hair_pointer(
        ViewportPointerEvent::PrimaryReleased(point + Vec2::X * 5.0),
        rect,
        false,
        false,
        false,
    );
    assert!(app.defer_hair_history(false));
    assert!(app.defer_hair_history(false));
    assert!(app.defer_hair_history(true));
    assert_eq!(
        app.hair.pending_history,
        VecDeque::from([false, false, true])
    );
    assert!(!app.hair_input_ready());
}

#[test]
fn hair_width_and_density_change_only_selected_visible_locks() {
    for existing in [false, true] {
        let (mut app, rect) = ready_hair_app();
        if existing {
            let state = app.hair.state.as_mut().unwrap();
            state.groups[0].mode = GroupMode::Existing;
            for lock in &mut state.locks {
                lock.kind = LockKind::Bound;
            }
        }
        let (_, id) = visible_lock(&app, rect);
        app.hair.selected = HashSet::from([id as usize]);
        let before = app.hair.state.clone().unwrap();
        let geometry = app.hair.scene.as_ref().unwrap().frame.positions.clone();
        app.hair.width = before.groups[0].width * 1.7;
        app.hair.density = 3;
        app.run_hair_action(HairAction::Settings);
        await_hair(&mut app);
        let after = app.hair.state.as_ref().unwrap();
        assert_eq!(
            after.guides, before.guides,
            "Width never moves roots or guides"
        );
        for lock in &after.locks {
            let old = before.locks.iter().find(|l| l.id == lock.id).unwrap();
            if lock.id == id {
                assert!((lock.width_scale - 1.7).abs() < 0.001);
                assert_eq!(lock.cards, if existing { old.cards } else { 3 });
            } else {
                assert_eq!(lock.width_scale, old.width_scale);
                assert_eq!(lock.cards, old.cards);
            }
        }
        assert_ne!(app.hair.scene.as_ref().unwrap().frame.positions, geometry);
    }
}

#[test]
fn hair_brush_strength_depends_on_stroke_distance_not_event_count() {
    for tool in [HairTool::Smooth, HairTool::Curl, HairTool::Clump] {
        let stroke = |steps: u32| {
            let (mut app, rect) = ready_hair_app();
            let (point, id) = visible_lock(&app, rect);
            app.hair.selected = HashSet::from([id as usize]);
            app.hair.radius = 160.0;
            app.hair.tool = Some(tool);
            app.dispatch_hair_pointer(
                ViewportPointerEvent::PrimaryPressed(point),
                rect,
                false,
                false,
                false,
            );
            for step in 1..=steps {
                app.dispatch_hair_pointer(
                    ViewportPointerEvent::PrimaryMoved(
                        point + Vec2::new(3.0 * step as f32 / steps as f32, 0.0),
                    ),
                    rect,
                    false,
                    false,
                    false,
                );
            }
            app.hair.stroke.clone().unwrap().guides
        };
        let one = stroke(1);
        let many = stroke(12);
        let error = one
            .iter()
            .zip(many)
            .flat_map(|(a, b)| {
                a.points
                    .iter()
                    .zip(b.points)
                    .map(|(p, q)| Vec3::from(*p).distance(Vec3::from(q)))
                    .collect::<Vec<_>>()
            })
            .fold(0.0_f32, f32::max);
        assert!(
            error < 1.0e-5,
            "{tool:?} event frequency changed the stroke by {error}"
        );
    }
}
