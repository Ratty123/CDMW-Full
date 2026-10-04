//! Exercise cloth through the real controls, owned loader and draw-only scene.
use super::*;
use sha2::{Digest, Sha256};

mod strain;
mod profiles {
    use super::*;

    #[test]
    fn spline_preview_loads_raw_spring_back_edits_and_refreshes_the_saved_assignment() -> TestResult {
        let (_root, mut ui, _) = spline_fixture()?;
        editable_profiles(&mut ui);
        {
            let state = &mut ui.application.cdmw_state["physics_profiles"];
            state["sources"][0]["authored"]["restoreanglestiffness"] = json!("0.025");
            state["profiles"][0]["authored"]["restoreanglestiffness"] = json!("0.025");
            state["profiles"][0]["preview"]["spline"] = json!(true);
            state["profiles"][0]["preview"]["restore_angle"] = json!(0.00630950927734375);
            state["profiles"][0]["preview"]["rotate_guides"] = json!(true);
            state["profiles"][0]["preview"]["single_edge_rotation"] = json!(true);
        }
        ui.frame(Vec::new());
        ui.click("Authored physics profile")?;
        ui.click("Variant 0")?;
        ui.click("Use profile in preview")?;
        assert!(ui.application.cdmw_jiggle.preview.cloth_settings.spline);
        assert_eq!(ui.application.cdmw_jiggle.preview.cloth_settings.restore_angle, 0.00630950927734375);
        ui.click("Play preview")?;
        wait(&mut ui)?;
        advance(&mut ui)?;
        ui.click("Edit profile for mod")?;
        ui.click("Override Spring-back stiffness")?;
        let actions = ui.actions_from_click("Apply profile edit")?;
        let mut rule = profile_command(&actions)["rule"].clone();
        assert_eq!(rule["values"], json!({"RestoreAngleStiffness": 0.025}));
        rule["values"]["RestoreAngleStiffness"] = json!(0.8);
        ui.application.cdmw_pending_request = None;
        {
            let state = &mut ui.application.cdmw_state["physics_profiles"];
            state["groups"][0]["rule"] = rule;
            let mut edited = state["profiles"][0].clone();
            edited["path"] = json!("cloned.xml");
            edited["preview"]["restore_angle"] = json!(0.5);
            state["profiles"].as_array_mut().unwrap().push(edited);
            state["parts"][0]["bindings"][0]["path"] = json!("cloned.xml");
        }
        ui.frame(Vec::new());
        assert_eq!(ui.application.cdmw_jiggle.preview.cloth_settings.restore_angle, 0.5);
        // Authoring commands reset draw-only playback; the saved preset remains.
        ui.click("Play preview")?;
        wait(&mut ui)?;
        assert!(ui.application.cdmw_jiggle.preview.playing);
        // Unrelated state changes keep temporary adjustments to loaded values.
        ui.application.cdmw_jiggle.preview.cloth_settings.restore_angle = 0.3;
        ui.application.cdmw_state["physics_profiles"]["cloth_geometry"]["guide_count"] = json!(4);
        ui.frame(Vec::new());
        assert_eq!(ui.application.cdmw_jiggle.preview.cloth_settings.restore_angle, 0.3);
        ui.click("Restore manual preview settings")?;
        assert_eq!(ui.application.cdmw_jiggle.preview.cloth_settings.restore_angle, 0.0);
        Ok(())
    }

    fn source_profiles(ui: &mut HeadlessUi) {
        ui.application.cdmw_state["physics_profiles"] = json!({
            "available": true, "source": "fixture.pac", "sidecar_sha256": "fixture-sidecar",
            "cloth_geometry": {"status": "available", "guide_count": 3, "fixed_count": 1},
            "variants": ["0", "1"],
            "parts": [{"index": 0, "name": "Cloth", "source_name": "Cloth", "bindings": [
                {"variant": "0", "profile": "Lower_Leather", "path": "lower.xml", "reason": ""},
                {"variant": "1", "profile": "", "path": "", "reason": ""}
            ]}],
            "profiles": [{"path": "lower.xml", "sha256": "fixture-profile", "reason": "",
                "authored": {"stretchingstiffness": ".3", "bendingstiffness": ".1388"},
                "preview": {"gravity": 10.0, "damping": 0.7998046875,
                    "stretch": 0.359619140625, "bend": 0.05999755859375,
                    "iterations": 4, "use_vertex_alpha": true, "rotate_guides": false}
            }]
        });
        ui.frame(Vec::new());
    }

    fn editable_profiles(ui: &mut HeadlessUi) {
        source_profiles(ui);
        let state = &mut ui.application.cdmw_state["physics_profiles"];
        let mut source = state["profiles"][0].clone();
        source["name"] = json!("Lower_Leather");
        source["authored"]["solveriterationcount"] = json!("3");
        source["authored"]["damping"] = json!(".8");
        state["sources"] = json!([source]);
        state["groups"] = json!([
            {"id": "shared:0", "variant": "0", "available": true, "reason": "",
                "names": ["Cloth", "Belt", "Trim"], "source_profile": "Lower_Leather", "rule": null},
            {"id": "shared:1", "variant": "1", "available": true, "reason": "",
                "names": ["Cloth", "Belt", "Trim"], "source_profile": "", "rule": null}
        ]);
        ui.frame(Vec::new());
    }

    fn profile_command(actions: &[UiAction]) -> &Value {
        actions
            .iter()
            .find_map(|action| match action {
                UiAction::CdmwCommand {
                    command: "replacement_physics_profile",
                    arguments,
                    ..
                } => Some(arguments),
                _ => None,
            })
            .expect("profile command from the actual control")
    }

    #[test]
    fn collision_overrides_emit_captured_binary_values_and_survive_collapsed_edits() -> TestResult {
        let (_root, mut ui, _) = fixture()?;
        editable_profiles(&mut ui);
        let authored = ui.application.mesh.as_ref().unwrap().draw_snapshot();
        let mut fields = [
            ("IsCloak", "Cloak behavior", 1),
            ("UseBackStopCollision", "Backstop collisions", 0),
            ("UseInputPositionCollision", "Input-position collisions", 1),
            ("ShrinkWhenShieldIsInSocket", "Shrink around sheathed shield", 1),
            ("UseLraConstraint", "Long-range attachments", 0),
            ("SkipSelfMeshCollidable", "Skip own model collisions", 1),
        ];
        for (key, _, value) in fields {
            ui.application.cdmw_state["physics_profiles"]["sources"][0]["authored"][key.to_ascii_lowercase()] = json!(value.to_string());
        }
        ui.click("Authored physics profile")?;
        ui.click("Variant 0")?;
        ui.click("Edit profile for mod")?;
        ui.click("Collision and attachment overrides")?;
        for (_, label, _) in fields {
            ui.click(&format!("Override {label}"))?;
        }
        let cloak = ui.reveal("Override Cloak behavior")?;
        let next = ui.label_rect("Override Backstop collisions").ok_or("next collision row")?;
        // The value checkbox can wrap below its long override label.
        ui.click_where("Enabled", |rect| rect.top() >= cloak.top() - 2.0 && rect.bottom() < next.top())?;
        fields[0].2 = 0;
        let actions = ui.actions_from_click("Apply profile edit")?;
        let rule = profile_command(&actions)["rule"].clone();
        assert_eq!(rule["values"].as_object().unwrap().len(), fields.len());
        for (key, _, value) in fields {
            assert_eq!(rule["values"][key], json!(f64::from(value)));
        }
        ui.application.cdmw_pending_request = None;
        ui.application.cdmw_state["physics_profiles"]["groups"][0]["rule"] = rule.clone();
        ui.frame(Vec::new());
        ui.click("Collision and attachment overrides")?;
        ui.click("Override Damping")?;
        let actions = ui.actions_from_click("Apply profile edit")?;
        let mut expected = rule["values"].clone();
        expected["Damping"] = json!(0.8);
        assert_eq!(profile_command(&actions)["rule"]["values"], expected);
        assert!(!ui.application.cdmw_jiggle.preview.cloth_settings.body_collisions);
        assert_eq!(ui.application.mesh.as_ref().unwrap().draw_snapshot(), authored);
        Ok(())
    }

