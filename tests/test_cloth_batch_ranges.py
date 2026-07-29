"""Cloth particles carry the submesh they belong to.

The solver seeds one particle per mesh position in order, but the overlay payload
flattens every cloth batch into one particle list. Without the ranges the
renderer cannot tell which submesh a run of particles came from, so it could only
draw lines over a static mesh instead of moving the mesh itself.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from cdmw.services.mesh_dotnet_preview_package import (
    dotnet_preview_overlays_from_preview_core_package,
)

_PARTICLE = struct.Struct("<3f")
_PIN = struct.Struct("<f")
_CONSTRAINT = struct.Struct("<2i2f")


def _write_cloth_batch(package: Path, stem: str, particle_count: int) -> dict[str, object]:
    geometry = package / "geometry"
    geometry.mkdir(parents=True, exist_ok=True)
    (geometry / f"{stem}_particles.bin").write_bytes(
        b"".join(_PARTICLE.pack(float(i), 1.0, 2.0) for i in range(particle_count))
    )
    (geometry / f"{stem}_pins.bin").write_bytes(
        b"".join(_PIN.pack(0.0) for _ in range(particle_count))
    )
    (geometry / f"{stem}_constraints.bin").write_bytes(
        _CONSTRAINT.pack(0, particle_count - 1, 1.0, 0.5)
    )
    return {
        "cloth_enabled": True,
        "cloth_particle_file": f"geometry/{stem}_particles.bin",
        "cloth_pin_file": f"geometry/{stem}_pins.bin",
        "cloth_constraint_file": f"geometry/{stem}_constraints.bin",
        "cloth_particle_count": particle_count,
        "cloth_constraint_count": 1,
    }


def _write_package(tmp_path: Path) -> Path:
    package = tmp_path / "package"
    package.mkdir()
    batches = [
        {"index": 0, **_write_cloth_batch(package, "batch_000_cloth", 3)},
        {"index": 1, "cloth_enabled": False},
        {"index": 2, **_write_cloth_batch(package, "batch_002_cloth", 4)},
    ]
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "normalization_center": [0.0, 0.0, 0.0],
                "normalization_scale": 1.0,
                "batches": batches,
            }
        ),
        encoding="utf-8",
    )
    return package


def test_ranges_name_the_submesh_each_particle_run_belongs_to(tmp_path: Path) -> None:
    cloth = dotnet_preview_overlays_from_preview_core_package(_write_package(tmp_path))["cloth"]

    assert len(cloth["particles"]) == 7
    # The non-cloth batch takes no particles and contributes no range, so a range
    # index is the batch's own index rather than its position among cloth batches.
    assert cloth["batch_ranges"] == [
        {"submesh_index": 0, "offset": 0, "count": 3},
        {"submesh_index": 2, "offset": 3, "count": 4},
    ]


def test_every_range_addresses_real_particles(tmp_path: Path) -> None:
    cloth = dotnet_preview_overlays_from_preview_core_package(_write_package(tmp_path))["cloth"]
    total = len(cloth["particles"])

    for entry in cloth["batch_ranges"]:
        assert entry["offset"] >= 0
        assert entry["count"] > 0
        assert entry["offset"] + entry["count"] <= total


def test_constraints_stay_inside_their_own_batch(tmp_path: Path) -> None:
    cloth = dotnet_preview_overlays_from_preview_core_package(_write_package(tmp_path))["cloth"]
    ranges = {entry["offset"]: entry["count"] for entry in cloth["batch_ranges"]}

    for a, b in cloth["constraints"]:
        owner = max(offset for offset in ranges if offset <= a)
        assert owner <= b < owner + ranges[owner]
