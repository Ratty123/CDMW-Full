"""Build profile companions from immutable intent, without touching archives."""

from dataclasses import replace
import hashlib
import json

from cdmw.domain.mesh.replacement import ReplacementFile
from cdmw.modding.pbd_profile_edit import ProfileXml, clone_catalogue_profiles, edit_profile_values
from cdmw.services.mesh_physics_profiles import _profile_path


CATALOGUE_PATH = "character/descriptors/pbd/pbdconfig.xml"


def build_physics_profile_files(state, original, companion_files):
    if sum(len(part.physics_profiles) for part in state.parts) > 4096:
        raise ValueError("Invalid physics profile settings.")
    groups = {}
    for part in state.parts:
        variants = set()
        for rule in part.physics_profiles:
            if rule.variant in variants:
                raise ValueError("Physics profile assignment is ambiguous or does not match the PAC.")
            variants.add(rule.variant)
            key = json.dumps(rule.to_dict(), sort_keys=True, separators=(",", ":"))
            if key not in groups:
                groups[key] = (rule, [])
            groups[key][1].append(original.submeshes[part.target_index].name)
    if len(groups) > 256:
        raise ValueError("Invalid physics profile settings.")
    if not groups:
        return tuple(companion_files)
    if original.format.casefold() != "pac":
        raise ValueError("Physics profiles require their source sidecar and catalogue.")
    sidecar_path = state.target_path.replace("\\", "/").casefold().replace("/model/", "/modelproperty/", 1) + "_xml"
    dependencies = {}
    for file in state.dependencies:
        key = file.path.casefold()
        if key in dependencies and dependencies[key] != file:
            raise ValueError("Physics profile edit source is missing or has changed.")
        dependencies[key] = file
    if sidecar_path.casefold() not in dependencies or CATALOGUE_PATH not in dependencies:
        raise ValueError("Physics profiles require their source sidecar and catalogue.")
    files = {file.path.casefold(): file for file in companion_files}
    if len(files) != len(companion_files):
        raise ValueError("Physics profile edit source is missing or has changed.")
    baseline_sidecar, baseline_catalogue = dependencies[sidecar_path.casefold()], dependencies[CATALOGUE_PATH]
    sidecar = files.get(sidecar_path.casefold(), baseline_sidecar)
    catalogue = files.get(CATALOGUE_PATH, baseline_catalogue)
    base_document = ProfileXml(baseline_sidecar.data)
    document = ProfileXml(sidecar.data)
    catalogue_document = ProfileXml(baseline_catalogue.data)
    total = len(sidecar.data) + len(catalogue.data)
    edits, clones, touched = [], [], set()
    for key, (rule, names) in sorted(groups.items()):
        source = dependencies.get(rule.source_path.casefold())
        if source is None or hashlib.sha256(source.data).hexdigest() != rule.source_sha256:
            raise ValueError("Physics profile edit source is missing or has changed.")
        entries = [node for node in catalogue_document.nodes
                   if node.attributes.get("Name", "").casefold() == rule.source_profile.casefold()
                   and "Filename" in node.attributes]
        if len(entries) != 1 or _profile_path(entries[0].attributes["Filename"]).casefold() != rule.source_path.casefold():
            raise ValueError("Physics profile edit source is missing or has changed.")
        # Validate baseline and composed material sidecars independently. The
        # required owner group cannot disappear through material replacement.
        base_document.assignment(rule.variant, names)
        owners = document.assignment(rule.variant, names)
        digest = hashlib.sha256((state.target_path.casefold() + "\n" + key).encode()).hexdigest()[:24]
        symbol = "CDMW_" + digest
        filename = "material/cdmw/" + symbol.casefold() + ".xml"
        path = "character/descriptors/pbd/" + filename
        if path in dependencies or path in files:
            raise ValueError("Generated physics profile name or path already exists.")
        for owner in owners:
            if owner.start in touched:
                raise ValueError("Select every part sharing this physics profile assignment.")
            touched.add(owner.start)
            edits.append(document.attribute_edit(owner, "_pbdSimulationMaterialName", symbol))
        payload = edit_profile_values(source.data, rule.values)
        total += len(payload)
        if total > 16 * 1024 * 1024:
            raise ValueError("Physics profile edits exceed the supported size limit.")
        files[path] = ReplacementFile(path, payload)
        clones.append((rule.source_profile, entries[0].attributes["Filename"].replace("\\", "/"), symbol, filename))
    files[sidecar.path.casefold()] = replace(sidecar, data=document.apply(edits))
    files[catalogue.path.casefold()] = replace(catalogue, data=clone_catalogue_profiles(catalogue.data, clones))
    return tuple(files[key] for key in sorted(files))
