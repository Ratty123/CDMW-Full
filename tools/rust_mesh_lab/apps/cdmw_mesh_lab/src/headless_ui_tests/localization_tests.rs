use super::*;

#[test]
fn native_localization_paints_and_activates_controls_in_every_builtin_language() -> TestResult {
    let mut ui = HeadlessUi::new_integrated_cdmw_for_controls(
        triangle_application()?,
        egui::vec2(1800.0, 1200.0),
    );
    let resources =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../../cdmw/resources/localization");
    // A user can name a layer with a word that is also a translated UI label.
    ui.application.cdmw_state["geometry_layers"]["layers"][0]["name"] = json!("History");
    for code in [
        "de", "es-ES", "es-419", "fr", "it", "pt-BR", "pl", "ru", "tr", "ja", "ko", "zh-Hans",
        "zh-Hant", "en",
    ] {
        let catalog: Value =
            serde_json::from_slice(&std::fs::read(resources.join(format!("{code}.json")))?)?;
        let translations = &catalog["translations"];
        ui.application.apply_cdmw_theme_payload(&json!({
            "language": code, "translations": translations,
        }));
        ui.settle_layout();
        assert!(ui.label_rect("History").is_some(), "{code}: changed a user-authored layer name");
        for source in ["Clear Selection", "Select All", "History"] {
            let label = translations[source].as_str().expect("scalar control label");
            assert!(
                ui.label_rect(label).is_some(),
                "{code}: missing painted {source}: {label}"
            );
            if code != "en" {
                assert_ne!(label, source, "{code}: untranslated {source}");
            }
        }
        let label = translations["Clear Selection"].as_str().unwrap();
        let actions = ui.actions_from_click(label)?;
        assert!(
            actions
                .iter()
                .any(|action| matches!(action, UiAction::ClearSelection)),
            "{code}: translated control lost its action: {actions:?}"
        );
    }
    Ok(())
}
