"""Bounded .cditem export/import. Rebuild records from typed intent, never byte patches."""
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import threading
from types import MappingProxyType
import zipfile

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.independent import IndependentItemError, IndependentItemPackage, IndependentItemExport, package_id
from cdmw.services.independent_item_codec import encode, decode

FORMAT = "cdmw_independent_item"
VERSION = 1
MAX_MANIFEST = 4 * 1024 * 1024
MAX_BLOB = 256 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024
MAX_FILES = 4096
_ZIP_CHUNK_BYTES = 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MAX_SHARED_COMPRESSED = 64 * 1024 * 1024
_STOCK_CACHE_LOCK = threading.RLock()
_stock_snapshot_cache = None


@dataclass(frozen=True, slots=True)
class VerifiedBlobDigests:
    """Preparation-owned receipts for exact bytes that passed package admission."""
    _values: object

    def digest(self, raw):
        row = self._values.get(id(raw))
        return row[1] if type(raw) is bytes and row is not None and row[0] is raw else None


class PackageReadCache:
    """Bounded verified content owned by one preparation, never a path cache.

    Whole-package hits require its exact artifact digest. Member hits require
    the exact compressed bytes and decoder metadata of a member whose decoded
    CRC, size and content digest already passed. Returned mutable metadata and
    resource mappings belong to each caller; only immutable bytes are shared.
    """

    def __init__(self, *, max_bytes=MAX_BLOB, max_packages=128):
        self.max_bytes = max(0, min(int(max_bytes), MAX_TOTAL))
        self.max_packages = max(0, min(int(max_packages), 128))
        self._packages = OrderedDict()
        self._members = OrderedDict()
        self._package_bytes = self._member_bytes = 0
        self._lock = threading.RLock()

    def package(self, artifact):
        with self._lock:
            key = (artifact, MAX_MANIFEST, MAX_BLOB, MAX_TOTAL, MAX_FILES)
            row = self._packages.get(key)
            if row is None:
                return None
            self._packages.move_to_end(key)
            return deepcopy(row[0])

    def remember_package(self, package):
        size = len(canonical(package_metadata(package))) + sum(map(len, package.blobs.values()))
        if size > self.max_bytes or not self.max_packages:
            return
        with self._lock:
            key = (package.artifact_digest, MAX_MANIFEST, MAX_BLOB, MAX_TOTAL, MAX_FILES)
            if key in self._packages:
                return
            while self._packages and (self._package_bytes + size > self.max_bytes
                                      or len(self._packages) >= self.max_packages):
                _key, (_package, removed) = self._packages.popitem(last=False)
                self._package_bytes -= removed
            self._packages[key] = (deepcopy(package), size)
            self._package_bytes += size

    def member(self, representation):
        with self._lock:
            value = self._members.get(representation)
            if value is not None:
                self._members.move_to_end(representation)
            return value

    def remember_members(self, members):
        with self._lock:
            for representation, value in members:
                if len(value) > self.max_bytes or representation in self._members:
                    continue
                while self._members and (self._member_bytes + len(value) > self.max_bytes
                                         or len(self._members) >= MAX_FILES):
                    _key, removed = self._members.popitem(last=False)
                    self._member_bytes -= len(removed)
                self._members[representation] = value
                self._member_bytes += len(value)

    def verified_blob_digests(self, packages):
        """Retain only current, immutable objects from fully admitted cache entries.

        Package metadata supplied by a caller is not evidence. The digest comes
        from our private entry registered after raw SHA, CRC and recipe checks.
        Strong byte references prevent id reuse; misses still hash normally.
        """
        wanted = {}
        for package in packages:
            for raw in package.blobs.values():
                if type(raw) is bytes and len(wanted) < MAX_FILES:
                    wanted[id(raw)] = raw
        values = {}
        with self._lock:
            for package, _size in self._packages.values():
                for checksum, raw in package.blobs.items():
                    if type(raw) is bytes and wanted.get(id(raw)) is raw:
                        values[id(raw)] = (raw, checksum)
        return VerifiedBlobDigests(MappingProxyType(values))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def virtual_path(value):
    if (not isinstance(value, str) or not value or len(value) > 512 or value != value.lower()
            or "\\" in value or ":" in value or "\0" in value or value.startswith("/")
            or any(p in ("", ".", "..") or p.rstrip(" .") != p for p in value.split("/"))):
        raise IndependentItemError("Invalid package resource path.")
    if value.split("/")[0] not in {"character", "gamedata", "effect", "ui", "texture", "textures", "common", "sound"}:
        raise IndependentItemError(f"Unsupported package resource path: {value}")
    return value


