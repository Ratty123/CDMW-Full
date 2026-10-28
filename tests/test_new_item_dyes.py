"""Inherited template dyes against shipped and edited variant materials."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.core.item_dye_material import material_dye_bindings
from cdmw.services.new_item_dyes import prepare_dye_assignments

FIXTURE = (Path(__file__).parent / "fixtures" / "new_item_golden" / "character" / "modelproperty" / "1_pc"
           / "1_phm" / "weapon" / "1_onehandweapon" / "cd_phm_01_sword_0109.pac_xml")


def _material():
    return FIXTURE.read_bytes()


def _row(*names):
    return SimpleNamespace(submeshes=tuple(SimpleNamespace(name=name, slots=(0, 1, 2)) for name in names))


def _wired_part(material):
    return next(name for _index, name in material_dye_bindings(material))


def test_template_copy_inherits_a_shipped_row_its_material_does_not_wire():
    material = _material()
    # Shipped rows can name a part whose shipped material has no dye wiring;
    # an unedited copy keeps that row exactly as the game ships it.
    row = _row(_wired_part(material), "part_without_wiring")
    parts, result = prepare_dye_assignments(row, material, material, None, imported=False, model="sword.pac")
    assert parts == row.submeshes
    assert result == material


def test_template_copy_names_the_model_and_part_when_an_edit_removed_wiring():
    source = _material()
    part = _wired_part(source)
    edited = source.replace(b"_dyeing", b"_edited")
    with pytest.raises(ValueError, match=rf"sword\.pac: the edited material for {part} "):
        prepare_dye_assignments(_row(part), edited, source, None, imported=False, model="sword.pac")


def test_imported_material_without_wiring_still_omits_inherited_dyes():
    source = _material()
    edited = source.replace(b"_dyeing", b"_edited")
    parts, result = prepare_dye_assignments(_row(_wired_part(source)), edited, source, None, imported=True)
    assert parts == ()
    assert result == edited


def test_cleared_dyes_skip_the_wiring_check():
    source = _material()
    edited = source.replace(b"_dyeing", b"_edited")
    assert prepare_dye_assignments(_row(_wired_part(source)), edited, source, (), imported=False) == ((), edited)
