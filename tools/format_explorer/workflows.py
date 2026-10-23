"""Application workflows presented by Format Explorer, separate from archive analysis.

This module describes existing routes. It neither reads assets nor authorizes writes.
Mesh restrictions come from the domain policy that the editor already uses.
"""

from __future__ import annotations

from dataclasses import dataclass

from cdmw.domain.mesh import authoring_capability as mesh_policy


OPERATION_LABELS = {
    "inspect": "Inspect",
    "edit": "Edit",
    "import": "Import",
    "export": "Export",
    "package": "Package",
}


READ_LABELS = {"converted": "Via Blender", "mesh": "Mesh import", "package": "Package reader"}
WRITE_LABELS = {
    "exact": "Limited edits", "refused": "Not editable",
    "working": "Edit after import; OBJ output", "import": "Import only",
    "package": "Package output",
}


@dataclass(frozen=True)
class FormatOperation:
    kind: str
    description: str


@dataclass(frozen=True)
class FormatWorkflow:
    operations: tuple[FormatOperation, ...] = ()
    prerequisites: str = ""
    limits: tuple[str, ...] = ()
    read_label: str = ""
    write_label: str = ""
    editable: bool | None = None


_ARCHIVE_SELECTION = (
    "Open Browse Archives, select a file with this extension, then use its context menu. "
    "The link opens the tool; it does not select an asset or perform an edit."
)
_ITEM_TEMPLATE = (
    "Choose a compatible template in Create New Item and review its output plan. "
    "These shared records are managed by the item workflow; there is no general-purpose table editor."
)
_WORKING_PREREQUISITES = (
    "Load a supported working mesh in Mesh Editor and choose a Free Edit output folder. "
    "An archive replacement also requires an open target mesh. The active editor must support the chosen action."
)
_WORKING_LIMIT = (
    "Imported geometry is a working mesh. Free Edit produces a new OBJ package; "
    "import does not promise a byte-preserving round trip or unrestricted game-asset replacement."
)
_PACKAGE_LIMIT = (
    "Experimental. Create New Item writes v1 packages; the reader also admits supported v2 modules "
    "and capability versions. Unknown package versions and unsupported required capabilities are refused. "
    "A readable package is not proof that every module can be installed or that the result works in game."
)
_MATERIAL_LIMIT = (
    "Preserve valid material structure and references. External text editing does not validate "
    "every material value or provide an unrestricted material rebuild."
)


def _capability_note(capability: mesh_policy.AuthoringCapability) -> str:
    return " ".join(part for part in (capability.reason, capability.detail) if part)


def _mesh_workflow(extension: str) -> FormatWorkflow:
    exact = extension.lstrip(".") in mesh_policy.AUTHORABLE_MESH_FORMATS
    if exact:
        geometry = mesh_policy.geometry_authoring_capability(extension)
        matrix = mesh_policy.capability_matrix(extension)
        restrictions = tuple(
            str(value["reason"])
            for group in ("topology_operations", "blocked_actions")
            for value in matrix[group].values()
            if not value["authorable"] and value["reason"]
        )
        lower_lod = mesh_policy.geometry_authoring_capability(extension, lod_index=1)
        limits = tuple(filter(None, (
            _capability_note(geometry) if not geometry.authorable else "",
            _capability_note(lower_lod) if not lower_lod.authorable else "",
            *restrictions,
            "Every output still passes the mesh writer's asset and operation checks.",
        )))
        operations = [
            FormatOperation("inspect", "Read supported mesh layouts and inspect the model in Mesh Editor."),
        ]
        if geometry.authorable:
            operations.append(FormatOperation(
                "edit", "Use the exact game-asset output policy for supported LOD0 edits.",
            ))
        operations.append(FormatOperation(
            "export", "Export OBJ, FBX or GLB through the available mesh export workflow.",
        ))
        return FormatWorkflow(
            operations=tuple(operations),
            prerequisites=(
                "Open a supported archive or extracted mesh. Operation availability depends on its "
                "layout, LOD, output policy and the active editor."
            ),
            limits=limits,
            write_label=WRITE_LABELS["exact" if geometry.authorable else "refused"],
            editable=geometry.authorable,
        )

    # This answers what is possible after the user supplies a destination. It
    # does not create a session or bypass the live editor's destination checks.
    output = mesh_policy.output_policy_state(
        extension, output_destination="user-selected output folder", destination_ready=True,
    )
    imports = (
        "Import FBX through the explicitly configured Blender conversion in Create New Item's Model step."
        if extension == ".fbx" else
        "Import with CDMW's mesh reader in Create New Item or a supported Mesh Editor workflow."
    )
    operations = [FormatOperation("import", imports)]
    if output.authoring_enabled:
        operations.append(FormatOperation(
            "edit", "Edit the imported working mesh using supported Free Edit operations.",
        ))
    if extension in {".obj", ".fbx", ".glb"}:
        operations.append(FormatOperation(
            "export",
            "Export this interchange format from supported meshes; the chosen exporter applies its own limits.",
        ))
    limits = [_WORKING_LIMIT, _capability_note(output.output_capability)]
    if extension in {".dae", ".gltf"}:
        limits.append(
            "Import support does not provide a same-format export route. Choose an available output format."
        )
    prerequisites = _WORKING_PREREQUISITES
    if extension == ".fbx":
        prerequisites = (
            "Configure Blender in Create New Item before importing FBX. Use the converted working mesh "
            "for editing. " + prerequisites
        )
    return FormatWorkflow(
        operations=tuple(operations),
        prerequisites=prerequisites,
        limits=tuple(filter(None, limits)),
        read_label=READ_LABELS["converted" if extension == ".fbx" else "mesh"],
        write_label=WRITE_LABELS["working" if output.authoring_enabled else "import"],
        editable=output.authoring_enabled,
    )


