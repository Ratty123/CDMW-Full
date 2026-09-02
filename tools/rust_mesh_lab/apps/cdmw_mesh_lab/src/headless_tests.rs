use super::*;
use cdmw_formats::{MeshDocument, MeshFormat, MeshLod, SourceRange, Submesh, decode_mesh};
use cdmw_interaction::{OperatorState, ProjectedHandle};
use sha2::{Digest, Sha256};
use tempfile::tempdir;

pub(super) type TestResult = Result<(), Box<dyn std::error::Error>>;

pub(super) fn viewport() -> egui::Rect {
    egui::Rect::from_min_size(egui::pos2(0.0, 0.0), egui::vec2(800.0, 600.0))
}

pub(super) fn triangle_application() -> Result<LabApplication, Box<dyn std::error::Error>> {
    let document = decode_mesh(
        &cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
        MeshFormat::Pam,
    )?;
    let mesh = WorkingMesh::from_document(&document)?;
    let mut application = LabApplication::new(None, None);
    application.document = Some(document);
    application.mesh = Some(mesh);
    application.source_label = "headless synthetic triangle".to_owned();
    application.update_viewport_rect(viewport());
    application
        .camera
        .frame_all(application.mesh.as_ref().ok_or("missing working mesh")?);
    Ok(application)
}

