"""Small owned PAMT/PAZ inputs for the real character catalogue worker tests."""
from pathlib import Path
import struct


def write_character_archive(root: Path) -> None:
    package = root / "0009"
    package.mkdir(parents=True)
    payloads = [(f"character/model/1_pc/1_phm/nude/hero_body_{i:04}.pac", b"PAC\0synthetic") for i in range(85)]
    payloads += [
        ("character/model/1_pc/1_phm/head/hero_head_0001.pac", b"PAC\0head"),
        ("character/appearance/1_pc/1_phm/hero.app_xml", b'<Appearance><Nude Name="hero_body_0000"/><Head Name="hero_head_0001"/></Appearance>'),
        ("character/appearance/3_npc/shared.app_xml", b'<Appearance><Nude Name="hero_body_0000"/></Appearance>'),
        ("character/appearance/3_npc/unresolved.app_xml", b'<Appearance><Head Name="absent_head"/></Appearance>'),
        ("character/modelproperty/1_pc/1_phm/nude/hero_body_0000.pac_xml", b'<Header/><Material FileName="character/texture/skin.dds"/>'),
        ("character/texture/skin.dds", b"DDS synthetic"),
    ]
    names = bytearray()
    entries = []
    offset = 0
    with (package / "0.paz").open("xb") as paz:
        for path, data in payloads:
            encoded = path.encode()
            name_offset = len(names)
            names += struct.pack("<I", 0xFFFFFFFF) + bytes([len(encoded)]) + encoded
            paz.write(data)
            entries.append((name_offset, offset, len(data)))
            offset += len(data)
    pamt = bytearray(struct.pack("<7I", 0, 1, 0, 0, 0, 0, 0))
    pamt += struct.pack("<I", len(names)) + names + struct.pack("<II", 0, len(entries))
    for name, offset, size in entries:
        pamt += struct.pack("<IIIIHH", name, offset, size, size, 0, 0)
    (package / "0.pamt").write_bytes(pamt)
