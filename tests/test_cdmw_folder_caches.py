"""Caches CDMW writes without an explicit path stay in the CDMW folder, never in AppData.

Under pytest the CDMW folder is the run's private profile (tests/conftest.py),
so these also show that no test writes into the user's AppData through them.
"""

from __future__ import annotations

from cdmw.app.app_folder import cdmw_folder, profile_override, workspace_folder


def test_the_mesh_baseline_cache_is_in_the_cdmw_folder() -> None:
    from cdmw.core.mesh_baseline import MeshBaselineCache

    root = MeshBaselineCache().root
    assert root == workspace_folder() / "mesh_baselines"
    assert root.resolve().is_relative_to(profile_override())


def test_the_pac_xml_profile_cache_defaults_to_the_cdmw_folder(monkeypatch) -> None:
    from cdmw.modding import pac_xml_profiles

    monkeypatch.delenv(pac_xml_profiles.PAC_XML_SETTINGS_DIR_ENV, raising=False)
    path = pac_xml_profiles.default_pac_xml_profile_cache_path()
    assert path.parent == cdmw_folder()
    assert path.resolve().is_relative_to(profile_override())
