"""Prepare separate resource images for research; never install or admit native items.

The current resolver remains the authority for packages, source dependencies and
identity reservations. Its shared-definition outputs are reported, not packed.
Large archive checks retain the existing temporary-file/checksum-helper policy.
"""
from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import struct

from cdmw.core.archive_format import calculate_pa_checksum, parse_archive_pamt_bytes
from cdmw.core.archive_overlay import (
    OverlayFile, PAZ_ALIGNMENT, PAMT_CONSTANT, _payload_checksum, build_overlay_archive,
)
from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, PapgtDirectory, parse_papgt, serialize_papgt
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.compilation import compiler_stamp
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.independent_item_install import _binding_hash, resolve_items
from cdmw.services.independent_item_package import (
    MAX_BLOB, MAX_FILES, MAX_TOTAL, canonical, digest, virtual_path,
)


_SHARED_SUFFIXES = frozenset({
    ".staticinfoheader", ".staticinfobody", ".pabgh", ".pabgb", ".pappt",
    ".papgt", ".pamt", ".paz", ".pathc", ".paver",
})
_FILES = ("meta/0.papgt", "0000/0.pamt", "0000/0.paz")


@dataclass(frozen=True, slots=True)
class NativeResourceImage:
    """Immutable research bytes and a detached diagnostic report, not a lease."""

    identity: str
    mount_bytes: bytes
    index_bytes: bytes
    archive_bytes: bytes
    report_bytes: bytes

    @property
    def files(self):
        return tuple(zip(_FILES, (self.mount_bytes, self.index_bytes, self.archive_bytes)))

    def report(self):
        return json.loads(self.report_bytes)


def _need(condition, message):
    if not condition:
        raise IndependentItemError(message)


def _validate_observed(resolved, stop_event):
    for revision in resolved.revisions:
        revision.validate(stop_event)
    resolved.external.validate(stop_event)
    overlays._verify_observed_state(
        resolved.root, resolved.observed, "during private resource preparation", IndependentItemError)
    raise_if_cancelled(stop_event)


def _index_end(index):
    """Require the complete single-PAZ layout, including its exact final extent."""
    _need(len(index) >= 24, "The private resource index is truncated.")
    offset = 24
    for width in (1, 1, 16, 20):
        _need(offset + 4 <= len(index), "The private resource index is truncated.")
        count = struct.unpack_from("<I", index, offset)[0]
        offset += 4 + count * width
        _need(offset <= len(index), "The private resource index is truncated.")
    _need(offset == len(index), "The private resource index has trailing data.")


def _verify_image(mount, index, archive, expected, stop_event):
    """Check serialized bytes against compiler payloads, beyond parser acceptance."""
    _index_end(index)
    checksum, count, constant, paz_index, paz_checksum, paz_size = struct.unpack_from("<6I", index)
    _need(count == 1 and constant == PAMT_CONSTANT and paz_index == 0,
          "The private resource archive layout differs.")
    _need(checksum == calculate_pa_checksum(index[12:]), "The private resource index checksum differs.")
    _need(paz_size == len(archive) and len(archive) % PAZ_ALIGNMENT == 0,
          "The private resource archive size differs.")
    _need(paz_checksum == _payload_checksum(archive, stop_event=stop_event),
          "The private resource archive checksum differs.")
    directories = parse_papgt(mount)
    _need(directories == (PapgtDirectory("0000", PAPGT_DEFAULT_FLAGS, checksum),),
          "The private resource mount does not name its exact index.")
    entries = parse_archive_pamt_bytes(index, Path("0000/0.pamt"), stop_event=stop_event)
    _need(len(entries) == len(expected) and len({entry.path for entry in entries}) == len(entries),
          "The private resource index membership differs.")
    rows, end = [], 0
    for entry in entries:
        raise_if_cancelled(stop_event)
        _need(entry.path in expected, "The private resource index contains an unexpected member.")
        data, compiler_flags = expected[entry.path]
        _need(entry.flags == 0 and entry.paz_index == 0
              and entry.comp_size == entry.orig_size == len(data)
              and entry.offset >= end and entry.offset % PAZ_ALIGNMENT == 0
              and entry.offset + len(data) <= len(archive),
              "The private resource entry range or representation differs.")
        _need(not any(archive[end:entry.offset]), "The private resource archive padding differs.")
        _need(archive[entry.offset:entry.offset + len(data)] == data,
              "The private resource bytes differ from the compiled contribution.")
        rows.append({"path": entry.path, "offset": entry.offset, "bytes": len(data),
                     "sha256": digest(data), "stored_flags": 0, "compiler_flags": compiler_flags})
        end = entry.offset + len(data)
    _need(not any(archive[end:]), "The private resource archive tail differs.")
    return rows


