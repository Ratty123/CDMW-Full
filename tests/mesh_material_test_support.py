"""Synthetic mesh shared by current material and preview tests."""

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


def _mesh() -> ParsedMesh:
    return ParsedMesh(
        path="character/body.pac",
        format="pac",
        submeshes=[
            SubMesh(
                name="body",
                material="skin",
                texture="skin.dds",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                normals=[(0.0, 0.0, 1.0)] * 3,
                faces=[(0, 1, 2)],
                source_vertex_map=[0, 1, 2],
                source_index_count=3,
            )
        ],
        total_vertices=3,
        total_faces=1,
        has_uvs=True,
    )
