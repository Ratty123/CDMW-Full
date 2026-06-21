#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("cdmw", "tests", "tools")
IGNORE_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "app_restore_points",
    "archive_cache",
    "build",
    "crash_reports",
    "dist",
    "graphify-out",
    "htmlcov",
    "item_icon_library",
    "test_artifacts",
    "test_outputs",
}
KEY_DOCS = (
    "AGENTS.md",
    "docs/release-confidence-plan.md",
    "docs/architecture.md",
    "docs/project-map.md",
    "docs/test-matrix.md",
    "docs/known-pitfalls.md",
)


def _run_git(args: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _ignored(path: Path) -> bool:
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return True
    return any(part in IGNORE_PARTS for part in relative.parts)


def _line_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _largest_python_files(limit: int = 20) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    for root_name in SCAN_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if _ignored(path):
                continue
            rows.append((_line_count(path), path.relative_to(ROOT).as_posix()))
    return sorted(rows, reverse=True)[:limit]


def main() -> int:
    print(f"Repo root: {ROOT}")
    branch = _run_git(["branch", "--show-current"])
    print(f"Git branch: {branch or 'unavailable'}")

    dirty = _run_git(["status", "--short"])
    print("Dirty files:")
    if dirty:
        for line in dirty.splitlines():
            print(f"  {line}")
    else:
        print("  none or unavailable")

    print("Largest Python files:")
    for lines, relative in _largest_python_files():
        print(f"  {lines:5d} {relative}")

    print("Key docs:")
    for relative in KEY_DOCS:
        status = "present" if (ROOT / relative).is_file() else "missing"
        print(f"  {status:7s} {relative}")

    print("Suggested next docs to read:")
    for relative in (
        "docs/release-confidence-plan.md",
        "docs/architecture.md",
        "docs/project-map.md",
        "docs/test-matrix.md",
        "docs/known-pitfalls.md",
    ):
        print(f"  {relative}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
