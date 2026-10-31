"""Read-only incoming-reference discovery. Paths, IDs and guesses stay distinct."""

from __future__ import annotations

import html
import posixpath
import re
import struct
import threading
from dataclasses import dataclass

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_wwise_bank import is_sound_bank, read_bank_chunks
from cdmw.core.common import raise_if_cancelled
from cdmw.domain.archives.association_vocabulary import reference_container_extensions
from cdmw.domain.archives.content_capabilities import load_capabilities
from cdmw.domain.archives.reference_sources import REFERENCE_SOURCES_BY_TARGET, RUNTIME_NAMED_TARGETS
from cdmw.domain.archives.resource_paths import length_prefix_variants, stored_reference_forms
from cdmw.domain.research.contracts import RESEARCH_REFERENCE_SOURCE_EXTENSIONS
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference, RunCancelled


MAX_REFERENCE_FILE_BYTES = 32 * 1024 * 1024
MAX_REFERENCE_RESULTS = 2000
REFERENCE_SOURCE_EXTENSIONS = tuple(sorted(reference_container_extensions() | RESEARCH_REFERENCE_SOURCE_EXTENSIONS))
_ANIMATION_GRAPH_TARGETS = frozenset({".paa", ".motionblending", ".paac", ".paseq", ".pab", ".prefab"})
# Charts, blend spaces and sequences name clips, blend spaces, sub-charts and
# prefabs; read them before the hundreds of thousands of clips themselves.
_ANIMATION_GRAPH_SOURCES = frozenset({".paac", ".motionblending", ".paseq", ".paseqc", ".pastage"})
REVERSE_TARGET_EXTENSIONS = frozenset(
    {capability.extension for capability in load_capabilities() if capability.group in {"texture_image", "audio_video"}}
    | {".seqmt", ".pac", ".pam", ".pamlod", ".prefab", ".pab", ".paa", ".motionblending", ".paac", ".paseq"}
)
CONFIRMED_REFERENCE_CONFIDENCES = frozenset({"explicit_path", "wwise_media_id"})


#: Why a search reads nothing: the target is chosen by name at run time.
NOTE_RUNTIME_NAMED_SOUND = "runtime_named_sound"
#: Why a search reads nothing: no shipped format stores paths of this kind.
NOTE_NO_PATH_SOURCES = "no_path_sources"


@dataclass(frozen=True)
class ReferenceSearchPlan:
    """What one Find references search reads, in order, and what it looks for."""

    groups: tuple[tuple[str, ...], ...]
    #: Names whose presence makes a file worth reading in full (casefolded).
    needles: tuple[str, ...]
    #: For a numeric `.wem`: banks are searched for this media ID instead of a name.
    bank_media_id: int | None = None
    #: Set when the plan is deliberately empty; the UI explains it.
    note: str = ""


def _search_names(target: ArchiveEntry) -> tuple[str, ...]:
    """The basename and the last segment of every form the target is stored under."""

    target_forms = set(stored_reference_forms(target.path)) or {_path(target.path)}
    return tuple(dict.fromkeys((target.basename.casefold(), *(form.rpartition("/")[2] for form in target_forms))))


def reference_search_needles(target: ArchiveEntry) -> tuple[str, ...]:
    """The fewest names that every stored form of the target contains."""

    names = tuple(name for name in _search_names(target) if name)
    shortest = min(names, key=len, default="")
    if shortest and all(shortest in name for name in names):
        return (shortest,)
    return names


def reference_search_plan(target: ArchiveEntry) -> ReferenceSearchPlan:
    """Read only the formats measured to store paths of the target's kind."""

    needles = reference_search_needles(target)
    if target.extension in RUNTIME_NAMED_TARGETS:
        stem = target.basename[: -len(target.extension)]
        if stem.isdigit():
            return ReferenceSearchPlan(((".bnk",),), needles, bank_media_id=int(stem))
        return ReferenceSearchPlan((), needles, note=NOTE_RUNTIME_NAMED_SOUND)
    groups: list[tuple[str, ...]] = []
    seen: set[str] = set()
    if target.extension in _ANIMATION_GRAPH_TARGETS:
        # Charts, blend spaces and sequences also name targets without an extension.
        groups.append(tuple(sorted(_ANIMATION_GRAPH_SOURCES)))
        seen.update(_ANIMATION_GRAPH_SOURCES)
    for measured in REFERENCE_SOURCES_BY_TARGET.get(target.extension, ()):
        remaining = tuple(source for source in measured if source not in seen)
        seen.update(remaining)
        if remaining:
            groups.append(remaining)
    if not groups:
        return ReferenceSearchPlan((), needles, note=NOTE_NO_PATH_SOURCES)
    return ReferenceSearchPlan(tuple(groups), needles)


