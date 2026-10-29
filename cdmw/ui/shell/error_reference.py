"""Shared, searchable Help/Wiki guide to source-owned diagnostic codes."""
from __future__ import annotations

from html import escape
from pathlib import PurePosixPath

from cdmw.ui.shell.error_reference_data import ERROR_REFERENCE


ERROR_REFERENCE_INTRO = """
<p>Search for the exact code from the message, Live Log or diagnostic report. Codes are case-sensitive. The same code can have different details; retain the complete message and the action that triggered it.</p>
<p>This library covers CDMW's named errors, validation findings and diagnostic code families in the documented source build. Some registered codes are reserved and may not appear in every release. It does not assign CDMW meanings to arbitrary Windows errors, process exit numbers or another mod manager's errors.</p>
<p>Diagnostic text is quoted verbatim for search, including English messages. Braces mark values filled in at runtime, or a code family. The surrounding guidance is translated. Source links identify the component that owns the check; the installed build may differ from the source currently online.</p>
<p>Read the severity in the actual report: error, fatal and blocker usually stop the affected operation; warning calls for review; info and successful capture states are not failures. A stale result is normally discarded to protect newer work. A successful check does not prove appearance, gameplay or save compatibility.</p>
<p>Before retrying a write, inspect the destination and recovery report. Keep the original input and backups. Do not bypass a safety refusal, delete recovery files or repeatedly reinstall mods to clear a code. If the cause remains unclear, use Report a Problem with the code, full detail, CDMW version, selected manager and reproduction steps.</p>
"""

ERROR_REFERENCE_FALLBACK = "The accompanying detail identifies the failing value or dependency. Follow the recovery guidance for this section."

ERROR_REFERENCE_GROUPS = {
    "archive": ("Archive operations", """<p>These codes come from the archive worker, its connection to CDMW, or catalogue recovery. The affected read, query or export stops; an error alone does not mean the archive is corrupt. Check the reported path and stage. Close competing file operations, check access and free space, then retry. After a game or mod update, rescan current sources. For missing or incompatible helpers, use a complete matching CDMW distribution. Repeated crashes, protocol errors or timeouts need the copied error report.</p>"""),
    "mesh_runtime": ("Mesh Editor runtime", """<p>These stable codes identify material delivery, view changes, edit sessions, writeback and package publication. For missing textures, resolve the imported dependencies. For a renderer failure, preserve a finished draft and reopen the editor. Wait for pending edits; undo or return to the last accepted mesh after a refused edit. Inspect output before retrying a failed build. Stale-generation codes normally discard an obsolete response and need no action unless the current operation is also stuck.</p>"""),
    "topology": ("Topology and provenance", """<p>Exact rebuild needs a proven relationship between edited geometry and the original mesh. These blockers refuse output when that relationship, supported layout or byte-preservation check fails. Undo the unsupported edit or return to the original editable package; use Free Edit for an external authoring package when exact game output is unavailable. Do not invent vertex identities or remove provenance checks. A PAC section is limited to 65,535 vertices and supported skin rows to six positive influences.</p>"""),
    "mesh_validation": ("Mesh validation and import", """<p>These findings come from mesh parsing, import review, operation validation and export checks. A blocker prevents the affected rebuild; warnings and differences need review. Correct the named part, face, vertex, material or sidecar, then run validation again. Keep matching originals and identity data. Restore removed sidecars or use a supported edit instead of forcing an incompatible replacement. If valid unchanged input also fails, include that fact in the report.</p>"""),
    "panels": ("Mesh summaries and recovery", """<p>These codes mean a panel cannot provide a current summary or validation result. The panel must not present an old Python snapshot as the current native mesh. Wait for an active edit to finish, select the mesh again and refresh the report. If it persists, reopen the last accepted draft and report the failure. A missing summary is not a successful validation.</p>"""),
    "new_item": ("Create New Item validation", """<p>These codes come from the item specification and authoring rules. The named field or step identifies what to fix; errors block planning or output, while warnings describe experimental or unusual choices. Correct ranges, identifiers and required names, load the relevant item references, choose compatible records and apply staged placement or effects before rebuilding the plan. A missing reference can mean the selected template or game data changed. Do not substitute guessed raw IDs.</p>"""),
    "dds": ("DDS texture inspection", """<p>These findings check the DDS header, format, dimensions, mipmaps and payload before texture use or export. Fatal findings refuse unsafe data. Re-export from the original texture with a supported format and complete mip chain; check truncated files and free disk space. Preserve technical maps. Informational findings such as a valid payload or a required PATHC registration describe the format and are not corruption reports.</p>"""),
    "materials": ("Materials and texture bindings", """<p>These diagnostics come from imported-material inspection, preview synthesis and package material checks. Missing files, wrong texture roles, unsupported shader features or changed sidecars can cause them. Reconnect the correct source textures and inspect alpha, colour space, normal maps and packed channels. Informational synthesis or fallback messages describe preview decisions, not proof of a broken game mod. Review the affected material and exported dependencies; do not treat a successful preview as game compatibility.</p>"""),
    "independent": ("Independent items and save evidence", """<p>These are isolation and evidence diagnostics for experimental independent items. They describe shared files, dependencies or changed and incomplete session evidence; they do not establish save safety. Restore a consistent package selection and matching receipt, keep verified backups and use the documented recovery flow. Do not edit a receipt to conceal a mismatch or remove an item from a save based only on an informational code.</p>"""),
    "capture": ("Capture and comparison diagnostics", """<p>These identifiers come from capture and comparison tools. Some report successful actions; others mean a window, screenshot or visual comparison is unavailable or differs from its reference. Check the target window, focus, capture permissions and matching reference conditions. Colour and brightness differences are review hints, not automatic fixes or proof of game accuracy. Preserve the original image and diagnostic detail.</p>"""),
}

