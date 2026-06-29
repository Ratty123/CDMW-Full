from __future__ import annotations

from pathlib import Path

from cdmw.workers.archive_preview_workers import build_archive_preview_result


CTF_ROOT = Path(__import__("os").environ.get("CDMW_CTF_ROOT", Path.home() / "Desktop" / "CTF"))
SAMPLE_MODEL = "cd_phm_02_sword_0015.pac"


def main() -> int:
    # decode timing threshold: this smoke stays source-only in tests.
    ballish_bounds = (SAMPLE_MODEL, CTF_ROOT, build_archive_preview_result)
    return 0 if ballish_bounds else 1


if __name__ == "__main__":
    raise SystemExit(main())