    #[test]
    fn collision_overrides_require_an_explicit_choice_for_invalid_source_flags() -> TestResult {
        let (_root, mut ui, _) = fixture()?;
        editable_profiles(&mut ui);
        ui.click("Authored physics profile")?;
        ui.click("Variant 0")?;
        ui.click("Edit profile for mod")?;
        ui.click("Collision and attachment overrides")?;
        for raw in ["NaN", "inf", "0.5", "invalid"] {
            ui.application.cdmw_pending_request = None;
            ui.application.cdmw_state["physics_profiles"]["sources"][0]["authored"]["iscloak"] = json!(raw);
            ui.frame(Vec::new());
            ui.reveal("Invalid source value")?;
            assert!(ui.label_rect("Invalid source value").is_some());
            ui.click("Override Cloak behavior")?;
            let actions = ui.actions_from_click("Apply profile edit")?;
            assert_eq!(profile_command(&actions)["rule"]["values"], json!({"IsCloak": 0.0}));
        }
        Ok(())
    }

    #[test]
    fn upward_profile_and_manual_gravity_use_xml_sign_without_changing_raw_edits() -> TestResult {
        let (_root, mut ui, _) = fixture()?;
        editable_profiles(&mut ui);
        let authored = ui.application.mesh.as_ref().unwrap().draw_snapshot();
        ui.application.cdmw_state["physics_profiles"]["profiles"][0]["preview"]["gravity"] =
            json!(-20.0);
        ui.application.cdmw_state["physics_profiles"]["sources"][0]["authored"]["gravity"] =
            json!("20");
        ui.application.cdmw_jiggle.preview.cloth_settings.gravity = 3.0;
        ui.click("Authored physics profile")?;
        ui.click("Variant 0")?;
        ui.click("Use profile in preview")?;
        assert_eq!(
            ui.application.cdmw_jiggle.preview.cloth_settings.gravity,
            -20.0
        );

        ui.click("Cloth preview settings")?;
        let gravity_label = ui.reveal("Gravity")?;
        let value = ui
            .output
            .shapes
            .iter()
            .find_map(|clipped| {
                let egui::Shape::Text(text) = &clipped.shape else {
                    return None;
                };
                let rect = text.visual_bounding_rect();
                (text.galley.job.text.parse::<f64>() == Ok(20.0)
                    && (rect.center().y - gravity_label.center().y).abs() < 4.0
                    && rect.right() < gravity_label.left())
                .then_some(rect)
            })
            .ok_or("preview gravity should display positive 20 in the actual numeric control")?;
        ui.click_at(value.center());
        ui.frame(vec![
            Event::Text("-15".into()),
            key_event(egui::Key::Enter, true),
        ]);
        ui.frame(vec![key_event(egui::Key::Enter, false)]);
        assert_eq!(
            ui.application.cdmw_jiggle.preview.cloth_settings.gravity,
            15.0
        );
        ui.click("Restore manual preview settings")?;
        assert_eq!(
            ui.application.cdmw_jiggle.preview.cloth_settings.gravity,
            3.0
        );

        ui.click("Edit profile for mod")?;
        ui.click("Override Gravity")?;
        let actions = ui.actions_from_click("Apply profile edit")?;
        assert_eq!(
            profile_command(&actions)["rule"]["values"],
            json!({"Gravity": 20.0})
        );
        assert_eq!(
            ui.application.mesh.as_ref().unwrap().draw_snapshot(),
            authored
        );
        Ok(())
    }

    #[test]
    fn profile_guide_diagnostics_do_not_confuse_missing_geometry_with_decode_limits() -> TestResult
    {
        let (_root, mut ui, _) = fixture()?;
        editable_profiles(&mut ui);
        ui.click("Authored physics profile")?;
        assert!(
            ui.label_rect("Authored cloth guides: 3 (1 fixed)")
                .is_some()
        );
        let absent = "This model has no authored cloth guides. Profile edits do not add cloth or bone jiggle.";
        let unsupported = "Cloth guide data could not be decoded; its availability is unknown.";
        ui.application.cdmw_state["physics_profiles"]["cloth_geometry"] =
            json!({"status": "absent", "guide_count": 0});
        ui.frame(Vec::new());
        assert!(ui.label_rect(absent).is_some());
        assert!(ui.label_rect(unsupported).is_none());
        // Metadata editing remains useful even when this source has no guides.
        ui.click("Variant 0")?;
        ui.click("Edit profile for mod")?;
        ui.click("Override Damping")?;
        let actions = ui.actions_from_click("Apply profile edit")?;
        assert_eq!(
            profile_command(&actions)["rule"]["values"],
            json!({"Damping": 0.8})
        );
        ui.application.cdmw_pending_request = None;
        ui.application.cdmw_state["physics_profiles"]["cloth_geometry"] =
            json!({"status": "unsupported", "reason": "Unknown guide layout"});
        ui.frame(Vec::new());
        assert!(ui.label_rect(unsupported).is_some());
        assert!(ui.label_rect(absent).is_none());
        ui.application.cdmw_state["physics_profiles"]
            .as_object_mut()
            .unwrap()
            .remove("cloth_geometry");
        ui.frame(Vec::new());
        assert!(ui.label_rect(unsupported).is_none());
        assert!(ui.label_rect(absent).is_none());
        Ok(())
    }

    #[test]
    fn profile_apply_and_restore_emit_raw_overrides_and_shared_owner_identity() -> TestResult {
        let (_root, mut ui, _) = fixture()?;
        editable_profiles(&mut ui);
        let authored = ui.application.mesh.as_ref().unwrap().draw_snapshot();
        ui.click("Authored physics profile")?;
        ui.click("Variant 0")?;
        ui.click("Use profile in preview")?;
        assert_eq!(
            ui.application.cdmw_jiggle.preview.cloth_settings.stretch,
            0.359619140625
        );
        ui.click("Edit profile for mod")?;
        assert!(
            ui.label_rect("Applies to all 3 parts sharing this assignment")
                .is_some()
        );
        ui.click("Override Stretch stiffness")?;
        ui.click("Override Iterations")?;
        let actions = ui.actions_from_click("Apply profile edit")?;
        let args = profile_command(&actions);
        assert_eq!(args["group_id"], "shared:0");
        assert_eq!(args["rule"]["variant"], "0");
        assert_eq!(
            args["rule"]["values"],
            json!({"StretchingStiffness": 0.3, "SolverIterationCount": 3.0})
        );
        ui.application.cdmw_pending_request = None; // Host acknowledgement.
        ui.application.cdmw_state["physics_profiles"]["groups"][0]["rule"] = args["rule"].clone();
        ui.frame(Vec::new());
        let actions = ui.actions_from_click("Restore profile assignment")?;
        assert_eq!(
            profile_command(&actions),
            &json!({"group_id": "shared:0", "reset": true})
        );
        assert_eq!(
            ui.application.mesh.as_ref().unwrap().draw_snapshot(),
            authored
        );
        Ok(())
    }

