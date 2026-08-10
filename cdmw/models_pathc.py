from dataclasses import dataclass


@dataclass
class PathcCollisionEntry:
    filename_offset: int
    texture_header_index: int
    unknown0: int
    compressed_block_infos: bytes
    path: str = ""


@dataclass
class PathcLookupResult:
    normalized_path: str
    checksum: int
    mapping_mode: str
    texture_header_index: int = -1
    header_size: int = 0
    compressed_block_infos: bytes = b""
    collision_path: str = ""
    message: str = ""


__all__ = ["PathcCollisionEntry", "PathcLookupResult"]