pub(super) fn symmetry_application() -> Result<LabApplication, Box<dyn std::error::Error>> {
    let positions = vec![
        [-1.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [2.0, 2.0, 0.0],
    ];
    let document = MeshDocument {
        format: MeshFormat::Pam,
        source_sha256: String::new(),
        parser: "headless-symmetry".to_owned(),
        lod_count_reported: 1,
        lods: vec![MeshLod {
            level: 0,
            submeshes: vec![Submesh {
                name: "symmetric".to_owned(),
                material: "symmetric-material".to_owned(),
                normals: vec![[0.0, 0.0, 1.0]; positions.len()],
                uvs: vec![[0.0, 0.0]; positions.len()],
                source_vertex_indices: vec![0, 1, 2, 3],
                positions,
                indices: vec![0, 1, 2],
                source_range: SourceRange {
                    offset: 0,
                    length: 0,
                },
                vertex_stride: 0,
                layout: "headless-symmetry".to_owned(),
            }],
        }],
        warnings: Vec::new(),
        structural_fingerprint: String::new(),
    };
    let mesh = WorkingMesh::from_document(&document)?;
    let mut application = LabApplication::new(None, None);
    application.document = Some(document);
    application.mesh = Some(mesh);
    application.source_label = "headless symmetric mesh".to_owned();
    application.update_viewport_rect(viewport());
    application
        .camera
        .frame_all(application.mesh.as_ref().ok_or("missing symmetric mesh")?);
    Ok(application)
}

pub(super) fn two_lod_application() -> Result<LabApplication, Box<dyn std::error::Error>> {
    let document = decode_mesh(&cdmw_formats::synthetic::two_lod_pac(), MeshFormat::Pac)?;
    let cancellation = cdmw_archive::CancellationToken::default();
    let mut meshes = crate::loader::build_lod_meshes(&document, &cancellation)?.into_iter();
    let mesh = meshes.next().ok_or("missing LOD0 working mesh")?;
    let mut application = LabApplication::new(None, None);
    application.install_loaded_mesh(LoadedMesh {
        path: PathBuf::from("headless-two-lod.pac"),
        document,
        mesh,
        other_lod_meshes: meshes.collect(),
        textures: Vec::new(),
        material_parameters: Vec::new(),
        material_factors: Vec::new(),
        skeleton: None,
    });
    application.update_viewport_rect(viewport());
    Ok(application)
}

fn cdmw_state_with_document(
    root: &Path,
    session_id: &str,
    revision: u64,
    document: &MeshDocument,
) -> Result<Value, Box<dyn std::error::Error>> {
    let name = format!("state-{revision}.json");
    let bytes = serde_json::to_vec(document)?;
    fs::write(root.join(&name), &bytes)?;
    Ok(json!({
        "session_id": session_id,
        "base_revision": revision,
        "selection": {
            "vertices_by_submesh": {},
            "edges_by_submesh": {},
            "faces_by_submesh": {},
            "source_indices": []
        },
        "document": {
            "path": name,
            "data_type": "mesh_document_json",
            "count": 1,
            "byte_length": bytes.len(),
            "sha256": format!("{:X}", Sha256::digest(&bytes)),
            "content_type": "application/json"
        }
    }))
}

pub(super) fn projected_domain_point(
    application: &mut LabApplication,
    domain: SelectionDomain,
) -> Result<Vec2, Box<dyn std::error::Error>> {
    if !application.ensure_projection(viewport()) {
        return Err("projection was not built".into());
    }
    application
        .projection
        .as_ref()
        .ok_or("missing projection")?
        .interaction
        .elements
        .iter()
        .find_map(|element| {
            let matches = matches!(
                (domain, element.handle),
                (SelectionDomain::Vertex, ProjectedHandle::Vertex(_))
                    | (SelectionDomain::Edge, ProjectedHandle::Edge(_))
                    | (SelectionDomain::Face, ProjectedHandle::Face(_))
            );
            matches.then_some(element.position)
        })
        .ok_or_else(|| "missing projected element for selection domain".into())
}

#[test]
fn capture_cli_is_isolated_and_derives_all_machine_readable_outputs() -> TestResult {
    let options = parse_startup_options_from(
        [
            "--capture-cdmw-session",
            "owned/session/manifest.json",
            "--capture-output",
            "proof/sword.bmp",
        ]
        .into_iter()
        .map(str::to_owned),
    )?;
    assert_eq!(
        options.capture_cdmw_session,
        Some(PathBuf::from("owned/session/manifest.json"))
    );
    assert_eq!(
        options.capture_output,
        Some(PathBuf::from("proof/sword.bmp"))
    );
    let paths = cdmw_capture_paths(
        options.capture_output.as_deref().ok_or("capture output")?,
        None,
    )?;
    assert_eq!(paths.textured, PathBuf::from("proof/sword.bmp"));
    assert_eq!(
        paths.base_color,
        PathBuf::from("proof/sword-base-color.bmp")
    );
    assert_eq!(paths.part_id, PathBuf::from("proof/sword-part-id.bmp"));
    assert_eq!(paths.report, PathBuf::from("proof/sword-report.json"));

    assert!(
        parse_startup_options_from(
            ["--capture-cdmw-session", "manifest.json"]
                .into_iter()
                .map(str::to_owned)
        )
        .is_err()
    );
    assert!(
        parse_startup_options_from(
            [
                "--capture-cdmw-session",
                "manifest.json",
                "--capture-output",
                "proof.bmp",
                "--mesh",
                "other.pac",
            ]
            .into_iter()
            .map(str::to_owned)
        )
        .is_err()
    );
    assert!(
        cdmw_capture_paths(Path::new("proof.bmp"), Some(Path::new("proof-report.bmp"))).is_err()
    );
    Ok(())
}

#[test]
fn capture_outputs_are_distinct_external_noclobber_publications() -> TestResult {
    let root = tempdir()?;
    let session_root = root.path().join("session");
    fs::create_dir(&session_root)?;

    let inside = cdmw_capture_paths(&session_root.join("inside.bmp"), None)?;
    assert!(validated_cdmw_capture_paths(&inside, &session_root).is_err());

    let requested = cdmw_capture_paths(&root.path().join("proof/sword.bmp"), None)?;
    let mut aliased = requested.clone();
    aliased.report = aliased.textured.clone();
    assert!(validated_cdmw_capture_paths(&aliased, &session_root).is_err());

    let validated = validated_cdmw_capture_paths(&requested, &session_root)?;
    let canonical_session = fs::canonicalize(&session_root)?;
    assert!(
        validated
            .iter()
            .all(|path| !path.starts_with(&canonical_session))
    );
    let publication = CdmwCapturePublication::reserve(validated.clone())?;
    for (index, temporary) in publication.temporary_paths.iter().enumerate() {
        fs::write(temporary, format!("owned-{index}"))?;
    }
    let published = publication.publish()?;
    for (index, path) in published.iter().enumerate() {
        assert_eq!(fs::read_to_string(path)?, format!("owned-{index}"));
    }
    assert!(CdmwCapturePublication::reserve(validated).is_err());
    Ok(())
}

fn run_selection_gesture(
    application: &mut LabApplication,
    domain: SelectionDomain,
    tool: SelectionTool,
) -> TestResult {
    application.viewport_tool = ViewportTool::Select;
    application.selection_domain = domain;
    application.selection_tool = tool;
    application.selection_operation = SelectionOperation::Replace;
    application.selection_visible_only = false;
    application.brush_radius = 24.0;
    let center = projected_domain_point(application, domain)?;
    let start = center + Vec2::new(-12.0, -12.0);
    match tool {
        SelectionTool::Click => application.begin_primary_gesture(viewport(), center),
        SelectionTool::Brush => {
            application.begin_primary_gesture(viewport(), center);
            application.update_primary_gesture(viewport(), center + Vec2::new(2.0, 0.0), true);
        }
        SelectionTool::Rectangle => {
            application.begin_primary_gesture(viewport(), start);
            application.update_primary_gesture(viewport(), center + Vec2::new(12.0, 12.0), true);
        }
        SelectionTool::Lasso => {
            application.begin_primary_gesture(viewport(), start);
            for point in [
                center + Vec2::new(12.0, -12.0),
                center + Vec2::new(12.0, 12.0),
                center + Vec2::new(-12.0, 12.0),
            ] {
                application.update_primary_gesture(viewport(), point, false);
            }
            application.update_primary_gesture(viewport(), start, true);
        }
    }
    if application.selection_gesture.is_none() {
        return Err(format!("{domain:?} {tool:?} did not start").into());
    }
    application.finish_primary_gesture();
    let selection = &application.mesh.as_ref().ok_or("missing mesh")?.selection;
    let selected = match domain {
        SelectionDomain::Vertex => selection.vertices.len(),
        SelectionDomain::Edge => selection.edges.len(),
        SelectionDomain::Face => selection.faces.len(),
    };
    if selected == 0 {
        return Err(format!("{domain:?} {tool:?} selected nothing").into());
    }
    if application.history.undo_len() != 1 {
        return Err(format!("{domain:?} {tool:?} did not create one history entry").into());
    }
    application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .validate()?;
    Ok(())
}

#[test]
fn integrated_layer_state_filters_render_snapshot_and_selection_projection() -> TestResult {
    let root = tempdir()?;
    let mut document = decode_mesh(
        &cdmw_formats::synthetic::triangle_pam("visible.dds"),
        MeshFormat::Pam,
    )?;
    let mut hidden = document.lods[0].submeshes[0].clone();
    hidden.name = "hidden".to_owned();
    for position in &mut hidden.positions {
        position[0] += 10.0;
    }
    document.lods[0].submeshes.push(hidden);
    let mesh = WorkingMesh::from_document(&document)?;
    let mut application = LabApplication::new(None, None);
    application.document = Some(document);
    application.mesh = Some(mesh);
    application.cdmw_bridge = Some(CdmwBridge::for_test(
        root.path().to_path_buf(),
        "layer-mask-session",
        1,
        0,
    ));
    application.cdmw_state = json!({
        "geometry_layers": {
            "revision": 3,
            "active_layer_id": "base",
            "layers": [
                {"layer_id": "base", "submesh_indices": [0], "visible": true, "base": true},
                {"layer_id": "detail", "submesh_indices": [1], "visible": false, "base": false}
            ]
        }
    });
    application.update_viewport_rect(viewport());
    application
        .camera
        .frame_all(application.mesh.as_ref().ok_or("mesh")?);

    let visible = application
        .cdmw_visible_submeshes()
        .ok_or("validated layer mask")?;
    assert_eq!(visible, HashSet::from([0]));
    let mesh = application.mesh.as_ref().ok_or("mesh")?;
    let allowed = mesh.element_handles_for_submeshes(&visible);
    let snapshot = mesh.draw_snapshot_for_submeshes(&visible);
    assert_eq!(snapshot.positions.len(), 3);
    assert_eq!(snapshot.indices.len(), 3);

    assert!(application.ensure_projection(viewport()));
    let projection = application.projection.as_ref().ok_or("projection")?;
    assert_eq!(projection.vertices.len(), 3);
    assert!(
        projection
            .interaction
            .elements
            .iter()
            .all(|element| match element.handle {
                ProjectedHandle::Vertex(handle) => allowed.vertices.contains(&handle),
                ProjectedHandle::Edge(handle) => allowed.edges.contains(&handle),
                ProjectedHandle::Face(handle) => allowed.faces.contains(&handle),
            })
    );
    application.run_selection_command(
        "Select visible faces",
        SelectionDomain::Face,
        SelectionCommand::SelectAll,
    );
    let selected = &application.mesh.as_ref().ok_or("mesh")?.selection.faces;
    assert_eq!(selected, &allowed.faces);
    Ok(())
}

#[test]
fn integrated_bone_overlay_parser_rejects_truncation_and_parent_cycles() -> TestResult {
    let mut state = json!({
        "skeleton": {
            "available": true,
            "bone_count": 2,
            "skeleton_bone_count": 2,
            "bones_truncated": false,
            "skeleton_parse_warning": "",
            "bones": [
                {"index": 0, "parent_index": -1, "position": [0.0, 0.0, 0.0]},
                {"index": 1, "parent_index": 0, "position": [0.0, 1.0, 0.0]}
            ]
        }
    });
    let overlay = parse_cdmw_skeleton_overlay(&state).map_err(std::io::Error::other)?;
    assert_eq!(overlay.bone_count, 2);
    assert_eq!(overlay.lines, vec![[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]]);

    state["skeleton"]["bones_truncated"] = json!(true);
    assert!(parse_cdmw_skeleton_overlay(&state).is_err_and(|reason| reason.contains("truncated")));
    state["skeleton"]["bones_truncated"] = json!(false);
    state["skeleton"]["bones"][0]["parent_index"] = json!(1);
    state["skeleton"]["bones"][1]["parent_index"] = json!(0);
    assert!(
        parse_cdmw_skeleton_overlay(&state)
            .is_err_and(|reason| reason.contains("cycle") || reason.contains("root"))
    );
    Ok(())
}

#[test]
fn pending_cdmw_result_blocks_edit_actions_but_keeps_camera_navigation_available() -> TestResult {
    let root = tempdir()?;
    let mut application = triangle_application()?;
    application.cdmw_bridge = Some(CdmwBridge::for_test(
        root.path().to_path_buf(),
        "pending-session",
        1,
        0,
    ));
    application.cdmw_pending_request = Some(CdmwPendingRequest {
        request_id: 3,
        event: "command_result",
        label: "Slow topology".to_owned(),
        origin: None,
    });
    let baseline = application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .structural_fingerprint();
    application.handle_actions(vec![UiAction::SelectAllVertices, UiAction::Nudge(Vec3::X)]);
    let mesh = application.mesh.as_ref().ok_or("mesh")?;
    assert_eq!(mesh.structural_fingerprint(), baseline);
    assert!(mesh.selection.vertices.is_empty());
    assert!(application.cdmw_pending_request.is_some());

    let camera_revision = application.camera.revision();
    application.handle_actions(vec![UiAction::OrbitYaw(15.0)]);
    assert!(application.camera.revision() > camera_revision);
    assert!(application.cdmw_pending_request.is_some());
    Ok(())
}

#[test]
fn matched_rejection_restores_host_document_before_clearing_pending_request() -> TestResult {
    let root = tempdir()?;
    let root_path = root.path().to_path_buf();
    let mut application = triangle_application()?;
    let authoritative = application.document.clone().ok_or("document")?;
    let mut local_edit = authoritative.clone();
    local_edit.lods[0].submeshes[0].positions[0] = [42.0, 0.0, 0.0];
    application.install_cdmw_document(local_edit)?;
    assert_eq!(
        application.document.as_ref().ok_or("local document")?.lods[0].submeshes[0].positions[0],
        [42.0, 0.0, 0.0]
    );
    application.cdmw_bridge = Some(CdmwBridge::for_test(
        root_path.clone(),
        "recovery-session",
        4,
        0,
    ));
    application.cdmw_pending_request = Some(CdmwPendingRequest {
        request_id: 7,
        event: "transaction_result",
        label: "Rust Inflate".to_owned(),
        origin: None,
    });
    let state = cdmw_state_with_document(&root_path, "recovery-session", 0, &authoritative)?;

    application.handle_cdmw_result(
        "transaction_result",
        7,
        0,
        false,
        json!({"state": state}),
        "exact output validation failed",
    );

    assert_eq!(
        application
            .document
            .as_ref()
            .ok_or("recovered document")?
            .lods[0]
            .submeshes[0]
            .positions[0],
        authoritative.lods[0].submeshes[0].positions[0]
    );
    assert!(application.cdmw_pending_request.is_none());
    assert_eq!(
        application
            .cdmw_bridge
            .as_ref()
            .ok_or("bridge")?
            .shadow_revision(),
        0
    );
    assert_eq!(
        application.status,
        "Rust Inflate rejected: exact output validation failed"
    );
    assert!(!application.cdmw_exit_requested);
    Ok(())
}

#[test]
fn successful_noop_result_surfaces_the_host_diagnostic_instead_of_claiming_completion() -> TestResult
{
    let root = tempdir()?;
    let mut application = triangle_application()?;
    let document = application.document.clone().ok_or("document")?;
    application.cdmw_bridge = Some(CdmwBridge::for_test(
        root.path().to_path_buf(),
        "noop-session",
        2,
        0,
    ));
    application.cdmw_pending_request = Some(CdmwPendingRequest {
        request_id: 8,
        event: "command_result",
        label: "Generate Tangents".to_owned(),
        origin: Some(CdmwRequestOrigin::Normals),
    });
    let state = cdmw_state_with_document(root.path(), "noop-session", 0, &document)?;

    application.handle_cdmw_result(
        "command_result",
        8,
        0,
        true,
        json!({
            "result": {
                "status": "noop",
                "diagnostics": ["Complete UV0 rows are required."]
            },
            "state": state
        }),
        "",
    );

    assert_eq!(
        application.status,
        "Generate Tangents made no change: Complete UV0 rows are required."
    );
    assert_eq!(
        application.cdmw_normals_feedback.as_deref(),
        Some("Generate Tangents made no change: Complete UV0 rows are required.")
    );
    assert!(application.cdmw_pending_request.is_none());
    Ok(())
}

#[test]
fn page_feedback_uses_the_typed_request_origin_instead_of_status_words() -> TestResult {
    for (index, label, origin, normal_feedback) in [
        (0, "Sharpen Edges", CdmwRequestOrigin::Normals, true),
        (1, "Flip U", CdmwRequestOrigin::Uv, false),
        (2, "Planar Project", CdmwRequestOrigin::Uv, false),
    ] {
        let root = tempdir()?;
        let mut application = triangle_application()?;
        let document = application.document.clone().ok_or("document")?;
        let session_id = format!("page-feedback-{index}");
        application.cdmw_bridge = Some(CdmwBridge::for_test(
            root.path().to_path_buf(),
            &session_id,
            2,
            0,
        ));
        application.cdmw_pending_request = Some(CdmwPendingRequest {
            request_id: 40 + index,
            event: "command_result",
            label: label.to_owned(),
            origin: Some(origin),
        });
        let state = cdmw_state_with_document(root.path(), &session_id, 0, &document)?;
        application.handle_cdmw_result(
            "command_result",
            40 + index,
            0,
            true,
            json!({"state": state}),
            "",
        );

        let expected = format!("{label} completed · shadow revision 0");
        if normal_feedback {
            assert_eq!(
                application.cdmw_normals_feedback.as_deref(),
                Some(expected.as_str())
            );
            assert!(application.cdmw_uv_feedback.is_none());
        } else {
            assert_eq!(
                application.cdmw_uv_feedback.as_deref(),
                Some(expected.as_str())
            );
            assert!(application.cdmw_normals_feedback.is_none());
        }
    }
    Ok(())
}

#[test]
fn request_origin_comes_from_the_typed_tool_identifier() {
    assert_eq!(
        cdmw_request_origin(
            "mesh_action",
            &json!({"action": "sharpen_normals", "label": "Sharpen Edges"})
        ),
        Some(CdmwRequestOrigin::Normals)
    );
    assert_eq!(
        cdmw_request_origin(
            "mesh_action",
            &json!({"action": "uv_transform", "label": "Planar Project"})
        ),
        Some(CdmwRequestOrigin::Uv)
    );
}

#[test]
fn morph_slider_coalesces_drag_samples_and_submits_the_release_value() {
    let mut drafts = HashMap::new();
    assert_eq!(
        stage_cdmw_morph_value(&mut drafts, "waist", 10.0, true, true, false),
        None
    );
    assert_eq!(
        stage_cdmw_morph_value(&mut drafts, "waist", 55.0, true, true, false),
        None
    );
    assert_eq!(drafts.get("waist"), Some(&55.0));
    assert_eq!(
        stage_cdmw_morph_value(&mut drafts, "waist", 55.0, false, false, true),
        Some(55.0)
    );
    assert_eq!(
        stage_cdmw_morph_value(&mut drafts, "height", 12.0, true, false, false),
        Some(12.0),
        "non-interactive value changes commit immediately"
    );
    assert_eq!(
        stage_cdmw_morph_value(&mut drafts, "height", 30.0, true, true, false),
        None,
        "focused text edits must wait for their final value"
    );
    assert_eq!(
        stage_cdmw_morph_value(&mut drafts, "height", 30.0, false, false, true),
        Some(30.0),
        "losing focus submits the final text-edited value"
    );
}

#[test]
fn successful_transaction_surfaces_post_edit_channel_guidance() -> TestResult {
    let root = tempdir()?;
    let mut application = triangle_application()?;
    let document = application.document.clone().ok_or("document")?;
    application.cdmw_bridge = Some(CdmwBridge::for_test(
        root.path().to_path_buf(),
        "feedback-session",
        3,
        0,
    ));
    application.cdmw_pending_request = Some(CdmwPendingRequest {
        request_id: 9,
        event: "transaction_result",
        label: "Rust Inflate".to_owned(),
        origin: None,
    });
    let mut state = cdmw_state_with_document(root.path(), "feedback-session", 1, &document)?;
    state["operation_feedback"] = json!({
        "status": "ok",
        "diagnostics": ["Invalidated tangents; run Generate Tangents before export."]
    });

    application.handle_cdmw_result("transaction_result", 9, 1, true, state, "");

    assert_eq!(
        application.status,
        "Rust Inflate completed · Invalidated tangents; run Generate Tangents before export. · shadow revision 1"
    );
    assert_eq!(
        application
            .cdmw_bridge
            .as_ref()
            .ok_or("bridge")?
            .shadow_revision(),
        1
    );
    Ok(())
}

#[test]
fn mismatched_result_leaves_local_document_pending_and_revision_unchanged() -> TestResult {
    let root = tempdir()?;
    let root_path = root.path().to_path_buf();
    let mut application = triangle_application()?;
    let authoritative = application.document.clone().ok_or("document")?;
    let mut local_edit = authoritative.clone();
    local_edit.lods[0].submeshes[0].positions[0] = [13.0, 0.0, 0.0];
    application.install_cdmw_document(local_edit)?;
    application.cdmw_bridge = Some(CdmwBridge::for_test(
        root_path.clone(),
        "mismatch-session",
        8,
        0,
    ));
    application.cdmw_pending_request = Some(CdmwPendingRequest {
        request_id: 20,
        event: "command_result",
        label: "Undo".to_owned(),
        origin: None,
    });
    let state = cdmw_state_with_document(&root_path, "mismatch-session", 1, &authoritative)?;

    application.handle_cdmw_result(
        "command_result",
        21,
        1,
        false,
        json!({"state": state}),
        "stale response",
    );

    assert_eq!(
        application.document.as_ref().ok_or("local document")?.lods[0].submeshes[0].positions[0],
        [13.0, 0.0, 0.0]
    );
    assert_eq!(
        application
            .cdmw_bridge
            .as_ref()
            .ok_or("bridge")?
            .shadow_revision(),
        0
    );
    assert_eq!(
        application
            .cdmw_pending_request
            .as_ref()
            .ok_or("pending")?
            .request_id,
        20
    );
    assert!(application.cdmw_exit_requested);
    Ok(())
}

#[test]
fn unsolicited_state_snapshot_cannot_overtake_a_pending_request() -> TestResult {
    let root = tempdir()?;
    let mut application = triangle_application()?;
    application.cdmw_bridge = Some(CdmwBridge::for_test(
        root.path().to_path_buf(),
        "snapshot-session",
        2,
        0,
    ));
    application.cdmw_pending_request = Some(CdmwPendingRequest {
        request_id: 2,
        event: "command_result",
        label: "Undo".to_owned(),
        origin: None,
    });

    application.handle_cdmw_host_event(HostEvent::StateSnapshot(json!({
        "session_id": "snapshot-session",
        "base_revision": 1
    })));

    assert_eq!(
        application
            .cdmw_bridge
            .as_ref()
            .ok_or("bridge")?
            .shadow_revision(),
        0
    );
    assert!(application.cdmw_pending_request.is_some());
    assert!(application.cdmw_exit_requested);
    Ok(())
}

#[test]
fn headless_ui_frame_builds_the_complete_app_without_a_window() -> TestResult {
    let mut application = triangle_application()?;
    let context = application.egui_context.clone();
    let input = egui::RawInput {
        screen_rect: Some(egui::Rect::from_min_size(
            egui::Pos2::ZERO,
            egui::vec2(1_440.0, 900.0),
        )),
        ..Default::default()
    };
    let mut output = context.run_ui(input, |ui| {
        let actions = application.draw_ui(ui);
        application.handle_actions(actions);
    });
    assert!(!output.shapes.is_empty());
    assert!(application.viewport_rect.is_some());
    assert!(application.window.is_none());
    assert!(application.renderer.is_none());
    output.textures_delta.clear();
    Ok(())
}

#[test]
fn decoded_lods_switch_headlessly_and_preserve_independent_edit_history() -> TestResult {
    let mut application = two_lod_application()?;
    assert_eq!(application.active_lod_index, 0);
    assert_eq!(application.lod_sessions.len(), 2);
    assert_eq!(
        application
            .mesh
            .as_ref()
            .ok_or("missing active LOD0")?
            .vertices()
            .count(),
        3
    );
    let total_history_budget = application.history.budget_bytes()
        + application
            .lod_sessions
            .iter()
            .flatten()
            .map(|session| session.history.budget_bytes())
            .sum::<usize>();
    assert_eq!(total_history_budget, HISTORY_BUDGET_BYTES);

    application.handle_actions(vec![UiAction::SelectAllFaces, UiAction::DuplicateFaces]);
    let lod_zero_edited = application
        .mesh
        .as_ref()
        .ok_or("missing edited LOD0")?
        .structural_fingerprint();
    assert_eq!(application.history.undo_len(), 2);

    application.handle_actions(vec![UiAction::SwitchLod(1)]);
    assert_eq!(application.active_lod_index, 1);
    let lod_one = application.mesh.as_ref().ok_or("missing active LOD1")?;
    assert_eq!(lod_one.vertices().count(), 4);
    assert_eq!(lod_one.faces().count(), 2);
    assert_eq!(application.history.undo_len(), 0);
    application.handle_actions(vec![UiAction::SelectAllFaces, UiAction::DuplicateFaces]);
    let lod_one_edited = application
        .mesh
        .as_ref()
        .ok_or("missing edited LOD1")?
        .structural_fingerprint();
    assert_eq!(application.history.undo_len(), 2);

    application.handle_actions(vec![UiAction::SwitchLod(0)]);
    assert_eq!(
        application
            .mesh
            .as_ref()
            .ok_or("missing restored LOD0")?
            .structural_fingerprint(),
        lod_zero_edited
    );
    assert_eq!(application.history.undo_len(), 2);
    application.handle_actions(vec![UiAction::Undo]);
    assert_ne!(
        application
            .mesh
            .as_ref()
            .ok_or("missing undone LOD0")?
            .structural_fingerprint(),
        lod_zero_edited
    );
    application.handle_actions(vec![UiAction::Redo]);
    assert_eq!(
        application
            .mesh
            .as_ref()
            .ok_or("missing redone LOD0")?
            .structural_fingerprint(),
        lod_zero_edited
    );

    application.handle_actions(vec![UiAction::SwitchLod(1)]);
    assert_eq!(
        application
            .mesh
            .as_ref()
            .ok_or("missing restored LOD1")?
            .structural_fingerprint(),
        lod_one_edited
    );
    assert_eq!(application.history.undo_len(), 2);

    let context = application.egui_context.clone();
    let mut output = context.run_ui(
        egui::RawInput {
            screen_rect: Some(egui::Rect::from_min_size(
                egui::Pos2::ZERO,
                egui::vec2(1_440.0, 900.0),
            )),
            ..Default::default()
        },
        |ui| {
            let actions = application.draw_ui(ui);
            application.handle_actions(actions);
        },
    );
    assert!(!output.shapes.is_empty());
    assert!(application.window.is_none());
    assert!(application.renderer.is_none());
    output.textures_delta.clear();
    Ok(())
}

#[test]
fn deformation_reference_survives_geometry_and_resets_for_topology_and_lod() -> TestResult {
    let mut application = two_lod_application()?;
    let initial_reference = application
        .deformation_reference
        .as_ref()
        .ok_or("missing initial deformation reference")?
        .mesh
        .draw_snapshot();

    application.handle_actions(vec![
        UiAction::SelectAllVertices,
        UiAction::Nudge(Vec3::new(0.1, 0.0, 0.0)),
    ]);
    application.publish_mesh_snapshot();
    let moved = application
        .mesh
        .as_ref()
        .ok_or("missing moved LOD0")?
        .draw_snapshot();
    let preserved = application
        .deformation_reference
        .as_ref()
        .ok_or("missing preserved deformation reference")?
        .mesh
        .draw_snapshot();
    assert_ne!(moved.positions, initial_reference.positions);
    assert_eq!(preserved.positions, initial_reference.positions);
    assert_eq!(preserved.indices, initial_reference.indices);

    application.handle_actions(vec![UiAction::SelectAllFaces, UiAction::DuplicateFaces]);
    let topology_current = application
        .mesh
        .as_ref()
        .ok_or("missing duplicated LOD0")?
        .draw_snapshot();
    let topology_reference = application
        .deformation_reference
        .as_ref()
        .ok_or("missing reset topology reference")?
        .mesh
        .draw_snapshot();
    assert_eq!(topology_reference.positions, topology_current.positions);
    assert_eq!(topology_reference.indices, topology_current.indices);
    assert_eq!(
        topology_reference.topology_generation,
        topology_current.topology_generation
    );
    assert_eq!(
        topology_reference.mesh_identity,
        topology_current.mesh_identity
    );
    let lod_zero_identity = topology_current.mesh_identity;

    application.handle_actions(vec![UiAction::SwitchLod(1)]);
    assert_eq!(application.active_lod_index, 1);
    let lod_current = application
        .mesh
        .as_ref()
        .ok_or("missing active LOD1")?
        .draw_snapshot();
    let lod_reference = application
        .deformation_reference
        .as_ref()
        .ok_or("missing LOD1 deformation reference")?
        .mesh
        .draw_snapshot();
    assert_ne!(lod_current.mesh_identity, lod_zero_identity);
    assert_eq!(lod_reference.positions, lod_current.positions);
    assert_eq!(lod_reference.indices, lod_current.indices);
    assert_eq!(
        lod_reference.topology_generation,
        lod_current.topology_generation
    );
    assert_eq!(lod_reference.mesh_identity, lod_current.mesh_identity);
    Ok(())
}

#[test]
fn integrated_session_activates_and_preserves_the_manifest_source_lod() -> TestResult {
    let root = tempdir()?;
    let document = decode_mesh(&cdmw_formats::synthetic::two_lod_pac(), MeshFormat::Pac)?;
    let expected_lod_one_vertices = document.lods[1].submeshes[0].positions.len();
    let bridge = CdmwBridge::for_test_with_source_lod(
        root.path().to_path_buf(),
        "source-lod-session",
        1,
        0,
        1,
    );
    let mut application = LabApplication::new_cdmw(bridge, document.clone(), None)?;

    assert_eq!(application.active_lod_index, 1);
    assert_eq!(
        application
            .mesh
            .as_ref()
            .ok_or("missing source LOD mesh")?
            .vertices()
            .count(),
        expected_lod_one_vertices
    );

    let mut recovered = document;
    recovered.lods[1].submeshes[0].positions[0][0] += 5.0;
    let expected_position = recovered.lods[1].submeshes[0].positions[0];
    application.install_cdmw_document(recovered)?;

    assert_eq!(application.active_lod_index, 1);
    assert!(
        application
            .mesh
            .as_ref()
            .ok_or("recovered LOD1")?
            .vertices()
            .any(|(_, vertex)| vertex.position == expected_position)
    );
    Ok(())
}

#[test]
fn accepted_geometry_revisions_keep_the_deformation_session_baseline() -> TestResult {
    let root = tempdir()?;
    let document = decode_mesh(
        &cdmw_formats::synthetic::triangle_pam("body_base.dds"),
        MeshFormat::Pam,
    )?;
    let bridge = CdmwBridge::for_test(root.path().to_path_buf(), "deformation-session", 1, 0);
    let mut application = LabApplication::new_cdmw(bridge, document.clone(), None)?;
    let baseline = application
        .deformation_reference
        .as_ref()
        .ok_or("missing deformation baseline")?
        .mesh
        .draw_snapshot();

    for delta in [0.25, 0.75] {
        let mut accepted = document.clone();
        accepted.lods[0].submeshes[0].positions[0][2] += delta;
        application.install_cdmw_document(accepted)?;
        let current = application
            .mesh
            .as_ref()
            .ok_or("missing accepted mesh")?
            .draw_snapshot();
        let reference = application
            .deformation_reference
            .as_ref()
            .ok_or("missing retained deformation baseline")?
            .mesh
            .draw_snapshot();
        assert_ne!(current.positions, baseline.positions);
        assert_eq!(reference.positions, baseline.positions);
        assert_eq!(reference.indices, baseline.indices);
    }
    Ok(())
}

#[test]
fn integrated_session_retains_textures_when_a_shadow_revision_reloads_geometry() -> TestResult {
    let root = tempdir()?;
    let document = decode_mesh(
        &cdmw_formats::synthetic::triangle_pam("body_base.dds"),
        MeshFormat::Pam,
    )?;
    let bytes = cdmw_texture::synthetic::rgba8_checker_dds();
    let metadata = cdmw_texture::inspect_dds(&bytes, cdmw_texture::TextureRole::BaseColor)?;
    let bridge = CdmwBridge::for_test_with_textures(
        root.path().to_path_buf(),
        "texture-session",
        1,
        0,
        vec![crate::cdmw_session::CdmwTextureResource {
            label: "body_base.dds".to_owned(),
            role: cdmw_texture::TextureRole::BaseColor,
            metadata,
            bytes: bytes.clone(),
            material_indices_by_lod: vec![vec![0]],
        }],
    );
    let mut application = LabApplication::new_cdmw(bridge, document.clone(), None)?;

    assert_eq!(application.cdmw_texture_resources.len(), 1);
    assert_eq!(application.texture_entries.len(), 1);

    application.install_cdmw_document(document)?;

    assert_eq!(application.cdmw_texture_resources.len(), 1);
    assert_eq!(application.cdmw_texture_resources[0].bytes, bytes);
    assert_eq!(application.texture_entries.len(), 1);
    assert_eq!(application.texture_entries[0].label, "body_base.dds");
    Ok(())
}

#[test]
fn integrated_session_remaps_texture_ownership_after_part_reorder_and_invalidates_ambiguity()
-> TestResult {
    let root = tempdir()?;
    let mut document = decode_mesh(
        &cdmw_formats::synthetic::triangle_pam("body_base.dds"),
        MeshFormat::Pam,
    )?;
    let first = document.lods[0].submeshes.first_mut().ok_or("first part")?;
    first.name = "Part A".to_owned();
    first.material = "Material A".to_owned();
    let mut second = first.clone();
    second.name = "Part B".to_owned();
    second.material = "Material B".to_owned();
    for position in &mut second.positions {
        position[0] += 3.0;
    }
    document.lods[0].submeshes.push(second);

    let bytes = cdmw_texture::synthetic::rgba8_checker_dds();
    let metadata = cdmw_texture::inspect_dds(&bytes, cdmw_texture::TextureRole::BaseColor)?;
    let bridge = CdmwBridge::for_test_with_textures(
        root.path().to_path_buf(),
        "texture-remap-session",
        1,
        0,
        vec![crate::cdmw_session::CdmwTextureResource {
            label: "body_base.dds".to_owned(),
            role: cdmw_texture::TextureRole::BaseColor,
            metadata,
            bytes,
            material_indices_by_lod: vec![vec![0]],
        }],
    );
    let mut application = LabApplication::new_cdmw(bridge, document.clone(), None)?;

    let mut reordered = document;
    reordered.lods[0].submeshes.swap(0, 1);
    application.install_cdmw_document(reordered.clone())?;
    assert_eq!(
        application.cdmw_texture_resources[0].material_indices_by_lod,
        vec![vec![1]],
        "ownership must follow Part A instead of its previous numeric slot"
    );

    let duplicate = reordered.lods[0].submeshes[1].clone();
    reordered.lods[0].submeshes.push(duplicate);
    application.install_cdmw_document(reordered)?;
    assert_eq!(
        application.cdmw_texture_resources[0].material_indices_by_lod,
        vec![Vec::<u32>::new()],
        "ambiguous source identities must invalidate ownership instead of guessing"
    );
    Ok(())
}

#[test]
fn lod_working_mesh_preparation_honors_cancellation() -> TestResult {
    let document = decode_mesh(&cdmw_formats::synthetic::two_lod_pac(), MeshFormat::Pac)?;
    let cancellation = cdmw_archive::CancellationToken::default();
    cancellation.cancel();
    assert!(crate::loader::build_lod_meshes(&document, &cancellation).is_err());
    Ok(())
}

#[test]
fn lod_switch_rolls_back_an_active_edit_before_parking_the_session() -> TestResult {
    let mut application = two_lod_application()?;
    application.select_all_vertices();
    application.viewport_tool = ViewportTool::Move;
    let mesh = application.mesh.as_ref().ok_or("missing LOD0")?;
    let before = mesh.structural_fingerprint();
    let selection_before = mesh.selection.clone();
    let pivot = OrbitCamera::selected_center(mesh).ok_or("missing selection pivot")?;
    let center = application
        .camera
        .project(pivot, viewport())
        .ok_or("missing projected pivot")?
        .screen;
    application.begin_primary_gesture(viewport(), center);
    application.update_primary_gesture(viewport(), center + Vec2::new(25.0, 0.0), false);
    assert_ne!(
        application
            .mesh
            .as_ref()
            .ok_or("missing edited LOD0")?
            .structural_fingerprint(),
        before
    );
    application.handle_actions(vec![UiAction::SwitchLod(1), UiAction::SwitchLod(0)]);
    let restored = application.mesh.as_ref().ok_or("missing restored LOD0")?;
    assert_eq!(restored.structural_fingerprint(), before);
    assert_eq!(restored.selection, selection_before);
    assert_eq!(application.history.undo_len(), 0);
    assert_eq!(application.operator.state(), OperatorState::Idle);
    assert!(application.edit_gesture.is_none());
    assert!(application.selection_gesture.is_none());
    assert!(!application.raw_primary_captured);
    Ok(())
}

#[test]
fn every_selection_domain_and_shape_runs_through_the_app_headlessly() -> TestResult {
    for domain in [
        SelectionDomain::Vertex,
        SelectionDomain::Edge,
        SelectionDomain::Face,
    ] {
        for tool in [
            SelectionTool::Click,
            SelectionTool::Brush,
            SelectionTool::Rectangle,
            SelectionTool::Lasso,
        ] {
            run_selection_gesture(&mut triangle_application()?, domain, tool)?;
        }
    }
    Ok(())
}

#[test]
fn visible_and_xray_selection_use_their_distinct_query_paths() -> TestResult {
    let mut visible = triangle_application()?;
    visible.selection_domain = SelectionDomain::Face;
    visible.selection_tool = SelectionTool::Click;
    visible.selection_visible_only = true;
    let point = projected_domain_point(&mut visible, SelectionDomain::Face)?;
    visible.begin_primary_gesture(viewport(), point);
    visible.finish_primary_gesture();
    let visible_stats = visible
        .last_selection_stats
        .ok_or("missing visible stats")?;
    assert!(visible_stats.depth_triangles_inspected > 0);

    let mut xray = triangle_application()?;
    xray.selection_domain = SelectionDomain::Face;
    xray.selection_tool = SelectionTool::Click;
    xray.selection_visible_only = false;
    let point = projected_domain_point(&mut xray, SelectionDomain::Face)?;
    xray.begin_primary_gesture(viewport(), point);
    xray.finish_primary_gesture();
    let xray_stats = xray.last_selection_stats.ok_or("missing X-Ray stats")?;
    assert_eq!(xray_stats.depth_triangles_inspected, 0);
    Ok(())
}

#[test]
fn camera_modes_and_resize_are_headless_and_aspect_safe() -> TestResult {
    let mut application = triangle_application()?;
    for view in [
        StandardView::Front,
        StandardView::Back,
        StandardView::Left,
        StandardView::Right,
        StandardView::Top,
        StandardView::Bottom,
    ] {
        let before = application.camera.revision();
        application.handle_actions(vec![UiAction::StandardView(view)]);
        assert!(application.camera.revision() > before);
    }
    let before = application.camera.revision();
    application.camera.orbit(Vec2::new(18.0, -9.0));
    application.camera.pan(Vec2::new(7.0, 5.0), viewport());
    application.camera.zoom(120.0);
    assert!(application.camera.revision() >= before + 3);

    application.handle_actions(vec![UiAction::FrameAll]);
    let camera = application.camera.clone();
    for rectangle in [
        egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(1_200.0, 400.0)),
        egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(400.0, 1_200.0)),
    ] {
        let target = camera.target();
        let origin = camera
            .project(target, rectangle)
            .ok_or("origin projection")?;
        let x = camera
            .project(target + camera.right() * 0.25, rectangle)
            .ok_or("X projection")?;
        let y = camera
            .project(target + camera.up() * 0.25, rectangle)
            .ok_or("Y projection")?;
        let x_pixels = x.screen.distance(origin.screen);
        let y_pixels = y.screen.distance(origin.screen);
        assert!((x_pixels - y_pixels).abs() <= x_pixels.max(y_pixels) * 0.001);
        application.update_viewport_rect(rectangle);
        assert!(application.ensure_projection(rectangle));
        assert_eq!(
            application
                .projection
                .as_ref()
                .ok_or("projection")?
                .rectangle,
            rectangle
        );
    }

    for mode in [
        ViewMode::TexturedSolid,
        ViewMode::GameOutdoor,
        ViewMode::BaseColor,
        ViewMode::NormalMap,
        ViewMode::UvChecker,
        ViewMode::BaseAlpha,
        ViewMode::PartId,
        ViewMode::MaterialResponse,
        ViewMode::LayerMask,
        ViewMode::Solid,
        ViewMode::SolidWire,
        ViewMode::Wireframe,
        ViewMode::Vertices,
        ViewMode::WireVertices,
        ViewMode::XRay,
    ] {
        application.view_mode = mode;
        assert!(!application.view_mode.label().is_empty());
    }
    application.show_normals = true;
    application.show_bounds = true;
    assert!(application.show_normals && application.show_bounds);
    Ok(())
}

