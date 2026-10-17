from concurrent.futures import ThreadPoolExecutor

import pytest

from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services import virtual_loader_cache as cache_owner
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import PROFILE_PATH, load_profile, publish_profile
from tests.test_virtual_loader import game_bytes, packages


@pytest.mark.parametrize('changed', ['package', 'metadata', 'external', 'registry'])
def test_cache_hit_rechecks_inputs_before_returning_a_prepared_generation(tmp_path, monkeypatch, changed):
    root, selected = packages(tmp_path, 1)
    mod = tmp_path / 'mod'
    external = mod / 'files/character/guarded.txt'
    external.parent.mkdir(parents=True)
    external.write_bytes(b'original external data')
    profile = VirtualProfile(selected, (mod,))
    first = prepare_profile(profile, root)
    publish_profile(first)
    previous = (root / PROFILE_PATH).read_bytes()
    target = {'package': selected[0], 'metadata': root / 'meta/0.papgt',
              'external': external, 'registry': root / '.cdmw/independent-items.json'}[changed]
    original = target.read_bytes()
    whole_output = cache_owner.VerifiedBuildCache.whole_output
    hits = []
    def mutate_after_verified_hit(self, *args, **kwargs):
        output = whole_output(self, *args, **kwargs)
        assert output is not None
        hits.append(True)
        # Bookkeeping whitespace remains valid JSON; observed bytes must still
        # match. All other cases change a just-verified source file directly.
        target.write_bytes(original + b'\n' if changed == 'registry' else bytes([original[0] ^ 1]) + original[1:])
        return output
    monkeypatch.setattr(cache_owner.VerifiedBuildCache, 'whole_output', mutate_after_verified_hit)
    try:
        with pytest.raises(ValueError, match='changed'):
            prepare_profile(profile, root)
        assert hits and (root / PROFILE_PATH).read_bytes() == previous
    finally:
        target.write_bytes(original)
    assert load_profile(root)['generation'] == first.generation


def test_parallel_preparations_own_separate_captured_cache_views(tmp_path):
    root, selected = packages(tmp_path, 1)
    profile = VirtualProfile(selected)
    first = prepare_profile(profile, root)
    publish_profile(first)
    previous = (root / PROFILE_PATH).read_bytes()
    before = game_bytes(root)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = tuple(workers.map(lambda _: prepare_profile(profile, root), range(2)))
    assert len({result.generation for result in results}) == 2
    assert all(dict(result.files) == dict(first.files) for result in results)
    assert all(any('Reused verified private archives' in line for line in result.summary) for result in results)
    assert (root / PROFILE_PATH).read_bytes() == previous and game_bytes(root) == before
    assert results[0].source_revision is not results[1].source_revision
