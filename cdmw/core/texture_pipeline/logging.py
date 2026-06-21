from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from cdmw.models import JobResult


def write_csv_log(log_path: Path, results: Sequence[JobResult]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "original_dds",
                "png",
                "output_dir",
                "width",
                "height",
                "original_mips",
                "used_mips",
                "texconv_format",
                "status",
                "note",
            ],
        )
        writer.writeheader()
        for row in results:
            writer.writerow(asdict(row))
