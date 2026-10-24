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


COMPILER_REVISION = 15
ADAPTER_REVISIONS = {'item-v1': 3, 'envelope-v2': 8, 'iteminfo-fields': 3, 'item-properties': 2, 'item-stats': 1, 'item-inventory': 1, 'item-layout': 1, 'item-use': 2, 'package-links': 1, 'dds-pathc': 2, 'flat-icon-registry': 2, 'texture-replace': 1}
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


def _identity(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def compilation_record(*, scope, packages, sources, allocations, order, runtime_abi, outputs, providers, links=None):
    inputs = {'compiler': compiler_stamp(), 'scope': scope, 'packages': packages,
              'sources': sources, 'allocations': allocations,
              'policy': {'conflicts': 'refuse', 'order': order},
              'runtime_abi': runtime_abi, 'outputs': outputs, 'providers': providers}
    if links is not None:
        inputs['links'] = links
    value = {'format': 'cdmw_compilation_v2' if links is not None else 'cdmw_compilation_v1', 'identity': _identity(inputs), 'inputs': inputs}
    validate_compilation(value)
    return value


def validate_compilation(value):
    def fail():
        raise IndependentItemError('Invalid independent mod compilation record.')

    def checksum(value):
        return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None

    def hashes(value, *, nullable=False):
        if not isinstance(value, dict) or len(value) > 65536:
            fail()
        for path, digest in value.items():
            if (not isinstance(path, str) or not 1 <= len(path) < 32768 or '\0' in path
                    or not (nullable and digest is None) and not checksum(digest)):
                fail()

    if (not isinstance(value, dict) or set(value) != {'format', 'identity', 'inputs'}
            or value['format'] not in ('cdmw_compilation_v1', 'cdmw_compilation_v2') or not checksum(value['identity'])):
        fail()
    inputs = value['inputs']
    expected = {'compiler', 'scope', 'packages', 'sources', 'allocations', 'policy', 'runtime_abi', 'outputs', 'providers'}
    if value['format'] == 'cdmw_compilation_v2':
        expected.add('links')
    if not isinstance(inputs, dict) or set(inputs) != expected:
        fail()
    if 'links' in inputs:
        from cdmw.domain.new_item.package_links import validate_link_record
        validate_link_record(inputs['links'])
    validate_compiler_stamp(inputs['compiler'])
    if inputs['scope'] not in ('archive-contribution', 'virtual-profile'):
        fail()
    if inputs['runtime_abi'] is not None and inputs['runtime_abi'] not in ('CDVFS2', 'CDVFS3'):
        fail()
    for name in ('sources', 'allocations'):
        hashes(inputs[name])
    for name in ('outputs', 'providers'):
        hashes(inputs[name], nullable=True)
    policy = inputs['policy']
    if (not isinstance(policy, dict) or set(policy) != {'conflicts', 'order'} or policy['conflicts'] != 'refuse'
            or not isinstance(policy['order'], list) or len(policy['order']) > 65536
            or any(not isinstance(v, str) or not 1 <= len(v) < 32768 or '\0' in v for v in policy['order'])
            or len(set(policy['order'])) != len(policy['order'])):
        fail()
    packages = inputs['packages']
    if not isinstance(packages, list) or len(packages) > 128:
        fail()
    seen = set()
    for package in packages:
        if not isinstance(package, dict) or set(package) != {'identity', 'content', 'artifact', 'retained_artifact', 'version', 'features', 'modules'}:
            fail()
        from cdmw.domain.new_item.independent import package_id
        identity = package_id(package['identity'])
        if (identity in seen or not checksum(package['content']) or not checksum(package['artifact']) or not checksum(package['retained_artifact'])
                or type(package['version']) is not int or package['version'] not in (1, 2)):
            fail()
        seen.add(identity)
        if 'links' in inputs and inputs['links']['providers'].get(identity, {}).get('content') != package['content']:
            fail()
        if not isinstance(package['features'], dict) or len(package['features']) > 128:
            fail()
        for name, version in package['features'].items():
            if (not isinstance(name, str) or not re.fullmatch('[a-z][a-z0-9.-]{0,63}', name)
                    or type(version) is not int or not 1 <= version <= 0x7fffffff):
                fail()
        if not isinstance(package['modules'], list) or len(package['modules']) > 128:
            fail()
        symbols = set()
        for module in package['modules']:
            if not isinstance(module, dict) or set(module) != {'id', 'type', 'version'}:
                fail()
            if (not isinstance(module['id'], str) or not re.fullmatch('[a-z][a-z0-9_-]{0,63}', module['id'])
                    or module['id'] in symbols or not isinstance(module['type'], str)
                    or package['features'].get(module['type']) != module['version']
                    or type(module['version']) is not int):
                fail()
            symbols.add(module['id'])
    if _identity(inputs) != value['identity']:
        fail()
    return inputs
