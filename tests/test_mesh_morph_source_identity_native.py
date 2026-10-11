"""A native metadata promotion must never conceal a changed loaded source map."""

import pytest

from tests.test_mesh_morph_authoring_native import resident, _sculpt
from tests.test_mesh_morph_service import _author_command
from tests.test_native_mesh_editor_morph_refit import _driver_garment_mesh


@pytest.mark.parametrize("promote_before_import", [False, True])
def test_recipe_rejects_changed_loaded_source_map_even_after_native_promotion(resident, tmp_path, promote_before_import):
    service, open_session = resident
    source = open_session()
    assert service.apply_command(source, _author_command()).ok
    assert service.set_refit_driver(source, (0, 1))[0].ok
    assert service.bind_refit(source, (2,))[0].ok
    assert service.set_morph_value(source, "volume", 50.0)[0].ok
    recipe = service.export_refit_recipe(source, tmp_path / "identity.recipe.json", "Identity")

    incompatible = _driver_garment_mesh()
    incompatible.submeshes[0].source_vertex_map = [2, 1, 0]
    target = open_session(incompatible)
    if promote_before_import:
        assert _sculpt(service, target, {0: (0,)}, (0.0, 0.0, 0.25)).ok
        assert _sculpt(service, target, {0: (0,)}, (0.0, 0.0, -0.25)).ok
        service.working_mesh(target, clone=True)
    before = len(service._session(target).undo_stack)
    with pytest.raises(ValueError, match="source|mapping|identity"):
        service.import_refit_recipe(target, recipe)
    assert len(service._session(target).undo_stack) == before
    assert not service.cached_morph_state(target).profile_id
