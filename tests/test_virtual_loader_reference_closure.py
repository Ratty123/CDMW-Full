"""Narrow launch guards only after a completed, parsed resource traversal."""
from types import SimpleNamespace

import pytest

from cdmw.domain.new_item.independent import IndependentItemError, IndependentItemPackage
from cdmw.models import ArchiveEntry
from cdmw.services.independent_item_references import audit_references
from cdmw.services.new_item_provenance import SourceTracker
from cdmw.services.virtual_loader_sources import profile_revision


def _item_table():
    from tests.item_layout_fixtures import full_item
    from tests.test_iteminfo_row import build_row
    from tests.test_new_item_service import _table4
    body = 'gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody'
    payload, header = _table4([(1, full_item(build_row(key=1)))])
    return SimpleNamespace(payload_entry=SimpleNamespace(path=body),
        header_entry=SimpleNamespace(path=body.replace('staticinfobody', 'staticinfoheader')),
        payload=payload, header=header)


def _audit_fixture(tmp_path, resources, first):
    index = tmp_path / '0.pamt'
    carrier = tmp_path / '0.paz'
    unrelated = tmp_path / '1.paz'
    for path in (index, carrier, unrelated):
        path.write_bytes(b'owned closure fixture')
    tracker = SourceTracker(lambda entry: resources[entry.path])
    tracker.pin_file(index)
    tracker.pin_catalogue_file(carrier)
    tracker.pin_catalogue_file(unrelated)
    family = SimpleNamespace(
        files=(SimpleNamespace(exists=True, path=first),), parts=())
    snapshot = SimpleNamespace(
        provenance=tracker,
        family=lambda _key: family,
        has_entry=lambda path: path in resources,
        iteminfo=_item_table(), stringinfo_texts={}, pappt=SimpleNamespace(index=lambda: {}),
        pappt_entry=SimpleNamespace(path='character/partprefabtable.pappt'))
    snapshot.payload = lambda path: snapshot.provenance.read(ArchiveEntry(
        path, index, carrier, 0, len(resources[path]), len(resources[path]), 0, 0))
    plan = SimpleNamespace(
        additions=(), manifest={}, loose_files={},
        spec=SimpleNamespace(template_key=1, item_key=1, variants=None, stem='fixture'))
    return tracker, snapshot, plan, carrier, unrelated


def _resolved(tracker):
    package = IndependentItemPackage('1' * 32, 'closure fixture', {}, {}, {}, '2' * 64)
    return SimpleNamespace(
        baseline=SimpleNamespace(provenance=tracker),
        revisions=(tracker.capture(),),
        external=SimpleNamespace(providers=()), state={'layers': ()},
        contributions=((package, {}),))


@pytest.mark.parametrize('borrowed,contents,complete', [
    ('character/texture.dds', b'DDS ' + bytes(124), True),
    ('character/borrowed.sockets.xml', b'<Sockets><Resource path="character/unvisited.dds"/></Sockets>', False),
    ('character/borrowed.hkx', b'unparsed borrowed physics', False),
])
def test_reference_closure_requires_parsed_transitive_boundaries(tmp_path, borrowed, contents, complete):
    first = 'character/model/fixture.pac_xml'
    resources = {
        first: ('<SkinnedMeshPropertyCommon><ResourceReferencePath _path="'
                + borrowed + '"/></SkinnedMeshPropertyCommon>').encode(),
        borrowed: contents,
    }
    tracker, snapshot, plan, carrier, unrelated = _audit_fixture(tmp_path, resources, first)
    # A v1 package type alone never authorizes a narrower source guard.
    assert profile_revision(_resolved(tracker)).catalogue_files == ()
    audit_references(plan, snapshot)
    revision = tracker.capture()
    assert revision.reference_closure_complete is complete
    assert {payload.entry.path for payload in revision.payloads} == set(resources)
    classified = profile_revision(_resolved(tracker))
    assert carrier in dict(classified.content_files)
    assert classified.catalogue_files == ((unrelated,) if complete else ())
    assert (unrelated in dict(classified.content_files)) is not complete


def test_reference_closure_forks_do_not_inherit_or_upgrade_unproved_dependencies(tmp_path):
    resources = {'character/texture.dds': b'DDS ' + bytes(124), 'character/borrowed.xml': b'<Unknown/>'}
    tracker, snapshot, plan, _carrier, _unrelated = _audit_fixture(tmp_path, resources, 'character/texture.dds')
    audit_references(plan, snapshot)
    assert tracker.capture().reference_closure_complete
    retained = tracker.fork(tracker.reader, include_reads=True)
    discovery = tracker.fork(tracker.reader)
    assert retained.capture().reference_closure_complete
    assert not discovery.capture().reference_closure_complete

    snapshot.provenance = retained
    snapshot.family = lambda _key: SimpleNamespace(
        files=(SimpleNamespace(exists=True, path='character/borrowed.xml'),), parts=())
    audit_references(plan, snapshot)
    assert not retained.capture().reference_closure_complete
    assert tracker.capture().reference_closure_complete
    snapshot.family = lambda _key: SimpleNamespace(
        files=(SimpleNamespace(exists=True, path='character/texture.dds'),), parts=())
    audit_references(plan, snapshot)
    assert not retained.capture().reference_closure_complete


def test_reference_closure_is_not_recorded_when_a_reference_audit_fails(tmp_path):
    first = 'character/model/fixture.pac_xml'
    resources = {first: b'<SkinnedMeshPropertyCommon><ResourceReferencePath _path="character/missing.dds"/></SkinnedMeshPropertyCommon>'}
    tracker, snapshot, plan, _carrier, _unrelated = _audit_fixture(tmp_path, resources, first)
    with pytest.raises(IndependentItemError, match='Unresolved item dependency'):
        audit_references(plan, snapshot)
    assert not tracker.capture().reference_closure_complete
    assert profile_revision(_resolved(tracker)).catalogue_files == ()
