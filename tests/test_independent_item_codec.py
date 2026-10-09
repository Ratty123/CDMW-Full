"""Historical v1 bytes stay stable when internal Python classes change."""
from dataclasses import dataclass
from enum import Enum
import importlib
import io
import json
from pathlib import Path
import zipfile

import pytest

from cdmw.domain.new_item import spec
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.services import independent_item_codec as codec


def historical_values():
    fixture = json.loads((Path(__file__).parent / 'fixtures/cditem_v1_codec.json').read_text(encoding='utf-8'))
    return fixture['values'] + fixture['populated_values']


def test_historical_v1_values_round_trip_with_identical_wire_names_and_fields():
    for value in historical_values():
        assert codec.encode(codec.decode(value)) == value


def test_v1_package_keeps_original_identity_and_content_digest():
    from cdmw.services.independent_item_package import package_bytes, read_package
    fixture = json.loads((Path(__file__).parent / 'fixtures/cditem_v1_codec.json').read_text(encoding='utf-8'))
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('item.json', json.dumps(fixture['manifest']))
    package = read_package(stream.getvalue())
    assert package.identity == fixture['manifest']['identity']
    assert package.digest == fixture['manifest_sha256']
    assert read_package(package_bytes(package)) == package


def test_internal_class_and_enum_names_do_not_define_wire_names():
    item = spec.StatEdit(1, 2, 3)
    expected = codec.encode(item)
    original = spec.StatEdit.__name__, spec.ModelSource.__name__
    try:
        spec.StatEdit.__name__ = 'RenamedStatSetting'
        spec.ModelSource.__name__ = 'RenamedModelSource'
        assert codec.encode(item) == expected
        assert codec.encode(spec.ModelSource.TEMPLATE) == {'enum': 'ModelSource', 'value': 'template'}
        assert codec.decode(expected) == item
    finally:
        spec.StatEdit.__name__, spec.ModelSource.__name__ = original


def test_new_authoring_types_do_not_implicitly_extend_v1(monkeypatch):
    @dataclass
    class FutureSetting:
        power: int
    FutureSetting.__module__ = spec.__name__
    monkeypatch.setattr(spec, 'FutureSetting', FutureSetting, raising=False)
    importlib.reload(codec)
    try:
        with pytest.raises(IndependentItemError):
            codec.encode(FutureSetting(1))
        with pytest.raises(IndependentItemError):
            codec.decode({'type': 'FutureSetting', 'fields': {'power': 1}})
    finally:
        monkeypatch.delattr(spec, 'FutureSetting')
        importlib.reload(codec)


def test_foreign_enum_cannot_be_encoded_as_a_v1_setting():
    class FutureSetting(Enum):
        ON = 'on'
    with pytest.raises(IndependentItemError):
        codec.encode(FutureSetting.ON)


def test_explicit_field_rename_retains_v1_and_new_behavior_cannot_be_silently_dropped(monkeypatch):
    @dataclass
    class NewStatSetting:
        level: int
        status_key: int
        amount: int
        future_mode: str = 'off'
    old = {'type': 'StatEdit', 'fields': {'level': 1, 'status_key': 2, 'value': 3}}
    monkeypatch.setitem(codec._RECORDS, 'StatEdit', codec.RecordAdapter(NewStatSetting))
    with pytest.raises(IndependentItemError, match='explicit compatibility translation'):
        codec.decode(old)
    monkeypatch.setitem(codec._RECORDS, 'StatEdit', codec.RecordAdapter(
        NewStatSetting, {'value': 'amount'}, {'future_mode': 'off'}))
    value = codec.decode(old)
    assert value == NewStatSetting(1, 2, 3)
    assert codec.encode(value) == old
    with pytest.raises(IndependentItemError, match='cannot be represented'):
        codec.encode(NewStatSetting(1, 2, 3, 'on'))


@pytest.mark.parametrize('data', [
    {'type': 'StatEdit', 'fields': {'level': 0, 'status_key': 1, 'value': True}},
    {'type': 'StatEdit', 'fields': {'level': 0, 'status_key': 1}},
    {'type': 'StatEdit', 'fields': {'level': 0, 'status_key': 1, 'value': 2, 'future': 3}},
    {'enum': 'ModelSource', 'value': 'future'}, {'enum': 'ModelSource', 'value': []},
    {'type': [], 'fields': {}}, {'map': {'bad\0key': 1}},
])
def test_unknown_fields_values_and_malformed_types_refuse(data):
    with pytest.raises(IndependentItemError):
        codec.decode(data)
