# Modding

Owns mesh and material replacement logic, scene import, source-part mapping,
runtime static mesh building, PAC/PAM/PAMLOD builders, material profiles, and
material payload routing.

Keep PySide UI and archive mutation confirmation outside this package. UI
packages collect user intent; services coordinate execution; archive patching
and backup policy stay behind archive services/core paths.

Related docs: `docs/architecture.md`, `docs/project-map.md`.
Related tests: mesh, static replacement, material, and package entries in
`docs/test-matrix.md`.
