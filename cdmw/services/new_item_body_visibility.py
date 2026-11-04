"""Prepare item-owned experimental visibility metadata; never writes archives."""
from dataclasses import dataclass, field, replace
import hashlib

from cdmw.core.equipment_visibility import (
    POSTFIX_PATH, SHRINK_PATH, VisibilityProfile, clone_postfix_rules,
    clone_shrink_rules, matching_postfixes, shrink_rule_names, shrink_rule_receivers,
)
from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.core.prefab_binary_edit import PrefabPathEdit, rewrite_prefab_paths_same_length
from cdmw.core.stringinfo_table import stringinfo_key
from cdmw.domain.new_item.body_visibility import HAIR_RECEIVERS, SKIN_RECEIVERS, BodyVisibilityChoice


@dataclass
class BodyVisibilityPlan:
    prefabs: dict[str, bytes] = field(default_factory=dict)
    stem_map: dict[str, str] = field(default_factory=dict)


def _key(path):
    return path.replace("\\", "/").casefold()


def _profile_tag(output_stem, source_tag, choice, known, profiles):
    occupied = {tag.casefold() for tag in known} | {p.tag.casefold() for p in profiles}
    for attempt in range(1000):
        tag = _candidate_tag(output_stem, source_tag, choice, attempt)
        if tag.casefold() not in occupied:
            return tag
    raise ValueError(f"No unused {len(source_tag)}-byte visibility tag is available for {source_tag}.")


def _candidate_tag(output_stem, source_tag, choice, attempt):
    # Preserve string lengths: some fully decoded shipped prefabs still have
    # ambiguous enclosing pointer lengths. An in-place tag edit moves no bytes.
    size = len(source_tag.encode("utf-8"))
    # Skin/hair-only choices keep the identities earlier exports already produced.
    layers = f"|{','.join(sorted(choice.keep_receivers))}" if choice.keep_receivers else ""
    digest = hashlib.shake_256(f"{output_stem}|{source_tag}|{choice.keep_skin}|{choice.keep_hair}{layers}|{attempt}".encode())
    return "V" + digest.hexdigest(size)[:size - 1]


def _binding_record(path, choice):
    record = {"model_path": path, "keep_skin": choice.keep_skin, "keep_hair": choice.keep_hair}
    if choice.keep_receivers:
        record["keep_layers"] = sorted(choice.keep_receivers)
    return record


def profile_record(profile):
    record = {"source_tag": profile.source_tag, "tag": profile.tag,
              "keep_skin": profile.choice.keep_skin, "keep_hair": profile.choice.keep_hair}
    if profile.choice.keep_receivers:
        record["keep_layers"] = sorted(profile.choice.keep_receivers)
    return record


def unlisted_layer_warnings(requested, cut):
    """Kept layers no examined rule cuts change nothing; say so instead of implying a fix.

    ``cut`` holds the casefolded receivers of every rule the selected components use.
    """
    unlisted = sorted(name for name in requested if name.casefold() not in cut)
    if not unlisted:
        return []
    return [f"Experimental visibility: none of this equipment's shrink rules cut {', '.join(unlisted)}; "
            f"keeping {'it' if len(unlisted) == 1 else 'them'} changes nothing."]


def rule_receivers_reader(shrink):
    """Cached receiver lookup for one descriptor."""
    cache = {}

    def receivers(tag):
        if tag not in cache:
            cache[tag] = shrink_rule_receivers(shrink, tag)
        return cache[tag]

    return receivers


@dataclass
class PrefabRetag:
    data: bytes
    details: list = field(default_factory=list)
    profiles: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    #: casefolded receivers of every rule a selected component uses
    cut: set = field(default_factory=set)


def component_shrink_tags(source: bytes, model_paths) -> dict[str, tuple[str, ...]]:
    """Map each wanted mesh path to the shrink tags of the components that bind it."""
    doc = decode_prefab_binary(source)
    if not doc.walk_complete or doc.inferred_objects:
        raise ValueError("visibility requires a complete, unambiguous component decode.")
    wanted = {_key(path) for path in model_paths}
    found = {}
    for obj in doc.objects:
        if obj.component_type != "SkinnedMeshComponent":
            continue
        paths = {_key(value.text) for name, value in obj.values if name in {"_skinnedMeshFile", "_skinnedMeshFileName"}}
        for path in paths & wanted:
            found.setdefault(path, []).extend(value.text for name, value in obj.values if name == "_shrinkTag")
    return {path: tuple(dict.fromkeys(tags)) for path, tags in found.items()}


