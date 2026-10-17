"""Private DDS bindings for model materials already owned by an item plan."""
from hashlib import sha256
from pathlib import PurePosixPath

from cdmw.core.pac_xml_references import parse_pac_xml_references
from cdmw.core.pathc_format import PathcError, validate_dds_payload


def private_texture_path(stem, source_path):
    """A stable item-owned destination for one exact stock texture pathname."""
    source_path = source_path.replace("\\", "/").lower()
    name = sha256(source_path.encode("utf-8")).hexdigest()[:16]
    return str(PurePosixPath(source_path).with_name(f"{stem}_r{name}.dds"))


def check_owned_resource_budget(planner, size):
    """Account logical output bytes and paths even when payload memory is shared."""
    from cdmw.services.independent_item_package import MAX_BLOB, MAX_FILES, MAX_TOTAL
    from cdmw.services.new_item_planning import NewItemPlanError

    if size > MAX_BLOB:
        raise NewItemPlanError("An independent owned resource exceeds the per-file size limit.")
    if len(planner.additions) >= MAX_FILES:
        raise NewItemPlanError("The independent owned resources exceed the file-count limit.")
    if planner.owned_resource_bytes + size > MAX_TOTAL:
        raise NewItemPlanError("The independent owned resources exceed the total size limit.")


def copy_material_textures(planner, material, replacements):
    """Relocate supported DDS paths in one owned material, preserving source pins.

    Explicit imported texture outputs keep their caller's existing destinations.
    Remaining typed DDS references receive unchanged private copies. Unsupported
    DDS layouts retain their borrowed binding and all existing dependency guards.
    Nothing here owns unselected materials, sockets, physics or other resources.
    """
    from cdmw.services.independent_item_package import virtual_path

    check_owned_resource_budget(planner, len(material))
    document = parse_pac_xml_references(material, check=planner.check)
    mapping = {}
    for source, target in replacements.items():
        source = virtual_path(source.replace("\\", "/").lower())
        target = virtual_path(target.replace("\\", "/").lower())
        if source in mapping and mapping[source] != target:
            raise ValueError("Ambiguous private texture source binding.")
        mapping[source] = target
    written, skipped = [], set()
    owned_textures = {request.path.lower() for request in planner.additions if request.path.lower().endswith(".dds")}
    for reference in document.references:
        planner.check()
        if reference.tag != "ResourceReferencePath_ITexture" or not reference.path:
            continue
        source = virtual_path(reference.path.replace("\\", "/").lower())
        if not source.endswith(".dds") or source in mapping or source in skipped or source in owned_textures:
            continue
        # Missing references still refuse, including references absent from an
        # older package's source pins. No fallback supplies unverified bytes.
        entry = planner.snapshot.entry(source)
        target = planner.private_texture_copies.get(source)
        if target is None:
            target = virtual_path(private_texture_path(planner.new_stem, source))
            check_owned_resource_budget(planner, max(0, int(entry.orig_size)))
            data = planner.snapshot.payload(source)
            try:
                validate_dds_payload(data)
            except PathcError as exc:
                planner.warnings.append(f"Texture {source} retains its source binding: {exc}")
                # Avoid repeated validation and repeated warnings within this
                # material while keeping the original attribute bytes intact.
                skipped.add(source)
                continue
            planner.add(entry, target, data, f"Private template texture: {target}")
            planner.private_texture_copies[source] = target
            written.append(target)
        mapping[source] = target
    return document.rewrite_textures(mapping, check=planner.check), tuple(written)
