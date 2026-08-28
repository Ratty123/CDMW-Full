from __future__ import annotations

from pathlib import Path

import pytest

from cdmw.core.archive_extraction import extract_archive_entries
from cdmw.domain.archives.mutation import ArchiveAddRequest
from cdmw.domain.archives.safety import safe_archive_output_path
from cdmw.models import ArchiveEntry
from cdmw.services.archive_overlay_package_service import export_archive_overlay_package


@pytest.mark.parametrize(
    "relative_path",
    (
        ".",
        "../outside.bin",
        "folder/../outside.bin",
        "folder/./outside.bin",
        "/outside.bin",
        r"\outside.bin",
        r"C:\outside.bin",
        r"C:outside.bin",
        r"\\server\share\outside.bin",
        r"\\?\C:\outside.bin",
        "CON",
        "CLOCK$",
        "aux.txt",
        "COM¹.log",
        "folder/trailing.",
        "folder/trailing ",
    ),
)
def test_archive_output_path_rejects_windows_escape_and_alias_forms(
    tmp_path: Path,
    relative_path: str,
) -> None:
    with pytest.raises(ValueError, match="unsafe archive path"):
        safe_archive_output_path(
            tmp_path,
            relative_path,
            error_message="unsafe archive path",
        )


@pytest.mark.parametrize(
    ("relative_path", "expected"),
    (
        ("folder//file.bin", Path("folder/file.bin")),
        (r"folder\nested/file.bin", Path("folder/nested/file.bin")),
        ("folder/ratio∕file.bin", Path("folder/ratio∕file.bin")),
        ("folder/fullwidth／file.bin", Path("folder/fullwidth／file.bin")),
    ),
)
def test_archive_output_path_normalizes_real_separators_without_rewriting_unicode(
    tmp_path: Path,
    relative_path: str,
    expected: Path,
) -> None:
    target = safe_archive_output_path(
        tmp_path,
        relative_path,
        error_message="unsafe archive path",
    )

    assert target == tmp_path / expected
    assert target.resolve(strict=False).is_relative_to(tmp_path.resolve())


def test_archive_output_path_can_require_one_group_component(tmp_path: Path) -> None:
    assert safe_archive_output_path(
        tmp_path,
        "0036",
        error_message="unsafe archive group",
        single_component=True,
    ) == tmp_path / "0036"

    for invalid_group in ("nested/0036", "0036/", r"0036\\"):
        with pytest.raises(ValueError, match="unsafe archive group"):
            safe_archive_output_path(
                tmp_path,
                invalid_group,
                error_message="unsafe archive group",
                single_component=True,
            )


def test_archive_extraction_rejects_a_rooted_entry_before_writing_outside_output(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source" / "0000"
    source.mkdir(parents=True)
    pamt_path = source / "0.pamt"
    paz_path = source / "0.paz"
    payload = b"payload"
    pamt_path.write_bytes(b"pamt")
    paz_path.write_bytes(payload)
    outside = tmp_path / "outside.bin"
    rooted_entry_path = "/" + outside.resolve().relative_to(Path(outside.resolve().anchor)).as_posix()
    entry = ArchiveEntry(
        path=rooted_entry_path,
        pamt_path=pamt_path,
        paz_file=paz_path,
        offset=0,
        comp_size=len(payload),
        orig_size=len(payload),
        flags=0,
        paz_index=0,
    )

    stats = extract_archive_entries((entry,), tmp_path / "output")

    assert stats["extracted"] == 0
    assert stats["failed"] == 1
    assert not outside.exists()


def _addition(tmp_path: Path) -> ArchiveAddRequest:
    return ArchiveAddRequest(
        pamt_path=tmp_path / "source" / "0.pamt",
        path="object/test.bin",
        payload_data=b"payload",
    )


def test_overlay_export_rejects_an_escaping_group_before_any_write(tmp_path: Path) -> None:
    package_root = tmp_path / "package"
    outside = tmp_path / "outside"

    with pytest.raises(ValueError, match="escapes the package"):
        export_archive_overlay_package(
            (),
            (_addition(tmp_path),),
            package_root=package_root,
            group="../outside",
        )

    assert not package_root.exists()
    assert not outside.exists()


def test_overlay_export_preflights_metadata_before_publishing_group_files(tmp_path: Path) -> None:
    package_root = tmp_path / "package"
    outside = tmp_path / "outside.txt"

    with pytest.raises(ValueError, match="escapes the package"):
        export_archive_overlay_package(
            (),
            (_addition(tmp_path),),
            package_root=package_root,
            group="0036",
            metadata_files=(("../outside.txt", b"outside"),),
        )

    assert not package_root.exists()
    assert not outside.exists()
