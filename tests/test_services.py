from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from cdmw.core.classification_registry import texture_classification_registry_path
from cdmw.services.archive_mutation_service import ArchiveMutationService
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings, prepare_settings_file, resolve_settings_file_path
from cdmw.services.workspace_layout import (
    migrate_legacy_workspace_layout,
    workspace_paths,
)


class _QSettingsStub:
    class Format:
        IniFormat = "ini"

    def __init__(self, path: str, file_format: object) -> None:
        self.path = path
        self.file_format = file_format
        self.fallbacks_enabled: bool | None = None

    def setFallbacksEnabled(self, enabled: bool) -> None:
        self.fallbacks_enabled = bool(enabled)


class _SettingsDict:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values = dict(values or {})
        self.synced = False

    def value(self, key: str, default: object = "") -> object:
        return self.values.get(key, default)

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value

    def sync(self) -> None:
        self.synced = True


class ServiceLayerTests(unittest.TestCase):
    def test_default_container_binds_settings_to_child_services(self) -> None:
        settings = object()
        container = ServiceContainer.create_default(settings=settings)

        self.assertIs(container.archives.settings, settings)
        self.assertIs(container.archive_mutations.settings, settings)
        self.assertIs(container.diagnostics.settings, settings)

        next_settings = object()
        container.bind_settings(next_settings)
        self.assertIs(container.settings, next_settings)
        self.assertIs(container.filesystem.settings, next_settings)

    def test_container_requires_configured_archive_mutation_service(self) -> None:
        service = ArchiveMutationService()
        container = ServiceContainer(archive_mutations=service)

        self.assertIs(service, container.require_archive_mutations())
        container.archive_mutations = None
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            container.require_archive_mutations()

    def test_settings_service_resolves_and_prepares_settings_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            settings_path = resolve_settings_file_path(app_name="WorkbenchTest", base_dir=base_dir)
            legacy_path = settings_path.with_name("LegacyWorkbench.cfg")
            legacy_path.write_text("legacy=true\n", encoding="utf-8")

            prepared_path = prepare_settings_file(settings_path, legacy_app_names=("MissingLegacy", "LegacyWorkbench"))

            self.assertEqual(settings_path, prepared_path)
            self.assertEqual("legacy=true\n", settings_path.read_text(encoding="utf-8"))
            self.assertEqual(base_dir / "texture_classification_registry.json", texture_classification_registry_path())

    def test_create_settings_builds_qsettings_and_disables_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.cfg"

            settings = create_settings(settings_file_path=settings_path, qsettings_cls=_QSettingsStub)

            self.assertIsInstance(settings, _QSettingsStub)
            self.assertEqual(str(settings_path), settings.path)
            self.assertEqual(_QSettingsStub.Format.IniFormat, settings.file_format)
            self.assertFalse(settings.fallbacks_enabled)

    def test_workspace_paths_use_simple_app_workspace(self) -> None:
        root = Path("C:/Workbench")
        paths = workspace_paths(root)

        self.assertEqual(root / "workspace" / "original_dds", paths["original_dds_root"])
        self.assertEqual(root / "workspace" / "staging" / "upscaled_png", paths["png_root"])
        self.assertEqual(root / "workspace" / "outputs" / "rebuilt_textures", paths["output_root"])
        self.assertEqual(root / "workspace" / "outputs" / "mod_packages", paths["mod_ready_export_root"])
        self.assertEqual(root / "workspace" / "cache", paths["archive_cache_root"])
        self.assertEqual(root / "workspace" / "logs", paths["crash_reports_dir"])

    def test_legacy_workspace_migration_moves_default_dirs_and_updates_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "input_dds").mkdir()
            (root / "input_dds" / "source.dds").write_text("dds", encoding="utf-8")
            (root / "dds_final_mod_ready_loose_export").mkdir()
            (root / "dds_final_mod_ready_loose_export" / "Mod").mkdir()
            settings = _SettingsDict(
                {
                    "paths/original_dds_root": str(root / "input_dds"),
                    "paths/output_root": str(root / "outside"),
                    "upscale/mod_ready_export_root": str(root / "dds_final_mod_ready_loose_export"),
                }
            )

            report = migrate_legacy_workspace_layout(root, settings)
            paths = workspace_paths(root)

            self.assertFalse((root / "input_dds").exists())
            self.assertTrue((paths["original_dds_root"] / "source.dds").exists())
            self.assertTrue((paths["mod_ready_export_root"] / "Mod").exists())
            self.assertEqual(str(paths["original_dds_root"]), settings.values["paths/original_dds_root"])
            self.assertEqual(str(root / "outside"), settings.values["paths/output_root"])
            self.assertEqual(str(paths["mod_ready_export_root"]), settings.values["upscale/mod_ready_export_root"])
            self.assertIn("workspace/layout_migration_v1_done", settings.values)
            self.assertEqual(2, len(report.moved))
            self.assertTrue(settings.synced)

    def test_legacy_workspace_migration_skips_destination_conflict_without_deleting_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "archive_cache"
            source.mkdir()
            destination = workspace_paths(root)["archive_cache_root"]
            destination.mkdir(parents=True)

            report = migrate_legacy_workspace_layout(root, _SettingsDict())

            self.assertTrue(source.exists())
            self.assertTrue(destination.exists())
            self.assertEqual([(source, destination, "destination exists")], report.skipped)

    def test_legacy_workspace_migration_never_moves_source_checkout_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
            (root / "cdmw").mkdir()
            source = root / "tools"
            source.mkdir()
            (source / "harness.py").write_text("# source", encoding="utf-8")

            report = migrate_legacy_workspace_layout(root, _SettingsDict())

            self.assertTrue((source / "harness.py").is_file())
            self.assertFalse((root / "workspace" / "tools").exists())
            self.assertEqual([(source, root / "workspace" / "tools", "source checkout")], report.skipped)

    def test_services_do_not_import_pyside_widgets(self) -> None:
        for path in Path("cdmw/services").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
            self.assertFalse(any(name.startswith("PySide6.QtWidgets") for name in imports), path)


if __name__ == "__main__":
    unittest.main()
