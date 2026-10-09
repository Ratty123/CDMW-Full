"""Physical inventory storage; logical compilation records keep their identities.

Contexts are content-addressed values inside the same atomic inventory as their
references. They are never updated in place or treated as fresh compiler output.
Virtual profile records and the .cditem package wire formats remain inline.
"""
from copy import deepcopy
import re

from cdmw.domain.new_item.compilation import _identity, validate_compilation
from cdmw.domain.new_item.independent import IndependentItemError


CONTEXT_FORMAT = 'cdmw_compilation_context_v1'
REFERENCE_FORMAT = 'cdmw_compilation_reference_v1'
_SHARED_FIELDS = ('allocations', 'policy', 'links')


def _fail():
    raise IndependentItemError('Invalid or missing shared compilation context. Restore the matching overlay inventory.')


def _context_inputs(identity, value):
    if (not isinstance(identity, str) or re.fullmatch('[0-9a-f]{64}', identity) is None
            or not isinstance(value, dict) or set(value) != {'format', 'inputs'}
            or value['format'] != CONTEXT_FORMAT or not isinstance(value['inputs'], dict)
            or set(value['inputs']) not in ({'allocations', 'policy'}, set(_SHARED_FIELDS))):
        _fail()
    try:
        matches = _identity(value) == identity
    except (TypeError, ValueError, RecursionError):
        _fail()
    if not matches:
        _fail()
    return value['inputs']


def validate_contexts(contexts):
    """Check every stored object, including retained objects without live users."""
    if not isinstance(contexts, dict):
        _fail()
    for identity, value in contexts.items():
        _context_inputs(identity, value)
    return contexts


def read_compilation(value, contexts=None):
    """Rehydrate and validate the original record; never substitute today's stamp.

    The result owns its nested data. Callers cannot edit a shared stored context
    through the returned inputs or accidentally change another contribution.
    """
    if isinstance(value, dict) and value.get('format') == REFERENCE_FORMAT:
        if (set(value) != {'format', 'identity', 'compilation_format', 'context', 'inputs'}
                or not isinstance(value['context'], str) or not isinstance(contexts, dict)
                or value['context'] not in contexts or not isinstance(value['inputs'], dict)
                or set(value['inputs']).intersection(_SHARED_FIELDS)):
            _fail()
        common = _context_inputs(value['context'], contexts[value['context']])
        value = {'format': value['compilation_format'], 'identity': value['identity'],
                 'inputs': {**common, **value['inputs']}}
    validate_compilation(value)
    return deepcopy(value)


def store_compilation(value, contexts):
    """Append an immutable context and return its per-contribution reference.

    Existing logical compiler stamps, package/source/output evidence and identity
    are preserved byte-for-byte in canonical form, including historical records.
    """
    if not isinstance(contexts, dict):
        _fail()
    inputs = validate_compilation(value)
    context = {'format': CONTEXT_FORMAT,
               'inputs': {key: deepcopy(inputs[key]) for key in _SHARED_FIELDS if key in inputs}}
    identity = _identity(context)
    if identity in contexts and contexts[identity] != context:
        _fail()
    contexts.setdefault(identity, context)
    return {'format': REFERENCE_FORMAT, 'identity': value['identity'], 'compilation_format': value['format'],
            'context': identity, 'inputs': {key: deepcopy(item) for key, item in inputs.items() if key not in _SHARED_FIELDS}}
