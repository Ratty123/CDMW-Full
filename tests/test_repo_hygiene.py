from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".bat",
    ".cfg",
    ".cmd",
    ".css",
    ".html",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".rs",
    ".spec",
    ".toml",
    ".txt",
    ".xml",
    ".yml",
    ".yaml",
}


class RepoHygieneTests(unittest.TestCase):
    def test_tracked_text_files_do_not_contain_local_machine_paths(self) -> None:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        local_user_backslash = "C:" + "\\Users\\Ratrider"
        local_user_slash = "C:" + "/Users/Ratrider"
        patterns = (local_user_backslash, local_user_slash)
        offenders: list[str] = []
        for raw_path in result.stdout.splitlines():
            relative_path = raw_path.strip()
            if not relative_path:
                continue
            path = REPO_ROOT / relative_path
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for pattern in patterns:
                if pattern in text:
                    offenders.append(f"{relative_path}: contains {pattern}")
        self.assertFalse(
            offenders,
            "Tracked text files contain local machine paths:\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
