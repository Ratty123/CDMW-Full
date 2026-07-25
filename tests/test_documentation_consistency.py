from __future__ import annotations

import re
import subprocess
from pathlib import Path

from cdmw.constants import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]
DELETED_ACTIVE_PLANS = {
    "app-shutdown-process-cleanup.md",
    "code-review-findings-remediation.md",
    "oversized-file-split-followup.md",
    "whole-codebase-repair.md",
}


def _documentation_files() -> tuple[Path, ...]:
    files = [ROOT / "README.md", ROOT / "SECURITY.md"]
    files.extend((ROOT / "docs").rglob("*.md"))
    files.extend((ROOT / "cdmw").rglob("README.md"))
    return tuple(sorted(set(files)))


def _tracked_active_plans() -> set[str]:
    """Names of plans under docs/plans/active that are committed to the repository.

    Implementation plans are working notes, kept out of source control. Reading
    the directory directly would assert on whichever plan the developer happens
    to have open locally, which is not something this repository can own.
    """

    result = subprocess.run(
        ["git", "ls-files", "docs/plans/active"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return {Path(line).name for line in result.stdout.splitlines() if line.strip().endswith(".md")}


def test_project_memory_is_compact_and_no_plan_is_committed() -> None:
    memory = ROOT / "docs" / "ai" / "PROJECT_MEMORY.md"
    assert len(memory.read_text(encoding="utf-8-sig").splitlines()) < 200

    assert _tracked_active_plans() == set()


def test_documented_markdown_paths_exist_and_deleted_plans_are_unreferenced() -> None:
    missing: list[tuple[str, str]] = []
    stale: list[tuple[str, str]] = []
    for source_path in _documentation_files():
        source = source_path.read_text(encoding="utf-8-sig")
        for reference in re.findall(r"`(docs/[A-Za-z0-9_./-]+\.md)`", source):
            if not (ROOT / reference).is_file():
                missing.append((source_path.relative_to(ROOT).as_posix(), reference))
        for deleted_name in DELETED_ACTIVE_PLANS:
            if deleted_name in source:
                stale.append((source_path.relative_to(ROOT).as_posix(), deleted_name))
    assert not missing, f"Missing documentation references: {missing}"
    assert not stale, f"Deleted active-plan references remain: {stale}"


def test_test_matrix_command_paths_exist() -> None:
    matrix = (ROOT / "docs" / "test-matrix.md").read_text(encoding="utf-8-sig")
    references = sorted(
        set(
            re.findall(
                r"((?:tests|tools|scripts)[/\\][A-Za-z0-9_./\\-]+\.(?:py|ps1|csproj))",
                matrix,
            )
        )
    )
    missing = [
        reference
        for reference in references
        if not (ROOT / reference.replace("\\", "/")).is_file()
    ]

    assert references
    assert not missing, f"Missing test-matrix command paths: {missing}"


def test_security_policy_tracks_current_application_version() -> None:
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8-sig")
    assert f"`{APP_VERSION}`" in security
