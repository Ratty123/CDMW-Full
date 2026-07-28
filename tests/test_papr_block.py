"""Structural gates for the `.papr` block decoder.

Behaviour tests over synthesised blocks: each builds bytes in the documented grammar and
asserts what comes back, so a change that breaks decoding fails here rather than quietly
reporting everything as partial again.
"""

from __future__ import annotations

import struct
import unittest

import pytest

from cdmw.core.papr_block import decode_block


def _rec(tag: int, typ: int, val: int = 0) -> bytes:
    return bytes((tag, typ, val))


def _s(text: str) -> bytes:
    raw = text.encode("ascii")
    return struct.pack("<H", len(raw)) + raw


def _drivers(*pairs: tuple[str, float], limits: tuple[float, ...] = (0.0, 0.0, 0.0, 1.0)) -> bytes:
    out = bytes((len(pairs),))
    for name, weight in pairs:
        out += _s(name) + struct.pack("<f", weight)
    return out + b"\x00" + struct.pack(f"<{len(limits)}f", *limits)


def _expression(node: str, variables: tuple[tuple[int, str], ...], text: str) -> bytes:
    out = _s(node) + b"\x00" + struct.pack("<H", len(variables))
    for kind, name in variables:
        out += bytes((kind,)) + _s(name) + b"\x00"
    return out + b"\x00" + _s(text)


def _drivers_only(*pairs: tuple[str, float]) -> bytes:
    """A `04 04` list: no limit run after the sentinel."""

    out = bytes((len(pairs),))
    for name, weight in pairs:
        out += _s(name) + struct.pack("<f", weight)
    return out + b"\x00"


def _bound_node(name: str, limits: int = 4) -> bytes:
    return b"\x00" + _s(name) + struct.pack(f"<{limits}f", *([0.0] * limits))


OPEN = _rec(0x05, 0x03)
CLOSE = _rec(0x07, 0x05)
SCALAR = _rec(0x10, 0x01)
MEMBER = _rec(0x06, 0x04)


class CanonicalTests(unittest.TestCase):
    """The 9-record shape that was the only one understood before."""

    def test_the_canonical_block_decodes_completely(self) -> None:
        block = OPEN + SCALAR * 3 + MEMBER + SCALAR * 3 + CLOSE

        decoded = decode_block(block)

        self.assertTrue(decoded.complete, decoded.note)
        self.assertEqual(decoded.record_count, 9)
        self.assertEqual(decoded.groups, ())

    def test_the_same_shape_without_its_close_also_decodes(self) -> None:
        """102 corpus blocks are exactly this, and all read as opaque before."""

        decoded = decode_block(OPEN + SCALAR * 3 + MEMBER + SCALAR * 3)

        self.assertTrue(decoded.complete, decoded.note)
        self.assertEqual(decoded.record_count, 8)


class DriverListTests(unittest.TestCase):
    def test_drivers_and_their_weights_come_back(self) -> None:
        block = OPEN + _rec(0x03, 0x04) + _drivers(("Bip01 Pelvis", 50.0), ("Bip01 Spine", 30.0)) + CLOSE

        decoded = decode_block(block)

        self.assertTrue(decoded.complete, decoded.note)
        self.assertEqual([d.name for d in decoded.drivers], ["Bip01 Pelvis", "Bip01 Spine"])
        self.assertEqual([d.weight for d in decoded.drivers], [50.0, 30.0])

    def test_four_limit_floats_follow_a_driver_list_by_default(self) -> None:
        # Values that are exact in float32, so the assertion is about the layout rather
        # than about single-precision rounding.
        block = OPEN + _rec(0x03, 0x04) + _drivers(("A", 50.0), limits=(-0.5, -0.25, 0.25, 0.5)) + CLOSE

        decoded = decode_block(block)

        self.assertTrue(decoded.complete, decoded.note)
        self.assertEqual(decoded.groups[0].limits, (-0.5, -0.25, 0.25, 0.5))

    def test_a_channel_record_lengthens_the_limits(self) -> None:
        """`0a 04`'s high byte is what made the tail 4, 5 or 6 floats in the corpus."""

        limits = (0.0, 0.0, 0.0, 1.0, 1.0)
        block = (
            OPEN
            + _rec(0x0A, 0x04) + b"\x00\x01"
            + _rec(0x03, 0x04) + _drivers(("A", 50.0), limits=limits)
            + CLOSE
        )

        decoded = decode_block(block)

        self.assertTrue(decoded.complete, decoded.note)
        self.assertEqual(len(decoded.groups[0].limits), 5)

    def test_the_channel_count_does_not_leak_into_a_block_that_lacks_it(self) -> None:
        four = OPEN + _rec(0x03, 0x04) + _drivers(("A", 1.0)) + CLOSE
        self.assertEqual(len(decode_block(four).groups[0].limits), 4)