    #[test]
    fn profile_empty_variant_requires_explicit_source_and_multiple_groups_require_selection()
    -> TestResult {
        let (_root, mut ui, _) = fixture()?;
        editable_profiles(&mut ui);
        let mut second = ui.application.cdmw_state["physics_profiles"]["groups"][0].clone();
        second["id"] = json!("separate:0");
        second["names"] = json!(["Other"]);
        ui.application.cdmw_state["physics_profiles"]["groups"]
            .as_array_mut()
            .unwrap()
            .push(second);
        ui.click("Authored physics profile")?;
        ui.click("Variant 0")?;
        ui.click("Edit profile for mod")?;
        assert!(ui.label_rect("Apply profile edit").is_none());
        ui.click("Profile group 2")?;
        ui.click("Override Damping")?;
        let actions = ui.actions_from_click("Apply profile edit")?;
        assert_eq!(profile_command(&actions)["group_id"], "separate:0");
        ui.application.cdmw_pending_request = None;
        ui.frame(Vec::new());
        ui.click("Variant 1")?;
        assert!(ui.label_rect("Apply profile edit").is_none());
        ui.click("Choose source profile")?;
        ui.click("Lower_Leather")?;
        ui.click("Override Damping")?;
        let actions = ui.actions_from_click("Apply profile edit")?;
        let args = profile_command(&actions);
        assert_eq!(args["group_id"], "shared:1");
        assert_eq!(args["rule"]["variant"], "1");
        assert_eq!(args["rule"]["values"], json!({"Damping": 0.8}));
        Ok(())
    }

    #[test]
    fn profile_nonfinite_sources_are_displayed_safely_and_never_sent_as_null() -> TestResult {
        let (_root, mut ui, _) = fixture()?;
        editable_profiles(&mut ui);
        ui.click("Authored physics profile")?;
        ui.click("Variant 0")?;
        ui.click("Edit profile for mod")?;
        for raw in ["NaN", "inf", "-Infinity", "1e999", "invalid"] {
            ui.application.cdmw_pending_request = None;
            ui.application.cdmw_state["physics_profiles"]["sources"][0]["authored"]["damping"] =
                json!(raw);
            ui.frame(Vec::new());
            assert!(ui.label_rect("Invalid source value").is_some(), "{raw}");
            ui.click("Override Damping")?;
            let actions = ui.actions_from_click("Apply profile edit")?;
            let value = profile_command(&actions)["rule"]["values"]["Damping"]
                .as_f64()
                .unwrap();
            assert!(value.is_finite() && (0.0..=10.0).contains(&value));
        }
        ui.application.cdmw_pending_request = None;
        ui.application.cdmw_state["physics_profiles"]["groups"][0]["available"] = json!(false);
        ui.frame(Vec::new());
        assert!(!has_host_command(
            &ui.actions_from_click("Apply profile edit")?,
            "replacement_physics_profile"
        ));
        Ok(())
    }

    #[test]
    fn explicit_profile_selection_drives_preview_and_empty_variant_restores_manual() -> TestResult {
        let (root, mut ui, payload) = fixture()?;
        source_profiles(&mut ui);
        let authored = ui.application.mesh.as_ref().unwrap().draw_snapshot();
        ui.application.cdmw_jiggle.preview.cloth_settings.gravity = 2.0;
        ui.application
            .cdmw_jiggle
            .preview
            .cloth_settings
            .ground_height = Some(-10.0);
        ui.click("Authored physics profile")?;
        assert!(ui.label_rect("Use profile in preview").is_none());
        ui.click("Variant 0")?;
        ui.click("Use profile in preview")?;
        let settings = ui.application.cdmw_jiggle.preview.cloth_settings;
        assert_eq!(settings.gravity, 10.0);
        assert_eq!(settings.stretch, 0.359619140625);
        assert_eq!(settings.bend, 0.05999755859375);
        assert_eq!(settings.damping, 0.7998046875);
        assert!(settings.use_vertex_alpha);
        assert_eq!(settings.ground_height, Some(-10.0));
        ui.click("Play preview")?;
        wait(&mut ui)?;
        advance(&mut ui)?;
        let profile_frame = ui
            .application
            .cdmw_jiggle
            .preview
            .scene
            .as_ref()
            .unwrap()
            .frame
            .clone();
        assert_ne!(profile_frame.positions, authored.positions);
        ui.click("Variant 1")?;
        assert!(ui.label_rect("Use profile in preview").is_none());
        assert_eq!(
            ui.application.cdmw_jiggle.preview.cloth_settings.gravity,
            2.0
        );
        assert!(
            !ui.application
                .cdmw_jiggle
                .preview
                .cloth_settings
                .use_vertex_alpha
        );
        wait(&mut ui)?;
        advance(&mut ui)?;
        let manual_frame = &ui
            .application
            .cdmw_jiggle
            .preview
            .scene
            .as_ref()
            .unwrap()
            .frame;
        assert_ne!(manual_frame.positions, profile_frame.positions);
        assert_eq!(
            ui.application.mesh.as_ref().unwrap().draw_snapshot(),
            authored
        );
        assert_eq!(std::fs::read(root.path().join("jiggle-rig.json"))?, payload);
        Ok(())
    }

    #[test]
    fn changed_assignment_revokes_loaded_profile_even_when_section_is_collapsed() -> TestResult {
        let (_root, mut ui, _) = fixture()?;
        source_profiles(&mut ui);
        ui.application.cdmw_jiggle.preview.cloth_settings.gravity = 3.0;
        ui.click("Authored physics profile")?;
        ui.click("Variant 0")?;
        ui.click("Use profile in preview")?;
        ui.click("Authored physics profile")?;
        ui.application.cdmw_state["physics_profiles"]["parts"][0]["bindings"][0]["profile"] = json!("");
        ui.frame(Vec::new());
        assert_eq!(
            ui.application.cdmw_jiggle.preview.cloth_settings.gravity,
            3.0
        );
        ui.click("Authored physics profile")?;
        assert!(ui.label_rect("Use profile in preview").is_none());
        Ok(())
    }

    #[test]
    fn models_without_cloth_bindings_can_inspect_profiles_without_applying_them() -> TestResult {
        let (_root, mut ui, _) = fixture()?;
        source_profiles(&mut ui);
        ui.application.cdmw_state["replacement"]["parts"] =
            ui.application.cdmw_state["cloth"]["parts"].clone();
        ui.application.cdmw_state["cloth"]["available"] = json!(false);
        ui.application.cdmw_state["cloth"]["reason"] = json!("No cloth bindings.");
        ui.frame(Vec::new());
        ui.click("Authored physics profile")?;
        ui.click("Variant 0")?;
        assert!(ui.label_rect("lower.xml").is_some());
        ui.click("Use profile in preview")?; // The visible control is disabled.
        assert_eq!(
            ui.application.cdmw_jiggle.preview.cloth_settings.gravity,
            9.81
        );
        assert!(ui.application.cdmw_jiggle.preview.scene.is_none());
        Ok(())
    }

