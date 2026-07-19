from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from cdmw.domain.archives.catalogue import (
    ArchiveChildrenRequest,
    ArchiveChildrenResult,
    ArchiveAssociationPurpose,
    ArchiveAssociationRequest,
    ArchiveDurableIdentity,
    ArchiveEntryDto,
    ArchiveEntryRole,
    ArchiveLookupResult,
    ArchivePage,
    ArchiveQuery,
    ArchiveSortField,
    ArchiveViewMode,
)
from cdmw.domain.archives.catalogue_operations import (
    ARCHIVE_BACKEND_PROTOCOL_VERSION,
    ArchiveBackendEnvelope,
    ArchiveBackendOperation,
    ArchiveBackendStatus,
    ArchiveExportCollisionPolicy,
    ArchiveExportRequest,
    ArchiveExportSelectionKind,
    ArchiveTextMatch,
    CreateQueryRequest,
    FetchPageRequest,
    PrepareEntriesRequest,
    PrepareEntriesResult,
)
from cdmw.domain.archives.catalogue_wire import ArchiveContractError, to_wire


def _entry_payload() -> dict[str, object]:
    return {
        "session_id": "session-a",
        "entry_id": 41,
        "identity": {
            "normalized_path": "character/model/example.pac",
            "source_pamt": "c:/game/0009/0.pamt",
            "paz_index": 2,
            "archive_offset": 8192,
        },
        "path": "character/model/Example.pac",
        "source_pamt": "C:/game/0009/0.pamt",
        "paz_file": "C:/game/0009/2.paz",
        "paz_index": 2,
        "offset": 8192,
        "stored_size": 1024,
        "original_size": 2048,
        "flags": 2,
        "extension": ".pac",
        "package": "0009/0.pamt",
        "role": "model",
        "category": "model_mesh_physics",
        "is_previewable": True,
        "known_name": "Example Sword",
        "exact_name": "Example Sword",
        "name_evidence": "Exact localization",
        "is_active_override": False,
        "override_state": "Shadowed original",
    }


def test_archive_entry_and_page_parse_to_frozen_bounded_contracts() -> None:
    entry = ArchiveEntryDto.from_wire(_entry_payload())
    assert entry.role is ArchiveEntryRole.MODEL
    assert entry.override_state == "Shadowed original"
    assert entry.identity == ArchiveDurableIdentity(
        "character/model/example.pac",
        "c:/game/0009/0.pamt",
        2,
        8192,
    )
    page = ArchivePage.from_wire(
        {
            "session_id": "session-a",
            "query_id": "query-a",
            "generation": 9,
            "total_matches": 100_000,
            "page_start": 256,
            "rows": [_entry_payload()],
        }
    )
    assert page.total_matches == 100_000
    assert len(page.rows) == 1
    with pytest.raises(FrozenInstanceError):
        page.total_matches = 0  # type: ignore[misc]


def test_query_serializes_using_worker_snake_case_enums() -> None:
    query = ArchiveQuery(
        session_id="session-a",
        include_text="sword",
        extensions=(".pac", ".prefab"),
        roles=(ArchiveEntryRole.MODEL,),
        view_mode=ArchiveViewMode.CATEGORIES_AND_FOLDERS,
        sort_field=ArchiveSortField.KNOWN_NAME,
        sort_active=True,
        sort_descending=True,
    )
    payload = to_wire(CreateQueryRequest(query))
    assert payload == {
        "query": {
            "session_id": "session-a",
            "include_text": "sword",
            "exclude_text": None,
            "extensions": [".pac", ".prefab"],
            "packages": [],
            "folder": None,
            "roles": ["model"],
            "technical_suffixes": [],
            "minimum_size": None,
            "previewable_only": False,
            "active_overrides_only": False,
            "view_mode": "categories_and_folders",
            "sort_field": "known_name",
            "sort_active": True,
            "sort_descending": True,
        }
    }


def test_text_match_parses_optional_package_label() -> None:
    match = ArchiveTextMatch.from_wire(
        {
            "entry_id": 7,
            "path": "text/example.txt",
            "line": 2,
            "column": 4,
            "length": 6,
            "context": "first needle",
            "package": "0009/0.pamt",
        }
    )

    assert match.package == "0009/0.pamt"


