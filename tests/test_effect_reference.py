"""Reference namespaces come from the active game snapshot, not a fixed suffix."""
import pytest

from cdmw.services.effect_reference import KINDS, resolve_effect_reference


class Snapshot:
    def __init__(self, files=None):
        self.files = files or {}
        self._authoring_indexes = {}
        self.reads = []

    def has_entry(self, path):
        return path in self.files

    def payload(self, path):
        self.reads.append(path)
        return self.files[path]


def test_action_namespace_is_resolved_and_cached_despite_malformed_xml_comments():
    snapshot = Snapshot({'effect/effect_action.xml': b'''<Effects>
        <!-- invalid -- comment -->
        <!-- <Effect Name="fx_hidden.action.effect"/> -->
        <Effect Name="fx_aftertaa_a__lightning_att1.action.effect" Path="fx/fx_aftertaa_a"/>
        </Effects>'''})
    source = 'fx_aftertaa_a__lightning_att1.level.effect'
    assert resolve_effect_reference(snapshot, source) == 'fx_aftertaa_a__lightning_att1.action.effect'
    assert resolve_effect_reference(snapshot, source) == 'fx_aftertaa_a__lightning_att1.action.effect'
    assert resolve_effect_reference(snapshot, 'fx_hidden.level.effect') == 'fx_hidden.level.effect'
    assert snapshot.reads == ['effect/effect_action.xml']


@pytest.mark.parametrize('kind', KINDS)
def test_every_shipped_namespace_is_retained(kind):
    from cdmw.domain.new_item.effect_authoring import EffectLayer
    from cdmw.services.effect_library_store import read_recipe, recipe_json
    reference = f'fx_test.{kind}.effect'
    snapshot = Snapshot({f'effect/effect_{kind}.xml': f'<Effect Name="{reference}"/>'.encode()})
    assert resolve_effect_reference(snapshot, reference) == reference
    assert resolve_effect_reference(snapshot, 'fx_test.level.effect') == reference
    layer = EffectLayer('fx_test', kind=kind)
    assert read_recipe(recipe_json((layer,))) == (layer,)


def test_valid_explicit_namespace_wins_over_other_registrations():
    snapshot = Snapshot({f'effect/effect_{kind}.xml': f'<Effect Name="fx_test.{kind}.effect"/>'.encode()
                         for kind in ('level', 'action')})
    assert resolve_effect_reference(snapshot, 'fx_test.action.effect') == 'fx_test.action.effect'


def test_legacy_snapshot_without_registries_preserves_reference():
    assert resolve_effect_reference(Snapshot(), 'fx_custom.level.effect') == 'fx_custom.level.effect'


def test_registry_read_failure_is_not_suppressed():
    class Broken(Snapshot):
        def payload(self, path):
            raise OSError('unreadable registry')
    with pytest.raises(OSError, match='unreadable registry'):
        resolve_effect_reference(Broken({'effect/effect_action.xml': b''}), 'fx_test.level.effect')
