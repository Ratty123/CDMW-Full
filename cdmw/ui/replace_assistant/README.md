# Texture Replacer

Owns Texture Replacer UI panels, queue/review presentation, preview controls,
settings, and worker handoff for replacement package building.

The internal package name remains `replace_assistant` for compatibility.

In the unified Textures workspace this is the **Replace** page. File-only imports
use the import worker without creating editor sessions. The shared texture job
owns source identity, inclusion, and document removal; queue rows retain stable
asset keys across edited-image preparation. Open Folder/Reload Folder replace the
job only after a successful scan, while Add Files appends. Import cancellation and
shutdown invalidate queued results before worker teardown. The standalone tab
retains its existing Add Folder behavior.

Keep core replacement planning and payload logic outside this UI package. Use
`cdmw/core/replace_assistant.py`, `cdmw/core/replace_assistant_package.py`,
modding modules, services, or workers for non-presentation behavior as it is
extracted.

Auto Match rejects a local original when its resolved path is the edited file.
Unresolved items keep no inferred destination and require Choose Archive
Original. Package builds preserve the matched package/game path, then route that
same payload through every selected manager profile.

When the standalone archive backend is the displayed backend, Texture Replacer
keeps its local Original DDS filesystem index but never receives the global
archive entry list. Auto Match resolves bounded exact-path candidates first and
then bounded basename candidates through the worker. Choose Archive Original is
a paged worker query, and package builds prepare only the matched session/entry
IDs before handing local prepared files to the existing build worker. Legacy and
shadow display modes retain the list-backed compatibility path.

`tests/test_texture_replacement_workspace.py` exercises the shared caller,
500-file import/matching/removal, cancellation and shutdown, and native DDS
package/rebuild output with owned fixtures. Native cases use the existing
DirectXTex helper and skip explicitly when it is unavailable. Build progress is
delivered through a queued slot on the tab's GUI thread.
