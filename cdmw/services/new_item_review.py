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
