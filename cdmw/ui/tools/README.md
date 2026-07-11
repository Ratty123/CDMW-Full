# Tools

Owns utility workspaces that do not belong to Assets, Textures, or Research.
Retrofit/Repackage Mods lives here; old Archive Browser imports remain
compatibility wrappers.

Retrofit/Repackage scans and conversions run through its tracked request-ID
worker controller. A newer scan cancels and supersedes older results; conversion
requests stage all selected packages before transactional publication.