def cut_layers(shrink: bytes, prefab: bytes, model_path: str) -> tuple[str, ...]:
    """Clothing receivers the components binding ``model_path`` cut, minus skin and hair.

    Skin and hair have their own choices. An unknown tag cuts nothing CDMW can change.
    """
    tags = component_shrink_tags(prefab, (model_path,)).get(_key(model_path), ())
    receivers = (name for tag in tags if tag for name in shrink_rule_receivers(shrink, tag))
    return tuple(name for name in dict.fromkeys(receivers) if name not in SKIN_RECEIVERS | HAIR_RECEIVERS)


def available_layers(snapshot, prefab_path: str, model_path: str) -> tuple[str, ...]:
    """Read-only lookup for the New Item layer list; run it off the UI thread."""
    if not snapshot.has_entry(SHRINK_PATH):
        return ()
    return cut_layers(snapshot.payload(SHRINK_PATH), snapshot.payload(prefab_path), model_path)


def retag_prefab_components(prefab_path, source, selected, known, allocate, profiles, rule_receivers=None,
                            hidden=frozenset(), explicit=None):
    """Point the components that bind the selected meshes at item-owned shrink profiles.

    ``selected`` maps normalized mesh paths to choices; ``allocate(old_tag, choice)``
    returns the same-length replacement tag. Tags keep their byte length, so no
    pointer in the prefab moves. ``profiles`` is the caller's list and grows in
    place, so an allocator that consults it sees tags chosen earlier in this prefab.
    With ``rule_receivers(tag)``, kept layers are matched to the spelling the rule
    uses, and a component whose rule cuts none of them, with no skin or hair
    choice, keeps its shipped tag.

    ``hidden`` holds mesh paths left out of the export. They draw nothing, so their
    rule stops cutting every clothing layer it lists as well as skin and hair.
    ``explicit`` holds the paths the author chose for; a hidden path outside it with
    no known rule (a ground model, for example) has nothing to neutralise.
    """
    doc = decode_prefab_binary(source)
    if not doc.walk_complete or doc.inferred_objects:
        raise ValueError(f"{prefab_path}: visibility requires a complete, unambiguous component decode.")
    result = PrefabRetag(source, profiles=profiles)
    edits, matched, expected_tags = [], set(), {}
    for object_index, obj in enumerate(doc.objects):
        if obj.component_type != "SkinnedMeshComponent":
            continue
        paths = [value.text for name, value in obj.values if name in {"_skinnedMeshFile", "_skinnedMeshFileName"}]
        paths = {_key(path) for path in paths}
        targets = paths & selected.keys()
        if not targets:
            continue
        if len(paths) != 1:
            raise ValueError(f"{prefab_path}: component {obj.name} has ambiguous mesh bindings.")
        path = next(iter(targets))
        matched.add(path)
        choice = selected[path]
        tags = [value for name, value in obj.values if name == "_shrinkTag"]
        if len(tags) > 1:
            raise ValueError(f"{prefab_path}: component {obj.name} has ambiguous shrink tags.")
        old = tags[0].text if tags else ""
        is_hidden = path in hidden
        if old not in known and is_hidden and (explicit is None or path not in explicit):
            result.details.append({"component": obj.name, "source_tag": old, "profile": None,
                                   "model_path": path, "hidden_in_export": True})
            continue
        if old not in known:
            result.warnings.append(f"Experimental visibility: {prefab_path}, {obj.name} has "
                                   f"{'an unknown shrink tag ' + repr(old) if old else 'no explicit shrink tag'}; "
                                   "its geometry-cut rule is unchanged. Only applicable whole-part hide rules can be adjusted.")
            result.details.append({"component": obj.name, "source_tag": old, "profile": None, "model_path": path})
            continue
        if is_hidden and rule_receivers is not None:
            layers = frozenset(name for name in rule_receivers(old)
                               if name not in SKIN_RECEIVERS | HAIR_RECEIVERS)
            choice = replace(choice, keep_receivers=choice.keep_receivers | layers)
        if rule_receivers is not None and choice.keep_receivers:
            cut = rule_receivers(old)
            result.cut.update(name.casefold() for name in cut)
            wanted = {name.casefold() for name in choice.keep_receivers}
            choice = replace(choice, keep_receivers=frozenset(name for name in cut if name.casefold() in wanted))
            if not choice.wanted:
                result.details.append({"component": obj.name, "source_tag": old, "profile": None,
                                       "model_path": path, "unchanged": True})
                continue
        tag = allocate(old, choice)
        profile = VisibilityProfile(old, tag, choice)
        if profile not in result.profiles:
            result.profiles.append(profile)
        edits.append(PrefabPathEdit(tags[0].offset, old, tag))
        expected_tags[object_index] = tag
        result.details.append({"component": obj.name, "source_tag": old, "profile": tag, "model_path": path,
                               "hidden_in_export": is_hidden})
    missing = selected.keys() - matched
    if missing:
        raise ValueError(f"{prefab_path}: no exact SkinnedMeshComponent for visibility selection: {', '.join(sorted(missing))}.")
    try:
        rewritten = rewrite_prefab_paths_same_length(source, tuple(dict.fromkeys(edits))).data if edits else source
        after = decode_prefab_binary(rewritten)
        if not after.walk_complete or after.inferred_objects or len(after.objects) != len(doc.objects):
            raise ValueError("The edited visibility components did not decode identically.")
        for index, (before_obj, after_obj) in enumerate(zip(doc.objects, after.objects)):
            expected = [(name, expected_tags[index] if name == "_shrinkTag" and index in expected_tags else value.text)
                        for name, value in before_obj.values]
            if (expected != [(name, value.text) for name, value in after_obj.values]
                    or (before_obj.component_type, before_obj.name) != (after_obj.component_type, after_obj.name)):
                raise ValueError("A visibility string is shared with an unselected field; refusing to change that field.")
    except ValueError as exc:
        raise ValueError(f"{prefab_path}: {exc}") from exc
    result.data = rewritten
    return result


