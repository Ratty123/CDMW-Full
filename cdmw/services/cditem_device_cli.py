"""Development-only device commands shared by the script and portable app."""
from contextlib import contextmanager
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from cdmw.services import cditem_device_saves as saves
from cdmw.services.cditem_device_runner import RunJournal, inspect_device_context, replay_policy
from cdmw.services.independent_item_package import canonical
from cdmw.services.virtual_loader_state import decode


@contextmanager
def _result_file(path):
    """Check writable, new output before execution; publish without replacement."""
    if path is None:
        if sys.stdout is None:
            raise ValueError('The windowed executable requires --output before the device command.')
        yield None
        return
    path = saves._absolute(path)
    if path.suffix.lower() != '.json' or not path.parent.is_dir():
        raise ValueError('Device output requires a new absolute JSON path in an existing folder.')
    if path.exists():
        raise FileExistsError('The device result already exists; it must not be overwritten or replayed.')
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.pending', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as writer:
            def publish(value):
                writer.write(canonical(value))
                writer.flush()
                os.fsync(writer.fileno())
                writer.close()
                saves._absolute(path)
                # Windows rename refuses an existing destination. Elsewhere,
                # link publishes this staged report exclusively, then unlinks
                # only its temporary name. Existing evidence is never replaced.
                if os.name == 'nt':
                    temporary.rename(path)
                else:
                    os.link(temporary, path)
                    temporary.unlink()
            yield publish
    finally:
        temporary.unlink(missing_ok=True)


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-root', type=Path, help='Exact existing installation; inspection is read-only.')
    parser.add_argument('--output', type=Path, help='New absolute JSON result path; required by the windowed app.')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('inspect', help='Read readiness; never start a game or send input.')
    replay = commands.add_parser('replay', help='Replay synthetic policy observations without a Windows driver.')
    replay.add_argument('input', type=Path)
    report = commands.add_parser('report', help='Read an existing journal; no recovery or input.')
    report.add_argument('directory', type=Path)
    report.add_argument('--run-id', required=True)
    for name in ('preflight', 'execute', 'resume', 'cancel'):
        command = commands.add_parser(name, help=(
            'Reconcile an exact existing game binding without input.' if name == 'preflight' else
            'Cancel one reconciled execution without input or closing the game.' if name == 'cancel' else
            'Capture and pause, or match one explicitly reviewed frame before one policy action.'))
        command.add_argument('manifest', type=Path)
        command.add_argument('--manifest-sha256', required=True)
        if name == 'preflight':
            command.add_argument('--resume', action='store_true')
        if name in ('execute', 'resume'):
            command.add_argument('--review', type=Path, help='One inspected, immutable frame-review JSON.')
            command.add_argument('--review-sha256', help='Exact SHA-256 of that frame review.')
    return parser


def _run(args, review_evidence):
    if args.command == 'replay':
        if args.input.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('The policy replay exceeds its size limit.')
        return replay_policy(decode(args.input.read_bytes(), limit=4 * 1024 * 1024))
    if args.command == 'report':
        return RunJournal(args.directory, run_id=args.run_id).value
    if args.command in ('preflight', 'execute', 'resume', 'cancel'):
        from cdmw.services.cditem_device_execution import cancel_execution, execute_execution, preflight_execution
        reference = {'path': str(args.manifest), 'sha256': args.manifest_sha256}
        if args.command == 'preflight':
            return preflight_execution(reference, resume=args.resume)
        if args.command == 'cancel':
            return cancel_execution(reference)
        if (args.review is None) != (args.review_sha256 is None):
            raise ValueError('A frame review requires both --review and --review-sha256.')
        if args.review is None:
            return execute_execution(reference, resume=args.command == 'resume')
        from cdmw.services.cditem_device_review import ReviewedFrameObserver
        observer = ReviewedFrameObserver({'path': str(args.review), 'sha256': args.review_sha256}, reference)
        try:
            return execute_execution(reference, resume=args.command == 'resume', observer=observer, steps=2)
        finally:
            review_evidence.update(observer.evidence())
    if args.game_root is None:
        raise ValueError('--game-root is required for read-only device inspection.')
    return inspect_device_context(args.game_root)


def main(argv=None):
    args = _parser().parse_args(argv)
    result, code, review_evidence = None, 0, {}
    try:
        with _result_file(args.output) as publish:
            try:
                result = _run(args, review_evidence)
            except (OSError, ValueError, TypeError, EOFError, RuntimeError) as exc:
                result = {'format': 'cdmw_cditem_device_cli_error_v1', 'error': str(exc),
                          'error_type': type(exc).__name__,
                          'acceptance': 'not_established',
                          'detail': 'Retain the device journal; do not replay input to recreate a result file.'}
                code = 2
            if review_evidence:
                result = {**result, 'frame_review': review_evidence}
            if publish is not None:
                publish(result)
    except (OSError, ValueError, TypeError) as exc:
        if sys.stderr is not None:
            print(str(exc) + '\nRetain any device journal; do not replay input to recreate a result file.', file=sys.stderr)
        return 2
    if sys.stdout is not None:
        print(json.dumps(result, indent=2))
    return code
