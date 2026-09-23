"""Prepare item-owned experimental visibility metadata; never writes archives."""
from dataclasses import dataclass, field
import hashlib

from cdmw.core.equipment_visibility import (
    POSTFIX_PATH, SHRINK_PATH, VisibilityProfile, clone_postfix_rules,
    clone_shrink_rules, matching_postfixes, shrink_rule_names,
)
from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.core.prefab_binary_edit import PrefabPathEdit, rewrite_prefab_paths_same_length
from cdmw.core.stringinfo_table import stringinfo_key
from cdmw.domain.new_item.body_visibility import BodyVisibilityChoice


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
    digest = hashlib.shake_256(f"{output_stem}|{source_tag}|{choice.keep_skin}|{choice.keep_hair}|{attempt}".encode())
    return "V" + digest.hexdigest(size)[:size - 1]


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
    if planner.variant_plan is not None:
        for variant in planner.variant_plan.settings:
            if variant.body_visibility.wanted:
                by_prefab.setdefault(_key(variant.prefab_path), {})[_key(variant.model_path)] = variant.body_visibility
    elif planner.spec.body_visibility.wanted:
        for part in planner.family.owned_parts:
            if part.record is not None:
                by_prefab[_key(part.prefab_path)] = {_key(path): planner.spec.body_visibility for path in part.pac_paths}
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
        combined = BodyVisibilityChoice(any(c.keep_skin for c in selected.values()), any(c.keep_hair for c in selected.values()))
        requests.append((part.stem, output_stem, combined))
        if not selected:
            records.append({"source_prefab": part.prefab_path, "output_prefab": part.record.cloned(output_stem).prefab_path,
                            "bindings": [], "whole_part_keep_skin": False, "whole_part_keep_hair": False,
                            "components": [], "inherited_postfixes": list(inherited)})
            continue
        source = snapshot.payload(part.prefab_path)
        doc = decode_prefab_binary(source)
        if not doc.walk_complete or doc.inferred_objects:
            raise ValueError(f"{part.prefab_path}: visibility requires a complete, unambiguous component decode.")
        edits, matched, details, expected_tags = [], set(), [], {}
        for object_index, obj in enumerate(doc.objects):
            if obj.component_type != "SkinnedMeshComponent":
                continue
            paths = [value.text for name, value in obj.values if name in {"_skinnedMeshFile", "_skinnedMeshFileName"}]
            paths = {_key(path) for path in paths}
            targets = paths & selected.keys()
            if not targets:
                continue
            if len(paths) != 1:
                raise ValueError(f"{part.prefab_path}: component {obj.name} has ambiguous mesh bindings.")
            path = next(iter(targets))
            matched.add(path)
            choice = selected[path]
            tags = [value for name, value in obj.values if name == "_shrinkTag"]
            if len(tags) > 1:
                raise ValueError(f"{part.prefab_path}: component {obj.name} has ambiguous shrink tags.")
            old = tags[0].text if tags else ""
            if old not in known:
                planner.warnings.append(f"Experimental visibility: {part.prefab_path}, {obj.name} has "
                                        f"{'an unknown shrink tag ' + repr(old) if old else 'no explicit shrink tag'}; "
                                        "its geometry-cut rule is unchanged. Only applicable whole-part hide rules can be adjusted.")
                details.append({"component": obj.name, "source_tag": old, "profile": None, "model_path": path})
                continue
            key = (output_stem, old, choice)
            if key not in profile_tags:
                profile_tags[key] = _profile_tag(output_stem, old, choice, known, profiles)
            tag = profile_tags[key]
            profile = VisibilityProfile(old, tag, choice)
            if profile not in profiles:
                profiles.append(profile)
            edits.append(PrefabPathEdit(tags[0].offset, old, tag))
            expected_tags[object_index] = tag
            details.append({"component": obj.name, "source_tag": old, "profile": tag, "model_path": path})
        missing = selected.keys() - matched
        if missing:
            raise ValueError(f"{part.prefab_path}: no exact SkinnedMeshComponent for visibility selection: {', '.join(sorted(missing))}.")
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
            plan.prefabs[_key(part.prefab_path)] = rewritten
        except ValueError as exc:
            raise ValueError(f"{part.prefab_path}: {exc}") from exc
        records.append({"source_prefab": part.prefab_path, "output_prefab": part.record.cloned(output_stem).prefab_path,
                        "bindings": [{"model_path": path, "keep_skin": choice.keep_skin, "keep_hair": choice.keep_hair}
                                     for path, choice in selected.items()],
                        "whole_part_keep_skin": combined.keep_skin, "whole_part_keep_hair": combined.keep_hair,
                        "components": details, "inherited_postfixes": list(inherited)})
        planner.summary.append(f"Experimental visibility: {output_stem}; "
                               f"keep skin/head {'on' if combined.keep_skin else 'off'}, hair/beard {'on' if combined.keep_hair else 'off'}")

    changed_shrink = clone_shrink_rules(shrink, tuple(profiles))
    changed_postfix = clone_postfix_rules(postfix, tuple(requests))
    if changed_shrink != shrink:
        planner.patch(snapshot.entry(SHRINK_PATH), changed_shrink, f"Equipment shrink rules: {len(profiles)} item-owned experimental profile(s)")
    if changed_postfix != postfix:
        planner.patch(snapshot.entry(POSTFIX_PATH), changed_postfix, "Equipment hide rules: isolated copies for this item's prefabs")
    if by_prefab and not profiles and changed_postfix == postfix:
        raise ValueError("The selected equipment has no supported shrink or postfix rules to override.")
    if planner.variant_plan is not None:
        planner.variant_plan.stem_map.update(plan.stem_map)
    if records:
        planner.manifest["body_visibility"] = {"experimental": bool(by_prefab), "prefabs": records,
                                              "profiles": [{"source_tag": p.source_tag, "tag": p.tag,
                                                            "keep_skin": p.choice.keep_skin, "keep_hair": p.choice.keep_hair} for p in profiles]}
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
