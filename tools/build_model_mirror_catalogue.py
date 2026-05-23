from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.model_catalogue import (
    DEFAULT_MODEL_MIRROR_URL,
    build_mirror_catalogue_index,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local searchable metadata index for a static model mirror. "
            "This downloads +catalogue JSON metadata only; model archives are left for the user to download manually."
        )
    )
    parser.add_argument(
        "--mirror-url",
        required=True,
        help=f"Mirror root URL. Example: {DEFAULT_MODEL_MIRROR_URL}",
    )
    parser.add_argument("--output", default=str(REPO_ROOT / "model_catalogue"), help="Local catalogue folder.")
    parser.add_argument("--db-name", default="mirror_catalogue.sqlite", help="SQLite database filename.")
    parser.add_argument(
        "--max-shards",
        type=int,
        default=0,
        help="Limit catalogue pages for testing. Use 0 to index every page listed by +catalogue.",
    )
    parser.add_argument("--refresh-shards", action="store_true", help="Re-download catalogue JSON pages already stored locally.")
    args = parser.parse_args()

    def progress(_current: int, _total: int, message: str) -> None:
        print(message, flush=True)

    manifest = build_mirror_catalogue_index(
        mirror_url=args.mirror_url,
        output_dir=Path(args.output),
        db_name=args.db_name,
        max_shards=max(0, int(args.max_shards)),
        refresh_shards=bool(args.refresh_shards),
        on_progress=progress,
    )
    print()
    print(f"Database: {manifest['database']}")
    print(f"Model records: {manifest['models_in_database']:,}")
    print(f"Catalogue pages indexed: {manifest['shards_in_database']:,} / {manifest['total_catalogue_pages']:,}")
    print(f"Manual downloads folder: {manifest['downloads_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
