from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cdmw.domain.packages.layout import resolve_mod_package_root
from cdmw.models import ModPackageInfo


@dataclass(slots=True)
class PackageService:
    settings: object | None = None

    def resolve_export_root(self, parent_root: Path, package_info: ModPackageInfo) -> Path:
        """Resolve one package output root without exposing builder internals to UI."""

        return resolve_mod_package_root(parent_root, package_info)
