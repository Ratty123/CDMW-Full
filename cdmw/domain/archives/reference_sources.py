"""Which archive formats store paths to which kinds of file.

Find references used to read every registered container for every target, about
1.2 million files for a sound. This table says which formats actually name each
kind of target, so a search reads those and nothing else.

Measured on game 1.0.0.3446 (2026-10-31): all 1,133,077 files of every
reference-container format (shader bytecode excluded) were searched for path
tokens, ASCII and UTF-16LE, ending in a reverse-searchable extension. A format is
listed when at least 2 of its files and at least 0.05% of them name the target
kind, or when more than half of a tiny format does. Rarer hits in the large
binary formats were checked by hand and are random bytes (`eU.WEm`, `dDG.dDS`,
`p.avi`). Each target lists its formats in two reading groups: those where at
least 10% of files name it, then the rest.

Sounds are the exception. No file stores a `.wem` path: banks name sounds by
numeric media ID, and named voice lines are picked by name at run time. Banks
are named only by `sound/soundconfig.xml` (`init.bnk`).
"""

from __future__ import annotations

REFERENCE_SOURCES_BY_TARGET: dict[str, tuple[tuple[str, ...], ...]] = {
    ".bnk": ((".xml",),),
    ".dds": (
        (".pasg", ".mi", ".pac_xml", ".pam", ".paem", ".pamlod", ".pami", ".pae", ".parg", ".material", ".xml",
         ".palevel", ".pat", ".technique", ".paseq"),
        (".css", ".staticinfobody", ".prefab"),
    ),
    ".jpg": ((".pat",),),
    ".m4v": ((".pat",),),
    ".motionblending": ((".paac",), (".xml",)),
    ".mp4": ((".staticinfobody",),),
    ".paa": (
        (".motionblending", ".paac", ".txt", ".paseqc", ".paseq"),
        (".binarygimmick", ".staticinfobody", ".xml", ".meshinfo"),
    ),
    ".paac": ((".motionblending",), (".paseq", ".paseqc")),
    ".pab": (
        (".pappt", ".pma", ".pacpmt", ".motionblending", ".prefabdata_xml", ".paa"),
        (".staticinfobody", ".prefab", ".xml"),
    ),
    ".pac": (
        (".paasmt",),
        (".palevel", ".prefab", ".paseq", ".pac_xml", ".motionblending", ".paa", ".xml", ".pae"),
    ),
    ".pam": (
        (".pami", ".pae", ".paem", ".parg"),
        (".palevel", ".xml", ".paseq", ".prefab", ".pamlod"),
    ),
    ".png": ((".pat",),),
    ".prefab": (
        (".palevel", ".paseq", ".staticinfomisc", ".prefab"),
        (".paac", ".staticinfobody", ".paschedule", ".binarygimmick"),
    ),
    ".tga": ((".pat",), (".pamlod", ".pami", ".pam")),
}

#: The formats a texture search spends most of its time in. On game 1.0.0.3663
#: (2026-11-16) the worker's byte search over every format `.dds` lists took 90 s;
#: these five took 65 s of it: `.pam` 29 s (66,572 files, 28.7 GB), `.pamlod` 15 s
#: (35,622 files, 11.8 GB), `.pami` 9 s (84,389 files), `.palevel` 6.5 s (35,721
#: files, 7.1 GB) and `.prefab` 5.4 s (52,908 files). The other formats took about
#: 1 s each, most of it the walk over the catalogue. A caller that wants a first
#: answer quickly reads the others first and these after.
BULK_REFERENCE_SOURCES = frozenset({".pam", ".pamlod", ".pami", ".palevel", ".prefab"})

#: The formats that answer first: model property files, where every user of the
#: character textures measured was (`.pac_xml`, 13,340 files, 555 MB, under 1 s
#: beyond the walk), and the formats of under 1,000 files and 15 MB, which cost
#: next to nothing. With the remaining small formats in the same request the
#: first answer took 7.8 s instead of 3.2 to 4.0 s.
QUICK_REFERENCE_SOURCES = frozenset({".pac_xml", ".pasg", ".mi", ".paem", ".parg", ".material", ".technique", ".css"})

#: Sounds are found by numeric media ID in banks. A named `.wem` (voice lines such
#: as `unique_kliff_aidialogstringinfo_..._51013.wem`) has no stored path at all.
RUNTIME_NAMED_TARGETS = frozenset({".wem"})

__all__ = ["BULK_REFERENCE_SOURCES", "QUICK_REFERENCE_SOURCES", "REFERENCE_SOURCES_BY_TARGET", "RUNTIME_NAMED_TARGETS"]