def _stock_paths(root, stop_event):
    from cdmw.core.archive_format import discover_pamt_files
    from cdmw.services.archive_overlay_install import OVERLAY_DIRECTORY_FIRST
    paths = []
    for path in discover_pamt_files(root):
        raise_if_cancelled(stop_event)
        path = Path(path).resolve()
        folder = path.parent.name
        if not path.is_relative_to(root):
            raise IndependentItemError("The game archive layout is unsupported for independent items.")
        # Manager archives (including named groups) and nested copies are not
        # shipped inputs. Only direct, four-digit game groups form the baseline.
        if (path.parent.parent == root and len(folder) == 4
                and folder.isascii() and folder.isdigit() and int(folder) < OVERLAY_DIRECTORY_FIRST):
            paths.append(path)
    return tuple(sorted(paths))


def _stock_metadata(root, stop_event):
    # Mount order selects providers and pathc is parsed beside the archives.
    # Hash these small metadata inputs, not filesystem timestamps alone.
    values = []
    for relative in ('meta/0.papgt', 'meta/0.paver', 'meta/0.pathc'):
        raise_if_cancelled(stop_event)
        path = root / relative
        values.append((relative, digest(path.read_bytes()) if path.is_file() else None))
    raise_if_cancelled(stop_event)
    return tuple(values)


def _clean_stock_snapshot(root, service, read_entry, stop_event, on_log):
    from cdmw.core.archive_format import parse_archive_pamt_bytes
    from cdmw.domain.new_item.allocation import DEFAULT_ITEM_KEY_RANGE
    from cdmw.services.new_item_provenance import ArchiveCatalogue, StaleNewItemSource
    from cdmw.services.new_item_service import NewItemService, _snapshot_view
    global _stock_snapshot_cache

    paths = _stock_paths(root, stop_event)
    metadata = _stock_metadata(root, stop_event)
    # Normal services parse identical clean inputs. A custom reader or service
    # is a separate authority. Only one verified stock generation is retained.
    authority = None if type(service) is NewItemService else service
    key = (root, id(read_entry), paths, metadata, id(authority))
    with _STOCK_CACHE_LOCK:
        cached = _stock_snapshot_cache
    if cached is not None and cached[0] == key and not cached[1].source_files_changed():
        try:
            cached[1].provenance.capture().validate(stop_event)
        except StaleNewItemSource:
            pass  # Reparse current sources; never use stale table values.
        else:
            if _stock_metadata(root, stop_event) != metadata or _stock_paths(root, stop_event) != paths:
                raise StaleNewItemSource('The clean game catalogue changed during snapshot validation.')
            raise_if_cancelled(stop_event)
            if on_log is not None:
                on_log('Reusing the verified clean game catalogue and parsed item tables.')
            return _snapshot_view(cached[1])

    entries, indexes = [], []
    for path in paths:
        raise_if_cancelled(stop_event)
        data = path.read_bytes()
        entries.extend(parse_archive_pamt_bytes(data, path, stop_event=stop_event))
        indexes.append((path, digest(data)))
    catalogue = ArchiveCatalogue(tuple(entries), tuple(indexes))
    result = service.build_snapshot(catalogue, read_entry=read_entry, stop_event=stop_event, on_log=on_log)
    if any(key in DEFAULT_ITEM_KEY_RANGE for key in result.rows):
        raise IndependentItemError('The shipped item tables contain custom items. Restore a clean game baseline before using independent packages.')
    result.provenance.capture().validate(stop_event)
    if _stock_metadata(root, stop_event) != metadata or _stock_paths(root, stop_event) != paths:
        raise StaleNewItemSource('The clean game catalogue changed while building its snapshot.')
    retained = _snapshot_view(result, freeze=True)
    raise_if_cancelled(stop_event)
    with _STOCK_CACHE_LOCK:
        _stock_snapshot_cache = (key, retained, authority)
    return _snapshot_view(retained)


