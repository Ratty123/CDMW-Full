from __future__ import annotations

from cdmw.domain.archives.prefab import (
    PREFAB_EDIT_JSON_FORMAT,
    PREFAB_EDIT_JSON_VERSION,
    SUPPORTED_PREFAB_EDIT_ROLES,
    SUPPORTED_PREFAB_PLACEMENT_FIELDS,
    PrefabEditJsonError,
)

from cdmw.core.prefab_json_apply import (
    apply_prefab_edit_document,
    rebuild_prefab_no_edit_from_edit_document,
    apply_prefab_edit_json,
)

from cdmw.core.prefab_json_common import (
    _sha256_hex,
    _as_mapping,
    _as_list,
    _as_string,
    _as_int,
    _as_bool,
    _require_keys,
    _normalize_path,
    _resource_path_extension,
    _validate_resource_replacement_path,
)

from cdmw.core.prefab_json_document import (
    _header_document,
    _member_declarations_document,
    _layout_document,
    _offset_candidates_document,
    _resize_impact_document,
    _validate_resize_impact,
    _length_change_blocked_message,
    _placement_fields_document,
    _role_set,
    _is_exact_layout_string_field,
    _resource_reference_rows_document,
    _resize_readiness_document,
    _policy_document,
    build_prefab_edit_document,
    dumps_prefab_edit_json,
)

from cdmw.core.prefab_json_validation import (
    _validate_source_identity,
    _current_reference_keys_and_counts,
    _current_placement_keys,
    _validate_resize_readiness,
    _validate_policy,
    _validate_structure,
    _validate_declared_fields,
    _validate_placement_rows,
    _editable_rows,
)


__all__ = ['PREFAB_EDIT_JSON_FORMAT', 'PREFAB_EDIT_JSON_VERSION', 'SUPPORTED_PREFAB_EDIT_ROLES', 'SUPPORTED_PREFAB_PLACEMENT_FIELDS', 'PrefabEditJsonError', 'apply_prefab_edit_document', 'apply_prefab_edit_json', 'build_prefab_edit_document', 'dumps_prefab_edit_json', 'rebuild_prefab_no_edit_from_edit_document']
