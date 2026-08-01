"""A previewed mesh must be built once and reused, not rebuilt on every open.

Every symptom reported against the Mesh Editor -- reloading, the placeholder
triangle appearing, the slowness -- is what a preview looks like when the
package is rebuilt from scratch each time it is opened. On the machine that
reported them, the on-disk cache held exactly one entry across two workspaces,
and it was the procedural prewarm triangle: no real mesh had ever been kept.

The prewarm path proves the machinery works, because it hardcodes a balanced
mode and its own budget and it does get reused (see
``test_procedural_prewarm_package_is_valid_geometry_only_and_reused``). The
question these tests answer is whether a *real* model, going through the
settings-driven budget the archive preview worker passes, is kept too.

The build is counted rather than timed: a cache hit is "the builder did not run
a second time", which a duration cannot tell you on a warm filesystem.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from cdmw.models import ModelPreviewData, ModelPreviewMesh, clamp_archive_performance_settings
from cdmw.rendering.native_preview_package_cache import (
    native_preview_package_cache_budget,
)
from cdmw.services import mesh_dotnet_preview_package as package_service
from cdmw.services.mesh_dotnet_preview_package import (
    build_or_lookup_dotnet_preview_package_from_model,
    validate_dotnet_preview_package,
)

# The budget the archive preview worker actually passes, rather than a number
# invented for the test: settings default to "balanced" and are clamped back to
# it when invalid, so this is what a real preview runs with.
DEFAULT_MODE = clamp_archive_performance_settings(None).native_preview_cache_mode
DEFAULT_MAX_BYTES, DEFAULT_TARGET_BYTES = native_preview_package_cache_budget(DEFAULT_MODE)


def _model(path: str = "archive/character/body.pac") -> ModelPreviewData:
    return ModelPreviewData(
        path=path,
        format="pac",
        normalization_center=(0.0, 0.0, 0.0),
        normalization_scale=1.0,
        meshes=[
            ModelPreviewMesh(
                material_name="body",
                positions=[(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (-1.0, 1.0, 0.0)],
                texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                normals=[(0.0, 0.0, 1.0)] * 3,
                indices=[0, 1, 2],
                source_submesh_index=0,
                source_vertex_indices=[0, 1, 2],
                source_face_indices=[0],
                preview_role="archive_model",
            )
        ],
    )


class _BuildCounter:
    """Counts real package builds by wrapping the one function that does them."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.count = 0
        original = package_service.build_mesh_dotnet_experiment_package

        def counting(*args: object, **kwargs: object) -> object:
            self.count += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(
            package_service, "build_mesh_dotnet_experiment_package", counting
        )


def _build(cache_root: Path, model: ModelPreviewData, identity: str) -> object:
    return build_or_lookup_dotnet_preview_package_from_model(
        model,
        cache_root=cache_root,
        archive_identity=identity,
        sidecar_generation=0,
        cache_mode=DEFAULT_MODE,
        max_bytes=DEFAULT_MAX_BYTES,
        target_bytes=DEFAULT_TARGET_BYTES,
        metadata={"entry_path": identity, "source_decoder": "python_model_preview"},
    )


def test_the_default_settings_actually_enable_the_package_cache() -> None:
    """If this is off, nothing below can pass and the reason is the settings."""

    assert DEFAULT_MODE in {"balanced", "aggressive"}, (
        f"preview package caching defaults to {DEFAULT_MODE!r}, so every open "
        "rebuilds the package from scratch"
    )
    assert DEFAULT_MAX_BYTES > 0, (
        "the default budget is zero bytes, which disables durable caching no "
        "matter what the mode says"
    )


def test_opening_the_same_mesh_twice_builds_it_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = tmp_path / "cache"
    counter = _BuildCounter(monkeypatch)

    first = _build(cache_root, _model(), "character/body.pac")
    assert counter.count == 1, "the first open must build the package"
    assert validate_dotnet_preview_package(first.package_dir)[0] is True

    second = _build(cache_root, _model(), "character/body.pac")

    assert counter.count == 1, (
        "the same mesh was rebuilt on the second open; nothing is reused, which "
        "is what the reader sees as the preview reloading and the placeholder "
        f"reappearing (builds={counter.count})"
    )
    assert second.package_dir == first.package_dir


def test_a_kept_package_survives_on_disk(tmp_path: Path) -> None:
    """A reused package has to still be there for the next session, not just this one."""

    cache_root = tmp_path / "cache"
    package = _build(cache_root, _model(), "character/body.pac")

    entries = [p for p in cache_root.rglob("package") if p.is_dir()]
    assert entries, f"nothing was written under {cache_root} after a build"
    assert Path(package.package_dir).is_dir()
    assert validate_dotnet_preview_package(package.package_dir)[0] is True


def test_a_different_mesh_does_not_collide_with_a_kept_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reuse must be keyed, or the wrong model is shown for the right file."""

    cache_root = tmp_path / "cache"
    counter = _BuildCounter(monkeypatch)

    first = _build(cache_root, _model("archive/a.pac"), "archive/a.pac")
    second = _build(cache_root, _model("archive/b.pac"), "archive/b.pac")

    assert counter.count == 2, "two distinct meshes must each build once"
    assert first.package_dir != second.package_dir

    again = _build(cache_root, _model("archive/a.pac"), "archive/a.pac")
    assert counter.count == 2, "the first mesh should still be cached"
    assert again.package_dir == first.package_dir


def test_the_prewarm_placeholder_does_not_evict_real_packages(tmp_path: Path) -> None:
    """The placeholder shares a cache root with real meshes but sets a 16MB budget.

    If storing it prunes against that budget rather than its own entry, a real
    package kept moments earlier is evicted, and the next open rebuilds it and
    shows the triangle again while it does. That is exactly the reported
    sequence, so it is worth pinning even though it looks obscure.
    """

    cache_root = tmp_path / "cache"
    real = _build(cache_root, _model(), "character/body.pac")
    assert validate_dotnet_preview_package(real.package_dir)[0] is True

    package_service.build_dotnet_preview_prewarm_package(cache_root)

    assert Path(real.package_dir).is_dir(), (
        "building the prewarm placeholder evicted the real package that had "
        "just been cached"
    )
    assert validate_dotnet_preview_package(real.package_dir)[0] is True
