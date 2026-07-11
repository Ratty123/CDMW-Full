# Item Icons

Owns Icon Creator UI, icon library browsing, target matching, generation
controls, and loose-mod icon patch orchestration.

Library scans/index writes and source/final preview preparation run in owned,
cancellable workers. Preview requests are latest-wins; metadata saves update the
loaded record and index without triggering a library rescan.
Immutable records/specifications and background/source-selection policy live in
`cdmw/domain/library/item_icons.py`; I/O is coordinated by `ItemIconService`.
Source imports, generated-icon registration, and deletes share the serialized
index worker; successful mutations update only the affected loaded row, and
copy/index publication is atomic.
Generated exports and loose-mod patches use the same owned lifecycle. Package
copies are staged, cancellable, and atomically published without partial output.