def _binding_status(row, prior, current_paths):
    old = prior or {"values": {}, "paths": [], "stem": ""}
    symbols = [{"namespace": namespace, "symbol": symbol, "value": value,
                "status": "retained" if old["values"].get(namespace, {}).get(symbol) == value else "proposed"}
               for namespace, values in sorted(row["values"].items()) for symbol, value in sorted(values.items())]
    paths = [{"path": path, "status": "retained" if path in old["paths"] else "proposed",
              "in_image": path in current_paths} for path in sorted(row["paths"])]
    return {"symbols": symbols, "paths": paths,
            "stem": {"value": row["stem"], "status": "retained" if prior and old["stem"] == row["stem"] else "proposed"},
            "projection": "retained" if prior and all(old[key] == row[key] for key in ("values", "stem", "paths")) else "proposed",
            "reservations_committed": False}


def _private_members(package, changes, row, assessment, stop_event):
    _need(assessment.get("identity") == package.identity
          and assessment.get("content_sha256") == package.digest
          and assessment.get("artifact_sha256") == package.artifact_digest,
          "The resource assessment does not match its captured package.")
    _need(assessment.get("contribution_class") == "new-item" and not assessment.get("stock_edits"),
          "Private resource preparation supports new-item contributions without stock-edit modules.")
    _need(assessment.get("proposed_bindings") == row["values"]
          and assessment.get("proposed_paths") == sorted(row["paths"])
          and row["binding_hash"] == _binding_hash(package.identity, row),
          "The resource contribution does not match its identity reservation.")
    graph = assessment.get("resource_graph")
    _need(isinstance(graph, dict), "The resource ownership assessment is missing.")
    graph_rows = graph.get("resources", ())
    graph_by_path = {entry["path"]: entry for entry in graph_rows}
    _need(len(graph_by_path) == len(graph_rows), "The resource graph contains duplicate paths.")
    records = assessment.get("private_outputs", ())
    reported = {entry["path"]: entry for entry in records}
    _need(len(reported) == len(records), "The resource assessment contains duplicate private outputs.")
    expected = {}
    total = 0
    for path, change in sorted(changes.items()):
        raise_if_cancelled(stop_event)
        if change["before"] is not None or change["after"] is None:
            continue
        _need(not change["meta"] and PurePosixPath(path).suffix not in _SHARED_SUFFIXES
              and not path.startswith(("meta/", "gamedata/binarystaticinfo__/")),
              "A shared definition, registry or archive carrier cannot enter a private resource image.")
        _need(virtual_path(path) == path and path in row["paths"],
              "The private resource path is not reserved by this package.")
        data = change["after"]
        _need(type(data) is bytes and 0 < len(data) <= MAX_BLOB,
              "The private resource payload is empty, mutable or exceeds the size limit.")
        total += len(data)
        _need(total <= MAX_TOTAL and len(expected) < MAX_FILES,
              "The private resources exceed the package size or member limit.")
        checksum = digest(data)
        claim, resource = reported.get(path), graph_by_path.get(path)
        _need(claim is not None and claim.get("bytes") == len(data) and claim.get("sha256") == checksum
              and resource is not None and resource.get("ownership") == "owned"
              and resource.get("sha256") == checksum and resource.get("byte_size") == len(data),
              "The private resource bytes do not match the derived ownership assessment.")
        _need(type(change["flags"]) is int and 0 <= change["flags"] <= 0xFFFF,
              "The compiled resource representation flags are invalid.")
        expected[path] = (data, change["flags"])
    _need(expected and set(expected) == set(reported), "The private resource output set is empty or incomplete.")
    padded = sum((len(data) + PAZ_ALIGNMENT - 1) // PAZ_ALIGNMENT * PAZ_ALIGNMENT for data, _flags in expected.values())
    _need(padded <= MAX_TOTAL and padded <= 0xFFFFFFFF, "The private resource archive exceeds its size limit.")
    return expected


def prepare_native_resource_images(sources, root, *, target="virtual", folders=(), stop_event=None, read_entry=None):
    """Return uninstalled per-package research images using current identity rules.

    Existing bindings are retained; new bindings are proposals only. Shared
    definitions and unresolved references remain visible in each report. These
    bytes do not establish native discovery, decoding, lifetime or save behavior.
    """
    sources = tuple(sources)
    _need(1 <= len(sources) <= 128, "Select between one and 128 packages for resource preparation.")
    raise_if_cancelled(stop_event)
    resolved = resolve_items(sources, root, target=target, folders=folders, rebuild=True,
                             capture_isolation=True, stop_event=stop_event, read_entry=read_entry)
    _validate_observed(resolved, stop_event)
    mount = dict(resolved.observed).get("meta/0.papgt")
    _need(type(mount) is bytes, "The captured source mount is missing.")
    parse_papgt(mount)
    prior = json.loads(resolved.registry_before)["items"]
    assessments = {entry["identity"]: entry for entry in resolved.isolation_assessments}
    identities = [package.identity for package, _changes in resolved.contributions]
    _need(len(identities) == len(set(identities)) == len(assessments) == len(resolved.isolation_assessments)
          and set(identities) == set(assessments), "Every resource contribution needs one exact assessment.")
    _need(identities, "No resource contributions were resolved.")
    images, total_bytes = [], 0
    for package, changes in sorted(resolved.contributions, key=lambda pair: pair[0].identity):
        raise_if_cancelled(stop_event)
        row = resolved.registry["items"][package.identity]
        assessment = assessments[package.identity]
        expected = _private_members(package, changes, row, assessment, stop_event)
        padded = sum((len(data) + PAZ_ALIGNMENT - 1) // PAZ_ALIGNMENT * PAZ_ALIGNMENT for data, _flags in expected.values())
        _need(total_bytes + padded <= MAX_TOTAL, "The private resource images exceed the batch size limit.")
        archive = build_overlay_archive(tuple(OverlayFile(path, data, len(data), 0)
                                              for path, (data, _flags) in expected.items()), stop_event=stop_event)
        private_mount = serialize_papgt((PapgtDirectory("0000", PAPGT_DEFAULT_FLAGS, archive.pamt_checksum),), header=mount[:12])
        members = _verify_image(private_mount, archive.pamt_bytes, archive.paz_bytes, expected, stop_event)
        files = tuple(zip(_FILES, (private_mount, archive.pamt_bytes, archive.paz_bytes)))
        file_pins = [{"path": path, "bytes": len(data), "sha256": digest(data)} for path, data in files]
        image_size = sum(len(data) for _path, data in files)
        total_bytes += image_size
        _need(total_bytes <= MAX_TOTAL, "The private resource images exceed the batch size limit.")
        report = {
            "format": "cdmw_native_resource_image_research_v1", "identity": package.identity,
            "content_sha256": package.digest, "artifact_sha256": package.artifact_digest,
            "binding_sha256": row["binding_hash"], "resource_image_sha256": digest(canonical(file_pins)),
            "compiler": compiler_stamp(), "binding_source_target": target,
            "bindings": row["values"], "binding_status": _binding_status(row, prior.get(package.identity), set(expected)),
            "binding_scope": assessment["binding_scope"], "added_records": assessment["added_records"],
            "members": members, "files": file_pins,
            "storage": {"members": len(members), "payload_bytes": sum(len(data) for data, _flags in expected.values()),
                        "archive_bytes": len(archive.paz_bytes), "metadata_bytes": len(private_mount) + len(archive.pamt_bytes),
                        "image_bytes": image_size},
            "source_mount_sha256": digest(mount), "source_mount_header_hex": mount[:12].hex(),
            "excluded_shared_outputs": assessment["shared_outputs"],
            "shared_integrations": assessment["shared_integrations"],
            "package_dependencies": assessment["package_dependencies"],
            "source_dependencies": assessment["source_dependencies"],
            "protected_game_records": assessment["protected_game_records"],
            "borrowed_contribution_paths": assessment["borrowed_contribution_paths"], "resource_graph": assessment["resource_graph"],
            "source_assessment_reasons": assessment["isolated_new_item"]["reasons"],
            "representation": "Logical compiler payloads stored uncompressed with flags zero; resource-specific native decoding is unverified.",
            "checksum_policy": "Existing archive checksum policy may use temporary files and an installed checksum helper for large payloads.",
            "evidence_scope": "Validated package/compiler output and archive byte checks under the existing checksum policy; no native engine or game observation.",
            "published": False, "native_engine_calls_executed": False, "native_resource_use_verified": False,
            "native_admission": False, "reference_closure_claimed": False,
        }
        images.append(NativeResourceImage(package.identity, private_mount, archive.pamt_bytes, archive.paz_bytes, canonical(report)))
    _validate_observed(resolved, stop_event)
    return tuple(images)
