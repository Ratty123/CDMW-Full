from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOTNET = ROOT / "tools/dotnet_mesh_editor_experiment"


def _read(name: str) -> str:
    return (DOTNET / name).read_text(encoding="utf-8")


class MeshHarnessVorticeProtocolTests(unittest.TestCase):




    def test_shared_python_controller_is_the_only_process_owner(self) -> None:
        source = (ROOT / "cdmw/ui/preview/dotnet_session.py").read_text(encoding="utf-8")

        self.assertIn("process.start()", source)
        self.assertIn("_package_event_is_current", source)
        self.assertNotIn("WM_COPYDATA", source)
        self.assertFalse((ROOT / "tools/mesh_harness/native_protocol.py").exists())



if __name__ == "__main__":
    unittest.main()