class ExpressionTests(unittest.TestCase):
    """The payload that turned 1,148 opaque blocks into readable rules."""

    def test_the_formula_and_its_variables_come_back(self) -> None:
        block = (
            OPEN
            + _rec(0x11, 0x01)
            + _expression("Bip01 L Calf:1:2", ((1, "Bip01 L Calf:1:2"),),
                          "amin(Local_Euler_Z*5.5+20) 8")
            + CLOSE
        )

        decoded = decode_block(block)

        self.assertTrue(decoded.complete, decoded.note)
        expression = decoded.expressions[0]
        self.assertEqual(expression.node, "Bip01 L Calf:1:2")
        self.assertEqual(expression.variables, ((1, "Bip01 L Calf:1:2"),))
        self.assertEqual(expression.text, "amin(Local_Euler_Z*5.5+20) 8")

    def test_an_expression_with_no_variables_decodes(self) -> None:
        block = OPEN + _rec(0x11, 0x01) + _expression("N", (), "-Local_Euler_Z*3+30.5") + CLOSE

        decoded = decode_block(block)

        self.assertTrue(decoded.complete, decoded.note)
        self.assertEqual(decoded.expressions[0].text, "-Local_Euler_Z*3+30.5")

    def test_several_variables_are_all_read(self) -> None:
        block = (
            OPEN
            + _rec(0x11, 0x01)
            + _expression("N", ((1, "A"), (2, "B"), (1, "C")), "A+B*C")
            + CLOSE
        )

        decoded = decode_block(block)

        self.assertTrue(decoded.complete, decoded.note)
        self.assertEqual([name for _kind, name in decoded.expressions[0].variables], ["A", "B", "C"])

    def test_a_plain_name_reference_is_not_read_as_an_expression(self) -> None:
        """`12 01` carries a bare string; reading it as an expression desynced the walk."""

        block = OPEN + _rec(0x12, 0x01) + _s("Bip01 R Thigh") + CLOSE

        decoded = decode_block(block)

        self.assertTrue(decoded.complete, decoded.note)
        self.assertEqual(decoded.names, ("Bip01 R Thigh",))
        self.assertEqual(decoded.expressions, ())


class DriverTagTests(unittest.TestCase):
    """The two driver tags differ, and reading them alike swallowed later records."""

    def test_tag_three_takes_the_limits_after_its_list(self) -> None:
        block = OPEN + _rec(0x03, 0x04) + _drivers(("A", 50.0)) + CLOSE

        decoded = decode_block(block)

        self.assertTrue(decoded.complete, decoded.note)
        self.assertEqual(len(decoded.groups[0].limits), 4)

    def test_tag_four_takes_none_and_lets_records_follow(self) -> None:
        """With limits read here, the four floats ate the records after the list."""

        block = OPEN + _rec(0x04, 0x04) + _drivers_only(("A", 50.0)) + SCALAR + CLOSE

        decoded = decode_block(block)

        self.assertTrue(decoded.complete, decoded.note)
        self.assertEqual(decoded.groups[0].limits, ())
        self.assertEqual(decoded.record_count, 4)


class BoundNodeTests(unittest.TestCase):
    """A driver payload can carry a bound node, and it is not a record."""

    def test_a_bound_node_is_read_and_not_counted_as_a_record(self) -> None:
        block = (
            OPEN
            + _rec(0x04, 0x04) + _drivers_only(("A", 50.0))
            + _rec(0x01, 0x01) + _bound_node("Bip01 L Hand")
            + CLOSE
        )

        decoded = decode_block(block)

        self.assertTrue(decoded.complete, decoded.note)
        self.assertIn("Bip01 L Hand", decoded.names)
        # open, drivers, close. The bound node is payload, per the header's own total.
        self.assertEqual(decoded.record_count, 3)

    def test_a_bound_node_takes_the_channel_count_too(self) -> None:
        block = (
            OPEN
            + _rec(0x0A, 0x04) + b"\x00"
            + _rec(0x04, 0x04) + _drivers_only(("A", 50.0))
            + _rec(0x01, 0x01) + _bound_node("N", limits=5)
            + CLOSE
        )

        self.assertTrue(decode_block(block).complete, decode_block(block).note)


class FrameTests(unittest.TestCase):
    def test_a_frame_record_carries_a_zero_and_three_floats(self) -> None:
        block = OPEN + _rec(0x01, 0x03) + b"\x00" + struct.pack("<3f", 0.5, 0.25, 0.125) + CLOSE

        decoded = decode_block(block)

        self.assertTrue(decoded.complete, decoded.note)
        self.assertEqual(decoded.record_count, 3)


