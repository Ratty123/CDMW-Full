# Texture Domain

Owns texture profiles, workflow rules, planner policy, output semantics,
validation, and material authority predicates.

Keep DDS/PNG inspection, external tool execution, preview rendering, workspace
creation, and UI controls outside this package. Runtime texture work belongs in
`cdmw/core/texture_pipeline/`, services, and workers.

Related docs: `docs/architecture.md`, `docs/project-map.md`.
Related tests: `tests/test_texture_domain_profiles.py` and texture entries in
`docs/test-matrix.md`.
