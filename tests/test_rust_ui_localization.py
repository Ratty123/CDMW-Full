"""Inventory contracts for the native presentation, without building Rust."""

from scripts.rust_ui_localization import RUST_UI_DIRECTORY, scan


def test_native_inventory_extracts_labels_and_formats_but_not_ids_comments_or_tests(tmp_path):
    directory = tmp_path / RUST_UI_DIRECTORY
    directory.mkdir(parents=True)
    (directory / "cdmw_ui.rs").write_text('''
        // A comment is not an interface caption.
        /* Neither is a /* nested */ comment. */
        fn controls() {
            let identifier = "internal_command";
            ui.button("Apply changes");
            ui.label(format!("LOD {lod}: {count:.2} vertices"));
            ui.label(r#"Choose a "mesh""#);
        }
        #[cfg(test)]
        mod tests {
            fn fixture() { ui.label("Only in a test"); }
        }
    ''', encoding="utf-8")
    (directory / "cdmw_jiggle.rs").write_text('''
        const SETTINGS: [(&str, &str); 1] = [("Linear response", "For example, a stronger pull catches up faster.")];
        fn controls() { ui.checkbox(&mut centred, "Keep model centred"); }
    ''', encoding="utf-8")
    inventory = scan(tmp_path)
    assert set(inventory) == {
        "Apply changes", "LOD {value_0}: {value_1} vertices", 'Choose a "mesh"',
        "Linear response", "For example, a stronger pull catches up faster.", "Keep model centred",
    }
    assert all(row["sink"] == "rust-presentation" for rows in inventory.values() for row in rows)
