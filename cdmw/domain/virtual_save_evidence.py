"""Consistency checks for save experiments; never save admission authority."""
import hashlib
import json
import re

from cdmw.domain.virtual_loader import VirtualLoaderError

FORMAT = 'cdmw_virtual_save_evidence_v1'
MAX_RECORD = 4 * 1024 * 1024
STAGES = ('baseline', 'absent_before_load', 'absent_loaded', 'absent_saved',
          'restored_before_load', 'restored_loaded')
CLAIMS = {'save_origin': 'unknown', 'save_compatibility': 'unverified',
          'runtime_activation': 'unverified', 'observation': 'operator_report'}
OUTCOMES = {
    'baseline': ('prepared',), 'absent_before_load': ('prepared',),
    'absent_loaded': ('loaded', 'failed', 'unknown'),
    'absent_saved': ('saved', 'failed', 'unknown'),
    'restored_before_load': ('prepared',), 'restored_loaded': ('loaded', 'failed', 'unknown'),
}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None


def _uuid(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{32}', value) is not None


def seal(value):
    return {**value, 'identity': checksum(encoded(value))}


def validate(value):
    error = 'Invalid or changed save experiment capture.'
    if not isinstance(value, dict) or set(value) != {
            'format', 'experiment', 'identity', 'parent', 'stage', 'provider', 'captured_utc',
            'context', 'files', 'selected', 'observation', 'claims'}:
        raise VirtualLoaderError(error)
    if (value['format'] != FORMAT or not _uuid(value['experiment']) or not _uuid(value['provider'])
            or not _hash(value['identity']) or value['stage'] not in STAGES
            or value['claims'] != CLAIMS or not isinstance(value['captured_utc'], str)
            or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', value['captured_utc'])
            or (value['parent'] is not None and not _hash(value['parent']))
            or (value['stage'] == 'baseline') != (value['parent'] is None)):
        raise VirtualLoaderError(error)
    observation = value['observation']
    if (not isinstance(observation, dict) or set(observation) != {'outcome', 'notes'}
            or observation['outcome'] not in OUTCOMES[value['stage']]
            or not isinstance(observation['notes'], str) or not 1 <= len(observation['notes']) <= 4096
            or '\0' in observation['notes']):
        raise VirtualLoaderError(error)
    selected, files = value['selected'], value['files']
    if (not isinstance(selected, list) or not 1 <= len(selected) <= 32
            or not all(_hash(v) for v in selected) or len(set(selected)) != len(selected)
            or not isinstance(files, dict) or len(files) > 4096):
        raise VirtualLoaderError(error)
    total = 0
    for name, row in files.items():
        if (not _hash(name) or not isinstance(row, dict) or set(row) != {'size', 'sha256'}
                or type(row['size']) is not int or row['size'] < 0 or not _hash(row['sha256'])):
            raise VirtualLoaderError(error)
        total += row['size']
    if total > 4 * 1024 * 1024 * 1024:
        raise VirtualLoaderError(error)
    context = value['context']
    hashes = {'profile_sha256', 'executable_sha256', 'compiler_sha256', 'compilation_identity',
              'sources_sha256', 'underlay_sha256'}
    if (not isinstance(context, dict) or set(context) != hashes | {
            'generation', 'runtime', 'items', 'physical_items', 'outputs', 'provider_binding'}
            or any(not _hash(context[key]) for key in hashes) or not _uuid(context['generation'])
            or not isinstance(context['runtime'], dict) or set(context['runtime']) != {'bootstrap', 'loader'}
            or any(v is not None and not _hash(v) for v in context['runtime'].values())):
        raise VirtualLoaderError(error)
    for key, limit in (('items', 128), ('physical_items', 4096)):
        rows = context[key]
        if not isinstance(rows, dict) or len(rows) > limit:
            raise VirtualLoaderError(error)
        for identity, row in rows.items():
            if (not _uuid(identity) or not isinstance(row, dict) or set(row) != {'digest', 'binding_hash'}
                    or any(not _hash(v) for v in row.values())):
                raise VirtualLoaderError(error)
    outputs = context['outputs']
    if (not isinstance(outputs, dict) or not outputs or len(outputs) > 256
            or any(not isinstance(k, str) or not re.fullmatch(
                r'(?:meta/0\.(?:papgt|pathc)|[A-Za-z0-9_-]+/0\.(?:pamt|paz))', k)
                or not _hash(v) for k, v in outputs.items())):
        raise VirtualLoaderError(error)
    binding = context['provider_binding']
    if binding is not None:
        if (not isinstance(binding, dict) or set(binding) != {'binding_hash', 'values'}
                or not _hash(binding['binding_hash']) or not isinstance(binding['values'], dict)
                or set(binding['values']) - {'iteminfo', 'multichangeinfo', 'dropsetinfo', 'effect'}):
            raise VirtualLoaderError(error)
        for symbols in binding['values'].values():
            if (not isinstance(symbols, dict) or len(symbols) > 4096
                    or any(not isinstance(k, str) or not 1 <= len(k) <= 128 or type(v) is not int
                           or not 0 < v <= 0xffffffff for k, v in symbols.items())):
                raise VirtualLoaderError(error)
    try:
        payload = {k: v for k, v in value.items() if k != 'identity'}
        if len(encoded(value)) > MAX_RECORD or checksum(encoded(payload)) != value['identity']:
            raise VirtualLoaderError(error)
    except (TypeError, ValueError, RecursionError) as exc:
        raise VirtualLoaderError(error) from exc
    return value


def decode(data):
    if not isinstance(data, bytes) or len(data) > MAX_RECORD:
        raise VirtualLoaderError('Save experiment capture exceeds its size limit.')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate capture key.')
            result[key] = value
        return result
    try:
        return validate(json.loads(data, object_pairs_hook=unique))
    except (TypeError, ValueError, RecursionError) as exc:
        raise VirtualLoaderError('Invalid or changed save experiment capture.') from exc


def describe_save_attempt(before, after, selected, outcome):
    """Describe selected-file observations without identifying a save writer."""
    changed = sorted(name for name in selected if name in after and before.get(name) != after[name])
    unchanged = sorted(name for name in selected if name in after and before.get(name) == after[name])
    missing = sorted(set(selected) - set(after))
    if changed and (unchanged or missing):
        effect = 'partially-changed'
    elif missing:
        effect = 'missing-selected-members'
    elif changed:
        effect = 'changed'
    else:
        effect = 'unchanged'
    return {'operator_outcome': 'reported-saved' if outcome == 'saved' else outcome,
            'file_effect': effect, 'changed_selected_files': changed,
            'unchanged_selected_files': unchanged, 'missing_selected_files': missing,
            'other_files_changed': {k: v for k, v in before.items() if k not in selected}
                                   != {k: v for k, v in after.items() if k not in selected},
            'producer': 'unknown', 'produced_context': 'unknown', 'ancestry': 'unknown',
            'limitation': 'File effects describe the observed copies. A mixed or changed file set '
                          'does not establish a partial or completed game save.'}


def compare(captures):
    """Even a consistent six-step sequence remains an operator-reported candidate."""
    if not 1 <= len(captures) <= len(STAGES):
        raise VirtualLoaderError('Supply one ordered save experiment, starting at baseline.')
    values = [validate(c) for c in captures]
    first = values[0]
    for index, value in enumerate(values):
        if (value['stage'] != STAGES[index] or value['experiment'] != first['experiment']
                or value['provider'] != first['provider'] or value['selected'] != first['selected']
                or value['parent'] != (None if not index else values[index - 1]['identity'])):
            raise VirtualLoaderError('Save experiment captures are missing, reordered or from different experiments.')
    checks = []
    def check(code, condition, detail):
        checks.append({'check': code, 'consistent': bool(condition), 'detail': detail})
    provider = first['provider']
    baseline = first['context']
    def chosen(value):
        return {key: value['files'].get(key) for key in first['selected']}
    def effective(context):
        return {key: value for key, value in context.items()
                if key not in {'generation', 'profile_sha256', 'compilation_identity'}}
    check('baseline-provider', provider in baseline['items'], 'The baseline selects the provider virtually.')
    for value in values:
        stage, context = value['stage'], value['context']
        present = provider in context['items'] or provider in context['physical_items']
        check(stage + ':provider', present == (not stage.startswith('absent_')),
              'Provider presence follows the intended experiment stage.')
        if stage != 'absent_saved' or value['observation']['outcome'] == 'saved':
            check(stage + ':selected-files', all(row is not None for row in chosen(value).values()),
                  'Every explicitly selected save file exists in this copy.')
        check(stage + ':bindings', context['provider_binding'] == baseline['provider_binding']
              and baseline['provider_binding'] is not None, 'Retained provider bindings have not changed.')
        check(stage + ':environment', all(context[k] == baseline[k] for k in
              ('executable_sha256', 'runtime', 'compiler_sha256', 'underlay_sha256', 'physical_items')),
              'Executable, recorded runtime files, compiler and physical underlay remain the same.')
        check(stage + ':other-packages',
              {k: v for k, v in context['items'].items() if k != provider}
              == {k: v for k, v in baseline['items'].items() if k != provider},
              'Other selected package content and bindings remain the same.')
    if len(values) > 1:
        check('absent-load-input', chosen(values[1]) == chosen(first),
              'The absent-provider load starts with the original selected save bytes.')
    if len(values) > 2:
        check('absent-load-no-save', chosen(values[2]) == chosen(values[1]),
              'The selected save bytes did not change during the reported load-only case.')
    save_attempt = None
    attempt_observation = None
    if len(values) > 3:
        outcome = values[3]['observation']['outcome']
        def other_files(value):
            return {key: row for key, row in value['files'].items() if key not in first['selected']}
        save_attempt = {
            'outcome': outcome,
            'selected_bytes_changed': chosen(values[3]) != chosen(values[2]),
            'other_files_changed': other_files(values[3]) != other_files(values[2]),
            'missing_selected_files': [key for key, row in chosen(values[3]).items() if row is None],
        }
        attempt_observation = describe_save_attempt(values[2]['files'], values[3]['files'],
                                                    first['selected'], outcome)
        if outcome == 'saved':
            check('new-absent-save', save_attempt['selected_bytes_changed'],
                  'The reported absent-provider save has different selected bytes; this alone does not prove a game write.')
    if len(values) > 4:
        if save_attempt['outcome'] == 'saved':
            check('restore-new-save-input', chosen(values[4]) == chosen(values[3])
                  and chosen(values[4]) != chosen(first),
                  'The restored-provider load starts with the newly written copy, not the original recovery save.')
        else:
            check('restore-save-attempt-input', chosen(values[4]) == chosen(values[3]),
                  'The restored-provider case retains the attempted-save bytes. '
                  'A failed or unknown attempt does not establish a committed save.')
    if len(values) > 5:
        check('restored-load-no-save', chosen(values[5]) == chosen(values[4]),
              'The selected save bytes stayed unchanged during the restored-provider load-only case. '
              'Different bytes, including possible autosaves, leave this sequence inconsistent and unverified.')
    for index in (2, 3):
        if len(values) > index:
            check(STAGES[index] + ':same-absent-context',
                  effective(values[index]['context']) == effective(values[1]['context']),
                  'The prepared absent-provider context stayed the same.')
    for index in (4, 5):
        if len(values) > index:
            check(STAGES[index] + ':restored-context', effective(values[index]['context']) == effective(baseline),
                  'Restored package content, bindings, source contracts and prepared output match the baseline.')
    complete = len(values) == len(STAGES)
    consistent = all(row['consistent'] for row in checks)
    outcomes = {row['stage']: row['observation']['outcome'] for row in values}
    if not consistent:
        status = 'inconsistent'
    elif 'failed' in outcomes.values():
        status = 'reported-failure'
    elif 'unknown' in outcomes.values():
        status = 'unverified-outcome'
    elif not complete:
        status = 'incomplete'
    else:
        status = 'candidate-observation'
    return {'format': 'cdmw_virtual_save_comparison_v1', 'experiment': first['experiment'],
            'status': status, 'claims': dict(CLAIMS), 'checks': checks, 'outcomes': outcomes,
            'missing_stages': list(STAGES[len(values):]), 'save_attempt': save_attempt,
            'save_attempt_observation': attempt_observation,
            'limitation': 'Hashes establish copy/context consistency, not save origin, game activation, '
                          'successful deserialization or migration safety. Operator reports are not authenticated.'}
