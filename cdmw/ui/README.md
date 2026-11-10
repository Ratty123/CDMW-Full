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

Preview Settings > Quality / Lighting exposes a **Lighting preset** selector,
**Shadows** and **Ambient occlusion**. **Studio (fixed lights)** is the fourth preset;
Neutral studio remains the default. Explicit session lighting (such as the New Item
dark preview) overrides the saved preference.
Both default on, persist with preview preferences, and send live display-quality updates
without rebuilding model packages. Mesh Editor has independent session switches in
Viewport, alongside its session lighting selector. These effects apply only to Textured and Game Outdoor modes. Icon mode
requests a transparent capture background while keeping self-shadows.

`preview/dotnet_host_prewarm.py` also owns one hidden spare Rust helper for the
next dialog. Archive/builder prewarming prepares its immutable placeholder on
the existing worker pool. Adoption requires an unused, ready process, matching
executable identity and current valid provenance; the child window is reparented
before ownership transfers. The dialog then owns shutdown. A spare never takes
over a real edit session, and late preparation results cannot restart it after
application shutdown. Only the waiting spare requests a retained GPU device;
ordinary hidden previews retain their existing idle release policy.

Preview and direct Mesh Editor protocol readers retain bytes until a complete
line arrives, preserving UTF-8 across pipe reads. Complete message bursts are
drained before enforcing the unfinished-buffer limit; individual lines remain
bounded in bytes, and rejected input is released. A helper losing ownership
stops the current batch. Failed editor sessions still retain terminal diagnostics
while their helper exits, but cannot accept further actions or reactivate rendering.

Related tests: UI source guards and feature-specific entries under `tests/`.
