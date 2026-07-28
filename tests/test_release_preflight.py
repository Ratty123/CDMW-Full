from __future__ import annotations

from scripts.release_preflight import classify_git_status, release_blockers


def test_release_preflight_blocks_generated_and_unclassified_source() -> None:
    inventory = classify_git_status(
        [
            "?? tools/dotnet_mesh_editor_experiment/bin/Release/app.dll",
            "?? docs/features/new-feature.md",
            "?? cdmw/new_feature.py",
            "?? scratch/new_feature.py",
            "?? tests/test_new_feature.py",
            " M cdmw/services/mesh_service.py",
            "?? notes.tmp",
        ]
    )

    assert inventory["generated_output"] == ["tools/dotnet_mesh_editor_experiment/bin/Release/app.dll"]
    assert inventory["unclassified_untracked_source"] == ["scratch/new_feature.py"]
    assert inventory["required_source_or_docs"] == [
        "cdmw/new_feature.py",
        "cdmw/services/mesh_service.py",
        "docs/features/new-feature.md",
        "tests/test_new_feature.py",
    ]
    assert release_blockers(inventory) == ["generated_output_present", "unclassified_untracked_source_present"]