fn run_edit_tool(tool: ViewportTool) -> TestResult {
    let mut application = triangle_application()?;
    application.select_all_vertices();
    application.viewport_tool = tool;
    application.brush_radius = 2_000.0;
    let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
    let before = mesh.structural_fingerprint();
    let selection_before = mesh.selection.clone();
    let pivot = OrbitCamera::selected_center(mesh).ok_or("missing selection pivot")?;
    let center = application
        .camera
        .project(pivot, viewport())
        .ok_or("missing projected pivot")?
        .screen;
    let (start, end) = if tool == ViewportTool::Rotate {
        let ring = rotation_ring(&application.camera, pivot, GizmoAxis::Z, viewport());
        (
            *ring.first().ok_or("missing rotation ring")?,
            *ring.get(ring.len() / 4).ok_or("short rotation ring")?,
        )
    } else if tool.sculpt_tool().is_some() {
        let point = projected_domain_point(&mut application, SelectionDomain::Vertex)?;
        (point, point + Vec2::new(20.0, -8.0))
    } else {
        (center, center + Vec2::new(20.0, -8.0))
    };
    application.begin_primary_gesture(viewport(), start);
    if application.edit_gesture.is_none() {
        return Err(format!("{tool:?} did not start").into());
    }
    application.update_primary_gesture(viewport(), end, true);
    application.finish_primary_gesture();
    let changed = application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .structural_fingerprint();
    if changed == before {
        return Err(format!("{tool:?} did not change the mesh").into());
    }
    assert_eq!(application.history.undo_len(), 1);
    assert_eq!(
        application.mesh.as_ref().ok_or("missing mesh")?.selection,
        selection_before
    );
    application.handle_actions(vec![UiAction::Undo]);
    assert_eq!(
        application
            .mesh
            .as_ref()
            .ok_or("missing mesh")?
            .structural_fingerprint(),
        before
    );
    application.handle_actions(vec![UiAction::Redo]);
    assert_eq!(
        application
            .mesh
            .as_ref()
            .ok_or("missing mesh")?
            .structural_fingerprint(),
        changed
    );
    application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .validate()?;
    Ok(())
}

