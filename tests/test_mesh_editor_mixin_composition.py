"""The tab mixins have to be self-sufficient, not rescued by composition order.

This codebase resolves most cross-module wiring at runtime, so a mixin calling a
method it does not declare a dependency on fails when a user clicks, not when a
test imports. Splitting the role helpers and the shared session bookkeeping out
of their original modules created exactly that risk: several mixins called into
them and resolved only because `MeshEditorTab` happens to compose everything.

These guards are cheap and they fail at import time, which is the whole point.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_every_mixin_that_uses_the_session_helpers_declares_them() -> None:
    """The coupling this guards against fails at a click, not at an import.

    Each of these mixins calls into the shared session bookkeeping. They used to
    resolve only because `MeshEditorTab` composes all of them, so a host that
    took one without the others would have failed at runtime on a path no test
    reaches.
    """
    from cdmw.ui.mesh_editor.tab_dotnet_capture import MeshEditorDotNetCaptureMixin
    from cdmw.ui.mesh_editor.tab_dotnet_lifecycle import MeshEditorDotNetLifecycleMixin
    from cdmw.ui.mesh_editor.tab_dotnet_material_compilation import (
        MeshEditorDotNetMaterialCompilationMixin,
    )
    from cdmw.ui.mesh_editor.tab_dotnet_process import MeshEditorDotNetProcessMixin
    from cdmw.ui.mesh_editor.tab_dotnet_provenance import MeshEditorDotNetProvenanceMixin
    from cdmw.ui.mesh_editor.tab_shell import MeshEditorTabShellMixin

    required = {
        MeshEditorDotNetMaterialCompilationMixin: (
            "_dotnet_material_roles_for_generation",
            "_dotnet_material_role_key",
            "_dotnet_material_role_label",
            "_record_dotnet_material_publication",
        ),
        MeshEditorDotNetCaptureMixin: ("_dotnet_material_roles_for_generation",),
        MeshEditorDotNetProvenanceMixin: ("_dotnet_material_roles_for_generation",),
        MeshEditorDotNetLifecycleMixin: (
            "_edit_session_transition",
            "_require_edit_session_recovery",
        ),
        MeshEditorDotNetProcessMixin: (
            "_require_edit_session_recovery",
            "_edit_session_generation",
        ),
        MeshEditorTabShellMixin: ("_record_dotnet_material_publication",),
    }
    for mixin, names in required.items():
        missing = [name for name in names if not hasattr(mixin, name)]
        assert missing == [], (mixin.__name__, missing)


def test_the_shared_helpers_have_exactly_one_definition_site() -> None:
    """Two copies drift; the tab has to resolve each of these to one place."""
    from cdmw.ui.mesh_editor import MeshEditorTab

    for name in (
        "_edit_session_machine",
        "_edit_session_generation",
        "_edit_session_transition",
        "_require_edit_session_recovery",
        "_observe_edit_session_from_scene_frame",
        "_record_dotnet_material_publication",
        "_dotnet_material_roles_for_generation",
    ):
        owners = [cls.__name__ for cls in MeshEditorTab.__mro__ if name in cls.__dict__]
        assert len(owners) == 1, (name, owners)