def test_envelope_round_trip_validates_correlation_fields() -> None:
    request_id = uuid4()
    request = ArchiveBackendEnvelope.request(
        ArchiveBackendOperation.FETCH_PAGE,
        FetchPageRequest("query-a", page_start=512, page_size=128),
        request_id=request_id,
        ui_generation=17,
        session_id="session-a",
    )
    wire = to_wire(request)
    parsed = ArchiveBackendEnvelope.from_wire(wire)
    assert parsed.protocol_version == ARCHIVE_BACKEND_PROTOCOL_VERSION
    assert parsed.request_id == str(request_id)
    assert parsed.operation is ArchiveBackendOperation.FETCH_PAGE
    assert parsed.status is ArchiveBackendStatus.REQUEST
    assert parsed.payload == {"query_id": "query-a", "page_start": 512, "page_size": 128}


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({**_entry_payload(), "role": "unknown-role"}, "unsupported value"),
        ({**_entry_payload(), "stored_size": "large"}, "stored_size must be an integer"),
        ({**_entry_payload(), "identity": None}, "archive identity must be an object"),
    ],
)
def test_archive_entry_rejects_malformed_worker_payloads(payload: object, message: str) -> None:
    with pytest.raises(ArchiveContractError, match=message):
        ArchiveEntryDto.from_wire(payload)


def test_fetch_page_enforces_worker_page_bound() -> None:
    with pytest.raises(ValueError, match="between 1 and 512"):
        FetchPageRequest("query-a", page_size=513)


def test_prepare_entries_contract_is_bounded_and_parses_stream_batches() -> None:
    request = PrepareEntriesRequest("session-a", (7, 9))
    assert to_wire(request) == {"session_id": "session-a", "entry_ids": [7, 9]}
    result = PrepareEntriesResult.from_wire(
        {
            "session_id": "session-a",
            "items": [
                {
                    "entry": {
                        "session_id": "session-a",
                        "entry_id": 7,
                        "identity": _entry_payload()["identity"],
                        "display_path": "character/model/Example.pac",
                    },
                    "prepared_path": "C:/cache/example.pac",
                    "size": 2048,
                    "sha256": "abc",
                    "note": "prepared",
                }
            ],
            "requested": 2,
            "prepared": 2,
            "total_bytes": 4096,
        }
    )
    assert result.items[0].entry.entry_id == 7
    assert result.total_bytes == 4096

    with pytest.raises(ValueError, match="at least one"):
        PrepareEntriesRequest("session-a", ())
    with pytest.raises(ValueError, match="must not contain duplicates"):
        PrepareEntriesRequest("session-a", (7, 7))
    with pytest.raises(ValueError, match="4,096"):
        PrepareEntriesRequest("session-a", tuple(range(4_097)))


def test_preview_association_contract_selects_semantic_dependency_mode() -> None:
    request = ArchiveAssociationRequest(
        "session-a",
        7,
        limit=4095,
        purpose=ArchiveAssociationPurpose.PREVIEW,
    )

    assert to_wire(request) == {
        "session_id": "session-a",
        "entry_id": 7,
        "limit": 4095,
        "purpose": "preview",
    }


def test_query_aware_lookup_parses_selection_row_positions() -> None:
    result = ArchiveLookupResult.from_wire(
        {
            "session_id": "session-a",
            "entries": [_entry_payload()],
            "total_matches": 1,
            "truncated": False,
            "query_rows": [98],
        }
    )

    assert result.entries[0].entry_id == 41
    assert result.query_rows == (98,)


def test_archive_children_contract_supports_bounded_continuation_pages() -> None:
    request = ArchiveChildrenRequest(
        "query-a",
        parent_path="character",
        limit=128,
        offset=256,
        include_package_root=True,
    )
    assert to_wire(request) == {
        "query_id": "query-a",
        "parent_path": "character",
        "category": None,
        "limit": 128,
        "offset": 256,
        "include_package_root": True,
    }
    result = ArchiveChildrenResult.from_wire(
        {
            "session_id": "session-a",
            "query_id": "query-a",
            "children": [],
            "truncated": True,
            "offset": 256,
            "total_children": 900,
            "next_offset": 384,
        }
    )
    assert result.offset == 256
    assert result.total_children == 900
    assert result.next_offset == 384

    legacy_result = ArchiveChildrenResult.from_wire(
        {
            "session_id": "session-a",
            "query_id": "query-a",
            "children": [],
            "truncated": True,
        }
    )
    assert legacy_result.next_offset == 0

    with pytest.raises(ValueError, match="must not be negative"):
        ArchiveChildrenRequest("query-a", offset=-1)


def test_archive_export_contract_carries_worker_owned_layout_and_collision_options() -> None:
    request = ArchiveExportRequest(
        session_id="session-a",
        selection_kind=ArchiveExportSelectionKind.FOLDER,
        destination="C:/exports/current",
        folder_path="0009/character/model",
        collision_policy=ArchiveExportCollisionPolicy.RENAME,
        include_package_root=True,
        replace_destination=True,
        extensions=(".dds", "material"),
    )

    assert to_wire(request) == {
        "session_id": "session-a",
        "selection_kind": "folder",
        "destination": "C:/exports/current",
        "entry_ids": [],
        "query_id": None,
        "folder_path": "0009/character/model",
        "family_entry_id": None,
        "collision_policy": "rename",
        "write_manifest": True,
        "include_package_root": True,
        "replace_destination": True,
        "extensions": [".dds", "material"],
    }
