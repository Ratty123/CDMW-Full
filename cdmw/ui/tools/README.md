# Tools

Owns utility workspaces that do not belong to Assets, Textures, or Research.
**Utilities > Mod Management** owns Merge mods, Check mods for game updates,
Installed overlays and Archive recovery, previously in Create New Item's Output.
The tab shares Create New Item's controller and services without requiring a
draft or archive snapshot. Both tools use one operation lane, preventing an
install from overlapping removal or recovery. Installed overlays loads current archive sources on
its preview worker and shows the selected item's geometry and materials. Refresh
and reopening use a new preview cache identity. Recovery and removal retain their
review, confirmation, backup and rollback steps; opening a tool is read-only.
The shell tracks the tab's operations, lookups and overlay preview during shutdown.

Retrofit/Repackage Mods lives here; old Archive Browser imports remain
compatibility wrappers.

Retrofit/Repackage scans and conversions run through its tracked request-ID
worker controller. A newer scan cancels and supersedes older results; conversion
requests stage all selected packages before transactional publication.
