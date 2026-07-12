from cdmw.modding.material_replacer import group_replacement_texture_sets


def test_missing_texture_file_collection_is_treated_as_empty() -> None:
    assert group_replacement_texture_sets(None) == {}
