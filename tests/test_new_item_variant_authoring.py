from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
import pytest

from cdmw.core.pappt_format import parse_pappt
from cdmw.core.stringinfo_table import stringinfo_key
from cdmw.domain.new_item.authoring import VariantAppearance
from cdmw.services.new_item_planning import ModelFiles
from cdmw.services.new_item_variants import variant_bindings, prepare_variant_models
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.model_import import ModelPlacement, ModelImportSource
from tests.test_new_item_provenance import setup_game, spec
from tests.test_new_item_service import TEMPLATE
from tests.test_new_item_socket_authoring import planned_row
from tests.test_new_item_service import imported_pac


def selections(snapshot):
    return tuple(VariantAppearance(part.prefab_path,path) for part,path in variant_bindings(snapshot.family(TEMPLATE)))


def test_selected_binding_gets_owned_resources_unselected_keeps_template(tmp_path):
    service,snapshot,_ = setup_game(tmp_path)
    choices = selections(snapshot)
    plan = service.plan(replace(spec(),variants=(choices[0],)),snapshot)
    variants = plan.manifest["variants"]
    assert any(v["prefab_path"]==choices[0].prefab_path and v["appearance"]=="owned template copy" for v in variants)
    assert any(v["prefab_path"]==choices[1].prefab_path and v["appearance"]=="template" for v in variants)
    mapping = plan.manifest["pappt_records"]
    assert len(mapping)==1
    row = planned_row(snapshot,plan)
    old,new = next(iter(mapping.items()))
    assert stringinfo_key(new).to_bytes(4,"little") in row.raw
    assert stringinfo_key(old).to_bytes(4,"little") not in row.raw
    assert choices[1].model_path not in plan.loose_files