def stock_snapshot(root, *, service=None, read_entry=None, stop_event=None, on_log=None, overlay_changes=None):
    """Reuse only verified clean tables; overlay baseline rebasing is per request."""
    from cdmw.services.new_item_service import NewItemService
    root = Path(root).resolve()
    result = _clean_stock_snapshot(root, service or NewItemService(), read_entry, stop_event, on_log)
    # Authoring uses temporary identities, so its texture registry must have the
    # same baseline as its tables. Installed additions are resolved at install.
    if overlay_changes is None:
        from cdmw.services import archive_overlay_manager as overlays
        result.provenance.pin_file(overlays._target(root, overlays.INDEX_PATH))
        state = overlays._load_index(root)
        layers = (state or {}).get('layers', ())
        if not any(layer['active'] or layer.get('disabled') for layer in layers):
            layers = ()  # Removed history may predate the current game baseline.
        overlay_changes = (overlays._unpack_changes(root, layer, {}, stop_event) for layer in layers)
    for changes in overlay_changes:
        raise_if_cancelled(stop_event)
        if 'meta/0.pathc' in changes:
            from cdmw.core.pathc_format import parse_pathc
            baseline = changes['meta/0.pathc']['before']
            result.pathc = parse_pathc(baseline) if baseline is not None else None
            break
    return result


def audit_plan(plan, snapshot, *, stop_event=None):
    """Whitelist semantic addition paths; no edits to unrelated or global records."""
    from cdmw.domain.archives.overlay_merge import _table
    from cdmw.domain.new_item.spec import PlacementKind
    if snapshot.base_payloads or plan.spec.reward_acquisitions:
        raise IndependentItemError("Independent packages cannot modify existing reward consumers or include another mod base.")
    if any(p.kind not in (PlacementKind.NONE, PlacementKind.INSERT) for p in (plan.spec.shop_placements or (plan.spec.placement,))):
        raise IndependentItemError("Independent packages support adding shop stock, not replacing existing stock.")
    files = plan.loose_files
    pairs = {str(row["payload_path"]).lower(): str(row["header_path"]).lower() for row in plan.manifest["tables"].values()}
    allowed_tables = {"iteminfo", "stringinfo", "storeinfo", "itemgroupinfo", "multichangeinfo", "dropsetinfo", "partprefabdyeslotinfo"}
    for request in plan.patches:
        path = virtual_path(request.entry.path.lower())
        if path in pairs:
            name = PurePosixPath(path).name.split(".")[0]
            if name not in allowed_tables:
                raise IndependentItemError(f"Unsupported shared table: {name}")
            if name not in {"storeinfo", "itemgroupinfo"}:
                header = pairs[path]
                old = dict(_table(snapshot.payload(path), snapshot.payload(header))[1])
                new = dict(_table(files[path], files[header])[1])
                if any(new.get(key) != raw for key, raw in old.items()):
                    raise IndependentItemError(f"Independent item changes an existing {name} record.")
        elif path in pairs.values() or path.endswith((".paloc", ".pappt")) or path == "ui/xml/texture/cd_item_icon.xml":
            continue
        else:
            raise IndependentItemError(f"Independent packages cannot carry the shared change: {path}")
    for request in plan.additions:
        path = virtual_path(request.path.lower())
        if not path.endswith((".pac", ".pac_xml", ".dds", ".prefab", ".hkx", ".pae", ".paem", ".parg", ".pasg")):
            raise IndependentItemError(f"Unsupported owned resource: {path}")
    if any(write.path != "meta/0.pathc" for write in plan.meta_files):
        raise IndependentItemError("Unsupported shared metadata change.")
    from cdmw.services.independent_item_references import audit_references
    audit_references(plan, snapshot, stop_event=stop_event)


def _prepared_spec(spec):
    # Painted masks and surface/transform settings have already been baked into
    # ModelFiles. Keep the choices that control family ownership, not local inputs.
    def translucency(value):
        return replace(value, masks=()) if value is not None else None
    variants = None if spec.variants is None else tuple(replace(v, translucency=translucency(v.translucency)) for v in spec.variants)
    return replace(spec, item_key=None, stem=None, name_key=None, desc_key=None,
                   internal_name="IndependentItem", translucency=translucency(spec.translucency), variants=variants)