    #[test]
    fn spline_missing_and_mixed_assignments_never_supply_cloth_settings() -> TestResult {
        let (_root, mut ui, _) = fixture()?;
        source_profiles(&mut ui);
        ui.click("Authored physics profile")?;
        ui.click("Variant 0")?;
        ui.application.cdmw_state["physics_profiles"]["profiles"][0]["preview"] = Value::Null;
        ui.application.cdmw_state["physics_profiles"]["profiles"][0]["reason"] =
            json!("Spline profile");
        ui.frame(Vec::new());
        assert!(ui.label_rect("Use profile in preview").is_none());
        ui.reveal("Spline profile")?;
        source_profiles(&mut ui);
        let mut other = ui.application.cdmw_state["physics_profiles"]["parts"][0].clone();
        other["index"] = json!(1);
        other["bindings"][0]["path"] = json!("different.xml");
        ui.application.cdmw_state["physics_profiles"]["parts"]
            .as_array_mut()
            .unwrap()
            .push(other);
        let mut part = ui.application.cdmw_state["cloth"]["parts"][0].clone();
        part["index"] = json!(1);
        part["id"] = json!("cloth:1");
        ui.application.cdmw_state["cloth"]["parts"]
            .as_array_mut()
            .unwrap()
            .push(part);
        ui.frame(Vec::new());
        assert!(ui.label_rect("Use profile in preview").is_none());
        ui.application.cdmw_state["physics_profiles"]["parts"][1]["bindings"] = json!([]);
        ui.frame(Vec::new());
        assert!(ui.label_rect("Use profile in preview").is_none());
        Ok(())
    }
}

#[test]
fn physics_detection_shows_spline_evidence_without_a_preview_rig() -> TestResult {
    let (_root, mut ui, _) = fixture()?;
    let authored = ui.application.mesh.as_ref().unwrap().draw_snapshot();
    ui.application.cdmw_state["physics"] = json!({"parts": [{
        "index": 0, "name": "Sword tail", "kind": "spline", "mode_source": "profile",
        "guide_counts": [330, 120, 40, 10], "vertex_counts": [870, 300, 100, 30],
        "jiggle_counts": [0, 0, 0, 0], "current_guide_count": 0,
        "guides": {"status": "available", "guide_count": 6, "fixed_count": 1},
        "profiles": [{"variant": "0", "profile": "WeaponSpline", "mode": "spline"}],
        "preview_reason": "spline_preview_approximate"
    }]});
    ui.application.cdmw_state["jiggle"]["decoded"] = json!({"available": false, "reason": "No matching rig."});
    ui.application.handle_actions(vec![UiAction::SetPartSelection(vec![0])]);
    ui.application.cdmw_pending_request = None; // Selection itself sends a host command.
    ui.settle_layout();
    ui.reveal("Physics: Spline")?;
    ui.reveal("330 / 870 source vertices use guides")?;
    ui.reveal("Guide vertices by LOD: 330 / 120 / 40 / 10")?;
    ui.reveal("Guides: 6 · fixed anchors: 1")?;
    ui.reveal("Current edit: 0 guide vertices")?;
    ui.reveal("Variant 0: WeaponSpline (spline)")?;
    ui.reveal("Controlled spline preview approximates game motion.")?;
    assert!(ui.label_rect("Spline").is_some()); // The Parts row has a badge too.
    ui.application.cdmw_state["physics"]["parts"][0]["jiggle_counts"] = json!([12, 6, 3, 1]);
    ui.settle_layout();
    ui.reveal("Physics: Spline + jiggle")?;
    ui.reveal("12 / 870 source vertices have jiggle contribution")?;
    assert_eq!(ui.application.mesh.as_ref().unwrap().draw_snapshot(), authored);
    assert!(ui.application.cdmw_jiggle.preview.scene.is_none());
    assert!(ui.application.cdmw_pending_request.is_none());
    Ok(())
}

#[test]
fn physics_detection_keeps_unknown_guides_distinct_from_no_bindings() -> TestResult {
    let (_root, mut ui, _) = fixture()?;
    ui.application.cdmw_state["physics"] = json!({"parts": [{
        "index": 0, "name": "Tail", "kind": "guide", "guide_counts": [2, 2, 2, 2],
        "vertex_counts": [3, 3, 3, 3], "jiggle_counts": [0, 0, 0, 0],
        "guides": {"status": "unsupported"}, "reason": "Unknown guide layout"
    }]});
    ui.application.handle_actions(vec![UiAction::SetPartSelection(vec![0])]);
    ui.settle_layout();
    ui.reveal("Physics: Guide bindings")?;
    ui.reveal("Unknown guide layout")?;
    assert!(ui.label_rect("Physics: Spline").is_none());
    ui.application.cdmw_state["physics"]["parts"][0]["kind"] = json!("none");
    ui.application.cdmw_state["physics"]["parts"][0]["guide_counts"] = json!([0, 0, 0, 0]);
    ui.application.cdmw_state["physics"]["parts"][0]["reason"] = json!("");
    ui.settle_layout();
    ui.reveal("Physics: No guide or jiggle bindings")?;
    assert!(ui.label_rect("Physics: Guide bindings").is_none());
    assert!(ui.label_rect("Unknown guide layout").is_none());
    Ok(())
}

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

fn spline_fixture() -> Result<(tempfile::TempDir, HeadlessUi, Vec<u8>), Box<dyn std::error::Error>> {
    let (root, mut ui, bytes) = fixture()?;
    let mut payload: Value = serde_json::from_slice(&bytes)?;
    let a = payload["cloth"]["source_positions"][1].as_array().unwrap();
    let b = payload["cloth"]["source_positions"][2].as_array().unwrap();
    let distance = (0..3).map(|i| (a[i].as_f64().unwrap() - b[i].as_f64().unwrap()).powi(2)).sum::<f64>().sqrt();
    payload["cloth"]["constraints"].as_array_mut().unwrap().push(json!({"kind": "pair", "indices": [1, 2], "rest": distance}));
    payload["cloth"]["spline_chains"] = json!([[0, 1, 2]]);
    payload["cloth"]["alpha_blends"] = json!([1.0, 0.0, 0.0]);
    let bytes = serde_json::to_vec(&payload)?;
    std::fs::write(root.path().join("jiggle-rig.json"), &bytes)?;
    let state = &mut ui.application.cdmw_state["jiggle"]["decoded"];
    state["rig_mode"] = json!("rigid_attachment");
    state["cloth"]["spline_available"] = json!(true);
    state["file"]["byte_length"] = json!(bytes.len());
    state["file"]["sha256"] = json!(format!("{:X}", Sha256::digest(&bytes)));
    ui.frame(Vec::new());
    Ok((root, ui, bytes))
}

