"""Inspect CDITEM readiness or capture a previously supported-launched game."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.services.cditem_device_runner import RunJournal, inspect_device_context, replay_policy
from cdmw.services.virtual_loader_state import decode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-root', type=Path, help='Exact existing installation; default mode is read-only inspection.')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('inspect', help='Read current readiness; never start a game or send input.')
    replay = commands.add_parser('replay', help='Replay synthetic policy observations without a Windows driver.')
    replay.add_argument('input', type=Path)
    report = commands.add_parser('report', help='Read an existing run journal; no recovery or input.')
    report.add_argument('directory', type=Path)
    report.add_argument('--run-id', required=True)
    for name in ('preflight', 'execute', 'resume', 'cancel'):
        command = commands.add_parser(name, help=(
            'Reconcile an exact existing game binding without input.' if name == 'preflight' else
            'Cancel one fully reconciled execution without input or closing the game.' if name == 'cancel' else
            'Retain a fresh bound-game frame and pause; no classification provider is installed.'))
        command.add_argument('manifest', type=Path)
        command.add_argument('--manifest-sha256', required=True)
        if name == 'preflight':
            command.add_argument('--resume', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'replay':
            if args.input.stat().st_size > 4 * 1024 * 1024:
                raise ValueError('The policy replay exceeds its size limit.')
            result = replay_policy(decode(args.input.read_bytes(), limit=4 * 1024 * 1024))
        elif args.command == 'report':
            result = RunJournal(args.directory, run_id=args.run_id).value
        elif args.command in ('preflight', 'execute', 'resume', 'cancel'):
            from cdmw.services.cditem_device_execution import cancel_execution, execute_execution, preflight_execution
            reference = {'path': str(args.manifest), 'sha256': args.manifest_sha256}
            if args.command == 'preflight':
                result = preflight_execution(reference, resume=args.resume)
            elif args.command == 'cancel':
                result = cancel_execution(reference)
            else:
                result = execute_execution(reference, resume=args.command == 'resume')
        else:
            if args.game_root is None:
                parser.error('--game-root is required for read-only device inspection.')
            result = inspect_device_context(args.game_root)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
