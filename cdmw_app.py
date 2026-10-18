#!/usr/bin/env python3
from __future__ import annotations

def main(argv=None):
    from cdmw.app.bootstrap import main as run

    return run(argv)


if __name__ == "__main__":
    # Dispatch frozen capture/guardian children before Qt or app startup. The
    # guardian must survive a lost parent long enough to release held input.
    from multiprocessing import freeze_support

    freeze_support()
    raise SystemExit(main())
