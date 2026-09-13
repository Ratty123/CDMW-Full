"""Read-only real hair handoff and additional-choice package roundtrip probe.

Prepare writes the Rust probe input. Run the ignored hair production test with
that input, then publish consumes its candidate through the production host and
immutable package writer. No game files are modified or installed.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
import threading
import tempfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import QSettings
from cdmw.core.pappt_format import parse_pappt
from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.modding.mesh_parser import parse_mesh
from cdmw.services.mesh_hair_output import export_hair_package
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession, _mesh_document_payload, _material_input_texture_role
from cdmw.services.mesh_rust_hair import setup_hair, apply_hair_candidate
from cdmw.services.mesh_service import MeshService
from tools.dotnet_archive_backend.probe_hair_registration import run, PART_PREFAB_TABLE


def probe(mode, stage, evidence):
    def execute(files, entries, get_file, mesh, game_root, output, stem):
        evidence.mkdir(parents=True, exist_ok=True)
        table = parse_pappt(files[PART_PREFAB_TABLE])

        def reference(stem):
            record = table.find(stem)
            if record is None:
                raise ValueError(f"Missing Damiane reference registration: {stem}")
            paths = [r.text.casefold() for r in decode_prefab_binary(get_file(record.prefab_path)).resource_strings()
                     if r.text.casefold().endswith('.pac') and Path(r.text).stem.casefold() == stem]
            if len(paths) != 1:
                raise ValueError(f"Reference has ambiguous meshes: {stem}: {paths}")
            data = get_file(paths[0])
            return SimpleNamespace(mesh=parse_mesh(data, paths[0]), original_data=data), entries[paths[0]]

        head, head_entry = reference('cd_phw_00_head_00_0111')
        body, body_entry = reference('cd_phw_00_nude_00_0001_damian')
        by_name, by_path = defaultdict(list), defaultdict(list)
        for path, entry in entries.items():
            by_name[Path(path).name].append(entry)
            by_path[path].append(entry)
        context = SimpleNamespace(entries_by_basename=by_name, entries_by_normalized_path=by_path)
        setattr(mesh, '_cdmw_original_data', files[mesh.path.casefold()])
        settings = QSettings(str(evidence / 'settings.ini'), QSettings.Format.IniFormat)
        authority = MeshService(settings=settings)
        view = authority.open_edit_session(mesh, session_id=f'hair-{mode}', mode='edit')
        root = Path(tempfile.mkdtemp(prefix=f'session-{stage}-', dir=evidence)) / 'session'
        authoring = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=authority, active_session_id=view.session_id),
                                                  root, process_generation=1)
        try:
            setup_hair(authoring, {'mode': mode, 'target_stem': stem, '_archive_snapshot': head, '_archive_entry': head_entry,
                '_body_snapshot': body, '_body_archive_entry': body_entry, '_target_entry': entries[mesh.path.casefold()],
                '_target_dependencies': context}, threading.Event())
            current = authoring.shadow_service._session(authoring.shadow_session_id)
            state = current.hair_state.payload
            if stage == 'prepare':
                from cdmw.core.archive_model_references import _extract_archive_model_sidecar_texture_references
                bindings, _, _, _ = _extract_archive_model_sidecar_texture_references(entries[mesh.path.casefold()], archive_entries_by_basename=by_name)
                textures=[]
                for binding in bindings:
                    path = binding.texture_path.casefold()
                    role = _material_input_texture_role(binding)
                    parts = [i for i,p in enumerate(mesh.submeshes) if p.name.casefold() == str(binding.material_name).casefold()]
                    if role == 'unknown': continue
                    if not parts or path not in entries: continue
                    textures.append({'path': str(entries[path].prepared_path), 'role': role, 'parts': parts})
                payload = {'hair': state, 'document': _mesh_document_payload(current.working_mesh), 'textures': textures}
                (evidence / 'input.json').write_text(json.dumps(payload), encoding='utf-8')
                print('Prepared Rust handoff:', evidence / 'input.json', flush=True)
            else:
                candidate = json.loads((evidence / 'candidate.json').read_text())
                # Recreated setup must be exactly the same source/reference transaction.
                if candidate['hair']['template'] != state['template']:
                    raise ValueError('The Rust candidate has a different donor or target.')
                apply_hair_candidate(authoring, candidate, 'Real authored hair proof')
                snapshot = authoring.shadow_service.capture_export_snapshot(authoring.shadow_session_id)
                rebuilt = authoring.shadow_service._replacement_output_for_snapshot(snapshot)
                export_hair_package(snapshot, rebuilt, entries[mesh.path.casefold()], output, on_log=print)
                result = parse_mesh(rebuilt.data, mesh.path)
                print(json.dumps({'package': str(output), 'original_vertices': sum(len(p.vertices) for p in mesh.submeshes),
                    'authored_vertices': sum(len(p.vertices) for p in result.submeshes), 'different_geometry': rebuilt.data != snapshot.original_data,
                    'sha256': hashlib.sha256(rebuilt.data).hexdigest(), 'game_verified': False}), flush=True)
        finally:
            authoring.cancel()
            authority.close_edit_session(view.session_id, force_without_saving=True)
    return execute


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-root', required=True, type=Path)
    parser.add_argument('--cache-root', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--mode', required=True, choices=('generated','existing'))
    parser.add_argument('--stage', required=True, choices=('prepare','publish'))
    parser.add_argument('--new-stem', required=True)
    args=parser.parse_args()
    run(args.package_root, args.evidence / 'package', args.cache_root, args.new_stem,
        authoring_probe=probe(args.mode,args.stage,args.evidence))
