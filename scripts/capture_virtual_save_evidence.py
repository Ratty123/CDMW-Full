"""Capture copied saves and a prepared virtual context; never launch or edit a game."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.domain.virtual_save_evidence import STAGES, compare
from cdmw.services.virtual_loader_save_evidence import capture, inspect_capture_lineage, read_capture
from cdmw.services.virtual_save_experiment_protocol import (
    inspect_receipt_file, prepare_experiment, retain_attempt,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    make = commands.add_parser('capture', help='Read an explicitly named save copy and game/profile context.')
    make.add_argument('--game-root', type=Path, required=True)
    make.add_argument('--save-copy', type=Path, required=True)
    make.add_argument('--output', type=Path, required=True)
    make.add_argument('--stage', choices=STAGES, required=True)
    make.add_argument('--outcome', choices=('prepared', 'loaded', 'saved', 'reported-saved', 'failed', 'unknown'), required=True)
    make.add_argument('--notes', required=True, help='Observed objects/state; user report, not machine validation.')
    make.add_argument('--provider', help='32-character package UUID, required for the baseline.')
    make.add_argument('--slot', action='append', default=[], help='Relative save file, required for the baseline; repeat for multi-file slots.')
    make.add_argument('--previous', type=Path, help='Previous stage capture, required after the baseline.')
    make.add_argument('--protocol', type=Path, help='Bind copied inputs and pre-load identities to a prepared experiment.')
    prepare = commands.add_parser('prepare-experiment', help='Prepare six capture commands from explicit disposable copies; no live operations.')
    for name in ('game-root', 'save-copy', 'original-copy', 'post-attempt-copy', 'output'):
        prepare.add_argument('--' + name, type=Path, required=True)
    prepare.add_argument('--provider', required=True, help='Exact baseline provider package UUID.')
    prepare.add_argument('--slot', action='append', required=True, help='Selected relative copied-save member; repeat for each member.')
    prepare.add_argument('--backup-manifest', type=Path, help='Optional retained CDMW backup manifest; its live source is never read.')
    prepare.add_argument('--backup-sha256', help='Exact SHA-256 of the optional backup manifest.')
    retain = commands.add_parser('retain-attempt', help='Retain the exact copied absent_saved files in a new protocol-pinned folder.')
    retain.add_argument('--protocol', type=Path, required=True)
    retain.add_argument('--capture', type=Path, required=True)
    receipt = commands.add_parser('inspect-receipt', help='Inspect a local session receipt without granting producer or save-admission authority.')
    receipt.add_argument('receipt', type=Path)
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
        elif args.command == 'inspect-receipt':
            result = inspect_receipt_file(args.receipt)
        elif args.command == 'prepare-experiment':
            value = prepare_experiment(args.game_root, args.save_copy, args.original_copy,
                args.post_attempt_copy, args.output, provider=args.provider, slots=args.slot,
                backup_manifest=args.backup_manifest, backup_sha256=args.backup_sha256)
            result = {'protocol': str(args.output), 'identity': value['identity'],
                      'unknowns': value['unknowns'], 'backup': value['backup'], 'checklist': value['commands']}
        elif args.command == 'retain-attempt':
            result = retain_attempt(args.protocol, args.capture)
        else:
            value = capture(args.game_root, args.save_copy, args.output, stage=args.stage,
                outcome='saved' if args.outcome == 'reported-saved' else args.outcome,
                notes=args.notes, provider=args.provider, slots=args.slot, previous=args.previous, protocol=args.protocol)
            result = {'capture': str(args.output), 'identity': value['identity'], 'stage': value['stage'], 'claims': value['claims']}
        print(json.dumps(result, indent=2))
    except (OSError, ValueError) as exc:
        parser.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