def from_plan(plan, identity, *, title=None, stop_event=None):
    package_id(identity)
    if plan.independent_inputs is None:
        raise IndependentItemError("Select Independent item package and rebuild the plan first.")
    if plan.source_revision is None:
        raise IndependentItemError("Independent packages require verified source dependencies.")
    plan.source_revision.validate(stop_event)
    model, variants, icon = plan.independent_inputs
    blobs = {}
    def blob(data):
        data = bytes(data)
        if len(data) > MAX_BLOB:
            raise IndependentItemError("An item resource exceeds the package size limit.")
        key = digest(data)
        blobs[key] = data
        return key
    def model_value(value):
        if value is None:
            return None
        return {"pac": blob(value.pac_data), "side_files": {virtual_path(path.lower()): blob(data) for path, data in value.side_files.items()},
                "material_route": value.material_route}
    recipe = {"spec": encode(_prepared_spec(plan.spec)), "model": model_value(model),
              "variants": [{"binding": list(key), "model": model_value(value)} for key, value in sorted(variants.items())],
              "icon": blob(icon) if icon is not None else None}
    dependencies = {}
    for row in plan.source_revision.payloads:
        folder = Path(row.entry.pamt_path).parent.name
        if not folder.isdigit() or int(folder) >= 36:
            raise IndependentItemError("Independent packages may borrow only shipped game resources. Rebuild against the clean game baseline.")
        path = virtual_path(row.entry.path.lower())
        if path in dependencies and dependencies[path] != row.sha256:
            raise IndependentItemError("The source contains conflicting resource versions.")
        dependencies[path] = row.sha256
    metadata = {"format": FORMAT, "version": VERSION, "identity": identity,
                "title": str(title or plan.spec.display_names.get("eng") or "Independent item"),
                "recipe": recipe, "dependencies": dependencies, "blobs": {key: len(data) for key, data in sorted(blobs.items())}}
    return _package(metadata, blobs)


def _package(meta, blobs, *, stop_event=None):
    if isinstance(meta, dict) and type(meta.get('version')) is int and meta['version'] == 2:
        from cdmw.services.independent_mod_package import read_v2
        return read_v2(meta, blobs, stop_event=stop_event)
    return _v1_package(meta, blobs)


def _v1_package(meta, blobs):
    if not isinstance(meta, dict) or set(meta) != {"format", "version", "identity", "title", "recipe", "dependencies", "blobs"} or meta["format"] != FORMAT or type(meta["version"]) is not int or meta["version"] != VERSION:
        raise IndependentItemError("Unsupported independent item package version or fields.")
    identity = _package_resources(meta, blobs)
    result = IndependentItemPackage(identity, meta["title"], meta["recipe"], meta["dependencies"], blobs, digest(canonical(meta)))
    unpack_recipe(result)  # Closed types, paths and every resource reference checked on import.
    return result


def _package_resources(meta, blobs):
    identity = package_id(meta["identity"])
    if not isinstance(meta["title"], str) or not 1 <= len(meta["title"]) <= 256 or "\0" in meta["title"]:
        raise IndependentItemError("Invalid item package title.")
    if not isinstance(meta["dependencies"], dict) or not meta["dependencies"]:
        raise IndependentItemError("The package has no verified game dependencies.")
    for path, checksum in meta["dependencies"].items():
        virtual_path(path)
        if not isinstance(checksum, str) or not _HASH.fullmatch(checksum):
            raise IndependentItemError("Invalid game dependency checksum.")
    if not isinstance(meta["blobs"], dict) or set(meta["blobs"]) != set(blobs):
        raise IndependentItemError("The package resource inventory does not match its contents.")
    if sum(len(v) for v in blobs.values()) > MAX_TOTAL:
        raise IndependentItemError("Item package exceeds the supported size.")
    for key, data in blobs.items():
        if not _HASH.fullmatch(key) or digest(data) != key or type(meta["blobs"][key]) is not int or meta["blobs"][key] != len(data):
            raise IndependentItemError("Item resource failed its checksum or size check.")
    return identity


