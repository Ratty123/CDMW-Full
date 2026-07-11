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

Related docs: `docs/project-map.md`.
Related tests: supporting feature tab and replacement workflow tests from
`docs/test-matrix.md`.