#[test]
fn every_transform_and_sculpt_tool_round_trips_headlessly() -> TestResult {
    for tool in [
        ViewportTool::Move,
        ViewportTool::Rotate,
        ViewportTool::Scale,
        ViewportTool::Grab,
        ViewportTool::Smooth,
        ViewportTool::Inflate,
        ViewportTool::Pinch,
    ] {
        run_edit_tool(tool)?;
    }
    Ok(())
}

fn symmetry_handles(
    application: &LabApplication,
) -> Result<(VertexHandle, VertexHandle, VertexHandle), Box<dyn std::error::Error>> {
    let mesh = application.mesh.as_ref().ok_or("missing symmetry mesh")?;
    let find = |position: [f32; 3]| {
        mesh.vertices()
            .find_map(|(handle, vertex)| (vertex.position == position).then_some(handle))
            .ok_or_else(|| -> Box<dyn std::error::Error> {
                format!("missing symmetry vertex {position:?}").into()
            })
    };
    Ok((
        find([-1.0, 0.0, 0.0])?,
        find([1.0, 0.0, 0.0])?,
        find([2.0, 2.0, 0.0])?,
    ))
}

fn projected_vertex(
    application: &LabApplication,
    handle: VertexHandle,
) -> Result<Vec2, Box<dyn std::error::Error>> {
    let position = Vec3::from_array(
        application
            .mesh
            .as_ref()
            .and_then(|mesh| mesh.vertex(handle))
            .ok_or("missing symmetry vertex")?
            .position,
    );
    application
        .camera
        .project(position, viewport())
        .map(|point| point.screen)
        .ok_or_else(|| "symmetry vertex is outside the camera".into())
}

