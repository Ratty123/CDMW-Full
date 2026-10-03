"""Template-only appearance/placement reaches owned output without modifying its source."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import numpy as np
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.pac_xml_standard_material import find_material_wrappers, TRANSLUCENT_SHADER
from cdmw.domain.new_item.spec import GlowChoice, ModelSource
from cdmw.domain.new_item.translucency import TranslucencyChoice
from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.new_item_service import NewItemService
from cdmw.services.new_item_template_model import prepare_template_model
from cdmw.services.new_item_variants import xml_path
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.model_import import ModelPlacement
from tests.test_new_item_provenance import current_files, spec
from tests.test_new_item_service import build_package, _read, PAC, PAC_XML
from tests.test_new_item_variant_authoring import selections
from tests.test_pac_xml_standard_material import SIDECAR, GLOWING, TEMPLATE as UNTOUCHED_WRAPPER
from tests.test_static_skin_weight_export import _skinned_pac
from tests.test_new_item_service import TEMPLATE, OTHER


@pytest.fixture
def template_game(tmp_path):
    files = current_files()
    files[PAC], mesh = _skinned_pac()
    files[PAC_XML] = SIDECAR.encode("utf-8")
    entries = parse_archive_pamt(build_package(tmp_path / "game", files))
    service = NewItemService()
    return service, service.build_snapshot(entries, read_entry=_read), files, mesh


@pytest.mark.parametrize("variant", [False, True])
def test_template_appearance_and_placement_survive_plan_and_pac_reparse(template_game, variant):
    service, snapshot, original, mesh = template_game
    blade = find_material_wrappers(SIDECAR)[0].submesh_name
    glow = GlowChoice(parts=(blade,), color=(1, 0, 0), intensity=6)
    glass = TranslucencyChoice((blade,), 0.2, 0.4)
    placement = ModelPlacement(offset=(0.4, -0.2, 0.1), rotation=(0, 90, 0), scale=(1.5, 0.8, 1.2))
    choice = replace(spec(), glow=glow, translucency=glass, template_transform=tuple(placement.matrix()))
    if variant:
        binding = next(item for item in selections(snapshot) if item.model_path == PAC)
        choice = replace(choice, variants=(replace(binding, glow_parts=glow.parts,
            glow_color=glow.color, glow_intensity=glow.intensity, translucency=glass,
            template_transform=choice.template_transform),))
    assert choice.model_source is ModelSource.TEMPLATE
    assert choice.needs_own_family
    plan = service.plan(choice, snapshot)
    if variant:
        out_path = next(row["output_model"] for row in plan.manifest["variants"] if row["model_path"] == PAC)
    else:
        out_path = next(path for path in plan.loose_files if path.endswith("/" + plan.spec.stem + ".pac"))
    actual = parse_pac(plan.loose_files[out_path], out_path)
    np.testing.assert_allclose(actual.submeshes[0].vertices,
        [placement.apply(point) for point in mesh.submeshes[0].vertices], atol=2e-4)
    assert actual.submeshes[0].faces == mesh.submeshes[0].faces
    assert actual.submeshes[0].bone_indices == mesh.submeshes[0].bone_indices
    assert actual.submeshes[0].bone_weights == mesh.submeshes[0].bone_weights
    np.testing.assert_allclose(actual.submeshes[0].uvs, mesh.submeshes[0].uvs, atol=1e-5)
    xml = plan.loose_files[xml_path(out_path)].decode("utf-8")
    assert GLOWING in xml and UNTOUCHED_WRAPPER in xml
    row = find_material_wrappers(xml)[0]
    assert row.shader == TRANSLUCENT_SHADER
    assert row.textures["_baseColorTexture"] == find_material_wrappers(SIDECAR)[0].textures["_baseColorTexture"]
    assert '_value="6.000000"' in xml and '_value="#ff0000ff"' in xml.lower()
    assert '_value="0.200000"' in xml and '_value="0.400000"' in xml
    assert row.textures["_emissiveIntensityTexture"] in plan.loose_files
    assert snapshot.payload(PAC) == original[PAC]
    assert snapshot.payload(PAC_XML) == original[PAC_XML]


def _events_until(app, condition, timeout=3):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert condition()