def _recipe_values(package):
    from cdmw.domain.new_item.spec import NewItemSpec
    from cdmw.services.new_item_planning import ModelFiles
    value = package.recipe
    if not isinstance(value, dict) or set(value) != {"spec", "model", "variants", "icon"}:
        raise IndependentItemError("Invalid independent item recipe.")
    spec = decode(value["spec"])
    if not isinstance(spec, NewItemSpec) or any(v is not None for v in (spec.item_key, spec.stem, spec.name_key, spec.desc_key)):
        raise IndependentItemError("Portable items must use symbolic identities.")
    for variant in spec.variants or ():
        virtual_path(variant.prefab_path)
        virtual_path(variant.model_path)
        if any(assignment.mask_path for assignment in variant.dyes or ()):
            raise IndependentItemError("Local dye mask files are not supported in independent packages. Clear the custom dye mask before exporting.")
    used = set()
    def blob(key):
        if not isinstance(key, str) or key not in package.blobs:
            raise IndependentItemError("A required item resource is missing.")
        used.add(key)
        return package.blobs[key]
    def model(raw):
        if raw is None:
            return None
        if not isinstance(raw, dict) or set(raw) != {"pac", "side_files", "material_route"} or not isinstance(raw["side_files"], dict) or not isinstance(raw["material_route"], str):
            raise IndependentItemError("Invalid prepared model.")
        side = {virtual_path(path): blob(key) for path, key in raw["side_files"].items()}
        if any(not path.endswith((".pac", ".pac_xml", ".dds")) for path in side):
            raise IndependentItemError("Unsupported prepared model side file.")
        return ModelFiles(blob(raw["pac"]), side, raw["material_route"])
    primary = model(value["model"])
    variants = {}
    if not isinstance(value["variants"], list) or len(value["variants"]) > 128:
        raise IndependentItemError("Invalid prepared variants.")
    for row in value["variants"]:
        if not isinstance(row, dict) or set(row) != {"binding", "model"} or not isinstance(row["binding"], list) or len(row["binding"]) != 2:
            raise IndependentItemError("Invalid prepared variant binding.")
        key = tuple(virtual_path(v) for v in row["binding"])
        if key in variants:
            raise IndependentItemError("Duplicate prepared variant binding.")
        variants[key] = model(row["model"])
    icon = None if value["icon"] is None else blob(value["icon"])
    return spec, primary, variants, icon, used


def unpack_recipe(package):
    values = _recipe_values(package)
    used = values[-1]
    from cdmw.domain.new_item.mod_package import IndependentModPackage
    if isinstance(package, IndependentModPackage):
        from cdmw.services.independent_texture_package import texture_resource_keys
        used = used | texture_resource_keys(package)
    if used != set(package.blobs):
        raise IndependentItemError("The package contains unreferenced resources.")
    return values[:-1]


def package_metadata(package):
    from cdmw.domain.new_item.mod_package import IndependentModPackage
    if isinstance(package, IndependentModPackage):
        return package.manifest
    return {"format": FORMAT, "version": VERSION, "identity": package.identity, "title": package.title,
            "recipe": package.recipe, "dependencies": package.dependencies,
            "blobs": {key: len(data) for key, data in sorted(package.blobs.items())}}


def _write_package_archive(package, stream, stop_event):
    meta = package_metadata(package)
    data = canonical(meta)
    if len(data) > MAX_MANIFEST or len(package.blobs) + 1 > MAX_FILES:
        raise IndependentItemError("Item package metadata exceeds the supported size.")
    if any(len(payload) > MAX_BLOB for payload in package.blobs.values()):
        raise IndependentItemError("An item resource exceeds the package size limit.")
    if len(data) + sum(map(len, package.blobs.values())) > MAX_TOTAL:
        raise IndependentItemError("Item package exceeds the supported size.")
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        def member(name, payload):
            # Artifact identity must not depend on the wall clock or host OS.
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o600 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            info.file_size = len(payload)
            with archive.open(info, 'w') as writer:
                view = memoryview(payload)
                for offset in range(0, len(view), _ZIP_CHUNK_BYTES):
                    raise_if_cancelled(stop_event, 'Item package export cancelled.')
                    writer.write(view[offset:offset + _ZIP_CHUNK_BYTES])
                raise_if_cancelled(stop_event, 'Item package export cancelled.')
        member("item.json", data)
        for key, payload in sorted(package.blobs.items()):
            raise_if_cancelled(stop_event, "Item package export cancelled.")
            member("assets/" + key, payload)
    raise_if_cancelled(stop_event, "Item package export cancelled.")


