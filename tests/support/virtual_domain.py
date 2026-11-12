"""Retired install code from cdmw.domain.virtual_loader, kept for tests only (decision 39)."""

# CDMW never installs into the game. Tests use this on owned game folders made in the
# test, to build the state the live code reads. Names the app still has are read from
# cdmw.domain.virtual_loader at call time (``_live``), so patching them there reaches this code.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cdmw.domain.virtual_loader as _live


def __getattr__(name):
    return getattr(_live, name)


@dataclass(frozen=True)
class VirtualProfile:
    packages: tuple[Path, ...] = ()
    mods: tuple[Path, ...] = ()
    disabled_packages: tuple[Path, ...] = ()
    disabled_mods: tuple[Path, ...] = ()


@dataclass(frozen=True)
class PreparedSnapshot:
    root: Path
    generation: str
    files: tuple[tuple[str, bytes], ...]
    registry: bytes
    profile: bytes
    observed: tuple[tuple[str, bytes | None], ...]
    source_revision: object
    external: object
    summary: tuple[str, ...]
    retained_packages: tuple[tuple[str, bytes], ...] = ()


@dataclass(frozen=True)
class VirtualLaunchPlan:
    root: Path
    generation: str
    executable: Path
    executable_sha256: str
    snapshot: Path
    manifest_sha256: str


@dataclass(frozen=True)
class VirtualSaveBackup:
    directory: Path
    source: Path
    manifest_sha256: str
    verified_files: tuple[tuple[str, int, str], ...] = ()
    observed_utc: str = ''


@dataclass(frozen=True)
class ExperimentalLaunchReview:
    plan: VirtualLaunchPlan
    backup: VirtualSaveBackup
    receipt_token: str = ''
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class VirtualSessionStatus:
    state: str
    detail: str
    generation: str = ''
    pid: int | None = None
    progress: int | None = None
    receipt_path: str = ''
    diagnostics: tuple[str, ...] = ()


# A test that patches a name the app still has (``monkeypatch.setattr(this_module,
# "resolve_items", ...)``) means the live function: the code above reads it from
# ``_live`` at call time, so the patch is forwarded there. pytest undoes a patch of
# a name it did not find in this module's own namespace by deleting it; that puts
# the live module's original value back.
_LIVE_ORIGINALS = {}


class _ForwardLiveNames(type(_live)):
    def __setattr__(self, name, value):
        shared = name in self.__dict__ and hasattr(_live, name) and self.__dict__[name] is getattr(_live, name)
        if shared or (name not in self.__dict__ and hasattr(_live, name)):
            # Also a name both modules import from the same place: patch both bindings.
            _LIVE_ORIGINALS.setdefault(name, getattr(_live, name))
            setattr(_live, name, value)
            if not shared:
                return
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if name not in self.__dict__ and hasattr(_live, name):
            if name in _LIVE_ORIGINALS:  # a second undo of the same name has nothing left to restore
                setattr(_live, name, _LIVE_ORIGINALS.pop(name))
        else:
            super().__delattr__(name)


import sys as _sys  # noqa: E402

_sys.modules[__name__].__class__ = _ForwardLiveNames
