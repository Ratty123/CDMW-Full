# Tools

Owns utility workspaces that do not belong to Assets, Textures, or Research. **Utilities
> Mod Management** owns Merge mods, Check mods for game updates, Installed overlays and
Archive recovery, previously in Create New Item's Output. The visible tab uses the
existing Rust presentation bridge over an offscreen `ModManagementTab`. Its default page
loads a searchable overlay inventory with a resizable preview and Files and history
inspector. Merge, comparison/export and recovery are embedded pages; only pickers and
mutation confirmations open dialogs.

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
The shell tracks the tab's operations, lookups and overlay preview during shutdown.

## Retrofit and Repackage

Retrofit/Repackage Mods lives here; old Archive Browser imports remain
compatibility wrappers.

Retrofit/Repackage scans and conversions run through its tracked request-ID
worker controller. A newer scan cancels and supersedes older results; conversion
requests stage all selected packages before transactional publication.
