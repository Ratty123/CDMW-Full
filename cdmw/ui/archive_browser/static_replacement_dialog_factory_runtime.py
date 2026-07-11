from __future__ import annotations

from types import SimpleNamespace


def run_static_replacement_factory(context, module_globals, global_names, steps):
    state = SimpleNamespace(
        context=context,
        _factory_globals=module_globals,
        _factory_result_values={},
    )
    for name in global_names:
        if name in module_globals:
            setattr(state, name, module_globals[name])
    for step in steps:
        step(state)
    return SimpleNamespace(**state._factory_result_values)
