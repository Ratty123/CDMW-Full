"""Placement and Animations writes its work files where the app writes its workspace."""

from __future__ import annotations

from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]


def test_the_work_root_follows_the_app_folder_and_its_test_profile(monkeypatch):
    from cdmw.app.app_folder import profile_override, workspace_folder
    from tools.placement_studio import corpus

    monkeypatch.delenv("CDMW_PS_WORK_ROOT", raising=False)
    root = corpus.work_root()
    assert root == workspace_folder() / "placement_studio"
    # The run's private profile (tests/conftest.py), never the checkout's own workspace.
    profile = profile_override()
    assert profile is not None and root.resolve().is_relative_to(profile)
    assert not root.resolve().is_relative_to((REPOSITORY / "workspace").resolve())


def test_an_explicit_work_root_still_wins(monkeypatch, tmp_path):
    from tools.placement_studio import corpus

    monkeypatch.setenv("CDMW_PS_WORK_ROOT", str(tmp_path / "placement"))
    assert corpus.work_root() == tmp_path / "placement"
