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
        version: 1,
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
    assert!(
        prepare(
            state.clone(),
            doc,
            "fill".into(),
            Preparation::Fill(0, Preset::Bob, 0.3),
            &AtomicBool::new(true)
        )
        .is_err()
    );
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
    assert!(
        state
            .rebind_cancellable(state.scalp.clone(), &AtomicBool::new(true))
            .is_err()
    );
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

/// Explicit licensed/offscreen probe. No archive writes; outputs stay under the
/// caller's temporary evidence directory. Optional input is the real host handoff.
#[test]
#[ignore = "requires an authorized DX12 GPU and temporary evidence directory"]
fn hair_production_render_and_benchmark() {
    let root =
        PathBuf::from(std::env::var("CDMW_HAIR_PROBE_OUTPUT").expect("temporary output directory"));
    std::fs::create_dir_all(&root).unwrap();
    let input: Option<Value> = std::env::var("CDMW_HAIR_PROBE_INPUT")
        .ok()
        .map(|path| serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap());
    let (mut state, document) = if let Some(input) = &input {
        (
            serde_json::from_value(input["hair"].clone()).unwrap(),
            serde_json::from_value(input["document"].clone()).unwrap(),
        )
    } else {
        fixture()
    };
    let existing = state.groups[0].mode == GroupMode::Existing;
    let span = (hair_bounds(&state).1 - hair_bounds(&state).0).max_element();
    state.revision += 1;
    let mut result = prepare(
        state,
        document,
        "preset".into(),
        Preparation::Fill(0, Preset::Bob, span * 0.75),
        &AtomicBool::new(false),
    )
    .unwrap();
    if existing {
        result = prepare(
            result.state,
            result.document,
            "bind".into(),
            Preparation::Bind(0),
            &AtomicBool::new(false),
        )
        .unwrap();
        let selected: Vec<_> = (0..result.state.guides.len()).collect();
        hair::groom(
            &mut result.state,
            &selected,
            Groom::Comb,
            0.5,
            [span * 0.25, span * 0.08, 0.0],
            false,
        )
        .unwrap();
        result = prepare(
            result.state,
            result.document,
            "reshape".into(),
            Preparation::Generate,
            &AtomicBool::new(false),
        )
        .unwrap();
    }
    let candidate = json!({"hair": result.state, "submeshes": result.document.lods[0].submeshes});
    std::fs::write(
        root.join("candidate.json"),
        serde_json::to_vec(&candidate).unwrap(),
    )
    .unwrap();
    let mut scene = build_scene(&result.document, &result.state, true, None, 1);
    let mut sim = Simulation::new(&result.state).unwrap();
    let rest = scene.frame.positions.clone();
    let texture_bytes: Vec<Vec<u8>> = input
        .as_ref()
        .and_then(|v| v["textures"].as_array())
        .map(|rows| {
            rows.iter()
                .map(|r| std::fs::read(r["path"].as_str().unwrap()).unwrap())
                .collect()
        })
        .unwrap_or_else(|| vec![cdmw_texture::synthetic::rgba8_checker_dds()]);
    let ownership: Vec<Vec<Vec<u32>>> = input
        .as_ref()
        .and_then(|v| v["textures"].as_array())
        .map(|rows| {
            rows.iter()
                .map(|r| vec![serde_json::from_value(r["parts"].clone()).unwrap()])
                .collect()
        })
        .unwrap_or_else(|| vec![vec![vec![0]]]);
    let roles: Vec<cdmw_texture::TextureRole> = input
        .as_ref()
        .and_then(|v| v["textures"].as_array())
        .map(|rows| {
            rows.iter()
                .map(|r| serde_json::from_value(r["role"].clone()).unwrap())
                .collect()
        })
        .unwrap_or_else(|| vec![cdmw_texture::TextureRole::BaseColor]);
    let textures: Vec<_> = texture_bytes
        .iter()
        .zip(&ownership)
        .zip(&roles)
        .map(|((bytes, owner), role)| HeadlessMaterialTexture {
            bytes,
            role: *role,
            material_indices_by_lod: owner,
        })
        .collect();
    let factor_owner =
        vec![(0..result.document.lods[0].submeshes.len() as u32).collect::<Vec<_>>()];
    let factors = [HeadlessMaterialFactors {
        factors: MaterialPreviewFactors {
            alpha_cutoff: Some(0.5),
            ..Default::default()
        },
        material_indices_by_lod: &factor_owner,
    }];
    let textured = root.join("textured.bmp");
    let base = root.join("base.bmp");
    let ids = root.join("parts.bmp");
    let normal = root.join("normals.bmp");
    let request = HeadlessMaterialCaptureRequest {
        options: HeadlessMaterialCaptureOptions {
            width: 1920,
            height: 1080,
            ..Default::default()
        },
        output: HeadlessMaterialCaptureOutput {
            textured_bmp: &textured,
            base_color_bmp: &base,
            part_id_bmp: &ids,
            normal_map: Some(&normal),
            material_response: None,
            layer_mask: None,
        },
    };
    let rest_textured = root.join("rest-textured.bmp");
    let rest_base = root.join("rest-base.bmp");
    let rest_ids = root.join("rest-parts.bmp");
    pollster::block_on(run_headless_material_capture(
        &scene.frame,
        &textures,
        &factors,
        request.options,
        HeadlessMaterialCaptureOutput {
            textured_bmp: &rest_textured,
            base_color_bmp: &rest_base,
            part_id_bmp: &rest_ids,
            normal_map: None,
            material_response: None,
            layer_mask: None,
        },
    ))
    .unwrap();
    let mut callback = |frame: &mut DrawSnapshot| {
        let rotation = Quat::from_rotation_y((sim.elapsed as f32 * 1.5).sin() * 0.3);
        sim.advance(
            1.0 / 60.0,
            MotionSettings::default(),
            &result.state.collisions,
            rotation,
        )
        .unwrap();
        for (part, first, count, indices) in &scene.parts {
            hair::deform(
                &result.state.bindings,
                &sim.points,
                *part,
                &mut frame.positions[*first..first + count],
            )
            .unwrap();
            normals_into(
                &frame.positions[*first..first + count],
                indices,
                &mut frame.normals[*first..first + count],
            );
        }
        for i in scene.reference_start..scene.reference_start + result.state.scalp.positions.len() {
            frame.positions[i] =
                (sim.pivot + rotation * (Vec3::from(rest[i]) - sim.pivot)).to_array();
        }
        Ok(())
    };
    let (report, timings) = pollster::block_on(run_headless_motion_capture(
        &scene.frame,
        &textures,
        &factors,
        request,
        180,
        &mut callback,
    ))
    .unwrap();
    let mut grooming = vec![];
    let selected: Vec<_> = (0..result.state.guides.len()).collect();
    for _ in 0..60 {
        let start = Instant::now();
        let mut stroke = result.state.clone();
        hair::groom(
            &mut stroke,
            &selected,
            Groom::Comb,
            0.1,
            [span * 0.01, 0.0, 0.0],
            true,
        )
        .unwrap();
        let points: Vec<_> = stroke.guides.iter().map(|g| g.points.clone()).collect();
        for (part, first, count, indices) in &scene.parts {
            hair::deform(
                &stroke.bindings,
                &points,
                *part,
                &mut scene.frame.positions[*first..first + count],
            )
            .unwrap();
            normals_into(
                &scene.frame.positions[*first..first + count],
                indices,
                &mut scene.frame.normals[*first..first + count],
            );
        }
        grooming.push(start.elapsed().as_secs_f64() * 1000.0);
    }
    fn p95(mut values: Vec<f64>) -> f64 {
        values.sort_by(f64::total_cmp);
        values[(values.len() * 95 / 100).min(values.len() - 1)]
    }
    let mean = timings.iter().map(|v| v[1]).sum::<f64>() / timings.len() as f64;
    let stats = json!({"adapter":format!("{:?}",report.adapter),"resolution":[1920,1080],"guides":result.state.guides.len(),"points_per_guide":16,
        "hair_vertices":scene.reference_start,"frames":timings.len(),"mean_frame_ms":mean,"offscreen_fps":1000.0/mean,
        "frame_p95_ms":p95(timings.iter().map(|v|v[1]).collect()),"cpu_sim_deform_p95_ms":p95(timings.iter().map(|v|v[0]).collect()),
        "grooming_p95_ms":p95(grooming.clone()),"textured_pixels":report.textured.non_background_pixels,"textures":report.dds_textures_uploaded,
        "real_game_verified":false,"measurement":"production offscreen DX12, CPU deformation and synchronous readback; excludes Qt and desktop presentation"});
    std::fs::write(
        root.join("benchmark.json"),
        serde_json::to_vec_pretty(&stats).unwrap(),
    )
    .unwrap();
    println!("{stats}");
    assert_ne!(
        sim.points,
        result
            .state
            .guides
            .iter()
            .map(|g| g.points.clone())
            .collect::<Vec<_>>()
    );
    assert!(1000.0 / mean >= 30.0, "offscreen minimum FPS missed");
    assert!(p95(grooming) < 100.0, "grooming feedback budget missed");
}
