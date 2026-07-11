from __future__ import annotations

import re
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


def test_project_memory_is_compact_and_only_current_plan_is_active() -> None:
    memory = ROOT / "docs" / "ai" / "PROJECT_MEMORY.md"
    assert len(memory.read_text(encoding="utf-8-sig").splitlines()) < 200

    active = {path.name for path in (ROOT / "docs" / "plans" / "active").glob("*.md")}
    assert active == set()


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


def test_security_policy_tracks_current_application_version() -> None:
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8-sig")
    assert f"`{APP_VERSION}`" in security