#[test]
fn standalone_spline_starts_flexible_retains_tuning_and_resets_to_spline_settings() -> TestResult {
    let (_root, mut ui, _) = spline_fixture()?;
    let settings = ui.application.cdmw_jiggle.preview.cloth_settings;
    assert!(settings.spline);
    assert_eq!(settings.bend, 0.);
    assert_eq!(settings.restore_angle, 0.);
    assert!(settings.rotate_guides && settings.single_edge_rotation && settings.use_vertex_alpha);
    ui.application.cdmw_jiggle.preview.cloth_settings.bend = 0.4;
    ui.application.cdmw_jiggle.preview.cloth_settings.restore_angle = 0.3;
    ui.frame(Vec::new());
    assert_eq!(ui.application.cdmw_jiggle.preview.cloth_settings.bend, 0.4);
    assert_eq!(ui.application.cdmw_jiggle.preview.cloth_settings.restore_angle, 0.3);
    ui.click("Spline preview settings")?;
    ui.click("Reset cloth preview settings")?;
    let reset = ui.application.cdmw_jiggle.preview.cloth_settings;
    assert!(reset.spline);
    assert_eq!(reset.bend, 0.);
    assert_eq!(reset.restore_angle, 0.);
    assert!(reset.rotate_guides && reset.single_edge_rotation && reset.use_vertex_alpha);
    ui.application.cdmw_state["physics"] = json!({"parts": [{"index": 0, "kind": "cloth"}]});
    ui.frame(Vec::new());
    let cloth = ui.application.cdmw_jiggle.preview.cloth_settings;
    assert!(!cloth.spline);
    assert_eq!(cloth.bend, cdmw_mesh::cloth::Settings::default().bend);
    Ok(())
}

#[test]
fn standalone_spline_play_pause_disable_and_reset_keep_authored_mesh_unchanged() -> TestResult {
    let (_root, mut ui, _) = spline_fixture()?;
    let authored = ui.application.mesh.as_ref().unwrap().draw_snapshot();
    ui.click("Spline preview settings")?;
    assert!(ui.reveal("Spring-back response").is_ok());
    ui.click("Play preview")?;
    wait(&mut ui)?;
    advance(&mut ui)?;
    assert!(ui.application.cdmw_jiggle.preview.playing);
    assert_ne!(ui.application.cdmw_jiggle.preview.scene.as_ref().unwrap().frame.positions, authored.positions);
    ui.click("Pause preview")?;
    assert!(!ui.application.cdmw_jiggle.preview.playing);
    ui.click("Resume preview")?;
    ui.click("All disabled")?;
    wait(&mut ui)?;
    advance(&mut ui)?;
    assert_eq!(ui.application.cdmw_jiggle.preview.scene.as_ref().unwrap().frame.positions, authored.positions);
    ui.click("Reset preview")?;
    assert!(ui.application.cdmw_jiggle.preview.scene.is_none());
    assert_eq!(ui.application.mesh.as_ref().unwrap().draw_snapshot(), authored);
    ui.click("Collision sources")?;
    let actions = ui.actions_from_click("Choose body PABV…")?;
    assert!(!actions.iter().any(|action| matches!(action, UiAction::ChooseClothCollisionInput { .. })));
    ui.click("Choose weapon PAC…")?;
    assert!(ui.actions_from_click("External file…")?.iter().any(|action|
        matches!(action, UiAction::ChooseClothCollisionInput { role: "weapon" })));
    ui.application.cdmw_state["jiggle"]["decoded"]["cloth"]["spline_available"] = json!(false);
    ui.frame(Vec::new());
    ui.click("Play preview")?;
    assert!(ui.application.cdmw_jiggle.preview.pending.is_none());
    Ok(())
}

#[test]
fn standalone_spline_does_not_override_an_explicit_cloth_assignment() -> TestResult {
    let (_root, mut ui, _) = spline_fixture()?;
    ui.application.cdmw_state["physics"] = json!({"parts": [{"index": 0, "kind": "cloth"}]});
    ui.frame(Vec::new());
    assert!(!ui.application.cdmw_jiggle.preview.cloth_settings.spline);
    ui.click("Play preview")?;
    assert!(ui.application.cdmw_jiggle.preview.pending.is_none());
    Ok(())
}

