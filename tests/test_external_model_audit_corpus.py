from __future__ import annotations

import os
import unittest
from pathlib import Path

from cdmw.modding.scene_importer import import_scene_mesh_with_report


def _catalogue_root() -> Path | None:
    value = os.environ.get("CDMW_MODEL_CATALOGUE_ROOT", "").strip()
    if not value:
        return None
    root = Path(value).expanduser()
    return root if root.is_dir() else None


def _find_importable(root: Path, name_fragment: str) -> Path | None:
    fragment = name_fragment.casefold()
    for candidate in root.rglob("*"):
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() not in {".gltf", ".glb", ".obj", ".dae"}:
            continue
        text = str(candidate).casefold()
        if fragment in text:
            return candidate
    return None


@unittest.skipUnless(_catalogue_root() is not None, "CDMW_MODEL_CATALOGUE_ROOT not set")
class ExternalModelAuditCorpusTests(unittest.TestCase):
    def test_verified_sword_samples_have_visible_texture_evidence(self) -> None:
        root = _catalogue_root()
        assert root is not None
        for fragment in ("Serpent-Sword", "sword-5902"):
            path = _find_importable(root, fragment)
            if path is None:
                self.skipTest(f"Missing downloaded sample: {fragment}")
            result = import_scene_mesh_with_report(path)
            self.assertIsNotNone(result.external_audit)
            self.assertEqual("sword", result.external_audit.verified_category)
            self.assertIn("base", result.external_audit.texture_slots)

    def test_axe_and_helmet_samples_are_not_filename_only(self) -> None:
        root = _catalogue_root()
        assert root is not None
        samples = {
            "Zombie-Survival-Hand-Axe": "axe",
            "Wooden-handled-Axe": "axe",
            "Helmet-7280": "helmet",
            "PBR-Tactical-Helmet": "helmet",
        }
        for fragment, expected_category in samples.items():
            path = _find_importable(root, fragment)
            if path is None:
                self.skipTest(f"Missing downloaded sample: {fragment}")
            result = import_scene_mesh_with_report(path)
            self.assertIsNotNone(result.external_audit)
            self.assertEqual(expected_category, result.external_audit.verified_category)
            self.assertGreater(result.external_audit.mesh_count, 0)

    def test_axem_character_sample_is_marked_false_positive(self) -> None:
        root = _catalogue_root()
        assert root is not None
        path = _find_importable(root, "Axem-Green")
        if path is None:
            self.skipTest("Missing downloaded sample: Axem-Green")
        result = import_scene_mesh_with_report(path)
        self.assertIsNotNone(result.external_audit)
        self.assertTrue(result.external_audit.false_positive)
        self.assertTrue(result.external_audit.mixed_model)