#[test]
fn grab_symmetry_reflects_axis_delta_and_off_preserves_the_existing_stroke() -> TestResult {
    let mut off = symmetry_application()?;
    let (off_left, off_right, _) = symmetry_handles(&off)?;
    let off_right_before = off
        .mesh
        .as_ref()
        .and_then(|mesh| mesh.vertex(off_right))
        .ok_or("right vertex")?
        .position;
    let off_point = projected_vertex(&off, off_left)?;
    off.viewport_tool = ViewportTool::Grab;
    off.brush_radius = 32.0;
    off.begin_primary_gesture(viewport(), off_point);
    off.update_primary_gesture(viewport(), off_point + Vec2::new(18.0, -7.0), true);
    off.finish_primary_gesture();
    assert_eq!(off.history.undo_len(), 1);
    assert_eq!(
        off.mesh
            .as_ref()
            .and_then(|mesh| mesh.vertex(off_right))
            .ok_or("right vertex")?
            .position,
        off_right_before,
        "Off must retain the pre-symmetry brush behavior"
    );

    let mut mirrored = symmetry_application()?;
    let (left, right, unmatched) = symmetry_handles(&mirrored)?;
    let before = mirrored
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .vertices()
        .map(|(handle, vertex)| (handle, Vec3::from_array(vertex.position)))
        .collect::<HashMap<_, _>>();
    let point = projected_vertex(&mirrored, left)?;
    mirrored.viewport_tool = ViewportTool::Grab;
    mirrored.sculpt_symmetry = SculptSymmetry::X;
    mirrored.brush_radius = 32.0;
    mirrored.begin_primary_gesture(viewport(), point);
    assert!(mirrored.status.contains("unmatched untouched"));
    mirrored.update_primary_gesture(viewport(), point + Vec2::new(18.0, -7.0), true);
    mirrored.finish_primary_gesture();
    let mesh = mirrored.mesh.as_ref().ok_or("mesh")?;
    let left_delta = Vec3::from_array(mesh.vertex(left).ok_or("left")?.position) - before[&left];
    let right_delta =
        Vec3::from_array(mesh.vertex(right).ok_or("right")?.position) - before[&right];
    assert!((right_delta.x + left_delta.x).abs() < 1.0e-5);
    assert!((right_delta.y - left_delta.y).abs() < 1.0e-5);
    assert!((right_delta.z - left_delta.z).abs() < 1.0e-5);
    assert_eq!(
        Vec3::from_array(mesh.vertex(unmatched).ok_or("unmatched")?.position),
        before[&unmatched]
    );
    assert_eq!(mirrored.history.undo_len(), 1);
    Ok(())
}

