from types import SimpleNamespace

import pytest

from tools.placement_studio.relationships import Relationships, Reference, from_files, active_entries


def test_mapping_precedence_suffix_and_missing_default():
    p = 'character/descriptors/animationset/bow.animset.xml'
    default = 'character/motion/1_pc/bow/default.paa'
    files = {p: b'<AnimationSet Suffix="_at.paa" DefaultAnimation="1_pc/bow/default.paa"><AnimationInfo Name="1_pc/draw.paa" FileName="1_pc/bow/draw.paa"/></AnimationSet>'}
    index = from_files(files, paths=[default, 'character/motion/1_pc/bow/draw.paa', 'character/motion/1_pc/bow/run_at.paa'])
    mapping = index.sets[p]
    assert mapping.resolve('1_pc/draw.paa', index.paths)[1] == 'Explicit animation-set mapping'
    assert mapping.resolve('1_pc/run.paa', index.paths)[1] == 'Installed suffix companion'
    assert mapping.resolve('1_pc/idle.paa', index.paths) == (default, 'Explicit default')
    assert mapping.resolve('1_pc/draw.paa', ())[0] == ''


def test_cycles_and_missing_references_are_retained():
    refs = (Reference('a', 'b', 'explicit'), Reference('b', 'a', 'explicit'), Reference('b', 'gone', 'explicit'))
    graph = Relationships(('a', 'b'), refs)
    found, issues = graph.closure('a')
    assert found == refs
    assert issues == ('Cycle: a', 'Missing: gone')
    assert 'Coverage:' in dict(graph.impact(['b']))['b'][-1]


def test_installed_mount_order_excludes_unmounted_and_invalid_manifest_fails(tmp_path, monkeypatch):
    from cdmw.core.papgt_format import PapgtDirectory, serialize_papgt
    from cdmw.core import archive_format
    tables = [tmp_path / name / '0.pamt' for name in ('base', 'overlay', 'unmounted')]
    for p in tables:
        p.parent.mkdir(); p.write_bytes(b'fixture')
    (tmp_path / 'meta').mkdir()
    mount = tmp_path / 'meta/0.papgt'
    mount.write_bytes(serialize_papgt([PapgtDirectory('overlay', 0, 0), PapgtDirectory('base', 0, 0)]))
    monkeypatch.setattr(archive_format, 'discover_pamt_files', lambda _: tables)
    monkeypatch.setattr(archive_format, 'parse_archive_pamt', lambda p: [SimpleNamespace(path='same.paa')])
    assert [package for package, _ in active_entries(tmp_path)] == ['overlay', 'base']
    mount.write_bytes(b'invalid')
    with pytest.raises(ValueError): list(active_entries(tmp_path))


def test_matching_patterns_report_ambiguous_mappings():
    model = 'character/model/1_pc/bow_01.pac'
    table = b'<AnimationSetMatchingTable><AnimationSet FilePath="a.animset.xml"><Model FilePath="1_pc/bow_*.pac"/></AnimationSet><AnimationSet FilePath="b.animset.xml"><Model FilePath="1_pc/bow_01.pac"/></AnimationSet></AnimationSetMatchingTable>'
    graph = from_files({'character/descriptors/animationset/matchingtable.xml': table}, paths=[model])
    assert graph.attachment(model, 'idle.paa')[0] == ''
    assert len(graph.forward[model]) == 2


def test_shared_impact_follows_explicit_sets_and_equipment_without_losing_cycles():
    graph=Relationships(('clip','set','mesh','chart'),(Reference('set','clip','Explicit input'),
        Reference('mesh','set','Explicit model pattern'),Reference('chart','clip','Explicit chart resource','Socket association only'),
        Reference('set','chart','Explicit input')))
    findings=dict(graph.impact(['clip']))['clip']
    assert any('mesh via set' in f for f in findings)
    assert any('Socket association only' in f for f in findings)
    assert findings[-1].startswith('Coverage:')


def test_metadata_companion_resolves_its_actual_animation_directory():
    clip='character/motion/1_pc/1_phm/draw.paa'
    meta='actionchart/bin__/animmeta/1_pc/1_phm/draw.paa_metabin'
    graph=from_files({},paths=(clip,meta))
    refs,problems=graph.closure(clip)
    assert len(refs)==1 and refs[0].target==meta
    assert refs[0].detail=='Event semantics Unverified' and not problems
