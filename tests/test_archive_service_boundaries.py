from __future__ import annotations

from unittest.mock import patch

from cdmw.services import (
    archive_environment_service,
    archive_extraction_service,
    archive_preview_service,
    archive_query_service,
    archive_read_service,
)
from cdmw.services.archive_service import ArchiveService


def test_archive_service_composes_focused_read_only_surfaces() -> None:
    service = ArchiveService(settings=object())

    assert service.reads is archive_read_service
    assert service.queries is archive_query_service
    assert service.previews is archive_preview_service
    assert service.extraction is archive_extraction_service
    assert service.environment is archive_environment_service


def test_archive_read_service_delegates_to_read_owner() -> None:
    with patch("cdmw.core.archive_extraction.format_byte_size", return_value="bounded") as owner:
        assert archive_read_service.format_byte_size(42) == "bounded"

    owner.assert_called_once_with(42)


def test_archive_query_service_delegates_to_query_owner() -> None:
    marker = object()
    with patch("cdmw.core.archive_asset_family.build_archive_asset_family_graph", return_value=marker) as owner:
        assert archive_query_service.build_archive_asset_family_graph("entry", stop_event=None) is marker

    owner.assert_called_once_with("entry", stop_event=None)


def test_archive_preview_service_delegates_to_preview_owner() -> None:
    marker = object()
    with patch("cdmw.core.archive_media_preview.ensure_archive_preview_source", return_value=marker) as owner:
        assert archive_preview_service.ensure_archive_preview_source("entry", output_root="cache") is marker

    owner.assert_called_once_with("entry", output_root="cache")


def test_archive_extraction_service_delegates_to_extraction_owner() -> None:
    with patch("cdmw.core.archive_extraction.clear_directory_contents", return_value=3) as owner:
        assert archive_extraction_service.clear_directory_contents("output") == 3

    owner.assert_called_once_with("output")


def test_archive_environment_service_delegates_to_environment_owner() -> None:
    marker = object()
    with patch("cdmw.core.archive_scan_cache.archive_scan_shard_cache_health", return_value=marker) as owner:
        assert archive_environment_service.archive_scan_shard_cache_health("root", "cache") is marker

    owner.assert_called_once_with("root", "cache")