#[test]
fn pinch_smooth_and_inflate_keep_mirror_partners_symmetric_in_one_history_entry() -> TestResult {
    for tool in [
        ViewportTool::Pinch,
        ViewportTool::Smooth,
        ViewportTool::Inflate,
    ] {
        let mut application = symmetry_application()?;
        let (left, right, unmatched) = symmetry_handles(&application)?;
        let unmatched_before = application
            .mesh
            .as_ref()
            .and_then(|mesh| mesh.vertex(unmatched))
            .ok_or("unmatched")?
            .position;
        let point = projected_vertex(&application, left)? + Vec2::new(8.0, -4.0);
        application.viewport_tool = tool;
        application.sculpt_symmetry = SculptSymmetry::X;
        application.brush_radius = 48.0;
        application.brush_strength = 0.3;
        application.begin_primary_gesture(viewport(), point);
        assert!(application.edit_gesture.is_some(), "{tool:?} did not start");
        application.finish_primary_gesture();
        let mesh = application.mesh.as_ref().ok_or("mesh")?;
        let left_position = Vec3::from_array(mesh.vertex(left).ok_or("left")?.position);
        let right_position = Vec3::from_array(mesh.vertex(right).ok_or("right")?.position);
        assert!(
            (right_position.x + left_position.x).abs() < 1.0e-4
                && (right_position.y - left_position.y).abs() < 1.0e-4
                && (right_position.z - left_position.z).abs() < 1.0e-4,
            "{tool:?} did not preserve reflected positions: left={left_position:?}, right={right_position:?}"
        );
        assert_eq!(
            mesh.vertex(unmatched).ok_or("unmatched")?.position,
            unmatched_before
        );
        assert_eq!(application.history.undo_len(), 1);
    }
    Ok(())
}

