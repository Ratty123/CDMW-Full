from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.rendering.native_preview_screenshot import capture_native_d3d11_preview_package
from cdmw.rendering.preview_comparison import compare_preview_images, write_preview_comparison_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare a D3D11 preview screenshot against item icon and in-game references.")
    parser.add_argument("--preview", default="", help="Preview screenshot path.")
    parser.add_argument("--preview-package", default="", help="Optional native D3D11 preview package directory to screenshot first.")
    parser.add_argument("--host", default="", help="Optional cdmw-d3d11-preview.exe path.")
    parser.add_argument("--item-icon", default="", help="Optional item icon reference path.")
    parser.add_argument("--in-game", default="", help="Optional in-game screenshot reference path.")
    parser.add_argument("--preview-roi", default="", help="Optional preview ROI as x,y,width,height.")
    parser.add_argument("--item-icon-roi", default="", help="Optional item icon ROI as x,y,width,height.")
    parser.add_argument("--in-game-roi", default="", help="Optional in-game ROI as x,y,width,height.")
    parser.add_argument("--out-json", required=True, help="Comparison report JSON path.")
    parser.add_argument("--out-csv", default="", help="Optional flat diagnostics CSV path.")
    parser.add_argument("--capture-timeout", type=float, default=12.0, help="Seconds to wait for a native preview first frame.")
    args = parser.parse_args(argv)

    if not args.preview and not args.preview_package:
        parser.error("--preview is required unless --preview-package is provided.")
    preview_path = (
        Path(args.preview)
        if args.preview
        else Path(args.out_json).with_name(Path(args.out_json).stem + "_preview.png")
    )
    capture_payload = {}
    if args.preview_package:
        capture_result = capture_native_d3d11_preview_package(
            args.preview_package,
            preview_path,
            host_path=args.host or None,
            timeout_s=args.capture_timeout,
        )
        capture_payload = capture_result.to_dict()
        if not capture_result.ok:
            output = {
                "outputs": {"json": str(Path(args.out_json)), "csv": str(Path(args.out_csv)) if args.out_csv else ""},
                "capture": capture_payload,
                "diagnostics": list(capture_result.diagnostics),
            }
            Path(args.out_json).write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
            print(json.dumps(output, indent=2))
            return 2
    report = compare_preview_images(
        preview_path,
        item_icon_path=Path(args.item_icon) if args.item_icon else "",
        in_game_path=Path(args.in_game) if args.in_game else "",
        preview_roi=args.preview_roi,
        item_icon_roi=args.item_icon_roi,
        in_game_roi=args.in_game_roi,
    )
    if capture_payload:
        report["native_preview_capture"] = capture_payload
    outputs = write_preview_comparison_report(report, json_path=args.out_json, csv_path=args.out_csv)
    print(json.dumps({"outputs": outputs, "capture": capture_payload, "diagnostics": report.get("diagnostics", [])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
