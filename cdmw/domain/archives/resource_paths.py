"""Installed-path conventions that connect files without naming each other.

Two kinds of rule live here, both pure path arithmetic measured on the shipped
archives (see `docs/crimson-desert-research.md` §7.3 and §11.3):

* Engine resource roots. Action charts, blend spaces, animation sets and
  sequences store a clip as `1_pc/1_phm/clip.paa`, which the engine reads under
  `character/motion/`; a sub-chart as the extensionless `loweraction/x`, read as
  `actionchart/bin__/loweraction/x.paac`; a prefab under the folder it was
  authored in rather than its compiled `bin__` copy. A stored string and the
  installed path it names are therefore not always equal, and treating them as
  unequal hid every chart that uses a clip from Find references.
* Layout companions. A clip's event metadata, its distance LOD, the other
  language copies of a voice line and the lip-sync clip recorded for that line
  all sit at fixed path transformations of each other. These are layout
  matches, not encoded references: the files never name one another.

Nothing here reads an archive. Callers check candidates against their own index.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass

MOTION_ROOT = "character/motion/"
MOTION_LOD_ROOT = "character/motion/motion_lod__/"
ANIMATION_METADATA_ROOT = "actionchart/bin__/animmeta/"
ACTION_CHART_ROOT = "actionchart/bin__/"
BLEND_SPACE_ROOT = "character/binary/motionblending/"
SEQUENCE_ROOT = "sequencer/"
VOICE_ROOT = "sound/windows/"
LIP_SYNC_FOLDER = "99_autofacial"

# The voice-language folders the shipped build mounts under `sound/windows/` and
# beside its lip-sync clips. The game's own spelling, not Wwise's defaults.
VOICE_LANGUAGE_FOLDERS: tuple[str, ...] = (
    "chinese(prc)",
    "english(us)",
    "french",
    "german",
    "japanese",
    "korean",
    "portuguese(br)",
    "spanish(es)",
)
_VOICE_LANGUAGES = frozenset(VOICE_LANGUAGE_FOLDERS)
_COMPILED_PREFAB_TOPS = ("character", "object")

# Relation kinds for `layout_companions`. The display role for each lives with
# the Asset Family owner; these keys are what tests and callers compare.
ANIMATION_METADATA = "animation_metadata"
ANIMATION_CLIP = "animation_clip"
LOD_CLIP = "lod_clip"
BASE_CLIP = "base_clip"
LANGUAGE_VARIANT = "language_variant"
VOICE_LINE = "voice_line"
LIP_SYNC_CLIP = "lip_sync_clip"

# Relation confidences. A path-layout match is a fixed transformation every
# installed file of that kind follows; a line-name match pairs a voice line and
# a lip-sync clip by their shared name and language, which is a naming
# convention rather than a reference either file encodes.
PATH_LAYOUT_CONFIDENCE = "path_layout"
LINE_NAME_CONFIDENCE = "line_name"
_LINE_NAME_KINDS = frozenset({VOICE_LINE, LIP_SYNC_CLIP})


@dataclass(frozen=True)
class LayoutCompanion:
    """A file at a fixed path transformation of another.

    `path` is exact when set. `basename` with `folder_segments` is used instead
    when part of the path cannot be derived, such as the rig folder a lip-sync
    clip sits in: the caller accepts a file of that name whose folder contains
    every listed segment in order.
    """

    kind: str
    path: str = ""
    basename: str = ""
    folder_segments: tuple[str, ...] = ()
    excluded_prefixes: tuple[str, ...] = ()

    @property
    def confidence(self) -> str:
        return LINE_NAME_CONFIDENCE if self.kind in _LINE_NAME_KINDS else PATH_LAYOUT_CONFIDENCE

    @property
    def lookup_basename(self) -> str:
        return self.basename or self.path.rpartition("/")[2]

    def matches(self, path: str) -> bool:
        candidate = normalize_resource_path(path)
        if self.path:
            return candidate == self.path
        return (
            candidate.rpartition("/")[2] == self.basename
            and not candidate.startswith(self.excluded_prefixes)
            and folder_matches_segments(candidate, self.folder_segments)
        )


def normalize_resource_path(value: str) -> str:
    """Lowercase posix form with no leading slash, matching archive indexes."""

    text = str(value or "").replace("\\", "/").strip().strip("\x00")
    if not text:
        return ""
    normalized = posixpath.normpath(text).lstrip("/").casefold()
    return "" if normalized == "." else normalized


def _extension(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name[name.rfind("."):] if "." in name else ""


def installed_path_candidates(stored: str) -> tuple[str, ...]:
    """Installed paths a stored reference string can name, most literal first."""

    path = normalize_resource_path(stored)
    if not path:
        return ()
    candidates = [path]
    if "/" not in path:
        # A bare name says nothing about its folder; roots apply to paths only.
        return tuple(candidates)
    extension = _extension(path)
    if extension == ".paa" and not path.startswith(("character/", "object/")):
        candidates.append(MOTION_ROOT + path)
    elif extension == ".motionblending" and not path.startswith("character/"):
        candidates.append(BLEND_SPACE_ROOT + path)
    elif extension == ".prefab":
        top, _, rest = path.partition("/")
        if top in _COMPILED_PREFAB_TOPS and rest.startswith("prefab/"):
            candidates.append(f"{top}/bin__/{rest}")
    elif not extension:
        candidates.append(ACTION_CHART_ROOT + path + ".paac")
        candidates.append(SEQUENCE_ROOT + path + ".paseq")
    return tuple(dict.fromkeys(candidates))


def stored_reference_forms(installed: str) -> tuple[str, ...]:
    """Strings a container may store to name `installed`, most literal first.

    The inverse of `installed_path_candidates`: every form returned here maps
    back to `installed` through that function.
    """

    path = normalize_resource_path(installed)
    if not path:
        return ()
    forms = [path]
    extension = _extension(path)
    if extension == ".paa" and path.startswith(MOTION_ROOT):
        forms.append(path[len(MOTION_ROOT):])
    elif extension == ".motionblending" and path.startswith(BLEND_SPACE_ROOT):
        forms.append(path[len(BLEND_SPACE_ROOT):])
    elif extension == ".prefab":
        top, _, rest = path.partition("/")
        if top in _COMPILED_PREFAB_TOPS and rest.startswith("bin__/prefab/"):
            forms.append(f"{top}/{rest[len('bin__/'):]}")
    elif extension == ".paac" and path.startswith(ACTION_CHART_ROOT) and not path.startswith(ANIMATION_METADATA_ROOT):
        forms.append(path[len(ACTION_CHART_ROOT):-len(".paac")])
    elif extension == ".paseq" and path.startswith(SEQUENCE_ROOT):
        forms.append(path[len(SEQUENCE_ROOT):-len(".paseq")])
    return tuple(form for form in dict.fromkeys(forms) if path in installed_path_candidates(form))


def length_prefix_variants(token: str) -> tuple[str, ...]:
    """`token`, plus the token without a leaked one-byte length prefix.

    Action charts store `<strlen + 1><text><NUL>` and clips `<strlen><text>`.
    When that length byte happens to be a printable path character, a scan for
    path characters swallows it, reading `c1_pc/...` for `1_pc/...`. The byte is
    only removed when its value is exactly the length either framing implies.
    """

    text = str(token or "")
    if len(text) < 2:
        return (text,) if text else ()
    if ord(text[0]) in {len(text) - 1, len(text)}:
        return text, text[1:]
    return (text,)


def _language_index(segments: tuple[str, ...]) -> int:
    for index, segment in enumerate(segments[:-1]):
        if segment in _VOICE_LANGUAGES:
            return index
    return -1


def language_variant_paths(path: str) -> tuple[str, ...]:
    """The same file in each other voice-language folder."""

    normalized = normalize_resource_path(path)
    segments = tuple(normalized.split("/"))
    index = _language_index(segments)
    if index < 0:
        return ()
    return tuple(
        "/".join((*segments[:index], language, *segments[index + 1:]))
        for language in VOICE_LANGUAGE_FOLDERS
        if language != segments[index]
    )


def layout_companions(path: str) -> tuple[LayoutCompanion, ...]:
    """Files the installed layout places at a fixed transformation of `path`."""

    normalized = normalize_resource_path(path)
    if not normalized:
        return ()
    extension = _extension(normalized)
    folder, _, name = normalized.rpartition("/")
    companions = []
    if extension == ".paa" and normalized.startswith(MOTION_LOD_ROOT):
        stem = name[: -len(".paa")]
        if stem.endswith("_lod"):
            relative_folder = folder[len(MOTION_LOD_ROOT):]
            base = f"{MOTION_ROOT}{relative_folder}/{stem[:-4]}.paa" if relative_folder else f"{MOTION_ROOT}{stem[:-4]}.paa"
            companions.append(LayoutCompanion(BASE_CLIP, path=base))
    elif extension == ".paa" and normalized.startswith(MOTION_ROOT):
        relative = normalized[len(MOTION_ROOT):]
        companions.append(LayoutCompanion(ANIMATION_METADATA, path=f"{ANIMATION_METADATA_ROOT}{relative}_metabin"))
        companions.append(LayoutCompanion(LOD_CLIP, path=f"{MOTION_LOD_ROOT}{relative[: -len('.paa')]}_lod.paa"))
        segments = tuple(normalized.split("/"))
        index = _language_index(segments)
        if index > 0 and segments[index - 1] == LIP_SYNC_FOLDER:
            companions.append(LayoutCompanion(VOICE_LINE, path=f"{VOICE_ROOT}{segments[index]}/{name[: -len('.paa')]}.wem"))
    elif extension == ".paa_metabin" and normalized.startswith(ANIMATION_METADATA_ROOT):
        companions.append(LayoutCompanion(ANIMATION_CLIP, path=MOTION_ROOT + normalized[len(ANIMATION_METADATA_ROOT): -len("_metabin")]))
    elif extension == ".wem" and normalized.startswith(VOICE_ROOT):
        segments = tuple(normalized.split("/"))
        if len(segments) == 4 and segments[2] in _VOICE_LANGUAGES:
            companions.append(
                LayoutCompanion(
                    LIP_SYNC_CLIP,
                    basename=name[: -len(".wem")] + ".paa",
                    folder_segments=(MOTION_ROOT.rstrip("/"), LIP_SYNC_FOLDER, segments[2]),
                    excluded_prefixes=(MOTION_LOD_ROOT,),
                )
            )
    companions.extend(LayoutCompanion(LANGUAGE_VARIANT, path=variant) for variant in language_variant_paths(normalized))
    return tuple(companions)


def layout_relation(source_path: str, target_path: str) -> LayoutCompanion | None:
    """The layout companion of `source_path` that `target_path` is, if any."""

    target = normalize_resource_path(target_path)
    if not target:
        return None
    return next((companion for companion in layout_companions(source_path) if companion.matches(target)), None)


def folder_matches_segments(path: str, segments: tuple[str, ...]) -> bool:
    """True when the folder of `path` starts with the first segment and contains the rest in order.

    The first segment may span several path parts (`character/motion`); the last
    must be the folder that directly holds the file.
    """

    folder = normalize_resource_path(path).rpartition("/")[0]
    if not segments:
        return True
    if not (folder == segments[0] or folder.startswith(segments[0] + "/")):
        return False
    if len(segments) > 1 and folder.rpartition("/")[2] != segments[-1]:
        return False
    parts = folder.split("/")
    position = 0
    for segment in segments[1:]:
        try:
            position = parts.index(segment, position) + 1
        except ValueError:
            return False
    return True


__all__ = [
    "ACTION_CHART_ROOT",
    "ANIMATION_CLIP",
    "ANIMATION_METADATA",
    "ANIMATION_METADATA_ROOT",
    "BASE_CLIP",
    "BLEND_SPACE_ROOT",
    "LANGUAGE_VARIANT",
    "LINE_NAME_CONFIDENCE",
    "LIP_SYNC_CLIP",
    "LIP_SYNC_FOLDER",
    "LOD_CLIP",
    "MOTION_LOD_ROOT",
    "MOTION_ROOT",
    "PATH_LAYOUT_CONFIDENCE",
    "SEQUENCE_ROOT",
    "VOICE_LANGUAGE_FOLDERS",
    "VOICE_LINE",
    "VOICE_ROOT",
    "LayoutCompanion",
    "folder_matches_segments",
    "installed_path_candidates",
    "language_variant_paths",
    "layout_companions",
    "layout_relation",
    "length_prefix_variants",
    "normalize_resource_path",
    "stored_reference_forms",
]