# Code-specific explanations supplement exact source messages. Repeated action
# advice belongs to the group above, so it cannot drift between codes/locales.
CODE_GUIDANCE = {
    "MAT_IMPORT_MANIFEST_MISSING": "Imported texture metadata is missing. Resolve or reimport the textures with their manifest.",
    "MAT_COMPILE_FAILED": "Material compilation failed. Inspect the compiler detail and retry the affected material.",
    "MAT_PUBLICATION_STALE": "A newer material result replaced this one; the obsolete result is ignored.",
    "MAT_PUBLICATION_SEND_FAILED": "The material update could not reach the renderer. Reopen the editor and retry.",
    "MAT_ROLE_ACK_TIMEOUT": "The renderer did not confirm the material update in time. Retry that material; report repeated timeouts.",
    "MAT_ROLE_UPDATE_REJECTED": "The renderer refused a material update. Check its rejection detail before retrying.",
    "MAT_REQUIRED_TEXTURE_MISSING": "A required texture is unavailable. Restore its file or resolve the dependency again.",
    "MAT_NO_TEXTURE_RESOURCES": "No usable texture resources were resolved. Check the import and texture paths.",
    "VIEW_MODE_STALE_UPDATE": "A view-mode response belongs to an older state and is ignored.",
    "VIEW_MODE_SEND_FAILED": "The view-mode request could not reach the renderer. Reopen the editor.",
    "EDIT_REQUEST_STALE": "The edit response belongs to an older request and cannot change the current mesh.",
    "EDIT_SELECTION_GENERATION_MISMATCH": "The selection belongs to another mesh generation. Select the intended geometry again.",
    "EDIT_FINISH_PENDING_COMMANDS": "Finish is waiting for outstanding edit commands. Let them complete before finishing.",
    "EDIT_SESSION_RECOVERY_REQUIRED": "The edit session cannot safely continue. Return to the last accepted mesh or saved draft.",
    "WRITEBACK_EXACT_WRITER_REQUIRED": "The exact output writer required by this edit is unavailable. Use a supported output route; do not force writeback.",
    "WRITEBACK_TOPOLOGY_UNSUPPORTED": "The topology change cannot be written safely through this output route. Undo it or use Free Edit.",
    "WRITEBACK_PROVENANCE_MISSING": "Writeback cannot prove the edited geometry's origin. Return to the accepted mesh and matching editable package.",
    "WRITEBACK_OUTPUT_SIGNATURE_MISMATCH": "Rebuilt output does not match the expected format signature. Stop and report the failed output check.",
    "PACKAGE_RESOURCE_REFERENCE_MISSING": "A package references a resource that is not present. Restore the dependency before rebuilding.",
    "PACKAGE_ATOMIC_COMMIT_FAILED": "The staged package could not be published. Inspect the destination, permissions and full error before retrying.",
    "RENDERER_PROCESS_UNAVAILABLE": "The renderer is not running or cannot be reached. Preserve accepted work and reopen the editor.",
    "RENDERER_GENERATION_RETIRED": "The response came from a retired renderer instance and is ignored.",
    "TOPOLOGY_PROVENANCE_REQUIRED": "The edit has no usable original-geometry provenance.",
    "TOPOLOGY_CONTRACT_UNSUPPORTED": "The topology contract version or structure is unsupported.",
    "TOPOLOGY_VERTEX_ORIGIN_INVALID": "An output vertex has invalid source indices or blend weights.",
    "TOPOLOGY_FACE_ORIGIN_INVALID": "An output face has no valid original-face mapping.",
    "TOPOLOGY_OPERATION_NOT_REBUILDABLE": "This topology operation is outside the exact writer's supported set.",
    "TOPOLOGY_SKIN_INFLUENCE_CAPACITY_EXCEEDED": "A derived vertex needs more skin influences than the supported row can store.",
    "TOPOLOGY_PROTECTED_BYTES_DIVERGE": "Bytes that the exact writer must preserve changed unexpectedly.",
    "TOPOLOGY_BOUNDS_EXCEED_SOURCE": "The rebuilt geometry exceeds the source layout's supported bounds.",
    "TOPOLOGY_PAC_INDEX_LIMIT_EXCEEDED": "The section exceeds the PAC vertex/index capacity.",
    "TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED": "The edit would leave a submesh empty, which this rebuild path cannot write.",
    "TOPOLOGY_REVISION_DISCONTINUOUS": "Chained topology edits do not form one continuous revision history.",
    "worker_missing": "The archive executable or a required library is missing. Restore a complete matching CDMW installation.",
    "backend_incompatible": "The archive helper or library cannot run with this build or architecture. Use matching components.",
    "source_missing": "A source file or directory no longer exists. Check the configured path and rescan.",
    "permission_denied": "The operating system denied file access. Check folder permissions and file protection.",
    "file_sharing": "Another process holds a conflicting file lock. Close the competing operation and retry.",
    "operation_timeout": "The backend operation exceeded its time limit. Inspect the last stage and retry once the cause is addressed.",
    "invalid_archive": "The native reader rejected the archive format. Check that index and data files belong together; this code alone does not prove corruption.",
    "unsupported_operation": "The backend does not support the requested operation or input. Use a supported route.",
    "invalid_data": "The worker encountered data that violates the expected structure. Keep the input and include the detail in a report.",
    "worker_failure": "An unclassified worker exception occurred. The full exception detail is needed to diagnose it.",
    "protocol_failure": "Communication with the archive worker was invalid or incomplete. Restart with matching components and report repeated failures.",
    "startup_timeout": "The archive helper did not become ready within the startup limit. Check missing files, security blocking and the diagnostic tail.",
    "dispatch_failed": "CDMW could not dispatch the archive request. Inspect the accompanying exception and retry after restoring the connection.",
    "item_names_unavailable": "The item-name catalogue could not be prepared. Check the reported source or indexing warning and rescan.",
    "unknown_error": "The failing component supplied no recognized code. Preserve the complete message and diagnostic report.",
}