def package_bytes(package, *, stop_event=None):
    stream = io.BytesIO()
    _write_package_archive(package, stream, stop_event)
    return stream.getvalue()


def _read_member(archive, member, stop_event):
    # Package members stay bounded by the validated directory above. Chunked
    # decoding adds cooperative cancellation without dropping ZIP CRC checks.
    expected = (archive.getinfo(member) if isinstance(member, str) else member).file_size
    raise_if_cancelled(stop_event)
    with archive.open(member, 'r') as reader:
        return _read_member_stream(reader, expected, stop_event)


def _read_member_stream(reader, expected, stop_event):
    result = io.BytesIO()
    raise_if_cancelled(stop_event)
    if expected:
        # Reserve once within the validated directory budget. Incremental growth
        # can temporarily retain two large buffers; getvalue can share this one.
        result.seek(expected - 1)
        result.write(b'\0')
        result.seek(0)
    while True:
        raise_if_cancelled(stop_event)
        chunk = reader.read(_ZIP_CHUNK_BYTES)
        raise_if_cancelled(stop_event)
        if not chunk:
            break
        if result.tell() + len(chunk) > expected:
            raise IndependentItemError("Item resource failed its checksum or size check.")
        result.write(chunk)
    if result.tell() != expected:
        # A lying central-directory size must never turn unwritten allocation
        # into accepted zero padding. CRC alone need not catch a short member.
        raise IndependentItemError("Item resource failed its checksum or size check.")
    return result.getvalue()


def _read_cached_member(archive, info, stop_event, cache, pending):
    if (info.compress_size > _MAX_SHARED_COMPRESSED or info.file_size > cache.max_bytes
            or cache.max_bytes == 0):
        return _read_member(archive, info, stop_event)
    # ZipFile owns local-header/name/overlap/method validation. Immediately after
    # open its source is positioned at this member's compressed data. Copy one
    # bounded representation so the bytes hashed for reuse are also the exact
    # bytes decoded and CRC-checked, even if an external writer races the read.
    compressed = io.BytesIO()
    with archive.open(info, 'r'):
        remaining = info.compress_size
        while remaining:
            raise_if_cancelled(stop_event)
            chunk = archive.fp.read(min(remaining, _ZIP_CHUNK_BYTES))
            if not chunk:
                raise IndependentItemError('Truncated item package resource.')
            compressed.write(chunk)
            remaining -= len(chunk)
    raw = compressed.getvalue()
    raise_if_cancelled(stop_event)
    representation = (info.filename, info.compress_type, info.flag_bits, info.compress_size,
                      info.file_size, info.CRC, digest(raw))
    value = cache.member(representation)
    if value is None:
        with zipfile.ZipExtFile(io.BytesIO(raw), 'r', info, close_fileobj=True) as reader:
            value = _read_member_stream(reader, info.file_size, stop_event)
        pending.append((representation, value))
    raise_if_cancelled(stop_event)
    return value


def _artifact_hash(source, stop_event):
    fingerprint, total = hashlib.sha256(), 0
    # Invalidate a BufferedReader's cached range after external writes.
    source.seek(0, 2)
    source.seek(0)
    while chunk := source.read(_ZIP_CHUNK_BYTES):
        raise_if_cancelled(stop_event)
        total += len(chunk)
        if total > MAX_TOTAL + MAX_MANIFEST:
            raise IndependentItemError('Item package exceeds the supported size.')
        fingerprint.update(chunk)
    raise_if_cancelled(stop_event)
    source.seek(0)
    return fingerprint.hexdigest()


