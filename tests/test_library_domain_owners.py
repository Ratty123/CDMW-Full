from __future__ import annotations

from pathlib import Path

from cdmw.core import item_icon as icon_facade
from cdmw.core import model_catalogue as model_facade
from cdmw.domain.library import item_icons, models


def test_item_icon_records_and_background_policy_have_one_owner(tmp_path: Path) -> None:
    record = item_icons.ItemIconLibraryRecord(
        path=tmp_path / "icon.png",
        root_path=tmp_path,
        relative_path="icon.png",
        file_size=4,
        mtime_ns=1,
    )
    candidates = (
        item_icons.score_item_icon_source_candidate(
            tmp_path / "itemicon_sword.png",
            target_path="ui/texture/itemicon_sword.dds",
        ),
        item_icons.score_item_icon_source_candidate(
            tmp_path / "other.png",
            target_path="ui/texture/itemicon_sword.dds",
        ),
    )

    chosen, ranked, _message = item_icons.select_item_icon_source_candidate(candidates)
    assert record.relative_path == "icon.png"
    assert chosen is ranked[0] and chosen.path.name == "itemicon_sword.png"
    assert item_icons.normalize_item_icon_background_mode("invalid") == item_icons.ITEM_ICON_DEFAULT_BACKGROUND_MODE
    assert icon_facade.ItemIconLibraryRecord is item_icons.ItemIconLibraryRecord
    assert icon_facade.ItemIconOverrideSpec is item_icons.ItemIconOverrideSpec


def test_model_catalogue_records_and_candidate_policy_have_one_owner(tmp_path: Path) -> None:
    local = models.LocalModelFile(
        path=tmp_path / "models" / "hero.glb",
        root=tmp_path,
        name="Hero",
        extension=".glb",
        size=10,
        modified_at=1.0,
        import_supported=True,
        texture_status="Embedded/Unknown",
    )
    record = models.normalize_mirror_model_record(
        {"uid": "abcdef", "name": "Hero", "archives": {"gltf": {}, "glb": {}}},
        models.DEFAULT_MODEL_MIRROR_URL,
    )
    candidates = models.mirror_download_candidates(record, models.DEFAULT_MODEL_MIRROR_URL, preferred_format="glb")

    assert local.relative_path == str(Path("models") / "hero.glb")
    assert [candidate.format for candidate in candidates[:2]] == ["glb", "gltf"]
    assert models.is_importable_model_path(local.path)
    assert model_facade.LocalModelFile is models.LocalModelFile
    assert model_facade.MirrorDownloadCandidate is models.MirrorDownloadCandidate
