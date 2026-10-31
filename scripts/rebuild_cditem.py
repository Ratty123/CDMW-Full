"""Rebuild .cditem packages written for an earlier game version against the installed game.

A package pins the exact game files its recipe read, so a game update makes it refuse.
Each package is planned again from its retained recipe and written beside the original
under --output with the same identity and title. Nothing in the game folder changes.
Only Create New Item packages can be rebuilt; field edits, stock overrides, texture
replacements and package links refuse. On a game with a DLC, a package the DLC changes
nothing in pins the base game alone, as Write item package does.
"""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.services.independent_item_dlc import portable_package
from cdmw.services.independent_item_package import (
    dlc_content, read_package, rebuild_for_game, stock_snapshot, write_package,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--game-root', type=Path, required=True, help='The Crimson Desert installation folder.')
    parser.add_argument('--output', type=Path, required=True, help='Folder for the rebuilt packages.')
    parser.add_argument('packages', type=Path, nargs='+')
    args = parser.parse_args(argv)
    if any(path.resolve().parent == args.output.resolve() for path in args.packages):
        parser.error('Write the rebuilt packages to another folder than the originals.')
    snapshot = stock_snapshot(args.game_root.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    results, failed = [], False
    for path in args.packages:
        try:
            package = read_package(path.read_bytes())
            rebuilt, needs = portable_package(rebuild_for_game(package, snapshot), args.game_root.resolve())
            write_package(rebuilt, args.output / path.name)
            changed = sorted(p for p, checksum in rebuilt.dependencies.items() if package.dependencies.get(p) != checksum)
            results.append({'package': str(path), 'identity': rebuilt.identity, 'rebuilt': str(args.output / path.name),
                            'changed_dependencies': len(changed), 'requires_dlc': list(dlc_content(rebuilt.dependencies)),
                            'changed_by_dlc': list(needs)})
        except (IndependentItemError, OSError, ValueError) as exc:
            failed = True
            results.append({'package': str(path), 'error': str(exc)})
    print(json.dumps(results, indent=2))
    return 2 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
