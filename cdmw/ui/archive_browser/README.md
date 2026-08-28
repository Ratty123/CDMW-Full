# Archive Browser

Owns archive listing, filtering, preview coordination, item icons, and archive
browser actions. Keep virtual model behavior in `model.py`; keep UI assembly and
feature coordination in focused modules as they are extracted from the shell.

The resident v2 catalogue is the listing authority. Preview requests are
request-correlated and latest-wins: a stale selection may be superseded but may
not clear or replace the current scene. Archive Browser publishes the path,
basename, extension, dependency, and native package indexes reused by Model
Library, Mesh Editor, and Create New Item.

Browsing, preview, scan, extraction, and package preparation are read-only.
Actions that can write route through service-owned confirmation and
`ArchiveMutationService`; this UI package never patches PAMT/PAZ directly.
