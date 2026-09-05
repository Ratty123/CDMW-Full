# UI

Owns PySide6 presentation code. `cdmw/ui/shell/` owns the app frame and tab
wiring; `cdmw/ui/<feature>/` packages own feature workspaces; `cdmw/ui/tools/`
owns utility tools such as Retrofit/Repackage Mods. Top-level legacy
modules such as `*_tab.py` stay compatibility wrappers while internals move.

`shell/compact/` is the first-run presentation around the same registered tool
widgets and activation paths; an existing Compact or Classic choice remains
authoritative. `new_item/` owns the
guided Create New Item UI and its latest-wins preview/task controllers. Neither
package duplicates business rules, archive writers, or renderer ownership.

Keep UI shell behavior in `shell/` and feature-specific behavior in the matching
feature package. Do not put business rules, archive mutation policy, or
long-running work directly in UI modules; route those through services, domain
rules, and workers.

The shared Rust preview host keeps complete presentation state for process
restarts, but sends only the changed fields to a running renderer. Display
changes therefore preserve the user's live camera and do not request a geometry
refresh. Shared Mesh Editor hosts continue to use their tab's presentation owner.

Related tests: UI source guards and feature-specific entries under `tests/`.
