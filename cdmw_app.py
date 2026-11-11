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
    # Everything CDMW writes stays in its own folder, temp files included;
    # children inherit the redirect. Before anything else can create a file.
    from cdmw.app.app_folder import AppFolderNotWritable, prepare_process_temp, report_unwritable_folder

    try:
        prepare_process_temp()
    except AppFolderNotWritable as error:
        report_unwritable_folder(error)
        raise SystemExit(3)
    raise SystemExit(main())
