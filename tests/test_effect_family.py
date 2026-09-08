from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from cdmw.ui.new_item.effect_workspace_authoring import EffectWorkspaceAuthoringMixin


@pytest.mark.parametrize(
    ("stem", "family"),
    (
        ("", ""),
        ("FX_Fire", "fx_fire"),
        ("fx_fire_001", "fx_fire"),
        ("fx_fire-12A", "fx_fire"),
        ("fx_fire__a", "fx_fire"),
        ("fx_fire__12", "fx_fire"),
        ("fx_fire__1a", "fx_fire_"),
        ("fx_fire__12a", "fx_fire"),
        ("fx_fire_1a-2__b__003", "fx_fire"),
        ("fx_fire___1", "fx_fire_"),
        ("fx_fire_1ab", "fx_fire_1ab"),
        ("fx_fire_123!", "fx_fire_123!"),
        ("fx_fire_\u0661\u0662a", "fx_fire"),
        ("fx_fire_\u00b2a", "fx_fire_\u00b2a"),
        ("Stra\u00dfe_12", "strasse"),
        ("fx_fire_1\n", "fx_fire\n"),
        ("fx_fire_1\n\n", "fx_fire_1\n\n"),
    ),
)
def test_effect_family_preserves_variant_grouping(stem: str, family: str) -> None:
    assert EffectWorkspaceAuthoringMixin._effect_family(stem) == family


@pytest.mark.parametrize("pattern", ("0", "00__"))
def test_effect_family_handles_long_nonmatching_suffixes(pattern: str) -> None:
    # Bound the old exponential failure in a child so a regression cannot hang pytest.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; "
            "from cdmw.ui.new_item.effect_workspace_authoring import EffectWorkspaceAuthoringMixin as W; "
            "stem = '__' + sys.argv[1] * 10000 + '!'; "
            "assert W._effect_family(stem) == stem; "
            "assert W._effect_family('FX_FIRE' + '_01a' * 10000) == 'fx_fire'",
            pattern,
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
