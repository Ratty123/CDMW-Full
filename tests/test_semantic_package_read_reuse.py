"""Semantic admission and lowering share one exact package decode owner."""
from cdmw.core.mod_compatibility import SEMANTIC_EXPORT_FILE, read_semantic_export
from cdmw.services import independent_item_package as packages
from cdmw.services.independent_item_install import resolve_items
from tests.test_independent_items import setup_game
from tests.test_semantic_export_contract import original_export


def test_semantic_contributor_is_not_decoded_again_during_lowering(tmp_path, original_export, monkeypatch):
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    wrapper = tmp_path / SEMANTIC_EXPORT_FILE
    wrapper.write_bytes(original_export)
    validate, decoded = packages._package, []
    def count(meta, blobs, **kwargs):
        decoded.append(meta['identity'])
        return validate(meta, blobs, **kwargs)
    monkeypatch.setattr(packages, '_package', count)
    result = resolve_items([wrapper], root, target='virtual')
    assert len(result.contributions) == len(decoded) == 1
    assert result.contributions[0][0].identity == decoded[0]
    assert not (root / '.cdmw').exists()


def test_semantic_read_cache_does_not_share_mutable_package_metadata(original_export):
    cache = packages.PackageReadCache()
    export = read_semantic_export(original_export, package_cache=cache)
    first = packages.read_package(export.packages[0], cache=cache)
    identity, checksum = first.identity, first.digest
    first.manifest['metadata']['caller'] = True
    first.dependencies.clear()
    second = packages.read_package(export.packages[0], cache=cache)
    assert second.identity == identity and second.digest == checksum
    assert second.dependencies and 'caller' not in second.manifest['metadata']
