from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOTNET_EDITOR = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET_EDITOR / name).read_text(encoding="utf-8")


def _source_family(stem: str) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(DOTNET_EDITOR.glob(f"{stem}*.cs"))
    )




def test_late_original_reference_completion_routes_to_resident_material_generation() -> None:
    callback_source = (
        ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_remaining_callbacks.py"
    ).read_text(encoding="utf-8")
    helper_source = (
        ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_preview_materials.py"
    ).read_text(encoding="utf-8")
    protocol_source = (
        ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_resources.py"
    ).read_text(encoding="utf-8")

    assert "preview_materials.apply_resolved_original_materials_to_resident_editor(" in callback_source
    assert "_mesh_editor_embedded_apply_reference_material_resources" in helper_source
    assert "apply_reference(preview_model)" in helper_source
    assert 'role="original_reference"' in protocol_source
    assert 'reason="late_original_reference_resources"' in protocol_source
    assert "standalone_dotnet_pending_reference_material_model" in protocol_source


def test_late_modify_original_materials_also_route_to_the_exact_editable_clone() -> None:
    callback_source = (
        ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_remaining_callbacks.py"
    ).read_text(encoding="utf-8")
    helper_source = (
        ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_preview_materials.py"
    ).read_text(encoding="utf-8")
    protocol_source = (
        ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_resources.py"
    ).read_text(encoding="utf-8")

    assert "modify_original_clone_mode=bool(modify_original_clone_mode)" in callback_source
    assert "if modify_original_clone_mode:" in helper_source
    assert "copy_dotnet_preview_material_bindings(" in helper_source
    assert "_mesh_editor_embedded_apply_clone_material_resources" in helper_source
    assert "def apply_resident_clone_material_resources(" in protocol_source
    assert 'reason="late_exact_clone_resources"' in protocol_source
    assert "standalone_dotnet_pending_clone_material_model" in protocol_source
    launch_source = (
        ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_launch.py"
    ).read_text(encoding="utf-8")
    connect_source = (
        ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_protocol.py"
    ).read_text(encoding="utf-8")
    assert launch_source.index("standalone_dotnet_pending_clone_material_model = None") < launch_source.index(
        "standalone_dotnet_package_request_id += 1"
    )
    assert "standalone_dotnet_pending_clone_material_model = None" not in connect_source
