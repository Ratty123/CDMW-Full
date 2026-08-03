"""The procedural warm-up triangle must never reach the screen.

`build_dotnet_preview_prewarm_package` builds a three-vertex procedural mesh
whose only job is to start the helper process, and tags it
`{"user_visible": False}`. Every reveal path in the helper already guards on
`--prewarm`, and every one of those guards held. The leak was on this side:
`serving_prewarm_placeholder` answered "no placeholder" as soon as the helper
applied a package, without asking *which* package -- and the package it applies
on a prewarm launch is the triangle. `_activate_applied` asks only for an
applied path, so it revealed it.
"""

import unittest
from types import SimpleNamespace


class _Controller:
    """The two attributes the property reads, and nothing else."""

    from cdmw.ui.preview.dotnet_session import DotNetPreviewSessionController

    serving_prewarm_placeholder = DotNetPreviewSessionController.serving_prewarm_placeholder

    def __init__(self, prewarm_dir: str | None, applied: str) -> None:
        self._prewarm_package = (
            SimpleNamespace(package_dir=prewarm_dir) if prewarm_dir is not None else None
        )
        self._applied_package_path = applied


class PrewarmPlaceholderTests(unittest.TestCase):
    def test_nothing_applied_yet_is_a_placeholder(self) -> None:
        self.assertTrue(_Controller("C:/cache/prewarm", "").serving_prewarm_placeholder)

    def test_the_applied_prewarm_package_is_still_a_placeholder(self) -> None:
        """The case that put a triangle in a fresh Mesh Editor."""

        controller = _Controller("C:/cache/prewarm", "C:/cache/prewarm")
        self.assertTrue(
            controller.serving_prewarm_placeholder,
            "an applied prewarm package reported itself as a real resident scene",
        )

    def test_a_real_package_is_not_a_placeholder(self) -> None:
        controller = _Controller("C:/cache/prewarm", "C:/cache/sword_pac")
        self.assertFalse(controller.serving_prewarm_placeholder)

    def test_without_a_prewarm_there_is_no_placeholder(self) -> None:
        self.assertFalse(_Controller(None, "").serving_prewarm_placeholder)
        self.assertFalse(_Controller(None, "C:/cache/sword_pac").serving_prewarm_placeholder)


class ActivateAppliedGuardTests(unittest.TestCase):
    def test_activate_applied_refuses_to_reveal_the_placeholder(self) -> None:
        from cdmw.ui.preview.dotnet_session import DotNetPreviewSessionController

        sent: list[dict] = []
        controller = SimpleNamespace(
            _visible=True,
            _applied_package_path="C:/cache/prewarm",
            _prewarm_package=SimpleNamespace(package_dir="C:/cache/prewarm"),
            _applied_package=SimpleNamespace(material_signature="sig"),
            _send_json=lambda payload: sent.append(payload) or True,
        )
        controller.serving_prewarm_placeholder = (
            DotNetPreviewSessionController.serving_prewarm_placeholder.fget(controller)
        )
        activated = DotNetPreviewSessionController._activate_applied(controller)
        self.assertFalse(activated)
        self.assertEqual(sent, [], "an activate_request was sent for the warm-up triangle")

    def test_activate_applied_still_reveals_a_real_package(self) -> None:
        from cdmw.ui.preview.dotnet_session import DotNetPreviewSessionController

        activated: list[object] = []
        package = SimpleNamespace(material_signature="sig")
        controller = SimpleNamespace(
            _visible=True,
            _applied_package_path="C:/cache/sword_pac",
            _prewarm_package=SimpleNamespace(package_dir="C:/cache/prewarm"),
            _applied_package=package,
            _request_activation=lambda requested: activated.append(requested) or True,
        )
        controller.serving_prewarm_placeholder = (
            DotNetPreviewSessionController.serving_prewarm_placeholder.fget(controller)
        )
        self.assertTrue(DotNetPreviewSessionController._activate_applied(controller))
        self.assertEqual(activated, [package])


if __name__ == "__main__":
    unittest.main()
