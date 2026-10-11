# Tools

Owns utility workspaces that do not belong to Assets, Textures, or Research. **Utilities
> Mod Management** opens one **Mods** list for item packages, CDMW installs and
externally managed archive folders. Type, Loads with and Status explain each row.
Add supported packages or folders, choose **Apply changes**, then **Launch game**.
New selections use the experimental virtual loader; existing installs retain their
loading method and identities. Installed-only games launch without virtual setup.
CDMW-owned installs can be enabled, disabled or removed from the list using the
existing reviewed backup workflow. External folders remain managed by their original
manager. Missing references and removed identity reservations are maintenance records,
not active mods, and remain available in **Health and recovery** and **Item identities**.

Select a CDMW install and choose **Details** to open its preview and file history;
**Back to mod list** retains the list's search and selection. One tab row opens **Mods**,
**Prepare packages**, **Item identities**, **Shared files**, and **Health and recovery**.

- **Health and recovery** combines archive status, missing-reference cleanup and
  expandable repair actions. Rebuild/reapply repairs saved installs in place.
- **Prepare packages** offers **Convert**, **Combine**, and **Update**. Each task retains
  its inputs when switching. Conversion lists show the package, kind, manager and status;
  **Package details** opens the selected package's additional settings and output plan.
  These operations write separate output packages; they do not apply them to the game.
- **Item identities** inspects installed/reserved IDs. **Identity profile** opens its
  import/export tools for transferring profiles with saves.
  The explicit **Install into game archives** action retains the older physical route.
- **Shared files** scans installed data or a mod folder, reviews conflicts, and offers
  the existing rebuild and export actions.

Compatibility and unsupported-input
checks remain mandatory; the combined list does not expand format or in-game support.
The visible workspace uses the existing Rust presentation bridge over an offscreen
`ModManagementTab`. The Rust layout measures
translated labels at the current font size, stacks the groups when they no longer fit
side by side, and scrolls when the window is short. All management pages share these
panel, input, button and navigation styles. Lists and review panes fill the available
height and scroll locally; profile, recovery and package details start collapsed.
At narrow widths, package details becomes a closable full-width panel. Form sections and inventory/preview panes
stack at narrow widths or larger text sizes; tables retain horizontal scrolling for
additional columns. Explanations stay concise, with longer guidance in hover help.
The shared game-folder selector
updates the existing archive setting. Installed mod details use the existing preview
and Files and history inspector without a second mod list. All workflows are embedded
pages; pickers and mutation confirmations still use dialogs.

Activity is collapsed by default and includes management operations and its own preview,
rather than unrelated Create New Item work. The loading page remains visible until the
Rust interface has rendered its first state. A newly loaded inventory has no selected
row; choosing an overlay starts its preview. Refresh preserves an existing selection,
and filtering clears a selection when its row is hidden instead of selecting and loading
another model.

## Shared controllers and read-only preparation

The workspace shares Create New Item's controller and services without requiring a draft
or archive snapshot. Both tools use one operation lane, preventing an install from
overlapping removal or recovery. Inventory and runtime status use separate cancellable
read workers, so startup's item-table preparation and runtime checks do not restart or
delay inventory browsing. Repeated status requests for the same root share the in-flight
read. A shared operation that could change the installation cancels these reads and
queues fresh reads after it finishes; stale results cannot replace current state.
Cancelled or failed status reads leave browsing and Refresh available, while Apply,
Launch and other state-changing actions await a current completed status check.
Runtime checks wait for a live session to end. Background rechecks preserve operation
results and session progress; Refresh can show the newly checked runtime status.

The Files and history inspector verifies the complete journal digest and validates its
metadata and member bounds without decompressing every stored payload. Composition,
removal and recovery retain the full payload verification path.

Installed previews resolve the selected item from current mounted sources, reading only
the needed model metadata instead of rebuilding the authoring catalogue. Current
snapshots and the published archive catalogue supply shared, lazy path lookups;
selecting an item does not copy the full archive index. Skeleton and descriptor searches
filter indexed filenames before decoding candidate records, including when obsolete
archive groups must be excluded. Loading and errors appear beside and within the
viewport; Reload preview, refresh and reopening use new request identities. The
renderer's acknowledgement remains separate from package creation.

## Game updates and overlay health

Build comparison and physical overlay health are shown separately. Disable/enable
recomposes owned changes while retaining the install ID and journal; removal retires
that logical install. Dependency and identity conflicts block incompatible changes.
Rebuild / reapply reviews saved changes against the current mounted underlay,
preserves independent game/external-mod records and texture registrations, and
creates versioned journals while retaining the previous inventory and journals.
Changed owned bytes and conflicting item IDs require review, not forced replacement.
All mutations retain confirmation, verified backup, stale-input checks and rollback;
opening, filtering, inspecting and previewing the workspace are read-only.

Other mounted archive folders are informational. This does not make DMM accept an
installation it considers non-vanilla, or establish simultaneous manager compatibility.
Overview shows archive folders with an existing index by default. **Show missing
references** reveals mod entries left in the mount list whose archive index is absent;
these are labelled stale references, with unknown ownership unless CDMW tracks them.
The count remains visible while those entries are hidden. Required missing game archives
still produce a visible warning. **Clean missing references...** reviews the affected
mod entries and game folder, then removes the confirmed stale references from
`meta/0.papgt` after creating a verified backup. Cleanup preserves every game entry,
existing mod index, folder and saved item identity. It requires the game to be closed
and rechecks the list and absent indexes after backup; changed inputs require a new
review. A failed write restores the backup, which remains available through the normal
archive-backup recovery workflow. Filtering never changes the mount list or game files.
Create New Item can read the remaining data when a non-game folder is absent; missing
required game archives and present but unindexed folders still block reading. Neither
read operation edits the mount list. A previously absent folder reappearing invalidates a
cached read, requiring an archive refresh.
Game-update comparisons handle both added and replaced textures while preserving
unrelated texture registrations.
The shell tracks the tab's operations, lookups and overlay preview during shutdown.

## Retrofit and Repackage

**Mod Management > Prepare packages > Convert** converts existing folders or ZIPs for supported managers.
It is constructed on first use and keeps its selection, output settings and inline
results when switching pages. Existing Repackage menu actions and saved navigation
open this page. Old Archive Browser imports remain compatibility wrappers.

Retrofit/Repackage scans and conversions run through its tracked request-ID
worker controller. A newer scan cancels and supersedes older results; conversion
requests stage all selected packages before transactional publication.
Cancel retains ownership until the worker stops; another conversion cannot start
while a cancelled writer is draining. The shared Activity drawer records its progress.
Available filenames are checked against both the folder and its complete name
with `.zip` appended. Filename selection also honours cancellation.
