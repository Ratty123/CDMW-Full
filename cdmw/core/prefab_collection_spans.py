"""What the walk found out about a prefab's collections, and how to judge it.

Split from :mod:`cdmw.core.prefab_binary` because it is a different kind of
thing: that module reads bytes, this one holds what reading them established
about where each collection sits and whether the reading is self-consistent.
Nothing here parses anything, and nothing here imports the decoder, so the
dependency runs one way.

:class:`PrefabCollection` is re-exported from ``prefab_binary``; callers should
keep importing it from there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PrefabCollection:
    """One collection the walk read, and where each of its elements sits.

    The walk already knows all of this -- it consumed the header and then read
    ``count`` elements one after another -- but it used to throw it away. An
    editor that wants to add or drop an element has to have it, and *has to
    have it from the walk*: the header is only distinguishable from the bytes
    around it by having been arrived at, and the element boundaries are wherever
    the previous element stopped. Searching for either is guesswork.
    """

    #: The member that declares the collection, e.g. ``_childSceneObjects``.
    member_name: str
    #: The component type holding that member; ``""`` at the root.
    owner_type: str
    #: Absolute offset of the header's kind byte.
    header_offset: int
    #: 5 for the narrow header, 6 for the wide one. The count sits in the last
    #: four bytes either way, so a writer never has to re-decide the width.
    header_width: int
    #: Elements the header declares. Equal to ``len(elements)`` except on a file
    #: whose count outruns the data, where the walk stopped at the trailer.
    count: int
    #: Absolute ``(start, end)`` per element, in file order.
    elements: tuple[tuple[int, int], ...] = ()

    @property
    def count_offset(self) -> int:
        """Absolute offset of the u32 element count."""
        return self.header_offset + self.header_width - 4


def over_declared(document: Any) -> int:
    """Collections claiming more elements than the walk could read.

    Every one of these is a decode that is wrong without saying so: the walk ran
    out of elements and stopped on the trailer, so the file looks read while a
    collection's count is fiction. A count rather than a flag, because the
    decoder uses it to decide whether re-reading the file at a different header
    width came out *better* -- which needs a comparison, not a yes or no.
    """
    return sum(1 for item in document.collections if len(item.elements) != item.count)


__all__ = ["PrefabCollection", "over_declared"]
