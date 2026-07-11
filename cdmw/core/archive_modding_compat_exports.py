from __future__ import annotations

from cdmw.core.archive_modding_compat_exports_0 import ARCHIVE_MODDING_EXPORTS_0
from cdmw.core.archive_modding_compat_exports_1 import ARCHIVE_MODDING_EXPORTS_1
from cdmw.core.archive_modding_compat_exports_2 import ARCHIVE_MODDING_EXPORTS_2


ARCHIVE_MODDING_EXPORTS = {
    **ARCHIVE_MODDING_EXPORTS_0,
    **ARCHIVE_MODDING_EXPORTS_1,
    **ARCHIVE_MODDING_EXPORTS_2,
}

__all__ = ["ARCHIVE_MODDING_EXPORTS"]