#[test]
fn mirrored_sculpt_commit_attempts_one_cdmw_candidate_transaction() -> TestResult {
    let root = tempdir()?;
    let mut application = symmetry_application()?;
    application.cdmw_bridge = Some(CdmwBridge::for_test(
        root.path().to_path_buf(),
        "symmetry-transaction-session",
        1,
        0,
    ));
    let (left, _, _) = symmetry_handles(&application)?;
    let point = projected_vertex(&application, left)?;
    application.viewport_tool = ViewportTool::Inflate;
    application.sculpt_symmetry = SculptSymmetry::X;
    application.brush_radius = 40.0;
    application.begin_primary_gesture(viewport(), point);
    application.finish_primary_gesture();
    assert_eq!(application.history.undo_len(), 1);
    assert_eq!(application.cdmw_transaction_attempts, 1);
    assert!(application.edit_gesture.is_none());
    Ok(())
}

#[test]
fn symmetry_plane_vertex_is_applied_once_and_cannot_leave_the_plane() -> TestResult {
    let mut application = symmetry_application()?;
    let plane = application
        .mesh
        .as_ref()
        .ok_or("mesh")?
        .vertices()
        .find_map(|(handle, vertex)| (vertex.position == [0.0, 1.0, 0.0]).then_some(handle))
        .ok_or("plane vertex")?;
    let before = Vec3::from_array(
        application
            .mesh
            .as_ref()
            .and_then(|mesh| mesh.vertex(plane))
            .ok_or("plane vertex")?
            .position,
    );
    let point = projected_vertex(&application, plane)?;
    let screen_delta = Vec2::new(16.0, -6.0);
    let expected_delta = SculptSymmetry::X.plane_vector(
        application
            .camera
            .screen_delta_to_world(screen_delta, viewport()),
    );
    application.viewport_tool = ViewportTool::Grab;
    application.sculpt_symmetry = SculptSymmetry::X;
    application.brush_radius = 3.0;
    application.begin_primary_gesture(viewport(), point);
    application.update_primary_gesture(viewport(), point + screen_delta, true);
    application.finish_primary_gesture();
    let after = Vec3::from_array(
        application
            .mesh
            .as_ref()
            .and_then(|mesh| mesh.vertex(plane))
            .ok_or("plane vertex")?
            .position,
    );
    let actual_delta = after - before;
    assert!(after.x.abs() < 1.0e-7);
    assert!(actual_delta.distance(expected_delta) < 1.0e-5);
    assert_eq!(application.history.undo_len(), 1);
    Ok(())
}

#[test]
fn app_cancellation_restores_the_exact_working_state() -> TestResult {
    let mut application = triangle_application()?;
    application.select_all_vertices();
    application.viewport_tool = ViewportTool::Move;
    let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
    let before = mesh.structural_fingerprint();
    let selection_before = mesh.selection.clone();
    let pivot = OrbitCamera::selected_center(mesh).ok_or("missing selection pivot")?;
    let center = application
        .camera
        .project(pivot, viewport())
        .ok_or("missing projected pivot")?
        .screen;
    application.begin_primary_gesture(viewport(), center);
    application.update_primary_gesture(viewport(), center + Vec2::new(25.0, 0.0), false);
    assert_ne!(
        application
            .mesh
            .as_ref()
            .ok_or("missing mesh")?
            .structural_fingerprint(),
        before
    );
    application.cancel_active_gesture("headless cancellation");
    let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
    assert_eq!(mesh.structural_fingerprint(), before);
    assert_eq!(mesh.selection, selection_before);
    assert_eq!(application.history.undo_len(), 0);
    assert_eq!(application.operator.state(), OperatorState::Idle);
    Ok(())
}

#[test]
fn every_topology_action_round_trips_geometry_and_selection() -> TestResult {
    for action in [
        UiAction::DuplicateFaces,
        UiAction::DuplicateFacesToNewSubmesh,
        UiAction::SubdivideFaces,
        UiAction::ExtrudeFaces,
        UiAction::InsetFaces,
        UiAction::DeleteFaces,
    ] {
        let expects_new_submesh = matches!(action, UiAction::DuplicateFacesToNewSubmesh);
        let mut application = triangle_application()?;
        application.select_all_faces();
        let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
        let before = mesh.structural_fingerprint();
        let selection_before = mesh.selection.clone();
        application.handle_actions(vec![action]);
        let changed = application
            .mesh
            .as_ref()
            .ok_or("missing mesh")?
            .structural_fingerprint();
        assert_ne!(changed, before);
        if expects_new_submesh {
            let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
            assert!(mesh.selection.faces.iter().all(|handle| {
                mesh.face(*handle)
                    .is_some_and(|face| face.submesh == 1 && face.material == 0)
            }));
        }
        assert_eq!(application.history.undo_len(), 1);
        application.handle_actions(vec![UiAction::Undo]);
        let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
        assert_eq!(mesh.structural_fingerprint(), before);
        assert_eq!(mesh.selection, selection_before);
        application.handle_actions(vec![UiAction::Redo]);
        let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
        assert_eq!(mesh.structural_fingerprint(), changed);
        if expects_new_submesh {
            assert!(mesh.selection.faces.iter().all(|handle| {
                mesh.face(*handle)
                    .is_some_and(|face| face.submesh == 1 && face.material == 0)
            }));
        }
        mesh.validate()?;
    }

    let mut application = triangle_application()?;
    application.handle_actions(vec![UiAction::SelectAllEdges]);
    let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
    let before = mesh.structural_fingerprint();
    let selection_before = mesh.selection.clone();
    assert_eq!(selection_before.edges.len(), 3);
    application.handle_actions(vec![UiAction::SubdivideEdges]);
    let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
    let changed = mesh.structural_fingerprint();
    assert_ne!(changed, before);
    assert_eq!(mesh.faces().count(), 4);
    assert_eq!(mesh.selection.edges.len(), 6);
    assert_eq!(application.history.undo_len(), 2);
    application.handle_actions(vec![UiAction::Undo]);
    let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
    assert_eq!(mesh.structural_fingerprint(), before);
    assert_eq!(mesh.selection, selection_before);
    application.handle_actions(vec![UiAction::Redo]);
    let mesh = application.mesh.as_ref().ok_or("missing mesh")?;
    assert_eq!(mesh.structural_fingerprint(), changed);
    assert_eq!(mesh.selection.edges.len(), 6);
    mesh.validate()?;
    Ok(())
}

