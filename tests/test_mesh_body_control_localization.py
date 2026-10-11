"""Focused discovery checks for Rust body controls and typed catalogue labels."""

from pathlib import Path

from cdmw.domain.mesh.body_region_sliders import DEFAULT_BODY_REGION_SLIDER_TEMPLATES
from cdmw.domain.mesh.body_regions import DEFAULT_BODY_REGION_RULES, sided_region_label
from cdmw.domain.mesh.morph_layers import _MACROS
from scripts import generate_ui_localization_manifest as generator
from scripts import rust_ui_localization


def test_rust_localization_discovers_body_and_outfit_child_modules(tmp_path: Path) -> None:
    root = tmp_path / rust_ui_localization.RUST_UI_DIRECTORY / "cdmw_ui"
    root.mkdir(parents=True)
    (root / "morph_body_controls.rs").write_text(
        'fn draw() { ui.label(tr("Body controls")); let command = "morph_set_macro"; }\n'
        '#[cfg(test)] mod tests { const LABEL: &str = "Test-only macro caption"; }\n',
        encoding="utf-8",
    )
    (root / "morph_outfit_workflows.rs").write_text(
        'fn draw() { ui.label(tr("Matching fitting setups")); let command = "morph_apply_setup"; }\n',
        encoding="utf-8",
    )

    sources = rust_ui_localization.scan(tmp_path)

    assert set(sources) == {"Body controls", "Matching fitting setups"}
    for text, filename in (
        ("Body controls", "morph_body_controls.rs"),
        ("Matching fitting setups", "morph_outfit_workflows.rs"),
    ):
        assert sources[text] == [{
            "path": (rust_ui_localization.RUST_UI_DIRECTORY / "cdmw_ui" / filename).as_posix(),
            "line": 1,
            "sink": "rust-presentation",
        }]


def test_manifest_harvests_finite_body_labels_for_native_translation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    monkeypatch.setattr(generator, "PYTHON_SOURCE_ROOTS", ())
    monkeypatch.setattr(generator, "EXCLUSIONS_PATH", tmp_path / "missing-exclusions.json")
    monkeypatch.setattr(generator, "_load_existing_manual_sources", lambda: set())
    manifest = generator.build_manifest()
    entries = {entry["key"]: entry["origins"] for entry in manifest["entries"]}
    native_keys = set(generator._native_ui_keys(manifest))

    expected = {
        (text, "cdmw/domain/mesh/morph_layers.py")
        for macro in _MACROS for text in (macro.label, macro.description)
    }
    for region in DEFAULT_BODY_REGION_RULES:
        expected.add((region.group, "cdmw/domain/mesh/body_regions.py"))
        for side in (("center", "left", "right") if region.sided else ("center",)):
            label = sided_region_label(region, side)
            expected.add((label, "cdmw/domain/mesh/body_regions.py"))
            expected.update(
                (f"{label} {template.label}", "cdmw/domain/mesh/body_region_sliders.py")
                for template in DEFAULT_BODY_REGION_SLIDER_TEMPLATES
            )
        if region.sided:
            expected.update(
                (f"{region.label} {template.label}", "cdmw/domain/mesh/morph_layers.py")
                for template in DEFAULT_BODY_REGION_SLIDER_TEMPLATES
            )

    for text, path in expected:
        assert text in native_keys
        assert any(row["path"] == path and row["sink"] == "rust-presentation" for row in entries[text])
    assert "Clavicle (Left) Size" in entries
    assert "Clavicle Size" in entries
    assert all(macro.macro_id not in entries for macro in _MACROS)
    assert "clavicle_l_size" not in entries


def test_body_generation_reasons_and_profile_name_reach_native_keys(monkeypatch) -> None:
    relative = "cdmw/services/mesh_service_body_controls.py"
    monkeypatch.setattr(generator, "PYTHON_SOURCE_ROOTS", (generator.ROOT / relative,))
    sources = generator._scan_python()
    expected = {
        "Save or discard the captured slider before generating body controls.",
        "Save or cancel the outfit correction before generating body controls.",
        "Resolve the changed body topology before generating body controls.",
        "Finish the active edit before generating body controls.",
        "Reset or Bake the active sliders before generating body controls.",
        "Assign the body Parts before generating body controls.",
        "Anatomical Body Controls",
    }
    assert expected.issubset(sources)
    assert any(
        row["sink"] == "python-return:_body_controls_availability_locked"
        for row in sources["Finish the active edit before generating body controls."]
    )
    manifest = {"entries": [
        {"key": text, "origins": rows} for text, rows in sorted(sources.items())
    ]}
    manifest["entries"].append({
        "key": "Unrelated service message",
        "origins": [{"path": "cdmw/services/other_service.py", "sink": "ValueError"}],
    })

    native_keys = set(generator._native_ui_keys(manifest))

    assert expected.issubset(native_keys)
    assert "Unrelated service message" not in native_keys
    assert "body_regions_{value_0}" not in native_keys
