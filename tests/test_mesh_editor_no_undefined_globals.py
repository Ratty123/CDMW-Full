"""No Mesh Editor code path may look up a global that does not exist.

Three of these shipped, and each one only failed when a user clicked:

- `normalize_mesh_preview_display_mode` in the Edit Mesh geometry preview, which
  raised out of the viewport display-mode handler on every mode change;
- `_int_list` in the native payload reader, left behind on the core facade by
  the module split, on the JSON fallback path for source vertex maps;
- `_selected_original_index_from_tree` in the original-parts clipboard factory,
  which the caller does put in the context and the factory never read out.

None was caught by an import, a type checker or a test, because a name only has
to exist at the moment the line runs. This asks the interpreter directly: every
`LOAD_GLOBAL` a compiled function will perform is a name that must be resolvable
from the module's own namespace or from builtins. A hit is a guaranteed
`NameError` for whoever reaches that branch first.
"""

import builtins
import importlib
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Mesh Editor, Edit Mesh and everything they reach directly.
SURFACE_PATTERNS = (
    "cdmw/ui/mesh_editor/*.py",
    "cdmw/ui/archive_browser/static_replacement*.py",
    "cdmw/ui/preview/dotnet_*.py",
    "cdmw/services/mesh_*.py",
    "cdmw/modding/mesh_*.py",
)

# Names a module legitimately expects to be supplied from outside its own
# namespace. Keep this empty unless there is a real injection site to point at.
ALLOWED_INJECTED: dict[str, frozenset[str]] = {}


def _surface_modules() -> list[str]:
    modules: list[str] = []
    for pattern in SURFACE_PATTERNS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            if path.name == "__init__.py":
                continue
            modules.append(path.relative_to(REPO_ROOT).as_posix()[:-3].replace("/", "."))
    return modules


def _code_objects(code: types.CodeType) -> list[types.CodeType]:
    found = [code]
    for constant in code.co_consts:
        if isinstance(constant, types.CodeType):
            found.extend(_code_objects(constant))
    return found


def _global_loads(module: types.ModuleType) -> set[str]:
    """Every global name a function *defined here* will look up at runtime.

    A function imported into this module resolves its globals against the module
    that defined it, so including those would report names that are perfectly
    resolvable where they actually run. `__module__` is the filter, and it also
    drops the compiler-generated members of dataclasses and enums.
    """

    names: set[str] = set()
    own = module.__name__
    # Compiler-generated members -- a dataclass __repr__, an enum accessor --
    # claim this module but carry the globals of the machinery that built them,
    # so the source file is the discriminator rather than __module__ alone.
    own_file = getattr(module, "__file__", None)

    def _is_defined_here(value: object) -> bool:
        code = getattr(value, "__code__", None)
        if code is None or getattr(value, "__module__", None) != own:
            return False
        return own_file is not None and Path(code.co_filename) == Path(own_file)

    for value in vars(module).values():
        if isinstance(value, type):
            if getattr(value, "__module__", None) != own:
                continue
            for attribute in vars(value).values():
                if _is_defined_here(attribute):
                    names.update(_names_from(attribute.__code__))
            continue
        if _is_defined_here(value):
            names.update(_names_from(value.__code__))
    return names


def _names_from(code: types.CodeType) -> set[str]:
    import dis

    names: set[str] = set()
    for block in _code_objects(code):
        for instruction in dis.get_instructions(block):
            if instruction.opname == "LOAD_GLOBAL" and isinstance(instruction.argval, str):
                names.add(instruction.argval)
    return names


class MeshEditorUndefinedGlobalTests(unittest.TestCase):
    def test_the_surface_is_not_empty(self) -> None:
        """A pattern that stops matching would make this pass vacuously."""

        modules = _surface_modules()
        self.assertGreater(len(modules), 250, "the Mesh Editor surface stopped being enumerated")
        self.assertIn("cdmw.ui.mesh_editor.tab_state", modules)
        self.assertIn("cdmw.services.mesh_service", modules)

    def test_every_global_a_mesh_editor_function_loads_exists(self) -> None:
        missing: list[str] = []
        for module_name in _surface_modules():
            module = importlib.import_module(module_name)
            allowed = ALLOWED_INJECTED.get(module_name, frozenset())
            for name in sorted(_global_loads(module)):
                if name in allowed or hasattr(module, name) or hasattr(builtins, name):
                    continue
                missing.append(f"{module_name}: {name}")
        self.assertEqual(
            missing,
            [],
            "these names are looked up at runtime and do not exist; each is a "
            "NameError waiting for whoever reaches that branch first:\n  "
            + "\n  ".join(missing),
        )


if __name__ == "__main__":
    unittest.main()