def workflow_for(extension: str) -> FormatWorkflow:
    if extension.lstrip(".") in (
        mesh_policy.AUTHORABLE_MESH_FORMATS | mesh_policy.FREE_EDIT_WORKING_MESH_FORMATS
    ):
        return _mesh_workflow(extension)
    if extension in {".paseq", ".paseqc", ".pastage"}:
        return FormatWorkflow(
            operations=(
                FormatOperation("inspect", "Inspect recovered sequence strings and references."),
                FormatOperation("edit", "Edit validated fixed-size strings with Edit Structured Data Safely... and save an edited copy."),
            ),
            prerequisites=_ARCHIVE_SELECTION,
            limits=("Track/event authoring and variable-size string edits are not supported.",),
            editable=True,
        )
    if extension == ".pabgh":
        return FormatWorkflow(
            operations=(FormatOperation(
                "edit", "Change validated row offsets with Edit Structured Data Safely... and save an edited copy.",
            ),),
            prerequisites=_ARCHIVE_SELECTION,
            limits=("Only supported 5- and 8-byte rows are rewritten; composite-key tables remain read-only.",),
            editable=True,
        )
    if extension == ".paloc":
        return FormatWorkflow(
            operations=(
                FormatOperation("import", "Open a PALOC language table in Edit Translations."),
                FormatOperation("edit", "Edit translation records and write a PALOC table while preserving its supported container."),
            ),
            prerequisites="Extract the language table and open it in Utilities > Edit Translations.",
            limits=("Flat tables and version-0 LZ4 containers are supported. Unknown container versions are refused.",),
        )
    if extension in {".pae", ".paem"}:
        return FormatWorkflow(
            operations=(FormatOperation(
                "edit", "Choose and tune a cloned effect or emitter in Create New Item's Effects workspace.",
            ),),
            prerequisites=(
                "Choose an item template, then an effect in the Effect Library. "
                "Review the generated item plan before writing its output."
            ),
            limits=(
                "Only decoded effect values and supported tuning controls are edited; strings and collections are not freely resized.",
                "The effect preview is approximate and does not prove the final in-game appearance.",
            ),
        )
    if extension in {".pathc", ".pappt", ".pabgb"}:
        description = {
            ".pathc": "Register new item textures, reusing a compatible DDS header or adding a validated new header.",
            ".pappt": "Clone and insert the part-prefab records required by a new item.",
            ".pabgb": "Clone and update the supported item-table records required by a new item.",
        }[extension]
        return FormatWorkflow(
            operations=(FormatOperation("edit", description),),
            prerequisites=_ITEM_TEMPLATE,
            limits=("Only the records and layouts admitted by the owning item workflow can be changed.",),
        )
    if extension in {".pac_xml", ".pami"}:
        return FormatWorkflow(
            operations=(
                FormatOperation("inspect", "Inspect the extracted material text."),
                FormatOperation("edit", "Edit an extracted copy with an external text editor."),
            ),
            prerequisites="Extract a copy before editing and use the normal reviewed repack workflow for installation.",
            limits=(_MATERIAL_LIMIT,),
        )
    if extension == ".cditem":
        return FormatWorkflow(
            operations=(
                FormatOperation("inspect", "Read package identity, dependencies and supported typed modules."),
                FormatOperation("package", "Create or update an independent item package from Create New Item's Output step."),
                FormatOperation("import", "Add item packages through Mod Management > Mods; Independent items provides advanced managed installation."),
            ),
            prerequisites=(
                "Choose Independent item package (Experimental) in Create New Item, or open Mod Management "
                "and use Add item packages in Mods. Installation and launch require a configured game folder "
                "and a successful compatibility review."
            ),
            limits=(_PACKAGE_LIMIT,),
            read_label=READ_LABELS["package"],
            write_label=WRITE_LABELS["package"],
            # Package creation/import alone is not a general editing route.
            editable=False,
        )
    return FormatWorkflow()
