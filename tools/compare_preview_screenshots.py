from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.rendering.preview_comparison import compare_preview_images, write_preview_comparison_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", type=Path, required=True)
    parser.add_argument("--item-icon", type=Path, default="")
    parser.add_argument("--in-game", type=Path, default="")
    parser.add_argument("--preview-roi", default="")
    parser.add_argument("--item-icon-roi", default="")
    parser.add_argument("--in-game-roi", default="")
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-csv", type=Path)
    args = parser.parse_args(argv)
    report = compare_preview_images(
        args.preview,
        item_icon_path=args.item_icon,
        in_game_path=args.in_game,
        preview_roi=args.preview_roi,
        item_icon_roi=args.item_icon_roi,
        in_game_roi=args.in_game_roi,
    )
    outputs = write_preview_comparison_report(report, json_path=args.out_json, csv_path=args.out_csv or "")
    print(json.dumps({"outputs": outputs}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