#[test]
fn cloth_precision_controls_type_scroll_and_step_without_editing_mesh() -> TestResult {
    let (_root, mut ui, _) = fixture()?;
    let authored = ui.application.mesh.as_ref().unwrap().draw_snapshot();
    ui.click("Cloth preview settings")?;
    let label = ui.reveal("Gravity")?;
    let menu = ui
        .label_rect_where("⋮", |rect| {
            (rect.center().y - label.center().y).abs() < 4.0
        })
        .ok_or("gravity increment menu")?;
    ui.click_at(menu.center());
    ui.click("0.5")?;
    let number = |ui: &HeadlessUi| -> Result<Pos2, Box<dyn std::error::Error>> {
        let label = ui.label_rect("Gravity").ok_or("gravity label")?;
        ui.output
            .shapes
            .iter()
            .find_map(|shape| match &shape.shape {
                egui::Shape::Text(text)
                    if text
                        .galley
                        .job
                        .text
                        .replace('−', "-")
                        .parse::<f64>()
                        .is_ok()
                        && (text.visual_bounding_rect().center().y - label.center().y).abs()
                            < 4.0
                        && text.visual_bounding_rect().right() < label.left() =>
                {
                    Some(text.visual_bounding_rect().center())
                }
                _ => None,
            })
            .ok_or_else(|| "gravity number".into())
    };
    ui.click_at(number(&ui)?);
    ui.frame(vec![
        Event::Text("-9.875".into()),
        key_event(egui::Key::Enter, true),
    ]);
    ui.frame(vec![key_event(egui::Key::Enter, false)]);
    assert_eq!(
        ui.application.cdmw_jiggle.preview.cloth_settings.gravity,
        9.875
    );
    ui.click_at(number(&ui)?);
    ui.frame(vec![Event::MouseWheel {
        unit: egui::MouseWheelUnit::Line,
        delta: egui::vec2(0.0, 1.0),
        phase: egui::TouchPhase::Move,
        modifiers: egui::Modifiers::NONE,
    }]);
    assert_eq!(
        ui.application.cdmw_jiggle.preview.cloth_settings.gravity,
        9.375
    );
    ui.frame(vec![key_event(egui::Key::Enter, true)]);
    ui.frame(vec![key_event(egui::Key::Enter, false)]);
    assert_eq!(
        ui.application.cdmw_jiggle.preview.cloth_settings.gravity,
        9.375
    );
    assert_eq!(
        ui.application.mesh.as_ref().unwrap().draw_snapshot(),
        authored
    );
    Ok(())
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
fn cloth_centred_motion_keeps_rigid_vertices_still_for_every_motion() -> TestResult {
    let (_root, mut ui, _) = fixture()?;
    check_centred_motion_preview(&mut ui)
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
    ui.reveal("No supported guide mesh in this PAC.")?;
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
    for (role, suffix) in [("body", "PABV"), ("head", "PABV"), ("weapon", "PAC")] {
        ui.click(&format!("Choose {role} {suffix}…"))?;
        assert!(ui.actions_from_click("External file…")?.iter().any(
            |action| matches!(action, UiAction::ChooseClothCollisionInput { role: selected } if *selected == role)
        ));
        ui.frame(Vec::new());
        ui.click(&format!("Choose {role} {suffix}…"))?;
        let actions = ui.actions_from_click("Game archives…")?;
        assert!(actions.iter().any(|action| matches!(action,
            UiAction::CdmwCommand { command: "cloth_collision_input", arguments, .. }
            if arguments == &json!({"role": role, "source": "archive"})
        )));
        ui.application.cdmw_pending_request = None;
        ui.frame(Vec::new());
    }
    ui.application.cdmw_state["jiggle"]["collision_inputs"] = json!({"body": "character/model/body/chosen.pabv"});
    ui.application.cdmw_state["jiggle"]["decoded"]["cloth"]["body_collider_source"] = json!("pac_model");
    ui.frame(Vec::new());
    assert!(ui.label_rect("Body volumes: chosen.pabv").is_some());
    assert!(ui.label_rect("Body volumes: character/model/body/chosen.pabv").is_none());
    assert!(ui.actions_from_click("Choose body PABV…")?.is_empty());
    ui.click("Choose weapon PAC…")?;
    assert!(ui.actions_from_click("External file…")?.iter().any(|action|
        matches!(action, UiAction::ChooseClothCollisionInput { role: "weapon" })));
    let actions = ui.actions_from_click("Clear collision inputs")?;
    assert!(actions.iter().any(|action| matches!(action,
        UiAction::CdmwCommand { command: "cloth_collision_input", arguments, .. } if arguments == &json!({"clear": true})
    )));
    assert!(ui.application.cdmw_pending_request.is_some());
    assert_eq!(ui.application.mesh.as_ref().unwrap().draw_snapshot(), authored);
    Ok(())
}

#[test]
fn weapon_export_controls_work_without_guides_and_restore_when_geometry_is_unavailable() -> TestResult {
    let (_root, mut ui, _) = fixture()?;
    ui.application.cdmw_state["cloth"]["available"] = json!(false);
    ui.application.cdmw_state["weapon_collisions"] = json!({"available": true, "active": false});
    ui.frame(Vec::new());
    ui.click("Weapon colliders")?;
    let actions = ui.actions_from_click("Create weapon colliders")?;
    assert!(actions.iter().any(|action| matches!(action,
        UiAction::CdmwCommand { command: "replacement_weapon_collisions", arguments, .. }
        if arguments == &json!({"enabled": true})
    )));
    ui.application.cdmw_pending_request = None;
    ui.application.cdmw_state["weapon_collisions"] = json!({"available": false, "active": true, "reason": "Edited attachment"});
    ui.frame(Vec::new());
    assert!(ui.actions_from_click("Create weapon colliders")?.is_empty());
    let actions = ui.actions_from_click("Restore source colliders")?;
    assert!(actions.iter().any(|action| matches!(action,
        UiAction::CdmwCommand { command: "replacement_weapon_collisions", arguments, .. }
        if arguments == &json!({"enabled": false})
    )));
    Ok(())
}

#[test]
fn weapon_collision_preview_and_overlay_follow_centring_without_authoring_edits() -> TestResult {
    let (root, mut ui, payload) = spline_fixture()?;
    let authored = ui.application.mesh.as_ref().unwrap().draw_snapshot();
    let mut payload: Value = serde_json::from_slice(&payload)?;
    let guide = &payload["cloth"]["animation_frames"][1][3];
    let x = guide[0].as_f64().unwrap();
    let z = guide[2].as_f64().unwrap();
    payload["cloth"]["weapon_colliders"] = json!([{
        "kind": 5, "center1": [x, -10., z], "center2": [x, 10., z], "radius": 0.5,
        "bone_index": 0, "source_ordinal": 0
    }]);
    let payload = serde_json::to_vec(&payload)?;
    std::fs::write(root.path().join("jiggle-rig.json"), &payload)?;
    let state = &mut ui.application.cdmw_state["jiggle"]["decoded"];
    state["file"]["byte_length"] = json!(payload.len());
    state["file"]["sha256"] = json!(format!("{:X}", Sha256::digest(&payload)));
    state["cloth"]["weapon_collider_count"] = json!(1);
    ui.click("Spline preview settings")?;
    ui.click("Play preview")?;
    wait(&mut ui)?;
    advance(&mut ui)?;
    let without = ui.application.cdmw_jiggle.preview.scene.as_ref().unwrap().frame.clone();
    ui.click("Reset preview")?;
    ui.click("Weapon colliders")?;
    ui.click("Weapon collisions")?;
    assert!(ui.application.cdmw_jiggle.preview.cloth_settings.weapon_collisions);
    assert!(!ui.application.cdmw_jiggle.preview.cloth_settings.body_collisions);
    ui.click("Show collision shapes")?;
    wait(&mut ui)?;
    assert!(!ui.application.cdmw_jiggle.preview.playing);
    assert_eq!(ui.application.cdmw_jiggle.preview.scene.as_ref().unwrap().frame.positions, authored.positions);
    assert!(!ui.application.jiggle_collider_lines().is_empty());
    ui.click("Resume preview")?;
    advance(&mut ui)?;
    let scene = ui.application.cdmw_jiggle.preview.scene.as_ref().unwrap();
    assert_ne!(scene.frame.positions[1], without.positions[1]);
    assert_eq!(scene.frame.positions[0], without.positions[0]);
    let centred = ui.application.jiggle_collider_lines();
    assert_eq!(centred.len(), 200);
    ui.click("Keep model centred")?;
    advance(&mut ui)?;
    let scene = ui.application.cdmw_jiggle.preview.scene.as_ref().unwrap();
    let offset = Vec3::from(scene.frame.positions[0]) - Vec3::from(authored.positions[0]);
    let moving = ui.application.jiggle_collider_lines();
    assert!(offset.length() > 0.);
    for (a, b) in centred.iter().zip(&moving) {
        let expected = Vec3::from(a.position) + offset;
        assert!((Vec3::from(b.position) - expected).length() < 1e-5);
        assert_eq!(a.colour, [1., 0.7, 0.15, 1.]);
    }
    ui.click("Show collision shapes")?;
    assert!(ui.application.jiggle_collider_lines().is_empty());
    ui.click("Pause preview")?;
    assert_eq!(ui.application.mesh.as_ref().unwrap().draw_snapshot(), authored);
    assert_eq!(std::fs::read(root.path().join("jiggle-rig.json"))?, payload);
    ui.click("Reset preview")?;
    ui.application.cdmw_state["jiggle"]["decoded"]["cloth"]["weapon_collider_count"] = json!(0);
    ui.frame(Vec::new());
    assert!(!ui.application.cdmw_jiggle.preview.cloth_settings.weapon_collisions);
    Ok(())
}

#[test]
fn cloak_collision_shapes_prepare_without_playback_and_show_both_sources() -> TestResult {
    let (root, mut ui, payload) = fixture()?;
    let authored = ui.application.mesh.as_ref().unwrap().draw_snapshot();
    let mut payload: Value = serde_json::from_slice(&payload)?;
    payload["cloth"]["body_colliders"] = json!([
        {"kind": 1, "center1": [0., 0., 0.], "center2": [0., 0., 0.], "radius": 0.1, "bone_index": 0, "source_ordinal": 0},
        {"kind": 3, "center1": [0., 0., 0.], "center2": [0., 0.5, 0.], "radius": 0.1, "bone_index": 0, "source_ordinal": 1},
        {"kind": 5, "center1": [0., 0., 0.], "center2": [0., 0.5, 0.], "radius": 0.1, "bone_index": 0, "source_ordinal": 2}
    ]);
    payload["cloth"]["weapon_colliders"] = json!([
        {"kind": 5, "center1": [0.2, 0., 0.], "center2": [0.2, 0.5, 0.], "radius": 0.1, "bone_index": 0, "source_ordinal": 0}
    ]);
    let payload = serde_json::to_vec(&payload)?;
    std::fs::write(root.path().join("jiggle-rig.json"), &payload)?;
    let state = &mut ui.application.cdmw_state["jiggle"]["decoded"];
    state["file"]["byte_length"] = json!(payload.len());
    state["file"]["sha256"] = json!(format!("{:X}", Sha256::digest(&payload)));
    state["cloth"]["body_collider_count"] = json!(3);
    state["cloth"]["body_collider_source"] = json!("pac_model");
    state["cloth"]["weapon_collider_count"] = json!(1);
    ui.frame(Vec::new());
    assert!(ui.label_rect("Body collisions").is_none(), "preview settings stay collapsed");
    ui.reveal("Collision shapes: 3 body · 1 weapon")?;
    ui.click("Show collision shapes")?;
    wait(&mut ui)?;
    assert!(!ui.application.cdmw_jiggle.preview.playing);
    advance(&mut ui)?;
    let scene = ui.application.cdmw_jiggle.preview.scene.as_ref().unwrap();
    assert_eq!(scene.frame.positions, authored.positions);
    let lines = ui.application.jiggle_collider_lines();
    assert_eq!(lines.len(), 672);
    assert!(lines.iter().all(|v| Vec3::from(v.position).is_finite()));
    assert_eq!(lines.iter().filter(|v| v.colour == [0.2, 0.85, 1., 1.]).count(), 472);
    assert_eq!(lines.iter().filter(|v| v.colour == [1., 0.7, 0.15, 1.]).count(), 200);
    ui.click("Turning")?;
    wait(&mut ui)?;
    assert!(!ui.application.cdmw_jiggle.preview.playing);
    assert_eq!(ui.application.jiggle_collider_lines().len(), 672);
    ui.click("Cloth preview settings")?;
    ui.click("Body collisions")?;
    ui.click("Weapon colliders")?;
    ui.click("Weapon collisions")?;
    assert!(ui.application.cdmw_jiggle.preview.cloth_settings.body_collisions);
    assert!(ui.application.cdmw_jiggle.preview.cloth_settings.weapon_collisions);
    ui.click("Reset preview")?;
    assert!(ui.application.jiggle_collider_lines().is_empty());
    assert_eq!(ui.application.mesh.as_ref().unwrap().draw_snapshot(), authored);
    assert_eq!(std::fs::read(root.path().join("jiggle-rig.json"))?, payload);
    Ok(())
}

fn load_weapon_reference(root: &std::path::Path, ui: &mut HeadlessUi, payload: &mut Value, x: f64) -> TestResult {
    payload["weapon_reference"] = json!({"positions": [[x, 0., 0.], [x + 0.3, 0., 0.], [x, 1., 0.]], "indices": [0, 1, 2]});
    payload["cloth"]["weapon_colliders"] = json!([
        {"kind": 5, "center1": [x, 0., 0.], "center2": [x, 1., 0.], "radius": 0.1, "bone_index": 0, "source_ordinal": 0}
    ]);
    let bytes = serde_json::to_vec(payload)?;
    std::fs::write(root.join("jiggle-rig.json"), &bytes)?;
    let mut state = ui.application.cdmw_state.clone();
    state["jiggle"]["decoded"]["file"]["byte_length"] = json!(bytes.len());
    state["jiggle"]["decoded"]["file"]["sha256"] = json!(format!("{:X}", Sha256::digest(&bytes)));
    state["jiggle"]["decoded"]["cloth"]["weapon_collider_count"] = json!(1);
    state["jiggle"]["collision_inputs"] = json!({"weapon": "sword.pac"});
    state["jiggle"]["weapon_placement"] = json!({"offset": [x, 0., 0.], "rotation": [0., 0., 0.]});
    ui.application.install_validated_cdmw_state(state, None)?;
    ui.frame(Vec::new());
    Ok(())
}

#[test]
fn weapon_reference_load_place_clear_and_preview_controls_keep_cloak_unchanged() -> TestResult {
    let (root, mut ui, bytes) = fixture()?;
    let authored = ui.application.mesh.as_ref().unwrap().draw_snapshot();
    let mut payload: Value = serde_json::from_slice(&bytes)?;
    load_weapon_reference(root.path(), &mut ui, &mut payload, 0.2)?;
    wait(&mut ui)?;
    advance(&mut ui)?;
    assert!(!ui.application.cdmw_jiggle.preview.playing);
    assert!(!ui.application.jiggle_collider_lines().is_empty());
    let display = ui.application.cdmw_jiggle.preview.scene.as_ref().unwrap().display.clone();
    assert_eq!(display.positions.len(), authored.positions.len() + 3);
    assert_eq!(display.indices.len(), authored.indices.len() + 3);
    assert_eq!(display.triangle_materials.last(), Some(&u32::MAX));
    ui.click("Weapon colliders")?;
    assert!(ui.label_rect("Create weapon colliders").is_none());
    ui.click("Weapon collisions")?;
    assert!(ui.application.cdmw_jiggle.preview.cloth_settings.weapon_collisions);
    assert!(ui.application.cdmw_pending_request.is_none());
    assert!(ui.label_rect("Weapon colliders").unwrap().top() < ui.label_rect("Collision sources").unwrap().top());
    ui.reveal("2 simulated vertices")?;
    let baseline = ui.label_rect("2 simulated vertices").unwrap().top();
    ui.application.submit_cdmw_command("cloth_collision_input",
        json!({"weapon_placement": {"offset": [1.2, 0., 0.], "rotation": [0., 0., 0.]}}), "Place weapon preview");
    ui.settle_layout();
    assert_eq!(ui.label_rect("2 simulated vertices").unwrap().top(), baseline);
    ui.application.cdmw_pending_request = None;
    load_weapon_reference(root.path(), &mut ui, &mut payload, 1.2)?;
    ui.settle_layout();
    assert_eq!(ui.label_rect("2 simulated vertices").unwrap().top(), baseline);
    // Keep the last renderable reference while its replacement loads.
    assert_eq!(ui.application.cdmw_jiggle.preview.scene.as_ref().unwrap().display, display);
    let stale = ui.application.cdmw_jiggle.preview.pending.unwrap();
    load_weapon_reference(root.path(), &mut ui, &mut payload, 1.4)?;
    ui.application.accept_prepared_jiggle(stale, Err("stale weapon placement".into()));
    assert!(ui.application.cdmw_jiggle.preview.pending.is_some());
    wait(&mut ui)?;
    advance(&mut ui)?;
    let scene = ui.application.cdmw_jiggle.preview.scene.as_ref().unwrap();
    assert_eq!(scene.display.positions[authored.positions.len()][0], 1.4);
    assert!(!ui.application.jiggle_collider_lines().is_empty());
    assert_eq!(scene.frame.positions, authored.positions);
    ui.click("Show collision shapes")?;
    assert!(ui.application.jiggle_collider_lines().is_empty());
    assert_eq!(ui.application.cdmw_jiggle.preview.scene.as_ref().unwrap().display.positions.len(), display.positions.len());
    let mut state = ui.application.cdmw_state.clone();
    state["jiggle"]["collision_inputs"] = json!({});
    state["jiggle"]["weapon_placement"] = Value::Null;
    state["jiggle"]["decoded"]["cloth"]["weapon_collider_count"] = json!(0);
    ui.application.install_validated_cdmw_state(state, None)?;
    ui.frame(Vec::new());
    assert!(ui.application.cdmw_jiggle.preview.scene.is_none());
    assert_eq!(ui.application.mesh.as_ref().unwrap().draw_snapshot(), authored);
    Ok(())
}

#[test]
fn weapon_placement_rows_keep_vertical_positions_at_different_values_and_fonts() -> TestResult {
    for font in [10., 14., 18.] {
        let (_root, mut ui, _) = fixture()?;
        ui.application.apply_cdmw_theme_payload(&json!({"font_point_size": font, "density": "comfortable"}));
        ui.application.cdmw_state["jiggle"]["collision_inputs"] = json!({"weapon": "sword.pac"});
        ui.click("Collision sources")?;
        ui.reveal("Clear collision inputs")?;
        let mut baseline: Option<(f32, f32)> = None;
        for value in [0., 0.01, -9.999999999, 100., -100., 1.234567891] {
            ui.application.cdmw_state["jiggle"]["weapon_placement"] = json!({"offset": [value, value, value], "rotation": [value, value, value]});
            ui.settle_layout();
            let positions = (ui.label_rect("Weapon preview rotation").ok_or("rotation label")?.top(),
                ui.label_rect("Clear collision inputs").ok_or("clear label")?.top());
            if let Some(baseline) = baseline {
                assert!((positions.0 - baseline.0).abs() < 0.1 && (positions.1 - baseline.1).abs() < 0.1,
                    "font {font}, value {value}: {positions:?} != {baseline:?}");
            } else { baseline = Some(positions); }
        }
    }
    Ok(())
}

#[test]
fn weapon_reference_invalid_reload_preserves_the_last_renderable_scene() -> TestResult {
    let (root, mut ui, bytes) = fixture()?;
    let mut payload: Value = serde_json::from_slice(&bytes)?;
    load_weapon_reference(root.path(), &mut ui, &mut payload, 0.2)?;
    wait(&mut ui)?;
    advance(&mut ui)?;
    let before = ui.application.cdmw_jiggle.preview.scene.as_ref().unwrap().display.clone();
    payload["weapon_reference"]["indices"] = json!([0, 1, 900]);
    let bytes = serde_json::to_vec(&payload)?;
    std::fs::write(root.path().join("jiggle-rig.json"), &bytes)?;
    let mut state = ui.application.cdmw_state.clone();
    state["jiggle"]["decoded"]["file"]["byte_length"] = json!(bytes.len());
    state["jiggle"]["decoded"]["file"]["sha256"] = json!(format!("{:X}", Sha256::digest(&bytes)));
    ui.application.install_validated_cdmw_state(state, None)?;
    ui.frame(Vec::new());
    wait(&mut ui)?;
    assert_eq!(ui.application.cdmw_jiggle.preview.scene.as_ref().unwrap().display, before);
    ui.reveal("Invalid weapon reference geometry.")?;
    Ok(())
}

#[test]
#[ignore = "synthetic hidden-window D3D12 weapon reference pixels; no game assets"]
fn weapon_reference_renders_solid_pixels_and_clears_without_cloak_changes() -> TestResult {
    use winit::application::ApplicationHandler;
    use winit::event::WindowEvent;
    use winit::event_loop::{ActiveEventLoop, EventLoop};
    use winit::platform::windows::EventLoopBuilderExtWindows;
    use winit::window::{Window, WindowId};

    #[derive(Default)]
    struct Probe(Option<TestResult>);
    impl ApplicationHandler for Probe {
        fn resumed(&mut self, event_loop: &ActiveEventLoop) {
            self.0 = Some(run(event_loop));
            event_loop.exit();
        }
        fn window_event(&mut self, _: &ActiveEventLoop, _: WindowId, _: WindowEvent) {}
    }
    fn run(event_loop: &ActiveEventLoop) -> TestResult {
        let (root, mut ui, bytes) = fixture()?;
        let mut payload: Value = serde_json::from_slice(&bytes)?;
        load_weapon_reference(root.path(), &mut ui, &mut payload, 2.0)?;
        wait(&mut ui)?;
        advance(&mut ui)?;
        let scene = ui.application.cdmw_jiggle.preview.scene.as_ref().unwrap();
        let window = std::sync::Arc::new(event_loop.create_window(Window::default_attributes()
            .with_visible(false).with_inner_size(winit::dpi::PhysicalSize::new(160, 120)))?);
        let mut renderer = pollster::block_on(WindowRenderer::new(window))?;
        renderer.set_clear_colour([0., 0., 0., 1.]);
        renderer.set_camera(glam::Mat4::orthographic_rh(-3., 3., -2., 2., 0.1, 10.)
            * glam::Mat4::look_at_rh(Vec3::new(0., 0., 5.), Vec3::ZERO, Vec3::Y));
        for mode in [ViewMode::TexturedSolid, ViewMode::Solid] {
            renderer.set_view_mode(mode);
            renderer.set_snapshot(&scene.frame)?;
            let cloak = renderer.capture_frame(160, 120, None)?.read_rgba()?;
            renderer.set_snapshot(&scene.display)?;
            let reference = renderer.capture_frame(160, 120, None)?.read_rgba()?;
            assert!(cloak.chunks_exact(4).zip(reference.chunks_exact(4)).filter(|(a, b)| a != b).count() > 20,
                "the weapon reference must produce visible pixels in {mode:?}");
            renderer.set_snapshot(&scene.frame)?;
            assert_eq!(renderer.capture_frame(160, 120, None)?.read_rgba()?, cloak);
        }
        Ok(())
    }
    let event_loop = EventLoop::builder().with_any_thread(true).build()?;
    let mut probe = Probe::default();
    event_loop.run_app(&mut probe)?;
    probe.0.ok_or("weapon pixel probe did not run")?
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
    assert!(ui.label_rect(source_label).is_none(), "source guidance belongs in hover help");
    ui.application.egui_context.style_mut_of(ui.application.egui_context.theme(),
        |style| style.interaction.tooltip_delay = 0.0);
    ui.reveal("Body collisions")?;
    for _ in 0..12 { ui.frame(vec![Event::PointerGone]); }
    let position = ui.label_rect("Body collisions").ok_or("body collisions checkbox")?.center();
    ui.frame(vec![Event::PointerMoved(position)]);
    for _ in 0..3 { ui.frame(Vec::new()); }
    assert!(ui.label_rect(source_label).is_some(), "source guidance remains available on hover");
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
