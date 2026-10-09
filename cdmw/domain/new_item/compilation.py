"""Semantic compiler identity, independent of package UUIDs and allocated IDs.

Bump the compiler revision when planner semantics change. Bump a named adapter
revision when its output or admission rules change. Wire schema changes require
a new wire version; the frozen v1 schema is included by digest.
"""
import hashlib
import json
import re

from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.independent_wire_v1 import V1_ENUM_VALUES, V1_RECORD_FIELDS


COMPILER_REVISION = 1
ADAPTER_REVISIONS = {'item-v1': 1, 'dds-pathc': 2, 'flat-icon-registry': 2}
FORMAT = 'cdmw_item_compiler_v1'


def compiler_stamp():
    schema = json.dumps({'records': V1_RECORD_FIELDS, 'enums': V1_ENUM_VALUES},
                        sort_keys=True, separators=(',', ':')).encode('utf-8')
    return {'format': FORMAT, 'revision': COMPILER_REVISION,
            'adapters': dict(ADAPTER_REVISIONS), 'wire_schema': hashlib.sha256(schema).hexdigest()}


def validate_compiler_stamp(value):
    if (not isinstance(value, dict) or set(value) != {'format', 'revision', 'adapters', 'wire_schema'}
            or value['format'] != FORMAT or type(value['revision']) is not int
            or not 1 <= value['revision'] <= 0x7fffffff
            or not isinstance(value['wire_schema'], str) or not re.fullmatch('[0-9a-f]{64}', value['wire_schema'])
            or not isinstance(value['adapters'], dict) or not 1 <= len(value['adapters']) <= 128
            or any(not isinstance(name, str) or not re.fullmatch('[a-z0-9-]{1,64}', name)
                   or type(revision) is not int or not 1 <= revision <= 0x7fffffff
                   for name, revision in value['adapters'].items())):
        raise IndependentItemError('Invalid independent item compiler record.')
    return value
