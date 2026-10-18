"""Inspect CDITEM readiness or exercise an exact supported-launched game binding."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.services.cditem_device_cli import main


if __name__ == '__main__':
    raise SystemExit(main())
