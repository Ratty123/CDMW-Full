from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


def _module_name(path: Path) -> str:
    relative = path.with_suffix("").as_posix().replace("/", ".")
    return relative.removesuffix(".__init__")


def _imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    module_name = _module_name(path)
    package_name = module_name if path.name == "__init__.py" else module_name.rpartition(".")[0]
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                target = importlib.util.resolve_name(
                    "." * node.level + (node.module or ""),
                    package_name,
                )
            else:
                target = node.module or ""
            if target:
                imports.add(target)
                imports.update(f"{target}.{alias.name}" for alias in node.names if alias.name != "*")
    return imports


# Packages under tools/ that register lazy shell tool tabs. Their Qt modules are
# UI by role even though they sit outside cdmw/ui/, so the UI layer rule applies.
_TOOL_TAB_PACKAGES = (
    "tools/placement_studio",
    "tools/format_explorer",
    "tools/translation_studio",
)
_CORE_IMPLEMENTATION_ROOTS = ("cdmw.core", "cdmw.modding", "cdmw.rendering")


def _imports_core_implementation(imports: set[str]) -> list[str]:
    return sorted(
        name
        for name in imports
        if any(name == root or name.startswith(f"{root}.") for root in _CORE_IMPLEMENTATION_ROOTS)
    )


def test_domain_does_not_import_pyside() -> None:
    for path in Path("cdmw/domain").rglob("*.py"):
        imports = _imports_for(path)
        assert not any(name.startswith("PySide6") for name in imports), path


def test_tool_tab_ui_modules_do_not_import_core_implementations() -> None:
    """Qt surfaces under tools/ obey the same layer rule as cdmw/ui/.

    Reading a format belongs to the domain module beside the window, which is
    what every one of these packages already does -- except that
    window_rig_behaviour.py reached past its own rig_behaviour.py straight to
    cdmw.core. Keying on PySide6 keeps the guard honest as modules are added:
    if it draws, it is UI, and it goes through its sibling.
    """

    offenders: list[tuple[str, str]] = []
    for package in _TOOL_TAB_PACKAGES:
        for path in Path(package).rglob("*.py"):
            imports = _imports_for(path)
            if not any(name.startswith("PySide6") for name in imports):
                continue
            offenders.extend((path.as_posix(), name) for name in _imports_core_implementation(imports))

    assert not offenders, f"Tool-tab UI modules importing core implementations: {offenders}"


def test_domain_does_not_import_modding_layer() -> None:
    for path in Path("cdmw/domain").rglob("*.py"):
        imports = _imports_for(path)
        assert not any(name == "cdmw.modding" or name.startswith("cdmw.modding.") for name in imports), path


def test_domain_does_not_import_core_layer() -> None:
    offenders = {
        path.as_posix(): sorted(
            name for name in _imports_for(path) if name == "cdmw.core" or name.startswith("cdmw.core.")
        )
        for path in Path("cdmw/domain").rglob("*.py")
    }
    assert not {path: imports for path, imports in offenders.items() if imports}


def test_core_does_not_import_services_layer() -> None:
    offenders = {
        path.as_posix(): sorted(
            name for name in _imports_for(path) if name == "cdmw.services" or name.startswith("cdmw.services.")
        )
        for path in Path("cdmw/core").rglob("*.py")
    }
    assert not {path: imports for path, imports in offenders.items() if imports}


def test_services_do_not_import_pyside_widgets() -> None:
    for path in Path("cdmw/services").rglob("*.py"):
        imports = _imports_for(path)
        assert not any(name.startswith("PySide6.QtWidgets") for name in imports), path


def test_workers_do_not_import_ui_packages() -> None:
    for path in Path("cdmw/workers").rglob("*.py"):
        imports = _imports_for(path)
        assert not any(name == "cdmw.ui" or name.startswith("cdmw.ui.") for name in imports), path


def test_rendering_does_not_import_ui_packages() -> None:
    for path in Path("cdmw/rendering").rglob("*.py"):
        imports = _imports_for(path)
        assert not any(name == "cdmw.ui" or name.startswith("cdmw.ui.") for name in imports), path