#[test]
#[ignore = "requires CDMW_RUST_MESH_PATH to name a caller-supplied mesh"]
fn caller_selected_mesh_select_linked_is_selection_only_and_undoable() -> TestResult {
    let path = std::path::PathBuf::from(std::env::var("CDMW_RUST_MESH_PATH")?);
    let bytes = std::fs::read(&path)?;
    let format = MeshFormat::from_path(&path)?;
    let document = decode_mesh(&bytes, format)?;
    let baseline = WorkingMesh::from_document(&document)?;
    let geometry_fingerprint = baseline.structural_fingerprint();

    for domain in [
        SelectionDomain::Vertex,
        SelectionDomain::Edge,
        SelectionDomain::Face,
    ] {
        let mut mesh = baseline.clone();
        let (seed, total) = match domain {
            SelectionDomain::Vertex => {
                let handle = mesh
                    .vertices()
                    .next()
                    .map(|(handle, _)| handle)
                    .ok_or("missing vertex")?;
                (
                    Selection {
                        vertices: [handle].into_iter().collect(),
                        ..Selection::default()
                    },
                    mesh.vertices().count(),
                )
            }
            SelectionDomain::Edge => {
                let handle = mesh
                    .edges()
                    .next()
                    .map(|(handle, _)| handle)
                    .ok_or("missing edge")?;
                (
                    Selection {
                        edges: [handle].into_iter().collect(),
                        ..Selection::default()
                    },
                    mesh.edges().count(),
                )
            }
            SelectionDomain::Face => {
                let handle = mesh
                    .faces()
                    .next()
                    .map(|(handle, _)| handle)
                    .ok_or("missing face")?;
                (
                    Selection {
                        faces: [handle].into_iter().collect(),
                        ..Selection::default()
                    },
                    mesh.faces().count(),
                )
            }
        };
        mesh.set_selection(seed.clone())?;
        let before = mesh.clone();
        let started = std::time::Instant::now();
        let linked = selection_after_command(&mesh, domain, SelectionCommand::SelectLinked);
        let elapsed_ms = started.elapsed().as_secs_f64() * 1_000.0;
        let linked_count = match domain {
            SelectionDomain::Vertex => linked.vertices.len(),
            SelectionDomain::Edge => linked.edges.len(),
            SelectionDomain::Face => linked.faces.len(),
        };
        assert!((1..=total).contains(&linked_count));
        mesh.set_selection(linked.clone())?;
        let mut history = History::new(HISTORY_BUDGET_BYTES);
        history.commit("select linked", before, &mesh)?;
        history.undo(&mut mesh)?;
        assert_eq!(mesh.selection, seed);
        assert_eq!(mesh.structural_fingerprint(), geometry_fingerprint);
        history.redo(&mut mesh)?;
        assert_eq!(mesh.selection, linked);
        assert_eq!(mesh.structural_fingerprint(), geometry_fingerprint);
        mesh.validate()?;
        eprintln!(
            "caller-selected {domain:?} Linked: {linked_count}/{total} elements in {elapsed_ms:.2} ms"
        );
    }
    Ok(())
}

#[test]
#[ignore = "requires a local Direct3D 12 adapter"]
fn offscreen_d3d12_renders_every_mode_without_a_window() -> TestResult {
    let application = triangle_application()?;
    let snapshot = application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .draw_snapshot();
    let proof_path = std::env::var_os("CDMW_RUST_MATERIAL_PROOF_BMP").map(std::path::PathBuf::from);
    let report = if let Some(proof_path) = proof_path.as_deref() {
        pollster::block_on(
            cdmw_render_wgpu::run_headless_render_smoke_with_material_proof(&snapshot, proof_path),
        )?
    } else {
        pollster::block_on(cdmw_render_wgpu::run_headless_render_smoke(&snapshot))?
    };
    assert_eq!(report.adapter.backend, "Dx12");
    assert_eq!(report.modes_rendered, 15);
    assert_eq!(report.viewport_sizes_rendered, 3);
    assert_eq!(report.frames_rendered, 84);
    assert_eq!(report.dds_textures_uploaded, 16);
    assert_eq!(report.sampled_material_roles, 13);
    assert_eq!(report.material_ranges_rendered, 2);
    assert!(report.composed_material_pixels_changed > 0);
    assert!(report.emissive_factor_pixels_changed > 0);
    assert!(report.roughness_factor_pixels_changed > 0);
    assert!(report.metalness_factor_pixels_changed > 0);
    assert!(report.specular_factor_pixels_changed > 0);
    assert!(report.specular_texture_pixels_changed > 0);
    assert_eq!(report.dielectric_specular_pixels_changed, 0);
    assert!(report.glossiness_texture_pixels_changed > 0);
    assert_eq!(report.dielectric_glossiness_pixels_changed, 0);
    assert!(report.height_texture_pixels_changed > 0);
    assert_eq!(report.disabled_height_pixels_changed, 0);
    assert!(report.hair_flow_pixels_changed > 0);
    assert_eq!(report.non_hair_flow_pixels_changed, 0);
    assert!(report.layer_mask_pixels_changed > 0);
    assert!(report.layer_mask_channel_pixels_changed > 0);
    assert_eq!(report.part_id_colors_rendered, 2);
    assert!(report.outdoor_lighting_pixels_changed > 0);
    assert!(report.bone_overlay_pixels_changed > 0);
    assert!(report.effect_overlay_pixels_changed > 0);
    assert!(report.opacity_cutout_pixels_removed > 0);
    assert_eq!(report.opaque_opacity_pixels_changed, 0);
    assert!(report.non_background_pixels > 0);
    assert!(report.base_color_round_trip_pixels > 0);
    assert!((35..=175).contains(&report.front_lighting_luma_percent));
    assert_eq!(report.category_materials_distinguished, 5);
    Ok(())
}

#[test]
#[ignore = "requires a local Direct3D 12 adapter"]
fn offscreen_d3d12_capture_pads_odd_rows_and_matches_alpha_cutout_owners() -> TestResult {
    let application = triangle_application()?;
    let snapshot = application
        .mesh
        .as_ref()
        .ok_or("missing mesh")?
        .draw_snapshot();
    let mut base_color = cdmw_texture::synthetic::rgba8_checker_dds();
    base_color[151] = 0;
    base_color[155] = 255;
    base_color[159] = 0;
    base_color[163] = 255;
    let ownership = vec![vec![0_u32]];
    let textures = [HeadlessMaterialTexture {
        bytes: &base_color,
        role: cdmw_texture::TextureRole::BaseColor,
        material_indices_by_lod: &ownership,
    }];
    let factors = [HeadlessMaterialFactors {
        factors: MaterialPreviewFactors {
            alpha_cutoff: Some(0.5),
            ..MaterialPreviewFactors::default()
        },
        material_indices_by_lod: &ownership,
    }];
    let root = tempdir()?;
    let report = pollster::block_on(cdmw_render_wgpu::run_headless_material_capture(
        &snapshot,
        &textures,
        &factors,
        HeadlessMaterialCaptureOptions {
            width: 65,
            height: 73,
            lod_index: 0,
        },
        HeadlessMaterialCaptureOutput {
            textured_bmp: &root.path().join("textured.bmp"),
            base_color_bmp: &root.path().join("base-color.bmp"),
            part_id_bmp: &root.path().join("part-id.bmp"),
        },
    ))?;
    assert!(report.textured.non_background_pixels > 0);
    assert_eq!(
        report.part_id.non_background_pixels,
        report.textured.non_background_pixels
    );
    assert_eq!(
        report.part_id.non_background_pixels,
        report.base_color.non_background_pixels
    );
    assert_eq!(report.owner_coverage.len(), 1);
    assert!(report.owner_coverage[0].pixel_count > 0);
    assert!(report.owner_coverage[0].pixel_count <= report.part_id.non_background_pixels);
    Ok(())
}

#[test]
#[ignore = "requires a local Direct3D 12 adapter and an owned CDMW session package"]
fn offscreen_d3d12_captures_the_exact_cdmw_material_package_without_a_window() -> TestResult {
    let manifest = std::env::var_os("CDMW_RUST_REAL_SESSION_MANIFEST")
        .map(PathBuf::from)
        .ok_or("CDMW_RUST_REAL_SESSION_MANIFEST is required")?;
    let output = std::env::var_os("CDMW_RUST_REAL_CAPTURE_BMP")
        .map(PathBuf::from)
        .ok_or("CDMW_RUST_REAL_CAPTURE_BMP is required")?;
    let report_path = std::env::var_os("CDMW_RUST_REAL_CAPTURE_REPORT_JSON").map(PathBuf::from);

    capture_cdmw_session(&manifest, &output, report_path.as_deref(), false)?;

    let paths = cdmw_capture_paths(&output, report_path.as_deref())?;
    let report: Value = serde_json::from_slice(&fs::read(paths.report)?)?;
    let uploaded = report["dds_textures_uploaded"]
        .as_u64()
        .ok_or("upload count")?;
    let range_count = report["material_ranges_rendered"]
        .as_u64()
        .ok_or("material range count")?;
    let owner_coverage = report["owner_coverage"]
        .as_array()
        .ok_or("owner coverage")?;
    assert!(uploaded > 0);
    assert!(range_count > 0);
    assert_eq!(owner_coverage.len() as u64, range_count);
    assert!(owner_coverage.iter().all(|owner| {
        owner["pixel_count"]
            .as_u64()
            .is_some_and(|pixel_count| pixel_count > 0)
    }));
    assert!(paths.textured.is_file());
    assert!(paths.base_color.is_file());
    assert!(paths.part_id.is_file());
    Ok(())
}
