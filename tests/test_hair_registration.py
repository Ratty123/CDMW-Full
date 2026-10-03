"""Additive registration and opaque clone preservation, without game assets."""

from dataclasses import replace
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from cdmw.core.pappt_format import PartPrefabPart, PartPrefabRecord, PartPrefabTable, encode_pappt, parse_pappt
from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.domain.hair_registration import HairRegistrationError, append_hair_choice, read_hair_choices
from cdmw.services.hair_registration import DAMIANE_MESH_PARAM, PART_PREFAB_TABLE, prepare_damiane_hair_registration
from tests.test_prefab_binary_edit import _build
from tools.dotnet_archive_backend.probe_hair_registration import collect_lookup_entries, select_active_entry


STEM = "cd_phw_00_hair_00_0008_01_player"
NEW = "cd_phw_00_hair_00_9000_01_player"
MESH = f"character/model/1_pc/2_phw/head/hair/{STEM}.pac"
ICON = "ui/texture/image/customizeimage/hair.dds"
XML = (b'\xef\xbb\xbf<!-- retained </ParamDesc> comment -->\r\n<MeshParam>\r\n'
       b'<ParamDesc Index="0" Default="0" />\r\n'
       b'<ParamDesc Index="2" Default="0" UIKey="hairShape">\r\n'
       b'<MeshSet Index="0" DecorationParamIndex="0 1" MinValue="40 50" FutureField="keep">'
       + f'<MeshList MeshFileName="{STEM}" IconPath="{ICON}"/></MeshSet>\r\n'.encode()
       + b'</ParamDesc>\r\n<ParamDesc Index="3" Default="0" /></MeshParam>')


def fixture(*, stem=STEM):
    mesh = MESH.replace(STEM, stem)
    record = PartPrefabRecord(stem, "1_pc/02_phw/head/hair", "", flag=0, parts=(PartPrefabPart("CD_Hair"),))
    table = PartPrefabTable((record,), tag_prefix=b"\x01")
    files = {
        DAMIANE_MESH_PARAM: XML.replace(STEM.encode(), stem.encode()),
        PART_PREFAB_TABLE: encode_pappt(table),
        record.prefab_path: _build(mesh),
        mesh: b"opaque source mesh with all LODs and skin lanes",
        mesh.replace("character/model/", "character/modelproperty/") + "_xml": b"authored material, opacity and PBD binding",
        mesh.replace("character/model/", "character/bin__/meshphysics/")[:-4] + ".hkx": b"opaque physics",
        ICON: b"authored DDS",
    }
    return files


@pytest.mark.parametrize("resources,reason", [([MESH, MESH.replace("00_0008", "uptail_0008")], "multiple PAC"),
                                            ([MESH.replace("_player.pac", ".pac")], "different PAC")])
def test_prefab_donor_gate_explains_multi_mesh_and_alias_choices(monkeypatch, resources, reason):
    from cdmw.services import hair_registration
    monkeypatch.setattr(hair_registration, "decode_prefab_binary", lambda data:
        SimpleNamespace(resource_strings=lambda: [SimpleNamespace(text=path) for path in resources]))
    with pytest.raises(HairRegistrationError, match=reason):
        hair_registration.validate_hair_prefab_donor(b"prefab", MESH)