def test_ui_does_not_import_core_common_or_atomic_file() -> None:
    forbidden = {"cdmw.core.atomic_file", "cdmw.core.common"}
    offenders = {
        path.as_posix(): sorted(name for name in _imports_for(path) if name in forbidden)
        for path in Path("cdmw/ui").rglob("*.py")
    }
    assert not {path: imports for path, imports in offenders.items() if imports}


def test_ui_does_not_import_archive_compatibility_facades() -> None:
    forbidden = {"cdmw.core.archive", "cdmw.core.archive_modding"}
    offenders = {
        path.as_posix(): sorted(
            name
            for name in _imports_for(path)
            if any(name == facade or name.startswith(f"{facade}.") for facade in forbidden)
        )
        for path in Path("cdmw/ui").rglob("*.py")
    }
    assert not {path: imports for path, imports in offenders.items() if imports}


def test_ui_does_not_import_research_compatibility_facade() -> None:
    facade = "cdmw.core.research"
    offenders = {
        path.as_posix(): sorted(
            name
            for name in _imports_for(path)
            if name == facade or name.startswith(f"{facade}.")
        )
        for path in Path("cdmw/ui").rglob("*.py")
    }
    assert not {path: imports for path, imports in offenders.items() if imports}


def test_ui_does_not_import_core_texture_editor_modules() -> None:
    offenders = {
        path.as_posix(): sorted(
            name
            for name in _imports_for(path)
            if name == "cdmw.core.texture_editor" or name.startswith("cdmw.core.texture_editor_")
        )
        for path in Path("cdmw/ui").rglob("*.py")
    }
    assert not {path: imports for path, imports in offenders.items() if imports}


def test_ui_does_not_import_core_mod_package_facades() -> None:
    forbidden = {"cdmw.core.mod_package", "cdmw.core.mod_package_retrofit"}
    offenders = {
        path.as_posix(): sorted(
            name
            for name in _imports_for(path)
            if any(name == facade or name.startswith(f"{facade}.") for facade in forbidden)
        )
        for path in Path("cdmw/ui").rglob("*.py")
    }
    assert not {path: imports for path, imports in offenders.items() if imports}


def test_ui_does_not_import_core_library_facades() -> None:
    forbidden = {"cdmw.core.item_icon", "cdmw.core.model_catalogue"}
    offenders = {
        path.as_posix(): sorted(
            name
            for name in _imports_for(path)
            if any(name == facade or name.startswith(f"{facade}.") for facade in forbidden)
        )
        for path in Path("cdmw/ui").rglob("*.py")
    }
    assert not {path: imports for path, imports in offenders.items() if imports}


def test_ui_does_not_import_preview_implementation_layers() -> None:
    forbidden = {
        "cdmw.core.archive_binary_preview",
        "cdmw.core.archive_mesh_import_preview",
        "cdmw.core.final_package_preview",
        "cdmw.core.model_preview_orientation",
        "cdmw.core.static_model_thumbnail",
        "cdmw.core.texture_pipeline.preview",
        "cdmw.rendering",
    }
    offenders = {
        path.as_posix(): sorted(
            name
            for name in _imports_for(path)
            if any(name == owner or name.startswith(f"{owner}.") for owner in forbidden)
        )
        for path in Path("cdmw/ui").rglob("*.py")
    }
    assert not {path: imports for path, imports in offenders.items() if imports}


def test_ui_does_not_import_low_level_implementation_layers() -> None:
    forbidden_roots = ("cdmw.core", "cdmw.modding", "cdmw.rendering")
    offenders = {
        path.as_posix(): sorted(
            name
            for name in _imports_for(path)
            if any(name == root or name.startswith(f"{root}.") for root in forbidden_roots)
        )
        for path in Path("cdmw/ui").rglob("*.py")
    }
    assert not {path: imports for path, imports in offenders.items() if imports}


def test_entrypoint_does_not_import_ui_or_core_internals() -> None:
    imports = _imports_for(Path("cdmw_app.py"))
    assert imports == {
        "__future__",
        "__future__.annotations",
        "cdmw.app.bootstrap",
        "cdmw.app.bootstrap.main",
    }
