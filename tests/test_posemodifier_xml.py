"""Gates for the pose-modifier descriptor reader and its surgical editor."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.posemodifier_xml import (  # noqa: E402
    PoseModifierError,
    changed_files,
    encode_posemodifier_xml,
    parse_posemodifier_xml,
    rebuild_is_exact,
    scale_setting,
    set_setting,
    set_values,
)

# Deliberately awkward in the same ways the shipped file is: two roots, an anonymous
# closing tag, a comment, tabs, and a Korean label.
SAMPLE = (
    '<PoseModifierDataList Type="LookAt">\n'
    "\t<DisabledKeyList>\n"
    "\t\t<KeyName>cd_m0009_00_fish.pab</KeyName>\n"
    "\t</DisabledKeyList>\n"
    "\t<PoseModifierData>\n"
    "\t\t<KeyList>\n"
    "\t\t\t<KeyName>phm_01.pab</KeyName>\n"
    "\t\t\t<KeyName>phw_01.pab</KeyName>\n"
    "\t\t</KeyList>\n"
    "\t\t<DefaultData>\n"
    '\t\t\t<Sight ForwardDirAdder="0 0.15 0">\n'
    "\t\t\t\t<YawRange>-70 70</YawRange>\n"
    '\t\t\t\t<PitchRange Basis="Bone">-45 57</PitchRange>\n'
    "\t\t\t</Sight>\n"
    "\t\t</DefaultData>\n"
    "\t</PoseModifierData>\n"
    "</PoseModifierDataList>\n"
    '<PoseModifierDataList Type="Vehicle">\n'
    "\t<PoseModifierData>\n"
    "\t\t<KeyList>\n"
    "\t\t\t<KeyName>cd_r0004_00_wagon_0001.pab</KeyName> <!-- 순환마차 -->\n"
    "\t\t</KeyList>\n"
    "\t\t<DefaultData>\n"
    '\t\t\t<Chassis Bone="B_axle_01" YawLimit="-60.0, 60.0">\n'
    '\t\t\t\t<Wheel Bone="B_wheel_FL_00" Radius="0.53620"/>\n'
    "\t\t\t</Chassis>\n"
    "\t\t</>\n"
    "\t</PoseModifierData>\n"
    "</PoseModifierDataList>\n"
)
SAMPLE_BYTES = ("﻿" + SAMPLE).encode("utf-8")


class ParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = parse_posemodifier_xml(SAMPLE_BYTES)

    def test_both_root_sections_are_found(self) -> None:
        """The file is several documents in one; a strict parser rejects it outright."""

        self.assertEqual(self.doc.sections, ("LookAt", "Vehicle"))

    def test_an_anonymous_closing_tag_does_not_derail_the_scan(self) -> None:
        self.assertTrue(any(s.section == "Vehicle" for s in self.doc.settings))

    def test_keys_are_collected_per_block(self) -> None:
        yaw = next(s for s in self.doc.settings if s.label == "YawRange")
        self.assertEqual(yaw.keys, ("phm_01.pab", "phw_01.pab"))

    def test_a_disabled_list_is_not_mistaken_for_a_key_list(self) -> None:
        self.assertEqual(self.doc.disabled["LookAt"], ("cd_m0009_00_fish.pab",))
        self.assertNotIn("cd_m0009_00_fish.pab", self.doc.keys())

    def test_attribute_and_text_values_are_both_settings(self) -> None:
        labels = {s.label for s in self.doc.settings}
        self.assertIn("Sight.ForwardDirAdder", labels)
        self.assertIn("YawRange", labels)
        self.assertIn("PitchRange.Basis", labels)

    def test_a_comment_becomes_the_note_on_what_follows(self) -> None:
        wheel = next(s for s in self.doc.settings if s.label == "Wheel.Radius")
        self.assertEqual(wheel.note, "순환마차")

    def test_a_comment_closed_with_the_bang_spelling_ends_there(self) -> None:
        """`--!>` closes a comment, and a scanner that only knows `-->` runs past it.

        The element after such a comment would be swallowed as comment text, so the
        document would lose settings silently rather than fail.
        """

        source = (
            '<PoseModifierDataList Type="LookAt">\n'
            "\t<PoseModifierData>\n"
            "\t\t<KeyList>\n"
            "\t\t\t<KeyName>phm_01.pab</KeyName>\n"
            "\t\t</KeyList>\n"
            "\t\t<Sight>\n"
            "\t\t\t<!-- label --!>\n"
            "\t\t\t<YawRange>60</YawRange>\n"
            "\t\t</Sight>\n"
            "\t</PoseModifierData>\n"
            "</PoseModifierDataList>\n"
        ).encode("utf-8")

        doc = parse_posemodifier_xml(source)
        yaw = next(s for s in doc.settings if s.label == "YawRange")
        self.assertEqual(yaw.value, "60")
        self.assertEqual(yaw.note, "label")
        self.assertTrue(rebuild_is_exact(source))

    def test_for_key_matches_case_insensitively(self) -> None:
        self.assertTrue(self.doc.for_key("PHM_01.PAB"))

    def test_numeric_detection(self) -> None:
        by = {s.label: s for s in self.doc.settings}
        self.assertTrue(by["YawRange"].numeric)
        self.assertTrue(by["Chassis.YawLimit"].numeric)
        self.assertFalse(by["PitchRange.Basis"].numeric)
        self.assertFalse(by["Chassis.Bone"].numeric)

    def test_numbers_are_extracted_from_a_range(self) -> None:
        by = {s.label: s for s in self.doc.settings}
        self.assertEqual(by["YawRange"].numbers, (-70.0, 70.0))
        self.assertEqual(by["Sight.ForwardDirAdder"].numbers, (0.0, 0.15, 0.0))

    def test_a_foreign_document_is_refused(self) -> None:
        with self.assertRaises(PoseModifierError):
            parse_posemodifier_xml(b"<html></html>")


class RoundTripTests(unittest.TestCase):
    def test_an_unedited_document_reproduces_its_source(self) -> None:
        self.assertTrue(rebuild_is_exact(SAMPLE_BYTES))
        self.assertEqual(
            encode_posemodifier_xml(parse_posemodifier_xml(SAMPLE_BYTES)), SAMPLE_BYTES
        )

    def test_a_file_without_a_bom_round_trips_too(self) -> None:
        raw = SAMPLE.encode("utf-8")
        doc = parse_posemodifier_xml(raw)
        self.assertEqual(encode_posemodifier_xml(doc, bom=False), raw)

    def test_comments_and_tabs_survive_an_edit(self) -> None:
        doc = parse_posemodifier_xml(SAMPLE_BYTES)
        yaw = next(s for s in doc.settings if s.label == "YawRange")
        out = encode_posemodifier_xml(set_setting(doc, yaw, "-90 90")).decode("utf-8-sig")
        self.assertIn("<!-- 순환마차 -->", out)
        self.assertIn("\t\t\t\t<YawRange>-90 90</YawRange>", out)
        self.assertIn("</>", out)


class EditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = parse_posemodifier_xml(SAMPLE_BYTES)

    def _get(self, label):
        return next(s for s in self.doc.settings if s.label == label)

    def test_an_edit_changes_only_that_value(self) -> None:
        before = self.doc.text
        after = set_setting(self.doc, self._get("YawRange"), "-90 90").text
        self.assertEqual(before.replace("-70 70", "-90 90"), after)

    def test_scaling_keeps_the_shape_of_a_range(self) -> None:
        out = scale_setting(self.doc, self._get("YawRange"), 2.0)
        self.assertEqual(
            next(s for s in out.settings if s.label == "YawRange").value, "-140 140"
        )

    def test_scaling_keeps_separators_in_a_comma_list(self) -> None:
        out = scale_setting(self.doc, self._get("Chassis.YawLimit"), 0.5)
        self.assertEqual(
            next(s for s in out.settings if s.label == "Chassis.YawLimit").value,
            "-30.0, 30.0",
        )

    def test_scaling_a_non_numeric_value_is_refused(self) -> None:
        with self.assertRaises(PoseModifierError):
            scale_setting(self.doc, self._get("Chassis.Bone"), 2.0)

    def test_a_wrong_expected_value_refuses_to_write(self) -> None:
        yaw = self._get("YawRange")
        with self.assertRaises(PoseModifierError):
            set_values(self.doc, {yaw.span: "0 0"}, expected={yaw.span: "nope"})

    def test_a_value_that_would_break_the_markup_is_refused(self) -> None:
        for bad in ('a"b', "a<b", "a>b"):
            with self.subTest(bad=bad):
                with self.assertRaises(PoseModifierError):
                    set_setting(self.doc, self._get("YawRange"), bad)

    def test_several_edits_apply_without_disturbing_each_other(self) -> None:
        """Spans shift as text changes, so they are applied right to left."""

        yaw = self._get("YawRange")
        pitch = self._get("PitchRange")
        out = set_values(
            self.doc,
            {yaw.span: "-100 100", pitch.span: "-1 1"},
            expected={yaw.span: yaw.value, pitch.span: pitch.value},
        )
        by = {s.label: s.value for s in out.settings}
        self.assertEqual(by["YawRange"], "-100 100")
        self.assertEqual(by["PitchRange"], "-1 1")

    def test_an_unchanged_document_exports_nothing(self) -> None:
        self.assertEqual(changed_files(SAMPLE_BYTES, self.doc, "x.xml"), {})

    def test_a_changed_document_exports_its_game_path(self) -> None:
        out = set_setting(self.doc, self._get("YawRange"), "-90 90")
        files = changed_files(SAMPLE_BYTES, out, "x.xml")
        self.assertEqual(list(files), ["x.xml"])
        self.assertTrue(files["x.xml"].startswith(b"\xef\xbb\xbf"))


@pytest.mark.real_game
class VanillaDescriptorTests(unittest.TestCase):
    """The shipped 119 KB descriptor."""

    def _data(self):
        try:
            from tools.placement_studio import corpus
            from tools.placement_studio.rig_behaviour import read_from_archives
        except ImportError:  # the Studio is a separate package and may not be present
            self.skipTest("needs tools.placement_studio for archive access")
        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        return read_from_archives()

    def test_the_shipped_descriptor_round_trips_byte_for_byte(self) -> None:
        data = self._data()
        self.assertTrue(rebuild_is_exact(data))

    def test_it_holds_the_sections_the_engine_names(self) -> None:
        doc = parse_posemodifier_xml(self._data())
        for section in ("Vehicle", "AimIK", "SpineTrain", "LookAt", "LimbIK", "Multileg"):
            self.assertIn(section, doc.sections)
        self.assertGreater(len(doc.settings), 2000)
        self.assertGreater(len(doc.keys()), 50)

    def test_the_player_skeleton_has_settings(self) -> None:
        doc = parse_posemodifier_xml(self._data())
        self.assertGreater(len(doc.for_key("phm_01.pab")), 100)

    def test_editing_one_value_changes_one_value(self) -> None:
        data = self._data()
        doc = parse_posemodifier_xml(data)
        target = next(
            s for s in doc.for_key("phm_01.pab")
            if s.section == "AimIK" and s.label == "AimIK.MaxRotationAngle"
        )
        out = encode_posemodifier_xml(set_setting(doc, target, "110"))
        self.assertEqual(len(out), len(data) + 1)
        again = parse_posemodifier_xml(out)
        changed = [
            (a.label, a.value) for a, b in zip(again.settings, doc.settings)
            if a.value != b.value
        ]
        self.assertEqual(changed, [("AimIK.MaxRotationAngle", "110")])
