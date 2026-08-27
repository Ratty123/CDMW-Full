from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from cdmw.constants import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]
# Untracked local working notes, not repository documentation. Both guards in
# this module agree on that: neither reads a plan off disk.
PLANS_DIR = ROOT / "docs" / "plans"
DELETED_ACTIVE_PLANS = {
    "app-shutdown-process-cleanup.md",
    "code-review-findings-remediation.md",
    "oversized-file-split-followup.md",
    "whole-codebase-repair.md",
}


def _documentation_files() -> tuple[Path, ...]:
    """Every markdown file this repository actually ships.

    Asked of git rather than read off disk. `docs/`, `AGENTS.md` and
    `CLAUDE.md` are local working notes now, on the same footing plans were
    already on, so a developer with those open must not be held to link and
    index rules for files nobody else receives. Package READMEs are
    documentation wherever they live: limiting this to cdmw/ once let a broken
    docs/ link sit in native/cdmw_mesh_core/README.md.
    """

    result = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    tracked = (ROOT / line for line in result.stdout.splitlines() if line.strip())
    return tuple(sorted(path for path in set(tracked) if path.is_file()))


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


def _require_local_doc(path: Path) -> Path:
    """A documentation file that lives on the developer's machine only.

    `docs/` is not committed, so these guards have something to check on a
    working copy and nothing to check on a fresh clone. Skipping keeps the check
    meaningful where the file exists instead of asserting against a file the
    repository never promised to ship.
    """

    if not path.is_file():
        pytest.skip(f"{path.relative_to(ROOT).as_posix()} is local-only and absent here")
    return path


def test_project_memory_is_compact_and_no_plan_is_committed() -> None:
    memory = _require_local_doc(ROOT / "docs" / "ai" / "PROJECT_MEMORY.md")
    assert len(memory.read_text(encoding="utf-8-sig").splitlines()) < 200

    assert _tracked_active_plans() == set()


def test_documented_markdown_paths_exist_and_deleted_plans_are_unreferenced() -> None:
    docs_present = (ROOT / "docs").is_dir()
    missing: list[tuple[str, str]] = []
    stale: list[tuple[str, str]] = []
    for source_path in _documentation_files():
        source = source_path.read_text(encoding="utf-8-sig")
        for reference in re.findall(r"`(docs/[A-Za-z0-9_./-]+\.md)`", source):
            # `docs/` is local-only, so a reference into it resolves on a working
            # copy and not on a fresh clone. Check it where it can be checked
            # rather than reporting every one of them as missing.
            if not docs_present:
                continue
            if not (ROOT / reference).is_file():
                missing.append((source_path.relative_to(ROOT).as_posix(), reference))
        for deleted_name in DELETED_ACTIVE_PLANS:
            if deleted_name in source:
                stale.append((source_path.relative_to(ROOT).as_posix(), deleted_name))
    assert not missing, f"Missing documentation references: {missing}"
    assert not stale, f"Deleted active-plan references remain: {stale}"


def test_docs_index_names_every_documentation_file() -> None:
    """docs/README.md is the entry point, so a doc it omits is a doc nobody opens.

    Eight docs had accumulated outside the index. Matching on file name keeps
    the guard indifferent to how the index nests its subfolder lists.
    """

    index_path = _require_local_doc(ROOT / "docs" / "README.md")
    index = index_path.read_text(encoding="utf-8-sig")
    unlisted = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "docs").rglob("*.md")
        if PLANS_DIR not in path.parents and path != index_path and path.name not in index
    )

    assert not unlisted, f"Docs missing from docs/README.md: {unlisted}"


def test_test_matrix_command_paths_exist() -> None:
    matrix = _require_local_doc(ROOT / "docs" / "test-matrix.md").read_text(encoding="utf-8-sig")
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


def test_readme_badge_and_source_note_track_current_application_version() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8-sig")
    badge_version = APP_VERSION.replace("-", "--")

    assert f"version-{badge_version}-" in readme
    assert f"`{APP_VERSION}` is the current source version" in readme
