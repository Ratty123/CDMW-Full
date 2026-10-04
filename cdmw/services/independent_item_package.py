"""Bounded .cditem export/import. Rebuild records from typed intent, never byte patches."""
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
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
_HASH = re.compile(r"[0-9a-f]{64}\Z")


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


def stock_snapshot(root, *, service=None, read_entry=None, stop_event=None, on_log=None):
    """Use the existing shipped-directory boundary, never a mounted custom table."""
    from cdmw.core.archive_format import discover_pamt_files, parse_archive_pamt
    from cdmw.services.new_item_service import NewItemService
    from cdmw.services.archive_overlay_install import OVERLAY_DIRECTORY_FIRST
    root = Path(root).resolve()
    entries = []
    for path in discover_pamt_files(root):
        raise_if_cancelled(stop_event)
        path = Path(path).resolve()
        folder = path.parent.name
        if not path.is_relative_to(root) or not folder.isascii() or not folder.isdigit():
            raise IndependentItemError("The game archive layout is unsupported for independent items.")
        if int(folder) < OVERLAY_DIRECTORY_FIRST:
            entries.extend(parse_archive_pamt(path))
    result = (service or NewItemService()).build_snapshot(entries, read_entry=read_entry, stop_event=stop_event, on_log=on_log)
    from cdmw.domain.new_item.allocation import DEFAULT_ITEM_KEY_RANGE
    if any(key in DEFAULT_ITEM_KEY_RANGE for key in result.rows):
        raise IndependentItemError("The shipped item tables contain custom items. Restore a clean game baseline before using independent packages.")
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


def _package(meta, blobs):
    if not isinstance(meta, dict) or set(meta) != {"format", "version", "identity", "title", "recipe", "dependencies", "blobs"} or meta["format"] != FORMAT or type(meta["version"]) is not int or meta["version"] != VERSION:
        raise IndependentItemError("Unsupported independent item package version or fields.")
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
    result = IndependentItemPackage(identity, meta["title"], meta["recipe"], meta["dependencies"], blobs, digest(canonical(meta)))
    unpack_recipe(result)  # Closed types, paths and every resource reference checked on import.
    return result


def unpack_recipe(package):
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
    if used != set(package.blobs):
        raise IndependentItemError("The package contains unreferenced resources.")
    return spec, primary, variants, icon


def package_bytes(package, *, stop_event=None):
    meta = {"format": FORMAT, "version": VERSION, "identity": package.identity, "title": package.title,
            "recipe": package.recipe, "dependencies": package.dependencies,
            "blobs": {key: len(data) for key, data in sorted(package.blobs.items())}}
    data = canonical(meta)
    if len(data) > MAX_MANIFEST or len(package.blobs) + 1 > MAX_FILES:
        raise IndependentItemError("Item package metadata exceeds the supported size.")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("item.json", data)
        for key, payload in sorted(package.blobs.items()):
            raise_if_cancelled(stop_event, "Item package export cancelled.")
            archive.writestr("assets/" + key, payload)
    raise_if_cancelled(stop_event, "Item package export cancelled.")
    return stream.getvalue()


def read_package(source, *, stop_event=None):
    try:
        if isinstance(source, (str, Path)):
            if Path(source).stat().st_size > MAX_TOTAL + MAX_MANIFEST:
                raise IndependentItemError("Item package exceeds the supported size.")
        elif isinstance(source, bytes):
            if len(source) > MAX_TOTAL + MAX_MANIFEST:
                raise IndependentItemError("Item package exceeds the supported size.")
            source = io.BytesIO(source)
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
            meta = json.loads(archive.read("item.json"), object_pairs_hook=unique)
            blobs = {}
            for info in infos:
                raise_if_cancelled(stop_event)
                if info.filename != "item.json":
                    blobs[info.filename[7:]] = archive.read(info)
        return _package(meta, blobs)
    except (zipfile.BadZipFile, KeyError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, IndependentItemError):
            raise
        raise IndependentItemError(f"Invalid independent item package: {exc}") from exc


def write_package(package, path, *, expected_digest=None, stop_event=None):
    path = Path(path).resolve()
    if path.suffix.lower() != ".cditem":
        raise IndependentItemError("Independent item packages use the .cditem extension.")
    if path.is_file() and path.stat().st_size > MAX_TOTAL + MAX_MANIFEST:
        raise IndependentItemError("Item package exceeds the supported size.")
    previous = path.read_bytes() if path.is_file() else None
    if previous is not None:
        old = read_package(previous)
        if expected_digest != old.digest or old.identity != package.identity:
            raise IndependentItemError("Select the existing package explicitly before updating it.")
    elif expected_digest is not None:
        raise IndependentItemError("The package selected for update is missing.")
    data = package_bytes(package, stop_event=stop_event)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".cditem-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        raise_if_cancelled(stop_event)
        if (path.read_bytes() if path.is_file() else None) != previous:
            raise IndependentItemError("The destination changed during package export.")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return IndependentItemExport(path, package.identity, package.digest)
