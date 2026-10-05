# Tools

Owns utility workspaces that do not belong to Assets, Textures, or Research. **Utilities
> Mod Management** owns installed mods, independent item packages, Repackage, Merge,
Game updates and Recovery. The visible tab uses the existing Rust presentation bridge
over an offscreen `ModManagementTab`. Overview shows enabled/disabled installs, entries
needing review and mounted folders. Its compact action groups are Install & manage,
Package tools and Maintenance; explanations appear on hover. The Rust layout measures
translated labels at the current font size, stacks the groups when they no longer fit
side by side, and scrolls when the window is short. All management pages share these
panel, input, button and navigation styles. Form sections and inventory/preview panes
stack at narrow widths or larger text sizes; tables retain horizontal scrolling for
additional columns. Explanations stay concise, with longer guidance in hover help.
The shared game-folder selector
updates the existing archive setting. Installed mods provides a searchable inventory
with a resizable preview and Files and history inspector. All workflows are embedded
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
overlapping removal or recovery. The inventory uses a separate cancellable read worker,
so startup's item-table preparation does not delay browsing or selection. A shared
operation that could change the archives cancels an in-flight inventory read and queues
a fresh read after it finishes; stale results cannot replace the inventory.

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
still produce a visible warning. Filtering never changes the mount list or game files.
Create New Item can read the remaining data when a non-game folder is absent; missing
required game archives and present but unindexed folders still block reading. Neither
operation edits the mount list. A previously absent folder reappearing invalidates a
cached read, requiring an archive refresh.
Game-update comparisons handle both added and replaced textures while preserving
unrelated texture registrations.
The shell tracks the tab's operations, lookups and overlay preview during shutdown.

## Retrofit and Repackage

**Mod Management > Repackage** converts existing folders or ZIPs for supported managers.
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
