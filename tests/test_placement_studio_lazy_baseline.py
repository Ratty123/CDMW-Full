from pathlib import Path

import pytest

from cdmw.core.archive_format import parse_archive_pamt
from tests.archive_resident_index_fixtures import write_resident_index
from tests.test_new_item_service import build_package
from tools.placement_studio.corpus import Baseline, extract_baseline
from tools.placement_studio.loading import prepare_model_baseline


def test_first_character_then_on_demand_baseline_preserves_existing_files(tmp_path, monkeypatch):
    from tools.placement_studio import cli_support, corpus, tab
    files = {}
    bodies = {}
    for model, stem in (('1_phm', 'phm'), ('2_phw', 'phw')):
        files[f'character/descriptors/socketbonedata/1_pc/{model}/{stem}_01.pab.sockets.xml'] = b'<Sockets />'
        files[f'character/model/1_pc/{model}/{stem}_01.pab'] = b'rig ' + model.encode()
        bodies[model] = f'character/model/1_pc/{model}/armor/15_vest/body.pac'
        files[bodies[model]] = b'body ' + model.encode()
    root = tmp_path / 'packages'
    entries = tuple(parse_archive_pamt(build_package(root, files)))
    source = write_resident_index(root, entries, tmp_path / 'index')
    monkeypatch.setenv('CDMW_PS_WORK_ROOT', str(tmp_path / 'work'))
    monkeypatch.setattr(corpus, 'discover_golden_mods', lambda: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(cli_support, 'discover_body_meshes', lambda models, **_: [bodies[model] for model in models])
    from PySide6.QtCore import Qt
    worker = tab.BaselineWorker(str(root), resident_source=source)
    result = []
    worker.done.connect(lambda baseline, error: result.append((baseline, error)), Qt.DirectConnection)
    worker.run()
    baseline, error = result[0]
    assert not error
    assert bodies['1_phm'] in baseline and bodies['2_phw'] not in baseline
    assert any('/2_phw/' in path and path.endswith('.xml') for path in baseline.paths())
    previous = baseline.root / bodies['1_phm']
    stamp = previous.stat().st_mtime_ns
    expanded = prepare_model_baseline(baseline, '2_phw', source, lambda: False)
    assert all(path in expanded for path in files)
    assert expanded.read(bodies['1_phm']) == files[bodies['1_phm']]
    assert previous.stat().st_mtime_ns == stamp
    assert Baseline.load(expanded.root).paths() == expanded.paths()
    assert prepare_model_baseline(expanded, '2_phw', source, lambda: False) is expanded


def test_cancelled_extension_keeps_published_baseline(tmp_path):
    root = tmp_path / 'packages'
    entries = tuple(parse_archive_pamt(build_package(root, {'model/a.pac': b'a', 'model/b.pac': b'b'})))
    index = write_resident_index(root, entries, tmp_path / 'index').open()
    baseline = extract_baseline(['model/a.pac'], out_root=tmp_path / 'baseline', resident_catalogue=index)
    manifest = (baseline.root / 'baseline.json').read_bytes()
    with pytest.raises(InterruptedError):
        extract_baseline(['model/b.pac'], out_root=baseline.root, resident_catalogue=index,
                         existing=baseline, should_stop=lambda: True)
    assert (baseline.root / 'baseline.json').read_bytes() == manifest
    assert Baseline.load(baseline.root).paths() == ['model/a.pac']
