"""Frozen operation and envelope contracts for the archive backend process."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping
from uuid import UUID, uuid4

from .catalogue import ArchiveEntryRef, ArchiveQuery
from .catalogue_wire import (
    read_bool,
    read_enum,
    read_int,
    read_optional_string,
    read_string,
    read_string_tuple,
    require_mapping,
    require_sequence,
    to_wire,
)


ARCHIVE_BACKEND_PROTOCOL_VERSION = 2
ARCHIVE_BACKEND_MAXIMUM_MESSAGE_BYTES = 1024 * 1024
ARCHIVE_BACKEND_DEFAULT_PAGE_SIZE = 256
ARCHIVE_BACKEND_MAXIMUM_PAGE_SIZE = 512


class ArchiveBackendOperation(str, Enum):
    PING = "ping"
    SHUTDOWN = "shutdown"
    CANCEL = "cancel"
    CACHE_HEALTH = "cache_health"
    OPEN_ARCHIVE = "open_archive"
    REFRESH_ARCHIVE = "refresh_archive"
    CREATE_QUERY = "create_query"
    FETCH_PAGE = "fetch_page"
    FETCH_CHILDREN = "fetch_children"
    FACETS = "facets"
    RESOLVE_ENTRIES = "resolve_entries"
    FIND_ASSOCIATION_CANDIDATES = "find_association_candidates"
    PREPARE_ENTRY = "prepare_entry"
    TEXT_SEARCH = "text_search"
    EXPORT = "export"


class ArchiveBackendStatus(str, Enum):
    REQUEST = "request"
    STARTED = "started"
    PROGRESS = "progress"
    BATCH = "batch"
    RESULT = "result"
    CANCELLED = "cancelled"
    ERROR = "error"


class ArchiveExportSelectionKind(str, Enum):
    ENTRY_IDS = "entry_ids"
    QUERY = "query"
    FOLDER = "folder"
    FAMILY = "family"


class ArchiveExportCollisionPolicy(str, Enum):
    SKIP = "skip"
    OVERWRITE = "overwrite"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class ArchiveBackendError:
    code: str
    message: str
    detail: str | None = None

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveBackendError":
        payload = require_mapping(value, "archive backend error")
        return cls(
            code=read_string(payload, "code"),
            message=read_string(payload, "message"),
            detail=read_optional_string(payload, "detail"),
        )


@dataclass(frozen=True, slots=True)
class ArchiveBackendEnvelope:
    protocol_version: int
    request_id: str
    ui_generation: int
    session_id: str | None
    operation: ArchiveBackendOperation
    status: ArchiveBackendStatus
    payload: Mapping[str, object] | None = None
    error: ArchiveBackendError | None = None

    @classmethod
    def request(
        cls,
        operation: ArchiveBackendOperation,
        payload: object,
        *,
        ui_generation: int,
        session_id: str | None = None,
        request_id: UUID | str | None = None,
    ) -> "ArchiveBackendEnvelope":
        wire_payload = to_wire(payload)
        if not isinstance(wire_payload, Mapping):
            raise TypeError("Archive backend request payload must serialize to an object.")
        return cls(
            protocol_version=ARCHIVE_BACKEND_PROTOCOL_VERSION,
            request_id=str(request_id or uuid4()),
            ui_generation=int(ui_generation),
            session_id=session_id,
            operation=operation,
            status=ArchiveBackendStatus.REQUEST,
            payload=wire_payload,
        )

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveBackendEnvelope":
        message = require_mapping(value, "archive backend message")
        request_id = read_string(message, "request_id")
        try:
            UUID(request_id)
        except ValueError as exc:
            raise ValueError("request_id must be a UUID.") from exc
        raw_payload = message.get("payload")
        raw_error = message.get("error")
        return cls(
            protocol_version=read_int(message, "protocol_version"),
            request_id=request_id,
            ui_generation=read_int(message, "ui_generation"),
            session_id=read_optional_string(message, "session_id"),
            operation=read_enum(message, "operation", ArchiveBackendOperation),
            status=read_enum(message, "status", ArchiveBackendStatus),
            payload=None if raw_payload is None else require_mapping(raw_payload, "payload"),
            error=None if raw_error is None else ArchiveBackendError.from_wire(raw_error),
        )


@dataclass(frozen=True, slots=True)
class PingRequest:
    client_version: str


@dataclass(frozen=True, slots=True)
class CancelRequest:
    target_request_id: str


@dataclass(frozen=True, slots=True)
class PingResult:
    worker_version: str
    protocol_version: int
    native_abi_version: int
    index_version: int
    process_id: int

    @classmethod
    def from_wire(cls, value: object) -> "PingResult":
        payload = require_mapping(value, "ping result")
        return cls(
            worker_version=read_string(payload, "worker_version"),
            protocol_version=read_int(payload, "protocol_version"),
            native_abi_version=read_int(payload, "native_abi_version"),
            index_version=read_int(payload, "index_version"),
            process_id=read_int(payload, "process_id"),
        )


@dataclass(frozen=True, slots=True)
class CacheHealthRequest:
    package_root: str


@dataclass(frozen=True, slots=True)
class CacheHealthResult:
    package_root: str
    root_id: str
    state: str
    reason: str
    fingerprint: str | None = None
    generation_id: str | None = None
    entry_count: int = 0

    @classmethod
    def from_wire(cls, value: object) -> "CacheHealthResult":
        payload = require_mapping(value, "cache health result")
        return cls(
            package_root=read_string(payload, "package_root"),
            root_id=read_string(payload, "root_id"),
            state=read_string(payload, "state"),
            reason=read_string(payload, "reason"),
            fingerprint=read_optional_string(payload, "fingerprint"),
            generation_id=read_optional_string(payload, "generation_id"),
            entry_count=read_int(payload, "entry_count", default=0),
        )


@dataclass(frozen=True, slots=True)
class OpenArchiveRequest:
    package_root: str
    force_refresh: bool = False


@dataclass(frozen=True, slots=True)
class CreateQueryRequest:
    query: ArchiveQuery


@dataclass(frozen=True, slots=True)
class FetchPageRequest:
    query_id: str
    page_start: int = 0
    page_size: int = ARCHIVE_BACKEND_DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        if self.page_start < 0:
            raise ValueError("page_start must not be negative.")
        if not 1 <= self.page_size <= ARCHIVE_BACKEND_MAXIMUM_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {ARCHIVE_BACKEND_MAXIMUM_PAGE_SIZE}.")


@dataclass(frozen=True, slots=True)
class PrepareEntryRequest:
    session_id: str
    entry_id: int


@dataclass(frozen=True, slots=True)
class PrepareEntryResult:
    entry: ArchiveEntryRef
    prepared_path: str
    size: int
    sha256: str
    note: str | None = None

    @classmethod
    def from_wire(cls, value: object) -> "PrepareEntryResult":
        payload = require_mapping(value, "prepare entry result")
        return cls(
            entry=ArchiveEntryRef.from_wire(payload.get("entry")),
            prepared_path=read_string(payload, "prepared_path"),
            size=read_int(payload, "size"),
            sha256=read_string(payload, "sha256"),
            note=read_optional_string(payload, "note"),
        )


@dataclass(frozen=True, slots=True)
class ArchiveTextSearchRequest:
    session_id: str
    query: str
    use_regular_expression: bool = False
    case_sensitive: bool = False
    path_filter: str | None = None
    extensions: tuple[str, ...] = ()
    maximum_matches: int = 2_000
    context_characters: int = 160
    regex_timeout_milliseconds: int = 1_000
    batch_size: int = 128


@dataclass(frozen=True, slots=True)
class ArchiveTextMatch:
    entry_id: int
    path: str
    line: int
    column: int
    length: int
    context: str

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveTextMatch":
        payload = require_mapping(value, "archive text match")
        return cls(
            entry_id=read_int(payload, "entry_id"),
            path=read_string(payload, "path"),
            line=read_int(payload, "line"),
            column=read_int(payload, "column"),
            length=read_int(payload, "length"),
            context=read_string(payload, "context"),
        )


@dataclass(frozen=True, slots=True)
class ArchiveTextSearchBatch:
    session_id: str
    files_scanned: int
    files_matched: int
    bytes_read: int
    matches: tuple[ArchiveTextMatch, ...]
    is_final: bool
    limit_reached: bool
    warnings: tuple[str, ...]

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveTextSearchBatch":
        payload = require_mapping(value, "archive text search batch")
        matches = require_sequence(payload.get("matches"), "matches")
        return cls(
            session_id=read_string(payload, "session_id"),
            files_scanned=read_int(payload, "files_scanned"),
            files_matched=read_int(payload, "files_matched"),
            bytes_read=read_int(payload, "bytes_read"),
            matches=tuple(ArchiveTextMatch.from_wire(match) for match in matches),
            is_final=read_bool(payload, "is_final"),
            limit_reached=read_bool(payload, "limit_reached"),
            warnings=read_string_tuple(payload, "warnings"),
        )


@dataclass(frozen=True, slots=True)
class ArchiveExportRequest:
    session_id: str
    selection_kind: ArchiveExportSelectionKind
    destination: str
    entry_ids: tuple[int, ...] = ()
    query_id: str | None = None
    folder_path: str | None = None
    family_entry_id: int | None = None
    collision_policy: ArchiveExportCollisionPolicy = ArchiveExportCollisionPolicy.SKIP
    write_manifest: bool = True


@dataclass(frozen=True, slots=True)
class ArchiveExportItem:
    source_path: str
    output_path: str | None
    status: str
    message: str | None = None

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveExportItem":
        payload = require_mapping(value, "archive export item")
        return cls(
            source_path=read_string(payload, "source_path"),
            output_path=read_optional_string(payload, "output_path"),
            status=read_string(payload, "status"),
            message=read_optional_string(payload, "message"),
        )


@dataclass(frozen=True, slots=True)
class ArchiveExportResult:
    session_id: str
    requested: int
    exported: int
    skipped: int
    failed: int
    cancelled: bool
    manifest_path: str | None
    items: tuple[ArchiveExportItem, ...]
    items_truncated: bool

    @classmethod
    def from_wire(cls, value: object) -> "ArchiveExportResult":
        payload = require_mapping(value, "archive export result")
        items = require_sequence(payload.get("items"), "items")
        return cls(
            session_id=read_string(payload, "session_id"),
            requested=read_int(payload, "requested"),
            exported=read_int(payload, "exported"),
            skipped=read_int(payload, "skipped"),
            failed=read_int(payload, "failed"),
            cancelled=read_bool(payload, "cancelled"),
            manifest_path=read_optional_string(payload, "manifest_path"),
            items=tuple(ArchiveExportItem.from_wire(item) for item in items),
            items_truncated=read_bool(payload, "items_truncated"),
        )


@dataclass(frozen=True, slots=True)
class ProgressUpdate:
    completed: int
    total: int
    phase: str
    current_item: str | None = None

    @classmethod
    def from_wire(cls, value: object) -> "ProgressUpdate":
        payload = require_mapping(value, "progress update")
        return cls(
            completed=read_int(payload, "completed"),
            total=read_int(payload, "total"),
            phase=read_string(payload, "phase"),
            current_item=read_optional_string(payload, "current_item"),
        )


__all__ = [
    "ARCHIVE_BACKEND_DEFAULT_PAGE_SIZE",
    "ARCHIVE_BACKEND_MAXIMUM_MESSAGE_BYTES",
    "ARCHIVE_BACKEND_MAXIMUM_PAGE_SIZE",
    "ARCHIVE_BACKEND_PROTOCOL_VERSION",
    "ArchiveBackendEnvelope",
    "ArchiveBackendError",
    "ArchiveBackendOperation",
    "ArchiveBackendStatus",
    "ArchiveExportCollisionPolicy",
    "ArchiveExportItem",
    "ArchiveExportRequest",
    "ArchiveExportResult",
    "ArchiveExportSelectionKind",
    "ArchiveTextMatch",
    "ArchiveTextSearchBatch",
    "ArchiveTextSearchRequest",
    "CancelRequest",
    "CacheHealthRequest",
    "CacheHealthResult",
    "CreateQueryRequest",
    "FetchPageRequest",
    "OpenArchiveRequest",
    "PingRequest",
    "PingResult",
    "PrepareEntryRequest",
    "PrepareEntryResult",
    "ProgressUpdate",
]
