"""Publish, inspect or smoke-test the launcher-independent CDMW profile.

update-runtime  Update CDMW's own installed runtime ASI to this build. Never replaces a foreign file.
publish         Let any launcher (Steam, DMM) load the applied profile. Hashes every source once.
withdraw        Stop launcher-independent loading. The applied profile is kept.
status          Show the runtime's report and trace from the most recent launch.
smoke           Launch through Steam, check the runtime's report and trace, close the game,
                and confirm the installation's index files are unchanged. No input is sent.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.services import virtual_loader_standalone as standalone

REPORTS = Path(__file__).resolve().parents[1] / 'workspace/reports/cditem-smoke'


def _parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--game-root', type=Path, required=True, help='The Crimson Desert installation folder.')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('update-runtime')
    commands.add_parser('publish')
    commands.add_parser('withdraw')
    status = commands.add_parser('status')
    status.add_argument('--rows', type=int, default=40, help='Trace rows to show.')
    smoke = commands.add_parser('smoke')
    smoke.add_argument('--hold', type=float, default=20.0, help='Seconds to keep the game open after the evidence arrives.')
    smoke.add_argument('--start-timeout', type=float, default=240.0)
    smoke.add_argument('--output', type=Path, help='Report path; defaults to workspace/reports/cditem-smoke.')
    return parser


def _run(args):
    root = args.game_root.resolve()
    if args.command == 'update-runtime':
        from cdmw.services.virtual_loader_runtime import apply_runtime_setup, prepare_runtime_setup
        plan = prepare_runtime_setup(root)
        if plan.previous is not None and not plan.owned:
            raise VirtualLoaderError('The installed runtime is not owned by CDMW. Set it up from CDMW instead.')
        return {'runtime_sha256': apply_runtime_setup(plan, confirmed=plan.previous is None)}
    if args.command == 'publish':
        result = standalone.publish_standalone(root, on_progress=lambda done, total, _text: print(
            f'\rChecking sources {done}/{total}', end='', file=sys.stderr, flush=True))
        print(file=sys.stderr)
        return {'published': str(result.path), 'generation': result.generation,
                'hashed_sources': result.hashed_sources, 'catalogue_sources': result.catalogue_sources}
    if args.command == 'withdraw':
        return {'withdrawn': standalone.withdraw_standalone(root)}
    if args.command == 'status':
        status = standalone.read_standalone_status(root)
        rows = standalone.read_standalone_trace(root)
        return {'published': standalone.standalone_published(root),
                'last_launch': None if status is None else json.loads(standalone.status_text(status)),
                'trace_rows': len(rows), 'redirected': sum(row.redirected for row in rows),
                'trace': [row.__dict__ for row in rows[:args.rows]]}
    from cdmw.services.virtual_loader_smoke import run_smoke
    report = run_smoke(root, start_timeout=args.start_timeout, hold=args.hold)
    output = args.output or REPORTS / (datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return {**report, 'report': str(output)}


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        result = _run(args)
    except (VirtualLoaderError, OSError, ValueError) as exc:
        print(json.dumps({'error': str(exc), 'error_type': type(exc).__name__}, indent=2))
        return 2
    print(json.dumps(result, indent=2))
    return 1 if result.get('verdict') == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