class RefusalTests(unittest.TestCase):
    """A block that does not fit is reported, never guessed past."""

    def test_an_unknown_tag_stops_the_walk_and_says_where(self) -> None:
        block = OPEN + _rec(0x7E, 0x04) + b"\xff\xff" + CLOSE

        decoded = decode_block(block)

        self.assertFalse(decoded.complete)
        self.assertEqual(decoded.stopped_at, 3)
        self.assertIn("0x7e", decoded.note)

    def test_an_unknown_record_type_stops_the_walk(self) -> None:
        decoded = decode_block(OPEN + _rec(0x05, 0x02) + CLOSE)

        self.assertFalse(decoded.complete)
        self.assertIn("no payload rule", decoded.note)

    def test_a_block_with_bytes_left_over_is_not_complete(self) -> None:
        decoded = decode_block(OPEN + CLOSE + b"\x01\x02")

        self.assertFalse(decoded.complete)
        self.assertIn("trailing bytes", decoded.note)

    def test_a_truncated_driver_list_is_refused_rather_than_partly_read(self) -> None:
        block = OPEN + _rec(0x03, 0x04) + b"\x02" + _s("A") + struct.pack("<f", 1.0)

        decoded = decode_block(block)

        self.assertFalse(decoded.complete)
        self.assertEqual(decoded.groups, ())

    def test_a_non_ascii_string_is_refused(self) -> None:
        block = OPEN + _rec(0x12, 0x01) + struct.pack("<H", 3) + b"\x01\x02\x03" + CLOSE

        decoded = decode_block(block)

        self.assertFalse(decoded.complete)
        self.assertIn("printable", decoded.note)

    def test_what_decoded_before_the_stop_is_still_returned(self) -> None:
        """A partly-read block still shows its drivers; it just is not called complete."""

        block = OPEN + _rec(0x03, 0x04) + _drivers(("A", 25.0)) + _rec(0x7E, 0x04) + b"\xff\xff"

        decoded = decode_block(block)

        self.assertFalse(decoded.complete)
        self.assertEqual([d.name for d in decoded.drivers], ["A"])


class EmptyTests(unittest.TestCase):
    def test_an_empty_block_is_complete_and_holds_nothing(self) -> None:
        decoded = decode_block(b"")

        self.assertTrue(decoded.complete)
        self.assertEqual(decoded.record_count, 0)


if __name__ == "__main__":
    unittest.main()


@pytest.mark.real_game
class VanillaBlockTests(unittest.TestCase):
    """The grammar against the shipped rigs, with the header's own oracle."""

    def _rigs(self):
        from cdmw.core.archive_extraction import read_archive_entry_data
        from tools.placement_studio import corpus

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
            path = corpus.normalize_game_path(entry.path)
            if path.endswith(".papr"):
                data, _decompressed, _note = read_archive_entry_data(entry)
                yield path, data

    def _decoded(self):
        from cdmw.core.papr_format import PaprFormatError, parse_papr

        blocks = complete = expressions = 0
        exact_rigs = 0
        for path, data in self._rigs():
            try:
                document = parse_papr(data, name=path)
            except PaprFormatError:
                continue
            walked = 0
            every = True
            for entry in document.entries:
                if not entry.block:
                    continue
                blocks += 1
                decoded = decode_block(entry.block)
                if not decoded.complete:
                    every = False
                    continue
                complete += 1
                walked += decoded.record_count
                expressions += len(decoded.expressions)
            # `record_count` counts every record in the file. It is only a fair check on a
            # rig whose blocks all decode; elsewhere the walk is legitimately short.
            if every and walked == document.header.record_count:
                exact_rigs += 1
        if not blocks:
            self.skipTest("no .papr entries in the archives")
        return blocks, complete, expressions, exact_rigs

    def test_most_of_the_corpus_now_decodes_completely(self) -> None:
        """A ratchet, not an equality: 78.4% at the time of writing, from 26.8%."""

        blocks, complete, _expressions, _exact = self._decoded()

        self.assertGreaterEqual(complete / blocks, 0.76, f"{complete}/{blocks}")

    def test_the_driver_formulas_are_recovered(self) -> None:
        _blocks, _complete, expressions, _exact = self._decoded()

        self.assertGreaterEqual(expressions, 1000, expressions)

    def test_a_rig_that_fully_decodes_reproduces_its_declared_record_count(self) -> None:
        """The header's own total is the one check that does not come from this grammar."""

        _blocks, _complete, _expressions, exact = self._decoded()

        # Four rigs decode end to end and all four reproduce their declared total. That
        # agreement is the whole reason to trust the rules the walk is built from.
        self.assertGreaterEqual(exact, 4, "fewer rigs agree with their header than before")
