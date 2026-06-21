# UI

Owns PySide6 presentation code. `cdmw/ui/shell/` owns the app frame and tab
wiring; `cdmw/ui/<feature>/` packages own feature workspaces; `cdmw/ui/tools/`
owns utility tools such as Retrofit/Repackage Mods. Top-level legacy
modules such as `*_tab.py` stay compatibility wrappers while internals move.

Keep UI shell behavior in `shell/` and feature-specific behavior in the matching
feature package. Do not put business rules, archive mutation policy, or
long-running work directly in UI modules; route those through services, domain
rules, and workers.

Related docs: `docs/architecture.md`, `docs/project-map.md`.
Related tests: UI source guards and feature-specific entries in
`docs/test-matrix.md`.
