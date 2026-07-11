from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from cdmw.core import mod_package as package_facade
from cdmw.core import mod_package_retrofit as retrofit_facade
from cdmw.domain.packages import export_policy, layout, retrofit
from cdmw.models import ModPackageInfo
from cdmw.services.package_service import PackageService


def test_export_options_are_immutable_and_core_exports_owner_objects() -> None:
    options = export_policy.mod_package_export_options_for_profiles(
        ("ultimate", "jmm", "ultimate"),
        create_zip=True,
        conflict_mode="override",
        target_language="ko",
    )

    assert options.export_profiles == ("cdumm", "jmm")
    assert options.create_zip is True
    assert options.conflict_mode == "override"
    assert options.target_language == "ko"
    with pytest.raises(dataclasses.FrozenInstanceError):
        options.create_zip = False  # type: ignore[misc]
    assert package_facade.ModPackageExportOptions is export_policy.ModPackageExportOptions
    assert package_facade.mod_package_export_options_for_profiles is export_policy.mod_package_export_options_for_profiles


def test_package_layout_and_service_resolve_the_same_sanitized_root(tmp_path: Path) -> None:
    package_info = ModPackageInfo(title=' Nude: Test / Package? ')
    expected = tmp_path / "Nude_ Test _ Package_"

    assert layout.resolve_mod_package_root(tmp_path, package_info) == expected
    assert PackageService().resolve_export_root(tmp_path, package_info) == expected
    assert layout.resolve_mod_package_profile_root(tmp_path, package_info, "ultimate", multi_profile=True) == expected.with_name(
        f"{expected.name}_cdumm"
    )
    assert package_facade.resolve_mod_package_root is layout.resolve_mod_package_root


def test_retrofit_models_are_direct_core_compatibility_exports() -> None:
    assert retrofit_facade.RETROFIT_MANAGER_PROFILES is retrofit.RETROFIT_MANAGER_PROFILES
    assert retrofit_facade.RetrofittableModPackage is retrofit.RetrofittableModPackage
    assert retrofit_facade.ModPackageRetrofitResult is retrofit.ModPackageRetrofitResult
    assert retrofit_facade.RetrofitPayloadMapping is retrofit.RetrofitPayloadMapping
    assert retrofit_facade.RetrofitPathRepairSummary is retrofit.RetrofitPathRepairSummary
