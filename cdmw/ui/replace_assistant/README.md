# Replace Assistant

Owns Replace Assistant UI panels, queue/review presentation, preview controls,
settings, and worker handoff for replacement package building.

Keep core replacement planning and payload logic outside this UI package. Use
`cdmw/core/replace_assistant.py`, modding modules, services, or workers for
non-presentation behavior as it is extracted.

Related docs: `docs/project-map.md`.
Related tests: supporting feature tab and replacement workflow tests from
`docs/test-matrix.md`.