def reference_source_extension_groups(target: ArchiveEntry) -> tuple[tuple[str, ...], ...]:
    """Read likely reference owners before large geometry/animation payloads."""
    return reference_search_plan(target).groups


def bank_media_id_query(media_id: int) -> str:
    """A media ID as the four little-endian bytes a bank stores, one character per byte."""

    return struct.pack("<I", media_id).decode("latin-1")


def may_name_target(data: bytes, needles: tuple[str, ...]) -> bool:
    """Whether a file can hold any needle, as ASCII or UTF-16; no decoding needed.

    Reading every candidate as text, three encodings over, was the dominant cost
    of a search. A file without the bytes cannot produce a match below.
    """

    lowered = data.lower()
    for needle in needles:
        try:
            raw = needle.encode("ascii")
        except UnicodeEncodeError:
            return True
        if raw in lowered or needle.encode("utf-16-le") in lowered or needle.encode("utf-16-be") in lowered:
            return True
    return False


def reference_evidence_group(confidence: str, status: str = "resolved") -> str:
    if status.casefold() in {"missing", "unresolved", "technical_only", "context"}:
        return "Unresolved / context"
    if confidence.casefold() in CONFIRMED_REFERENCE_CONFIDENCES:
        return "Confirmed references"
    if confidence.casefold() in {"authoritative", "exact_path"}:
        return "Confirmed references"
    if confidence.casefold() in {"derived_same_stem", "derived_family_heuristic", "path_normalized",
                                "cross_package", "basename_fallback", "token_match", "sidecar_match"}:
        return "Name-based guesses"
    return "Unresolved / context"


def _path(value: str) -> str:
    return posixpath.normpath(html.unescape(value).replace("\\", "/").strip()).lstrip("/").casefold()


def read_bank_media_reference_ids(data: bytes) -> tuple[set[int], bool]:
    """DIDX and bounded HIRC Sound source headers; never search arbitrary u32s.

    Standard LE versions 113..154 share the source-ID prefix. Versions >150
    add cacheID after sourceID. Generators/external sources are not file media.
    Layout reference: bnnm/wwiser, wparser.py, CAkBankMgr__LoadSource and
    CAkBankMgr__ReadSourceParent_CAkSound_. This does not decode event graphs.
    """
    if not is_sound_bank(data):
        return set(), False
    chunks, consumed = read_bank_chunks(data)
    if consumed != len(data) or not chunks or chunks[0].identifier != "BKHD" or chunks[0].size < 4:
        return set(), False
    version = struct.unpack_from("<I", data, chunks[0].offset)[0]
    ids: set[int] = set()
    supported = True
    for chunk in chunks:
        start, end = chunk.offset, chunk.offset + chunk.size
        if chunk.identifier == "DIDX":
            if chunk.size % 12:
                return set(), False
            for offset in range(start, end, 12):
                ids.add(struct.unpack_from("<I", data, offset)[0])
        elif chunk.identifier == "HIRC":
            if not 113 <= version <= 154 or chunk.size < 4:
                supported = False
                continue
            count = struct.unpack_from("<I", data, start)[0]
            cursor = start + 4
            if count > (end - cursor) // 9:
                return set(), False
            for _ in range(count):
                if cursor + 5 > end:
                    return set(), False
                kind, size = struct.unpack_from("<BI", data, cursor)
                cursor += 5
                if size < 4 or cursor + size > end:
                    return set(), False
                if kind == 2:
                    # object ID, plugin ID, stream type, source ID, [cache ID],
                    # in-memory byte count, source flags, then node parameters.
                    minimum = 22 if version > 150 else 18
                    if size < minimum:
                        return set(), False
                    plugin = struct.unpack_from("<I", data, cursor + 4)[0]
                    stream_type = data[cursor + 8]
                    source_id = struct.unpack_from("<I", data, cursor + 9)[0]
                    if plugin & 0xF == 1 and plugin != 0x00080001 and stream_type in {0, 1, 2} and source_id:
                        ids.add(source_id)
                cursor += size
            if cursor != end:
                return set(), False
    return ids, supported


def _length_prefixed_form(data: bytes, forms) -> str:
    """A stored form written as a whole u32-length-prefixed string, as reflection
    containers (prefabs, effects, presets) store paths.

    The byte after such a string belongs to the next field and can be anything,
    `/` included, so the text matcher below would reject it; a length that equals
    the form's own length says the string is exactly that path.
    """

    lowered = data.lower()
    for form in forms:
        raw = form.encode("utf-8")
        if not raw:
            continue
        start = lowered.find(raw)
        while start >= 0:
            if start >= 4 and struct.unpack_from("<I", data, start - 4)[0] == len(raw):
                return data[start:start + len(raw)].decode("utf-8", errors="replace")
            start = lowered.find(raw, start + 1)
    return ""


