from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cdmw.build_metadata import (
    windows_file_version_tuple,
    windows_version_resource_text,
    write_windows_version_resource,
)
from cdmw.constants import APP_NAME, APP_ORGANIZATION, APP_REPOSITORY_URL, APP_TITLE, APP_VERSION


class BuildMetadataTests(unittest.TestCase):
    def test_windows_file_version_tuple_uses_prerelease_number_as_revision(self) -> None:
        self.assertEqual((0, 10, 0, 1), windows_file_version_tuple("0.10.0-alpha.1"))
        self.assertEqual((1, 2, 3, 0), windows_file_version_tuple("1.2.3"))
        self.assertEqual((1, 2, 3, 4), windows_file_version_tuple("1.2.3-beta.4"))

    def test_windows_version_resource_contains_app_identity(self) -> None:
        text = windows_version_resource_text(APP_VERSION)

        compile(text, "pyinstaller-version-info.txt", "exec")
        self.assertIn("VSVersionInfo(", text)
        self.assertIn(f"StringStruct('CompanyName', {APP_ORGANIZATION!r})", text)
        self.assertIn(f"StringStruct('FileDescription', {APP_TITLE!r})", text)
        self.assertIn(f"StringStruct('InternalName', {APP_NAME!r})", text)
        self.assertIn(f"StringStruct('OriginalFilename', {APP_NAME + '.exe'!r})", text)
        self.assertIn(f"Official repository: {APP_REPOSITORY_URL}", text)

    def test_write_windows_version_resource_creates_parent_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            output_path = Path(temp_text) / "nested" / "version-info.txt"

            result = write_windows_version_resource(output_path)

            self.assertEqual(output_path, result)
            self.assertTrue(output_path.exists())
            self.assertIn(APP_VERSION, output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
