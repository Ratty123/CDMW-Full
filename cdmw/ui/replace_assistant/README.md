# Replace Assistant

Owns Replace Assistant UI panels, queue/review presentation, preview controls,
settings, and worker handoff for replacement package building.

Keep core replacement planning and payload logic outside this UI package. Use
`cdmw/core/replace_assistant.py`, `cdmw/core/replace_assistant_package.py`,
modding modules, services, or workers for non-presentation behavior as it is
extracted.

Auto Match rejects a local original when its resolved path is the edited file.
Unresolved items keep no inferred destination and require Choose Archive
Original. Package builds preserve the matched package/game path, then route that
same payload through every selected manager profile.

When the standalone archive backend is the displayed backend, Replace Assistant
keeps its local Original DDS filesystem index but never receives the global
archive entry list. Auto Match resolves bounded exact-path candidates first and
then bounded basename candidates through the worker. Choose Archive Original is
a paged worker query, and package builds prepare only the matched session/entry
IDs before handing local prepared files to the existing build worker. Legacy and
shadow display modes retain the list-backed compatibility path.

Related docs: `docs/project-map.md`.
Related tests: supporting feature tab and replacement workflow tests from
`docs/test-matrix.md`.
