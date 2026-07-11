from __future__ import annotations

import ast
import subprocess
import sys
from importlib import import_module
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_UI_OWNERS = ("cdmw.core.archive",)
FORBIDDEN_UI_MODULES = {"cdmw.core.prefab_json", "cdmw.core.weapon_swap_templates"}


def test_archive_ui_has_no_direct_core_workflow_imports() -> None:
    violations: list[tuple[str, int, str]] = []
    for path in (ROOT / "cdmw" / "ui").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                if module.startswith(FORBIDDEN_UI_OWNERS) or module in FORBIDDEN_UI_MODULES:
                    violations.append((path.relative_to(ROOT).as_posix(), node.lineno, module))
    assert violations == []


def test_archive_workflow_service_is_cached_lazy_and_preserves_owner_identity() -> None:
    service = import_module("cdmw.services.archive_workflow_service")
    exports = import_module("cdmw.services.archive_workflow_exports").ARCHIVE_WORKFLOW_EXPORTS
    for name in (
        "export_archive_payloads_to_mod_ready_loose",
        "build_prefab_attachment_profile_patch",
        "build_character_swap_plan",
        "ArchiveNameSearchIndex",
        "apply_prefab_edit_json",
    ):
        module_name, attribute_name = exports[name]
        value = getattr(service, name)
        assert value is getattr(import_module(module_name), attribute_name)
        assert service.__dict__[name] is value


def test_cold_archive_workflow_service_import_does_not_import_owners() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import cdmw.services.archive_workflow_service; "
            "assert 'cdmw.core.archive_loose_export' not in sys.modules; "
            "assert 'cdmw.core.archive_relationships' not in sys.modules; "
            "assert 'cdmw.core.prefab_json' not in sys.modules",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_core_archive_contracts_reexport_domain_identity() -> None:
    archive_format = import_module("cdmw.core.archive_format")
    binary_preview = import_module("cdmw.core.archive_binary_preview")
    format_contract = import_module("cdmw.domain.archives.format")
    relationships = import_module("cdmw.core.archive_relationships")
    relationship_contract = import_module("cdmw.domain.archives.relationships")
    attachments = import_module("cdmw.core.archive_attachment_patches")
    attachment_contract = import_module("cdmw.domain.archives.attachments")
    prefab = import_module("cdmw.core.prefab_json")
    prefab_contract = import_module("cdmw.domain.archives.prefab")
    weapon_swap = import_module("cdmw.core.weapon_swap_templates")
    weapon_contract = import_module("cdmw.domain.archives.weapon_swap")

    assert archive_format._is_material_sidecar_extension is format_contract.is_material_sidecar_extension
    assert archive_format.try_decode_text_like_archive_data is format_contract.try_decode_text_like_archive_data
    assert binary_preview.try_decode_text_like_archive_data is format_contract.try_decode_text_like_archive_data
    assert relationships.ArchiveRelationEdge is relationship_contract.ArchiveRelationEdge
    assert relationships.CharacterDependencyPlan is relationship_contract.CharacterDependencyPlan
    assert attachments.PrefabAttachmentProfilePatchResult is attachment_contract.PrefabAttachmentProfilePatchResult
    assert prefab.PrefabEditJsonError is prefab_contract.PrefabEditJsonError
    assert weapon_swap.WeaponSwapSocketRow is weapon_contract.WeaponSwapSocketRow


def test_archive_contract_identity_is_import_order_independent() -> None:
    scripts = (
        "from cdmw.core import archive_relationships as c; "
        "from cdmw.domain.archives import relationships as d; "
        "assert c.ArchiveRelationEdge is d.ArchiveRelationEdge",
        "from cdmw.domain.archives import relationships as d; "
        "from cdmw.core import archive_relationships as c; "
        "assert c.ArchiveRelationEdge is d.ArchiveRelationEdge",
    )
    for script in scripts:
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr or result.stdout


def test_archive_format_contract_keeps_extension_and_text_rules() -> None:
    contract = import_module("cdmw.domain.archives.format")
    assert contract.normalize_archive_extension_filter(" DDS ") == ".dds"
    assert contract.is_material_sidecar_extension(".xml", "hero.pac.xml")
    assert contract.try_decode_text_like_archive_data(b"<root>ok</root>") == "<root>ok</root>"
    assert contract.try_decode_text_like_archive_data(b"\x00\x01\x02\x03") is None
