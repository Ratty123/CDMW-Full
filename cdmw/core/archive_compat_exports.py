from __future__ import annotations

from cdmw.core.archive_compat_exports_0 import ARCHIVE_EXPORTS_0
from cdmw.core.archive_compat_exports_1 import ARCHIVE_EXPORTS_1
from cdmw.core.archive_compat_exports_2 import ARCHIVE_EXPORTS_2
from cdmw.core.archive_compat_exports_3 import ARCHIVE_EXPORTS_3
from cdmw.core.archive_compat_exports_4 import ARCHIVE_EXPORTS_4


ARCHIVE_EXPORTS = {
    **ARCHIVE_EXPORTS_0,
    **ARCHIVE_EXPORTS_1,
    **ARCHIVE_EXPORTS_2,
    **ARCHIVE_EXPORTS_3,
    **ARCHIVE_EXPORTS_4,
}

__all__ = ["ARCHIVE_EXPORTS"]
