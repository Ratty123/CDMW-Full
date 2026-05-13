from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cdmw.modding.mesh_exporter import export_fbx_with_skeleton
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.skeleton_parser import Bone, Skeleton


class FbxExporterTests(unittest.TestCase):
    def test_skeleton_fbx_export_keeps_uv_layer_and_bone_sizes(self) -> None:
        mesh = ParsedMesh(
            path="character/test.pac",
            format="pac",
            submeshes=[
                SubMesh(
                    name="Body",
                    material="BodyMat",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                    normals=[(0.0, 0.0, 1.0)] * 3,
                    faces=[(0, 1, 2)],
                )
            ],
            total_vertices=3,
            total_faces=1,
            has_uvs=True,
        )
        skeleton = Skeleton(
            path="character/test.pab",
            bones=[
                Bone(index=0, name="Root", parent_index=-1, position=(0.0, 0.0, 0.0)),
                Bone(index=1, name="Child", parent_index=0, position=(0.0, 2.0, 0.0)),
            ],
            bone_count=2,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            fbx_path = Path(export_fbx_with_skeleton(mesh, skeleton, temp_dir, name="skinned"))
            payload = fbx_path.read_bytes()

        self.assertIn(b"LayerElementUV", payload)
        self.assertIn(b"UVMap", payload)
        self.assertIn(b"Size", payload)


if __name__ == "__main__":
    unittest.main()
