# UI

Owns PySide6 presentation code. `cdmw/ui/shell/` owns the app frame and tab
wiring; `cdmw/ui/<feature>/` packages own feature workspaces; `cdmw/ui/tools/`
owns utility tools such as Retrofit/Repackage Mods. Top-level legacy
modules such as `*_tab.py` stay compatibility wrappers while internals move.

`shell/compact/` is an optional presentation around the same registered tool
widgets and activation paths; Classic remains the default. `new_item/` owns the
guided Create New Item UI and its latest-wins preview/task controllers. Neither
package duplicates business rules, archive writers, or renderer ownership.

Keep UI shell behavior in `shell/` and feature-specific behavior in the matching
feature package. Do not put business rules, archive mutation policy, or
long-running work directly in UI modules; route those through services, domain
rules, and workers.

Related tests: UI source guards and feature-specific entries under `tests/`.
