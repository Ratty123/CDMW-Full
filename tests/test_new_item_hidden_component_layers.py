"""A component left out of the export stops cutting everything underneath it."""
from cdmw.core.equipment_visibility import clone_shrink_rules, shrink_rule_names
from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.domain.new_item.body_visibility import BodyVisibilityChoice
from cdmw.services.new_item_body_visibility import _key, retag_prefab_components, rule_receivers_reader
from tests.test_new_item_body_visibility import SHRINK, prefab, receivers

SHIRT = "character/model/test/shirt.pac"
GROUND = "character/model/test/ground.pac"


def _retag(selected, *, hidden=frozenset(), explicit=None, source=None):
    profiles = []
    known = shrink_rule_names(SHRINK)

    def allocate(old, choice):
        return ("Z" * len(old)) if choice.keep_receivers else ("Y" * len(old))

    data = source or prefab(((SHIRT, "Hand"), (GROUND, "")))
    result = retag_prefab_components("character/bin__/prefab/test.prefab", data, selected, known, allocate,
                                     profiles, rule_receivers_reader(SHRINK), hidden=hidden, explicit=explicit)
    return result, profiles


def test_a_hidden_component_keeps_skin_hair_and_every_clothing_layer_its_rule_cuts():
    shirt = _key(SHIRT)
    result, profiles = _retag({shirt: BodyVisibilityChoice(True, True)}, hidden=frozenset({shirt}), explicit=frozenset())
    profile, = profiles
    assert profile.source_tag == "Hand"
    assert profile.choice.keep_skin and profile.choice.keep_hair
    # The Hand rule cuts Nude and Underwear; a component that draws nothing keeps both.
    assert profile.choice.keep_receivers == frozenset({"Underwear"})
    rules = clone_shrink_rules(SHRINK, tuple(profiles))
    assert receivers(rules, profile.tag) == set()
    assert receivers(rules, "Hand") == {"Nude", "Underwear"}
    detail, = (d for d in result.details if d["model_path"] == shirt)
    assert detail["hidden_in_export"] is True and detail["profile"] == profile.tag
    tags = [dict(o.values)["_shrinkTag"].text for o in decode_prefab_binary(result.data).objects]
    assert profile.tag in tags


def test_a_visible_component_keeps_only_the_layers_the_author_ticked():
    shirt = _key(SHIRT)
    _result, profiles = _retag({shirt: BodyVisibilityChoice(keep_skin=True)})
    profile, = profiles
    assert profile.choice.keep_receivers == frozenset()


def test_a_hidden_component_without_a_rule_is_noted_quietly():
    ground = _key(GROUND)
    result, profiles = _retag({ground: BodyVisibilityChoice(True, True)}, hidden=frozenset({ground}), explicit=frozenset())
    assert profiles == []
    assert result.warnings == []
    detail, = result.details
    assert detail["hidden_in_export"] is True and detail["profile"] is None
