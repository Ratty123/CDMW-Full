from __future__ import annotations

import json

from cdmw.workers.d3d11_package_workers import AlignmentD3D11PackageWorker


def test_native_reference_splice_filters_nested_identity_role(tmp_path) -> None:
    target_dir = tmp_path / "target"
    native_dir = tmp_path / "native"
    target_dir.mkdir()
    native_dir.mkdir()
    (target_dir / "manifest.json").write_text(
        json.dumps(
            {
                "batches": [
                    {
                        "vertex_file": "geometry/old.bin",
                        "editor_identity": {"role": "original_reference"},
                        "material_name": "NestedOld",
                    },
                    {
                        "vertex_file": "geometry/replacement.bin",
                        "editor_role": "replacement_preview",
                        "material_name": "Replacement",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (native_dir / "manifest.json").write_text(
        json.dumps({"batches": [{"vertex_file": "geometry/native.bin", "material_name": "Native"}]}),
        encoding="utf-8",
    )

    assert AlignmentD3D11PackageWorker._replace_original_reference_with_native_package(
        target_dir,
        native_dir,
    )
    batches = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))["batches"]

    assert [batch["material_name"] for batch in batches] == ["Native", "Replacement"]
