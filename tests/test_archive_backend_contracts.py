from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from cdmw.domain.archives.catalogue import (
    ArchiveDurableIdentity,
    ArchiveEntryDto,
    ArchiveEntryRole,
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
    CreateQueryRequest,
    FetchPageRequest,
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
    }


def test_archive_entry_and_page_parse_to_frozen_bounded_contracts() -> None:
    entry = ArchiveEntryDto.from_wire(_entry_payload())
    assert entry.role is ArchiveEntryRole.MODEL
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
            "sort_descending": True,
        }
    }


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
