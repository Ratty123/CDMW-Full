"""Effect cache checks must not materialize the full resident archive catalogue."""

from collections.abc import Mapping
from types import SimpleNamespace
import threading

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.services.effect_catalogue import catalogue_signature
from cdmw.services.effect_catalogue_dependencies import effect_binary_entries


class LazyEntries(Mapping):
    def __init__(self, definitions, *, paths_only=False, cancel=None):
        self.definitions = definitions
        self.paths_only = paths_only
        self.cancel = cancel
        self.reads = []

    def __iter__(self):
        assert not self.paths_only, "The snapshot already has indexed effect paths"
        yield "character/texture/unrelated.dds"
        yield from self.definitions

    def __len__(self):
        raise AssertionError("No full catalogue count is needed")

    def __getitem__(self, key):
        assert key in self.definitions, "Unrelated entries must stay lazy"
        self.reads.append(key)
        if self.cancel is not None:
            self.cancel.set()
        return self.definitions[key]


@pytest.mark.parametrize("indexed", [False, True])
def test_signature_reads_only_effect_definitions_and_preserves_cache_identity(indexed):
    definitions = {f"effect/binary__/releasebin/sample{extension}": SimpleNamespace(orig_size=10, offset=i)
                   for i, extension in enumerate((".pae", ".paem", ".parg", ".pasg"))}
    lazy = LazyEntries(definitions, paths_only=indexed)
    snapshot = SimpleNamespace(entries=lazy, _effect_binary_paths=tuple(definitions) if indexed else None)
    expected = catalogue_signature(SimpleNamespace(entries=definitions))
    assert catalogue_signature(snapshot) == expected
    assert set(lazy.reads) == set(definitions)
    definitions[next(path for path in definitions if path.endswith('.paem'))].offset += 1
    assert catalogue_signature(snapshot) != expected


@pytest.mark.parametrize("pre_cancelled", [False, True])
def test_effect_candidate_scan_honors_cancellation_before_and_between_entries(pre_cancelled):
    stop = threading.Event()
    if pre_cancelled:
        stop.set()
    definitions = {f"effect/binary__/releasebin/{stem}.pae": object() for stem in ("one", "two")}
    lazy = LazyEntries(definitions, paths_only=True, cancel=stop)
    with pytest.raises(RunCancelled):
        effect_binary_entries(SimpleNamespace(entries=lazy, _effect_binary_paths=tuple(definitions)), stop_event=stop)
    assert len(lazy.reads) == (0 if pre_cancelled else 1)


@pytest.mark.parametrize("indexed", [False, True])
def test_snapshot_prepares_effect_paths_from_the_archive_extension_index(tmp_path, indexed):
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.services.new_item_service import NewItemService
    from tests.test_new_item_service import _read, build_package, synthetic_files

    files = synthetic_files()
    definitions = {f"effect/binary__/releasebin/sample{extension}": b"metadata"
                   for extension in (".pae", ".paem", ".parg", ".pasg")}
    files.update(definitions)
    files['character/unrelated.pae'] = b'not an effect'
    expected = set(definitions) | {'effect/binary__/releasebin/fx_test_fire.pae', 'effect/binary__/releasebin/fx_test_ice.pae'}
    entries = tuple(parse_archive_pamt(build_package(tmp_path, files)))
    by_extension = {}
    for entry in entries:
        by_extension.setdefault('.' + entry.path.rsplit('.', 1)[-1], []).append(entry)
    snapshot = NewItemService().build_snapshot(entries, read_entry=_read, entries_by_extension=by_extension if indexed else None)
    assert set(snapshot._effect_binary_paths) == expected
    assert snapshot.effect_stems == frozenset({'sample', 'fx_test_fire', 'fx_test_ice'})
    assert {path for path, _entry in effect_binary_entries(snapshot)} == expected