def build_error_reference_section() -> dict[str, str]:
    parts = [ERROR_REFERENCE_INTRO]
    for group, (title, guide) in ERROR_REFERENCE_GROUPS.items():
        parts.append(f'<h4 id="errors-{group}">{escape(title)}</h4>{guide}')
        for row in ERROR_REFERENCE:
            if row["group"] != group:
                continue
            detail = []
            if row["code"] in CODE_GUIDANCE:
                detail.append(escape(CODE_GUIDANCE[row["code"]]))
            detail.extend(f'<code translate="no">{escape(message)}</code>' for message in row["messages"])
            if not detail:
                detail.append(ERROR_REFERENCE_FALLBACK)
            sources = ', '.join(f'<a href="https://github.com/Ratty123/CDMW-Full/blob/main/{path}"><code translate="no">{escape(PurePosixPath(path).name)}</code></a>' for path in row["sources"])
            parts.append(f'<p><b><code translate="no">{escape(row["code"])}</code></b></p>')
            parts.append('<ul>' + ''.join(f'<li>{message}</li>' for message in detail) + '</ul>')
            parts.append(f'<p><b>Source</b>: {sources}</p>')
    return {
        "id": "error_code_library",
        "title": "Error Code Library",
        "category": "Reference",
        "summary": "Find a diagnostic code, its source, likely causes and recovery steps.",
        "keywords": "error code library diagnostic warning fatal blocker recovery reason troubleshooting exception",
        "html": ''.join(parts),
    }