def _matching_path_tokens(text: str, basename: str):
    # Search the literal basename first. Running an unanchored general path
    # expression over large binary/string runs can have quadratic cost.
    def path_char(char):
        return char.isalnum() or char in "_@%+-./\\()"

    for match in re.finditer(re.escape(basename), text, re.IGNORECASE):
        if match.end() < len(text) and path_char(text[match.end()]):
            continue
        start = match.start()
        while start and match.end() - start < 4096 and path_char(text[start - 1]):
            start -= 1
        if start and path_char(text[start - 1]):
            continue
        yield text[start:match.end()]


def incoming_reference(target: ArchiveEntry, source: ArchiveEntry, data: bytes) -> tuple[ArchiveModelTextureReference | None, bool]:
    """Return one strongest incoming edge per source, plus bank coverage."""
    if source.identity == target.identity:
        return None, True
    confidence = ""
    evidence = ""
    supported = True
    target_path = _path(target.path)
    target_name = target.basename.casefold()
    if source.extension == ".bnk":
        ids, supported = read_bank_media_reference_ids(data)
        if target.extension == ".wem" and target_name[:-4].isdigit() and int(target_name[:-4]) in ids:
            confidence = "wwise_media_id"
            evidence = target_name[:-4]
        # Media bytes can contain coincidental filenames; never string-scan banks.
    else:
        # A container may store the target under the folder the engine reads it
        # from (`1_pc/clip.paa` for `character/motion/1_pc/clip.paa`) or without
        # its extension (sub-charts, sequences). Each stored form is searched by
        # its own last segment.
        target_forms = set(stored_reference_forms(target.path)) or {target_path}
        search_names = _search_names(target)
        if not may_name_target(data, reference_search_needles(target)):
            return None, supported
        stored = _length_prefixed_form(data, target_forms)
        if stored:
            confidence, evidence = "explicit_path", stored
        texts = [] if confidence else [data.decode("utf-8-sig", errors="replace")]
        if not confidence and (b"\x00" in data or data.startswith((b"\xff\xfe", b"\xfe\xff"))):
            texts.extend((data.decode("utf-16-le", errors="replace"), data.decode("utf-16-be", errors="replace")))
        for text in texts:
            unescaped = html.unescape(text)
            for search_name in search_names:
                for raw_token in _matching_path_tokens(unescaped, search_name):
                    for stored in length_prefix_variants(raw_token):
                        token = _path(stored)
                        has_path = "/" in stored.replace("\\", "/")
                        if has_path and (
                            token in target_forms
                            or _path(posixpath.join(posixpath.dirname(source.path), stored.replace("\\", "/"))) == target_path
                        ):
                            confidence, evidence = "explicit_path", stored
                            break
                        # An explicit path to a DIFFERENT folder is not a basename hit.
                        if not has_path and token == target_name and not confidence:
                            confidence, evidence = "derived_same_stem", stored
                    if confidence == "explicit_path":
                        break
                if confidence == "explicit_path":
                    break
            if confidence == "explicit_path":
                break
    if not confidence:
        return None, supported
    return ArchiveModelTextureReference(
        reference_name=source.basename, resolution_status="resolved", resolved_entry=source,
        resolved_archive_path=source.path, resolved_package_label=source.package_label,
        reference_kind="used_by", relation_group="Used By", relation_confidence=confidence,
        relation_reason=evidence, usage_count=1,
    ), supported


@dataclass(frozen=True)
class ReferenceScanBatch:
    references: tuple[ArchiveModelTextureReference, ...] = ()
    scanned: int = 0
    skipped: int = 0
    unreadable: int = 0
    unsupported_banks: int = 0
    bytes_read: int = 0


def scan_reference_batch(target: ArchiveEntry, entries: tuple[ArchiveEntry, ...], stop_event: threading.Event) -> ReferenceScanBatch:
    references = []
    scanned = skipped = unreadable = unsupported = byte_count = 0
    for source in entries:
        raise_if_cancelled(stop_event)
        if source.identity == target.identity:
            continue
        if max(source.orig_size, source.comp_size, source.prepared_size or 0) > MAX_REFERENCE_FILE_BYTES:
            skipped += 1
            continue
        try:
            data, _, _ = read_archive_entry_data(source, stop_event=stop_event)
            raise_if_cancelled(stop_event)
            if len(data) > MAX_REFERENCE_FILE_BYTES:
                skipped += 1
                continue
            reference, supported = incoming_reference(target, source, data)
            scanned += 1
            byte_count += len(data)
            unsupported += int(not supported)
            if reference is not None:
                references.append(reference)
        except RunCancelled:
            raise
        except (OSError, ValueError, RuntimeError, struct.error):
            unreadable += 1
    return ReferenceScanBatch(tuple(references), scanned, skipped, unreadable, unsupported, byte_count)