def _isolated_stem(planner, part, stem, postfix, mapping):
    if not matching_postfixes(postfix, stem):
        return stem
    # Variant identities also name meshes and dye records. Their allocator has
    # already checked those identities; do not silently change them here.
    if planner.variant_plan is not None:
        raise ValueError(f"Generated variant {stem} matches an existing hide suffix; choose another item name.")
    taken = set(planner.snapshot.pappt.index()) | set(mapping.values())
    digest = hashlib.sha256(part.prefab_path.encode()).hexdigest()[:8]
    for attempt in range(1000):
        planner.check()
        candidate = f"{stem[:44]}_bv{digest}_{attempt}"
        if (candidate not in taken and stringinfo_key(candidate) not in planner.snapshot.stringinfo_texts
                and not planner.snapshot.has_entry(part.record.cloned(candidate).prefab_path)
                and not matching_postfixes(postfix, candidate)):
            return candidate
    raise ValueError(f"No isolated equipment visibility identity is available for {part.prefab_path}.")


def prepare_body_visibility(planner):
    """Resolve exact components before the planner publishes identities or files."""
    if not planner.clones_model:
        return None
    by_prefab = {}
    # Explicit choices only: whole-part (postfix) rules are shared by a prefab's
    # bindings, so a hidden companion must not change its visible siblings' rules.
    explicit = {}
    hidden = {}
    if planner.variant_plan is not None:
        from cdmw.services.new_item_skinning import is_hidden_variant_result

        models = {(_key(prefab), _key(model)): result
                  for (prefab, model), result in dict(getattr(planner, "variant_models", None) or {}).items()}
        for variant in planner.variant_plan.settings:
            identity = (_key(variant.prefab_path), _key(variant.model_path))
            # A component hidden in export draws nothing, so its geometry-cut
            # rule must not keep cutting the body (or hair) where it used to be.
            is_hidden = bool(variant.custom_model) and is_hidden_variant_result(models.get(identity))
            choice = variant.body_visibility
            if is_hidden:
                hidden.setdefault(identity[0], set()).add(identity[1])
                choice = BodyVisibilityChoice(True, True)
            if variant.body_visibility.wanted:
                explicit.setdefault(identity[0], {})[identity[1]] = variant.body_visibility
            if choice.wanted:
                by_prefab.setdefault(identity[0], {})[identity[1]] = choice
    elif planner.spec.body_visibility.wanted:
        for part in planner.family.owned_parts:
            if part.record is not None:
                by_prefab[_key(part.prefab_path)] = {_key(path): planner.spec.body_visibility for path in part.pac_paths}
                explicit[_key(part.prefab_path)] = dict(by_prefab[_key(part.prefab_path)])
    snapshot = planner.snapshot
    # Ordinary appearance copies also need their original whole-part rules:
    # variant naming drops suffixes such as _D. Otherwise the experiment's off
    # state already changes hair visibility, making the A/B comparison invalid.
    if not by_prefab and not snapshot.has_entry(POSTFIX_PATH):
        return None
    postfix = snapshot.payload(POSTFIX_PATH)
    shrink = snapshot.payload(SHRINK_PATH) if by_prefab else b""
    known = shrink_rule_names(shrink) if by_prefab else frozenset()
    plan = BodyVisibilityPlan(stem_map=dict(planner.owned_stem_map()))
    profiles, requests, records = [], [], []
    profile_tags = {}
    rule_receivers = rule_receivers_reader(shrink)
    cut_layers_seen = set()
    for part in planner.family.parts:
        if part.stem not in plan.stem_map:
            continue
        selected = by_prefab.get(_key(part.prefab_path), {})
        inherited = matching_postfixes(postfix, part.stem)
        output_stem = plan.stem_map[part.stem]
        if not selected and inherited == matching_postfixes(postfix, output_stem):
            continue
        planner.check()
        output_stem = _isolated_stem(planner, part, output_stem, postfix, plan.stem_map)
        plan.stem_map[part.stem] = output_stem
        chosen = explicit.get(_key(part.prefab_path), {})
        automatic = hidden.get(_key(part.prefab_path), set())
        # Whole-part (postfix) rules follow explicit choices only: a hidden companion
        # must not change its visible siblings' rules.
        combined = BodyVisibilityChoice.combine(chosen.values())
        requests.append((part.stem, output_stem, combined))
        if not selected:
            records.append({"source_prefab": part.prefab_path, "output_prefab": part.record.cloned(output_stem).prefab_path,
                            "bindings": [], "whole_part_keep_skin": False, "whole_part_keep_hair": False,
                            "components": [], "inherited_postfixes": list(inherited)})
            continue
        def allocate(old, choice, output_stem=output_stem):
            key = (output_stem, old, choice)
            if key not in profile_tags:
                profile_tags[key] = _profile_tag(output_stem, old, choice, known, profiles)
            return profile_tags[key]

        retag = retag_prefab_components(part.prefab_path, snapshot.payload(part.prefab_path), selected, known,
                                        allocate, profiles, rule_receivers,
                                        hidden=frozenset(automatic), explicit=frozenset(chosen))
        cut_layers_seen |= retag.cut
        planner.warnings.extend(retag.warnings)
        plan.prefabs[_key(part.prefab_path)] = retag.data
        records.append({"source_prefab": part.prefab_path, "output_prefab": part.record.cloned(output_stem).prefab_path,
                        "bindings": [{**_binding_record(path, choice), "hidden_in_export": path in automatic,
                                      "explicit": path in chosen} for path, choice in selected.items()],
                        "whole_part_keep_skin": combined.keep_skin, "whole_part_keep_hair": combined.keep_hair,
                        "components": retag.details, "inherited_postfixes": list(inherited)})
        layers = f", layers kept underneath: {', '.join(sorted(combined.keep_receivers))}" if combined.keep_receivers else ""
        planner.summary.append(f"Experimental visibility: {output_stem}; "
                               f"keep skin/head {'on' if combined.keep_skin else 'off'}, hair/beard {'on' if combined.keep_hair else 'off'}{layers}")
        if automatic:
            planner.summary.append(f"Hidden in export: {len(automatic)} component(s) of {output_stem} "
                                   "no longer cut the body, hair or clothing underneath")

    requested = frozenset().union(*(c.keep_receivers for choices in by_prefab.values() for c in choices.values()))
    planner.warnings.extend(unlisted_layer_warnings(requested, cut_layers_seen))
    changed_shrink = clone_shrink_rules(shrink, tuple(profiles))
    changed_postfix = clone_postfix_rules(postfix, tuple(requests))
    if changed_shrink != shrink:
        planner.patch(snapshot.entry(SHRINK_PATH), changed_shrink, f"Equipment shrink rules: {len(profiles)} item-owned experimental profile(s)")
    if changed_postfix != postfix:
        planner.patch(snapshot.entry(POSTFIX_PATH), changed_postfix, "Equipment hide rules: isolated copies for this item's prefabs")
    if explicit and not profiles and changed_postfix == postfix:
        raise ValueError("The selected equipment has no supported shrink or postfix rules to override.")
    if planner.variant_plan is not None:
        planner.variant_plan.stem_map.update(plan.stem_map)
    if records:
        planner.manifest["body_visibility"] = {"experimental": bool(by_prefab), "prefabs": records,
                                              "hidden_components": sum(len(paths) for paths in hidden.values()),
                                              "profiles": [profile_record(p) for p in profiles]}
    if by_prefab:
        planner.warnings.extend((
            "Underlying parts is experimental and needs in-game A/B testing. The preview does not simulate these rules; "
            "other equipment, cut volumes or missing body geometry can still hide skin or hair.",
            "Whole-part skin/hair hiding is shared by all mesh bindings in a prefab. Those choices are combined for that prefab.",
        ))
    if changed_shrink != shrink or changed_postfix != postfix:
        planner.warnings.append(
            "This item changes shared equipment descriptors. To combine several custom items, use the previous exported mod as the base; "
            "independently exported copies of these descriptors can overwrite each other's rules.")
    return plan
