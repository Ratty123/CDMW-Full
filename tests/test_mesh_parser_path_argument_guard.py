"""Pins that the mesh parsers reject a path where they want a payload.

Every parser here is `(data: bytes, filename: str = "")`. Because `filename`
defaults, `parse_mesh(path)` is valid Python: it falls through to the PAM branch
and reads the path's own first four characters as the magic number. The result
is `ValueError: Not a valid PAM file: bad magic 'test'` for anything under
`tests/`, or `bad magic 'C:\\U'` for an absolute Windows path.

That message accuses the asset, not the caller, and it is convincing. It was
read as evidence that 34 real fixture PACs were sanitised placeholders; all 34
parse and contain geometry once the payload is actually passed.

These assertions keep the failure pointed at the caller.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from cdmw.modding.mesh_parser import (
    parse_mesh,
    parse_pac,
    parse_pam,
    parse_pamlod,
)


PARSERS = (
    ("parse_mesh", parse_mesh),
    ("parse_pam", parse_pam),
    ("parse_pac", parse_pac),
    ("parse_pamlod", parse_pamlod),
)


class MeshParserPathArgumentGuardTests(unittest.TestCase):
    def test_str_path_is_rejected_by_every_parser(self) -> None:
        for name, parser in PARSERS:
            with self.subTest(parser=name):
                with self.assertRaises(TypeError) as caught:
                    parser("tests/Extracts/0009/character/model/thing.pac")
                self.assertIn(name, str(caught.exception))

    def test_pathlib_path_is_rejected_by_every_parser(self) -> None:
        for name, parser in PARSERS:
            with self.subTest(parser=name):
                with self.assertRaises(TypeError):
                    parser(Path("C:/games/whatever/thing.pac"))

    def test_rejection_names_the_fix(self) -> None:
        """The message has to say what to do, because the old one sent readers
        looking at the asset instead of the call."""
        with self.assertRaises(TypeError) as caught:
            parse_mesh("tests/Extracts/thing.pac")
        message = str(caught.exception)
        self.assertIn("bytes", message)
        self.assertIn("read_bytes()", message)

    def test_a_path_no_longer_reports_bad_magic(self) -> None:
        """The exact regression: a path used to surface as a corrupt asset."""
        with self.assertRaises(TypeError):
            parse_mesh("tests/Extracts/0009/thing.pac")
        try:
            parse_mesh("tests/Extracts/0009/thing.pac")
        except TypeError as exc:
            self.assertNotIn("bad magic", str(exc))

    def test_bytes_still_reach_the_real_parser(self) -> None:
        """The guard must not swallow genuine payloads.

        What each parser then does with malformed bytes is its own business:
        parse_pam and parse_pac check the magic and raise ValueError, while
        parse_pamlod has no magic check and returns a degenerate mesh. Both are
        pre-existing behaviour. The only thing asserted here is that the guard
        did not fire.
        """
        for name, parser in PARSERS:
            with self.subTest(parser=name):
                try:
                    parser(b"NOTPAR" + b"\x00" * 256, "thing.pac")
                except TypeError as exc:  # pragma: no cover - guard misfire
                    self.fail(f"{name} rejected real bytes as a path: {exc}")
                except Exception:
                    pass  # a format complaint is fine; a TypeError is not

    def test_bytearray_and_memoryview_are_accepted_as_payloads(self) -> None:
        payload = bytearray(b"NOTPAR" + b"\x00" * 256)
        for candidate in (payload, memoryview(bytes(payload))):
            with self.subTest(kind=type(candidate).__name__):
                try:
                    parse_mesh(candidate, "thing.pam")
                except TypeError as exc:  # pragma: no cover - guard misfire
                    self.fail(f"guard rejected {type(candidate).__name__}: {exc}")
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
