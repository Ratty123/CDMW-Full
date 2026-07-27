"""Unit tests for Placement Studio Phase 5: manager packaging.

Synthetic plans and a fake baseline — no game install, no Qt. The corpus gate
(`cli package`) regenerates real golden variants and compares payloads and manifests.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.placement_studio.ops import Operation, Plan
from tools.placement_studio.packaging import (
    DESCRIPTOR_ALIAS_PAIRS,
    IN_GAME_CHECKLIST,
    MANAGER_PROFILES,
    PackageMetadata,
    PackagingError,
    apply_alias_closure,
    build_all,
    build_package,
    build_readme,
    derive_new_paths,
)

_ALIAS, _CANONICAL = DESCRIPTOR_ALIAS_PAIRS[0]
_SOCKETS = "character/descriptors/socketbonedata/1_pc/1_phm/phm_01.pab.sockets.xml"
_CHART = "actionchart/bin__/upperaction/1_pc/1_phm/ride_upper.paac"


class _FakeBaseline:
    """Stands in for the pinned vanilla baseline: membership is all packaging needs."""

    def __init__(self, paths):
        self._paths = set(paths)

    def __contains__(self, path):
        return path in self._paths


def _plan() -> Plan:
    return Plan(
        "test",
        (
            Operation("A", "xml_attr", _SOCKETS, "Pelvis_L_Socket",
                      {"attr": "Translation", "old": "0.000000 0.000000 0.000000",
                       "new": "0.000000 0.020000 0.000000"}),
            Operation("A2", "xml_element_add", _SOCKETS, "Spine2_R_Socket",
                      {"raw": "<Socket Name=\"Spine2_R_Socket\"/>", "after": "", "container": "SocketList"}),
            Operation("B", "xml_attr", _CANONICAL, "CD_MainWeapon_Sword_R",
                      {"attr": "InSocketBone", "old": "Pelvis_L_Socket", "new": "Spine2_R_Socket"}),
            Operation("C", "paac_retarget", _CHART, "Spine2_B_SubWeapon_Socket",
                      {"old": "Spine2_B_SubWeapon_Socket", "new": "Pelvis_L_SubWeapon_Socket",
                       "offsets": [125923]}),
        ),
    )


def _files() -> dict:
    return {
        _SOCKETS: b"<SocketBoneData/>\r\n",
        _CANONICAL: b"<CharacterDescription/>\r\n",
        _ALIAS: b"<CharacterDescription/>\r\n",
        _CHART: b"PAAC-bytes",
    }


def _metadata() -> PackageMetadata:
    return PackageMetadata(
        name="Test Placement Mod",
        version="1.2.3",
        author="Ratrider",
        description="Moves the sword to back carry.",
    )


class NewPathTests(unittest.TestCase):
    def test_only_paths_absent_from_vanilla_are_new(self) -> None:
        baseline = _FakeBaseline([_SOCKETS, _CANONICAL, _CHART])
        self.assertEqual(derive_new_paths([_SOCKETS, _CHART], baseline), [])

    def test_the_guide_rule_declares_both_descriptor_halves(self) -> None:
        """"If either path is in new_paths, both should be" — a manager quirk, encoded."""

        baseline = _FakeBaseline([_CANONICAL])  # the alias is genuinely new
        derived = derive_new_paths([_ALIAS, _CANONICAL], baseline)
        self.assertEqual(derived, sorted([_ALIAS, _CANONICAL]))

    def test_closure_does_not_invent_paths_the_package_does_not_ship(self) -> None:
        # Only the alias is shipped, so the canonical must not be declared.
        self.assertEqual(apply_alias_closure([_ALIAS], [_ALIAS]), [_ALIAS])

    def test_closure_is_a_no_op_without_alias_paths(self) -> None:
        self.assertEqual(apply_alias_closure([_SOCKETS], [_SOCKETS, _CHART]), [_SOCKETS])


class ReadmeTests(unittest.TestCase):
    def test_readme_reports_every_tier_and_the_checklist(self) -> None:
        text = build_readme(
            _plan(), _metadata(), manager="DMM",
            payload_paths=list(_files()), new_paths=[_ALIAS],
        )
        self.assertIn("socket transform edits", text)
        self.assertIn("socket definitions created", text)
        self.assertIn("descriptor routing edits", text)
        self.assertIn("action-chart socket retargets", text)
        for item in IN_GAME_CHECKLIST:
            self.assertIn(item, text)

    def test_readme_spells_out_actual_value_changes(self) -> None:
        text = build_readme(
            _plan(), _metadata(), manager="DMM", payload_paths=[], new_paths=[]
        )
        self.assertIn("Pelvis_L_Socket.Translation", text)
        self.assertIn("CD_MainWeapon_Sword_R.InSocketBone: Pelvis_L_Socket -> Spine2_R_Socket", text)
        self.assertIn("Spine2_R_Socket", text)

    def test_readme_explains_the_same_length_retarget_guarantee(self) -> None:
        text = build_readme(_plan(), _metadata(), manager="DMM", payload_paths=[], new_paths=[])
        self.assertIn("Pelvis_L_SubWeapon_Socket", text)
        self.assertIn("size is unchanged", text)

    def test_new_files_are_called_out(self) -> None:
        text = build_readme(
            _plan(), _metadata(), manager="JMM", payload_paths=[], new_paths=[_ALIAS]
        )
        self.assertIn("New files (not present in vanilla)", text)
        self.assertIn(_ALIAS, text)


class LayoutTests(unittest.TestCase):
    def _build(self, manager: str, directory: str):
        return build_package(
            manager, _plan(), _files(), _metadata(),
            out_root=Path(directory) / manager,
            baseline=_FakeBaseline([_SOCKETS, _CANONICAL, _CHART]),
            created_utc="2026-07-27T12:00:00+00:00",
        )

    def test_cdumm_nests_payloads_under_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._build("CDUMM", directory)
            self.assertTrue((result.root / "files" / "character").is_dir())
            self.assertTrue((result.root / ".no_encrypt").is_file())
            self.assertTrue((result.root / "manifest.json").is_file())

    def test_dmm_keeps_the_game_tree_at_the_root_and_has_no_no_encrypt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._build("DMM", directory)
            self.assertTrue((result.root / "character").is_dir())
            self.assertFalse((result.root / ".no_encrypt").exists())

    def test_jmm_writes_mod_json_and_no_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._build("JMM", directory)
            self.assertTrue((result.root / "mod.json").is_file())
            self.assertFalse((result.root / "manifest.json").exists())

    def test_jmm_declares_loose_mod_not_archive_loose_mod(self) -> None:
        # The goldens use loose_mod here; passing the archive kind produced a silent mismatch.
        with tempfile.TemporaryDirectory() as directory:
            result = self._build("JMM", directory)
            payload = json.loads((result.root / "mod.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["kind"], "loose_mod")

    def test_payload_bytes_survive_the_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._build("DMM", directory)
            for path, data in _files().items():
                self.assertEqual((result.root / path).read_bytes(), data)

    def test_metadata_version_reaches_the_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._build("DMM", directory)
            payload = json.loads((result.root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], "1.2.3")
            self.assertEqual(payload["created_utc"], "2026-07-27T12:00:00+00:00")

    def test_unknown_manager_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PackagingError):
                build_package("NOPE", _plan(), _files(), _metadata(), out_root=Path(directory))

    def test_empty_plan_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PackagingError):
                build_package("DMM", _plan(), {}, _metadata(), out_root=Path(directory))


class BuildAllTests(unittest.TestCase):
    def test_one_plan_emits_every_manager_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            results = build_all(
                _plan(), _files(), _metadata(),
                out_root=Path(directory),
                baseline=_FakeBaseline([_SOCKETS, _CANONICAL, _CHART]),
                created_utc="2026-07-27T12:00:00+00:00",
            )
            self.assertEqual([r.manager for r in results], ["CDUMM", "DMM", "JMM"])
            for result in results:
                self.assertEqual(result.file_count, len(_files()))
                self.assertTrue((result.root / "README.txt").is_file())

    def test_every_profile_is_buildable(self) -> None:
        self.assertEqual(set(MANAGER_PROFILES), {"CDUMM", "DMM", "JMM"})


if __name__ == "__main__":
    unittest.main()