def read_package(source, *, stop_event=None, cache=None):
    try:
        if isinstance(source, (str, Path)):
            if Path(source).stat().st_size > MAX_TOTAL + MAX_MANIFEST:
                raise IndependentItemError("Item package exceeds the supported size.")
            with Path(source).open('rb') as stream:
                return read_package(stream, stop_event=stop_event, cache=cache)
        immutable = isinstance(source, bytes)
        if immutable:
            if len(source) > MAX_TOTAL + MAX_MANIFEST:
                raise IndependentItemError("Item package exceeds the supported size.")
            source = io.BytesIO(source)
        artifact = _artifact_hash(source, stop_event)
        if cache is not None:
            cached = cache.package(artifact)
            if cached is not None:
                if not immutable and _artifact_hash(source, stop_event) != artifact:
                    raise IndependentItemError('The package changed while it was being read.')
                raise_if_cancelled(stop_event)
                return cached
        pending_members = []
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(infos) > MAX_FILES or len(set(names)) != len(names) or "item.json" not in names:
                raise IndependentItemError("Duplicate or missing package entries.")
            total = 0
            for info in infos:
                limit = MAX_MANIFEST if info.filename == "item.json" else MAX_BLOB
                if (info.flag_bits & 1 or info.file_size > limit or info.is_dir()
                        or (info.external_attr >> 16) & 0o170000 == 0o120000
                        or info.filename != "item.json" and not re.fullmatch(r"assets/[0-9a-f]{64}", info.filename)):
                    raise IndependentItemError("Unsafe or unsupported package entry.")
                total += info.file_size
            if total > MAX_TOTAL:
                raise IndependentItemError("Item package exceeds the supported size.")
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise IndependentItemError("Duplicate package metadata key.")
                    result[key] = value
                return result
            meta = json.loads(_read_member(archive, 'item.json', stop_event), object_pairs_hook=unique)
            blobs = {}
            for info in infos:
                raise_if_cancelled(stop_event)
                if info.filename != "item.json":
                    blobs[info.filename[7:]] = (_read_member(archive, info, stop_event) if cache is None
                        else _read_cached_member(archive, info, stop_event, cache, pending_members))
        if not immutable and _artifact_hash(source, stop_event) != artifact:
            raise IndependentItemError('The package changed while it was being read.')
        result = replace(_package(meta, blobs, stop_event=stop_event), artifact_digest=artifact)
        raise_if_cancelled(stop_event)
        if cache is not None:
            cache.remember_members(pending_members)
            cache.remember_package(result)
        raise_if_cancelled(stop_event)
        return result
    except (zipfile.BadZipFile, KeyError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, IndependentItemError):
            raise
        raise IndependentItemError(f"Invalid independent item package: {exc}") from exc


def write_package(package, path, *, expected_digest=None, stop_event=None, validate_source=None):
    path = Path(path).resolve()
    if path.suffix.lower() != ".cditem":
        raise IndependentItemError("Independent item packages use the .cditem extension.")
    previous = None
    if path.is_file():
        old = read_package(path, stop_event=stop_event)
        if expected_digest != old.digest or old.identity != package.identity:
            raise IndependentItemError("Select the existing package explicitly before updating it.")
        if package_metadata(old)['version'] == 2 and package_metadata(package)['version'] == 1:
            raise IndependentItemError('A v2 package requires a v2-aware editor. Refusing to discard its modules or provenance.')
        previous = old.artifact_digest
        del old  # Retain its exact artifact guard, not every decompressed resource.
    elif expected_digest is not None:
        raise IndependentItemError("The package selected for update is missing.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".cditem-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            _write_package_archive(package, handle, stop_event)
            handle.flush()
            os.fsync(handle.fileno())
        raise_if_cancelled(stop_event)
        checked = read_package(Path(temporary), stop_event=stop_event)
        if (checked.identity, checked.digest) != (package.identity, package.digest):
            raise IndependentItemError('The staged package failed final identity and content readback.')
        del checked
        if validate_source is not None:
            validate_source(stop_event)
        current = None
        if path.is_file():
            with path.open('rb') as handle:
                current = _artifact_hash(handle, stop_event)
        if current != previous:
            raise IndependentItemError("The destination changed during package export.")
        raise_if_cancelled(stop_event)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return IndependentItemExport(path, package.identity, package.digest)
