"""Capture copied saves and a prepared virtual context; never launch or edit a game."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.domain.virtual_save_evidence import STAGES, compare
from cdmw.services.virtual_loader_save_evidence import capture, inspect_capture_lineage, read_capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    make = commands.add_parser('capture', help='Read an explicitly named save copy and game/profile context.')
    make.add_argument('--game-root', type=Path, required=True)
    make.add_argument('--save-copy', type=Path, required=True)
    make.add_argument('--output', type=Path, required=True)
    make.add_argument('--stage', choices=STAGES, required=True)
    make.add_argument('--outcome', choices=('prepared', 'loaded', 'saved', 'failed', 'unknown'), required=True)
    make.add_argument('--notes', required=True, help='Observed objects/state; user report, not machine validation.')
    make.add_argument('--provider', help='32-character package UUID, required for the baseline.')
    make.add_argument('--slot', action='append', default=[], help='Relative save file, required for the baseline; repeat for multi-file slots.')
    make.add_argument('--previous', type=Path, help='Previous stage capture, required after the baseline.')
    inspect = commands.add_parser('compare', help='Check one ordered capture sequence; cannot certify save compatibility.')
    inspect.add_argument('captures', type=Path, nargs='+')
    lineage = commands.add_parser('lineage', help='Inspect a capture as unknown-origin evidence; does not authorize loading.')
    lineage.add_argument('capture', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'compare':
            result = compare([read_capture(path) for path in args.captures])
        elif args.command == 'lineage':
            result = inspect_capture_lineage(read_capture(args.capture))
        else:
            value = capture(args.game_root, args.save_copy, args.output, stage=args.stage,
                outcome=args.outcome, notes=args.notes, provider=args.provider, slots=args.slot, previous=args.previous)
            result = {'capture': str(args.output), 'identity': value['identity'], 'stage': value['stage'], 'claims': value['claims']}
        print(json.dumps(result, indent=2))
    except (OSError, ValueError) as exc:
        parser.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
