"""Human-readable operation details from the authored New Item manifest."""


def authoring_review_lines(plan):
    manifest = plan.manifest
    lines = [f"Active table generation: {manifest.get('generation','legacy')}"]
    for name, table in manifest.get("tables",{}).items():
        lines.append(f"{name}: {table.get('payload_path','')} · {table.get('source_archive','')}")
    for variant in manifest.get("variants",()):
        lines.append(f"Variant: {variant['prefab_path']} → {variant.get('output_model',variant['model_path'])} · {variant['appearance']}")
    for dye in manifest.get("dyes",()):
        lines.append(f"Dye record {dye['key']}: {dye['model']}")
        lines.extend(f"  {part['name']} · RGB slots {part['slots']} · properties {part['property_overrides']}" for part in dye['submeshes'])
    for recipe in manifest.get("recipes",()):
        lines.append(f"Recipe {recipe['source_key']} → {recipe['key']} · tool {recipe['tool_key']} · knowledge {recipe['knowledge_key']}")
        lines.extend(f"  Input: {value}" for value in recipe['inputs']+recipe['group_inputs'])
        lines.extend(f"  Output: {value}" for value in recipe['outputs'])
    for route in manifest.get("reward_acquisitions",()):
        lines.append(f"Reward route: {route}")
    for route in manifest.get("shops",()):
        lines.append(f"Shop route: {route}")
    lines.append("Files replaced:")
    lines.extend(f"- {request.entry.path}" for request in plan.patches)
    return lines


def plan_review_content(plan, mode, labels, stop_event):
    from cdmw.domain.cancellation import raise_if_cancelled
    rows = []
    for request in plan.patches:
        raise_if_cancelled(stop_event)
        rows.append((request.entry.path, labels[0]))
    for path in plan.new_paths:
        raise_if_cancelled(stop_event)
        rows.append((path, labels[1]))
    if mode == "overlay":
        rows.extend((meta.path, labels[2]) for meta in plan.meta_files)
    lines = [f"Item {plan.spec.item_key} {plan.spec.internal_name} from template {plan.spec.template_key}"]
    if plan.spec.stem:
        lines.append(f"Model stem: {plan.spec.stem}")
    lines.append("")
    lines.extend(plan.summary_lines)
    lines.extend(authoring_review_lines(plan))
    if plan.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in plan.warnings)
    notes = [issue for issue in plan.issues if not issue.is_error]
    if notes:
        lines.append("")
        lines.extend(f"Note: {issue.message}" for issue in notes)
    lines.append("")
    lines.append(f"{len(plan.patches)} table file(s) replaced, {len(plan.additions)} new file(s):")
    lines.extend(f"- {path}" for path in plan.new_paths)
    raise_if_cancelled(stop_event)
    return tuple(rows), "\n".join(lines)
