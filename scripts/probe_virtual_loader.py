"""Read-only PE loading leads and bounded native startup trace inspection.

Addresses reported here are research candidates, never callable registration APIs.
No process attachment, patching, game launch or archive writes are performed.
"""
import argparse
import hashlib
import json
import mmap
from pathlib import Path
import struct


def inspect_executable(path):
    import pefile
    pe = pefile.PE(str(path), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
    with path.open('rb') as handle:
        checksum = hashlib.file_digest(handle, 'sha256').hexdigest()
    result = {'executable_sha256': checksum,
              'size': path.stat().st_size, 'image_size': pe.OPTIONAL_HEADER.SizeOfImage,
              'entry_rva': pe.OPTIONAL_HEADER.AddressOfEntryPoint, 'imports': {}, 'strings': {}, 'lea_candidates': []}
    wanted_imports = {'CreateFileW', 'CreateFileA', 'CreateFile2', 'GetFileAttributesW', 'GetFileAttributesA',
                      'GetFileAttributesExW', 'FindFirstFileW', 'FindFirstFileExW', 'FindNextFileW',
                      'ReadFile', 'CreateFileMappingW', 'MapViewOfFile'}
    for descriptor in pe.DIRECTORY_ENTRY_IMPORT:
        for item in descriptor.imports:
            name = (item.name or b'').decode('ascii', errors='replace')
            if name in wanted_imports:
                result['imports'][name] = item.address - pe.OPTIONAL_HEADER.ImageBase
    wanted = (b'iteminfo\0', b'equiptypeinfo\0', b'gamedata/binarystaticinfo__/bin/\0',
              b'%s%s.staticinfobody\0', b'%s%s.%s.staticinfobody\0',
              b'%s%s.staticinfoheader\0', b'%s%s.%s.staticinfoheader\0')
    with path.open('rb') as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
        for needle in wanted:
            matches, at = [], 0
            while len(matches) < 32:
                at = data.find(needle, at)
                if at < 0:
                    break
                matches.append(pe.get_rva_from_offset(at))
                at += len(needle)
            result['strings'][needle.rstrip(b'\0').decode()] = matches
        targets = {rva for values in result['strings'].values() for rva in values}
        for section in pe.sections:
            if not section.Characteristics & 0x20000000:
                continue
            raw, base = section.get_data(), section.VirtualAddress
            for prefix in (b'\x48\x8d', b'\x4c\x8d'):
                at = 0
                while len(result['lea_candidates']) < 1024:
                    at = raw.find(prefix, at)
                    if at < 0:
                        break
                    if at + 7 <= len(raw) and raw[at + 2] & 0xc7 == 5:
                        target = base + at + 7 + struct.unpack_from('<i', raw, at + 3)[0]
                        if target in targets:
                            result['lea_candidates'].append({'rva': base + at, 'target': target})
                    at += 2
    pe.close()
    result['evidence'] = 'Static string/import leads only. LEA matches require instruction-boundary and caller verification. No registration ABI is established.'
    return result


def inspect_trace(path):
    row = struct.Struct('<IIIIq1024s')
    if path.stat().st_size > row.size * 4096 or path.stat().st_size % row.size:
        raise ValueError('Unsupported, truncated or oversized native trace.')
    names = {0: 'initialize', 1: 'CreateFileW', 2: 'CreateFile2', 3: 'CreateFileA', 4: 'GetFileAttributesW',
             5: 'GetFileAttributesExW', 6: 'GetFileAttributesA', 7: 'FindFirstFileW', 8: 'FindFirstFileExW',
             9: 'hook ownership changed', 10: 'verified bootstrap forwarding', 11: 'loader callout context',
             12: 'verified startup path', 13: 'file hooks ready'}
    events = []
    for kind, thread, redirected, error, ticks, raw in row.iter_unpack(path.read_bytes()):
        if kind not in names or redirected not in (0, 1):
            raise ValueError('Invalid native trace event.')
        text = raw.decode('utf-16le').split('\0', 1)[0]
        events.append({'operation': names[kind], 'thread': thread, 'redirected': bool(redirected), 'last_error': error,
                       'qpc': ticks, 'path': text, 'possibly_truncated': len(text) == 511})
    return {'events': events, 'limit_reached': len(events) == 4096,
            'evidence': 'Only calls after InitializeASI are observed. This trace alone does not prove that the first game-data read was intercepted, record acceptance, or save compatibility.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--executable', type=Path)
    source.add_argument('--trace', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect_executable(args.executable) if args.executable else inspect_trace(args.trace), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
